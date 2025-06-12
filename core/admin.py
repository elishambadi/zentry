# core/admin.py
from django.contrib import admin
from .models import Task, JournalEntry

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'date', 'tag', 'completed', 'created_at']
    list_filter = ['tag', 'completed', 'date']
    search_fields = ['title', 'user__username']
    date_hierarchy = 'date'

@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'created_at', 'updated_at']
    list_filter = ['date']
    search_fields = ['user__username', 'content']
    date_hierarchy = 'date'
