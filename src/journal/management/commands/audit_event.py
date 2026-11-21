"""Inscrit une opération d'exploitation (mise à jour, restauration…) dans le journal de sécurité."""
import json

from django.core.management.base import BaseCommand

from journal.chain import record_event


class Command(BaseCommand):
    help = "Ajoute un événement au journal de sécurité depuis la ligne de commande."

    def add_arguments(self, parser):
        parser.add_argument("action")
        parser.add_argument("--target", default="")
        parser.add_argument("--details", default="{}", help="JSON")

    def handle(self, *args, **options):
        details = json.loads(options["details"])
        details.setdefault("origine", "ligne de commande")
        record_event(options["action"], target=options["target"], details=details)
