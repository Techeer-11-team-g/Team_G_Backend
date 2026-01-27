# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Team_G is an AI-powered fashion image search backend built with Django 4.2 and Django REST Framework. It processes uploaded images through a pipeline: Google Vision object detection → FashionCLIP embeddings → OpenSearch k-NN vector search → LLM re-ranking (Claude/GPT) → virtual try-on (fashn.ai).

**Python Version:** 3.11.8 (필수) - pyenv 사용 권장

## Build and Run Commands

### Local Development (Docker - Recommended)
```bash
cp .env.example .env  # Edit with API keys
docker-compose up -d
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser
```

### Local Development (Manual)
```bash
# Requires Python 3.11.8 (use pyenv)
pyenv install 3.11.8 && pyenv local 3.11.8
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# Celery worker (separate terminal, required for async tasks)
celery -A config worker -l info
# macOS workaround for fork safety issues:
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES celery -A config worker -l info -P solo

# Celery beat scheduler (separate terminal)
celery -A config beat -l info
```

### Testing
```bash
python manage.py test                              # All tests
python manage.py test analyses                     # Single app
python manage.py test analyses.tests.TestAnalysisAPI  # Single class
python manage.py test --keepdb                     # Preserve test DB between runs
```

### Database Commands
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py shell                             # Django interactive shell
```

### API Documentation
```bash
python manage.py spectacular --validate            # Validate OpenAPI schema
python manage.py spectacular --file schema.yml     # Export schema to file
```

## Architecture

### Service Layer (`services/`)
Singleton factory pattern in `services/__init__.py` provides centralized access to external API clients. All services are lazy-initialized on first call.

```python
# Usage pattern - import getter functions from services/__init__.py
from services import get_vision_service, get_embedding_service, get_redis_service

vision = get_vision_service()        # Returns singleton instance
embedding = get_embedding_service()  # Returns singleton instance
```

Service modules:
- `vision_service.py` - Google Vision API wrapper with category normalization
- `embedding_service.py` - Marqo-FashionCLIP 512-dim embeddings (Apple Silicon compatible with Float64)
- `gpt4v_service.py` - Claude Vision for attribute extraction + ranking
- `hybrid_reranker.py` - 2-stage reranking (cosine similarity + OpenSearch score + attribute matching)
- `opensearch_client.py` - Thin wrapper re-exporting from `services/search/` (backward compatible)
- `langchain_service.py` - LLM orchestration via LangChain
- `fashn_service.py` - Virtual fitting integration
- `redis_service.py` - Analysis state management (PENDING → RUNNING → DONE/FAILED)
- `metrics.py` - Prometheus custom metrics (process, system, business)
- `base.py` - Base classes (`BaseService`, `ExternalAPIService`, `SingletonMeta`, `retry` decorator) for creating new services

### OpenSearch Search Module (`services/search/`)
Modular search implementation split from monolithic `opensearch_client.py`:

```python
# Recommended: import from services/search/
from services.search import OpenSearchService, get_client
from services.search.strategies import SearchStrategies
from services.search.utils import RELATED_CATEGORIES, COLOR_KEYWORDS

