"""Rend les traces immuables au niveau de PostgreSQL.

Même un accès direct à la base avec le compte de l'application, ou une faille dans
le code, ne permet ni de modifier ni de supprimer une fiche, une version ou une
entrée du journal. Seul un superutilisateur PostgreSQL pourrait retirer ces
déclencheurs, et la chaîne d'empreintes le révélerait.
"""
from django.db import migrations

TABLES = ["journal_intervention", "journal_version", "journal_version_elements", "journal_auditevent"]

FUNCTION = """
CREATE OR REPLACE FUNCTION logit_refuse_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'LogIT : la table % est en ajout seul (% refusé)', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
"""


def forward_sql():
    statements = [FUNCTION]
    for table in TABLES:
        statements.append(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION logit_refuse_change();"
        )
        statements.append(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            f"FOR EACH STATEMENT EXECUTE FUNCTION logit_refuse_change();"
        )
    return statements


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ("Contributeur", "Lecteur"):
        Group.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [("journal", "0001_initial"), ("auth", "0012_alter_user_first_name_max_length")]

    operations = [
        migrations.RunSQL(forward_sql(), reverse_sql=migrations.RunSQL.noop),
        migrations.RunPython(create_groups, migrations.RunPython.noop),
    ]
