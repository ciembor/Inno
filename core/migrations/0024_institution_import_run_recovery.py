from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0023_seed_prompt_templates")]

    operations = [
        migrations.AddField(
            model_name="institutionimportrun",
            name="heartbeat_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="institutionimportrun",
            name="retry_after",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
