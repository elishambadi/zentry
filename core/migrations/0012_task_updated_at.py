from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_task_dead'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
    ]