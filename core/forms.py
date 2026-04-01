# core/forms.py
from django import forms
from .models import Task, JournalEntry, SubTask, Note, Link, Idea, Goal, DailyMood, UserPreference


WEEKDAY_CHOICES = [
    ('0', 'Mon'),
    ('1', 'Tue'),
    ('2', 'Wed'),
    ('3', 'Thu'),
    ('4', 'Fri'),
    ('5', 'Sat'),
    ('6', 'Sun'),
]

class TaskForm(forms.ModelForm):
    recurrence_days = forms.MultipleChoiceField(
        required=False,
        choices=WEEKDAY_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'flex flex-wrap gap-2 text-xs'}),
    )

    class Meta:
        model = Task
        fields = ['title', 'tag', 'priority', 'is_rest', 'recurrence_type', 'recurrence_days', 'recurrence_end_date']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'Enter task...'
            }),
            'tag': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent'
            }),
            'priority': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent'
            }),
            'is_rest': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-green-600 border-gray-300 rounded'
            }),
            'recurrence_type': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent'
            }),
            'recurrence_end_date': forms.DateInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'type': 'date'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.recurrence_days:
            self.initial['recurrence_days'] = [part for part in self.instance.recurrence_days.split(',') if part.strip()]

    def clean(self):
        cleaned = super().clean()
        recurrence_type = cleaned.get('recurrence_type', 'none')
        recurrence_days = cleaned.get('recurrence_days') or []

        if recurrence_type == 'custom' and not recurrence_days:
            self.add_error('recurrence_days', 'Select at least one weekday for custom recurrence.')

        if recurrence_type != 'custom':
            cleaned['recurrence_days'] = []

        if recurrence_type == 'none':
            cleaned['recurrence_end_date'] = None

        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        selected_days = self.cleaned_data.get('recurrence_days') or []
        instance.recurrence_days = ','.join(selected_days)
        if commit:
            instance.save()
        return instance


EDIT_SCOPE_CHOICES = [
    ('this_only',       'This task only'),
    ('this_and_future', 'This and all future occurrences'),
    ('all',             'All occurrences (past and future)'),
]


class TaskEditForm(TaskForm):
    edit_scope = forms.ChoiceField(
        choices=EDIT_SCOPE_CHOICES,
        initial='this_only',
        required=False,
        widget=forms.RadioSelect(attrs={'class': 'mr-2'}),
        label='Apply changes to',
    )

    class Meta(TaskForm.Meta):
        fields = ['title', 'tag', 'priority', 'date', 'is_rest', 'recurrence_type', 'recurrence_days', 'recurrence_end_date']
        widgets = {
            **TaskForm.Meta.widgets,
            'date': forms.DateInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'type': 'date'
            }),
        }


class SubTaskForm(forms.ModelForm):
    class Meta:
        model = SubTask
        fields = ['title']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'Enter subtask...'
            })
        }


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'Add a note...',
                'rows': 3
            })
        }


class LinkForm(forms.ModelForm):
    class Meta:
        model = Link
        fields = ['url', 'title']
        widgets = {
            'url': forms.URLInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'https://example.com'
            }),
            'title': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'Link title (optional)'
            })
        }


class IdeaForm(forms.ModelForm):
    class Meta:
        model = Idea
        fields = ['title', 'description']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'Enter idea...'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'Describe your idea...',
                'rows': 4
            })
        }


class GoalForm(forms.ModelForm):
    class Meta:
        model = Goal
        fields = ['title', 'description', 'image', 'term', 'target_date']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'Enter goal...'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'Describe your goal...',
                'rows': 3
            }),
            'image': forms.ClearableFileInput(attrs={
                'class': 'w-full text-sm text-gray-600'
            }),
            'term': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent'
            }),
            'target_date': forms.DateInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'type': 'date'
            })
        }


class DailyMoodForm(forms.ModelForm):
    class Meta:
        model = DailyMood
        fields = ['mood', 'notes']
        widgets = {
            'mood': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'How are you feeling today?',
                'rows': 2
            })
        }


class JournalForm(forms.ModelForm):
    class Meta:
        model = JournalEntry
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'w-full h-64 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'Dear diary, today I...',
                'id': 'journal-editor'
            })
        }


class UserPreferenceForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = ['default_page', 'monthly_books', 'favorite_authors']
        widgets = {
            'default_page': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent'
            }),
            'monthly_books': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'Books you are reading this month (one per line)...',
                'rows': 4
            }),
            'favorite_authors': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent',
                'placeholder': 'Favorite authors, thinkers, or references...',
                'rows': 3
            }),
        }