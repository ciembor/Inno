"""Tworzy startowe konto bez nadpisywania zmienionego hasła."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Tworzy admin/admin, jeżeli konto admin jeszcze nie istnieje."

    def handle(self, *args, **options):
        user, created = get_user_model().objects.get_or_create(
            username="admin", defaults={"is_staff": True, "is_superuser": True}
        )
        if created:
            user.set_password("admin")
            user.save(update_fields=["password"])
        self.stdout.write("Utworzono konto admin." if created else "Konto admin już istnieje.")
