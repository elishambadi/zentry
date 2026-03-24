
# core/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db.models import Q, Count, Prefetch
from django.template.loader import render_to_string
from datetime import date, datetime, timedelta
from django.utils import timezone
from decouple import config
import json
import calendar
from .models import (
    Task,
    JournalEntry,
    SubTask,
    Note,
    Link,
    Idea,
    Goal,
    TaskGoal,
    DailyMood,
    UserPreference,
    ZenChatSession,
    ZenChatMessage,
)
from .forms import (TaskForm, TaskEditForm, JournalForm, SubTaskForm, NoteForm, 
                    LinkForm, IdeaForm, GoalForm, DailyMoodForm, UserPreferenceForm)

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


def get_or_create_user_preferences(user):
    preferences, _ = UserPreference.objects.get_or_create(user=user)
    return preferences


def build_zen_context(user, section):
    today = date.today()
    start_week = today - timedelta(days=today.weekday())
    end_week = start_week + timedelta(days=6)

    recent_tasks = Task.objects.filter(user=user).order_by('-date', '-created_at')[:12]
    completed_recent = Task.objects.filter(user=user, completed=True).order_by('-date')[:8]
    active_goals = Goal.objects.filter(user=user, completed=False).order_by('-updated_at')[:8]
    recent_ideas = Idea.objects.filter(user=user).order_by('-updated_at')[:8]
    journals = JournalEntry.objects.filter(user=user).order_by('-date')[:5]

    weekly_tasks = Task.objects.filter(user=user, date__range=[start_week, end_week])
    weekly_total = weekly_tasks.count()
    weekly_completed = weekly_tasks.filter(completed=True).count()

    preferences = get_or_create_user_preferences(user)

    return {
        'section': section,
        'today': today.isoformat(),
        'weekly_summary': {
            'start': start_week.isoformat(),
            'end': end_week.isoformat(),
            'total_tasks': weekly_total,
            'completed_tasks': weekly_completed,
        },
        'recent_tasks': [
            {
                'title': task.title,
                'date': task.date.isoformat(),
                'tag': task.get_tag_display(),
                'priority': task.get_priority_display(),
                'completed': task.completed,
            }
            for task in recent_tasks
        ],
        'recent_completions': [
            {
                'title': task.title,
                'date': task.date.isoformat(),
                'tag': task.get_tag_display(),
            }
            for task in completed_recent
        ],
        'ideas': [
            {
                'title': idea.title,
                'description': idea.description,
                'converted_to_task': idea.converted_to_task,
            }
            for idea in recent_ideas
        ],
        'goals': [
            {
                'title': goal.title,
                'term': goal.get_term_display(),
                'target_date': goal.target_date.isoformat() if goal.target_date else None,
                'completed': goal.completed,
            }
            for goal in active_goals
        ],
        'journal_highlights': [journal.content[:300] for journal in journals if journal.content],
        'reading_context': {
            'monthly_books': preferences.monthly_books,
            'favorite_authors': preferences.favorite_authors,
        },
    }


def parse_zenai_json_response(raw_text):
    if not raw_text:
        return None

    text = raw_text.strip()
    if text.startswith('```json'):
        text = text[7:]
    elif text.startswith('```'):
        text = text[3:]
    if text.endswith('```'):
        text = text[:-3]

    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def normalize_suggested_tasks(items):
    if not isinstance(items, list):
        return []

    normalized = []
    valid_tags = {choice[0] for choice in Task.TAGS}
    valid_priorities = {choice[0] for choice in Task.PRIORITY_CHOICES}

    for item in items[:12]:
        if not isinstance(item, dict):
            continue
        title = (item.get('title') or '').strip()
        if not title:
            continue

        tag = (item.get('tag') or 'W').strip().upper()
        priority = (item.get('priority') or 'M').strip().upper()
        cadence = (item.get('cadence') or 'one-off').strip().lower()

        normalized.append({
            'title': title[:200],
            'why': (item.get('why') or '').strip(),
            'duration_minutes': int(item.get('duration_minutes') or 0) if str(item.get('duration_minutes') or '').isdigit() else 0,
            'cadence': cadence if cadence in {'daily', 'weekly', 'monthly', 'one-off'} else 'one-off',
            'frequency_detail': (item.get('frequency_detail') or '').strip(),
            'recommended_date': (item.get('recommended_date') or '').strip(),
            'tag': tag if tag in valid_tags else 'W',
            'priority': priority if priority in valid_priorities else 'M',
            'note': (item.get('note') or '').strip(),
        })

    return normalized


