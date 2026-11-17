from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .models import Equipment, Intervention, Revision, Service


class InterventionForm(forms.ModelForm):
    class Meta:
        model = Intervention
        exclude = ["author"]
        widgets = {"occurred_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"})}


class CorrectionForm(InterventionForm):
    correction_reason = forms.CharField(label="Motif de la correction", max_length=250)


class Filters(forms.Form):
    q = forms.CharField(label="Recherche", required=False)
    equipment = forms.ModelChoiceField(label="Équipement", queryset=Equipment.objects.all(), required=False)
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
        for key in ("equipment", "service", "author"):
            if data[key]:
                items = items.filter(**{key: data[key]})
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
    return render(request, "index.html", {
        "filters": filters, "page": page, "selected": selected, "query": query.urlencode(),
        "revisions": selected.revisions.select_related("editor") if selected else [],
    })


@login_required
def edit(request, pk=None):
    with transaction.atomic():
        item = get_object_or_404(Intervention, pk=pk) if pk is not None else Intervention(author=request.user)
        form_type = CorrectionForm if pk is not None else InterventionForm
        form = form_type(request.POST if request.method == "POST" else None, instance=item)
        before = item.snapshot() if pk is not None else {}
        if request.method == "POST" and form.is_valid():
            item = form.save()
            if pk is not None:
                changes = {
                    field: {"before": before[field], "after": value}
                    for field, value in item.snapshot().items() if before[field] != value
                }
                if changes:
                    Revision.objects.create(
                        intervention=item, editor=request.user, changes=changes,
                        reason=form.cleaned_data["correction_reason"],
                    )
            return redirect("detail", pk=item.pk)
    return render(request, "edit.html", {"form": form, "item": item})
