"""Administration : comptes, référentiel des éléments, journal de sécurité, intégrité."""
import secrets

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from . import chain
from .models import AuditEvent, Element
from .permissions import CONTRIBUTOR, READER, ROLES, admin_required, role_of
from .security import profile_of

User = get_user_model()


def temporary_password():
    return secrets.token_urlsafe(18)  # 144 bits


def apply_role(user, role):
    user.is_superuser = user.is_staff = role == "admin"
    user.save(update_fields=["is_superuser", "is_staff"])
    user.groups.clear()
    if role != "admin":
        user.groups.add(Group.objects.get(name=CONTRIBUTOR if role == "contributor" else READER))


def active_admins():
    return User.objects.filter(is_active=True, is_superuser=True)


class UserCreateForm(forms.Form):
    username = forms.RegexField(label="Identifiant", max_length=150, regex=r"^[\w.-]+$",
                                help_text="Lettres, chiffres, point, tiret. Un compte par personne.")
    first_name = forms.CharField(label="Prénom", max_length=150, required=False)
    last_name = forms.CharField(label="Nom", max_length=150, required=False)
    role = forms.ChoiceField(label="Rôle", choices=ROLES, initial="contributor")
    totp_required = forms.BooleanField(label="TOTP obligatoire", required=False, initial=True)

    def clean_username(self):
        name = self.cleaned_data["username"]
        if User.objects.filter(username__iexact=name).exists():
            raise forms.ValidationError("Cet identifiant existe déjà.")
        return name


class UserEditForm(forms.Form):
    first_name = forms.CharField(label="Prénom", max_length=150, required=False)
    last_name = forms.CharField(label="Nom", max_length=150, required=False)
    role = forms.ChoiceField(label="Rôle", choices=ROLES)
    totp_required = forms.BooleanField(label="TOTP obligatoire", required=False)
    is_active = forms.BooleanField(label="Compte actif", required=False)


@login_required
@admin_required
def users(request):
    accounts = User.objects.select_related("profile").order_by("username")
    rows = [{"user": u, "role": dict(ROLES)[role_of(u)], "profile": profile_of(u)} for u in accounts]
    return render(request, "journal/admin/users.html", {"rows": rows, "now": timezone.now()})


@login_required
@admin_required
@never_cache
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        password = temporary_password()
        with transaction.atomic():
            user = User.objects.create_user(data["username"], password=password,
                                            first_name=data["first_name"], last_name=data["last_name"])
            apply_role(user, data["role"])
            profile = profile_of(user)
            profile.must_change_password = True
            profile.totp_required = data["totp_required"]
            profile.save()
        chain.record_event("user_created", actor=request.user, target=user.username,
                           details={"rôle": data["role"], "totp obligatoire": data["totp_required"]}, request=request)
        return render(request, "journal/admin/password_shown.html", {"account": user, "password": password})
    return render(request, "journal/admin/user_form.html", {"form": form, "title": "Nouveau compte"})


@login_required
@admin_required
def user_edit(request, pk):
    account = get_object_or_404(User, pk=pk)
    profile = profile_of(account)
    form = UserEditForm(request.POST or None, initial={
        "first_name": account.first_name, "last_name": account.last_name, "role": role_of(account),
        "totp_required": profile.totp_required, "is_active": account.is_active})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        demoting = account.is_superuser and (data["role"] != "admin" or not data["is_active"])
        if demoting and active_admins().exclude(pk=account.pk).count() == 0:
            form.add_error(None, "Impossible : ce compte est le dernier administrateur actif.")
        else:
            before = {"rôle": role_of(account), "actif": account.is_active, "totp obligatoire": profile.totp_required}
            account.first_name, account.last_name, account.is_active = data["first_name"], data["last_name"], data["is_active"]
            account.save(update_fields=["first_name", "last_name", "is_active"])
            apply_role(account, data["role"])
            profile.totp_required = data["totp_required"]
            profile.save(update_fields=["totp_required"])
            after = {"rôle": data["role"], "actif": data["is_active"], "totp obligatoire": data["totp_required"]}
            changed = {k: {"avant": before[k], "après": after[k]} for k in before if before[k] != after[k]}
            chain.record_event("user_updated", actor=request.user, target=account.username, details=changed,
                               request=request)
            messages.success(request, "Compte mis à jour.")
            return redirect("admin_users")
    return render(request, "journal/admin/user_form.html", {
        "form": form, "title": f"Compte {account.username}", "account": account, "profile": profile})


@login_required
@admin_required
@require_POST
@never_cache
def user_reset_password(request, pk):
    account = get_object_or_404(User, pk=pk)
    password = temporary_password()
    account.set_password(password)
    account.save(update_fields=["password"])
    profile = profile_of(account)
    profile.must_change_password, profile.failed_attempts, profile.locked_until = True, 0, None
    profile.save(update_fields=["must_change_password", "failed_attempts", "locked_until"])
    chain.record_event("password_reset_by_admin", actor=request.user, target=account.username, request=request)
    return render(request, "journal/admin/password_shown.html", {"account": account, "password": password})


@login_required
@admin_required
@require_POST
def user_reset_totp(request, pk):
    account = get_object_or_404(User, pk=pk)
    profile = profile_of(account)
    profile.totp_secret, profile.totp_confirmed, profile.recovery_codes = "", False, []
    profile.save(update_fields=["totp_secret", "totp_confirmed", "recovery_codes"])
    chain.record_event("totp_reset_by_admin", actor=request.user, target=account.username, request=request)
    messages.success(request, f"TOTP de {account.username} réinitialisé : un nouvel enrôlement sera demandé.")
    return redirect("admin_user_edit", pk=pk)


class ElementForm(forms.ModelForm):
    class Meta:
        model = Element
        fields = ["name", "kind", "description"]


@login_required
@admin_required
def elements(request):
    form = ElementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        element = form.save()
        chain.record_event("element_created", actor=request.user, target=element.name,
                           details={"type": element.kind}, request=request)
        messages.success(request, f"« {element.name} » ajouté.")
        return redirect("admin_elements")
    return render(request, "journal/admin/elements.html", {"form": form, "elements": Element.objects.all()})


@login_required
@admin_required
@require_POST
def element_toggle(request, pk):
    element = get_object_or_404(Element, pk=pk)
    element.archived = not element.archived
    element.save(update_fields=["archived"])
    chain.record_event("element_archived" if element.archived else "element_restored", actor=request.user,
                       target=element.name, request=request)
    messages.success(request, f"« {element.name} » {'archivé' if element.archived else 'réactivé'}. "
                              "Les fiches existantes sont conservées.")
    return redirect("admin_elements")


@login_required
@admin_required
def audit(request):
    page = Paginator(AuditEvent.objects.select_related("actor"), 50).get_page(request.GET.get("page"))
    return render(request, "journal/admin/audit.html", {"page": page})


@login_required
@admin_required
def integrity(request):
    problems = chain.verify() if request.method == "POST" else None
    if problems is not None:
        chain.record_event("integrity_checked", actor=request.user, details={"anomalies": len(problems)},
                           request=request)
    return render(request, "journal/admin/integrity.html", {"problems": problems})
