import difflib
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from . import activity
from .attachments import build_attachments
from .chain import ConcurrentEdit, append_version
from .forms import CancelForm, CompleteForm, CorrectionForm, FilterForm, InterventionForm
from .models import Attachment, Intervention, Version
from .permissions import writer_required

PERIODS = {"24h": timedelta(hours=24), "48h": timedelta(hours=48), "7j": timedelta(days=7), "30j": timedelta(days=30)}
CONCURRENT = "La fiche a été modifiée par quelqu’un d’autre entre-temps. Vérifie la version actuelle avant de recommencer."
TEXT_FIELDS = ["title", "change", "reason", "impact", "verification", "rollback", "before_state", "after_state"]


def current_versions():
    """La version la plus récente de chaque fiche."""
    latest = Version.objects.filter(intervention=OuterRef("pk")).order_by("-number").values("pk")[:1]
    ids = Intervention.objects.annotate(latest=Subquery(latest)).values("latest")
    return (Version.objects.filter(pk__in=ids)
            .select_related("intervention", "intervention__created_by", "author")
            .prefetch_related("elements"))


def incomplete_q():
    missing = Q()
    for name in Version.REQUIRED_FOR_COMPLETE:
        missing |= Q(**{name: ""})
    return missing & ~Q(status=Version.STATUS_CANCELLED)


@login_required
def home(request):
    versions = current_versions()
    form = FilterForm(request.GET or None)
    filtered = versions
    active = False
    if form.is_valid():
        data = form.cleaned_data
        if data["q"]:
            q = data["q"]
            filtered = filtered.filter(
                Q(title__icontains=q) | Q(change__icontains=q) | Q(reason__icontains=q) | Q(impact__icontains=q)
                | Q(rollback__icontains=q) | Q(before_state__icontains=q) | Q(after_state__icontains=q)
                | Q(elements__name__icontains=q)).distinct()
        if data["element"]:
            filtered = filtered.filter(elements=data["element"])
        if data["kind"]:
            filtered = filtered.filter(kind=data["kind"])
        if data["period"]:
            filtered = filtered.filter(occurred_at__gte=timezone.now() - PERIODS[data["period"]])
        active = any(data.values())
    page = Paginator(filtered.order_by("-occurred_at", "-pk"), 25).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    unseen = [] if active else activity.unseen_items(request.user)
    return render(request, "journal/home.html", {
        "form": form, "page": page, "filters_active": active, "query": query.urlencode(),
        "unseen": unseen, "unseen_upto": max((i["version"].pk for i in unseen), default=0),
        "rolled_back": set(Intervention.objects.filter(rollbacks__isnull=False).values_list("pk", flat=True)),
        "to_complete": [] if active else versions.filter(incomplete_q()).order_by("occurred_at"),
        "upcoming": [] if active else versions.filter(status=Version.STATUS_PLANNED).order_by("occurred_at"),
    })


def line_diff(before, after):
    rows = []
    for line in difflib.ndiff((before or "").splitlines(), (after or "").splitlines()):
        tag = line[:2]
        if tag == "? ":
            continue
        rows.append(({"- ": "removed", "+ ": "added"}.get(tag, "same"), line[2:]))
    return rows


def version_changes(previous, version):
    changes = []
    labels = {f.name: f.verbose_name for f in Version._meta.fields}
    for name in ["kind", "status", "occurred_at"]:
        old, new = getattr(previous, name), getattr(version, name)
        if old != new:
            display = (lambda v: timezone.localtime(v).strftime("%d/%m/%Y %H:%M")) if name == "occurred_at" else \
                (lambda v, n=name: dict(Version._meta.get_field(n).choices)[v])
            changes.append({"label": labels[name], "simple": True, "old": display(old), "new": display(new)})
    old_el = {e.name for e in previous.elements.all()}
    new_el = {e.name for e in version.elements.all()}
    if old_el != new_el:
        changes.append({"label": "éléments concernés", "simple": True,
                        "old": ", ".join(sorted(old_el)) or "—", "new": ", ".join(sorted(new_el)) or "—"})
    for name in TEXT_FIELDS:
        old, new = getattr(previous, name), getattr(version, name)
        if old != new:
            changes.append({"label": labels[name], "simple": False, "rows": line_diff(old, new)})
    added = [a.name for a in version.attachments.all()]
    if added:
        changes.append({"label": "captures ajoutées", "simple": True, "old": "", "new": ", ".join(added)})
    return changes


