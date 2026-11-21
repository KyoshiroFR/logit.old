"""Ce qu'affiche un bloc d'intervention : état, résumé Action / Cible / Avant / Après, retour arrière."""
from datetime import date

from django.utils import timezone

from .models import Version

NO_IMPACT = {"", "aucun", "aucune", "néant", "neant", "ras", "-", "n/a", "na", "rien"}


def first_line(text, limit=90):
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line if len(line) <= limit else line[: limit - 1] + "…"
    return ""


def state_of(version, rolled_back=False):
    """Badge principal : (code, libellé). Un seul état, le plus important pour l'enquête."""
    if version.status == Version.STATUS_CANCELLED:
        return "cancelled", "Annulée"
    if rolled_back:
        return "rolledback", "Rollback effectué"
    if version.status == Version.STATUS_PLANNED:
        return ("running", "En cours") if version.occurred_at <= timezone.now() else ("planned", "Planifiée")
    if version.incomplete:
        return "incomplete", "À compléter"
    return "applied", "Appliqué"


def has_impact(version):
    return version.impact.strip().lower().rstrip(".") not in NO_IMPACT


def card(version, rolled_back=False, today=None):
    today = today or date.today()
    author = version.intervention.created_by
    profile = getattr(author, "profile", None)
    away = profile.away_until if profile and profile.away_until and profile.away_until >= today else None
    state, label = state_of(version, rolled_back)
    elements = list(version.elements.all())
    return {
        "v": version, "state": state, "state_label": label,
        "urgent": version.kind == Version.URGENT,
        "watch": state in ("applied", "incomplete", "running") and has_impact(version),
        "author": author, "author_away": away,
        "target": ", ".join(e.name for e in elements) or "—",
        "before": first_line(version.before_state), "after": first_line(version.after_state),
        "rollback": first_line(version.rollback, 160),
        "rollback_available": bool(version.rollback.strip()) and state not in ("cancelled", "rolledback"),
    }
