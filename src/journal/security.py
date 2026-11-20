"""Authentification : verrouillage, TOTP avec codes de secours, mot de passe initial imposé."""
import hashlib
import secrets
from datetime import timedelta

import pyotp
import segno
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from .chain import record_event
from .models import Profile

OTP_SESSION_KEY = "logit_otp_ok"
RECOVERY_COUNT = 10
ISSUER = "LogIT"


def profile_of(user):
    return Profile.objects.get_or_create(user=user)[0]


def hash_code(code):
    return hashlib.sha256(code.replace("-", "").strip().lower().encode()).hexdigest()


def new_recovery_codes():
    codes = []
    for _ in range(RECOVERY_COUNT):
        raw = secrets.token_hex(5)  # 40 bits d'aléa par code
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes, [hash_code(c) for c in codes]


# --- Passage obligatoire : TOTP, puis mot de passe initial, puis enrôlement ----------------

EXEMPT_PREFIXES = ("/static/", "/sante/", "/deconnexion/")


def required_step(request):
    user = request.user
    if not user.is_authenticated:
        return None
    profile = profile_of(user)
    if profile.totp_confirmed and not request.session.get(OTP_SESSION_KEY):
        return "totp_verify"
    if profile.must_change_password:
        return "password_initial"
    if profile.totp_required and not profile.totp_confirmed:
        return "totp_setup"
    return None


class SecurityGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        step = required_step(request)
        if step and not request.path.startswith(EXEMPT_PREFIXES):
            target = reverse(step)
            if request.path != target:
                return redirect(target)
        return self.get_response(request)


class SecurityHeadersMiddleware:
    CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
           "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.CSP)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.user.is_authenticated:
            response.setdefault("Cache-Control", "no-store")
        return response


# --- Connexion ---------------------------------------------------------------------------

class LoginForm(forms.Form):
    username = forms.CharField(label="Identifiant", max_length=150)
    password = forms.CharField(label="Mot de passe", widget=forms.PasswordInput)


GENERIC_ERROR = "Identifiant ou mot de passe incorrect, ou compte temporairement verrouillé."


def register_failure(request, user, reason):
    profile = profile_of(user)
    profile.failed_attempts += 1
    details = {"raison": reason, "échecs": profile.failed_attempts}
    if profile.failed_attempts >= settings.LOGIT_LOCKOUT_ATTEMPTS:
        profile.locked_until = timezone.now() + timedelta(minutes=settings.LOGIT_LOCKOUT_MINUTES)
        profile.failed_attempts = 0
        record_event("account_locked", target=user.username, details=details, request=request)
    profile.save(update_fields=["failed_attempts", "locked_until"])
    record_event("login_failed", target=user.username, details=details, request=request)


def is_locked(user):
    profile = profile_of(user)
    return bool(profile.locked_until and profile.locked_until > timezone.now())


@sensitive_post_parameters("password")
@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"]
        known = get_user_model().objects.filter(username=username, is_active=True).first()
        if known and is_locked(known):
            record_event("login_refused_locked", target=username, request=request)
            form.add_error(None, GENERIC_ERROR)
        else:
            user = authenticate(request, username=username, password=form.cleaned_data["password"])
            if user is None:
                if known:
                    register_failure(request, known, "mot de passe")
                else:
                    record_event("login_failed", target=username[:150], details={"raison": "compte inconnu"},
                                 request=request)
                form.add_error(None, GENERIC_ERROR)
            else:
                profile = profile_of(user)
                profile.failed_attempts = 0
                profile.save(update_fields=["failed_attempts"])
                login(request, user)
                request.session[OTP_SESSION_KEY] = False
                record_event("login_password_ok", actor=user, target=user.username, request=request)
                return redirect(request.GET.get("next") if _safe_next(request) else "home")
    return render(request, "journal/auth/login.html", {"form": form})


def _safe_next(request):
    from django.utils.http import url_has_allowed_host_and_scheme
    target = request.GET.get("next")
    return bool(target) and url_has_allowed_host_and_scheme(target, {request.get_host()}, require_https=True)


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        record_event("logout", actor=request.user, target=request.user.username, request=request)
    logout(request)
    return redirect("login")


# --- TOTP --------------------------------------------------------------------------------

class CodeForm(forms.Form):
    code = forms.CharField(label="Code", max_length=20, widget=forms.TextInput(attrs={
        "autocomplete": "one-time-code", "inputmode": "text", "autofocus": True}))


def check_totp(profile, code):
    """Vérifie un code TOTP (fenêtre ±1 pas) en refusant la réutilisation d'un code déjà accepté."""
    code = code.replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return False
    totp = pyotp.TOTP(profile.totp_secret)
    now = timezone.now()
    for offset in (-1, 0, 1):
        moment = now + timedelta(seconds=30 * offset)
        step = int(moment.timestamp()) // 30
        if step > profile.totp_last_step and secrets.compare_digest(totp.at(moment), code):
            profile.totp_last_step = step
            profile.save(update_fields=["totp_last_step"])
            return True
    return False


