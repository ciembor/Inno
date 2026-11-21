from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0020_backfill_institution_import_run_totals")]

    operations = [
        migrations.AddField(
            model_name="institutionimportrun",
            name="news_source_index",
            field=models.PositiveIntegerField(default=0),
        )
    ]
