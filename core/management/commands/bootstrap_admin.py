"""Tworzy konto administracyjne z sekretem przekazanym przez środowisko."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Tworzy konto początkowe, jeżeli nie istnieje żaden superużytkownik."

    def handle(self, *args, **options):
        user_model = get_user_model()
        initial_password = settings.INITIAL_ADMIN_PASSWORD
        default_password_users = [
            user
            for user in user_model.objects.filter(is_superuser=True)
            if user.check_password("admin")
        ]
        if default_password_users:
            if not initial_password:
                raise CommandError("Brakuje DJANGO_INITIAL_ADMIN_PASSWORD.")
            for user in default_password_users:
                user.set_password(initial_password)
                user.save(update_fields=["password"])
            self.stdout.write("Zastąpiono niebezpieczne hasło początkowe.")
            return
        if user_model.objects.filter(is_superuser=True).exists():
            self.stdout.write("Konto administratora już istnieje.")
            return
        if not initial_password:
            raise CommandError("Brakuje DJANGO_INITIAL_ADMIN_PASSWORD.")
        user_model.objects.create_superuser(
            username=settings.INITIAL_ADMIN_USERNAME,
            password=initial_password,
        )
        self.stdout.write("Utworzono konto administratora.")
