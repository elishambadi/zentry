from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_notebooks_feature'),
    ]

    operations = [
        migrations.AddField(
            model_name='notebookblock',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='notebook_blocks/'),
        ),
    ]
