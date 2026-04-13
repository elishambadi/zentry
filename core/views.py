
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
import logging
import time
import httpx

logger = logging.getLogger('core.zenai')

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


def normalize_idea_suggested_tasks(items, idea, clarifying_answer=''):
    normalized = normalize_suggested_tasks(items)
    bounded_tasks = normalized[:9]

    if len(bounded_tasks) >= 3:
        return bounded_tasks

    fallback_payload = build_idea_task_breakdown_fallback(
        idea,
        clarifying_question='',
        clarifying_answer=clarifying_answer,
    )
    fallback_tasks = fallback_payload.get('suggested_tasks', [])
    return fallback_tasks[:9]


def build_slot_hint(context_data):
    slot_date = (context_data.get('slot_date') or '').strip()
    slot_start = (context_data.get('slot_start') or '').strip()
    slot_end = (context_data.get('slot_end') or '').strip()

    if not slot_date:
        return ''

    slot_hint = f"The user has allocated time on {slot_date}"
    if slot_start and slot_end:
        slot_hint += f" from {slot_start} to {slot_end}"
    slot_hint += '. Use this date for recommended_date and keep the plan realistic for this window.'
    return slot_hint


def normalize_session_suggested_tasks(items, fallback_payload):
    normalized = normalize_suggested_tasks(items)[:9]
    if len(normalized) >= 3:
        return normalized

    return (fallback_payload.get('suggested_tasks') or [])[:9]


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


def build_subject_clarifying_question_fallback(section, subject_title):
    subject_label = 'goal' if section == 'goal' else 'idea'
    return {
        'response_markdown': 'Before I generate tasks, answer one sharp question so the plan becomes concrete.',
        'clarifying_question': (
            f'For this {subject_label}, what exact deliverable are you building next, and which main tool, stack, or method will you use?'
        ),
        'step': 1,
    }


def generate_subject_clarifying_question(section, subject_title, subject_description, extra_notes=''):
    system_prompt = (
        'You are ZenAI-Questioner. You do only step 1 of 2. '
        'Given one user goal or idea, ask EXACTLY ONE high-signal clarifying question that will unlock concrete implementation tasks. '
        'Ask about the exact deliverable, target artifact, tool, stack, method, environment, or execution path. '
        'Do not ask broad planning, motivational, or generic success questions. '
        'Keep the question under 28 words. '
        'Return ONLY valid JSON with this exact schema: '
        '{'
        '"response_markdown": string,'
        '"clarifying_question": string'
        '}'
    )

    api_key = config('ANTHROPIC_API_KEY', default='').strip()
    if Anthropic and api_key:
        client = Anthropic(api_key=api_key)
        prompt = {
            'section': section,
            'subject_title': subject_title,
            'subject_description': subject_description,
            'extra_notes': extra_notes,
            'today': date.today().isoformat(),
        }
        logger.info(
            '[ZenAI] generate_subject_clarifying_question | section=%s | subject=%r | model=claude-sonnet-4-6 | max_tokens=220',
            section, subject_title,
        )
        logger.debug('[ZenAI] subject_clarifying_question prompt payload: %s', json.dumps(prompt, ensure_ascii=False))
        _t0 = time.monotonic()
        try:
            response = client.messages.create(
                model='claude-sonnet-4-6',
                max_tokens=220,
                temperature=0.3,
                system=system_prompt,
                messages=[
                    {
                        'role': 'user',
                        'content': f"Ask the single best clarifying question for this subject: {json.dumps(prompt, ensure_ascii=False)}",
                    }
                ],
            )
        except Exception as exc:
            logger.exception('[ZenAI] generate_subject_clarifying_question API call failed: %s', exc)
            return build_subject_clarifying_question_fallback(section, subject_title)
        _elapsed = time.monotonic() - _t0
        logger.info(
            '[ZenAI] generate_subject_clarifying_question response received | elapsed=%.2fs | stop_reason=%s | input_tokens=%s | output_tokens=%s',
            _elapsed,
            getattr(response, 'stop_reason', 'unknown'),
            getattr(getattr(response, 'usage', None), 'input_tokens', '?'),
            getattr(getattr(response, 'usage', None), 'output_tokens', '?'),
        )
        if response.content:
            raw_text = response.content[0].text
            logger.debug('[ZenAI] generate_subject_clarifying_question raw response: %s', raw_text)
            parsed = parse_zenai_json_response(raw_text)
            if parsed:
                question = (parsed.get('clarifying_question') or '').strip()
                logger.info('[ZenAI] generate_subject_clarifying_question parsed | question=%r', question)
                if question:
                    return {
                        'response_markdown': (parsed.get('response_markdown') or '').strip(),
                        'clarifying_question': question,
                        'step': 1,
                    }
            else:
                logger.warning('[ZenAI] generate_subject_clarifying_question JSON parse failed | raw=%r', raw_text[:300])
        else:
            logger.warning('[ZenAI] generate_subject_clarifying_question returned empty content')

    logger.info('[ZenAI] generate_subject_clarifying_question falling back to static payload | section=%s | subject=%r', section, subject_title)
    return build_subject_clarifying_question_fallback(section, subject_title)


