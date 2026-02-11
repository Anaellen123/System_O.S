from pathlib import Path
import os

# ==================================================
# BASE
# ==================================================
BASE_DIR = Path(__file__).resolve().parent.parent

# ==================================================
# SEGURANÇA
# ==================================================
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-chave-apenas-para-desenvolvimento"
)

DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"

# ==================================================
# HOSTS
# ==================================================
ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "delfina-unprognosticated-javon.ngrok-free.dev",
    # quando subir na VPS, pode adicionar o IP aqui
    # "SEU_IP_DA_VPS",
]

# ==================================================
# APLICAÇÕES
# ==================================================
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

# ==================================================
# MIDDLEWARE
# ==================================================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ==================================================
# URLS / WSGI
# ==================================================
ROOT_URLCONF = "config.urls"

WSGI_APPLICATION = "config.wsgi.application"

# ==================================================
# TEMPLATES
# ==================================================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ==================================================
# BANCO DE DADOS (MYSQL + DOCKER)
# ==================================================
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("MYSQL_DATABASE", "banco_socorro"),
        "USER": os.getenv("MYSQL_USER", "django_user"),
        "PASSWORD": os.getenv("MYSQL_PASSWORD", "Pam-2804$GSE"),
        "HOST": os.getenv("DB_HOST", "db"),
        "PORT": os.getenv("DB_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
        },
    }
}

# ==================================================
# VALIDAÇÃO DE SENHAS
# ==================================================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ==================================================
# IDIOMA / FUSO
# ==================================================
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# ==================================================
# STATIC FILES
# ==================================================
STATIC_URL = "/static/"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"

# ==================================================
# MEDIA FILES
# ==================================================
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ==================================================
# LOGIN / LOGOUT
# ==================================================
LOGIN_URL = "login_admin"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login_admin"

# ==================================================
# HTTPS / NGROK / PROXY REVERSO
# ==================================================
CSRF_TRUSTED_ORIGINS = [
    "https://delfina-unprognosticated-javon.ngrok-free.dev",
]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# ==================================================
# PADRÃO
# ==================================================
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
