# core/migrations/0004_task_recurrence_fields.py
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_userpreference_zenchatsession_zenchatmessage'),
    ]

    operations = [
        # Use SeparateDatabaseAndState throughout so that:
        #   - Django's migration state is always updated (state_operations)
        #   - The SQL uses ADD COLUMN IF NOT EXISTS, safe on both fresh and
        #     existing databases where these columns were added another way.

        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE core_task ADD COLUMN IF NOT EXISTS recurrence_type varchar(20) NOT NULL DEFAULT 'none';",
                    reverse_sql="ALTER TABLE core_task DROP COLUMN IF EXISTS recurrence_type;",
                ),
            ],
            state_operations=[
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
            ],
        ),

        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE core_task ADD COLUMN IF NOT EXISTS recurrence_days varchar(32) NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE core_task DROP COLUMN IF EXISTS recurrence_days;",
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='task',
                    name='recurrence_days',
                    field=models.CharField(blank=True, max_length=32),
                ),
            ],
        ),

        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE core_task ADD COLUMN IF NOT EXISTS recurrence_end_date date NULL;",
                    reverse_sql="ALTER TABLE core_task DROP COLUMN IF EXISTS recurrence_end_date;",
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='task',
                    name='recurrence_end_date',
                    field=models.DateField(blank=True, null=True),
                ),
            ],
        ),

        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE core_task ADD COLUMN IF NOT EXISTS is_recurring_template boolean NOT NULL DEFAULT false;",
                    reverse_sql="ALTER TABLE core_task DROP COLUMN IF EXISTS is_recurring_template;",
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='task',
                    name='is_recurring_template',
                    field=models.BooleanField(default=False),
                ),
            ],
        ),

        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE core_task ADD COLUMN IF NOT EXISTS recurrence_source_id integer NULL REFERENCES core_task(id) ON DELETE SET NULL;",
                    reverse_sql="ALTER TABLE core_task DROP COLUMN IF EXISTS recurrence_source_id;",
                ),
            ],
            state_operations=[
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
            ],
        ),

        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE core_task ADD COLUMN IF NOT EXISTS is_rest boolean NOT NULL DEFAULT false;",
                    reverse_sql="ALTER TABLE core_task DROP COLUMN IF EXISTS is_rest;",
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='task',
                    name='is_rest',
                    field=models.BooleanField(default=False),
                ),
            ],
        ),
    ]
