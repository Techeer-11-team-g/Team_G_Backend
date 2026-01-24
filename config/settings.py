"""
Django settings for config project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-change-this-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'drf_spectacular',
    'rest_framework_simplejwt.token_blacklist',
    'django_prometheus',
    'storages',
    'corsheaders',
    # Local apps
    'users.apps.UsersConfig',
    'products.apps.ProductsConfig',
    'analyses.apps.AnalysesConfig',
    'fittings.apps.FittingsConfig',
    'orders.apps.OrdersConfig',
    'agents.apps.AgentsConfig',
]

# Custom User Model
AUTH_USER_MODEL = 'users.User'

MIDDLEWARE = [
    'django_prometheus.middleware.PrometheusBeforeMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'config.middleware.RequestLoggingMiddleware',  # API 요청/응답 로깅
    'django_prometheus.middleware.PrometheusAfterMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database - MySQL
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

# MySQL Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.getenv('DB_NAME', 'team_g_db'),
        'USER': os.getenv('DB_USER', 'root'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
    }
}

# Local Development (SQLite)
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

# PyMySQL as MySQL client
import pymysql
pymysql.install_as_MySQLdb()


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization

LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True


# Static files

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'


# Default primary key field type

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# =============================================================================
# Redis
# =============================================================================

REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = os.getenv('REDIS_PORT', '6379')
REDIS_URL = f'redis://{REDIS_HOST}:{REDIS_PORT}/0'

# Cache
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': REDIS_URL,
    }
}


# =============================================================================
# Celery Configuration
# =============================================================================

# Broker - RabbitMQ (primary) or Redis (fallback)
CELERY_BROKER_URL = 'amqp://guest:guest@localhost:5672//'

# Result backend - Redis
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'

CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Seoul'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes
CELERY_TASK_ALWAYS_EAGER = False
CELERY_WORKER_HIJACK_ROOT_LOGGER = False  # Django 로깅 설정 사용

# =============================================================================
# OpenSearch Configuration
# =============================================================================

OPENSEARCH_HOST = os.getenv('OPENSEARCH_HOST', 'localhost')
OPENSEARCH_PORT = os.getenv('OPENSEARCH_PORT', '9200')
OPENSEARCH_USER = os.getenv('OPENSEARCH_USER', 'admin')
OPENSEARCH_PASSWORD = os.getenv('OPENSEARCH_PASSWORD', 'admin')
OPENSEARCH_USE_SSL = os.getenv('OPENSEARCH_USE_SSL', 'False').lower() == 'true'


# =============================================================================
# LangChain / OpenAI Configuration
# =============================================================================

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
LANGCHAIN_TRACING_V2 = os.getenv('LANGCHAIN_TRACING_V2', 'false')
LANGCHAIN_API_KEY = os.getenv('LANGCHAIN_API_KEY', '')


# =============================================================================
# The New Black Virtual Try-On Configuration
# =============================================================================

THENEWBLACK_API_KEY = os.getenv('THENEWBLACK_API_KEY', '')


# =============================================================================
# Google Vision API Configuration
# =============================================================================

GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '')


# =============================================================================
# Django REST Framework
# =============================================================================

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}


# =============================================================================
# JWT Settings
# =============================================================================

from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
}


# =============================================================================
# Google Cloud Storage
# =============================================================================

GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', '')
GCS_PROJECT_ID = os.getenv('GCS_PROJECT_ID', '')
GCS_CREDENTIALS_FILE = os.getenv('GCS_CREDENTIALS_FILE', '')

# Use GCS for media files if configured
if GCS_BUCKET_NAME and GCS_CREDENTIALS_FILE and os.path.exists(GCS_CREDENTIALS_FILE):
    from google.oauth2 import service_account
    DEFAULT_FILE_STORAGE = 'storages.backends.gcloud.GoogleCloudStorage'
    GS_BUCKET_NAME = GCS_BUCKET_NAME
    GS_PROJECT_ID = GCS_PROJECT_ID
    GS_CREDENTIALS = service_account.Credentials.from_service_account_file(GCS_CREDENTIALS_FILE)
    GS_DEFAULT_ACL = None  # Uniform bucket-level access 사용 시 ACL 비활성화
    GS_QUERYSTRING_AUTH = False

MEDIA_URL = os.getenv('MEDIA_URL', '/media/')
MEDIA_ROOT = BASE_DIR / 'media'


# =============================================================================
# Logging Configuration
# =============================================================================

LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# Loki configuration
LOKI_URL = os.getenv('LOKI_URL', 'http://localhost:3100/loki/api/v1/push')
LOKI_ENABLED = os.getenv('LOKI_ENABLED', 'true').lower() == 'true'

# Build handlers dict dynamically
_log_handlers = {
    'console': {
        'class': 'logging.StreamHandler',
        'formatter': 'verbose',
    },
    'file': {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': LOG_DIR / 'django.log',
        'maxBytes': 10 * 1024 * 1024,  # 10MB
        'backupCount': 5,
        'formatter': 'json',
    },
}

# Add Loki handler if enabled
if LOKI_ENABLED:
    try:
        import logging_loki
        _log_handlers['loki'] = {
            'class': 'logging_loki.LokiHandler',
            'url': LOKI_URL,
            'tags': {'app': 'team-g-backend', 'env': os.getenv('ENV', 'local')},
            'version': '1',
            'formatter': 'json',  # JSON 구조화 로깅
        }
        # 프로덕션에서는 console도 JSON으로 (로그 수집기 파싱용)
        if os.getenv('ENV') == 'production':
            _log_handlers['console']['formatter'] = 'json'
        _active_handlers = ['console', 'file', 'loki']
    except ImportError:
        _active_handlers = ['console', 'file']
else:
    _active_handlers = ['console', 'file']

# Custom JSON Formatter to include extra fields
import logging
import json as json_module


class SkipHealthMetricsFilter(logging.Filter):
    """Filter out health check, metrics endpoint, and other noisy logs."""

    SKIP_PATHS = ['/metrics', '/health/', '/favicon.ico']
    SKIP_PATTERNS = [
        'HEAD ',  # HEAD 요청
        'heartbeat',  # Celery heartbeat
        'pidbox',  # Celery pidbox (control messages)
        'celery@',  # Celery worker 상태 메시지
        'mingle:',  # Celery mingle
        'connected to',  # 연결 메시지
        'ready.',  # ready 메시지
    ]

    def filter(self, record):
        message = record.getMessage()
        # Skip health/metrics paths
        if any(path in message for path in self.SKIP_PATHS):
            return False
        # Skip noisy patterns
        if any(pattern.lower() in message.lower() for pattern in self.SKIP_PATTERNS):
            return False
        return True


class JsonFormatter(logging.Formatter):
    """JSON Formatter that includes extra fields from log records."""

    RESERVED_ATTRS = {
        'name', 'msg', 'args', 'created', 'filename', 'funcName', 'levelname',
        'levelno', 'lineno', 'module', 'msecs', 'pathname', 'process',
        'processName', 'relativeCreated', 'stack_info', 'exc_info', 'exc_text',
        'thread', 'threadName', 'taskName', 'message',
    }

    def format(self, record):
        log_obj = {
            'timestamp': self.formatTime(record, self.datefmt),
            'level': record.levelname,
            'logger': record.name,
            'module': record.module,
            'message': record.getMessage(),
        }

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS and not key.startswith('_'):
                try:
                    json_module.dumps(value)  # Check if serializable
                    log_obj[key] = value
                except (TypeError, ValueError):
                    log_obj[key] = str(value)

        return json_module.dumps(log_obj, ensure_ascii=False)


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {name} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'json': {
            '()': JsonFormatter,
        },
    },
    'filters': {
        'skip_health_metrics': {
            '()': SkipHealthMetricsFilter,
        },
    },
    'handlers': _log_handlers,
    'root': {
        'handlers': _active_handlers,
        'level': 'INFO',
    },
    'loggers': {
        'django.server': {
            'handlers': _active_handlers,
            'level': 'INFO',
            'filters': ['skip_health_metrics'],
            'propagate': False,
        },
        'django': {
            'handlers': _active_handlers,
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'celery': {
            'handlers': _active_handlers,
            'level': 'INFO',
            'filters': ['skip_health_metrics'],
            'propagate': False,
        },
        'analyses': {
            'handlers': _active_handlers,
            'level': 'INFO',
            'propagate': False,
        },
        'services': {
            'handlers': _active_handlers,
            'level': 'INFO',
            'propagate': False,
        },
        'fittings': {
            'handlers': _active_handlers,
            'level': 'INFO',
            'propagate': False,
        },
        'orders': {
            'handlers': _active_handlers,
            'level': 'INFO',
            'propagate': False,
        },
        'users': {
            'handlers': _active_handlers,
            'level': 'INFO',
            'propagate': False,
        },
        'agents': {
            'handlers': _active_handlers,
            'level': 'INFO',
            'propagate': False,
        },
        'config': {
            'handlers': _active_handlers,
            'level': 'INFO',
            'propagate': False,
        },
    },
}


# =============================================================================
# CORS Configuration
# =============================================================================

CORS_ALLOWED_ORIGINS = os.getenv('CORS_ALLOWED_ORIGINS', 'http://localhost:3000').split(',')
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

SPECTACULAR_SETTINGS = {
    'TITLE': 'Team_G API',
    'DESCRIPTION': '''
## Team_G AI 패션 쇼핑 어시스턴트 API

AI 기반 패션 이미지 분석 및 쇼핑 지원 백엔드 API입니다.

### 주요 기능
- **이미지 분석**: 패션 이미지 업로드 및 AI 분석 (Google Vision + FashionCLIP)
- **상품 검색**: 벡터 유사도 기반 상품 추천 (OpenSearch k-NN)
- **가상 피팅**: AI 가상 피팅 서비스 (fashn.ai)
- **AI 채팅**: 자연어 기반 쇼핑 어시스턴트 (LangChain + Claude)
- **주문 관리**: 장바구니, 주문, 결제 관리

### 인증
JWT Bearer Token 인증을 사용합니다.
1. `/api/v1/auth/register` 또는 `/api/v1/auth/login`으로 토큰 발급
2. `Authorization: Bearer {access_token}` 헤더에 토큰 포함
    ''',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,

    # API 태그 정의 및 순서
    'TAGS': [
        {'name': 'Users', 'description': '사용자 인증 및 프로필 관리'},
        {'name': 'Analyses', 'description': '이미지 업로드 및 AI 분석'},
        {'name': 'Feed', 'description': '공개 피드 및 히스토리'},
        {'name': 'Fittings', 'description': '가상 피팅 서비스'},
        {'name': 'Orders', 'description': '장바구니 및 주문 관리'},
        {'name': 'Chat', 'description': 'AI 패션 어시스턴트 채팅'},
    ],

    # JWT 인증 스키마
    'SECURITY': [{'BearerAuth': []}],
    'APPEND_COMPONENTS': {
        'securitySchemes': {
            'BearerAuth': {
                'type': 'http',
                'scheme': 'bearer',
                'bearerFormat': 'JWT',
                'description': 'JWT access token. `/api/v1/auth/login`에서 발급받은 토큰을 입력하세요.',
            }
        }
    },

    # 스키마 설정
    'COMPONENT_SPLIT_REQUEST': True,
    'SCHEMA_PATH_PREFIX': r'/api/v1/',
    'SCHEMA_PATH_PREFIX_TRIM': False,

    # Swagger UI 설정
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayOperationId': False,
        'filter': True,
        'docExpansion': 'list',
        'defaultModelsExpandDepth': 2,
        'defaultModelExpandDepth': 2,
    },

    # 기타 설정
    'SORT_OPERATIONS': False,  # 태그 순서 유지
    'ENUM_GENERATE_CHOICE_DESCRIPTION': True,
}