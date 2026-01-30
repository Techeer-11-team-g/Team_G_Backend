# 이미지 분석 파이프라인 기술 문서

## 개요

사용자가 패션 이미지를 업로드하면, AI가 의류 아이템을 감지하고 유사한 상품을 찾아주는 기능입니다.

---

## 전체 플로우

```
┌─────────────────────────────────────────────────────────────────────┐
│                         프론트엔드                                    │
│                    (이미지 업로드)                                    │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          백엔드                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 1. Google Vision API                                         │   │
│  │    - 이미지에서 패션 아이템 감지 (top, bottom, shoes, outer)    │   │
│  │    - Bounding Box 좌표 반환                                   │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 2. 이미지 크롭                                                │   │
│  │    - 각 아이템별 Bounding Box로 이미지 자르기                   │   │
│  │    - 패딩 추가 (더 나은 임베딩을 위해)                          │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│           ┌──────────────────┼──────────────────┐                   │
│           ▼                  ▼                  ▼                   │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐             │
│  │  아이템 1   │    │  아이템 2   │    │  아이템 3   │  (병렬 처리) │
│  └─────────────┘    └─────────────┘    └─────────────┘             │
│           │                  │                  │                   │
│           ▼                  ▼                  ▼                   │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 3. Claude Haiku - 속성 추출                                   │   │
│  │    - 색상 (color)                                            │   │
│  │    - 브랜드 (brand) - 로고/텍스트에서 감지                      │   │
│  │    - 아이템 타입 (item_type) - sneakers, jacket, jeans 등     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 4. Marqo-FashionCLIP - 임베딩 생성                            │   │
│  │    - 크롭된 이미지 → 512차원 벡터                              │   │
│  │    - FashionCLIP 2.0 대비 +57% 성능 향상                       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 5. OpenSearch - 유사 상품 검색                                │   │
│  │    - 브랜드/색상 필터링 먼저 적용                               │   │
│  │    - k-NN 벡터 유사도로 정렬                                   │   │
│  │    - 상위 30개 후보 반환                                       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 6. MySQL - 상품 상세 정보 조회                                 │   │
│  │    - OpenSearch에서 받은 product_id로 조회                     │   │
│  │    - 상품명, 가격, 이미지 URL 등 반환                          │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                       │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         프론트엔드                                    │
│              (아이템별 TOP 5 유사 상품 표시)                          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 기술 스택

| 구성요소 | 기술 | 용도 |
|---------|-----|------|
| **객체 감지** | Google Vision API | 이미지에서 패션 아이템 위치 감지 |
| **속성 추출** | Claude 3 Haiku | 색상, 브랜드, 아이템 타입 추출 |
| **이미지 임베딩** | Marqo-FashionCLIP | 이미지 → 512차원 벡터 변환 |
| **벡터 검색** | OpenSearch (k-NN) | 유사 상품 벡터 검색 |
| **상품 DB** | MySQL | 상품 상세 정보 저장 |
| **이미지 저장** | Google Cloud Storage | 크롭된 이미지 저장 |

---

## 각 단계 상세

### 1. Google Vision API - 객체 감지

```python
from services.vision_service import get_vision_service

vision_service = get_vision_service()
detected_items = vision_service.detect_objects_from_bytes(image_bytes)

# 반환값 예시
# [
#   DetectedItem(category='top', bbox=BBox(x_min=100, y_min=50, x_max=400, y_max=300), confidence=0.92),
#   DetectedItem(category='bottom', bbox=BBox(...), confidence=0.87),
#   DetectedItem(category='shoes', bbox=BBox(...), confidence=0.85),
# ]
```

**감지 가능한 카테고리:**
- `top` - 상의 (티셔츠, 셔츠, 블라우스 등)
- `bottom` - 하의 (바지, 스커트, 청바지 등)
- `shoes` - 신발
- `outerwear` - 아우터 (자켓, 코트 등)
- `bag` - 가방
- `hat` - 모자

---

### 2. Claude Haiku - 속성 추출

```python
from services.gpt4v_service import get_gpt4v_service

gpt4v_service = get_gpt4v_service()
attributes = gpt4v_service.extract_attributes(cropped_bytes, category)

# 반환값 예시
# FashionAttributes(
#   color='black',
#   brand='adidas',
#   item_type='sneakers',
#   material='leather',
#   style='sporty'
# )
```

**추출 속성:**
| 속성 | 설명 | 예시 |
|-----|------|-----|
| `color` | 주요 색상 | black, white, navy blue |
| `brand` | 브랜드 (로고/텍스트 감지) | Nike, Adidas, Zara |
| `item_type` | 구체적 아이템 종류 | sneakers, track jacket, jeans |
| `material` | 소재 | cotton, leather, denim |
| `style` | 스타일 | casual, sporty, formal |

---

### 3. Marqo-FashionCLIP - 임베딩

```python
from services.embedding_service import get_embedding_service

