# Team_G_Backend

## 기술 스택

- Python 3.11+
- Django 4.2.11 (LTS)
- Django REST Framework 3.14.0
- Celery 5.3.6
- Redis 7.2
- MySQL 8.0
- LangChain 0.1.16
- OpenSearch 2.11.1

## 초기 세팅

### 1. 저장소 클론

```bash
git clone <repository-url>
cd Team_G_Backend
```

### 2. 가상환경 생성 및 활성화

```bash
python3 -m venv venv
source venv/bin/activate  # Mac/Linux
# Windows: venv\Scripts\activate
```

### 3. 패키지 설치

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. 환경변수 설정

`.env` 파일을 생성하고 필요한 환경변수를 설정하세요.

```bash
cp .env.example .env  # 예시 파일이 있는 경우
```

## 실행

```bash
# Django 서버 실행
python manage.py runserver

# Celery 워커 실행 (별도 터미널)
celery -A config worker -l info
```
