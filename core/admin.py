# core/admin.py
from django.contrib import admin
from .models import Task, JournalEntry, SubTask, Note, Link, Idea, Goal, TaskGoal, DailyMood


class SubTaskInline(admin.TabularInline):
    model = SubTask
    extra = 1


class NoteInline(admin.TabularInline):
    model = Note
    extra = 0


class LinkInline(admin.TabularInline):
    model = Link
    extra = 0


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'date', 'tag', 'priority', 'completed', 'carried_over', 'created_at']
    list_filter = ['tag', 'priority', 'completed', 'carried_over', 'date']
    search_fields = ['title', 'user__username']
    date_hierarchy = 'date'
    inlines = [SubTaskInline, NoteInline, LinkInline]


@admin.register(SubTask)
class SubTaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'task', 'completed', 'created_at']
    list_filter = ['completed', 'created_at']
    search_fields = ['title', 'task__title']


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ['get_parent', 'content_preview', 'created_at']
    list_filter = ['created_at']
    search_fields = ['content', 'task__title', 'subtask__title']
    
    def get_parent(self, obj):
        if obj.task:
            return f"Task: {obj.task.title}"
        elif obj.subtask:
            return f"SubTask: {obj.subtask.title}"
        return "No parent"
    get_parent.short_description = 'Parent'
    
    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = 'Content'


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ['title', 'url', 'task', 'created_at']
    list_filter = ['created_at']
    search_fields = ['title', 'url', 'task__title']


@admin.register(Idea)
class IdeaAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'converted_to_task', 'task', 'created_at']
    list_filter = ['converted_to_task', 'created_at']
    search_fields = ['title', 'description', 'user__username']


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'term', 'target_date', 'completed', 'created_at']
    list_filter = ['term', 'completed', 'created_at']
    search_fields = ['title', 'description', 'user__username']


@admin.register(TaskGoal)
class TaskGoalAdmin(admin.ModelAdmin):
    list_display = ['task', 'goal', 'created_at']
    list_filter = ['created_at']
    search_fields = ['task__title', 'goal__title']


@admin.register(DailyMood)
class DailyMoodAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'mood', 'created_at']
    list_filter = ['mood', 'date']
    search_fields = ['user__username', 'notes']
    date_hierarchy = 'date'


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'created_at', 'updated_at']
    list_filter = ['date']
    search_fields = ['user__username', 'content']
    date_hierarchy = 'date'
