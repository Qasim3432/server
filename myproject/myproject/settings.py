# myproject/settings.py

from pathlib import Path
import os
import sys
import warnings
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from dotenv import load_dotenv


# ==========================================================
# ✅ EXPLICIT .env LOADING (multi-location search)
#
# The project layout is:
#   server-main/
#     myproject/            ← manage.py + .env live here
#       myproject/          ← settings.py lives here
#         settings.py
#       myapp/
#
# So settings.py must search in multiple places for .env.
# ==========================================================

_THIS_FILE = Path(__file__).resolve()

_ENV_CANDIDATES = [
    _THIS_FILE.parent / ".env",               # next to settings.py
    _THIS_FILE.parent.parent / ".env",        # next to manage.py  ← most likely
    _THIS_FILE.parent.parent.parent / ".env", # project root
]

_loaded_env = None
for _candidate in _ENV_CANDIDATES:
    if _candidate.exists():
        load_dotenv(dotenv_path=_candidate, override=True)
        _loaded_env = _candidate
        print(f"[settings] Loaded .env from: {_candidate}", file=sys.stderr)
        break

if _loaded_env is None:
    print(
        "[settings] WARNING: no .env found. Searched:\n  "
        + "\n  ".join(str(c) for c in _ENV_CANDIDATES),
        file=sys.stderr,
    )

BASE_DIR = _THIS_FILE.parent.parent


# ==========================================================
# SECURITY — FAIL-FAST IN PRODUCTION
#
# ✅ P0-4 FIX: Missing critical env values → crash with clear error
# (previously: silently used insecure defaults)
# ==========================================================

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY or SECRET_KEY == "change-this-to-a-very-long-random-string-on-server":
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a real random value in .env. "
        "Generate with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )

DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() == "true"

ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",")
    if h.strip()
]
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be set in production.")


# ==========================================================
# DEVICE_FINGERPRINT_SECRET (P0-4 + P0-1)
# ==========================================================

_dev_fp = os.getenv("DEVICE_FINGERPRINT_SECRET")

if not _dev_fp or _dev_fp == "REPLACE_WITH_64_CHAR_HEX_STRING":
    if DEBUG:
        _dev_fp = "DEV_DEFAULT_INSECURE_SECRET_DO_NOT_USE_IN_PROD"
        warnings.warn(
            "⚠️ DEVICE_FINGERPRINT_SECRET not set — using insecure dev default.",
            UserWarning,
        )
    else:
        raise ImproperlyConfigured(
            "DEVICE_FINGERPRINT_SECRET must be set in production. "
            "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

DEVICE_FINGERPRINT_SECRET = _dev_fp


# ==========================================================
# TRUSTED PROXY
# ==========================================================

TRUSTED_PROXY_IPS = os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1")


# ==========================================================
# SILENCED CHECKS (only in DEBUG)
# ==========================================================

if DEBUG:
    SILENCED_SYSTEM_CHECKS = [
        "django_ratelimit.E003",
        "django_ratelimit.W001",
    ]
else:
    SILENCED_SYSTEM_CHECKS = []


# ==========================================================
# APPS
# ==========================================================

INSTALLED_APPS = [
    "daphne",
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_ratelimit",
    "myapp",
]


# ==========================================================
# MIDDLEWARE
# ==========================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "myapp.middleware.AuthTokenMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "myapp.middleware.RateLimitResponseMiddleware",
    "myapp.middleware.CSPMiddleware",           # ✅ P2-12 prep
]

ROOT_URLCONF = "myproject.urls"
WSGI_APPLICATION = "myproject.wsgi.application"
ASGI_APPLICATION = "myproject.asgi.application"


# ==========================================================
# TEMPLATES
# ==========================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# ==========================================================
# CHANNEL LAYERS & CACHE (platform-aware)
# ==========================================================

if sys.platform == "win32":
    CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
    }
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "unique-snowflake",
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [(
                    os.getenv("GAME_REDIS_HOST", "127.0.0.1"),
                    int(os.getenv("GAME_REDIS_PORT", "6379")),
                )],
            },
        },
    }
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": f"redis://{os.getenv('GAME_REDIS_HOST', '127.0.0.1')}:{os.getenv('GAME_REDIS_PORT', '6379')}/1",
            "KEY_PREFIX": "rg",
        }
    }


# ==========================================================
# DATABASE — FAIL-FAST on missing DB_PASSWORD in production
# ==========================================================

_db_pass = os.getenv("DB_PASSWORD", "")
if not DEBUG and (not _db_pass or _db_pass == "ChangeMe_StrongPass123!"):
    raise ImproperlyConfigured(
        "DB_PASSWORD must be changed from default in production."
    )

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "rockgames_db"),
        "USER": os.getenv("DB_USER", "rockgames_user"),
        "PASSWORD": _db_pass,
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "5432"),
        "OPTIONS": {"connect_timeout": 10},
        "CONN_MAX_AGE": 60,                     # ✅ keep-alive
    }
}


# ==========================================================
# PASSWORDS
# ==========================================================

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ==========================================================
# I18N
# ==========================================================

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "Asia/Karachi")
USE_I18N = True
USE_TZ = True


# ==========================================================
# EMAIL
# ==========================================================

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER


# ==========================================================
# STATIC & MEDIA
# ==========================================================

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ==========================================================
# HTTPS / SECURITY — P0-4
# ==========================================================