@login_required
def detail(request, pk):
    intervention = get_object_or_404(Intervention.objects.select_related("created_by"), pk=pk)
    versions = list(intervention.versions.select_related("author")
                    .prefetch_related("elements", "attachments").order_by("number"))
    current = versions[-1]
    history = []
    for previous, version in zip(versions, versions[1:]):
        history.append({"version": version, "changes": version_changes(previous, version)})
    history.reverse()
    sensitive = {"impact", "retour arrière"}
    return render(request, "journal/detail.html", {
        "intervention": intervention, "current": current, "first": versions[0], "history": history,
        "corrections": [h for h in history if h["version"].action == Version.CORRECTED],
        "sensitive_corrected": any(c["label"] in sensitive for h in history for c in h["changes"]),
        "state_diff": line_diff(current.before_state, current.after_state)
        if current.before_state or current.after_state else None,
        "attachments": intervention.attachments.defer("data").select_related("uploader", "version"),
        "rollbacks": [(r, r.current) for r in intervention.rollbacks.select_related("created_by")],
        "can_rollback": current.status == Version.STATUS_DONE,
    })


def _version_from(current, author, action, **changes):
    fields = {f: getattr(current, f) for f in Version.CONTENT_FIELDS}
    fields.update(changes)
    return Version(intervention=current.intervention, number=current.number + 1, action=action,
                   author=author, **fields)


def _form_initial(version):
    data = {f: getattr(version, f) for f in Version.CONTENT_FIELDS if f != "status"}
    data["occurred_at"] = timezone.localtime(version.occurred_at)
    data["elements"] = list(version.elements.all())
    return data


def _content(data):
    return {f: data[f] for f in Version.CONTENT_FIELDS if f not in ("status",)}


def _uploads(request, form, already=0):
    """Captures envoyées avec le formulaire, ou None si elles sont refusées (erreur ajoutée au formulaire)."""
    try:
        return build_attachments(request.FILES.getlist("attachments"), already)
    except ValidationError as error:
        form.add_error(None, error.messages[0])
        return None


def _create_intervention(request, form, rollback_of=None, template="journal/form.html", context=None):
    if request.method == "POST" and form.is_valid():
        uploads = _uploads(request, form)
        if uploads is not None:
            data = form.cleaned_data
            with transaction.atomic():
                intervention = Intervention.objects.create(created_by=request.user, recorded_at=timezone.now(),
                                                           rollback_of=rollback_of)
                status = Version.STATUS_PLANNED if data["kind"] == Version.PLANNED else Version.STATUS_DONE
                version = Version(intervention=intervention, number=1, action=Version.CREATED, author=request.user,
                                  status=status, **_content(data))
                append_version(version, [e.pk for e in data["elements"]], uploads)
            messages.success(request, f"Fiche n° {intervention.pk} enregistrée.")
            return redirect("detail", pk=intervention.pk)
    return render(request, template, {"form": form, "mode": "create", **(context or {})})


@login_required
@writer_required
@require_http_methods(["GET", "POST"])
def create(request):
    return _create_intervention(request, InterventionForm(request.POST or None))


@login_required
@writer_required
@require_http_methods(["GET", "POST"])
def rollback(request, pk):
    original = get_object_or_404(Intervention, pk=pk)
    source = original.current
    if source.status != Version.STATUS_DONE:
        messages.error(request, "Seule une intervention réalisée peut faire l’objet d’un retour arrière.")
        return redirect("detail", pk=pk)
    elements = list(source.elements.all())
    initial = {
        "kind": Version.NORMAL, "title": f"Retour arrière : {source.title}"[:200], "elements": elements,
        "change": source.rollback, "reason": f"Retour arrière de la fiche n° {pk} : ",
        "rollback": f"Réappliquer la fiche n° {pk}.",
        "before_state": source.after_state, "after_state": source.before_state,
    }
    form = InterventionForm(request.POST or None, initial=initial, current_elements=elements)
    return _create_intervention(request, form, rollback_of=original, context={"rollback_source": source})