def build_fallback_zen_payload(context_data):
    return {
        'response_markdown': (
            "I narrowed this into one priority outcome and concrete next actions. "
            "Use the task cards below to add them directly to your plan."
        ),
        'focus_target': 'One measurable weekly outcome',
        'clarifying_questions': [
            'Which single outcome matters most this week?',
            'What constraints must we respect (time, energy, deadlines)?',
        ],
        'suggested_tasks': [
            {
                'title': 'Define one weekly outcome with metric',
                'why': 'Prevents focus drift and narrows decisions.',
                'duration_minutes': 20,
                'cadence': 'one-off',
                'frequency_detail': 'Today, once',
                'recommended_date': date.today().isoformat(),
                'tag': 'W',
                'priority': 'H',
                'note': 'Write: outcome, metric, deadline, and owner.',
            },
            {
                'title': 'Schedule two deep-work blocks',
                'why': 'Protects execution time for highest-value work.',
                'duration_minutes': 90,
                'cadence': 'weekly',
                'frequency_detail': '2 sessions/week',
                'recommended_date': date.today().isoformat(),
                'tag': 'W',
                'priority': 'H',
                'note': 'No meetings, no notifications.',
            },
        ],
    }


def build_setup_required_payload(missing_tasks, missing_goals):
    clarifying_questions = []
    suggested_tasks = []

    if missing_goals:
        clarifying_questions.append('What is one short-term or long-term goal you want to achieve next?')
        suggested_tasks.append({
            'title': 'Create one short-term goal with a target date',
            'why': 'ZenAI needs a concrete destination before optimizing your path.',
            'duration_minutes': 10,
            'cadence': 'one-off',
            'frequency_detail': 'Do this now',
            'recommended_date': date.today().isoformat(),
            'tag': 'W',
            'priority': 'H',
            'note': 'Example: Launch MVP landing page in 14 days.',
        })

    if missing_tasks:
        clarifying_questions.append('Which concrete tasks are you actively executing this week?')
        suggested_tasks.append({
            'title': 'Add three execution tasks tied to your top goal',
            'why': 'ZenAI can only optimize action plans when tasks exist.',
            'duration_minutes': 15,
            'cadence': 'one-off',
            'frequency_detail': 'Do this now',
            'recommended_date': date.today().isoformat(),
            'tag': 'W',
            'priority': 'H',
            'note': 'Write clear verb-first tasks with realistic effort estimates.',
        })

    if not clarifying_questions:
        clarifying_questions.append('What exact outcome should we optimize first?')

    return {
        'response_markdown': (
            'I skipped advanced AI planning for now because your workspace lacks minimum planning context. '
            'Complete the setup tasks below, then ask again for high-precision optimization.'
        ),
        'focus_target': 'Create baseline goals and tasks',
        'clarifying_questions': clarifying_questions,
        'suggested_tasks': suggested_tasks,
    }


def build_no_work_zen_payload(missing_tasks, missing_goals):
    clarifying_questions = []
    suggested_tasks = []

    if missing_goals:
        clarifying_questions.append('What short-term or long-term goal are you pursuing right now?')
        suggested_tasks.append({
            'title': 'Create one short-term goal',
            'why': 'ZenAI needs a concrete target to optimize decisions and execution.',
            'duration_minutes': 10,
            'cadence': 'one-off',
            'frequency_detail': 'Do this now',
            'recommended_date': date.today().isoformat(),
            'tag': 'W',
            'priority': 'H',
            'note': 'Example: Ship MVP landing page in 2 weeks.',
        })

    if missing_tasks:
        clarifying_questions.append('What concrete task are you actively working on this week?')
        suggested_tasks.append({
            'title': 'Add three execution tasks for this week',
            'why': 'ZenAI can only optimize what exists as actionable work items.',
            'duration_minutes': 15,
            'cadence': 'one-off',
            'frequency_detail': 'Do this now',
            'recommended_date': date.today().isoformat(),
            'tag': 'W',
            'priority': 'H',
            'note': 'Include at least one task linked to your top goal.',
        })

    if not clarifying_questions:
        clarifying_questions.append('What specific outcome should we optimize next?')

    return {
        'response_markdown': (
            'I paused advanced optimization because your workspace needs baseline planning data first. '
            'Add the suggested setup tasks below, then ask again and I will generate high-precision strategy.'
        ),
        'focus_target': 'Set baseline goals and tasks',
        'clarifying_questions': clarifying_questions,
        'suggested_tasks': suggested_tasks,
    }


