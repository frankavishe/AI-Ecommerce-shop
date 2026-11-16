from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR.parent / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    "apps.accounts",
    "apps.catalog",
    "apps.orders",
    "apps.payments",
    "apps.ai",
    "apps.whatsapp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://shop:shop@localhost:5432/shop"),
}
CACHES = {"default": env.cache("CACHE_URL", default="locmemcache://")}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = "Africa/Dar_es_Salaam"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

if env("S3_BUCKET", default=""):
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": env("S3_BUCKET"),
                "endpoint_url": env("S3_ENDPOINT_URL", default=None),
                "access_key": env("S3_ACCESS_KEY", default=None),
                "secret_key": env("S3_SECRET_KEY", default=None),
                "custom_domain": env("S3_CUSTOM_DOMAIN", default=None),
                "querystring_auth": False,
            },
        },
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"])

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 24,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {"ai_chat": "20/min", "ai_conversation": "10/min",
                               "whatsapp_link_code": "5/hour"},
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "AI Ecommerce Shop API",
    "VERSION": "0.1.0",
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "OrderStatusEnum": "apps.orders.models.Order.Status",
        "PaymentStatusEnum": "apps.payments.models.Payment.Status",
        "PaymentMethodEnum": "apps.payments.models.Payment.Method",
        "MobileMoneyNetworkEnum": "apps.payments.stakaba.NETWORKS",
        "LanguageEnum": "apps.ai.models.Language",
        "ConversationStateEnum": "apps.ai.models.Conversation.State",
        "DocumentLanguageEnum": "apps.ai.models.KnowledgeDocument.DocLanguage",
    },
}

CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "send-payment-reminders": {
        "task": "apps.orders.tasks.send_payment_reminders",
        "schedule": timedelta(minutes=5),
    },
    "expire-unpaid-orders": {
        "task": "apps.orders.tasks.expire_unpaid_orders",
        "schedule": timedelta(minutes=5),
    },
    "ai-purge-old-conversations": {
        "task": "apps.ai.tasks.purge_old_conversations",
        "schedule": timedelta(days=1),
    },
}

SHOP_CURRENCY = "TZS"
SHOP_DEFAULT_DELIVERY_FEE = Decimal(env("SHOP_DEFAULT_DELIVERY_FEE", default="5000"))
ORDER_REMINDER_MINUTES = env.int("ORDER_REMINDER_MINUTES", default=30)
ORDER_EXPIRY_MINUTES = env.int("ORDER_EXPIRY_MINUTES", default=120)

# Stakaba payments (apps/payments/stakaba.md). sk_test_ keys hit the sandbox, sk_live_ keys move money.
STAKABA_API_KEY = env("STAKABA_API_KEY", default="")
STAKABA_BASE_URL = env("STAKABA_BASE_URL", default="https://api.stakaba.com")
# Secret path segment of the webhook URL (/api/payments/stakaba/webhook/<token>/). Webhooks are
# unsigned, so with no token set the webhook is disabled.
STAKABA_WEBHOOK_TOKEN = env("STAKABA_WEBHOOK_TOKEN", default="")
# Confirm webhooks via GET /transactions/{ref}. Off until Stakaba accepts x-api-key there.
STAKABA_CONFIRM_VIA_API = env.bool("STAKABA_CONFIRM_VIA_API", default=False)

# --- AI assistant (specs/003-ai-core/contracts/model-endpoints.md) ---
AI_CHAT_BASE_URL = env("AI_CHAT_BASE_URL", default="http://localhost:11434/v1")
AI_CHAT_MODEL = env("AI_CHAT_MODEL", default="qwen3:4b-instruct-2507-q4_K_M")
AI_CHAT_NO_THINK = env.bool("AI_CHAT_NO_THINK", default=True)
AI_VISION_BASE_URL = env("AI_VISION_BASE_URL", default="") or AI_CHAT_BASE_URL
AI_VISION_MODEL = env("AI_VISION_MODEL", default="qwen2.5vl:3b")
AI_EMBED_BASE_URL = env("AI_EMBED_BASE_URL", default="http://localhost:11434/v1")
AI_EMBED_MODEL = env("AI_EMBED_MODEL", default="bge-m3")
AI_IMAGE_EMBED_URL = env("AI_IMAGE_EMBED_URL", default="http://localhost:8090")
AI_API_KEY = env("AI_API_KEY", default="ollama")
AI_CHAT_TIMEOUT = env.int("AI_CHAT_TIMEOUT", default=90)  # seconds for one whole chat turn
AI_MAX_STEPS = env.int("AI_MAX_STEPS", default=6)
# caps each chat completion so a looping model cannot hold the server until its context fills
AI_CHAT_MAX_TOKENS = env.int("AI_CHAT_MAX_TOKENS", default=600)
AI_TEXT_DIM = 1024  # fixed by migration ai/0001 (bge-m3)
AI_IMAGE_DIM = 768  # fixed by migration ai/0001 (siglip2-base)
AI_HISTORY_MESSAGES = env.int("AI_HISTORY_MESSAGES", default=12)
AI_MESSAGE_MAX_CHARS = 2000
AI_UPLOAD_MAX_BYTES = 10 * 1024 * 1024
AI_KNOWLEDGE_MIN_SCORE = env.float("AI_KNOWLEDGE_MIN_SCORE", default=0.3)
AI_PRODUCT_MIN_SIMILARITY = env.float("AI_PRODUCT_MIN_SIMILARITY", default=0.3)
AI_IMAGE_MIN_SIMILARITY = env.float("AI_IMAGE_MIN_SIMILARITY", default=0.2)  # photo vs product photo (SigLIP)