def use_recovery_code(profile, code):
    digest = hash_code(code)
    if digest in profile.recovery_codes:
        profile.recovery_codes = [c for c in profile.recovery_codes if c != digest]
        profile.save(update_fields=["recovery_codes"])
        return True
    return False


@login_required
@never_cache
def totp_verify(request):
    profile = profile_of(request.user)
    if not profile.totp_confirmed:
        return redirect("home")
    form = CodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        code = form.cleaned_data["code"]
        if check_totp(profile, code):
            method = "totp"
        elif use_recovery_code(profile, code):
            method = "code de secours"
        else:
            method = None
        if method:
            request.session.cycle_key()
            request.session[OTP_SESSION_KEY] = True
            profile.failed_attempts = 0
            profile.save(update_fields=["failed_attempts"])
            record_event("login_ok", actor=request.user, target=request.user.username,
                         details={"second facteur": method, "codes de secours restants": len(profile.recovery_codes)},
                         request=request)
            if method == "code de secours":
                messages.warning(request, f"Code de secours utilisé. Il en reste {len(profile.recovery_codes)}.")
            return redirect("home")
        user = request.user
        register_failure(request, user, "code TOTP")
        if is_locked(user):
            logout(request)
            return redirect("login")
        form.add_error("code", "Code invalide.")
    return render(request, "journal/auth/totp_verify.html", {"form": form})


@login_required
@never_cache
def totp_setup(request):
    profile = profile_of(request.user)
    if profile.totp_confirmed:
        return redirect("account")
    if not profile.totp_secret or request.method == "GET":
        profile.totp_secret = pyotp.random_base32(32)  # 160 bits
        profile.save(update_fields=["totp_secret"])
    uri = pyotp.TOTP(profile.totp_secret).provisioning_uri(name=request.user.username, issuer_name=ISSUER)
    form = CodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if check_totp(profile, form.cleaned_data["code"]):
            codes, digests = new_recovery_codes()
            profile.totp_confirmed = True
            profile.recovery_codes = digests
            profile.save(update_fields=["totp_confirmed", "recovery_codes"])
            request.session[OTP_SESSION_KEY] = True
            record_event("totp_enrolled", actor=request.user, target=request.user.username, request=request)
            return render(request, "journal/auth/recovery_codes.html", {"codes": codes})
        form.add_error("code", "Code invalide. Vérifie l’heure de ton téléphone et réessaie.")
    qr = segno.make(uri, error="m").svg_data_uri(scale=5, border=2)
    return render(request, "journal/auth/totp_setup.html", {
        "form": form, "qr": qr, "secret": profile.totp_secret, "required": profile.totp_required})


@login_required
@require_POST
def totp_disable(request):
    profile = profile_of(request.user)
    if profile.totp_required:
        messages.error(request, "Le TOTP est obligatoire pour ton compte.")
        return redirect("account")
    profile.totp_confirmed, profile.totp_secret, profile.recovery_codes = False, "", []
    profile.save(update_fields=["totp_confirmed", "totp_secret", "recovery_codes"])
    record_event("totp_disabled", actor=request.user, target=request.user.username, request=request)
    messages.success(request, "TOTP désactivé.")
    return redirect("account")


@login_required
@require_POST
def recovery_regenerate(request):
    profile = profile_of(request.user)
    if not profile.totp_confirmed:
        return redirect("account")
    codes, digests = new_recovery_codes()
    profile.recovery_codes = digests
    profile.save(update_fields=["recovery_codes"])
    record_event("recovery_codes_regenerated", actor=request.user, target=request.user.username, request=request)
    return render(request, "journal/auth/recovery_codes.html", {"codes": codes})


# --- Mots de passe -------------------------------------------------------------------------

@login_required
@sensitive_post_parameters()
@never_cache
def password_initial(request):
    profile = profile_of(request.user)
    if not profile.must_change_password:
        return redirect("home")
    form = SetPasswordForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        profile.must_change_password = False
        profile.save(update_fields=["must_change_password"])
        update_session_auth_hash(request, request.user)
        record_event("password_initial_changed", actor=request.user, target=request.user.username, request=request)
        return redirect("home")
    return render(request, "journal/auth/password_initial.html", {"form": form})


@login_required
@sensitive_post_parameters()
@never_cache
def account(request):
    profile = profile_of(request.user)
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        update_session_auth_hash(request, request.user)
        record_event("password_changed", actor=request.user, target=request.user.username, request=request)
        messages.success(request, "Mot de passe modifié.")
        return redirect("account")
    return render(request, "journal/auth/account.html", {
        "form": form, "profile": profile, "recovery_left": len(profile.recovery_codes)})


def health(request):
    return HttpResponse("ok", content_type="text/plain")
