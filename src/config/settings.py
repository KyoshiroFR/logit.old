"""Configuration LogIT. Tout ce qui dépend de l'installation vient de l'environnement (.env)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_list(name, default=""):
    return os.environ.get(name, default).replace(",", " ").split()


SECRET_KEY = os.environ["LOGIT_SECRET_KEY"]
DEBUG = os.environ.get("LOGIT_DEBUG") == "1"

# Adresses par lesquelles LogIT est joint (IP, nom de machine, domaine).
LOGIT_HOSTS = env_list("LOGIT_HOSTS", "localhost")
ALLOWED_HOSTS = LOGIT_HOSTS + ["127.0.0.1"]
LOGIT_PUBLIC_PORT = os.environ.get("LOGIT_PUBLIC_PORT", "443")
_port = "" if LOGIT_PUBLIC_PORT == "443" else f":{LOGIT_PUBLIC_PORT}"
CSRF_TRUSTED_ORIGINS = [f"https://{host}{_port}" for host in LOGIT_HOSTS]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "journal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "journal.security.SecurityGateMiddleware",
    "journal.security.SecurityHeadersMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "journal.context.roles",
    ]},
}]

# Deux comptes PostgreSQL : le propriétaire applique les migrations, l'application
# tourne avec un compte qui ne peut ni modifier ni supprimer les traces.
_db_role = "OWNER" if os.environ.get("LOGIT_DB_AS_OWNER") == "1" else "APP"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "HOST": os.environ.get("LOGIT_DB_HOST", "db"),
    "PORT": os.environ.get("LOGIT_DB_PORT", "5432"),
    "NAME": os.environ.get("LOGIT_DB_NAME", "logit"),
    "USER": os.environ.get(f"LOGIT_DB_{_db_role}_USER", "logit_app"),
    "PASSWORD": os.environ.get(f"LOGIT_DB_{_db_role}_PASSWORD", ""),
    "CONN_MAX_AGE": 60,
    "TEST": {"NAME": "logit_test"},
}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = os.environ.get("LOGIT_TIME_ZONE", "Europe/Paris")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if DEBUG or os.environ.get("LOGIT_TESTING") == "1":
    STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

# Sécurité des sessions : HTTPS obligatoire, expiration après 8 h et à la fermeture du navigateur.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = not DEBUG
SECURE_REDIRECT_EXEMPT = [r"^sante/$"]
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_AGE = 8 * 3600
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Verrouillage : 5 échecs consécutifs bloquent le compte 15 minutes.
LOGIT_LOCKOUT_ATTEMPTS = 5
LOGIT_LOCKOUT_MINUTES = 15
# Écart au-delà duquel une fiche est signalée « saisie a posteriori ».
LOGIT_LATE_ENTRY_MINUTES = 15

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
