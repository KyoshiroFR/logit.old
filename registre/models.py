from django.conf import settings
from django.db import models
from django.utils import timezone


class AccountSecurity(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    must_change_password = models.BooleanField(default=False)
    totp_required = models.BooleanField(default=False)


class Equipment(models.Model):
    name = models.CharField("nom", max_length=120, unique=True)
    archived = models.BooleanField("archivé", default=False)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "équipement"
        ordering = ["name"]


class Service(models.Model):
    name = models.CharField("nom", max_length=120, unique=True)
    archived = models.BooleanField("archivé", default=False)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


class Intervention(models.Model):
    title = models.CharField("titre", max_length=180)
    occurred_at = models.DateTimeField("date de l’intervention", default=timezone.now)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    equipment = models.ForeignKey(Equipment, verbose_name="équipement", on_delete=models.PROTECT)
    service = models.ForeignKey(Service, verbose_name="service", on_delete=models.PROTECT, blank=True, null=True)
    impacted_services = models.ManyToManyField(
        Service, verbose_name="services concernés", related_name="impacting_interventions", blank=True,
    )
    change = models.TextField("modification")
    reason = models.TextField("motif")
    impact = models.TextField("impact")
    verification = models.TextField("vérification")
    rollback = models.TextField("retour arrière")
    reference = models.CharField("référence au journal technique", max_length=200, blank=True)
    before_state = models.TextField("état avant", blank=True)
    after_state = models.TextField("état après", blank=True)

    class Meta:
        ordering = ["-occurred_at", "-pk"]

    def snapshot(self):
        snapshot = {
            field.verbose_name: str(
                timezone.localtime(value).strftime("%d/%m/%Y à %H:%M")
                if field.name == "occurred_at" else value or ""
            )
            for field in self._meta.fields
            if field.name not in {"id", "author"}
            for value in [getattr(self, field.name)]
        }
        snapshot["services concernés"] = ", ".join(service.name for service in self.impacted_services.all())
        return snapshot


class Revision(models.Model):
    intervention = models.ForeignKey(Intervention, on_delete=models.PROTECT, related_name="revisions")
    editor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    corrected_at = models.DateTimeField(auto_now_add=True)
    changes = models.JSONField()
    reason = models.CharField(max_length=250)

    class Meta:
        ordering = ["-corrected_at", "-pk"]


class Attachment(models.Model):
    intervention = models.ForeignKey(Intervention, on_delete=models.PROTECT, related_name="attachments")
    uploader = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=20)
    data = models.BinaryField()

    class Meta:
        ordering = ["pk"]
