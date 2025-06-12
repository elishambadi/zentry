
# core/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db.models import Q, Count
from datetime import date, datetime, timedelta
import calendar
from .models import Task, JournalEntry
from .forms import TaskForm, JournalForm

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
    
    # Handle journal form submission
    if request.method == 'POST' and 'journal_content' in request.POST:
        journal_form = JournalForm(request.POST, instance=journal_entry)
        if journal_form.is_valid():
            journal_form.save()
            messages.success(request, 'Journal saved successfully!')
            return redirect('daily_view', year=year, month=month, day=day)
    else:
        journal_form = JournalForm(instance=journal_entry)
    
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
    
    # Get tasks for the day
    tasks = Task.objects.filter(user=request.user, date=selected_date)
    
    # Navigation dates
    prev_date = selected_date - timedelta(days=1)
    next_date = selected_date + timedelta(days=1)
    
    context = {
        'selected_date': selected_date,
        'journal_form': journal_form,
        'task_form': task_form,
        'tasks': tasks,
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
    start_of_month = date(today.year, today.month, 1)
    if today.month == 12:
        end_of_month = date(today.year + 1, 1, 1) - timedelta(days=1)
    else:
        end_of_month = date(today.year, today.month + 1, 1) - timedelta(days=1)
    
    # Get month's tasks
    tasks = Task.objects.filter(
        user=request.user,
        date__range=[start_of_month, end_of_month]
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
    
    context = {
        'start_of_month': start_of_month,
        'end_of_month': end_of_month,
        'month_name': calendar.month_name[today.month],
        'total_tasks': total_tasks,
        'completed_tasks': completed_tasks,
        'completion_rate': completion_rate,
        'tag_stats': tag_stats,
        'daily_stats': daily_stats,
    }
    
    return render(request, 'core/monthly_review.html', context)
