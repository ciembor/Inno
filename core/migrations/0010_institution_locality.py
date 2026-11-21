from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0009_institutionnewssource")]
    operations = [
        migrations.AddField(
            model_name="institution", name="locality",
            field=models.ForeignKey(
                to="core.locality", on_delete=django.db.models.deletion.PROTECT,
                null=True, blank=True, related_name="institutions", verbose_name="Miejscowość",
            ),
        ),
    ]
