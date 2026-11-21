from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="idea",
            name="email",
            field=models.EmailField(default="", max_length=254, verbose_name="Adres e-mail"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="idea",
            name="submitter_name",
            field=models.CharField(default="", max_length=160, verbose_name="Imię i nazwisko"),
            preserve_default=False,
        ),
    ]
