import secrets

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from registre.models import AccountSecurity


class Command(BaseCommand):
    help = "Crée le compte d’administration initial si la base ne contient aucun compte."

    def handle(self, *args, **options):
        users = get_user_model().objects
        username = "admin-logit"
        # In LogIT, SQLite acquires the write lock at the start of this transaction.
        with transaction.atomic():
            if users.exists():
                self.stdout.write("Un compte existe déjà. Aucun compte créé.")
                return
            password = secrets.token_urlsafe(24)
            admin = users.create_superuser(username=username, password=password)
            AccountSecurity.objects.create(user=admin, must_change_password=True)

        self.stdout.write(f"Identifiant {username}")
        self.stdout.write(f"Mot de passe temporaire {password}")
