from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0018_institutionimportrun")]

    operations = [
        migrations.AddField(
            model_name="institutionimportrun",
            name="current_action",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="institutionimportrun",
            name="current_institution",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="institutionimportrun",
            name="institutions_total",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="InstitutionImportEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("message", models.CharField(max_length=500)),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="core.institutionimportrun")),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
    ]
