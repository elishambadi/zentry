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
    path('task/toggle/<int:task_id>/', views.toggle_task, name='toggle_task'),
    path('task/delete/<int:task_id>/', views.delete_task, name='delete_task'),
]