def build_subject_task_breakdown_fallback(section, subject_title, subject_description, clarifying_question, clarifying_answer, context_data):
    topic = ' '.join((clarifying_answer or subject_title or '').split()).strip()
    if not topic:
        topic = subject_title[:80]

    recommended_date = (context_data.get('slot_date') or date.today().isoformat()).strip() or date.today().isoformat()
    note_lines = []
    if section:
        note_lines.append(f'Subject type: {section}')
    if subject_description:
        note_lines.append(f'Subject description: {subject_description}')
    if clarifying_question:
        note_lines.append(f'Clarifying question: {clarifying_question}')
    if clarifying_answer:
        note_lines.append(f'Your answer: {clarifying_answer}')
    shared_note = '\n'.join(note_lines)[:600]

    return {
        'focus_target': f"Ship the first realistic working slice for: {topic[:80]}",
        'response_markdown': 'Using your answer, I turned the subject into concrete execution steps for this session.',
        'suggested_tasks': normalize_suggested_tasks([
            {
                'title': f"Lock the exact stack, inputs, and output for {topic[:120]}",
                'why': 'A concrete technical scope removes ambiguity before implementation begins.',
                'duration_minutes': 20,
                'is_rest': False,
                'cadence': 'one-off',
                'frequency_detail': 'One focused technical scoping pass',
                'recommended_date': recommended_date,
                'slot_start': '',
                'slot_end': '',
                'recurrence_type': 'none',
                'recurrence_days': '',
                'recurrence_end_date': '',
                'tag': 'W',
                'priority': 'H',
                'note': shared_note,
            },
            {
                'title': f"Set up the local environment and dependencies for {topic[:120]}",
                'why': 'A runnable environment makes it possible to test the core path immediately.',
                'duration_minutes': 25,
                'is_rest': False,
                'cadence': 'one-off',
                'frequency_detail': 'Install and configure the first working version',
                'recommended_date': recommended_date,
                'slot_start': '',
                'slot_end': '',
                'recurrence_type': 'none',
                'recurrence_days': '',
                'recurrence_end_date': '',
                'tag': 'W',
                'priority': 'H',
                'note': shared_note,
            },
            {
                'title': f"Build and test the first end-to-end slice for {topic[:120]}",
                'why': 'A full working slice exposes integration issues faster than abstract planning.',
                'duration_minutes': 40,
                'is_rest': False,
                'cadence': 'one-off',
                'frequency_detail': 'Implement the smallest usable version',
                'recommended_date': recommended_date,
                'slot_start': '',
                'slot_end': '',
                'recurrence_type': 'none',
                'recurrence_days': '',
                'recurrence_end_date': '',
                'tag': 'W',
                'priority': 'H',
                'note': shared_note,
            },
        ]),
        'step': 2,
    }


