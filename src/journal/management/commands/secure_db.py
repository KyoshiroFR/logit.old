"""Crée le compte PostgreSQL de l'application et lui donne le strict nécessaire.

À lancer avec le compte propriétaire, après les migrations. Idempotent.
Le compte de l'application peut lire et ajouter des traces, mais pas les modifier
ni les supprimer, et ne peut pas changer la structure de la base.
"""
import os

from django.core.management.base import BaseCommand
from django.db import connection
from psycopg import sql

APPEND_ONLY = ["journal_intervention", "journal_version", "journal_version_elements", "journal_auditevent"]
READ_ONLY = ["django_migrations", "django_content_type", "auth_permission"]


class Command(BaseCommand):
    help = "Applique les droits minimaux du compte PostgreSQL de l'application."

    def handle(self, *args, **options):
        role = os.environ["LOGIT_DB_APP_USER"]
        password = os.environ["LOGIT_DB_APP_PASSWORD"]
        database = connection.settings_dict["NAME"]
        r = sql.Identifier(role)
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
            verb = "ALTER" if cur.fetchone() else "CREATE"
            cur.execute(sql.SQL(verb + " ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}")
                        .format(r, sql.Literal(password)).as_string(cur.connection))
            cur.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)).as_string(cur.connection))
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), r).as_string(cur.connection))
            cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(r).as_string(cur.connection))
            cur.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(r).as_string(cur.connection))
            cur.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(r).as_string(cur.connection))
            for table in APPEND_ONLY + READ_ONLY:
                cur.execute(sql.SQL("REVOKE UPDATE, DELETE, TRUNCATE ON {} FROM {}").format(sql.Identifier(table), r).as_string(cur.connection))
            for table in READ_ONLY:
                cur.execute(sql.SQL("REVOKE INSERT ON {} FROM {}").format(sql.Identifier(table), r).as_string(cur.connection))
            cur.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(r).as_string(cur.connection))
        self.stdout.write(f"Droits appliqués au compte {role} (ajout seul sur : {', '.join(APPEND_ONLY)}).")
