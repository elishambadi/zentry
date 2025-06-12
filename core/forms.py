# core/forms.py
from django import forms
from .models import Task, JournalEntry

class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['title', 'tag']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'Enter task...'
            }),
            'tag': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent'
            })
        }

class JournalForm(forms.ModelForm):
    class Meta:
        model = JournalEntry
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'w-full h-64 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'Dear diary, today I...'
            })
        }