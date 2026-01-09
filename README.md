# Team_G_Backend

## 기술 스택

| 분류 | 기술 | 버전 | 용도 |
|------|------|------|------|
| **Backend** | Python | 3.11+ | 런타임 |
| | Django | 4.2.11 LTS | 웹 프레임워크 |
| | Django REST Framework | 3.14.0 | REST API |
| | Gunicorn | 21.2.0 | WSGI 서버 |
| **Task Queue** | Celery | 5.3.6 | 비동기 작업 |
| | RabbitMQ | 3.12 | 메시지 브로커 |
| | Redis | 7.2 | 결과 백엔드 / 캐시 |
| **Database** | MySQL | 8.0 | 메인 DB |
| | OpenSearch | 2.11.1 | 검색 / 벡터 DB |
| **AI** | LangChain | 0.1.16 | LLM 프레임워크 |
| | OpenAI API | - | GPT 모델 |
| **Proxy** | Nginx | 1.24 | 리버스 프록시 |
| **Monitoring** | Prometheus | 2.48.0 | 메트릭 수집 |
| | Grafana | 10.2.2 | 대시보드 |
| | cAdvisor | 0.47.2 | 컨테이너 모니터링 |
| **Logging** | Fluent Bit | 2.2 | 로그 수집 |
| | OpenSearch Dashboards | 2.11.1 | 로그 시각화 |
| **Storage** | Google Cloud Storage | - | 파일 저장 (선택) |
| **Container** | Docker | 24.x | 컨테이너화 |
| | Docker Compose | 3.8 | 오케스트레이션 |

## 프로젝트 구조

```
Team_G_Backend/
├── config/                     # Django 설정
│   ├── settings.py             # 메인 설정
│   ├── celery.py               # Celery 설정
│   ├── urls.py                 # URL 라우팅
│   └── wsgi.py
├── services/                   # 외부 서비스 클라이언트
│   ├── opensearch_client.py    # OpenSearch 클라이언트
│   └── langchain_service.py    # LangChain 서비스
├── deploy/
│   ├── nginx/
│   │   └── nginx.conf          # Nginx 설정
│   ├── fluent-bit/
│   │   ├── fluent-bit.conf     # Fluent Bit 설정
│   │   └── parsers.conf        # 로그 파서
│   └── prometheus/
│       └── prometheus.yml      # Prometheus 설정
├── docker-compose.yml          # 전체 서비스 구성
├── Dockerfile
├── requirements.txt
├── .env.example                # 환경변수 템플릿
└── README.md
```

## 서비스 포트

| 서비스 | 포트 | 설명 |
|--------|------|------|
| Nginx | 80 | 메인 진입점 |
| Django | 8000 | 웹 애플리케이션 |
| MySQL | 3306 | 데이터베이스 |
| Redis | 6379 | 캐시 / Celery 백엔드 |
| RabbitMQ | 5672 | 메시지 브로커 |
| RabbitMQ UI | 15672 | RabbitMQ 관리 콘솔 |
| OpenSearch | 9200 | 검색 엔진 API |
| OpenSearch Dashboards | 5601 | 로그 시각화 |
| Prometheus | 9090 | 메트릭 수집 |
| Grafana | 3000 | 모니터링 대시보드 |
| cAdvisor | 8080 | 컨테이너 메트릭 |

## 초기 세팅

### 방법 1: Docker (권장)

```bash
# 1. 저장소 클론
git clone <repository-url>
cd Team_G_Backend

# 2. 환경변수 설정
cp .env.example .env
# .env 파일 편집하여 값 수정

# 3. Docker Compose 실행
docker-compose up -d

# 4. 마이그레이션 (최초 1회)
docker-compose exec web python manage.py migrate

# 5. 관리자 계정 생성
docker-compose exec web python manage.py createsuperuser
```

### 방법 2: 로컬 개발 환경

```bash
# 1. 저장소 클론
git clone <repository-url>
cd Team_G_Backend

# 2. 가상환경 생성 및 활성화
python3 -m venv venv
source venv/bin/activate  # Mac/Linux
# Windows: venv\Scripts\activate

# 3. 패키지 설치
pip install --upgrade pip
pip install -r requirements.txt

# 4. 환경변수 설정
cp .env.example .env
# .env 파일 편집

# 5. 마이그레이션
python manage.py migrate

# 6. 서버 실행
python manage.py runserver
```

