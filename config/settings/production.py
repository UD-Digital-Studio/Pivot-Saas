import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403


def required_environment_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"La variable d'environnement {name} est obligatoire.")
    return value


SECRET_KEY = required_environment_value("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = [
    host.strip()
    for host in required_environment_value("DJANGO_ALLOWED_HOSTS").split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

# SQLite3 reste la base initiale. L'accès à la base est centralisé ici pour
# permettre son remplacement par PostgreSQL sans toucher au code métier.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH", BASE_DIR / "pivot.sqlite3"),  # noqa: F405
    }
}

SECURE_SSL_REDIRECT = True
# PythonAnywhere termine HTTPS avant de transmettre la requête à Django.
# Cet en-tête évite une boucle de redirection tout en conservant HTTPS obligatoire.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
