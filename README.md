# Team_G_Backend

이미지 기반 상품 탐색 + 가상 피팅 + 원터치 구매 웹 서비스의 백엔드입니다.

## 서비스 흐름

```
사용자가 이미지 업로드
       ↓
Google Vision API로 패션 아이템 탐지 (신발, 가방, 상의, 하의 등)
       ↓
각 아이템을 크롭하여 OpenAI로 벡터화
       ↓
OpenSearch에서 유사 상품 검색
       ↓
LangChain으로 검색 품질 평가
       ↓
결과 반환 (bbox 오버레이 + 매칭 상품)
       ↓
(선택) fashn.ai로 가상 피팅
```

---

## 목차

1. [기술 스택](#기술-스택)
2. [프로젝트 구조](#프로젝트-구조)
3. [초기 세팅 가이드](#초기-세팅-가이드)
4. [환경변수 설정](#환경변수-설정)
5. [서비스별 설명](#서비스별-설명)
6. [자주 쓰는 명령어](#자주-쓰는-명령어)
7. [트러블슈팅](#트러블슈팅)

---

## 기술 스택

### 이게 뭔지 모르겠다면?

| 기술 | 한줄 설명 |
|------|----------|
| **Django** | Python으로 웹서버 만드는 프레임워크 (Spring 같은 것) |
| **Django REST Framework** | Django에서 API 쉽게 만들게 해주는 도구 |
| **Celery** | 오래 걸리는 작업을 백그라운드에서 처리 (예: 이미지 분석) |
| **RabbitMQ** | Celery한테 "이 작업 해줘" 라고 전달하는 메신저 |
| **Redis** | 빠른 임시 저장소 (분석 상태 저장용) |
| **MySQL** | 메인 데이터베이스 (사용자, 상품, 분석결과 저장) |
| **OpenSearch** | 벡터 검색용 (유사 상품 찾기) |
| **LangChain** | OpenAI GPT를 쉽게 쓰게 해주는 도구 |
| **Docker** | 모든 서비스를 패키징해서 어디서든 동일하게 실행 |

### 전체 기술 스택 표

| 분류 | 기술 | 버전 | 용도 |
|------|------|------|------|
| **Backend** | Python | 3.11+ | 프로그래밍 언어 |
| | Django | 4.2.11 LTS | 웹 프레임워크 |
| | Django REST Framework | 3.14.0 | REST API |
| | Gunicorn | 21.2.0 | 운영 서버 |
| **Task Queue** | Celery | 5.3.6 | 비동기 작업 처리 |
| | RabbitMQ | 3.12 | 메시지 브로커 |
| | Redis | 7.2 | 캐시 / 상태 저장 |
| **Database** | MySQL | 8.0 | 메인 DB (Cloud SQL) |
| | OpenSearch | 2.11.1 | 벡터 검색 (k-NN) |
| **AI/ML** | LangChain | 0.1.16 | LLM 프레임워크 |
| | OpenAI API | - | GPT, Embeddings |
| | Google Vision API | - | 이미지 객체 탐지 |
| | fashn.ai | - | 가상 피팅 |
| **Infra** | Nginx | 1.24 | 리버스 프록시 |
| | Docker | 24.x | 컨테이너화 |
| **Monitoring** | Prometheus | 2.48 | 메트릭 수집 |
| | Grafana | 10.2 | 대시보드 |
| **Storage** | Google Cloud Storage | - | 이미지 저장 |

---

## 프로젝트 구조

```
Team_G_Backend/
│
├── config/                      # Django 프로젝트 설정
│   ├── __init__.py             # Celery 앱 로드
│   ├── settings.py             # 메인 설정 파일 ⭐
│   ├── celery.py               # Celery 설정
│   ├── urls.py                 # URL 라우팅
│   └── wsgi.py                 # 운영 서버용
│
├── services/                    # 외부 API 연결 모듈 ⭐
│   ├── __init__.py
│   ├── vision_service.py       # Google Vision API (이미지 분석)
│   ├── embedding_service.py    # OpenAI Embeddings (벡터 생성)
│   ├── opensearch_client.py    # OpenSearch (유사 상품 검색)
│   ├── langchain_service.py    # LangChain (GPT 활용)
│   ├── fashn_service.py        # fashn.ai (가상 피팅)
│   ├── redis_service.py        # Redis (상태 관리)
│   └── rabbitmq_client.py      # RabbitMQ (메시지 큐)
│
├── analyses/                    # 이미지 분석 앱
│   ├── __init__.py
│   ├── apps.py
│   └── tasks.py                # Celery 태스크 (분석 파이프라인) ⭐
│
├── deploy/                      # 배포 설정
│   ├── app-server/             # Django 서버
│   ├── queue-server/           # Celery + Redis + RabbitMQ
│   ├── search-server/          # OpenSearch
│   ├── monitoring-server/      # Prometheus + Grafana
│   └── DEPLOYMENT.md           # 배포 가이드
│
├── .github/
│   └── workflows/
│       └── deploy.yml          # GitHub Actions CI/CD
│
├── venv/                        # 가상환경 (git에 안올라감)
├── logs/                        # 로그 파일 (git에 안올라감)
│
├── .env                         # 환경변수 (git에 안올라감) ⭐
├── .env.example                 # 환경변수 예시 파일
├── .gitignore                   # git 제외 파일 목록
├── requirements.txt             # Python 패키지 목록
├── Dockerfile                   # Docker 이미지 빌드 설정
├── docker-compose.yml           # 로컬 개발용 Docker 설정
└── README.md                    # 이 파일
```

### ⭐ 표시된 파일이 중요한 파일입니다!

---

## 초기 세팅 가이드

### 사전 준비물

1. **Git** - 코드 다운로드용
2. **Python 3.11 이상** - [다운로드](https://www.python.org/downloads/)
3. **Docker Desktop** - [다운로드](https://www.docker.com/products/docker-desktop/)

### 설치 확인 방법

터미널(맥) 또는 명령 프롬프트(윈도우)를 열고:

```bash
# Git 확인
git --version
# 예시 출력: git version 2.39.0

# Python 확인
python3 --version
# 예시 출력: Python 3.11.4

# Docker 확인
docker --version
# 예시 출력: Docker version 24.0.0
```

---

### 방법 1: Docker로 실행 (권장 - 가장 쉬움)

```bash
# 1. 코드 다운로드
git clone <repository-url>
cd Team_G_Backend

# 2. 환경변수 파일 만들기
cp .env.example .env

# 3. .env 파일 열어서 수정 (아래 "환경변수 설정" 섹션 참고)
#    - Mac: open .env
#    - Windows: notepad .env

# 4. Docker로 모든 서비스 실행
docker-compose up -d

# 5. 잘 실행됐는지 확인
docker-compose ps

# 6. 데이터베이스 테이블 생성 (최초 1회만)
docker-compose exec web python manage.py migrate

# 7. 관리자 계정 만들기 (최초 1회만)
docker-compose exec web python manage.py createsuperuser
```

**접속 확인:**
- Django: http://localhost:8000
- Django Admin: http://localhost:8000/admin

---

### 방법 2: 로컬에서 직접 실행 (코드 수정하면서 개발할 때)

#### Mac/Linux

```bash
# 1. 코드 다운로드
git clone <repository-url>
cd Team_G_Backend

# 2. 가상환경 만들기 (프로젝트별 독립된 Python 환경)
python3 -m venv venv

# 3. 가상환경 활성화
source venv/bin/activate
# 성공하면 터미널 앞에 (venv) 표시됨

# 4. 패키지 설치
pip install --upgrade pip
pip install -r requirements.txt

# 5. 환경변수 설정
cp .env.example .env
# .env 파일 수정

# 6. 데이터베이스 테이블 생성
python manage.py migrate

# 7. 개발 서버 실행
python manage.py runserver

# 서버 종료: Ctrl + C
# 가상환경 종료: deactivate
```

#### Windows

```bash
# 1. 코드 다운로드
git clone <repository-url>
cd Team_G_Backend

# 2. 가상환경 만들기
python3.11 -m venv venv

# 3. 가상환경 활성화
venv\Scripts\activate
# 성공하면 터미널 앞에 (venv) 표시됨

# 4. 패키지 설치
pip install --upgrade pip
pip install -r requirements.txt

# 5. 환경변수 설정
copy .env.example .env
# .env 파일 메모장으로 수정

# 6. 데이터베이스 테이블 생성
python manage.py migrate

# 7. 개발 서버 실행
python manage.py runserver

# 서버 종료: Ctrl + C
# 가상환경 종료: deactivate
```

---

## 환경변수 설정

`.env` 파일을 열어서 아래 값들을 수정하세요.

### 필수 설정 (반드시 변경)

```bash
# Django 보안 키 (아무 긴 문자열로 변경)
SECRET_KEY=your-super-secret-key-change-this-123456

# OpenAI API 키 (https://platform.openai.com/api-keys 에서 발급)
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx

# fashn.ai API 키 (https://fashn.ai 에서 발급)
FASHN_API_KEY=your-fashn-api-key
```

### Google Cloud 설정 (이미지 분석, 저장용)

```bash
# GCS 버킷 이름
GCS_BUCKET_NAME=your-bucket-name

# GCP 프로젝트 ID
GCS_PROJECT_ID=your-project-id

# 서비스 계정 키 파일 경로
GOOGLE_APPLICATION_CREDENTIALS=/path/to/your-credentials.json
```

### 데이터베이스 설정 (로컬 개발 시)

```bash
# MySQL 설정
DB_NAME=team_g_db
DB_USER=root
DB_PASSWORD=your-password
DB_HOST=localhost        # Docker: db
DB_PORT=3306
```

### 전체 환경변수 목록

| 변수 | 설명 | 필수 | 예시 |
|------|------|------|------|
| `SECRET_KEY` | Django 보안키 | O | 긴 랜덤 문자열 |
| `DEBUG` | 디버그 모드 | X | True (개발), False (운영) |
| `OPENAI_API_KEY` | OpenAI API 키 | O | sk-xxxx |
| `FASHN_API_KEY` | fashn.ai API 키 | O | xxxx |
| `GCS_BUCKET_NAME` | GCS 버킷명 | O | my-bucket |
| `GOOGLE_APPLICATION_CREDENTIALS` | GCP 인증 파일 | O | /path/to/key.json |
| `DB_PASSWORD` | MySQL 비밀번호 | O | - |
| `REDIS_HOST` | Redis 호스트 | X | localhost |
| `OPENSEARCH_HOST` | OpenSearch 호스트 | X | localhost |

---

## 서비스별 설명

### 1. Vision Service (`services/vision_service.py`)

Google Vision API를 사용해서 이미지에서 패션 아이템을 찾습니다.

```python
from services import get_vision_service

vision = get_vision_service()

# 이미지에서 패션 아이템 찾기
items = vision.detect_objects_from_bytes(image_bytes)

# 결과 예시:
# [
#   DetectedItem(category='shoes', bbox=BoundingBox(...), confidence=0.95),
#   DetectedItem(category='bag', bbox=BoundingBox(...), confidence=0.87),
# ]
```

### 2. Embedding Service (`services/embedding_service.py`)

이미지나 텍스트를 벡터(숫자 배열)로 변환합니다. 유사한 상품을 찾는데 사용됩니다.

```python
from services import get_embedding_service

embedding_svc = get_embedding_service()

# 이미지를 벡터로 변환
vector = embedding_svc.get_image_embedding(image_bytes)
# 결과: [0.123, -0.456, 0.789, ...] (1536차원 벡터)
```

### 3. OpenSearch Service (`services/opensearch_client.py`)

벡터로 유사한 상품을 검색합니다 (k-NN 검색).

```python
from services import OpenSearchService

search = OpenSearchService()

# 유사 상품 검색
results = search.search_similar_products(
    embedding=vector,  # 위에서 만든 벡터
    k=5,               # 상위 5개
    category='shoes',  # 신발 카테고리에서만
)
```

### 4. Redis Service (`services/redis_service.py`)

분석 작업의 상태를 관리합니다 (PENDING → RUNNING → DONE).

```python
from services import get_redis_service, AnalysisStatus

redis = get_redis_service()

# 상태 설정
redis.set_analysis_status('analysis-123', AnalysisStatus.RUNNING)

# 상태 확인
status = redis.get_analysis_status('analysis-123')
# 결과: 'RUNNING'
```

### 5. fashn.ai Service (`services/fashn_service.py`)

가상 피팅 이미지를 생성합니다.

```python
from services import get_fashn_service

fashn = get_fashn_service()

# 가상 피팅 요청
result = fashn.create_fitting_and_wait(
    model_image_url='https://...user_photo.jpg',
    garment_image_url='https://...product.jpg',
    category='tops',
)
# result.output_url → 가상 피팅 결과 이미지 URL
```

### 6. LangChain Service (`services/langchain_service.py`)

GPT를 활용한 다양한 작업 (검색 품질 평가 등).

```python
from services import get_langchain_service

llm = get_langchain_service()

# 채팅
response = llm.chat("이 상품에 대해 설명해줘")

# 검색 결과 품질 평가
evaluation = llm.evaluate_search_result(
    category='shoes',
    confidence=0.9,
    match_score=0.85,
    product_id='prod-123',
)
```

---

## 자주 쓰는 명령어

### Git 명령어

```bash
# 최신 코드 받기
git pull

# 내 변경사항 확인
git status

# 변경사항 저장
git add .
git commit -m "작업 내용 설명"
git push
```

### 가상환경 명령어

```bash
# 활성화 (Mac/Linux)
source venv/bin/activate

# 활성화 (Windows)
venv\Scripts\activate

# 비활성화
deactivate

# 새 패키지 설치 후 requirements.txt 업데이트
pip freeze > requirements.txt
```

### Django 명령어

```bash
# 개발 서버 실행
python manage.py runserver

# 데이터베이스 변경사항 적용
python manage.py migrate

# 관리자 계정 생성
python manage.py createsuperuser

# 새 앱 만들기
python manage.py startapp 앱이름
```

### Docker 명령어

```bash
# 모든 서비스 시작
docker-compose up -d

# 모든 서비스 중지
docker-compose down

# 로그 보기
docker-compose logs -f web

# 특정 서비스만 재시작
docker-compose restart web

# Django 명령어 실행
docker-compose exec web python manage.py migrate
```

### Celery 명령어 (로컬 개발 시)

```bash
# Worker 실행 (별도 터미널에서)
celery -A config worker -l info

# Beat 실행 (정기 작업용, 별도 터미널에서)
celery -A config beat -l info
```

---

## 트러블슈팅

### 1. `pip install` 에러

**증상:** `pip install -r requirements.txt` 실행 시 에러

**해결:**
```bash
# pip 업그레이드
pip install --upgrade pip

# 다시 시도
pip install -r requirements.txt
```

### 2. 가상환경이 활성화 안됨

**증상:** `source venv/bin/activate` 실행해도 (venv) 안보임

**해결:**
```bash
# 가상환경 다시 만들기
rm -rf venv
python3 -m venv venv
source venv/bin/activate
```

### 3. Docker 실행 안됨

**증상:** `docker-compose up` 에러

**해결:**
1. Docker Desktop이 실행 중인지 확인
2. 터미널 재시작
3. `docker-compose down -v` 후 다시 `docker-compose up -d`

### 4. 포트 충돌

**증상:** "port is already in use" 에러

**해결:**
```bash
# Mac/Linux: 해당 포트 사용 프로세스 찾기
lsof -i :8000

# 프로세스 종료
kill -9 <PID>
```

### 5. 환경변수 인식 안됨

**증상:** `OPENAI_API_KEY not configured` 등의 경고

**해결:**
1. `.env` 파일이 프로젝트 루트에 있는지 확인
2. 값에 따옴표 없이 입력했는지 확인
3. 서버 재시작

### 6. MySQL 연결 에러

**증상:** "Can't connect to MySQL server"

**해결 (Docker):**
```bash
# MySQL 컨테이너 상태 확인
docker-compose ps db

# 재시작
docker-compose restart db
```

**해결 (로컬):**
- MySQL 서버가 실행 중인지 확인
- `.env`의 DB_HOST, DB_PORT 확인

---

## 서비스 포트 정리

| 서비스 | 포트 | 접속 URL |
|--------|------|----------|
| Django | 8000 | http://localhost:8000 |
| Django Admin | 8000 | http://localhost:8000/admin |
| MySQL | 3306 | - |
| Redis | 6379 | - |
| RabbitMQ | 5672 | - |
| RabbitMQ 관리 | 15672 | http://localhost:15672 |
| OpenSearch | 9200 | - |
| Grafana | 3000 | http://localhost:3000 |
| Prometheus | 9090 | http://localhost:9090 |

---

## 도움이 필요하면?

1. 이 README를 다시 읽어보기
2. 에러 메시지 구글링
3. 팀원에게 물어보기
4. ChatGPT에게 에러 메시지 복붙해서 물어보기

---

## 기여 방법

1. `main` 브랜치에서 새 브랜치 생성
2. 코드 수정
3. Pull Request 생성
4. 코드 리뷰 후 머지

```bash
# 새 브랜치 만들기
git checkout -b feature/기능이름

# 작업 후 푸시
git add .
git commit -m "기능 설명"
git push origin feature/기능이름
```