def generate_zenai_reply(user_prompt, context_data, history):
    prompt = (
        "You are ZenAI, an elite personal strategy assistant for productivity, planning, execution, and reflective thinking. "
        "You must converge, not fan out: narrow to the most important target and produce specific next actions. "
        "Return ONLY valid JSON with this exact schema: "
        "{"
        "\"focus_target\": string,"
        "\"response_markdown\": string,"
        "\"clarifying_questions\": string[],"
        "\"suggested_tasks\": ["
        "{"
        "\"title\": string,"
        "\"why\": string,"
        "\"duration_minutes\": number,"
        "\"cadence\": \"daily\"|\"weekly\"|\"monthly\"|\"one-off\","
        "\"frequency_detail\": string,"
        "\"recommended_date\": string,"
        "\"tag\": \"P\"|\"S\"|\"W\"|\"R\"|\"B\","
        "\"priority\": \"L\"|\"M\"|\"H\"|\"U\","
        "\"note\": string"
        "}"
        "]"
        "}. "
        "For skill plans (e.g., chess), include exact time controls, named master games, explicit checkpoints and timeframes in tasks. "
        "Keep suggestions concrete and directly executable."
    )

    api_key = config('ANTHROPIC_API_KEY', default='').strip()
    if Anthropic and api_key:
        client = Anthropic(api_key=api_key)
        history_text = "\n".join([f"{item['role']}: {item['content']}" for item in history[-8:]])
        message = (
            f"Context JSON:\n{json.dumps(context_data, ensure_ascii=False)}\n\n"
            f"Recent Conversation:\n{history_text}\n\n"
            f"User Prompt:\n{user_prompt}"
        )
        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=900,
            temperature=0.5,
            system=prompt,
            messages=[{'role': 'user', 'content': message}],
        )
        if response.content:
            parsed = parse_zenai_json_response(response.content[0].text)
            if parsed:
                return {
                    'focus_target': (parsed.get('focus_target') or '').strip(),
                    'response_markdown': (parsed.get('response_markdown') or '').strip(),
                    'clarifying_questions': parsed.get('clarifying_questions') or [],
                    'suggested_tasks': normalize_suggested_tasks(parsed.get('suggested_tasks') or []),
                }

    return build_fallback_zen_payload(context_data)

def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'core/home.html')

@login_required
def dashboard(request):
    today = date.today()
    preferences = get_or_create_user_preferences(request.user)

    if preferences.default_page == 'calendar':
        return redirect('calendar')
    if preferences.default_page == 'ideas':
        return redirect('ideas_board')
    if preferences.default_page == 'goals':
        return redirect('goals_list')
    if preferences.default_page == 'weekly':
        return redirect('weekly_review')
    if preferences.default_page == 'monthly':
        return redirect('monthly_review')

    return redirect('daily_view', year=today.year, month=today.month, day=today.day)


@login_required
def preferences_view(request):
    preferences = get_or_create_user_preferences(request.user)

    def build_preferences_payload(preference_obj):
        return {
            'default_page': preference_obj.default_page,
            'monthly_books': preference_obj.monthly_books,
            'favorite_authors': preference_obj.favorite_authors,
            'saved_at': preference_obj.updated_at.strftime('%H:%M') if preference_obj.updated_at else '',
        }

    if request.method == 'POST':
        form = UserPreferenceForm(request.POST, instance=preferences)
        if form.is_valid():
            saved_preferences = form.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Preferences updated successfully!',
                    'preferences': build_preferences_payload(saved_preferences),
                })

            messages.success(request, 'Preferences updated successfully!')
            return redirect('preferences')

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'errors': form.errors,
            }, status=400)
    else:
        form = UserPreferenceForm(instance=preferences)

    return render(request, 'core/preferences.html', {
        'form': form,
        'preferences_data': build_preferences_payload(preferences),
    })


