from decimal import Decimal

from django.db import migrations, models


def calculate_decimal_scores(apps, schema_editor):  # pragma: no cover
    idea_model = apps.get_model("core", "Idea")
    weights = {
        "Nowatorstwo": Decimal("0.3"),
        "Wartość innowacji": Decimal("0.3"),
        "Replikowalność": Decimal("0.2"),
        "Potencjał oddziaływania": Decimal("0.2"),
    }
    for idea in idea_model.objects.all().iterator():
        details = idea.innovation_details
        values = [details.get(name) for name in weights]
        idea.innovation_score = (
            None
            if any(value is None for value in values)
            else sum(Decimal(str(details[name])) * weight for name, weight in weights.items()).quantize(
                Decimal("0.1")
            )
        )
        idea.save(update_fields=["innovation_score"])


class Migration(migrations.Migration):
    dependencies = [("core", "0012_institution_type_choices")]

    operations = [
        migrations.AlterField(
            model_name="idea",
            name="innovation_score",
            field=models.DecimalField(
                blank=True,
                decimal_places=1,
                max_digits=4,
                null=True,
                verbose_name="Wynik innowacyjności",
            ),
        ),
        migrations.RunPython(calculate_decimal_scores, migrations.RunPython.noop),
    ]
