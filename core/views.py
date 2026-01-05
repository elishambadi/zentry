
# core/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db.models import Q, Count, Prefetch
from datetime import date, datetime, timedelta
import calendar
from .models import Task, JournalEntry, SubTask, Note, Link, Idea, Goal, TaskGoal, DailyMood
from .forms import (TaskForm, TaskEditForm, JournalForm, SubTaskForm, NoteForm, 
                    LinkForm, IdeaForm, GoalForm, DailyMoodForm)

def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'core/home.html')

@login_required
def dashboard(request):
    today = date.today()
    return redirect('daily_view', year=today.year, month=today.month, day=today.day)

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

