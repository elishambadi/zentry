# core/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('day/<int:year>/<int:month>/<int:day>/', views.daily_view, name='daily_view'),
    path('calendar/', views.calendar_view, name='calendar'),
    path('review/weekly/', views.weekly_review, name='weekly_review'),
    path('review/monthly/', views.monthly_review, name='monthly_review'),
    
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
    path('idea/convert/<int:idea_id>/', views.convert_idea_to_task, name='convert_idea_to_task'),
    path('idea/delete/<int:idea_id>/', views.delete_idea, name='delete_idea'),
    
    # Goals
    path('goals/', views.goals_list, name='goals_list'),
    path('goal/toggle/<int:goal_id>/', views.toggle_goal, name='toggle_goal'),
    path('goal/delete/<int:goal_id>/', views.delete_goal, name='delete_goal'),
    path('task/<int:task_id>/goal/attach/', views.attach_goal_to_task, name='attach_goal_to_task'),
    path('task/<int:task_id>/goal/<int:goal_id>/detach/', views.detach_goal_from_task, name='detach_goal_from_task'),
]
