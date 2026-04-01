# core/migrations/0004_task_recurrence_fields.py
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_userpreference_zenchatsession_zenchatmessage'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='recurrence_type',
            field=models.CharField(
                choices=[
                    ('none', 'One-time'),
                    ('daily', 'Daily'),
                    ('weekly', 'Weekly'),
                    ('custom', 'Custom days'),
                ],
                default='none',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='task',
            name='recurrence_days',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='task',
            name='recurrence_end_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='task',
            name='is_recurring_template',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='task',
            name='recurrence_source',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='recurrence_instances',
                to='core.task',
            ),
        ),
    ]
