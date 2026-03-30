
# core/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db.models import Q, Count, Prefetch
from django.template.loader import render_to_string
from django.utils.html import strip_tags
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


def ensure_goal_celebration_task(goal):
    if not goal.target_date:
        return

    celebration_title = f"Celebrate end of goal: {goal.title}"
    task = Task.objects.filter(
        user=goal.user,
        title=celebration_title,
        tag='B',
        is_rest=True,
    ).first()

    if task:
        task.date = goal.target_date
        task.priority = 'M'
        task.save(update_fields=['date', 'priority'])
        return

    Task.objects.create(
        user=goal.user,
        date=goal.target_date,
        title=celebration_title,
        tag='B',
        priority='M',
        is_rest=True,
    )


def ensure_recurring_tasks_for_date(user, selected_date):
    templates = Task.objects.filter(
        user=user,
        is_recurring_template=True,
    ).exclude(recurrence_type='none')

    for template in templates:
        if not template.recurs_on(selected_date):
            continue

        already_exists = Task.objects.filter(
            user=user,
            date=selected_date,
            recurrence_source=template,
        ).exists()
        if already_exists:
            continue

        Task.objects.create(
            user=user,
            date=selected_date,
            title=template.title,
            tag=template.tag,
            priority=template.priority,
            is_rest=template.is_rest,
            recurrence_source=template,
        )


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
            'is_rest': bool(item.get('is_rest', False)),
            'cadence': cadence if cadence in {'daily', 'weekly', 'monthly', 'one-off'} else 'one-off',
            'frequency_detail': (item.get('frequency_detail') or '').strip(),
            'recommended_date': (item.get('recommended_date') or '').strip(),
            'slot_start': (item.get('slot_start') or '').strip(),
            'slot_end': (item.get('slot_end') or '').strip(),
            'recurrence_type': (item.get('recurrence_type') or 'none').strip(),
            'recurrence_days': (item.get('recurrence_days') or '').strip(),
            'recurrence_end_date': (item.get('recurrence_end_date') or '').strip(),
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
                'is_rest': False,
                'cadence': 'one-off',
                'frequency_detail': 'Today, once',
                'recommended_date': date.today().isoformat(),
                'slot_start': '',
                'slot_end': '',
                'recurrence_type': 'none',
                'recurrence_days': '',
                'recurrence_end_date': '',
                'tag': 'W',
                'priority': 'H',
                'note': 'Write: outcome, metric, deadline, and owner.',
            },
            {
                'title': 'Take a deliberate recovery block',
                'why': 'Rest protects consistency and prevents burnout.',
                'duration_minutes': 20,
                'is_rest': True,
                'cadence': 'daily',
                'frequency_detail': 'One short wind-down block/day',
                'recommended_date': date.today().isoformat(),
                'slot_start': '',
                'slot_end': '',
                'recurrence_type': 'daily',
                'recurrence_days': '',
                'recurrence_end_date': '',
                'tag': 'B',
                'priority': 'M',
                'note': 'Walk, stretch, breathe, no screens.',
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
    slot_date   = context_data.get('slot_date', '')
    slot_start  = context_data.get('slot_start', '')
    slot_end    = context_data.get('slot_end', '')
    slot_hint   = ''
    if slot_date:
        slot_hint = f"The user has allocated time on {slot_date}"
        if slot_start and slot_end:
            slot_hint += f" from {slot_start} to {slot_end}"
        slot_hint += ". ALL suggested tasks MUST fit inside this window and use this date as recommended_date."

    prompt = (
        "You are ZenAI — a focused goal-breakdown assistant. "
        "Your only job is to take ONE goal or idea and break it into the smallest concrete daily actions that move it forward. "
        "Philosophy (encode this into every response): "
        "'A man on a thousand mile walk has to forget his goal and say to himself every morning: "
        "Today I am going to cover twenty-five miles and then rest up and sleep.' — Leo Tolstoy. "
        "This means: ignore the overwhelming whole. Surface the exact 25-mile segment the user can walk TODAY or in their available time slot. "
        "Rules you must obey: "
        "1. Never produce generic advice. Every task must be a direct sub-step of the provided goal or idea. "
        "2. Fit all suggested tasks inside the user's stated time slot; sum of duration_minutes must not exceed the slot duration. "
        "3. If no time slot is given, default to 60-minute total effort. "
        "4. Order tasks by execution sequence, not importance. "
        "5. Provide a 'focus_target' that is a single, measurable outcome for this session only — not the whole goal. "
        "6. Clarifying questions should help narrow scope if the goal is too broad. "
        "7. Always include both ACTION tasks and REST/RECOVERY blocks when appropriate to avoid burnout. "
        f"{slot_hint} "
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
        "\"is_rest\": boolean,"
        "\"cadence\": \"daily\"|\"weekly\"|\"monthly\"|\"one-off\","
        "\"frequency_detail\": string,"
        "\"recommended_date\": string (YYYY-MM-DD),"
        "\"slot_start\": string (HH:MM, the start time for this task within the slot),"
        "\"slot_end\": string (HH:MM, the end time for this task within the slot),"
        "\"recurrence_type\": \"none\"|\"daily\"|\"weekly\"|\"custom\","
        "\"recurrence_days\": string (comma-separated weekday numbers 0-6 when recurrence_type is custom),"
        "\"recurrence_end_date\": string (YYYY-MM-DD or empty),"
        "\"tag\": \"P\"|\"S\"|\"W\"|\"R\"|\"B\","
        "\"priority\": \"L\"|\"M\"|\"H\"|\"U\","
        "\"note\": string"
        "}"
        "]"
        "}"
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
    else:
        return build_fallback_zen_payload(context_data)


def build_idea_breakdown_fallback(idea):
    idea_summary = (idea.description or '').strip()
    if not idea_summary:
        idea_summary = 'Clarify scope and produce one practical first deliverable.'

    return {
        'focus_target': f"Ship first concrete output for: {idea.title[:80]}",
        'response_markdown': (
            'I broke this idea into concrete, executable tasks you can start today. '
            'Add the cards below directly to your plan.'
        ),
        'suggested_tasks': normalize_suggested_tasks([
            {
                'title': f"Define success criteria for {idea.title[:80]}",
                'why': 'A measurable target prevents scope drift.',
                'duration_minutes': 20,
                'is_rest': False,
                'cadence': 'one-off',
                'frequency_detail': 'One focused planning pass',
                'recommended_date': date.today().isoformat(),
                'slot_start': '',
                'slot_end': '',
                'recurrence_type': 'none',
                'tag': 'W',
                'priority': 'H',
                'note': idea_summary[:400],
            },
            {
                'title': f"Create a tiny prototype for {idea.title[:80]}",
                'why': 'Fast validation reveals what to keep or discard.',
                'duration_minutes': 45,
                'is_rest': False,
                'cadence': 'one-off',
                'frequency_detail': 'Build first draft',
                'recommended_date': date.today().isoformat(),
                'slot_start': '',
                'slot_end': '',
                'recurrence_type': 'none',
                'tag': 'W',
                'priority': 'H',
                'note': '',
            },
            {
                'title': f"List 3 improvements for {idea.title[:80]}",
                'why': 'Structured iteration keeps momentum practical.',
                'duration_minutes': 25,
                'is_rest': False,
                'cadence': 'one-off',
                'frequency_detail': 'Review and refine',
                'recommended_date': date.today().isoformat(),
                'slot_start': '',
                'slot_end': '',
                'recurrence_type': 'none',
                'tag': 'W',
                'priority': 'M',
                'note': '',
            },
        ]),
    }


def generate_idea_breakdown_reply(idea):
    system_prompt = (
        'You are ZenAI-IdeaPlanner. Break one idea into practical, workable tasks. '
        'Use execution-first thinking: each task must be directly actionable, time-boxed, and testable. '
        'Do not output motivational filler. Keep scope realistic for daily execution. '
        'Return ONLY valid JSON with this exact schema: '
        '{'
        '"focus_target": string,'
        '"response_markdown": string,'
        '"suggested_tasks": ['
        '{'
        '"title": string,'
        '"why": string,'
        '"duration_minutes": number,'
        '"is_rest": boolean,'
        '"cadence": "daily"|"weekly"|"monthly"|"one-off",'
        '"frequency_detail": string,'
        '"recommended_date": string (YYYY-MM-DD),'
        '"slot_start": string,'
        '"slot_end": string,'
        '"recurrence_type": "none"|"daily"|"weekly"|"custom",'
        '"recurrence_days": string,'
        '"recurrence_end_date": string,'
        '"tag": "P"|"S"|"W"|"R"|"B",'
        '"priority": "L"|"M"|"H"|"U",'
        '"note": string'
        '}'
        ']'
        '}'
    )

    api_key = config('ANTHROPIC_API_KEY', default='').strip()
    if Anthropic and api_key:
        client = Anthropic(api_key=api_key)
        prompt = {
            'idea_title': idea.title,
            'idea_description': idea.description,
            'today': date.today().isoformat(),
        }
        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=900,
            temperature=0.4,
            system=system_prompt,
            messages=[
                {
                    'role': 'user',
                    'content': f"Create a practical execution plan for this idea: {json.dumps(prompt, ensure_ascii=False)}",
                }
            ],
        )
        if response.content:
            parsed = parse_zenai_json_response(response.content[0].text)
            if parsed:
                return {
                    'focus_target': (parsed.get('focus_target') or '').strip(),
                    'response_markdown': (parsed.get('response_markdown') or '').strip(),
                    'suggested_tasks': normalize_suggested_tasks(parsed.get('suggested_tasks') or []),
                }

    return build_idea_breakdown_fallback(idea)

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
    section   = (payload.get('section') or 'goal').strip()
    session_id = payload.get('session_id')

    # Goal or idea being broken down
    goal_id  = payload.get('goal_id')
    idea_id  = payload.get('idea_id')
    # Time slot the user allocated
    slot_date  = (payload.get('slot_date') or '').strip()
    slot_start = (payload.get('slot_start') or '').strip()
    slot_end   = (payload.get('slot_end') or '').strip()
    extra_notes = (payload.get('notes') or '').strip()

    # Resolve the subject (goal or idea)
    subject_title = ''
    subject_description = ''
    if goal_id:
        try:
            goal_obj = Goal.objects.get(id=goal_id, user=request.user)
            subject_title = goal_obj.title
            subject_description = goal_obj.description
            section = 'goal'
        except Goal.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Goal not found.'}, status=404)
    elif idea_id:
        try:
            idea_obj = Idea.objects.get(id=idea_id, user=request.user)
            subject_title = idea_obj.title
            subject_description = idea_obj.description
            section = 'idea'
        except Idea.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Idea not found.'}, status=404)
    else:
        return JsonResponse({'success': False, 'error': 'Please select a goal or idea to break down.'}, status=400)

    # Build the user message from subject + time slot + extra notes
    slot_description = ''
    if slot_date:
        slot_description = f" | Time slot: {slot_date}"
        if slot_start and slot_end:
            slot_description += f" {slot_start}–{slot_end}"
    user_message = f"Break down: {subject_title}"
    if subject_description:
        user_message += f"\n{subject_description}"
    user_message += slot_description
    if extra_notes:
        user_message += f"\nExtra context: {extra_notes}"

    if session_id:
        session = get_object_or_404(ZenChatSession, id=session_id, user=request.user)
    else:
        session = ZenChatSession.objects.create(
            user=request.user,
            section=section if section in dict(ZenChatSession.SECTION_CHOICES) else 'goal',
            title=subject_title[:120],
        )

    context_data = build_zen_context(request.user, section)
    # Inject slot info into context so generate_zenai_reply can reference it
    context_data['slot_date']  = slot_date
    context_data['slot_start'] = slot_start
    context_data['slot_end']   = slot_end
    context_data['subject_title'] = subject_title
    context_data['subject_description'] = subject_description

    existing_messages = session.messages.values('role', 'content')
    history = list(existing_messages)

    has_active_goals = Goal.objects.filter(user=request.user, completed=False).exists()
    has_any_ideas    = Idea.objects.filter(user=request.user).exists()

    ZenChatMessage.objects.create(
        session=session,
        role='user',
        content=user_message,
        context_snapshot=context_data,
    )

    if not has_active_goals and not has_any_ideas:
        assistant_payload = build_no_work_zen_payload(
            missing_tasks=False,
            missing_goals=True,
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

    recommended_date = (payload.get('recommended_date') or payload.get('slot_date') or '').strip()
    task_date = date.today()
    if recommended_date:
        try:
            task_date = datetime.strptime(recommended_date, '%Y-%m-%d').date()
        except ValueError:
            task_date = date.today()

    slot_start = (payload.get('slot_start') or '').strip()
    slot_end   = (payload.get('slot_end') or '').strip()
    is_rest = bool(payload.get('is_rest', False))
    recurrence_type = (payload.get('recurrence_type') or 'none').strip().lower()
    recurrence_days = (payload.get('recurrence_days') or '').strip()
    recurrence_end_date_raw = (payload.get('recurrence_end_date') or '').strip()

    if recurrence_type not in {'none', 'daily', 'weekly', 'custom'}:
        recurrence_type = 'none'

    recurrence_end_date = None
    if recurrence_end_date_raw:
        try:
            recurrence_end_date = datetime.strptime(recurrence_end_date_raw, '%Y-%m-%d').date()
        except ValueError:
            recurrence_end_date = None

    valid_tags = {choice[0] for choice in Task.TAGS}
    valid_priorities = {choice[0] for choice in Task.PRIORITY_CHOICES}
    tag = (payload.get('tag') or 'W').strip().upper()
    priority = (payload.get('priority') or 'M').strip().upper()

    if recurrence_type != 'none':
        template_task = Task.objects.create(
            user=request.user,
            title=title[:200],
            date=task_date,
            tag=tag if tag in valid_tags else 'W',
            priority=priority if priority in valid_priorities else 'M',
            is_rest=is_rest,
            recurrence_type=recurrence_type,
            recurrence_days=recurrence_days if recurrence_type == 'custom' else '',
            recurrence_end_date=recurrence_end_date,
            is_recurring_template=True,
        )
        task = Task.objects.create(
            user=request.user,
            title=title[:200],
            date=task_date,
            tag=tag if tag in valid_tags else 'W',
            priority=priority if priority in valid_priorities else 'M',
            is_rest=is_rest,
            recurrence_source=template_task,
        )
    else:
        task = Task.objects.create(
            user=request.user,
            title=title[:200],
            date=task_date,
            tag=tag if tag in valid_tags else 'W',
            priority=priority if priority in valid_priorities else 'M',
            is_rest=is_rest,
        )

    note_parts = []
    if slot_start and slot_end:
        note_parts.append(f"Time slot: {slot_start}–{slot_end}")
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


@login_required
def zenai_calendar_tasks(request):
    """Return tasks for a given date so the time-slot picker can show busy blocks."""
    date_str = request.GET.get('date', '')
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        target_date = date.today()

    tasks = Task.objects.filter(user=request.user, date=target_date).values(
        'id', 'title', 'tag', 'priority', 'completed'
    )
    return JsonResponse({
        'success': True,
        'date': target_date.isoformat(),
        'tasks': list(tasks),
    })


def pwa_manifest(request):
    return render(request, 'manifest.json', content_type='application/manifest+json')


def service_worker(request):
    content = render_to_string('service-worker.js')
    return HttpResponse(content, content_type='application/javascript')

@login_required
def daily_view(request, year, month, day):
    selected_date = date(year, month, day)

    ensure_recurring_tasks_for_date(request.user, selected_date)

    # Get or create daily mood
    daily_mood, mood_created = DailyMood.objects.get_or_create(
        user=request.user,
        date=selected_date,
        defaults={'mood': 'N', 'notes': ''}
    )

    journal_form = JournalForm()
    mood_form = DailyMoodForm(instance=daily_mood)
    task_form = TaskForm()
    idea_form = IdeaForm()

    if request.method == 'POST':
        if 'journal_content' in request.POST:
            journal_form = JournalForm(request.POST)
            if journal_form.is_valid():
                entry = journal_form.save(commit=False)
                entry.user = request.user
                entry.date = selected_date
                entry.save()
                messages.success(request, 'Journal entry saved.')
                return redirect('daily_view', year=year, month=month, day=day)

        elif 'mood' in request.POST:
            mood_form = DailyMoodForm(request.POST, instance=daily_mood)
            if mood_form.is_valid():
                mood_form.save()
                messages.success(request, 'Mood saved successfully!')
                return redirect('daily_view', year=year, month=month, day=day)

        elif 'task_title' in request.POST:
            task_form = TaskForm(request.POST)
            if task_form.is_valid():
                task = task_form.save(commit=False)
                task.user = request.user
                task.date = selected_date

                if task.recurrence_type != 'none':
                    task.is_recurring_template = True
                    task.save()
                    Task.objects.create(
                        user=request.user,
                        date=selected_date,
                        title=task.title,
                        tag=task.tag,
                        priority=task.priority,
                        is_rest=task.is_rest,
                        recurrence_source=task,
                    )
                else:
                    task.save()

                messages.success(request, 'Task added successfully!')
                return redirect('daily_view', year=year, month=month, day=day)

        elif 'idea_title' in request.POST:
            idea_form = IdeaForm(request.POST)
            if idea_form.is_valid():
                idea = idea_form.save(commit=False)
                idea.user = request.user
                idea.save()
                messages.success(request, 'Idea saved from daily view.')
                return redirect('daily_view', year=year, month=month, day=day)
    
    # Get tasks for the day with related data
    tasks = Task.objects.filter(
        user=request.user, 
        date=selected_date,
        is_recurring_template=False,
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
        'journal_entries': JournalEntry.objects.filter(
            user=request.user,
            date=selected_date,
        ).order_by('-created_at')[:20],
        'mood_form': mood_form,
        'task_form': task_form,
        'idea_form': idea_form,
        'tasks': tasks,
        'carried_over_tasks': carried_over_tasks,
        'prev_date': prev_date,
        'next_date': next_date,
        'today': date.today(),
    }
    
    return render(request, 'core/daily_view.html', context)


@login_required
def daily_journal_editor(request, year, month, day):
    selected_date = date(year, month, day)

    if request.method == 'POST' and 'journal_content' in request.POST:
        form = JournalForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user = request.user
            entry.date = selected_date
            entry.save()
            messages.success(request, 'Journal entry saved.')

            if request.POST.get('continue_editing') == '1':
                return redirect('daily_journal_editor', year=year, month=month, day=day)
            return redirect('daily_view', year=year, month=month, day=day)
    else:
        form = JournalForm()

    context = {
        'selected_date': selected_date,
        'form': form,
        'prev_date': selected_date - timedelta(days=1),
        'next_date': selected_date + timedelta(days=1),
        'recent_entries': JournalEntry.objects.filter(
            user=request.user,
            date=selected_date,
        ).order_by('-created_at')[:20],
    }
    return render(request, 'core/daily_journal_editor.html', context)

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

    task_rows = Task.objects.filter(
        user=request.user,
        date__range=[start_date, end_date]
    ).values('date', 'title', 'completed', 'tag', 'priority').order_by('date', 'created_at')
    
    journals = JournalEntry.objects.filter(
        user=request.user,
        date__range=[start_date, end_date]
    ).values_list('date', flat=True)
    
    # Create lookup dictionaries with ISO date keys for safe template lookup
    task_data = {item['date'].isoformat(): item for item in tasks}
    task_lines = {}
    for item in task_rows:
        key = item['date'].isoformat()
        task_lines.setdefault(key, []).append({
            'title': item['title'],
            'completed': item['completed'],
            'tag': item['tag'],
            'priority': item['priority'],
        })
    journal_dates = set(journals)

    calendar_cells = []
    for week in cal:
        week_cells = []
        for day in week:
            if day == 0:
                week_cells.append({'day': 0})
                continue

            day_date = date(year, month, day)
            day_key = day_date.isoformat()
            week_cells.append({
                'day': day,
                'day_key': day_key,
                'is_today': day_date == today,
                'task_info': task_data.get(day_key),
                'task_lines': task_lines.get(day_key, []),
                'has_journal': day_date in journal_dates,
            })
        calendar_cells.append(week_cells)
    
    # Navigation
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    context = {
        'calendar': cal,
        'calendar_cells': calendar_cells,
        'year': year,
        'month': month,
        'month_name': month_name,
        'task_data': task_data,
        'task_lines': task_lines,
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

    # JSON API for ZenAI drawer
    if request.GET.get('json') == '1':
        return JsonResponse({
            'ideas': [
                {
                    'id': i.id,
                    'title': i.title,
                    'description': i.description,
                }
                for i in ideas
            ]
        })

    context = {
        'form': form,
        'ideas': ideas,
        'converted_ideas': converted_ideas,
        'today': date.today(),
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


@login_required
@require_POST
def idea_ai_breakdown(request, idea_id):
    idea = get_object_or_404(Idea, id=idea_id, user=request.user)

    payload = generate_idea_breakdown_reply(idea)

    focus_target = payload.get('focus_target', '').strip()
    if not focus_target:
        focus_target = strip_tags(idea.title)[:120]

    return JsonResponse({
        'success': True,
        'idea': {
            'id': idea.id,
            'title': idea.title,
        },
        'focus_target': focus_target,
        'response_markdown': payload.get('response_markdown', '').strip(),
        'suggested_tasks': payload.get('suggested_tasks', []),
    })


# Goal views
@login_required
def goals_list(request):
    if request.method == 'POST':
        form = GoalForm(request.POST, request.FILES)
        if form.is_valid():
            goal = form.save(commit=False)
            goal.user = request.user
            goal.save()
            ensure_goal_celebration_task(goal)
            messages.success(request, 'Goal added successfully!')
            return redirect('goals_list')
    else:
        form = GoalForm()

    short_term_goals = Goal.objects.filter(user=request.user, term='S', completed=False)
    long_term_goals  = Goal.objects.filter(user=request.user, term='L', completed=False)
    completed_goals  = Goal.objects.filter(user=request.user, completed=True)

    # JSON API for ZenAI drawer
    if request.GET.get('json') == '1':
        active_goals = list(short_term_goals) + list(long_term_goals)
        return JsonResponse({
            'goals': [
                {
                    'id': g.id,
                    'title': g.title,
                    'description': g.description,
                    'term': g.term,
                    'target_date': g.target_date.isoformat() if g.target_date else None,
                }
                for g in active_goals
            ]
        })

    context = {
        'form': form,
        'short_term_goals': short_term_goals,
        'long_term_goals': long_term_goals,
        'completed_goals': completed_goals,
    }
    return render(request, 'core/goals_list.html', context)


@login_required
def edit_goal(request, goal_id):
    goal = get_object_or_404(Goal, id=goal_id, user=request.user)

    if request.method == 'POST':
        form = GoalForm(request.POST, request.FILES, instance=goal)
        if form.is_valid():
            updated_goal = form.save()
            ensure_goal_celebration_task(updated_goal)
            messages.success(request, 'Goal updated successfully!')
            return redirect('goals_list')
    else:
        form = GoalForm(instance=goal)

    return render(request, 'core/edit_goal.html', {'form': form, 'goal': goal})


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
    Task.objects.filter(
        user=request.user,
        title=f"Celebrate end of goal: {goal.title}",
        tag='B',
        is_rest=True,
    ).delete()
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

