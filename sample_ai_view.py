from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
import json
import uuid
from anthropic import Anthropic
from .models import ScriptProject, Character, Script, ScriptVersion, Scene, Job
from .serializers import (
    CharacterSerializer, ScriptSerializer, ScriptVersionSerializer, 
    SceneSerializer, JobSerializer, JobCreateSerializer,
    UserRegisterSerializer, UserLoginSerializer, UserSerializer
)
from .tasks import generate_script_task, generate_scene_task


@ensure_csrf_cookie
def index(request):
    """Main view for the script writing interface"""
    projects = ScriptProject.objects.all()
    return render(request, 'scriptwriter/index_pro.html', {'projects': projects})


def script_viewer(request):
    """View for displaying scripts in a formatted reader"""
    return render(request, 'scriptwriter/script_viewer.html')


def health_check(request):
    """Health check endpoint for monitoring"""
    return JsonResponse({'status': 'healthy', 'service': 'spielberg'})


# ============================================================================
# REST API ViewSets
# ============================================================================

class CharacterViewSet(viewsets.ModelViewSet):
    """ViewSet for managing characters"""
    serializer_class = CharacterSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return Character.objects.filter(user=self.request.user)


class ScriptViewSet(viewsets.ModelViewSet):
    """ViewSet for managing scripts"""
    serializer_class = ScriptSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return Script.objects.filter(user=self.request.user).prefetch_related('characters', 'versions')
    
    @action(detail=True, methods=['post'])
    def create_version(self, request, pk=None):
        """Create a new version for a script"""
        script = self.get_object()
        content = request.data.get('content', '')
        notes = request.data.get('notes', '')
        
        latest_version = script.get_latest_version()
        version_number = (latest_version.version_number + 1) if latest_version else 1
        
        version = ScriptVersion.objects.create(
            script=script,
            version_number=version_number,
            content=content,
            notes=notes
        )
        
        serializer = ScriptVersionSerializer(version)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        """Get all versions for a script"""
        script = self.get_object()
        versions = script.versions.all()
        serializer = ScriptVersionSerializer(versions, many=True)
        return Response(serializer.data)


class ScriptVersionViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing script versions"""
    serializer_class = ScriptVersionSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return ScriptVersion.objects.filter(script__user=self.request.user)
    
    @action(detail=True, methods=['post'])
    def create_scene(self, request, pk=None):
        """Create a new scene for a script version"""
        version = self.get_object()
        
        scene_data = request.data.copy()
        scene_data['script_version'] = version.id
        
        serializer = SceneSerializer(data=scene_data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SceneViewSet(viewsets.ModelViewSet):
    """ViewSet for managing scenes"""
    serializer_class = SceneSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return Scene.objects.filter(script_version__script__user=self.request.user)
    
    @action(detail=True, methods=['post'])
    def regenerate(self, request, pk=None):
        """Regenerate a scene using AI"""
        scene = self.get_object()
        prompt = request.data.get('prompt', 'Regenerate this scene with improvements.')
        
        # Create a job for scene regeneration
        job_id = str(uuid.uuid4())
        job = Job.objects.create(
            user=request.user,
            job_id=job_id,
            job_type='scene_generation',
            status='pending',
            prompt=prompt,
            scene=scene
        )
        
        # Enqueue Celery task
        generate_scene_task.delay(job_id, scene.id, prompt)
        
        serializer = JobSerializer(job)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)


class JobViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing job status"""
    serializer_class = JobSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return Job.objects.filter(user=self.request.user)
    
    @action(detail=True, methods=['get'])
    def status(self, request, pk=None):
        """Get the status of a job"""
        job = self.get_object()
        return Response({
            'job_id': job.job_id,
            'status': job.status,
            'created_at': job.created_at,
            'started_at': job.started_at,
            'completed_at': job.completed_at,
        })
    
    @action(detail=True, methods=['get'])
    def result(self, request, pk=None):
        """Get the result of a completed job"""
        job = self.get_object()
        
        if job.status == 'completed':
            return Response({
                'job_id': job.job_id,
                'status': job.status,
                'result': job.result,
            })
        elif job.status == 'failed':
            return Response({
                'job_id': job.job_id,
                'status': job.status,
                'error': job.error_message,
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response({
                'job_id': job.job_id,
                'status': job.status,
                'message': 'Job not yet completed',
            }, status=status.HTTP_202_ACCEPTED)


# ============================================================================
# Job Creation API
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_job(request):
    """Create a new async job for script generation"""
    serializer = JobCreateSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    job_type = data['job_type']
    prompt = data['prompt']
    script_id = data.get('script_id')
    scene_id = data.get('scene_id')
    script_type = data.get('script_type', 'screenplay')
    
    # Create job
    job_id = str(uuid.uuid4())
    job = Job.objects.create(
        user=request.user,
        job_id=job_id,
        job_type=job_type,
        status='pending',
        prompt=prompt,
        script_id=script_id,
        scene_id=scene_id
    )
    
    # Enqueue appropriate task
    if job_type == 'scene_generation' and scene_id:
        generate_scene_task.delay(job_id, scene_id, prompt)
    else:
        generate_script_task.delay(job_id, prompt, script_id, script_type)
    
    return Response({
        'job_id': job.job_id,
        'status': job.status,
        'message': 'Job created and queued for processing'
    }, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def job_status(request, job_id):
    """Get the status of a job by job_id"""
    try:
        job = Job.objects.get(job_id=job_id, user=request.user)
        serializer = JobSerializer(job)
        return Response(serializer.data)
    except Job.DoesNotExist:
        return Response({'error': 'Job not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def job_result(request, job_id):
    """Get the result of a completed job"""
    try:
        job = Job.objects.get(job_id=job_id, user=request.user)
        
        if job.status == 'completed':
            return Response({
                'job_id': job.job_id,
                'status': job.status,
                'result': job.result,
                'script': job.script.id if job.script else None,
            })
        elif job.status == 'failed':
            return Response({
                'job_id': job.job_id,
                'status': job.status,
                'error': job.error_message,
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response({
                'job_id': job.job_id,
                'status': job.status,
                'message': 'Job not yet completed',
            }, status=status.HTTP_202_ACCEPTED)
    except Job.DoesNotExist:
        return Response({'error': 'Job not found'}, status=status.HTTP_404_NOT_FOUND)


# ============================================================================
# Legacy API Endpoints (for backwards compatibility)
# ============================================================================

@require_http_methods(["POST"])
def generate_script(request):
    """Legacy API endpoint to generate script using Claude AI"""
    try:
        data = json.loads(request.body)
        api_key = data.get('api_key')
        prompt = data.get('prompt')
        script_type = data.get('script_type', 'screenplay')
        
        if not api_key or not prompt:
            return JsonResponse({
                'error': 'API key and prompt are required'
            }, status=400)
        
        # Initialize Claude AI client
        client = Anthropic(api_key=api_key)
        
        # System prompt for script writing
        system_prompt = get_script_writing_system_prompt(script_type)
        
        # Generate script using Claude
        message = client.messages.create(
            model="claude-opus-4-5-20251101",
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {"role": "user", "content": prompt}
            ],
            stream=False
        )

        print(f"Claude response: {message}")
        
        script_content = message.content[0].text
        
        return JsonResponse({
            'success': True,
            'script': script_content
        })
        
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)


@require_http_methods(["POST"])
def save_script(request):
    """Save a script project (legacy)"""
    try:
        data = json.loads(request.body)
        title = data.get('title')
        content = data.get('content')
        genre = data.get('genre', '')
        logline = data.get('logline', '')
        
        script = ScriptProject.objects.create(
            title=title,
            content=content,
            genre=genre,
            logline=logline
        )
        
        return JsonResponse({
            'success': True,
            'id': script.id
        })
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)


def get_script_writing_system_prompt(script_type):
    """Get the system prompt for script writing based on type"""
    
    base_prompt = """You are an expert screenwriter and script consultant with deep knowledge of storytelling, 
    character development, and screenplay formatting. You understand the principles of dramatic structure, 
    including the three-act structure, character arcs, and compelling dialogue."""
    
    if script_type == 'screenplay':
        return base_prompt + """

SCREENPLAY FORMAT RULES:
1. Use proper screenplay formatting with scene headings, action lines, character names, and dialogue
2. Scene headings: INT./EXT. LOCATION - TIME OF DAY (e.g., INT. COFFEE SHOP - DAY)
3. Action lines: Present tense, active voice, describing what we see and hear
4. Character names: ALL CAPS when they first appear and above dialogue
5. Dialogue: Character name centered, dialogue below
6. Parentheticals: Brief direction for how a line should be delivered
7. Transitions: FADE IN:, CUT TO:, FADE OUT: (use sparingly)

STORYTELLING PRINCIPLES:
- Strong opening hook that establishes the world and protagonist
- Clear character motivations and goals
- Rising tension and conflict
- Well-paced scenes with purpose
- Subtext in dialogue - show don\'t tell
- Visual storytelling over exposition
- Satisfying character arcs
- Three-act structure: Setup, Confrontation, Resolution

Generate professional, properly formatted screenplay content. Focus on vivid visual storytelling, 
authentic dialogue, and compelling character development."""
    
    elif script_type == 'treatment':
        return base_prompt + """

TREATMENT FORMAT:
- Write in present tense, third person
- Describe the story chronologically from beginning to end
- Include major plot points, character arcs, and turning points
- Paint a vivid picture of the story world
- Convey the tone and style of the piece
- No dialogue, just narrative description
- 3-5 pages for a short treatment, 10-30 for a full treatment

Focus on compelling story structure and emotional journey."""
    
    else:  # outline
        return base_prompt + """

OUTLINE FORMAT:
- Organized by acts and sequences
- Clear beat sheet of major story moments
- Character introductions and arc progressions
- Key plot points and turning points
- Theme development
- Conflict escalation

Structure:
ACT ONE: Setup
- Opening Image
- Inciting Incident
- First Plot Point

ACT TWO: Confrontation
- Rising Action
- Midpoint
- Complications
- Crisis

ACT THREE: Resolution
- Climax
- Falling Action
- Resolution
- Closing Image

Provide a comprehensive story outline with dramatic beats."""


# ============================================================================
# Authentication Views
# ============================================================================

@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    """Register a new user"""
    serializer = UserRegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        login(request, user)
        return Response({
            'message': 'User registered successfully',
            'user': UserSerializer(user).data
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def login_user(request):
    """Login user"""
    serializer = UserLoginSerializer(data=request.data)
    if serializer.is_valid():
        username = serializer.validated_data['username']
        password = serializer.validated_data['password']
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            return Response({
                'message': 'Login successful',
                'user': UserSerializer(user).data
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'error': 'Invalid username or password'
            }, status=status.HTTP_401_UNAUTHORIZED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_user(request):
    """Logout user"""
    logout(request)
    return Response({
        'message': 'Logout successful'
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_current_user(request):
    """Get current authenticated user"""
    return Response({
        'user': UserSerializer(request.user).data
    }, status=status.HTTP_200_OK)


def auth_page(request):
    """View for login/register page"""
    return render(request, 'scriptwriter/auth.html')