@login_required
def zenai_panel(request):
    sessions = ZenChatSession.objects.filter(user=request.user)[:20]
    return render(request, 'core/zenai.html', {'sessions': sessions})


@login_required
@require_POST
def zenai_send_message(request):
    payload = json.loads(request.body or '{}')
    user_message = (payload.get('message') or '').strip()
    section = (payload.get('section') or 'general').strip()
    session_id = payload.get('session_id')

    if not user_message:
        return JsonResponse({'success': False, 'error': 'Message is required.'}, status=400)

    if session_id:
        session = get_object_or_404(ZenChatSession, id=session_id, user=request.user)
    else:
        session = ZenChatSession.objects.create(
            user=request.user,
            section=section if section in dict(ZenChatSession.SECTION_CHOICES) else 'general',
            title=user_message[:120],
        )

    context_data = build_zen_context(request.user, session.section)
    existing_messages = session.messages.values('role', 'content')
    history = list(existing_messages)

    has_any_tasks = Task.objects.filter(user=request.user).exists()
    has_active_goals = Goal.objects.filter(user=request.user, completed=False).exists()

    has_any_tasks = Task.objects.filter(user=request.user).exists()
    has_active_goals = Goal.objects.filter(user=request.user, completed=False).exists()

    ZenChatMessage.objects.create(
        session=session,
        role='user',
        content=user_message,
        context_snapshot=context_data,
    )

    if not has_any_tasks or not has_active_goals:
        assistant_payload = build_no_work_zen_payload(
            missing_tasks=not has_any_tasks,
            missing_goals=not has_active_goals,
        )
    else:
        if not has_any_tasks or not has_active_goals:
            assistant_payload = build_setup_required_payload(
                missing_tasks=not has_any_tasks,
                missing_goals=not has_active_goals,
            )
        else:
            assistant_payload = generate_zenai_reply(user_message, context_data, history)
    assistant_reply = assistant_payload.get('response_markdown') or 'I could not generate a response.'

    ZenChatMessage.objects.create(
        session=session,
        role='assistant',
        content=assistant_reply,
        context_snapshot={
            'context': context_data,
            'assistant_structured': assistant_payload,
        },
    )

    session.updated_at = timezone.now()
    session.save(update_fields=['updated_at'])

    return JsonResponse({
        'success': True,
        'session_id': session.id,
        'reply': assistant_reply,
        'focus_target': assistant_payload.get('focus_target') or '',
        'clarifying_questions': assistant_payload.get('clarifying_questions') or [],
        'suggested_tasks': assistant_payload.get('suggested_tasks') or [],
    })


@login_required
@require_POST
def zenai_add_suggested_task(request):
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload.'}, status=400)

    title = (payload.get('title') or '').strip()
    if not title:
        return JsonResponse({'success': False, 'error': 'Task title is required.'}, status=400)

    recommended_date = (payload.get('recommended_date') or '').strip()
    task_date = date.today()
    if recommended_date:
        try:
            task_date = datetime.strptime(recommended_date, '%Y-%m-%d').date()
        except ValueError:
            task_date = date.today()

    valid_tags = {choice[0] for choice in Task.TAGS}
    valid_priorities = {choice[0] for choice in Task.PRIORITY_CHOICES}
    tag = (payload.get('tag') or 'W').strip().upper()
    priority = (payload.get('priority') or 'M').strip().upper()

    task = Task.objects.create(
        user=request.user,
        title=title[:200],
        date=task_date,
        tag=tag if tag in valid_tags else 'W',
        priority=priority if priority in valid_priorities else 'M',
    )

    note_parts = []
    for label, key in [
        ('Why', 'why'),
        ('Cadence', 'cadence'),
        ('Frequency', 'frequency_detail'),
        ('Duration (mins)', 'duration_minutes'),
        ('Note', 'note'),
    ]:
        value = payload.get(key)
        if value not in [None, '']:
            note_parts.append(f"{label}: {value}")

    if note_parts:
        Note.objects.create(task=task, content='\n'.join(note_parts))

    return JsonResponse({
        'success': True,
        'task': {
            'id': task.id,
            'title': task.title,
            'date': task.date.isoformat(),
            'tag': task.get_tag_display(),
            'priority': task.get_priority_display(),
        }
    })


