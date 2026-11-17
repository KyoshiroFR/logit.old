from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import path
from django_otp.plugins.otp_totp.models import TOTPDevice

from registre import security, views
from registre.admin import audit_log

if admin.site.is_registered(TOTPDevice):
    admin.site.unregister(TOTPDevice)

urlpatterns = [
    path("", views.index, name="index"),
    path("historique/", views.history, name="history"),
    path("interventions/nouvelle/", views.edit, name="create"),
    path("interventions/<int:pk>/", views.index, name="detail"),
    path("interventions/<int:pk>/corriger/", views.edit, name="edit"),
    path("captures/<int:pk>/", views.attachment, name="attachment"),
    path("connexion/", security.LogITLoginView.as_view(template_name="login.html"), name="login"),
    path("connexion/nouveau-mot-de-passe/", security.first_password, name="first_password"),
    path("connexion/totp/", security.totp, name="totp"),
    path("deconnexion/", auth.LogoutView.as_view(), name="logout"),
    path("compte/", security.account, name="account"),
    path("compte/securite/", security.account_security, name="account_security"),
    path("compte/securite/mot-de-passe/", security.AccountPasswordChangeView.as_view(), name="account_password"),
    path("administration/journal/", admin.site.admin_view(audit_log), name="admin_audit"),
    path("administration/login/", security.admin_login),
    path("administration/", admin.site.urls),
]
