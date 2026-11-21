"""Modèle de données LogIT.

Règle centrale : une trace ne se modifie jamais. Une fiche (Intervention) est une suite
de versions (Version). Corriger, marquer réalisée ou annuler ajoute une version.
Les tables Intervention, Version, Version.elements et AuditEvent sont protégées
au niveau de PostgreSQL (voir la migration 0002) : UPDATE et DELETE y sont refusés.
"""
from django.conf import settings
from django.db import models

from .chain import canonical_hash


class Element(models.Model):
    EQUIPMENT = "equipment"
    SERVICE = "service"
    KINDS = [(EQUIPMENT, "Équipement"), (SERVICE, "Service")]

    name = models.CharField("nom", max_length=120, unique=True)
    kind = models.CharField("type", max_length=12, choices=KINDS)
    description = models.CharField("description", max_length=250, blank=True)
    archived = models.BooleanField("archivé", default=False)

    class Meta:
        ordering = ["kind", "name"]

    def __str__(self):
        return self.name


class Profile(models.Model):
    """État de sécurité d'un compte (modifiable : ce n'est pas une trace)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="profile")
    must_change_password = models.BooleanField(default=True)
    totp_required = models.BooleanField(default=False)
    totp_secret = models.CharField(max_length=64, blank=True)
    totp_confirmed = models.BooleanField(default=False)
    totp_last_step = models.BigIntegerField(default=0)
    recovery_codes = models.JSONField(default=list, blank=True)  # empreintes des codes de secours
    failed_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)


class Intervention(models.Model):
    """En-tête immuable d'une fiche. Le contenu est porté par ses versions."""

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    recorded_at = models.DateTimeField("date d’enregistrement")
    # Fiche de retour arrière : la fiche d'origine qu'elle annule.
    rollback_of = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="rollbacks")

    class Meta:
        ordering = ["-pk"]

    @property
    def current(self):
        if not hasattr(self, "_current"):
            self._current = self.versions.order_by("-number").first()
        return self._current


class Version(models.Model):
    PLANNED, NORMAL, URGENT = "planned", "normal", "urgent"
    KINDS = [(PLANNED, "Planifiée"), (NORMAL, "Normale"), (URGENT, "Urgence")]
    STATUS_PLANNED, STATUS_DONE, STATUS_CANCELLED = "planned", "done", "cancelled"
    STATUSES = [(STATUS_PLANNED, "Planifiée"), (STATUS_DONE, "Réalisée"), (STATUS_CANCELLED, "Annulée")]
    CREATED, CORRECTED, COMPLETED, CANCELLED = "created", "corrected", "completed", "cancelled"
    ACTIONS = [(CREATED, "Création"), (CORRECTED, "Correction"), (COMPLETED, "Marquée réalisée"),
               (CANCELLED, "Annulation")]

    # Champs à remplir pour qu'une fiche soit complète (une urgence peut être enregistrée sans).
    REQUIRED_FOR_COMPLETE = ["reason", "impact", "verification", "rollback"]
    CONTENT_FIELDS = ["kind", "status", "title", "occurred_at", "change", "reason", "impact",
                      "verification", "rollback", "before_state", "after_state"]

    intervention = models.ForeignKey(Intervention, on_delete=models.PROTECT, related_name="versions")
    number = models.PositiveIntegerField()
    action = models.CharField(max_length=12, choices=ACTIONS)
    note = models.CharField("motif", max_length=300, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    recorded_at = models.DateTimeField("date d’enregistrement")

    kind = models.CharField("type", max_length=10, choices=KINDS)
    status = models.CharField("statut", max_length=10, choices=STATUSES)
    title = models.CharField("titre", max_length=200)
    occurred_at = models.DateTimeField("date de l’intervention")
    elements = models.ManyToManyField(Element, verbose_name="éléments concernés", related_name="versions")
    change = models.TextField("modification")
    reason = models.TextField("motif", blank=True)
    impact = models.TextField("impact", blank=True)
    verification = models.TextField("vérifications", blank=True)
    rollback = models.TextField("retour arrière", blank=True)
    before_state = models.TextField("état avant", blank=True)
    after_state = models.TextField("état après", blank=True)

    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["intervention", "number"]
        constraints = [models.UniqueConstraint(fields=["intervention", "number"], name="version_unique_number")]

    @property
    def incomplete(self):
        return self.status != self.STATUS_CANCELLED and any(not getattr(self, f).strip() for f in self.REQUIRED_FOR_COMPLETE)

    @property
    def late_entry(self):
        from datetime import timedelta
        first = self.intervention.recorded_at
        limit = timedelta(minutes=settings.LOGIT_LATE_ENTRY_MINUTES)
        return self.kind != self.PLANNED and first - self.occurred_at > limit

    def payload(self, element_ids, attachment_digests=()):
        data = {f: getattr(self, f) for f in self.CONTENT_FIELDS}
        data.update(
            intervention=self.intervention_id, number=self.number, action=self.action, note=self.note,
            author=self.author_id, recorded_at=self.recorded_at, elements=sorted(element_ids),
        )
        # Clés ajoutées en 2.1 : présentes seulement si utilisées, pour que les empreintes 2.0 restent valides.
        if attachment_digests:
            data["attachments"] = sorted(attachment_digests)
        if self.number == 1 and self.intervention.rollback_of_id:
            data["rollback_of"] = self.intervention.rollback_of_id
        return data

    def compute_hash(self, element_ids=None, attachment_digests=None):
        if element_ids is None:
            element_ids = list(self.elements.values_list("pk", flat=True))
        if attachment_digests is None:
            attachment_digests = [a.sha256 for a in self.attachments.all()]
        return canonical_hash(self.prev_hash, self.payload(element_ids, attachment_digests))


class Attachment(models.Model):
    """Capture jointe à une fiche, ajoutée avec une version. Immuable comme les versions."""

    MAX_BYTES = 5 * 1024 * 1024
    MAX_PER_INTERVENTION = 10
    TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}

    intervention = models.ForeignKey(Intervention, on_delete=models.PROTECT, related_name="attachments")
    version = models.ForeignKey(Version, on_delete=models.PROTECT, related_name="attachments")
    uploader = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    recorded_at = models.DateTimeField()
    name = models.CharField(max_length=200)
    content_type = models.CharField(max_length=20)
    size = models.PositiveIntegerField()
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    data = models.BinaryField()

    class Meta:
        ordering = ["pk"]


class ReadMarker(models.Model):
    """Dernière version vue par un utilisateur, pour « depuis ma dernière visite » (modifiable)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="read_marker")
    last_version_id = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class AuditEvent(models.Model):
    """Journal de sécurité et d'administration : connexions, comptes, référentiel."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    recorded_at = models.DateTimeField()
    action = models.CharField(max_length=60)
    target = models.CharField(max_length=200, blank=True)
    details = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["-pk"]

    def payload(self):
        return {"actor": self.actor_id, "recorded_at": self.recorded_at, "action": self.action,
                "target": self.target, "details": self.details, "ip": self.ip}

    def compute_hash(self):
        return canonical_hash(self.prev_hash, self.payload())
