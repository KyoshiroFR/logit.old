from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig


class LogITAdminSite(AdminSite):
    def has_permission(self, request):
        user = request.user
        return user.is_active and (user.is_superuser or user.is_staff)


class LogITAdminConfig(AdminConfig):
    default_site = "logit.admin_config.LogITAdminSite"