# Backward compatible: old import path still works
from services.opensearch_client import OpenSearchClient, get_client
```

Module structure:
- `client.py` - Base OpenSearchClient class, connection management
- `strategies.py` - 6 search strategies (k-NN, hybrid, attribute-based, etc.)
- `utils.py` - Constants (RELATED_CATEGORIES, COLOR_KEYWORDS) and helpers

### Common Utilities (`common/`)
Shared utilities for pagination and serializer optimization:

```python
from common import StandardPagination, paginate_queryset
from common import PrefetchMixin, DynamicFieldsMixin
```

- `pagination.py` - StandardPagination (page_size=20), CursorPaginationMixin
- `serializers.py` - PrefetchMixin (auto setup_eager_loading), DynamicFieldsMixin

### Celery Task Pipeline (`analyses/tasks/`)
Uses Celery Group/Chord pattern for parallel per-object processing:

```python
# Pattern: Group of parallel tasks → callback
chord([task1, task2, task3])(callback)  # Tasks run in parallel
```

Task modules:
- `analysis.py` - Main pipeline: Vision → crop → embed → search → rank → save
- `refine.py` - Natural language re-analysis with query parsing
- `upload.py` - Async GCS upload
- `fitting.py` - Virtual try-on processing
- `storage.py` - GCS download/upload utilities
- `image_processing.py` - Crop, resize, bbox normalization
- `db_operations.py` - Batch DB saves, status updates, metrics recording

Three named queues with routing in `config/celery.py`:
- `default` - General tasks
- `analysis` - Image analysis tasks (`analyses.tasks.*`)
- `fitting` - Virtual fitting tasks (`fittings.tasks.*` only)

### Django Apps
- `analyses/` - Core image analysis pipeline
  - Models: UploadedImage, ImageAnalysis, DetectedObject, ObjectProductMapping, SelectedProduct
  - Views: UploadedImageView, ImageAnalysisView
- `agents/` - AI 패션 어시스턴트 챗봇 (LLM 기반)
  - `orchestrator.py` - 메인 오케스트레이터: Intent Classification → Sub-Agent 라우팅
  - `sub_agents/` - SearchAgent, FittingAgent, CommerceAgent
  - `response_builder.py` - 응답 포맷 생성기
  - `schemas.py` - Intent 분류 스키마 및 지원 카테고리
- `fittings/` - Virtual fitting (UserImage, FittingImage with status caching)
- `products/` - Product catalog (Product, SizeCode)
- `orders/` - Order management (Order, OrderItem, CartItem with soft delete)
- `users/` - Custom User model with JWT auth (simplejwt)

### Data Models Key Patterns

**Soft Delete:** Orders/CartItems use `BaseSoftDeleteModel` with `SoftDeleteManager`
```python
Order.objects.active()   # Only non-deleted
Order.objects.deleted()  # Only deleted
```

**Analysis Status:** Tracked in both MySQL (ImageAnalysis model) and Redis (for fast polling)
```python
# Redis keys pattern
analysis:{id}:status    # PENDING, RUNNING, DONE, FAILED
analysis:{id}:progress  # 0-100 percentage
analysis:{id}:data      # Cached results (24h TTL)
```

### API Endpoints (`/api/v1/`)
```
POST   /uploaded-images          - Upload image (auto_analyze flag triggers pipeline)
GET    /uploaded-images          - List upload history with results
GET    /uploaded-images/<id>     - Get image + analysis results
PATCH  /uploaded-images/<id>/visibility - Toggle public/private

POST   /analyses                 - Trigger analysis on uploaded image
GET    /analyses/<id>            - Get analysis results
GET    /analyses/<id>/status     - Poll status from Redis (fast)
PATCH  /analyses                 - Refine analysis with natural language query

GET    /feed                     - Public feed (Pinterest style, category/style filter)
GET    /feed/styles              - Available style tags
GET    /my-history               - User's analysis history

POST   /fittings                 - Create virtual try-on
GET    /fittings/<id>            - Get fitting result

POST   /orders                   - Create order
GET    /orders                   - List orders
GET    /orders/<id>              - Get order details
PATCH  /orders/<id>              - Update order status
GET    /cart-items               - Get cart items
POST   /cart-items               - Add to cart
DELETE /cart-items/<id>          - Remove from cart

POST   /chat                     - AI 채팅 (메시지 + 이미지)
POST   /chat/status              - 분석/피팅 상태 폴링
GET    /chat/sessions/<id>       - 세션 조회
DELETE /chat/sessions/<id>       - 세션 삭제

POST   /auth/register            - User signup
POST   /auth/login               - JWT token generation
POST   /auth/refresh             - Token refresh
GET    /users/profile            - Get profile (authenticated)
PATCH  /users/profile            - Update profile
```

**Documentation:** `/api/schema/swagger-ui/` (Swagger) or `/api/schema/redoc/` (ReDoc)

## Key Configuration

- Django settings: `config/settings.py`
- Celery config: `config/celery.py` (includes queue routing, worker init hooks)
- URL routing: `config/urls.py`
- OpenTelemetry: `config/tracing.py`
- Request logging middleware: `config/middleware.py`
- Environment variables: `.env` (see `.env.example` for template)

## Deployment

GitHub Actions CI/CD in `.github/workflows/deploy.yml` deploys to 4 GCP VMs:
- `deploy/app-server/` - Django + Nginx + Gunicorn
- `deploy/queue-server/` - Celery workers + Redis + RabbitMQ
- `deploy/search-server/` - OpenSearch
- `deploy/monitoring-server/` - Prometheus + Grafana + Loki + Jaeger

See `deploy/DEPLOYMENT.md` for GCP infrastructure setup.

## External Services Required

- OpenAI API (GPT for chat)
- Anthropic Claude API (vision + text, attribute extraction, ranking)
- Google Vision API (object detection)
- Google Cloud Storage (image storage)
- fashn.ai / TheNewBlack API (virtual try-on)

## Observability

### Distributed Tracing (Jaeger)
OpenTelemetry auto-instruments Django, Celery, requests, and gRPC. Custom spans added for pipeline stages.

**View traces:** http://localhost:16686
- Service: `team-g-backend` (Django HTTP)
- Service: `team-g-celery-worker` (Celery tasks)

**Analysis pipeline span hierarchy:**
```
POST /api/v1/analyses
  └── apply_async/process_image_analysis
      └── run/process_image_analysis
          ├── 1_decode_image_bytes
          ├── 1.5_upload_original_to_gcs  ─┐ (parallel)
          ├── 2_detect_objects_vision_api ─┘
          ├── 3_encode_image_base64
          ├── 4_dispatch_parallel_tasks
          │   └── (per detected object, parallel)
          │       ├── crop_image
          │       ├── upload_to_gcs
          │       ├── extract_attributes_claude
          │       ├── generate_embedding_fashionclip
          │       ├── search_opensearch_knn
          │       ├── 5a_rerank_hybrid_filter  (30→15 candidates)
          │       └── 5b_rerank_claude_final   (15→5 candidates)
          └── 7_save_results_to_db
