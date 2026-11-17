from difflib import unified_diff
from itertools import islice

from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.shortcuts import get_object_or_404, redirect, render
from PIL import Image, UnidentifiedImageError

from .models import Attachment, Equipment, Intervention, Revision, Service


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
        widgets = {"occurred_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"})}


class CorrectionForm(InterventionForm):
    correction_reason = forms.CharField(label="Motif de la correction", max_length=250)


class Filters(forms.Form):
    q = forms.CharField(label="Recherche", required=False)
    equipment = forms.ModelChoiceField(
        label="Équipement", queryset=Equipment.objects.all(), required=False, empty_label="Tous les équipements",
    )
    service = forms.ModelChoiceField(label="Service", queryset=Service.objects.all(), required=False)
    author = forms.ModelChoiceField(label="Auteur", queryset=get_user_model().objects.order_by("username"), required=False)
    start = forms.DateField(label="Depuis", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="Jusqu’au", required=False, widget=forms.DateInput(attrs={"type": "date"}))


@login_required
def index(request, pk=None):
    items = Intervention.objects.select_related("author", "equipment", "service")
    filters = Filters(request.GET)
    if filters.is_valid():
        data = filters.cleaned_data
        for key in ("equipment", "author"):
            if data[key]:
                items = items.filter(**{key: data[key]})
        if data["service"]:
            items = items.filter(Q(service=data["service"]) | Q(impacted_services=data["service"])).distinct()
        if data["q"]:
            items = items.filter(Q(title__icontains=data["q"]) | Q(change__icontains=data["q"]))
        if data["start"]:
            items = items.filter(occurred_at__date__gte=data["start"])
        if data["end"]:
            items = items.filter(occurred_at__date__lte=data["end"])
    page = Paginator(items, 20).get_page(request.GET.get("page"))
    selected = get_object_or_404(items, pk=pk) if pk is not None else next(iter(page), None)
    query = request.GET.copy()
    query.pop("page", None)
    services = list(selected.impacted_services.all()) if selected else []
    if selected and selected.service and selected.service not in services:
        services.insert(0, selected.service)
    configuration_diff = []
    if selected and selected.before_state and selected.after_state:
        lines = unified_diff(selected.before_state.splitlines(), selected.after_state.splitlines(), lineterm="")
        configuration_diff = [
            (line[0], line[1:]) for line in islice(lines, 2, None) if not line.startswith("@@")
        ]
    return render(request, "index.html", {
        "filters": filters, "page": page, "selected": selected, "query": query.urlencode(),
        "revisions": selected.revisions.select_related("editor") if selected else [],
        "attachments": selected.attachments.defer("data").select_related("uploader") if selected else [],
        "impact_services": services,
        "configuration_diff": configuration_diff,
    })


@login_required
def edit(request, pk=None):
    with transaction.atomic():
        item = get_object_or_404(Intervention, pk=pk) if pk is not None else Intervention(author=request.user)
        form_type = CorrectionForm if pk is not None else InterventionForm
        form = form_type(
            request.POST if request.method == "POST" else None,
            request.FILES if request.method == "POST" else None,
            instance=item,
        )
        before = item.snapshot() if pk is not None else {}
        if request.method == "POST" and form.is_valid():
            images = form.cleaned_data["attachments"]
            existing_count = item.attachments.count() if item.pk else 0
            if existing_count + len(images) > 10:
                form.add_error("attachments", "Une fiche peut contenir au plus 10 images.")
                return render(request, "edit.html", {"form": form, "item": item})
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
            return redirect("detail", pk=item.pk)
    return render(request, "edit.html", {"form": form, "item": item})


@login_required
@never_cache
def attachment(request, pk):
    image = get_object_or_404(Attachment, pk=pk)
    response = HttpResponse(image.data, content_type=image.content_type)
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response
