
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
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.title} ({self.get_tag_display()})"
    
    def get_tag_color(self):
        return self.TAG_COLORS.get(self.tag, 'bg-gray-100 text-gray-800')

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
