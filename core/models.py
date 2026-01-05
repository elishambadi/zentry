
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