```

### Metrics (Prometheus)
Custom metrics in `services/metrics.py`:

**Business metrics:**
- `teamg_analysis_total{status}` - Analysis count by status
- `teamg_analysis_duration_seconds{stage}` - Pipeline stage latency
- `teamg_external_api_requests_total{service,status}` - External API calls
- `teamg_fittings_requested_total{status}` - Fitting requests

**Process/System metrics:**
- `teamg_process_cpu_percent` - Django process CPU usage
- `teamg_process_memory_bytes{type=rss|vms}` - Process memory
- `teamg_system_cpu_percent` - System-wide CPU usage
- `teamg_system_memory_bytes{type=total|available|used}` - System memory

Call `update_process_metrics()` to refresh process metrics (auto-called by middleware).

### Logging (Loki)
Structured JSON logs with custom `JsonFormatter`. Use `extra` dict for structured fields:

```python
logger.info(
    "주문 생성 완료",
    extra={
        'event': 'order_created',
        'user_id': user.id,
        'order_id': order.id,
    }
)
```

`RequestLoggingMiddleware` (`config/middleware.py`) auto-logs all API requests/responses.

`SkipHealthMetricsFilter` in `config/settings.py` filters noisy logs: `/health/`, `/metrics/`, Celery heartbeat messages.

### Health Check
- `GET /health/` - Application health status

## Git Branch Conventions

Branch naming: `feat/#<issue>`, `fix/#<issue>`, `refactor/#<issue>`

```bash
# Push with quoted branch name (# requires escaping in bash)
git push origin 'feat/#123'
```

## Key Implementation Details

### Apple Silicon (M1/M2/M3) Support
FashionCLIP in `embedding_service.py` uses Float64 dtype on ARM architecture to avoid numerical precision issues.

### Vision API Category Normalization
`vision_service.py` and `analyses/constants.py` contain `CATEGORY_MAPPING` to normalize variable Vision API labels (e.g., 'sneaker' → 'shoes', 'handbag' → 'bag').

### FashionCLIP Model Warm-up
Model is pre-loaded at Celery worker startup via `worker_process_init` signal in `config/celery.py` to avoid cold start latency.

### GCS Direct Upload Optimization
When `auto_analyze=True`, base64-encoded images are passed directly to analysis tasks, skipping the GCS round-trip for faster processing.

### 2-Stage Hybrid Reranking
`services/hybrid_reranker.py`와 `analyses/constants.py`의 `RerankerConfig`:
1. **1단계 (하이브리드 필터)**: 30개 → 15개 빠르게 필터링
   - 코사인 유사도 70% + OpenSearch 점수 15% + 속성 매칭 15%
2. **2단계 (Claude 최종)**: 15개 → 5개 정확한 순위 결정
   - Claude Vision API로 최종 리랭킹

```python
# analyses/constants.py
class RerankerConfig:
    VISUAL_WEIGHT = 0.70      # 코사인 유사도
    OPENSEARCH_WEIGHT = 0.15  # k-NN 점수
    ATTRIBUTE_WEIGHT = 0.15   # 브랜드/색상 매칭
    USE_HYBRID = True         # False면 Claude only
```

### Parallel Processing in Analysis Pipeline
GCS 업로드와 Vision API 호출은 ThreadPoolExecutor로 병렬 실행됨 (`analyses/tasks/analysis.py`).

### MySQL bulk_create Compatibility
MySQL은 `bulk_create()` 후 ID를 반환하지 않음. `db_operations.py`에서 `max_id_before` 쿼리 후 재조회 방식 사용.

### AI Agent (Chat) Architecture
`agents/orchestrator.py`의 MainOrchestrator가 메인 진입점:
1. Intent Classification: 키워드 기반 + LLM Function Calling (LangChain)
2. Sub-Agent 라우팅: SearchAgent, FittingAgent, CommerceAgent
3. 세션 상태: Redis에 저장 (2시간 TTL, `agent:session:{id}` 키 패턴)
4. 대화 이력: `agent:session:{id}:turns` 리스트 (최대 20턴)

Intent 분류 우선순위: commerce → fitting → general → refine → search
