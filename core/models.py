
# core/models.py
from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse
from datetime import date

class Task(models.Model):
    TAGS = [
        ('P', 'Physical'),
        ('S', 'Spiritual'),
        ('W', 'Work'),
        ('R', 'Relationships'),
        ('B', 'Bonus'),
    ]
    
    PRIORITY_CHOICES = [
        ('L', 'Low'),
        ('M', 'Medium'),
        ('H', 'High'),
        ('U', 'Urgent'),
    ]

    RECURRENCE_CHOICES = [
        ('none', 'One-time'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('custom', 'Custom days'),
    ]
    
    TAG_COLORS = {
        'P': 'bg-green-100 text-green-800',
        'S': 'bg-purple-100 text-purple-800',
        'W': 'bg-blue-100 text-blue-800',
        'R': 'bg-pink-100 text-pink-800',
        'B': 'bg-yellow-100 text-yellow-800',
    }
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField()
    title = models.CharField(max_length=200)
    tag = models.CharField(max_length=1, choices=TAGS)
    priority = models.CharField(max_length=1, choices=PRIORITY_CHOICES, default='M')
    is_rest = models.BooleanField(default=False)
    recurrence_type = models.CharField(max_length=20, choices=RECURRENCE_CHOICES, default='none')
    recurrence_days = models.CharField(max_length=32, blank=True)
    recurrence_end_date = models.DateField(null=True, blank=True)
    is_recurring_template = models.BooleanField(default=False)
    recurrence_source = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='recurrence_instances')
    completed = models.BooleanField(default=False)
    carried_over = models.BooleanField(default=False)
    overdue_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.title} ({self.get_tag_display()})"
    
    def get_tag_color(self):
        return self.TAG_COLORS.get(self.tag, 'bg-gray-100 text-gray-800')

    def get_recurrence_days_set(self):
        values = set()
        for part in (self.recurrence_days or '').split(','):
            cleaned = part.strip()
            if cleaned.isdigit():
                values.add(int(cleaned))
        return values

    def recurs_on(self, target_date):
        if self.recurrence_type == 'none' or target_date < self.date:
            return False

        if self.recurrence_end_date and target_date > self.recurrence_end_date:
            return False

        if self.recurrence_type == 'daily':
            return True

        if self.recurrence_type == 'weekly':
            return target_date.weekday() == self.date.weekday()

        if self.recurrence_type == 'custom':
            return target_date.weekday() in self.get_recurrence_days_set()

        return False


class SubTask(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='subtasks')
    title = models.CharField(max_length=200)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"SubTask: {self.title}"


class Note(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='notes', null=True, blank=True)
    subtask = models.ForeignKey(SubTask, on_delete=models.CASCADE, related_name='notes', null=True, blank=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        if self.task:
            return f"Note for task: {self.task.title}"
        elif self.subtask:
            return f"Note for subtask: {self.subtask.title}"
        return "Note"


class Link(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='links')
    url = models.URLField(max_length=500)
    title = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Link: {self.title or self.url}"


class Idea(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    converted_to_task = models.BooleanField(default=False)
    task = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True, related_name='source_idea')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.title


class Goal(models.Model):
    TERM_CHOICES = [
        ('S', 'Short-term'),
        ('L', 'Long-term'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='goal_images/', null=True, blank=True)
    term = models.CharField(max_length=1, choices=TERM_CHOICES)
    target_date = models.DateField(null=True, blank=True)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} ({self.get_term_display()})"


class TaskGoal(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='task_goals')
    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name='goal_tasks')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['task', 'goal']
    
    def __str__(self):
        return f"{self.task.title} -> {self.goal.title}"


class DailyMood(models.Model):
    MOOD_CHOICES = [
        ('VH', 'Very Happy'),
        ('H', 'Happy'),
        ('N', 'Neutral'),
        ('S', 'Sad'),
        ('VS', 'Very Sad'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField()
    mood = models.CharField(max_length=2, choices=MOOD_CHOICES)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'date']
        ordering = ['-date']
    
    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.get_mood_display()}"


class JournalEntry(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField()
    content = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'date']
        ordering = ['-date']
    
    def __str__(self):
        return f"Journal - {self.user.username} - {self.date}"


class UserPreference(models.Model):
    DEFAULT_PAGE_CHOICES = [
        ('daily', 'Daily View'),
        ('calendar', 'Calendar'),
        ('ideas', 'Ideas Board'),
        ('goals', 'Goals'),
        ('weekly', 'Weekly Review'),
        ('monthly', 'Monthly Review'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='preferences')
    default_page = models.CharField(max_length=20, choices=DEFAULT_PAGE_CHOICES, default='daily')
    monthly_books = models.TextField(blank=True)
    favorite_authors = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preferences - {self.user.username}"


class ZenChatSession(models.Model):
    SECTION_CHOICES = [
        ('general', 'General'),
        ('task', 'Task'),
        ('idea', 'Idea'),
        ('goal', 'Goal'),
        ('review', 'Review'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='zen_chat_sessions')
    section = models.CharField(max_length=20, choices=SECTION_CHOICES, default='general')
    title = models.CharField(max_length=200, default='New ZenAI Chat')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.user.username} - {self.title} ({self.section})"


class ZenChatMessage(models.Model):
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]

    session = models.ForeignKey(ZenChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    context_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.session_id} - {self.role}"