@login_required
def zenai_session_messages(request, session_id):
    session = get_object_or_404(ZenChatSession, id=session_id, user=request.user)
    messages_qs = session.messages.values('id', 'role', 'content', 'created_at', 'context_snapshot')
    return JsonResponse({
        'success': True,
        'session': {
            'id': session.id,
            'title': session.title,
            'section': session.section,
        },
        'messages': [
            {
                'id': item['id'],
                'role': item['role'],
                'content': item['content'],
                'created_at': item['created_at'].isoformat(),
                'focus_target': (item['context_snapshot'] or {}).get('assistant_structured', {}).get('focus_target', ''),
                'clarifying_questions': (item['context_snapshot'] or {}).get('assistant_structured', {}).get('clarifying_questions', []),
                'suggested_tasks': (item['context_snapshot'] or {}).get('assistant_structured', {}).get('suggested_tasks', []),
            }
            for item in messages_qs
        ]
    })


@login_required
def zenai_sessions(request):
    sessions = ZenChatSession.objects.filter(user=request.user).values('id', 'title', 'section', 'updated_at')[:30]
    return JsonResponse({
        'success': True,
        'sessions': [
            {
                'id': item['id'],
                'title': item['title'],
                'section': item['section'],
                'updated_at': item['updated_at'].isoformat(),
            }
            for item in sessions
        ]
    })


def pwa_manifest(request):
    return render(request, 'manifest.json', content_type='application/manifest+json')


def service_worker(request):
    content = render_to_string('service-worker.js')
    return HttpResponse(content, content_type='application/javascript')

@login_required
def daily_view(request, year, month, day):
    selected_date = date(year, month, day)
    
    # Get or create journal entry for the day
    journal_entry, created = JournalEntry.objects.get_or_create(
        user=request.user,
        date=selected_date,
        defaults={'content': ''}
    )
    
    # Get or create daily mood
    daily_mood, mood_created = DailyMood.objects.get_or_create(
        user=request.user,
        date=selected_date,
        defaults={'mood': 'N', 'notes': ''}
    )
    
    # Handle journal form submission
    if request.method == 'POST' and 'journal_content' in request.POST:
        journal_form = JournalForm(request.POST, instance=journal_entry)
        if journal_form.is_valid():
            journal_form.save()
            messages.success(request, 'Journal saved successfully!')
            return redirect('daily_view', year=year, month=month, day=day)
    else:
        journal_form = JournalForm(instance=journal_entry)
    
    # Handle mood form submission
    if request.method == 'POST' and 'mood' in request.POST:
        mood_form = DailyMoodForm(request.POST, instance=daily_mood)
        if mood_form.is_valid():
            mood_form.save()
            messages.success(request, 'Mood saved successfully!')
            return redirect('daily_view', year=year, month=month, day=day)
    else:
        mood_form = DailyMoodForm(instance=daily_mood)
    
    # Handle task form submission
    if request.method == 'POST' and 'task_title' in request.POST:
        task_form = TaskForm(request.POST)
        if task_form.is_valid():
            task = task_form.save(commit=False)
            task.user = request.user
            task.date = selected_date
            task.save()
            messages.success(request, 'Task added successfully!')
            return redirect('daily_view', year=year, month=month, day=day)
    else:
        task_form = TaskForm()
    
    # Get tasks for the day with related data
    tasks = Task.objects.filter(
        user=request.user, 
        date=selected_date
    ).prefetch_related('subtasks', 'notes', 'links', 'task_goals__goal')
    
    # Get carried over tasks from previous day
    previous_date = selected_date - timedelta(days=1)
    carried_over_tasks = Task.objects.filter(
        user=request.user,
        date__lt=selected_date,
        completed=False
    ).order_by('-date')[:10]
    
    # Navigation dates
    prev_date = selected_date - timedelta(days=1)
    next_date = selected_date + timedelta(days=1)
    
    context = {
        'selected_date': selected_date,
        'journal_form': journal_form,
        'mood_form': mood_form,
        'task_form': task_form,
        'tasks': tasks,
        'carried_over_tasks': carried_over_tasks,
        'prev_date': prev_date,
        'next_date': next_date,
        'today': date.today(),
    }
    
    return render(request, 'core/daily_view.html', context)

