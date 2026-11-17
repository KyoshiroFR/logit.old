from difflib import unified_diff
from itertools import islice
import re

from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.vary import vary_on_headers
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from PIL import Image, UnidentifiedImageError

from .models import Attachment, Equipment, Intervention, Revision, Service


QUOTED_VALUE = re.compile(r'("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')')


def configuration_lines(before, after):
    old_lines, new_lines = before.splitlines(), after.splitlines()
    numbered_before = [(number, "", QUOTED_VALUE.split(line)) for number, line in enumerate(old_lines, 1)]
    if not before or not after or old_lines == new_lines:
        return numbered_before, [(number, "", QUOTED_VALUE.split(line)) for number, line in enumerate(new_lines, 1)]
    diff = unified_diff(old_lines, new_lines, n=max(len(old_lines), len(new_lines)), lineterm="")
    old_number = new_number = 1
    numbered_after = []
    for line in islice(diff, 3, None):
        marker, content = line[0], line[1:]
        number = old_number if marker == "-" else new_number
        numbered_after.append((number, marker.strip(), QUOTED_VALUE.split(content)))
        old_number += marker != "+"
        new_number += marker != "-"
    return numbered_before, numbered_after


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class AttachmentField(forms.FileField):
    def clean(self, files, initial=None):
        images = []
        allowed_types = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
        for file in files or []:
            upload = super().clean(file, initial)
            if upload.size > 5 * 1024 * 1024:
                raise forms.ValidationError("Chaque image doit peser au plus 5 Mo.")
            try:
                with Image.open(upload, formats=tuple(allowed_types)) as image:
                    if image.width * image.height > 25_000_000:
                        raise forms.ValidationError("Une capture dépasse 25 mégapixels.")
                    content_type = allowed_types[image.format]
                    image.verify()
            except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError) as error:
                raise forms.ValidationError("Choisis une image PNG, JPEG ou WebP valide.") from error
            upload.seek(0)
            images.append(Attachment(name=upload.name, content_type=content_type, data=upload.read()))
        return images