embedding_service = get_embedding_service()
embedding = embedding_service.get_image_embedding(cropped_bytes)

# 반환값: 512차원 float 리스트
# [0.023, -0.041, 0.087, ...]
```

**모델 정보:**
- 모델: `Marqo/marqo-fashionCLIP`
- 차원: 512
- 성능: FashionCLIP 2.0 대비 +57% 향상

---

### 4. OpenSearch - 벡터 검색

```python
from services.opensearch_client import OpenSearchService

opensearch_service = OpenSearchService()

# 브랜드/색상 필터 + 벡터 유사도
results = opensearch_service.search_with_attributes(
    embedding=embedding,
    category='shoes',
    brand='adidas',
    color='black',
    item_type='sneakers',
    k=30,
    search_k=400
)

# 반환값 예시
# [
#   {'product_id': '12345', 'name': '포럼 로우', 'brand': 'adidas', 'score': 0.92, ...},
#   {'product_id': '12346', 'name': '삼바 OG', 'brand': 'adidas', 'score': 0.89, ...},
#   ...
# ]
```

**검색 전략:**
1. 브랜드가 감지된 경우: 브랜드/색상 필터 → 벡터 유사도 정렬
2. 브랜드 미감지: 순수 벡터 유사도 검색 → 카테고리 필터

---

## 성능 지표

### 처리 시간 (3개 아이템 기준)

| 단계 | 시간 | 비고 |
|-----|------|-----|
| 이미지 업로드 | ~0.5s | 네트워크 의존 |
| Vision API | ~0.5s | |
| Haiku 속성 추출 | ~1.0s | 병렬 처리 |
| Marqo-CLIP 임베딩 | ~0.3s | 병렬 처리 |
| OpenSearch 검색 | ~1.6s | 병렬 처리 |
| MySQL 조회 | ~0.2s | |
| **총 시간** | **~4-5초** | |

### 정확도

| 항목 | 성능 |
|-----|------|
| 객체 감지 | ~90% (Google Vision) |
| 브랜드 감지 | ~85% (로고 있을 때) |
| 유사 상품 매칭 | +57% (vs FashionCLIP 2.0) |

---

## 파일 구조

```
services/
├── vision_service.py      # Google Vision API 객체 감지
├── gpt4v_service.py       # Claude 속성 추출 + 리랭킹
├── embedding_service.py   # Marqo-FashionCLIP 임베딩
├── opensearch_client.py   # OpenSearch 벡터 검색
├── blip_service.py        # BLIP 캡션 (선택적 리랭킹)
└── redis_service.py       # 분석 상태 관리

analyses/
├── views.py               # API 엔드포인트
├── tasks.py               # Celery 비동기 태스크
└── models.py              # 분석 결과 모델
```

---

## API 엔드포인트

### POST /api/v1/analyses

이미지 분석 요청

**Request:**
```json
{
  "image_url": "https://storage.googleapis.com/bucket/image.jpg"
}
```

**Response:**
```json
{
  "analysis_id": "abc123",
  "status": "processing"
}
```

### GET /api/v1/analyses/{id}/status

분석 상태 조회

**Response:**
```json
{
  "analysis_id": "abc123",
  "status": "done",
  "items": [
    {
      "category": "shoes",
      "attributes": {
        "color": "black",
        "brand": "adidas",
        "item_type": "sneakers"
      },
      "matches": [
        {
          "product_id": "12345",
          "name": "포럼 로우 - 블랙",
          "brand": "adidas",
          "price": 139000,
          "image_url": "https://..."
        }
      ]
    }
  ]
}
```

---

## 환경 변수

```bash
# Google Vision API
GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json

# Anthropic Claude
ANTHROPIC_API_KEY=sk-ant-...

# OpenSearch
OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200
OPENSEARCH_USER=admin
OPENSEARCH_PASSWORD=****

# Google Cloud Storage
GCS_BUCKET_NAME=team_g_bucket
GCS_CREDENTIALS_FILE=/path/to/gcs-credentials.json
```

---

## 향후 개선 사항

1. **Marqo-FashionSigLIP 업그레이드** - 768차원, +20% 추가 성능 향상
2. **BLIP/Claude 리랭킹** - 정확도 우선 시 활성화 (시간 +5초)
3. **캐싱** - Redis로 자주 검색되는 임베딩 캐시
4. **배치 처리** - 여러 이미지 동시 분석

---

## 테스트

```bash
# 파이프라인 테스트
python test_pipeline.py

# 단위 테스트
python manage.py test analyses
```