@login_required
@require_POST
def toggle_task(request, task_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    task.completed = not task.completed
    task.save()
    return JsonResponse({'completed': task.completed})

@login_required
@require_POST
def delete_task(request, task_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    task.delete()
    return JsonResponse({'success': True})

@login_required
def calendar_view(request):
    today = date.today()
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))
    
    # Create calendar
    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]
    
    # Get tasks and journals for the month
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)
    
    tasks = Task.objects.filter(
        user=request.user,
        date__range=[start_date, end_date]
    ).values('date').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(completed=True))
    )
    
    journals = JournalEntry.objects.filter(
        user=request.user,
        date__range=[start_date, end_date]
    ).values_list('date', flat=True)
    
    # Create lookup dictionaries
    task_data = {item['date']: item for item in tasks}
    journal_dates = set(journals)
    
    # Navigation
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    context = {
        'calendar': cal,
        'year': year,
        'month': month,
        'month_name': month_name,
        'task_data': task_data,
        'journal_dates': journal_dates,
        'today': today,
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
    }
    
    return render(request, 'core/calendar.html', context)

@login_required
def weekly_review(request):
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    
    # Get week's tasks
    tasks = Task.objects.filter(
        user=request.user,
        date__range=[start_of_week, end_of_week]
    )
    
    # Calculate statistics
    total_tasks = tasks.count()
    completed_tasks = tasks.filter(completed=True).count()
    completion_rate = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
    
    # Tasks by tag
    tag_stats = {}
    for tag_code, tag_name in Task.TAGS:
        tag_tasks = tasks.filter(tag=tag_code)
        tag_completed = tag_tasks.filter(completed=True).count()
        tag_total = tag_tasks.count()
        tag_stats[tag_name] = {
            'total': tag_total,
            'completed': tag_completed,
            'rate': (tag_completed / tag_total * 100) if tag_total > 0 else 0
        }
    
    # Get journal entries
    journals = JournalEntry.objects.filter(
        user=request.user,
        date__range=[start_of_week, end_of_week]
    ).order_by('date')
    
    context = {
        'start_of_week': start_of_week,
        'end_of_week': end_of_week,
        'total_tasks': total_tasks,
        'completed_tasks': completed_tasks,
        'completion_rate': completion_rate,
        'tag_stats': tag_stats,
        'journals': journals,
    }
    
    return render(request, 'core/weekly_review.html', context)

@login_required
def monthly_review(request):
    today = date.today()
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))
    
    start_of_month = date(year, month, 1)
    if month == 12:
        end_of_month = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_of_month = date(year, month + 1, 1) - timedelta(days=1)
    
    # Get month's tasks with all related data
    tasks = Task.objects.filter(
        user=request.user,
        date__range=[start_of_month, end_of_month]
    ).prefetch_related('subtasks', 'notes', 'links', 'task_goals__goal').order_by('date', 'created_at')
    
    # Calculate statistics
    total_tasks = tasks.count()
    completed_tasks = tasks.filter(completed=True).count()
    completion_rate = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
    
    # Tasks by tag
    tag_stats = {}
    for tag_code, tag_name in Task.TAGS:
        tag_tasks = tasks.filter(tag=tag_code)
        tag_completed = tag_tasks.filter(completed=True).count()
        tag_total = tag_tasks.count()
        tag_stats[tag_name] = {
            'total': tag_total,
            'completed': tag_completed,
            'rate': (tag_completed / tag_total * 100) if tag_total > 0 else 0
        }
    
    # Daily completion rates for chart
    daily_stats = []
    current_date = start_of_month
    while current_date <= end_of_month:
        day_tasks = tasks.filter(date=current_date)
        day_total = day_tasks.count()
        day_completed = day_tasks.filter(completed=True).count()
        daily_stats.append({
            'date': current_date.strftime('%Y-%m-%d'),
            'day': current_date.day,
            'total': day_total,
            'completed': day_completed,
            'rate': (day_completed / day_total * 100) if day_total > 0 else 0
        })
        current_date += timedelta(days=1)
    
    # Get mood data for the month
    moods = DailyMood.objects.filter(
        user=request.user,
        date__range=[start_of_month, end_of_month]
    ).order_by('date')
    
    # Navigation
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    context = {
        'start_of_month': start_of_month,
        'end_of_month': end_of_month,
        'month_name': calendar.month_name[month],
        'year': year,
        'month': month,
        'total_tasks': total_tasks,
        'completed_tasks': completed_tasks,
        'completion_rate': completion_rate,
        'tag_stats': tag_stats,
        'daily_stats': daily_stats,
        'tasks': tasks,
        'moods': moods,
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
    }
    
    return render(request, 'core/monthly_review.html', context)