def generate_subject_task_breakdown_reply(section, subject_title, subject_description, clarifying_question, clarifying_answer, context_data):
    slot_hint = build_slot_hint(context_data)
    fallback_payload = build_subject_task_breakdown_fallback(
        section,
        subject_title,
        subject_description,
        clarifying_question,
        clarifying_answer,
        context_data,
    )

    system_prompt = (
        'You are ZenAI-Planner. You do only step 2 of 2. '
        'The user already has a goal or idea and has already answered one clarifying question. '
        'Generate a concrete execution plan with AT LEAST 3 and AT MOST 9 suggested tasks. '
        'Every task must be domain-specific, implementation-ready, and directly based on the subject plus the user answer. '
        'Prefer specific tools, frameworks, APIs, environments, file types, integrations, and verbs. '
        'Avoid vague tasks like "plan", "brainstorm", "define success", or "make prototype" unless they name a concrete artifact and tool. '
        'Order tasks by execution sequence. Keep scope realistic for a near-term working slice. '
        f'{slot_hint} '
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
        client = Anthropic(api_key=api_key, http_client=httpx.Client(timeout=105.0))
        prompt = {
            'section': section,
            'subject_title': subject_title,
            'subject_description': subject_description,
            'clarifying_question': clarifying_question,
            'clarifying_answer': clarifying_answer,
            'context': context_data,
            'today': date.today().isoformat(),
        }
        logger.info(
            '[ZenAI] generate_subject_task_breakdown_reply | section=%s | subject=%r | answer=%r | model=claude-sonnet-4-6 | max_tokens=4096',
            section, subject_title, clarifying_answer,
        )
        logger.debug('[ZenAI] subject_task_breakdown prompt payload: %s', json.dumps(prompt, ensure_ascii=False))
        _t0 = time.monotonic()
        try:
            response = client.messages.create(
                model='claude-sonnet-4-6',
                max_tokens=4096,
                temperature=0.4,
                system=system_prompt,
                messages=[
                    {
                        'role': 'user',
                        'content': f"Create the concrete execution tasks for this clarified subject: {json.dumps(prompt, ensure_ascii=False)}",
                    }
                ],
            )
        except Exception as exc:
            logger.exception('[ZenAI] generate_subject_task_breakdown_reply API call failed: %s', exc)
            return fallback_payload
        _elapsed = time.monotonic() - _t0
        _stop_reason = getattr(response, 'stop_reason', 'unknown')
        _usage = getattr(response, 'usage', None)
        logger.info(
            '[ZenAI] generate_subject_task_breakdown_reply response received | elapsed=%.2fs | stop_reason=%s | input_tokens=%s | output_tokens=%s',
            _elapsed,
            _stop_reason,
            getattr(_usage, 'input_tokens', '?'),
            getattr(_usage, 'output_tokens', '?'),
        )
        if _stop_reason == 'max_tokens':
            logger.warning(
                '[ZenAI] generate_subject_task_breakdown_reply TRUNCATED by max_tokens — raise limit or shorten prompt | '
                'output_tokens=%s | section=%s | subject=%r',
                getattr(_usage, 'output_tokens', '?'), section, subject_title,
            )
        if response.content:
            raw_text = response.content[0].text
            logger.debug('[ZenAI] generate_subject_task_breakdown_reply raw response: %s', raw_text)
            parsed = parse_zenai_json_response(raw_text)
            if parsed:
                tasks = normalize_session_suggested_tasks(parsed.get('suggested_tasks') or [], fallback_payload)
                logger.info('[ZenAI] generate_subject_task_breakdown_reply parsed | task_count=%d | focus_target=%r', len(tasks), (parsed.get('focus_target') or '')[:80])
                return {
                    'focus_target': (parsed.get('focus_target') or '').strip(),
                    'response_markdown': (parsed.get('response_markdown') or '').strip(),
                    'suggested_tasks': tasks,
                    'step': 2,
                }
            else:
                logger.warning('[ZenAI] generate_subject_task_breakdown_reply JSON parse failed | raw=%r', raw_text[:300])
        else:
            logger.warning('[ZenAI] generate_subject_task_breakdown_reply returned empty content')

    logger.info('[ZenAI] generate_subject_task_breakdown_reply falling back to static payload | section=%s | subject=%r', section, subject_title)
    return fallback_payload


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
        ""
        "CRITICAL WORKFLOW: "
        "1. First, ask EXACTLY ONE high-signal clarifying question that cuts through ambiguity. "
        "   - This question must be domain-specific and actionable. "
        "   - Example: Instead of 'Define the AI workflow', ask 'AI workflow for what? What tools (n8n, Make, Zapier)?'. "
        "   - Do NOT ask about success metrics or generic scope—ask about the specific domain, tools, methods to use. "
        "2. Then generate EXACTLY 2 domain-specific, fully actionable tasks that follow the clarification logic. "
        "   - Each task must reference specific tools, frameworks, libraries, or methods. "
        "   - Task 1: Setup/learning (e.g., 'Learn how to use n8n document ingestion connectors'). "
        "   - Task 2: Build/execute (e.g., 'Build and test a document ingestion workflow using n8n locally'). "
        "   - Never use generic titles like 'Plan', 'Define', 'Create a prototype'—be specific. "
        ""
        "Rules you must obey: "
        "1. Ask at most 1 clarifying question; it must be high-signal and domain-specific. "
        "2. Generate EXACTLY 2 suggested_tasks, never more. "
        "3. Each task must name specific tools, frameworks, methods, or actions (e.g., 'n8n', 'Docker', 'pytest', 'FastAPI'). "
        "4. Never produce generic advice. Every task must be a direct, actionable sub-step of the provided goal or idea. "
        "5. Fit all suggested tasks inside the user's stated time slot; sum of duration_minutes must not exceed the slot duration. "
        "6. If no time slot is given, default to 60-minute total effort. "
        "7. Order tasks by execution sequence (e.g., learn first, then build). "
        "8. Provide a 'focus_target' that is a single, measurable outcome for this session only — not the whole goal. "
        "9. Always include both ACTION tasks and REST/RECOVERY blocks when appropriate to avoid burnout. "
        f"{slot_hint} "
        "Return ONLY valid JSON with this exact schema: "
        "{"
        "\"focus_target\": string,"
        "\"response_markdown\": string,"
        "\"clarifying_questions\": string[] (exactly 1 question if scope is unclear; empty array if scope is clear),"
        "\"suggested_tasks\": ["
        "{"
        "\"title\": string (MUST be domain-specific with tools/methods named),"
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
        logger.info(
            '[ZenAI] generate_zenai_reply | user_prompt=%r | slot_date=%s | model=claude-sonnet-4-6 | max_tokens=900',
            user_prompt[:120], slot_date,
        )
        logger.debug('[ZenAI] generate_zenai_reply full message: %s', message[:600])
        _t0 = time.monotonic()
        try:
            response = client.messages.create(
                model='claude-sonnet-4-6',
                max_tokens=900,
                temperature=0.5,
                system=prompt,
                messages=[{'role': 'user', 'content': message}],
            )
        except Exception as exc:
            logger.exception('[ZenAI] generate_zenai_reply API call failed: %s', exc)
            return build_fallback_zen_payload(context_data)
        _elapsed = time.monotonic() - _t0
        logger.info(
            '[ZenAI] generate_zenai_reply response received | elapsed=%.2fs | stop_reason=%s | input_tokens=%s | output_tokens=%s',
            _elapsed,
            getattr(response, 'stop_reason', 'unknown'),
            getattr(getattr(response, 'usage', None), 'input_tokens', '?'),
            getattr(getattr(response, 'usage', None), 'output_tokens', '?'),
        )
        if response.content:
            raw_text = response.content[0].text
            logger.debug('[ZenAI] generate_zenai_reply raw response: %s', raw_text)
            parsed = parse_zenai_json_response(raw_text)
            if parsed:
                tasks = normalize_suggested_tasks(parsed.get('suggested_tasks') or [])
                logger.info(
                    '[ZenAI] generate_zenai_reply parsed | task_count=%d | clarifying_q_count=%d | focus_target=%r',
                    len(tasks), len(parsed.get('clarifying_questions') or []), (parsed.get('focus_target') or '')[:80],
                )
                return {
                    'focus_target': (parsed.get('focus_target') or '').strip(),
                    'response_markdown': (parsed.get('response_markdown') or '').strip(),
                    'clarifying_questions': parsed.get('clarifying_questions') or [],
                    'suggested_tasks': tasks,
                }
            else:
                logger.warning('[ZenAI] generate_zenai_reply JSON parse failed | raw=%r', raw_text[:300])
        else:
            logger.warning('[ZenAI] generate_zenai_reply returned empty content')
    else:
        logger.warning('[ZenAI] generate_zenai_reply skipped — no Anthropic client or API key configured')
        return build_fallback_zen_payload(context_data)


def build_idea_clarifying_question_fallback(idea):
    return {
        'response_markdown': 'Answer one sharp question first so the task list can become concrete and tool-specific.',
        'clarifying_question': (
            f'For "{idea.title[:80]}", what exact deliverable are you building first, and which main tool or stack will you use?'
        ),
    }


def generate_idea_clarifying_question(idea):
    system_prompt = (
        'You are ZenAI-IdeaQuestioner. You do only step 1 of 2. '
        'Given one idea, ask EXACTLY ONE high-signal clarifying question that will unlock concrete implementation tasks. '
        'The question must cut through ambiguity by asking about the exact deliverable, domain, tool, stack, method, target artifact, or operating environment. '
        'Do not ask broad planning, motivation, or success-metric questions. '
        'Keep the question under 28 words. '
        'Return ONLY valid JSON with this exact schema: '
        '{'
        '"response_markdown": string,'
        '"clarifying_question": string'
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
        logger.info(
            '[ZenAI] generate_idea_clarifying_question | idea_id=%s | idea_title=%r | model=claude-sonnet-4-6 | max_tokens=220',
            idea.id, idea.title,
        )
        logger.debug('[ZenAI] idea_clarifying_question prompt payload: %s', json.dumps(prompt, ensure_ascii=False))
        _t0 = time.monotonic()
        try:
            response = client.messages.create(
                model='claude-sonnet-4-6',
                max_tokens=220,
                temperature=0.3,
                system=system_prompt,
                messages=[
                    {
                        'role': 'user',
                        'content': f"Ask the single best clarifying question for this idea: {json.dumps(prompt, ensure_ascii=False)}",
                    }
                ],
            )
        except Exception as exc:
            logger.exception('[ZenAI] generate_idea_clarifying_question API call failed: %s', exc)
            return build_idea_clarifying_question_fallback(idea)
        _elapsed = time.monotonic() - _t0
        logger.info(
            '[ZenAI] generate_idea_clarifying_question response received | elapsed=%.2fs | stop_reason=%s | input_tokens=%s | output_tokens=%s',
            _elapsed,
            getattr(response, 'stop_reason', 'unknown'),
            getattr(getattr(response, 'usage', None), 'input_tokens', '?'),
            getattr(getattr(response, 'usage', None), 'output_tokens', '?'),
        )
        if response.content:
            raw_text = response.content[0].text
            logger.debug('[ZenAI] generate_idea_clarifying_question raw response: %s', raw_text)
            parsed = parse_zenai_json_response(raw_text)
            if parsed:
                question = (parsed.get('clarifying_question') or '').strip()
                logger.info('[ZenAI] generate_idea_clarifying_question parsed | question=%r', question)
                if question:
                    return {
                        'response_markdown': (parsed.get('response_markdown') or '').strip(),
                        'clarifying_question': question,
                    }
            else:
                logger.warning('[ZenAI] generate_idea_clarifying_question JSON parse failed | raw=%r', raw_text[:300])
        else:
            logger.warning('[ZenAI] generate_idea_clarifying_question returned empty content')

    logger.info('[ZenAI] generate_idea_clarifying_question falling back to static payload | idea_id=%s | idea_title=%r', idea.id, idea.title)
    return build_idea_clarifying_question_fallback(idea)


def build_idea_task_breakdown_fallback(idea, clarifying_question, clarifying_answer):
    topic = ' '.join((clarifying_answer or idea.title or '').split()).strip()
    if not topic:
        topic = idea.title[:80]

    answer_note = []
    if clarifying_question:
        answer_note.append(f'Clarifying question: {clarifying_question}')
    if clarifying_answer:
        answer_note.append(f'Your answer: {clarifying_answer}')
    shared_note = '\n'.join(answer_note)[:500]

    return {
        'focus_target': f"Ship the first runnable slice for: {topic[:80]}",
        'response_markdown': (
            'Using your answer, I translated the idea into concrete implementation steps. '
            'Complete these in sequence and add the ones you want directly to your calendar.'
        ),
        'suggested_tasks': normalize_suggested_tasks([
            {
                'title': f"Choose the exact toolchain and input/output contract for {topic[:120]}",
                'why': 'A precise stack and data contract remove ambiguity before implementation starts.',
                'duration_minutes': 20,
                'is_rest': False,
                'cadence': 'one-off',
                'frequency_detail': 'One technical scoping pass',
                'recommended_date': date.today().isoformat(),
                'slot_start': '',
                'slot_end': '',
                'recurrence_type': 'none',
                'recurrence_days': '',
                'recurrence_end_date': '',
                'tag': 'W',
                'priority': 'H',
                'note': shared_note,
            },
            {
                'title': f"Set up the local environment and dependencies for {topic[:120]}",
                'why': 'A runnable environment lets you validate the core flow immediately.',
                'duration_minutes': 25,
                'is_rest': False,
                'cadence': 'one-off',
                'frequency_detail': 'Install and configure the first stack version',
                'recommended_date': date.today().isoformat(),
                'slot_start': '',
                'slot_end': '',
                'recurrence_type': 'none',
                'recurrence_days': '',
                'recurrence_end_date': '',
                'tag': 'W',
                'priority': 'H',
                'note': shared_note,
            },
            {
                'title': f"Build and test the first end-to-end workflow for {topic[:120]}",
                'why': 'A complete first slice reveals integration gaps faster than abstract planning.',
                'duration_minutes': 40,
                'is_rest': False,
                'cadence': 'one-off',
                'frequency_detail': 'Implement the smallest working version',
                'recommended_date': date.today().isoformat(),
                'slot_start': '',
                'slot_end': '',
                'recurrence_type': 'none',
                'recurrence_days': '',
                'recurrence_end_date': '',
                'tag': 'W',
                'priority': 'H',
                'note': shared_note,
            },
        ]),
    }


def generate_idea_task_breakdown_reply(idea, clarifying_question, clarifying_answer):
    system_prompt = (
        'You are ZenAI-IdeaPlanner. You do only step 2 of 2. '
        'The user already has an idea and has already answered one clarifying question. '
        'Generate a concrete execution plan with AT LEAST 3 and AT MOST 9 suggested tasks. '
        'Every task must be domain-specific, implementation-ready, and directly based on the idea plus the user answer. '
        'Prefer specific tools, frameworks, APIs, environments, file types, integrations, and verbs. '
        'Avoid vague tasks like "plan", "brainstorm", "define success", or "make prototype" unless they name a concrete artifact and tool. '
        'Order tasks by execution sequence. Keep scope realistic for a near-term working slice. '
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
        client = Anthropic(api_key=api_key, http_client=httpx.Client(timeout=105.0))
        prompt = {
            'idea_title': idea.title,
            'idea_description': idea.description,
            'clarifying_question': clarifying_question,
            'clarifying_answer': clarifying_answer,
            'today': date.today().isoformat(),
        }
        logger.info(
            '[ZenAI] generate_idea_task_breakdown_reply | idea_id=%s | idea_title=%r | answer=%r | model=claude-sonnet-4-6 | max_tokens=4096',
            idea.id, idea.title, clarifying_answer,
        )
        logger.debug('[ZenAI] idea_task_breakdown prompt payload: %s', json.dumps(prompt, ensure_ascii=False))
        _t0 = time.monotonic()
        try:
            response = client.messages.create(
                model='claude-sonnet-4-6',
                max_tokens=4096,
                temperature=0.4,
                system=system_prompt,
                messages=[
                    {
                        'role': 'user',
                        'content': f"Create the concrete execution tasks for this clarified idea: {json.dumps(prompt, ensure_ascii=False)}",
                    }
                ],
            )
        except Exception as exc:
            logger.exception('[ZenAI] generate_idea_task_breakdown_reply API call failed: %s', exc)
            return build_idea_task_breakdown_fallback(idea, clarifying_question, clarifying_answer)
        _elapsed = time.monotonic() - _t0
        _stop_reason = getattr(response, 'stop_reason', 'unknown')
        _usage = getattr(response, 'usage', None)
        logger.info(
            '[ZenAI] generate_idea_task_breakdown_reply response received | elapsed=%.2fs | stop_reason=%s | input_tokens=%s | output_tokens=%s',
            _elapsed,
            _stop_reason,
            getattr(_usage, 'input_tokens', '?'),
            getattr(_usage, 'output_tokens', '?'),
        )
        if _stop_reason == 'max_tokens':
            logger.warning(
                '[ZenAI] generate_idea_task_breakdown_reply TRUNCATED by max_tokens — raise limit or shorten prompt | '
                'output_tokens=%s | idea_id=%s | idea_title=%r',
                getattr(_usage, 'output_tokens', '?'), idea.id, idea.title,
            )
        if response.content:
            raw_text = response.content[0].text
            logger.debug('[ZenAI] generate_idea_task_breakdown_reply raw response: %s', raw_text)
            parsed = parse_zenai_json_response(raw_text)
            if parsed:
                normalized_tasks = normalize_idea_suggested_tasks(
                    parsed.get('suggested_tasks') or [],
                    idea=idea,
                    clarifying_answer=clarifying_answer,
                )
                logger.info(
                    '[ZenAI] generate_idea_task_breakdown_reply parsed | task_count=%d | focus_target=%r',
                    len(normalized_tasks), (parsed.get('focus_target') or '')[:80],
                )
                if normalized_tasks:
                    return {
                        'focus_target': (parsed.get('focus_target') or '').strip(),
                        'response_markdown': (parsed.get('response_markdown') or '').strip(),
                        'suggested_tasks': normalized_tasks,
                    }
                else:
                    logger.warning('[ZenAI] generate_idea_task_breakdown_reply normalization returned 0 tasks, will fallback')
            else:
                logger.warning('[ZenAI] generate_idea_task_breakdown_reply JSON parse failed | raw=%r', raw_text[:300])
        else:
            logger.warning('[ZenAI] generate_idea_task_breakdown_reply returned empty content')

    logger.info('[ZenAI] generate_idea_task_breakdown_reply falling back to static payload | idea_id=%s | idea_title=%r', idea.id, idea.title)
    return build_idea_task_breakdown_fallback(idea, clarifying_question, clarifying_answer)

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
        assistant_payload = generate_subject_clarifying_question(
            section=section,
            subject_title=subject_title,
            subject_description=subject_description,
            extra_notes=extra_notes,
        )

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
        'step': assistant_payload.get('step') or 1,
        'clarifying_question': assistant_payload.get('clarifying_question') or '',
        'focus_target': assistant_payload.get('focus_target') or '',
        'clarifying_questions': assistant_payload.get('clarifying_questions') or [],
        'suggested_tasks': assistant_payload.get('suggested_tasks') or [],
    })


@login_required
@require_POST
def zenai_answer_clarifying_question(request):
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload.'}, status=400)

    section = (payload.get('section') or 'goal').strip()
    session_id = payload.get('session_id')
    goal_id = payload.get('goal_id')
    idea_id = payload.get('idea_id')
    slot_date = (payload.get('slot_date') or '').strip()
    slot_start = (payload.get('slot_start') or '').strip()
    slot_end = (payload.get('slot_end') or '').strip()
    extra_notes = (payload.get('notes') or '').strip()
    clarifying_question = (payload.get('clarifying_question') or '').strip()
    clarifying_answer = (payload.get('clarifying_answer') or '').strip()

    if not clarifying_answer:
        return JsonResponse({
            'success': False,
            'error': 'Please answer the clarifying question before generating tasks.',
        }, status=400)

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

    session = get_object_or_404(ZenChatSession, id=session_id, user=request.user)

    context_data = build_zen_context(request.user, section)
    context_data['slot_date'] = slot_date
    context_data['slot_start'] = slot_start
    context_data['slot_end'] = slot_end
    context_data['subject_title'] = subject_title
    context_data['subject_description'] = subject_description
    context_data['clarifying_question'] = clarifying_question
    context_data['clarifying_answer'] = clarifying_answer
    context_data['extra_notes'] = extra_notes

    answer_message = f"Clarification: {clarifying_answer}"
    ZenChatMessage.objects.create(
        session=session,
        role='user',
        content=answer_message,
        context_snapshot=context_data,
    )

    assistant_payload = generate_subject_task_breakdown_reply(
        section=section,
        subject_title=subject_title,
        subject_description=subject_description,
        clarifying_question=clarifying_question,
        clarifying_answer=clarifying_answer,
        context_data=context_data,
    )

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
        'step': assistant_payload.get('step') or 2,
        'focus_target': assistant_payload.get('focus_target') or '',
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
                'step': (item['context_snapshot'] or {}).get('assistant_structured', {}).get('step', ''),
                'clarifying_question': (item['context_snapshot'] or {}).get('assistant_structured', {}).get('clarifying_question', ''),
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
        date__range=[start_date, end_date],
        is_recurring_template=False,
    ).values('date').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(completed=True))
    )

    task_rows = Task.objects.filter(
        user=request.user,
        date__range=[start_date, end_date],
        is_recurring_template=False,
    ).values('date', 'title', 'completed', 'tag', 'priority').order_by('date', 'created_at')

    # Recurring templates — project onto each day of the month they recur on
    recurring_templates = Task.objects.filter(
        user=request.user,
        is_recurring_template=True,
    ).exclude(recurrence_type='none')

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
            'recurring': False,
        })

    # Inject recurring occurrences into task_lines (shown as projected, not completed)
    current = start_date
    while current <= end_date:
        for tmpl in recurring_templates:
            if tmpl.recurs_on(current):
                key = current.isoformat()
                # Avoid doubling if a real instance already exists for this day
                already = Task.objects.filter(
                    user=request.user,
                    date=current,
                    recurrence_source=tmpl,
                ).exists()
                if not already:
                    task_lines.setdefault(key, []).append({
                        'title': tmpl.title,
                        'completed': False,
                        'tag': tmpl.tag,
                        'priority': tmpl.priority,
                        'recurring': True,
                    })
        current += timedelta(days=1)

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

    # Determine the template and whether this task is part of a recurring series.
    # A task is "in a series" if it IS the template or is an instance spawned from one.
    template = None
    if task.is_recurring_template:
        template = task
    elif task.recurrence_source_id:
        template = task.recurrence_source

    is_recurring = template is not None

    if request.method == 'POST':
        form = TaskEditForm(request.POST, instance=task)
        if form.is_valid():
            scope = form.cleaned_data.get('edit_scope') or 'this_only'

            # Fields that get propagated to instances (everything except date).
            PROPAGATED_FIELDS = ['title', 'tag', 'priority', 'is_rest']
            # Fields that also update the template's recurrence settings.
            RECURRENCE_FIELDS = ['recurrence_type', 'recurrence_days', 'recurrence_end_date']

            if not is_recurring or scope == 'this_only':
                # ── Edit this task only ──────────────────────────────────────────
                # If this is a recurring instance, detach it so it becomes its own
                # standalone task (no longer follows the template).
                saved = form.save(commit=False)
                if task.recurrence_source_id and scope == 'this_only':
                    saved.recurrence_source = None
                    # Keep it non-template so it doesn't spawn new instances.
                    saved.is_recurring_template = False
                    saved.recurrence_type = 'none'
                    saved.recurrence_days = ''
                    saved.recurrence_end_date = None
                saved.save()
                messages.success(request, 'Task updated (this occurrence only).')

            elif scope in ('this_and_future', 'all'):
                # ── Propagate to template + a subset of instances ────────────────
                # Step 1: save the edited task normally.
                form.save()

                # Step 2: update the template's shared fields & recurrence settings.
                if template:
                    for field in PROPAGATED_FIELDS + RECURRENCE_FIELDS:
                        setattr(template, field, getattr(task, field))
                    # Re-derive recurrence_days string (form.save already stored it on task).
                    template.recurrence_days = task.recurrence_days
                    template.save(update_fields=PROPAGATED_FIELDS + RECURRENCE_FIELDS)

                # Step 3: find all instances to update.
                if template:
                    instances_qs = Task.objects.filter(
                        user=request.user,
                        recurrence_source=template,
                    ).exclude(pk=task.pk)   # already saved above

                    if scope == 'this_and_future':
                        instances_qs = instances_qs.filter(date__gte=task.date)

                    # Bulk-update shared fields (keep each instance's own date).
                    update_kwargs = {
                        field: getattr(task, field)
                        for field in PROPAGATED_FIELDS
                    }
                    instances_qs.update(**update_kwargs)

                label = 'this and all future occurrences' if scope == 'this_and_future' else 'all occurrences'
                messages.success(request, f'Task updated for {label}.')

            return redirect('daily_view', year=task.date.year, month=task.date.month, day=task.date.day)
    else:
        form = TaskEditForm(instance=task)

    context = {
        'form': form,
        'task': task,
        'is_recurring': is_recurring,
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
    payload = generate_idea_clarifying_question(idea)

    return JsonResponse({
        'success': True,
        'idea': {
            'id': idea.id,
            'title': idea.title,
        },
        'response_markdown': payload.get('response_markdown', '').strip(),
        'clarifying_question': payload.get('clarifying_question', '').strip(),
        'step': 1,
    })


@login_required
@require_POST
def idea_ai_breakdown_tasks(request, idea_id):
    idea = get_object_or_404(Idea, id=idea_id, user=request.user)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload.'}, status=400)

    clarifying_question = (payload.get('clarifying_question') or '').strip()
    clarifying_answer = (payload.get('clarifying_answer') or '').strip()

    if not clarifying_answer:
        return JsonResponse({
            'success': False,
            'error': 'Please answer the clarifying question before generating tasks.',
        }, status=400)

    task_payload = generate_idea_task_breakdown_reply(
        idea,
        clarifying_question=clarifying_question,
        clarifying_answer=clarifying_answer,
    )

    focus_target = task_payload.get('focus_target', '').strip()
    if not focus_target:
        focus_target = strip_tags(idea.title)[:120]

    suggested_tasks = (task_payload.get('suggested_tasks') or [])[:9]

    return JsonResponse({
        'success': True,
        'idea': {
            'id': idea.id,
            'title': idea.title,
        },
        'step': 2,
        'focus_target': focus_target,
        'response_markdown': task_payload.get('response_markdown', '').strip(),
        'suggested_tasks': suggested_tasks,
        'task_count': len(suggested_tasks),
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