## 서비스 접속 정보

| 서비스 | URL | 계정 |
|--------|-----|------|
| Django Admin | http://localhost:8000/admin | (생성 필요) |
| Grafana | http://localhost:3000 | admin / admin |
| RabbitMQ | http://localhost:15672 | guest / guest |
| OpenSearch Dashboards | http://localhost:5601 | - |
| Prometheus | http://localhost:9090 | - |

## 서비스 사용법

### Celery 태스크

```python
# apps/myapp/tasks.py
from celery import shared_task

@shared_task
def send_email(user_id, subject, message):
    """이메일 발송 태스크"""
    user = User.objects.get(id=user_id)
    user.email_user(subject, message)
    return f"Email sent to {user.email}"

# views.py에서 호출
from .tasks import send_email

def my_view(request):
    # 비동기로 실행 (즉시 반환)
    send_email.delay(user_id=1, subject="Hello", message="World")
    return JsonResponse({"status": "queued"})
```

### RabbitMQ 직접 사용

```python
from services.rabbitmq_client import RabbitMQClient

# 메시지 발행
with RabbitMQClient() as client:
    client.publish('notifications', {
        'type': 'user_signup',
        'user_id': 123
    })

# 메시지 구독 (별도 프로세스에서 실행)
def handle_message(ch, method, properties, body):
    data = json.loads(body)
    print(f"Received: {data}")
    ch.basic_ack(delivery_tag=method.delivery_tag)

with RabbitMQClient() as client:
    client.consume('notifications', handle_message)
```

### OpenSearch

```python
from services.opensearch_client import OpenSearchService

service = OpenSearchService()

# 인덱스 생성
service.create_index('my-index')

# 문서 색인
service.index_document('my-index', {'title': 'Hello', 'content': '...'})

# 검색
results = service.search('my-index', {'query': {'match': {'title': 'Hello'}}})

# 벡터 검색
results = service.vector_search('my-index', vector=[0.1, 0.2, ...], k=10)
```

### LangChain

```python
from services.langchain_service import get_langchain_service

llm = get_langchain_service()

# 채팅
response = llm.chat("안녕하세요!", system_message="You are a helpful assistant.")

# 템플릿 사용
response = llm.chat_with_template(
    "Translate '{text}' to {language}",
    text="Hello",
    language="Korean"
)

# 임베딩
embedding = llm.get_embedding("텍스트")
embeddings = llm.get_embeddings(["텍스트1", "텍스트2"])
```

### Google Cloud Storage

```python
# settings.py에서 GCS_BUCKET_NAME 설정 시 자동 활성화
# 모델에서 FileField/ImageField 사용하면 자동으로 GCS에 저장됨

from django.db import models

class Document(models.Model):
    file = models.FileField(upload_to='documents/')
```

## 환경변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| SECRET_KEY | Django 시크릿 키 | - |
| DEBUG | 디버그 모드 | True |
| DB_NAME | MySQL 데이터베이스명 | team_g_db |
| DB_PASSWORD | MySQL 비밀번호 | - |
| REDIS_HOST | Redis 호스트 | redis |
| RABBITMQ_HOST | RabbitMQ 호스트 | rabbitmq |
| OPENSEARCH_HOST | OpenSearch 호스트 | opensearch |
| OPENAI_API_KEY | OpenAI API 키 | - |
| GCS_BUCKET_NAME | GCS 버킷명 (선택) | - |
| GRAFANA_PASSWORD | Grafana 비밀번호 | admin |

## 모니터링

### Grafana 대시보드 설정

1. http://localhost:3000 접속
2. Data Sources → Add data source → Prometheus
3. URL: `http://prometheus:9090` 입력
4. Dashboard → Import → 추천 대시보드:
   - Django: 17658
   - Docker: 893
   - MySQL: 7362
   - Redis: 763

### 로그 확인

1. http://localhost:5601 접속 (OpenSearch Dashboards)
2. Stack Management → Index Patterns → `logs-*` 생성
3. Discover에서 로그 검색

## Docker 명령어

```bash
# 전체 서비스 시작
docker-compose up -d

# 특정 서비스만 시작
docker-compose up -d web db redis

# 로그 확인
docker-compose logs -f web

# 서비스 중지
docker-compose down

# 볼륨 포함 삭제
docker-compose down -v

# 이미지 재빌드
docker-compose up -d --build
```
