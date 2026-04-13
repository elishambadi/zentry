from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_goal_image_journalentry_ordering'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userpreference',
            name='default_page',
            field=models.CharField(
                choices=[
                    ('pomodoro', 'Pomodoro Focus'),
                    ('daily', 'Daily View'),
                    ('calendar', 'Calendar'),
                    ('ideas', 'Ideas Board'),
                    ('goals', 'Goals'),
                    ('weekly', 'Weekly Review'),
                    ('monthly', 'Monthly Review'),
                ],
                default='pomodoro',
                max_length=20,
            ),
        ),
    ]
