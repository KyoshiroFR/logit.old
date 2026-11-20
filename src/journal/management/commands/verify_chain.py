from django.core.management.base import BaseCommand, CommandError

from journal.chain import record_event, verify
from journal.models import AuditEvent, Version


class Command(BaseCommand):
    help = "Vérifie l'intégrité des chaînes d'empreintes (fiches et journal de sécurité)."

    def handle(self, *args, **options):
        problems = verify()
        record_event("integrity_checked", details={"anomalies": len(problems), "origine": "ligne de commande"})
        if problems:
            for problem in problems:
                self.stderr.write(problem)
            raise CommandError(f"{len(problems)} anomalie(s) détectée(s).")
        self.stdout.write(f"Intégrité vérifiée : {Version.objects.count()} versions de fiches, "
                          f"{AuditEvent.objects.count()} événements du journal. Aucune anomalie.")
