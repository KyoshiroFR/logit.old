"""Crée le premier administrateur si aucun compte n'existe. Affiche son mot de passe temporaire une seule fois."""
import secrets

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from journal.chain import record_event
from journal.models import Profile


class Command(BaseCommand):
    help = "Crée le compte admin-logit sur une base vide."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin-logit")

    def handle(self, *args, **options):
        users = get_user_model().objects
        with transaction.atomic():
            if users.exists():
                self.stdout.write("EXISTANT")
                return
            password = secrets.token_urlsafe(18)
            admin = users.create_superuser(options["username"], password=password)
            Profile.objects.create(user=admin, must_change_password=True, totp_required=True)
            record_event("user_created", target=admin.username,
                         details={"rôle": "admin", "origine": "installation", "totp obligatoire": True})
        self.stdout.write(f"IDENTIFIANT={admin.username}")
        self.stdout.write(f"MOT_DE_PASSE={password}")
