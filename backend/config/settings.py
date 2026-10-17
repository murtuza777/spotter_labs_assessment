"""Django settings. All environment-specific values come from env vars (see .env.example)."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:5173"]),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-insecure-key")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# Stateless JSON API: no admin, auth, sessions or models.
INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "planner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Weather cells and geocoder results. In production use a file cache so every gunicorn
# worker shares it, e.g. CACHE_URL=filecache:///tmp/planner-cache
CACHES = {"default": env.cache("CACHE_URL", default="locmemcache://planner")}
CACHES["default"].setdefault("OPTIONS", {})["MAX_ENTRIES"] = 50_000

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("API_THROTTLE_RATE", default="120/min"),
        "plan": env("PLAN_THROTTLE_RATE", default="20/min"),
    },
    "EXCEPTION_HANDLER": "planner.views.api_exception_handler",
}

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
# Vercel preview deployments get per-commit URLs; allow them for this project only.
CORS_ALLOWED_ORIGIN_REGEXES = env.list("CORS_ALLOWED_ORIGIN_REGEXES", default=[])

# Behind Render's TLS-terminating proxy.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 0 if DEBUG else 3600
SILENCED_SYSTEM_CHECKS = [
    # Stateless JSON API: no cookies, sessions or forms, so there is nothing for CSRF to protect.
    "security.W003",
    # Render terminates TLS and redirects HTTP itself; its internal health check uses plain
    # HTTP, which a Django-level redirect would break.
    "security.W008",
    # HSTS subdomains/preload: the API lives on the shared onrender.com domain, not ours.
    "security.W005",
    "security.W021",
]

# Third-party providers
TOMTOM_API_KEY = env("TOMTOM_API_KEY", default="")
OPEN_METEO_BASE_URL = env("OPEN_METEO_BASE_URL", default="https://api.open-meteo.com/v1/forecast")
PHOTON_BASE_URL = env("PHOTON_BASE_URL", default="https://photon.komoot.io/api")
HTTP_TIMEOUT_SECONDS = env.float("HTTP_TIMEOUT_SECONDS", default=30.0)

# Weather sampling (see docs/IMPLEMENTATION_PLAN.md section 3)
WEATHER_MODEL = env("WEATHER_MODEL", default="gfs_seamless")
WEATHER_GRID_DEG = env.float("WEATHER_GRID_DEG", default=0.25)
WEATHER_CACHE_TTL_S = env.int("WEATHER_CACHE_TTL_S", default=3600)
WEATHER_BATCH_SIZE = env.int("WEATHER_BATCH_SIZE", default=25)
WEATHER_MAX_WORKERS = env.int("WEATHER_MAX_WORKERS", default=3)
HEATMAP_MAX_POINTS = env.int("HEATMAP_MAX_POINTS", default=220)

# Routing weight = load + an empty tractor-trailer (~35,000 lb is typical for a 5-axle rig).
TRUCK_TARE_LB = env.float("TRUCK_TARE_LB", default=35_000)

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    # httpx logs full request URLs at INFO, and the TomTom key travels in the query string.
    "loggers": {
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}
