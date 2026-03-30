# core/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('preferences/', views.preferences_view, name='preferences'),
    path('day/<int:year>/<int:month>/<int:day>/', views.daily_view, name='daily_view'),
    path('day/<int:year>/<int:month>/<int:day>/journal/', views.daily_journal_editor, name='daily_journal_editor'),
    path('calendar/', views.calendar_view, name='calendar'),
    path('review/weekly/', views.weekly_review, name='weekly_review'),
    path('review/monthly/', views.monthly_review, name='monthly_review'),
    path('zenai/', views.zenai_panel, name='zenai_panel'),
    path('zenai/send/', views.zenai_send_message, name='zenai_send_message'),
    path('zenai/sessions/', views.zenai_sessions, name='zenai_sessions'),
    path('zenai/session/<int:session_id>/', views.zenai_session_messages, name='zenai_session_messages'),
    path('zenai/task/add/', views.zenai_add_suggested_task, name='zenai_add_suggested_task'),
    path('zenai/calendar-tasks/', views.zenai_calendar_tasks, name='zenai_calendar_tasks'),
    path('manifest.json', views.pwa_manifest, name='pwa_manifest'),
    path('service-worker.js', views.service_worker, name='service_worker'),
    
    # Task management
    path('task/toggle/<int:task_id>/', views.toggle_task, name='toggle_task'),
    path('task/delete/<int:task_id>/', views.delete_task, name='delete_task'),
    path('task/edit/<int:task_id>/', views.edit_task, name='edit_task'),
    path('task/carry/<int:task_id>/', views.carry_task_to_next_day, name='carry_task_to_next_day'),
    
    # SubTask management
    path('task/<int:task_id>/subtask/add/', views.add_subtask, name='add_subtask'),
    path('subtask/toggle/<int:subtask_id>/', views.toggle_subtask, name='toggle_subtask'),
    path('subtask/delete/<int:subtask_id>/', views.delete_subtask, name='delete_subtask'),
    
    # Note management
    path('task/<int:task_id>/note/add/', views.add_note_to_task, name='add_note_to_task'),
    path('subtask/<int:subtask_id>/note/add/', views.add_note_to_subtask, name='add_note_to_subtask'),
    path('note/delete/<int:note_id>/', views.delete_note, name='delete_note'),
    
    # Link management
    path('task/<int:task_id>/link/add/', views.add_link_to_task, name='add_link_to_task'),
    path('link/delete/<int:link_id>/', views.delete_link, name='delete_link'),
    
    # Ideas board
    path('ideas/', views.ideas_board, name='ideas_board'),
    path('idea/<int:idea_id>/breakdown/', views.idea_ai_breakdown, name='idea_ai_breakdown'),
    path('idea/convert/<int:idea_id>/', views.convert_idea_to_task, name='convert_idea_to_task'),
    path('idea/delete/<int:idea_id>/', views.delete_idea, name='delete_idea'),
    
    # Goals
    path('goals/', views.goals_list, name='goals_list'),
    path('goal/edit/<int:goal_id>/', views.edit_goal, name='edit_goal'),
    path('goal/toggle/<int:goal_id>/', views.toggle_goal, name='toggle_goal'),
    path('goal/delete/<int:goal_id>/', views.delete_goal, name='delete_goal'),
    path('task/<int:task_id>/goal/attach/', views.attach_goal_to_task, name='attach_goal_to_task'),
    path('task/<int:task_id>/goal/<int:goal_id>/detach/', views.detach_goal_from_task, name='detach_goal_from_task'),
]