# Task management views
@login_required
def edit_task(request, task_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    if request.method == 'POST':
        form = TaskEditForm(request.POST, instance=task)
        if form.is_valid():
            form.save()
            messages.success(request, 'Task updated successfully!')
            return redirect('daily_view', year=task.date.year, month=task.date.month, day=task.date.day)
    else:
        form = TaskEditForm(instance=task)
    
    context = {
        'form': form,
        'task': task,
    }
    return render(request, 'core/edit_task.html', context)


@login_required
@require_POST
def carry_task_to_next_day(request, task_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    if not task.completed:
        task.carried_over = True
        if not task.overdue_date:
            task.overdue_date = task.date
        task.date = task.date + timedelta(days=1)
        task.save()
        return JsonResponse({'success': True, 'new_date': task.date.strftime('%Y-%m-%d')})
    return JsonResponse({'success': False, 'error': 'Task is already completed'})


# SubTask views
@login_required
@require_POST
def add_subtask(request, task_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    form = SubTaskForm(request.POST)
    if form.is_valid():
        subtask = form.save(commit=False)
        subtask.task = task
        subtask.save()
        return JsonResponse({
            'success': True,
            'subtask': {
                'id': subtask.id,
                'title': subtask.title,
                'completed': subtask.completed
            }
        })
    return JsonResponse({'success': False, 'errors': form.errors})


@login_required
@require_POST
def toggle_subtask(request, subtask_id):
    subtask = get_object_or_404(SubTask, id=subtask_id, task__user=request.user)
    subtask.completed = not subtask.completed
    subtask.save()
    return JsonResponse({'completed': subtask.completed})


@login_required
@require_POST
def delete_subtask(request, subtask_id):
    subtask = get_object_or_404(SubTask, id=subtask_id, task__user=request.user)
    subtask.delete()
    return JsonResponse({'success': True})


# Note views
@login_required
@require_POST
def add_note_to_task(request, task_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    form = NoteForm(request.POST)
    if form.is_valid():
        note = form.save(commit=False)
        note.task = task
        note.save()
        return JsonResponse({
            'success': True,
            'note': {
                'id': note.id,
                'content': note.content,
                'created_at': note.created_at.strftime('%Y-%m-%d %H:%M')
            }
        })
    return JsonResponse({'success': False, 'errors': form.errors})


@login_required
@require_POST
def add_note_to_subtask(request, subtask_id):
    subtask = get_object_or_404(SubTask, id=subtask_id, task__user=request.user)
    form = NoteForm(request.POST)
    if form.is_valid():
        note = form.save(commit=False)
        note.subtask = subtask
        note.save()
        return JsonResponse({
            'success': True,
            'note': {
                'id': note.id,
                'content': note.content,
                'created_at': note.created_at.strftime('%Y-%m-%d %H:%M')
            }
        })
    return JsonResponse({'success': False, 'errors': form.errors})


@login_required
@require_POST
def delete_note(request, note_id):
    note = get_object_or_404(Note, id=note_id)
    if (note.task and note.task.user == request.user) or (note.subtask and note.subtask.task.user == request.user):
        note.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'error': 'Permission denied'})


# Link views
@login_required
@require_POST
def add_link_to_task(request, task_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    form = LinkForm(request.POST)
    if form.is_valid():
        link = form.save(commit=False)
        link.task = task
        link.save()
        return JsonResponse({
            'success': True,
            'link': {
                'id': link.id,
                'url': link.url,
                'title': link.title or link.url
            }
        })
    return JsonResponse({'success': False, 'errors': form.errors})


@login_required
@require_POST
def delete_link(request, link_id):
    link = get_object_or_404(Link, id=link_id, task__user=request.user)
    link.delete()
    return JsonResponse({'success': True})


# Idea views
@login_required
def ideas_board(request):
    if request.method == 'POST':
        form = IdeaForm(request.POST)
        if form.is_valid():
            idea = form.save(commit=False)
            idea.user = request.user
            idea.save()
            messages.success(request, 'Idea added successfully!')
            return redirect('ideas_board')
    else:
        form = IdeaForm()
    
    ideas = Idea.objects.filter(user=request.user, converted_to_task=False)
    converted_ideas = Idea.objects.filter(user=request.user, converted_to_task=True).select_related('task')
    
    context = {
        'form': form,
        'ideas': ideas,
        'converted_ideas': converted_ideas,
    }
    return render(request, 'core/ideas_board.html', context)


@login_required
@require_POST
def convert_idea_to_task(request, idea_id):
    idea = get_object_or_404(Idea, id=idea_id, user=request.user)
    
    if request.POST.get('task_date'):
        task_date = datetime.strptime(request.POST.get('task_date'), '%Y-%m-%d').date()
    else:
        task_date = date.today()
    
    task = Task.objects.create(
        user=request.user,
        title=idea.title,
        date=task_date,
        tag=request.POST.get('tag', 'W'),
        priority=request.POST.get('priority', 'M')
    )
    
    # Add idea description as a note
    if idea.description:
        Note.objects.create(
            task=task,
            content=idea.description
        )
    
    idea.converted_to_task = True
    idea.task = task
    idea.save()
    
    return JsonResponse({'success': True, 'task_id': task.id})


@login_required
@require_POST
def delete_idea(request, idea_id):
    idea = get_object_or_404(Idea, id=idea_id, user=request.user)
    idea.delete()
    return JsonResponse({'success': True})


# Goal views
@login_required
def goals_list(request):
    if request.method == 'POST':
        form = GoalForm(request.POST)
        if form.is_valid():
            goal = form.save(commit=False)
            goal.user = request.user
            goal.save()
            messages.success(request, 'Goal added successfully!')
            return redirect('goals_list')
    else:
        form = GoalForm()
    
    short_term_goals = Goal.objects.filter(user=request.user, term='S', completed=False)
    long_term_goals = Goal.objects.filter(user=request.user, term='L', completed=False)
    completed_goals = Goal.objects.filter(user=request.user, completed=True)
    
    context = {
        'form': form,
        'short_term_goals': short_term_goals,
        'long_term_goals': long_term_goals,
        'completed_goals': completed_goals,
    }
    return render(request, 'core/goals_list.html', context)


@login_required
@require_POST
def toggle_goal(request, goal_id):
    goal = get_object_or_404(Goal, id=goal_id, user=request.user)
    goal.completed = not goal.completed
    goal.save()
    return JsonResponse({'completed': goal.completed})


@login_required
@require_POST
def delete_goal(request, goal_id):
    goal = get_object_or_404(Goal, id=goal_id, user=request.user)
    goal.delete()
    return JsonResponse({'success': True})


@login_required
@require_POST
def attach_goal_to_task(request, task_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    goal_id = request.POST.get('goal_id')
    goal = get_object_or_404(Goal, id=goal_id, user=request.user)
    
    task_goal, created = TaskGoal.objects.get_or_create(task=task, goal=goal)
    
    return JsonResponse({
        'success': True,
        'created': created,
        'goal': {
            'id': goal.id,
            'title': goal.title
        }
    })


@login_required
@require_POST
def detach_goal_from_task(request, task_id, goal_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    goal = get_object_or_404(Goal, id=goal_id, user=request.user)
    
    TaskGoal.objects.filter(task=task, goal=goal).delete()
    
    return JsonResponse({'success': True})

