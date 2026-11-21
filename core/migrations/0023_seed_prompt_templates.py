"""Wprowadza do bazy początkowy komplet promptów LLM."""

import json
from pathlib import Path

from django.db import migrations


def seed_prompt_templates(apps, schema_editor):
    """Tworzy wyłącznie brakujące prompty, nie nadpisując zmian administratora."""
    prompt_template = apps.get_model("core", "PromptTemplate")
    seed_path = Path(__file__).resolve().parents[1] / "data" / "prompt_templates.json"
    prompts = json.loads(seed_path.read_text(encoding="utf-8"))
    for key, content in prompts.items():
        prompt_template.objects.get_or_create(key=key, defaults={"content": content})


class Migration(migrations.Migration):
    dependencies = [("core", "0022_prompttemplate")]

    operations = [migrations.RunPython(seed_prompt_templates, migrations.RunPython.noop)]
