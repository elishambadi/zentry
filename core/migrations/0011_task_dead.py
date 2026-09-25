from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_notebookpage_slug'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='dead_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='task',
            name='is_dead',
            field=models.BooleanField(default=False),
        ),
    ]