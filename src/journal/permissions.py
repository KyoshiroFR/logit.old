"""Trois rôles : admin (superutilisateur), contributeur, lecteur (groupe Django)."""
from functools import wraps

from django.core.exceptions import PermissionDenied

CONTRIBUTOR = "Contributeur"
READER = "Lecteur"
ROLES = [("admin", "Administrateur"), ("contributor", CONTRIBUTOR), ("reader", READER)]


def is_admin(user):
    return user.is_active and user.is_superuser


def can_write(user):
    return is_admin(user) or user.groups.filter(name=CONTRIBUTOR).exists()


def role_of(user):
    if user.is_superuser:
        return "admin"
    return "contributor" if user.groups.filter(name=CONTRIBUTOR).exists() else "reader"


def writer_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not can_write(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not is_admin(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper
