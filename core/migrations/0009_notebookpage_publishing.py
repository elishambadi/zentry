# Generated migration for public notebook publishing

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_notebookblock_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='notebookpage',
            name='is_public',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='notebookpage',
            name='published_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