# --- Speech-to-text (004, contracts/speech-endpoint.md): OpenAI-compatible /audio/transcriptions ---
AI_SPEECH_BASE_URL = env("AI_SPEECH_BASE_URL", default="http://localhost:8091/v1")
AI_SPEECH_MODEL = env("AI_SPEECH_MODEL", default="small")
AI_SPEECH_TIMEOUT = env.int("AI_SPEECH_TIMEOUT", default=120)

# --- WhatsApp Cloud API (specs/004-whatsapp-channel) ---
WHATSAPP_PHONE_NUMBER_ID = env("WHATSAPP_PHONE_NUMBER_ID", default="")
WHATSAPP_BUSINESS_NUMBER = env("WHATSAPP_BUSINESS_NUMBER", default="")
WHATSAPP_ACCESS_TOKEN = env("WHATSAPP_ACCESS_TOKEN", default="")
WHATSAPP_APP_SECRET = env("WHATSAPP_APP_SECRET", default="")
WHATSAPP_VERIFY_TOKEN = env("WHATSAPP_VERIFY_TOKEN", default="")
WHATSAPP_GRAPH_URL = env("WHATSAPP_GRAPH_URL", default="https://graph.facebook.com")
WHATSAPP_GRAPH_VERSION = env("WHATSAPP_GRAPH_VERSION", default="v23.0")
WHATSAPP_TEMPLATE_ORDER_PAID = env("WHATSAPP_TEMPLATE_ORDER_PAID", default="order_paid")
WHATSAPP_TEMPLATE_ORDER_OUT_FOR_DELIVERY = env("WHATSAPP_TEMPLATE_ORDER_OUT_FOR_DELIVERY", default="order_out_for_delivery")
WHATSAPP_TEMPLATE_ORDER_DELIVERED = env("WHATSAPP_TEMPLATE_ORDER_DELIVERED", default="order_delivered")
WHATSAPP_TEMPLATE_ORDER_CANCELLED = env("WHATSAPP_TEMPLATE_ORDER_CANCELLED", default="order_cancelled")
WHATSAPP_TEMPLATE_ORDER_EXPIRED = env("WHATSAPP_TEMPLATE_ORDER_EXPIRED", default="order_expired")
WHATSAPP_TEMPLATE_FOLLOW_UP = env("WHATSAPP_TEMPLATE_FOLLOW_UP", default="follow_up")
WHATSAPP_RATE_PER_MINUTE = env.int("WHATSAPP_RATE_PER_MINUTE", default=10)
WHATSAPP_RATE_PER_DAY = env.int("WHATSAPP_RATE_PER_DAY", default=200)
WHATSAPP_RESET_DAYS = env.int("WHATSAPP_RESET_DAYS", default=7)
WHATSAPP_VOICE_MAX_SECONDS = env.int("WHATSAPP_VOICE_MAX_SECONDS", default=120)
WHATSAPP_VOICE_MAX_BYTES = env.int("WHATSAPP_VOICE_MAX_BYTES", default=2 * 1024 * 1024)
WHATSAPP_TEXT_LIMIT = env.int("WHATSAPP_TEXT_LIMIT", default=4096)
WHATSAPP_MAX_PRODUCT_PHOTOS = env.int("WHATSAPP_MAX_PRODUCT_PHOTOS", default=3)
# DEBUG only: log outbound payloads instead of calling Meta (quickstart section 2).
WHATSAPP_FAKE_GRAPH = env.bool("WHATSAPP_FAKE_GRAPH", default=False)
WHATSAPP_LOCK_NAMESPACE = env.int("WHATSAPP_LOCK_NAMESPACE", default=4004)
