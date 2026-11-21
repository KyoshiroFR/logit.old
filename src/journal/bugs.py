"""Signalement des bugs de LogIT : envoi par tout utilisateur, suivi par les administrateurs."""
from datetime import timedelta
from urllib.parse import urlencode

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .attachments import build_attachments
from .chain import record_event
from .models import BugReport
from .permissions import admin_required, is_admin


class BugForm(forms.ModelForm):
    class Meta:
        model = BugReport
        fields = ["title", "description", "bug_type", "priority", "environment", "page"]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Ex. Le filtre « 7 jours » ne réagit pas", "autocomplete": "off"}),
            "description": forms.Textarea(attrs={"rows": 4, "placeholder": "Ce que tu faisais, ce qui s’est passé, ce que tu attendais…"}),
            "bug_type": forms.RadioSelect, "priority": forms.RadioSelect,
            "environment": forms.TextInput(attrs={"placeholder": "Navigateur, système"}),
            "page": forms.HiddenInput,
        }

    def clean_page(self):
        page = self.cleaned_data.get("page", "")
        return page if page.startswith("/") and not page.startswith("//") else ""


def _wants_json(request):
    return request.headers.get("X-Requested-With") == "fetch"


@login_required
@require_http_methods(["GET", "POST"])
def report(request):
    form = BugForm(request.POST or None, initial={"page": request.GET.get("page", "")})
    if request.method == "POST":
        recent = BugReport.objects.filter(reporter=request.user, recorded_at__gte=timezone.now() - timedelta(hours=1))
        if recent.count() >= settings.LOGIT_BUG_REPORTS_PER_HOUR:
            form.add_error(None, "Trop de signalements en une heure. Réessaie plus tard.")
        files = request.FILES.getlist("screenshot")[:1]
        shot = None
        if files:
            try:
                shot = build_attachments(files)[0]
            except ValidationError as error:
                form.add_error(None, error.messages[0])
        if form.is_valid():
            bug = form.save(commit=False)
            bug.reporter, bug.version = request.user, settings.LOGIT_VERSION
            if shot:
                bug.screenshot_name, bug.screenshot_type, bug.screenshot = shot.name, shot.content_type, bytes(shot.data)
            bug.save()
            record_event("bug_reported", actor=request.user, target=f"bug n° {bug.pk}",
                         details={"priorité": bug.priority, "type": bug.bug_type}, request=request)
            if _wants_json(request):
                return JsonResponse({"ok": True, "id": bug.pk})
            messages.success(request, f"Merci ! Bug n° {bug.pk} transmis aux administrateurs.")
            return redirect("home")
        if _wants_json(request):
            errors = {k: [str(m) for m in v] for k, v in form.errors.items()}
            return JsonResponse({"ok": False, "errors": errors}, status=400)
    return render(request, "journal/bugs/report_page.html", {"bug_form": form})


@login_required
@admin_required
def bug_list(request):
    status = request.GET.get("statut", "open")
    bugs = BugReport.objects.select_related("reporter").defer("screenshot")
    if status == "open":
        bugs = bugs.filter(status__in=[BugReport.NEW, BugReport.IN_PROGRESS])
    elif status in dict(BugReport.STATUSES):
        bugs = bugs.filter(status=status)
    page = Paginator(bugs, 30).get_page(request.GET.get("page"))
    return render(request, "journal/bugs/list.html", {"page": page, "status": status, "statuses": BugReport.STATUSES})


class BugAdminForm(forms.ModelForm):
    class Meta:
        model = BugReport
        fields = ["status", "admin_note"]
        widgets = {"admin_note": forms.Textarea(attrs={"rows": 3})}


def github_issue_url(bug):
    """Lien de création d'une issue GitHub préremplie, sans capture ni information interne."""
    body = (
        f"**Type** : {bug.get_bug_type_display()} · **Priorité** : {bug.get_priority_display()}\n"
        f"**Version de LogIT** : {bug.version or 'inconnue'}\n"
        f"**Navigateur / appareil** : {bug.environment or 'non précisé'}\n\n"
        f"### Description\n{bug.description}\n\n"
        "---\n_Signalé depuis LogIT. Vérifier qu’aucune information interne (noms de serveurs, adresses, "
        "comptes) ne figure ci-dessus avant de publier : les issues sont publiques._"
    )
    return f"{settings.LOGIT_REPOSITORY}/issues/new?" + urlencode({"title": bug.title, "body": body, "labels": "bug"})


@login_required
@admin_required
def bug_detail(request, pk):
    bug = get_object_or_404(BugReport.objects.select_related("reporter"), pk=pk)
    form = BugAdminForm(request.POST or None, instance=bug)
    before = bug.status
    if request.method == "POST" and form.is_valid():
        form.save()
        if bug.status != before:
            record_event("bug_status_changed", actor=request.user, target=f"bug n° {bug.pk}",
                         details={"avant": before, "après": bug.status}, request=request)
        messages.success(request, "Suivi mis à jour.")
        return redirect("bug_detail", pk=pk)
    return render(request, "journal/bugs/detail.html", {"bug": bug, "form": form, "github_url": github_issue_url(bug)})


@login_required
@never_cache
def bug_screenshot(request, pk):
    bug = get_object_or_404(BugReport, pk=pk)
    if not (is_admin(request.user) or bug.reporter_id == request.user.pk) or not bug.screenshot:
        raise PermissionDenied
    response = HttpResponse(bytes(bug.screenshot), content_type=bug.screenshot_type)
    response["Content-Disposition"] = f'inline; filename="bug-{bug.pk}.{bug.screenshot_type.split("/")[1]}"'
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cache-Control"] = "private, no-store"
    return response