def _locked_current(pk):
    intervention = get_object_or_404(Intervention, pk=pk)
    current = intervention.current
    return intervention, current


@login_required
@writer_required
@require_http_methods(["GET", "POST"])
def correct(request, pk):
    intervention, current = _locked_current(pk)
    if current.status == Version.STATUS_CANCELLED:
        messages.error(request, "Une fiche annulée ne se corrige plus.")
        return redirect("detail", pk=pk)
    elements = list(current.elements.all())
    form = CorrectionForm(request.POST or None, initial=_form_initial(current), current_elements=elements)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        status = current.status
        if status == Version.STATUS_PLANNED and data["kind"] != Version.PLANNED:
            status = Version.STATUS_DONE
        new_ids = sorted(e.pk for e in data["elements"])
        uploads = _uploads(request, form, intervention.attachments.count())
        unchanged = all(data[f] == getattr(current, f) for f in Version.CONTENT_FIELDS if f != "status") \
            and new_ids == sorted(e.pk for e in elements) and status == current.status and not uploads
        if uploads is None:
            pass
        elif unchanged:
            form.add_error(None, "Aucune modification par rapport à la version actuelle.")
        else:
            try:
                with transaction.atomic():
                    version = _version_from(current, request.user, Version.CORRECTED, status=status,
                                            note=data["note"], **_content(data))
                    append_version(version, new_ids, uploads)
            except ConcurrentEdit:
                messages.error(request, CONCURRENT)
                return redirect("detail", pk=pk)
            messages.success(request, "Correction enregistrée.")
            return redirect("detail", pk=pk)
    return render(request, "journal/form.html", {"form": form, "mode": "correct", "current": current})


@login_required
@writer_required
@require_http_methods(["GET", "POST"])
def complete(request, pk):
    intervention, current = _locked_current(pk)
    if current.status != Version.STATUS_PLANNED:
        return redirect("detail", pk=pk)
    form = CompleteForm(request.POST or None, initial={
        "occurred_at": timezone.localtime().replace(second=0, microsecond=0), "verification": current.verification})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                version = _version_from(current, request.user, Version.COMPLETED, status=Version.STATUS_DONE,
                                        occurred_at=data["occurred_at"], verification=data["verification"],
                                        note=data["note"])
                append_version(version, [e.pk for e in current.elements.all()])
        except ConcurrentEdit:
            messages.error(request, CONCURRENT)
            return redirect("detail", pk=pk)
        messages.success(request, "Intervention marquée réalisée.")
        return redirect("detail", pk=pk)
    return render(request, "journal/action.html", {"form": form, "current": current,
                                                   "title": "Marquer l’intervention réalisée"})


@login_required
@writer_required
@require_http_methods(["GET", "POST"])
def cancel(request, pk):
    intervention, current = _locked_current(pk)
    if current.status == Version.STATUS_CANCELLED:
        return redirect("detail", pk=pk)
    form = CancelForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                version = _version_from(current, request.user, Version.CANCELLED, status=Version.STATUS_CANCELLED,
                                        note=form.cleaned_data["note"])
                append_version(version, [e.pk for e in current.elements.all()])
        except ConcurrentEdit:
            messages.error(request, CONCURRENT)
            return redirect("detail", pk=pk)
        messages.success(request, "Fiche annulée. Elle reste consultable dans le registre.")
        return redirect("detail", pk=pk)
    return render(request, "journal/action.html", {"form": form, "current": current, "title": "Annuler la fiche",
                                                   "danger": True})


@login_required
@never_cache
def attachment(request, pk):
    item = get_object_or_404(Attachment, pk=pk)
    response = HttpResponse(bytes(item.data), content_type=item.content_type)
    disposition = "attachment" if request.GET.get("telecharger") else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="capture-{item.pk}.{item.content_type.split("/")[1]}"'
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def mark_read(request):
    try:
        activity.mark_read(request.user, request.POST.get("upto", 0))
    except ValueError:
        pass
    return redirect("home")
