# core/migrations/0005_goal_image_journalentry_ordering.py

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_task_recurrence_fields'),
    ]

    operations = [
        # Add the missing image field to Goal (never added in any prior migration)
        migrations.AddField(
            model_name='goal',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='goal_images/'),
        ),

        # Sync JournalEntry ordering with models.py (was ['-date'], now ['-date', '-created_at'])
        migrations.AlterModelOptions(
            name='journalentry',
            options={'ordering': ['-date', '-created_at']},
        ),
    ]
