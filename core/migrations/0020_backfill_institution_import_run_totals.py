from django.db import migrations
from django.db.models import F


def backfill_totals(apps, schema_editor):
    del schema_editor
    run_model = apps.get_model("core", "InstitutionImportRun")
    run_model.objects.filter(institutions_total=0).update(
        institutions_total=F("institutions_processed")
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0019_institutionimportevent_import_progress")]

    operations = [migrations.RunPython(backfill_totals, migrations.RunPython.noop)]
