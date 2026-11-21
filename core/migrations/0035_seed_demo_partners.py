from django.db import migrations


def seed_demo_partners(apps, schema_editor):
    partner_model = apps.get_model("core", "PartnerOrganization")
    tag_model = apps.get_model("core", "PartnerTag")
    tags = {
        key: tag_model.objects.get_or_create(key=key, defaults={"name": name})[0]
        for key, name in (
            ("pilotaz", "Pilotaż"),
            ("badania", "Badania i walidacja"),
            ("wdrozenie", "Wdrożenie"),
            ("finansowanie", "Finansowanie"),
            ("transfer", "Transfer wiedzy"),
        )
    }
    partners = (
        (
            "Partner demonstracyjny — laboratorium pilotażowe",
            "implementation",
            "Wpis demonstracyjny: pomaga zaplanować oraz przetestować pilotaż rozwiązania.",
            ("pilotaz", "wdrozenie"),
        ),
        (
            "Partner demonstracyjny — zespół badawczy",
            "expert",
            "Wpis demonstracyjny: wspiera walidację metody, badania i ocenę rezultatów.",
            ("badania", "pilotaz"),
        ),
        (
            "Partner demonstracyjny — program wsparcia",
            "funder",
            "Wpis demonstracyjny: pomaga przygotować projekt do finansowania i dalszego transferu.",
            ("finansowanie", "transfer"),
        ),
    )
    for name, organization_type, description, tag_keys in partners:
        partner, _ = partner_model.objects.get_or_create(
            name=name,
            defaults={
                "organization_type": organization_type,
                "description": description,
                "areas": "Dane demonstracyjne",
                "is_active": True,
            },
        )
        partner.tags.add(*(tags[key] for key in tag_keys))


class Migration(migrations.Migration):
    dependencies = [("core", "0034_partnertag_partnerorganization_idea_partner_needs")]

    operations = [migrations.RunPython(seed_demo_partners, migrations.RunPython.noop)]
