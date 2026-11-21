"""« Depuis ma dernière visite » : ce que les autres ont enregistré depuis la dernière lecture."""
from django.db.models import Max

from .models import ReadMarker, Version

LIMIT = 50
SENSITIVE = ("impact", "rollback")


def marker_of(user):
    return ReadMarker.objects.filter(user=user).first()


def unseen_versions(user):
    marker = marker_of(user)
    versions = Version.objects.exclude(author=user)
    if marker:
        versions = versions.filter(pk__gt=marker.last_version_id)
    else:
        versions = versions.filter(recorded_at__gte=user.date_joined)
    return versions


def unseen_count(user):
    return unseen_versions(user).count()


def unseen_items(user):
    versions = list(unseen_versions(user).select_related("author", "intervention", "intervention__rollback_of")
                    .order_by("-pk")[:LIMIT])
    previous = {}
    corrected = [v for v in versions if v.action == Version.CORRECTED]
    if corrected:
        lookups = Version.objects.filter(intervention__in=[v.intervention_id for v in corrected])
        for v in lookups:
            previous[(v.intervention_id, v.number)] = v
    items = []
    for v in versions:
        if v.action == Version.CREATED:
            label = "Retour arrière" if v.intervention.rollback_of_id else "Nouvelle fiche"
        else:
            label = v.get_action_display()
        changed = []
        if v.action == Version.CORRECTED:
            before = previous.get((v.intervention_id, v.number - 1))
            if before:
                changed = [Version._meta.get_field(f).verbose_name for f in SENSITIVE
                           if getattr(before, f) != getattr(v, f)]
        items.append({"version": v, "label": label, "sensitive": changed})
    return items


def mark_read(user, upto):
    latest = Version.objects.aggregate(m=Max("pk"))["m"] or 0
    upto = min(int(upto), latest)
    marker, _ = ReadMarker.objects.get_or_create(user=user)
    if upto > marker.last_version_id:
        marker.last_version_id = upto
        marker.save(update_fields=["last_version_id", "updated_at"])
