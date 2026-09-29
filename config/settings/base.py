import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.organizations",
    "apps.accounts",
    "apps.projects",
    "apps.finance",
    "apps.planning",
    "apps.inventory",
    "apps.collaboration",
    "apps.reporting",
    "apps.audit",
    "apps.ai_assistant",
    "apps.subscriptions",
]

SUBSCRIPTION_TRIAL_MONTHS = int(os.getenv("SUBSCRIPTION_TRIAL_MONTHS", "3"))
SUBSCRIPTIONS_ENABLED = os.getenv("SUBSCRIPTIONS_ENABLED", "true").lower() == "true"
SUBSCRIPTION_TRIAL_PLAN_CODE = os.getenv("SUBSCRIPTION_TRIAL_PLAN_CODE", "professional")
SUBSCRIPTION_GRACE_DAYS = int(os.getenv("SUBSCRIPTION_GRACE_DAYS", "7"))
SUBSCRIPTION_NOTICE_DAYS = tuple(
    int(value.strip()) for value in os.getenv("SUBSCRIPTION_NOTICE_DAYS", "7,3,1").split(",")
    if value.strip()
)
SUBSCRIPTION_PAYMENT_RECHECK_MINUTES = int(
    os.getenv("SUBSCRIPTION_PAYMENT_RECHECK_MINUTES", "2")
)
MESOMB_USE_SYSTEM_PROXY = os.getenv("MESOMB_USE_SYSTEM_PROXY", "false").lower() == "true"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.organizations.middleware.ActiveOrganizationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.subscriptions.middleware.SubscriptionAccessMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.accounts.context_processors.notification_context",
                "apps.subscriptions.context_processors.subscription_access",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr"
LANGUAGES = [
    ("fr", "Français"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Africa/Douala"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

# E-mails transactionnels (invitations, activation et réinitialisation).
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "20"))
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "noreply@pivot.local")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise ValueError("EMAIL_USE_TLS et EMAIL_USE_SSL ne peuvent pas être activés ensemble.")

# Paiements MeSomb. MESOMB_APP_KEY est accepté comme alias pratique.
MESOMB_APPLICATION_KEY = os.environ.get("MESOMB_APPLICATION_KEY") or os.environ.get(
    "MESOMB_APP_KEY", ""
)
MESOMB_ACCESS_KEY = os.environ.get("MESOMB_ACCESS_KEY", "")
MESOMB_SECRET_KEY = os.environ.get("MESOMB_SECRET_KEY", "")
MESOMB_COUNTRY = os.environ.get("MESOMB_COUNTRY", "CM")
MESOMB_CURRENCY = os.environ.get("MESOMB_CURRENCY", "XAF")
MESOMB_CONNECT_TIMEOUT = float(os.environ.get("MESOMB_CONNECT_TIMEOUT", "5"))
MESOMB_READ_TIMEOUT = float(os.environ.get("MESOMB_READ_TIMEOUT", "30"))
PAYMENT_PENDING_TTL_MINUTES = int(
    os.environ.get("PAYMENT_PENDING_TTL_MINUTES", "2")
)
MESOMB_MAX_RETRIES = int(os.environ.get("MESOMB_MAX_RETRIES", "2"))
MESOMB_RETRY_BACKOFF = float(os.environ.get("MESOMB_RETRY_BACKOFF", "0.5"))
MESOMB_OPERATION_MODE = os.environ.get("MESOMB_OPERATION_MODE", "asynchronous").strip().lower()
if MESOMB_OPERATION_MODE not in {"asynchronous", "synchronous"}:
    raise ValueError("MESOMB_OPERATION_MODE doit être 'asynchronous' ou 'synchronous'.")
MESOMB_KEYS_CONFIGURED = all((MESOMB_APPLICATION_KEY, MESOMB_ACCESS_KEY, MESOMB_SECRET_KEY))
PAYMENT_GATEWAY = (
    os.environ.get("PAYMENT_GATEWAY", "mesomb" if MESOMB_KEYS_CONFIGURED else "simulated")
    .strip()
    .lower()
)

# Journal de diagnostic des paiements, visible directement dans le terminal Django.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "payment": {
            "format": "[{asctime}] {levelname} {name} | {message}",
            "style": "{",
        },
    },
    "handlers": {
        "payment_console": {
            "class": "logging.StreamHandler",
            "formatter": "payment",
        },
    },
    "loggers": {
        "pivot.payments": {
            "handlers": ["payment_console"],
            "level": os.environ.get("PAYMENT_LOG_LEVEL", "INFO").upper(),
            "propagate": False,
        },
    },
}

# Assistant IA OpenRouter. La clé reste exclusivement dans l'environnement serveur.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip(
    "/"
)
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openrouter/auto").strip()
OPENROUTER_CONNECT_TIMEOUT = float(os.environ.get("OPENROUTER_CONNECT_TIMEOUT", "5"))
OPENROUTER_READ_TIMEOUT = float(os.environ.get("OPENROUTER_READ_TIMEOUT", "45"))
OPENROUTER_MAX_TOKENS = int(os.environ.get("OPENROUTER_MAX_TOKENS", "800"))
OPENROUTER_TEMPERATURE = float(os.environ.get("OPENROUTER_TEMPERATURE", "0.2"))
OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "http://127.0.0.1:8000").strip()
OPENROUTER_APP_TITLE = os.environ.get("OPENROUTER_APP_TITLE", "PIVOT Engineering").strip()
OPENROUTER_ENABLED = os.environ.get("OPENROUTER_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
} and bool(OPENROUTER_API_KEY)
AI_CONVERSATION_MAX_MESSAGES = int(os.environ.get("AI_CONVERSATION_MAX_MESSAGES", "100"))
AI_CONTEXT_MAX_MESSAGES = int(os.environ.get("AI_CONTEXT_MAX_MESSAGES", "20"))
AI_MESSAGE_MAX_CHARS = int(os.environ.get("AI_MESSAGE_MAX_CHARS", "8000"))
AI_CONVERSATION_RETENTION_DAYS = int(os.environ.get("AI_CONVERSATION_RETENTION_DAYS", "90"))
AI_RATE_LIMIT_REQUESTS = int(os.environ.get("AI_RATE_LIMIT_REQUESTS", "20"))
AI_RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("AI_RATE_LIMIT_WINDOW_SECONDS", "60"))
AI_TOKEN_BUDGET_PER_WINDOW = int(os.environ.get("AI_TOKEN_BUDGET_PER_WINDOW", "50000"))
AI_DUPLICATE_WINDOW_SECONDS = int(os.environ.get("AI_DUPLICATE_WINDOW_SECONDS", "30"))
AI_REQUEST_STALE_SECONDS = int(os.environ.get("AI_REQUEST_STALE_SECONDS", "120"))

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:post-login"
LOGOUT_REDIRECT_URL = "accounts:login"