class InterventionForm(forms.ModelForm):
    attachments = AttachmentField(
        required=False, label="Captures",
        help_text="Colle avec Ctrl+V ou choisis un fichier. PNG, JPEG et WebP, 5 Mo par image, 10 images par fiche.",
        widget=MultipleImageInput(attrs={"accept": "image/png,image/jpeg,image/webp"}),
    )

    class Meta:
        model = Intervention
        exclude = ["author"]
        widgets = {
            "occurred_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "impacted_services": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        equipment = Q(archived=False)
        service = Q(archived=False)
        impacted = Q(archived=False)
        if self.instance.pk:
            equipment |= Q(pk=self.instance.equipment_id)
            service |= Q(pk=self.instance.service_id)
            impacted |= Q(pk__in=self.instance.impacted_services.values("pk"))
        self.fields["equipment"].queryset = Equipment.objects.filter(equipment)
        self.fields["service"].queryset = Service.objects.filter(service)
        self.fields["impacted_services"].queryset = Service.objects.filter(impacted)


class CorrectionForm(InterventionForm):
    correction_reason = forms.CharField(label="Motif de la correction", max_length=250)


class Filters(forms.Form):
    q = forms.CharField(label="Recherche", required=False, max_length=200)
    equipment = forms.ModelChoiceField(
        label="Équipement", queryset=Equipment.objects.all(), required=False, empty_label="Tous les équipements",
    )
    service = forms.ModelChoiceField(label="Service", queryset=Service.objects.all(), required=False)
    author = forms.ModelChoiceField(label="Auteur", queryset=get_user_model().objects.order_by("username"), required=False)
    start = forms.DateField(label="Depuis", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="Jusqu’au", required=False, widget=forms.DateInput(attrs={"type": "date"}))


def filter_interventions(items, filters):
    if filters.is_valid():
        data = filters.cleaned_data
        for key in ("equipment", "author"):
            if data[key]:
                items = items.filter(**{key: data[key]})
        if data["service"]:
            items = items.filter(Q(service=data["service"]) | Q(impacted_services=data["service"])).distinct()
        if data["q"]:
            term = data["q"]
            items = items.filter(
                Q(title__icontains=term) | Q(change__icontains=term) | Q(reference__icontains=term)
                | Q(equipment__name__icontains=term) | Q(service__name__icontains=term)
                | Q(impacted_services__name__icontains=term)
            ).distinct()
        if data["start"]:
            items = items.filter(occurred_at__date__gte=data["start"])
        if data["end"]:
            items = items.filter(occurred_at__date__lte=data["end"])
    return items


def history_query(params, include_page=True):
    fields = (*Filters.base_fields, "page") if include_page else Filters.base_fields
    query = params.copy()
    for key in tuple(query):
        if key not in fields or not query.get(key):
            query.pop(key)
    return query


@login_required
@vary_on_headers("X-LogIT-Preview")
def history(request):
    filters = Filters(request.GET)
    items = Intervention.objects.select_related("author", "equipment", "service")
    items = filter_interventions(items, filters) if filters.is_valid() else items.none()
    params = history_query(request.GET, include_page=False)
    personal = params.get("author") == str(request.user.pk)
    page = Paginator(items, 20).get_page(request.GET.get("page"))
    active_filters = []
    for field in filters:
        if params.get(field.name):
            remaining = params.copy()
            remaining.pop(field.name)
            value = filters.cleaned_data.get(field.name, field.value())
            active_filters.append((field.label, value, remaining.urlencode()))
    detail_params = params.copy()
    detail_params["page"] = page.number
    panel_query = detail_params.urlencode()
    detail_params["from"] = "history"
    results = list(page.object_list)
    selected_index = next(
        (index for index, item in enumerate(results) if str(item.pk) == request.GET.get("fiche")), None,
    )
    selected = results[selected_index] if selected_index is not None else None
    context = {
        "filters": filters, "page": page, "query": params.urlencode(),
        "active_filters": active_filters, "detail_query": detail_params.urlencode(),
        "active_section": "mine" if personal else "history",
        "panel_query": panel_query, "preview": selected,
        "previous_preview": results[selected_index - 1] if selected_index is not None and selected_index > 0 else None,
        "next_preview": results[selected_index + 1] if selected_index is not None and selected_index + 1 < len(results) else None,
    }
    if selected:
        context["preview_services"] = selected.impacted_services.all()
    if request.headers.get("X-LogIT-Preview") == "1":
        return render(request, "history_preview.html", context, status=200 if selected else 404)
    return render(request, "history.html", context)


@login_required
def index(request, pk=None):
    items = Intervention.objects.select_related("author", "equipment", "service")
    filters = Filters(request.GET)
    params = history_query(request.GET)
    if pk is None and params:
        return redirect(f"{reverse('history')}?{params.urlencode()}")
    recent = list(items[:5])
    selected = get_object_or_404(items, pk=pk) if pk is not None else next(iter(recent), None)
    from_history = request.GET.get("from") == "history"
    active_section = "register"
    if from_history:
        active_section = "mine" if params.get("author") == str(request.user.pk) else "history"
    detail_params = params.copy()
    if from_history:
        detail_params["from"] = "history"
    services = list(selected.impacted_services.all()) if selected else []
    if selected and selected.service and selected.service not in services:
        services.insert(0, selected.service)
    before_lines, after_lines = configuration_lines(selected.before_state, selected.after_state) if selected else ([], [])
    return render(request, "index.html", {
        "filters": filters, "recent": recent, "selected": selected, "active_section": active_section,
        "from_history": from_history, "return_query": params.urlencode(),
        "detail_query": detail_params.urlencode() if from_history else "",
        "revisions": selected.revisions.select_related("editor") if selected else [],
        "attachments": selected.attachments.defer("data").select_related("uploader") if selected else [],
        "impact_services": services,
        "before_lines": before_lines, "after_lines": after_lines,
    })


@login_required
def edit(request, pk=None, source_pk=None):
    source = None
    initial = {}
    if source_pk is not None:
        source = get_object_or_404(Intervention.objects.select_related("equipment", "service"), pk=source_pk)
        if request.method == "GET":
            initial = {
                "title": source.title,
                "equipment": None if source.equipment.archived else source.equipment_id,
                "service": source.service_id if source.service and not source.service.archived else None,
                "impacted_services": list(source.impacted_services.filter(archived=False).values_list("pk", flat=True)),
                "change": source.change,
                "reason": source.reason,
                "impact": source.impact,
                "rollback": source.rollback,
            }
    with transaction.atomic():
        item = get_object_or_404(Intervention, pk=pk) if pk is not None else Intervention(author=request.user)
        form_type = CorrectionForm if pk is not None else InterventionForm
        form = form_type(
            request.POST if request.method == "POST" else None,
            request.FILES if request.method == "POST" else None,
            instance=item,
            initial=initial,
        )
        before = item.snapshot() if pk is not None else {}
        if request.method == "POST" and form.is_valid():
            images = form.cleaned_data["attachments"]
            existing_count = item.attachments.count() if item.pk else 0
            if existing_count + len(images) > 10:
                form.add_error("attachments", "Une fiche peut contenir au plus 10 images.")
                return render(request, "edit.html", {"form": form, "item": item, "source": source})
            item = form.save()
            for image in images:
                image.intervention = item
                image.uploader = request.user
            Attachment.objects.bulk_create(images)
            if pk is not None:
                changes = {
                    field: {"before": before[field], "after": value}
                    for field, value in item.snapshot().items() if before[field] != value
                }
                if images:
                    changes["captures ajoutées"] = {
                        "before": "",
                        "after": ", ".join(image.name for image in images),
                    }
                if changes:
                    Revision.objects.create(
                        intervention=item, editor=request.user, changes=changes,
                        reason=form.cleaned_data["correction_reason"],
                    )
            url = reverse("detail", kwargs={"pk": item.pk})
            if request.GET.get("from") == "history":
                params = history_query(request.GET)
                params["from"] = "history"
                url += "?" + params.urlencode()
            return redirect(url)
    return render(request, "edit.html", {"form": form, "item": item, "source": source})


@login_required
@never_cache
def attachment(request, pk):
    image = get_object_or_404(Attachment, pk=pk)
    response = HttpResponse(image.data, content_type=image.content_type)
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response
