# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

이미지 기반 상품 검색 + 가상 피팅 백엔드 서비스. 사용자가 이미지를 업로드하면 패션 아이템(신발, 가방, 상의, 하의)을 감지하고, 크롭 후 벡터화하여 OpenSearch k-NN으로 유사 상품을 검색. 선택적으로 fashn.ai로 가상 피팅 이미지 생성.

## 기술 스택

- **Python 3.11.8** (정확한 버전 필수)
- **Django 4.2.11 LTS** + Django REST Framework 3.14.0
- **Celery 5.3.6** - RabbitMQ (브로커) + Redis (결과 백엔드 + 캐시)
- **MySQL 8.0** (메인 DB)
- **OpenSearch 2.11.1** (벡터 검색 k-NN)
- **외부 API**: Google Vision API, OpenAI API, Anthropic Claude API, fashn.ai

## 명령어

### 로컬 개발
```bash
# 가상환경
python3 -m venv venv
source venv/bin/activate  # Mac/Linux
pip install -r requirements.txt

# 환경 설정
cp .env.example .env  # API 키 수정

# 데이터베이스
python manage.py migrate
python manage.py runserver
```

### Celery (별도 터미널)
```bash
# 표준 (Linux/운영)
celery -A config worker -l info

# macOS (fork() 문제 회피)
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES celery -A config worker -l info -P solo
```

### 테스트
```bash
python manage.py test                    # 전체 테스트
python manage.py test analyses           # 특정 앱
python manage.py test analyses.tests.TestAnalysisAPI  # 특정 클래스
```

### Docker
```bash
docker-compose up -d
docker-compose exec web python manage.py migrate
```

## 아키텍처

### 핵심 분석 플로우
```
이미지 업로드 → Google Vision (아이템 감지) → 크롭
    → Claude Vision (속성 추출: 색상, 브랜드, 스타일)
    → Marqo-FashionCLIP (벡터화) → OpenSearch (k-NN 검색)
    → Claude (리랭킹) → MySQL 저장
    → (선택) fashn.ai (가상 피팅)
```

### Django 앱

| 앱 | 용도 |
|-----|---------|
| `users` | 커스텀 유저 모델 (`AUTH_USER_MODEL = 'users.User'`) |
| `products` | 상품 카탈로그 - `Product`, `SizeCode` 모델 |
| `analyses` | 이미지 업로드, 객체 감지, 상품 매칭 파이프라인 |
| `fittings` | fashn.ai 가상 피팅 연동 |
| `orders` | 주문 관리 |

### 핵심 모델 (`analyses/models.py`)

- `UploadedImage` → `ImageAnalysis` (1:N) - 이미지당 분석 작업
- `UploadedImage` → `DetectedObject` (1:N) - 이미지에서 감지된 패션 아이템
- `DetectedObject` → `ObjectProductMapping` → `Product` - k-NN 검색 결과 매핑

### API 엔드포인트 (`analyses/urls.py`)

```
POST /api/v1/uploaded-images              - 이미지 업로드 (GCS 비동기 업로드)
GET  /api/v1/uploaded-images/<id>         - 업로드 히스토리 + 매칭 결과 조회
POST /api/v1/analyses                     - 분석 시작 (Celery 태스크 트리거)
GET  /api/v1/analyses/<id>/status         - 분석 상태/진행률 폴링
GET  /api/v1/analyses/<id>                - 분석 결과 조회
PATCH /api/v1/analyses                    - 자연어 쿼리로 재분석
```

### 서비스 모듈 (`services/`)

외부 API 클라이언트용 싱글톤 패턴:
```python
from services import get_vision_service, get_embedding_service, get_redis_service
from services import OpenSearchService
```

| 서비스 | 용도 |
|---------|---------|
| `vision_service` | Google Vision API - 패션 아이템 감지 + 바운딩 박스 |
| `embedding_service` | Marqo-FashionCLIP - 이미지 → 512차원 벡터 변환 |
| `gpt4v_service` | Claude Vision - 속성 추출 (색상, 브랜드, 스타일) + 리랭킹 |
| `opensearch_client` | OpenSearch k-NN - 벡터로 유사 상품 검색 |
| `langchain_service` | LangChain + GPT - 자연어 재분석 쿼리 파싱 |
| `fashn_service` | fashn.ai - 가상 피팅 이미지 생성 |
| `redis_service` | 분석 상태 관리 (PENDING/RUNNING/DONE/FAILED) |

### Celery 태스크 (`analyses/tasks/`)

기능별 분리:
```
analyses/tasks/
├── __init__.py      # 모든 태스크 re-export
├── upload.py        # upload_image_to_gcs_task
├── analysis.py      # process_image_analysis, process_single_item, analysis_complete_callback
├── refine.py        # parse_refine_query_task, process_refine_analysis, refine_single_object
└── fitting.py       # process_virtual_fitting
```

주요 패턴:
- `@shared_task(bind=True, max_retries=3)` - 재시도 가능한 태스크
- Celery `chord` - 병렬 처리 + 콜백
- Redis - 분석 중 진행률 추적

### 설정

모든 설정은 환경 변수 (`.env` 파일):
- `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `FASHN_API_KEY`
- `GOOGLE_APPLICATION_CREDENTIALS`, `GCS_BUCKET_NAME`
- `DB_*` (MySQL), `REDIS_*`, `OPENSEARCH_*`

## 서비스 포트

| 서비스 | 포트 |
|---------|------|
| Django | 8000 |
| MySQL | 3306 |
| Redis | 6379 |
| RabbitMQ | 5672, 15672 (관리) |
| OpenSearch | 9200 |
