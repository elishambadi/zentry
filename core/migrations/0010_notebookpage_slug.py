# Generated migration for adding slug field to NotebookPage

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_notebookpage_publishing'),
    ]

    operations = [
        migrations.AddField(
            model_name='notebookpage',
            name='slug',
            field=models.SlugField(blank=True, max_length=200, null=True, unique=True),
        ),
    ]
