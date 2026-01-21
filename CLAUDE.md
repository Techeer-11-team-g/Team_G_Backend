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
- `opensearch_client.py` - Vector search with k-NN (HNSW algorithm, cosine similarity)
- `langchain_service.py` - LLM orchestration via LangChain
- `fashn_service.py` - Virtual fitting integration
- `redis_service.py` - Analysis state management (PENDING → RUNNING → DONE/FAILED)
- `metrics.py` - Prometheus custom metrics

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
- `analysis` - Image analysis (high priority)
- `fitting` - Virtual fitting

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

POST   /analyses                 - Trigger analysis on uploaded image
GET    /analyses/<id>            - Get analysis results
GET    /analyses/<id>/status     - Poll status from Redis (fast)
PATCH  /analyses                 - Refine analysis with natural language query

POST   /fittings                 - Create virtual try-on
GET    /fittings/<id>            - Get fitting result

POST   /orders                   - Create order
GET    /orders                   - List orders
GET    /orders/<id>              - Get order details
PATCH  /orders/<id>              - Update order status

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
- Environment variables: `.env.example` (200+ variables)

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
          ├── 0_detect_objects_google_vision
          ├── 1_crop_image
          ├── 2_upload_to_gcs
          ├── 3_extract_attributes_claude
          ├── 4_generate_embedding_fashionclip
          ├── 5_search_opensearch_knn
          ├── 6_rerank_claude
          └── 7_save_results_to_db
```

### Metrics (Prometheus)
Custom metrics in `services/metrics.py`:
- `teamg_analysis_total{status}` - Analysis count by status
- `teamg_analysis_duration_seconds{stage}` - Pipeline stage latency
- `teamg_external_api_requests_total{service,status}` - External API calls
- `teamg_fittings_requested_total{status}` - Fitting requests

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

### AI Agent (Chat) Architecture
`agents/orchestrator.py`의 MainOrchestrator가 메인 진입점:
1. Intent Classification: 키워드 기반 + LLM Function Calling (LangChain)
2. Sub-Agent 라우팅: SearchAgent, FittingAgent, CommerceAgent
3. 세션 상태: Redis에 저장 (2시간 TTL, `agent:session:{id}` 키 패턴)
4. 대화 이력: `agent:session:{id}:turns` 리스트 (최대 20턴)

Intent 분류 우선순위: commerce → fitting → general → refine → search