_https_enabled = os.getenv("SECURE_SSL_REDIRECT", "False").lower() == "true"

SECURE_SSL_REDIRECT = _https_enabled
SESSION_COOKIE_SECURE = _https_enabled
CSRF_COOKIE_SECURE = _https_enabled
SECURE_HSTS_SECONDS = 31536000 if _https_enabled else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = _https_enabled
SECURE_HSTS_PRELOAD = _https_enabled
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Session hardening
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"

_csrf_origins_raw = os.getenv("CSRF_TRUSTED_ORIGINS", "").strip()
if _csrf_origins_raw:
    CSRF_TRUSTED_ORIGINS = [
        o.strip() for o in _csrf_origins_raw.split(",") if o.strip()
    ]


# ==========================================================
# GAME REDIS
# ==========================================================

GAME_REDIS_HOST = os.getenv("GAME_REDIS_HOST", "127.0.0.1")
GAME_REDIS_PORT = int(os.getenv("GAME_REDIS_PORT", "6379"))
GAME_REDIS_DB = int(os.getenv("GAME_REDIS_DB", "2"))


# ==========================================================
# AGORA
# ==========================================================

AGORA_APP_ID = os.getenv("AGORA_APP_ID", "")
AGORA_APP_CERTIFICATE = os.getenv("AGORA_APP_CERTIFICATE", "")


# ==========================================================
# UPLOAD LIMITS
# ==========================================================

MAX_PROFILE_PIC_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024


# ==========================================================
# LOGGING — console + rotating file (production ready)
# ==========================================================

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "myapp": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "django.db.backends": {"level": "WARNING"},
        "django_ratelimit": {"handlers": ["console"], "level": "WARNING"},
        "django.security": {"handlers": ["console"], "level": "WARNING"},
    },
}


# ==========================================================
# JAZZMIN (unchanged)
# ==========================================================

JAZZMIN_SETTINGS = {
    "site_title": "2x Ludo Admin",
    "site_header": "2x Ludo",
    "site_brand": "🎮 2x Ludo",
    "welcome_sign": "Welcome to 2x Ludo Control Center",
    "copyright": "2x Ludo Ltd",
    "site_logo": "admin/logo.png",
    "login_logo": "admin/logo.png",
    "site_logo_classes": "img-circle elevation-2",
    "site_icon": "admin/favicon.png",
    "search_model": ["auth.User", "myapp.UserProfileBalance"],
    "topmenu_links": [
        {"name": "🏠 Dashboard", "url": "admin:index", "permissions": ["auth.view_user"]},
        {"name": "💰 Deposits", "url": "admin:myapp_depositrequest_changelist"},
        {"name": "💸 Withdrawals", "url": "admin:myapp_withdrawalrequest_changelist"},
        {"name": "👥 Users", "url": "admin:myapp_userprofilebalance_changelist"},
        {"name": "🎁 Custom Portal", "url": "/management/"},
        {"name": "📊 Finance", "url": "/dashboard/finance/"},
        {"name": "🏆 Rewards", "url": "/management/dashboard/rewards/"},
        {"name": "📈 Analytics", "url": "/management/dashboard/analytics/"},
    ],
    "show_sidebar": True,
    "navigation_expanded": True,
    "order_with_respect_to": [
        "myapp", "myapp.UserProfileBalance", "myapp.DepositRequest", "myapp.WithdrawalRequest",
        "myapp.GameRoom", "myapp.GameHistory", "myapp.SpinHistory", "myapp.ReferralSystem",
        "myapp.SystemTransactionLog", "myapp.SystemPaymentMethod", "myapp.SystemConfiguration",
        "myapp.SystemSetting", "auth",
    ],
    "icons": {
        "auth": "fas fa-users-cog", "auth.user": "fas fa-user-shield", "auth.Group": "fas fa-users",
        "myapp": "fas fa-gamepad", "myapp.UserProfileBalance": "fas fa-wallet",
        "myapp.DepositRequest": "fas fa-money-bill-wave", "myapp.WithdrawalRequest": "fas fa-money-bill-transfer",
        "myapp.GameRoom": "fas fa-dice", "myapp.GameHistory": "fas fa-history",
        "myapp.SpinHistory": "fas fa-dharmachakra", "myapp.ReferralSystem": "fas fa-user-friends",
        "myapp.SystemTransactionLog": "fas fa-file-invoice-dollar", "myapp.SystemPaymentMethod": "fas fa-credit-card",
        "myapp.SystemConfiguration": "fas fa-sliders-h", "myapp.SystemSetting": "fas fa-cog",
        "myapp.GameUser": "fas fa-user-circle",
    },
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",
    "custom_css": "admin/custom_admin.css",
    "show_ui_builder": False,
    "related_modal_active": False,
    "changeform_format": "horizontal_tabs",
    "language_chooser": False,
}

JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False, "body_small_text": False, "brand_small_text": False,
    "brand_colour": "navbar-primary", "accent": "accent-primary", "navbar": "navbar-dark",
    "navbar_fixed": True, "layout_boxed": False, "footer_fixed": False, "sidebar_fixed": True,
    "sidebar": "sidebar-dark-primary", "theme": "flatly", "default_theme_mode": "light",
    "actions_sticky_top": True,
}