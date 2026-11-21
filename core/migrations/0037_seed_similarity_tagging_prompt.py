import json
from pathlib import Path

from django.db import migrations


def seed_prompt(apps, schema_editor):
    del schema_editor
    prompt_model = apps.get_model("core", "PromptTemplate")
    path = Path(__file__).resolve().parents[1] / "data" / "prompt_templates.json"
    content = json.loads(path.read_text(encoding="utf-8"))["similarity_tagging"]
    prompt_model.objects.get_or_create(key="similarity_tagging", defaults={"content": content})


class Migration(migrations.Migration):
    dependencies = [("core", "0036_similaritytag_idea_similarity_tags")]

    operations = [migrations.RunPython(seed_prompt, migrations.RunPython.noop)]
