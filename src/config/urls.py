from django.urls import path

from journal import admin_views as admin, bugs, security, views

urlpatterns = [
    path("", views.home, name="home"),
    path("fiches/nouvelle/", views.create, name="create"),
    path("fiches/<int:pk>/", views.detail, name="detail"),
    path("fiches/<int:pk>/apercu/", views.preview, name="preview"),
    path("fiches/<int:pk>/corriger/", views.correct, name="correct"),
    path("fiches/<int:pk>/realisee/", views.complete, name="complete"),
    path("fiches/<int:pk>/annuler/", views.cancel, name="cancel"),
    path("fiches/<int:pk>/retour-arriere/", views.rollback, name="rollback"),
    path("captures/<int:pk>/", views.attachment, name="attachment"),
    path("nouveautes/lu/", views.mark_read, name="mark_read"),

    path("connexion/", security.login_view, name="login"),
    path("connexion/code/", security.totp_verify, name="totp_verify"),
    path("connexion/mot-de-passe/", security.password_initial, name="password_initial"),
    path("deconnexion/", security.logout_view, name="logout"),
    path("compte/", security.account, name="account"),
    path("compte/absence/", security.account_away, name="account_away"),
    path("compte/totp/", security.totp_setup, name="totp_setup"),
    path("compte/totp/desactiver/", security.totp_disable, name="totp_disable"),
    path("compte/codes-de-secours/", security.recovery_regenerate, name="recovery_regenerate"),

    path("admin/comptes/", admin.users, name="admin_users"),
    path("admin/comptes/nouveau/", admin.user_create, name="admin_user_create"),
    path("admin/comptes/<int:pk>/", admin.user_edit, name="admin_user_edit"),
    path("admin/comptes/<int:pk>/mot-de-passe/", admin.user_reset_password, name="admin_user_reset_password"),
    path("admin/comptes/<int:pk>/totp/", admin.user_reset_totp, name="admin_user_reset_totp"),
    path("admin/elements/", admin.elements, name="admin_elements"),
    path("admin/elements/<int:pk>/archiver/", admin.element_toggle, name="admin_element_toggle"),
    path("admin/journal/", admin.audit, name="admin_audit"),
    path("admin/integrite/", admin.integrity, name="admin_integrity"),

    path("bugs/signaler/", bugs.report, name="bug_report"),
    path("bugs/<int:pk>/capture/", bugs.bug_screenshot, name="bug_screenshot"),
    path("admin/bugs/", bugs.bug_list, name="bug_list"),
    path("admin/bugs/<int:pk>/", bugs.bug_detail, name="bug_detail"),

    path("sante/", security.health, name="health"),
]
