from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0010_institution_locality")]
    operations = [
        migrations.AlterField(
            model_name="institution",
            name="news_url",
            field=models.URLField(blank=True, verbose_name="Adres URL aktualności"),
        ),
    ]
