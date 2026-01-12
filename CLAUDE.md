# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Image-based product search + virtual fitting backend service. Users upload an image, the system detects fashion items (shoes, bags, tops, pants), crops and vectorizes them, searches for similar products via OpenSearch k-NN, evaluates results with LangChain, and optionally generates virtual try-on images via fashn.ai.

## Tech Stack

- **Python 3.11.8** (exact version required - team-wide)
- **Django 4.2.11 LTS** + Django REST Framework 3.14.0
- **Celery 5.3.6** with RabbitMQ (broker) and Redis (result backend + cache)
- **MySQL 8.0** (main DB via Cloud SQL)
- **OpenSearch 2.11.1** (vector search with k-NN)
- **External APIs**: Google Vision API, OpenAI API, fashn.ai

## Commands

### Local Development
```bash
# Create virtual environment (must use Python 3.11.8)
python3 -m venv venv
source venv/bin/activate  # Mac/Linux
venv\Scripts\activate      # Windows

pip install -r requirements.txt
cp .env.example .env       # Edit with your API keys

python manage.py migrate
python manage.py runserver
```

### Celery (separate terminals)
```bash
celery -A config worker -l info
celery -A config beat -l info
```

### Docker (recommended for full stack)
```bash
docker-compose up -d
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser
```

### Common Django Commands
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

### Testing
```bash
python manage.py test                    # Run all tests
python manage.py test analyses           # Run tests for specific app
python manage.py test analyses.tests.TestAnalysisAPI  # Run specific test class
```

## Architecture

### Core Flow
```
Image Upload → Google Vision (detect items) → Crop items → OpenAI (vectorize)
    → OpenSearch (k-NN search) → LangChain (evaluate) → Return results
    → (optional) fashn.ai (virtual fitting)
```

### Django Apps

| App | Purpose |
|-----|---------|
| `analyses/` | Image analysis pipeline, Celery tasks, detected objects |
| `products/` | Product catalog, sizes, brands |
| `users/` | Custom User model with profile fields |
| `fittings/` | Virtual fitting images and results |
| `orders/` | Order management |

### Services Module (`services/`)

Each service has a singleton getter pattern:
```python
from services import get_vision_service, get_embedding_service, get_redis_service
from services import OpenSearchService, LangChainService
```

| Service | Purpose |
|---------|---------|
| `vision_service` | Google Vision API - detect fashion items with bounding boxes |
| `embedding_service` | OpenAI API - convert images/text to vectors |
| `opensearch_client` | OpenSearch k-NN - search similar products by vector |
| `langchain_service` | LangChain + GPT - evaluate search quality |
| `fashn_service` | fashn.ai - virtual fitting image generation |
| `redis_service` | Analysis status management (PENDING/RUNNING/DONE/FAILED) |
| `rabbitmq_client` | Direct RabbitMQ connection (Celery uses this implicitly) |

### Celery Tasks (`analyses/tasks.py`)

Main tasks:
- `process_image_analysis` - Full pipeline: detect → crop → embed → search → evaluate
- `process_virtual_fitting` - Virtual try-on via fashn.ai

Task configuration: `@shared_task(bind=True, max_retries=3, default_retry_delay=60)`

### Configuration

All settings via environment variables (`.env` file). Key ones:
- `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`
- `OPENAI_API_KEY`, `FASHN_API_KEY`
- `GOOGLE_APPLICATION_CREDENTIALS`, `GCS_BUCKET_NAME`
- `DB_*` (MySQL), `REDIS_*`, `RABBITMQ_*`, `OPENSEARCH_*`

## Deployment

- **CI/CD**: GitHub Actions (`.github/workflows/deploy.yml`) - pushes to GCR, deploys to GCE
- **Multi-VM architecture**: App Server, Queue Server, Search Server, Monitoring Server
- **See**: `deploy/DEPLOYMENT.md` for full GCE deployment guide

## Service Ports

| Service | Port |
|---------|------|
| Django | 8000 |
| MySQL | 3306 |
| Redis | 6379 |
| RabbitMQ | 5672, 15672 (mgmt) |
| OpenSearch | 9200 |
| Grafana | 3000 |
| Prometheus | 9090 |
