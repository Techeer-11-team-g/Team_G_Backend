# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Team_G is an AI-powered fashion image search backend built with Django 4.2 and Django REST Framework. It processes uploaded images through a pipeline: Google Vision object detection → FashionCLIP embeddings → OpenSearch k-NN vector search → LLM re-ranking (Claude/GPT) → virtual try-on (fashn.ai).

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
# Requires Python 3.11.8
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# Celery worker (separate terminal, required for async tasks)
celery -A config worker -l info
# macOS workaround:
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES celery -A config worker -l info -P solo

# Celery beat scheduler (separate terminal)
celery -A config beat -l info
```

### Testing
```bash
python manage.py test                              # All tests
python manage.py test analyses                     # Single app
python manage.py test analyses.tests.TestAnalysisAPI  # Single class
```

### Database Commands
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

## Architecture

### Service Layer (`services/`)
Singleton factory pattern in `services/__init__.py` provides centralized access to external API clients:
- `vision_service.py` - Google Vision API wrapper
- `embedding_service.py` - Marqo-FashionCLIP (Apple Silicon compatible)
- `gpt4v_service.py` - Claude Vision for attribute extraction + ranking
- `opensearch_client.py` - Vector search with k-NN queries
- `langchain_service.py` - LLM orchestration
- `fashn_service.py` - Virtual fitting integration
- `redis_service.py` - State management and caching

### Celery Task Pipeline (`analyses/tasks/`)
Uses chord pattern for parallel processing with callbacks:
- `upload.py` - GCS async upload
- `analysis.py` - Main pipeline: Vision → embedding → search → mapping
- `refine.py` - Natural language re-analysis
- `fitting.py` - Virtual try-on processing

Three named queues with routing in `config/celery.py`:
- `default` - General tasks
- `analysis` - Image analysis (high priority)
- `fitting` - Virtual fitting

### Django Apps
- `analyses/` - Core image analysis pipeline (UploadedImage, ImageAnalysis, DetectedObject, ObjectProductMapping models)
- `fittings/` - Virtual fitting results
- `products/` - Product catalog with SizeCode
- `orders/` - Order management
- `users/` - Custom User model with JWT authentication

### API Endpoints (`/api/v1/`)
```
POST   /uploaded-images          - Upload image → GCS
GET    /uploaded-images/<id>     - Get history + results
POST   /analyses                 - Trigger analysis
GET    /analyses/<id>/status     - Poll status (Redis)
GET    /analyses/<id>            - Get results
PATCH  /analyses                 - Re-analyze with query
```

## Key Configuration

- Django settings: `config/settings.py`
- Celery config: `config/celery.py`
- URL routing: `config/urls.py`
- OpenTelemetry: `config/tracing.py`
- Environment variables: `.env.example` (200+ variables)

## Deployment

GitHub Actions CI/CD in `.github/workflows/deploy.yml` deploys to 4 GCP VMs:
- `deploy/app-server/` - Django + Nginx
- `deploy/queue-server/` - Celery + Redis + RabbitMQ
- `deploy/search-server/` - OpenSearch
- `deploy/monitoring-server/` - Prometheus + Grafana + Loki + Jaeger

See `deploy/DEPLOYMENT.md` for GCP infrastructure setup.

## External Services Required

- OpenAI API (embeddings + chat)
- Anthropic Claude API (vision + text)
- Google Vision API (object detection)
- Google Cloud Storage (image storage)
- fashn.ai / TheNewBlack API (virtual try-on)

## Observability

### Local Services
```bash
# Required for full observability (run separately)
jaeger-all-in-one              # Distributed tracing (http://localhost:16686)
# Loki, Prometheus, Grafana via docker-compose or local install
```

### Distributed Tracing (Jaeger)
OpenTelemetry auto-instruments Django, Celery, requests, and gRPC calls. Custom spans added for pipeline stages.

**View traces:** http://localhost:16686
- Service: `team-g-backend` (Django HTTP)
- Service: `team-g-celery-worker` (Celery tasks)

**Analysis pipeline spans:**
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
Structured JSON logs via `python-logging-loki`. Configure `LOKI_URL` in `.env`.

### Health Check
- `GET /health/` - Application health status
