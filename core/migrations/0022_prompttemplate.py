from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0021_institutionimportrun_news_source_index")]

    operations = [
        migrations.CreateModel(
            name="PromptTemplate",
            fields=[
                ("key", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("content", models.TextField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["key"]},
        )
    ]
