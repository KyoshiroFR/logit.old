from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import path

from registre import views
from registre.admin import audit_log

urlpatterns = [
    path("", views.index, name="index"),
    path("historique/", views.history, name="history"),
    path("interventions/nouvelle/", views.edit, name="create"),
    path("interventions/<int:pk>/", views.index, name="detail"),
    path("interventions/<int:pk>/corriger/", views.edit, name="edit"),
    path("captures/<int:pk>/", views.attachment, name="attachment"),
    path("connexion/", auth.LoginView.as_view(template_name="login.html"), name="login"),
    path("deconnexion/", auth.LogoutView.as_view(), name="logout"),
    path("administration/journal/", admin.site.admin_view(audit_log), name="admin_audit"),
    path("administration/", admin.site.urls),
]
