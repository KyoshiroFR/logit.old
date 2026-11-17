import base64
import time
from io import BytesIO

import django_otp
import qrcode
from django import forms
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.contrib.messages import success
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.crypto import constant_time_compare
from django.utils.http import urlencode, url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import AccountSecurity

PENDING_SESSION = "logit_pending_login"
PENDING_SECONDS = 600


def policy_for(user):
    return getattr(user, "accountsecurity", None)


def pending_step(policy):
    if policy and policy.must_change_password:
        return "first_password"
    if policy and policy.totp_required:
        return "totp"
    return None


def pending_user(request):
    pending = request.session.get(PENDING_SESSION)
    if pending and time.time() - pending["started"] <= PENDING_SECONDS:
        user = get_user_model().objects.filter(pk=pending["user_id"], is_active=True).first()
        if user and constant_time_compare(user.get_session_auth_hash(), pending["password_hash"]):
            return user, pending
    request.session.pop(PENDING_SESSION, None)
    return None, None


def finish_login(request, user, pending, device=None):
    request.session.pop(PENDING_SESSION, None)
    login(request, user, backend=pending["backend"])
    if device:
        django_otp.login(request, device)
    return redirect(pending["next"])


class LogITLoginView(LoginView):
    def form_valid(self, form):
        user = form.get_user()
        step = pending_step(policy_for(user))
        if not step:
            self.request.session.pop(PENDING_SESSION, None)
            return super().form_valid(form)
        if self.request.user.is_authenticated:
            logout(self.request)
        self.request.session.cycle_key()
        self.request.session[PENDING_SESSION] = {
            "user_id": user.pk, "backend": user.backend,
            "password_hash": user.get_session_auth_hash(), "started": time.time(),
            "next": self.get_success_url(),
        }
        return redirect(step)


class AccountSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated:
            policy = policy_for(user)
            if pending_step(policy) and (policy.must_change_password or not user.is_verified()):
                target = request.get_full_path()
                logout(request)
                if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=True):
                    target = reverse("index")
                return redirect(reverse("login") + "?" + urlencode({"next": target}))
        return self.get_response(request)


def admin_login(request):
    target = request.GET.get("next", reverse("admin:index"))
    return redirect(reverse("login") + "?" + urlencode({"next": target}))


@never_cache
@login_required
def account(request):
    return render(request, "account.html", {"title": "Mon compte"})


@never_cache
@login_required
def account_security(request):
    policy = policy_for(request.user)
    return render(request, "account.html", {
        "title": "Sécurité", "security_page": True,
        "totp_required": bool(policy and policy.totp_required),
        "totp_configured": TOTPDevice.objects.filter(user=request.user, confirmed=True).exists(),
    })


class AccountPasswordChangeView(PasswordChangeView):
    template_name = "account_password.html"
    success_url = reverse_lazy("account_security")

    def form_valid(self, form):
        response = super().form_valid(form)
        success(self.request, "Ton mot de passe a été modifié.")
        return response


class FirstPasswordForm(SetPasswordForm):
    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("new_password2")
        if password and self.user.check_password(password):
            self.add_error("new_password2", "Choisis un mot de passe différent du mot de passe temporaire.")
        return cleaned


@never_cache
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def first_password(request):
    user, pending = pending_user(request)
    if not user:
        return redirect("login")
    policy = policy_for(user)
    if not policy or not policy.must_change_password:
        return redirect("totp") if pending_step(policy) else finish_login(request, user, pending)
    form = FirstPasswordForm(user, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            current = get_user_model().objects.get(pk=user.pk)
            policy = AccountSecurity.objects.get(user=current)
            if not current.is_active or not policy.must_change_password or not constant_time_compare(
                current.get_session_auth_hash(), pending["password_hash"],
            ):
                request.session.pop(PENDING_SESSION, None)
                return redirect("login")
            user = form.save()
            policy.must_change_password = False
            policy.save(update_fields=["must_change_password"])
        pending["password_hash"] = user.get_session_auth_hash()
        request.session[PENDING_SESSION] = pending
        return redirect("totp") if policy.totp_required else finish_login(request, user, pending)
    return render(request, "account_security.html", {"title": "Changer le mot de passe temporaire", "form": form})


class CodeForm(forms.Form):
    code = forms.RegexField(
        r"^[0-9]{6}$", label="Code à six chiffres",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "maxlength": 6}),
    )


@never_cache
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def totp(request):
    user, pending = pending_user(request)
    if not user:
        return redirect("login")
    step = pending_step(policy_for(user))
    if step == "first_password":
        return redirect(step)
    if step != "totp":
        return finish_login(request, user, pending)
    form = CodeForm(request.POST if request.method == "POST" else None)
    verified = False
    with transaction.atomic():
        device = TOTPDevice.objects.filter(user=user, confirmed=True).order_by("pk").first()
        if device is None:
            device, _ = TOTPDevice.objects.get_or_create(user=user, name="LogIT", defaults={"confirmed": False})
        if request.method == "POST" and form.is_valid():
            checked_user, _ = pending_user(request)
            if not checked_user or pending_step(policy_for(checked_user)) != "totp":
                return redirect("login")
            if device.verify_token(form.cleaned_data["code"]):
                if not device.confirmed:
                    device.confirmed = True
                    device.save(update_fields=["confirmed"])
                verified = True
            else:
                form.add_error("code", "Code invalide, déjà utilisé ou délai entre les essais en cours.")
    if verified:
        return finish_login(request, user, pending, device)
    qr = None
    if not device.confirmed:
        image = BytesIO()
        qrcode.make(device.config_url).save(image, format="PNG")
        qr = base64.b64encode(image.getvalue()).decode("ascii")
    return render(request, "account_security.html", {
        "title": "Configurer le TOTP" if qr else "Vérifier le code TOTP", "form": form, "qr": qr,
    })
