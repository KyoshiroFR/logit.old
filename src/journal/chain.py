"""Chaîne d'empreintes : chaque trace contient l'empreinte SHA-256 de la précédente.

Modifier ou retirer une trace directement dans la base casse la chaîne, ce que
`manage.py verify_chain` (ou `logit verify`) détecte.
"""
import hashlib
import ipaddress
import json
from datetime import datetime, timezone as dt_timezone

from django.db import connection, transaction
from django.utils import timezone

GENESIS = "0" * 64
LOCK_VERSIONS = 7_740_001
LOCK_AUDIT = 7_740_002


def _default(value):
    if isinstance(value, datetime):
        return value.astimezone(dt_timezone.utc).isoformat(timespec="microseconds")
    raise TypeError(type(value))


def canonical_hash(prev_hash, payload):
    body = json.dumps(payload, default=_default, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{prev_hash}\n{body}".encode()).hexdigest()


def _lock(key):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


class ConcurrentEdit(Exception):
    """La fiche a reçu une autre version pendant la saisie."""


def append_version(version, element_ids):
    """Enregistre une version en fin de chaîne. Doit être appelée dans une transaction."""
    from .models import Version

    assert transaction.get_connection().in_atomic_block
    _lock(LOCK_VERSIONS)
    expected = Version.objects.filter(intervention_id=version.intervention_id).count() + 1
    if version.number != expected:
        raise ConcurrentEdit
    last = Version.objects.order_by("-pk").values_list("hash", flat=True).first()
    version.prev_hash = last or GENESIS
    version.recorded_at = timezone.now()
    version.hash = version.compute_hash(element_ids)
    version.save(force_insert=True)
    version.elements.set(element_ids)
    return version


def client_ip(request):
    """IP du client. Le reverse proxy de LogIT (seul à joindre l'application) pose X-Real-IP."""
    if request is None:
        return None
    for candidate in (request.META.get("HTTP_X_REAL_IP", ""), request.META.get("REMOTE_ADDR", "")):
        try:
            return str(ipaddress.ip_address(candidate.strip()))
        except ValueError:
            continue
    return None


def record_event(action, actor=None, target="", details=None, request=None):
    from .models import AuditEvent

    with transaction.atomic():
        _lock(LOCK_AUDIT)
        last = AuditEvent.objects.order_by("-pk").values_list("hash", flat=True).first()
        event = AuditEvent(
            actor=actor if actor and actor.is_authenticated else None, recorded_at=timezone.now(),
            action=action, target=str(target)[:200], details=details or {},
            ip=client_ip(request), prev_hash=last or GENESIS,
        )
        event.hash = event.compute_hash()
        event.save(force_insert=True)
        return event


def verify():
    """Renvoie la liste des anomalies (vide si les deux chaînes sont intactes)."""
    from .models import AuditEvent, Version

    problems = []
    previous = GENESIS
    for version in Version.objects.order_by("pk").prefetch_related("elements"):
        ids = [e.pk for e in version.elements.all()]
        if version.prev_hash != previous:
            problems.append(f"Version #{version.pk} : maillon manquant ou réordonné avant cette version.")
        if version.compute_hash(ids) != version.hash:
            problems.append(f"Version #{version.pk} (fiche {version.intervention_id}, v{version.number}) : contenu altéré.")
        previous = version.hash
    previous = GENESIS
    for event in AuditEvent.objects.order_by("pk"):
        if event.prev_hash != previous:
            problems.append(f"Journal #{event.pk} : maillon manquant ou réordonné avant cet événement.")
        if event.compute_hash() != event.hash:
            problems.append(f"Journal #{event.pk} ({event.action}) : contenu altéré.")
        previous = event.hash
    return problems
