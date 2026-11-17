from django import forms
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import render

from .models import Equipment, Service

admin.site.site_header = "Administration LogIT"


@admin.register(Equipment, Service)
class ReferenceAdmin(admin.ModelAdmin):
    list_display = ("name", "status")
    list_filter = ("archived",)
    search_fields = ("name",)
    actions = ("archive", "restore")

    @admin.display(description="Statut", ordering="archived")
    def status(self, obj):
        return "Archivé" if obj.archived else "Actif"

    def construct_change_message(self, request, form, formsets, add=False):
        message = super().construct_change_message(request, form, formsets, add)
        if "archived" in form.changed_data:
            status = "Archivé" if form.cleaned_data["archived"] else "Réactivé"
            if add:
                message.append({"changed": {"fields": [status]}})
            else:
                for entry in message:
                    fields = entry.get("changed", {}).get("fields", [])
                    if "archivé" in fields:
                        fields[fields.index("archivé")] = status
        return message

    def _set_archived(self, request, queryset, archived):
        count = 0
        with transaction.atomic():
            for obj in queryset.filter(archived=not archived):
                obj.archived = archived
                obj.save(update_fields=["archived"])
                self.log_change(request, obj, "Archivage" if archived else "Réactivation")
                count += 1
        self.message_user(request, f"Nombre d’éléments {'archivés' if archived else 'réactivés'} : {count}.")

    @admin.action(permissions=["change"], description="Archiver les éléments sélectionnés")
    def archive(self, request, queryset):
        self._set_archived(request, queryset, True)

    @admin.action(permissions=["change"], description="Réactiver les éléments sélectionnés")
    def restore(self, request, queryset):
        self._set_archived(request, queryset, False)


class AuditFilters(forms.Form):
    author = forms.ModelChoiceField(
        label="Auteur", required=False, empty_label="Tous les auteurs",
        queryset=get_user_model().objects.filter(logentry__isnull=False).distinct().order_by("username"),
    )
    start = forms.DateField(label="Du", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="Au", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("start") and cleaned.get("end") and cleaned["start"] > cleaned["end"]:
            self.add_error("end", "La date de fin doit être égale ou postérieure à la date de début.")
        return cleaned


def audit_log(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    filters = AuditFilters(request.GET)
    entries = LogEntry.objects.select_related("user", "content_type").order_by("-action_time", "-pk")
    if filters.is_valid():
        for field, lookup in (("author", "user"), ("start", "action_time__date__gte"), ("end", "action_time__date__lte")):
            if value := filters.cleaned_data[field]:
                entries = entries.filter(**{lookup: value})
    else:
        entries = entries.none()
    page = Paginator(entries, 30).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "admin/audit_log.html", {
        **admin.site.each_context(request),
        "title": "Journal d’administration", "filters": filters, "page": page, "query": query.urlencode(),
    })
