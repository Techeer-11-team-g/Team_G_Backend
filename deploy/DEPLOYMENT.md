# GCE 배포 가이드

## 아키텍처

```
                              ┌─────────────────┐
                              │  Google Cloud   │
                              │    Storage      │
                              └────────┬────────┘
                                       │
┌──────────┐    ┌──────────────────────┼──────────────────────────────────────┐
│  GitHub  │    │                Google Cloud Platform                        │
│          │    │                                                              │
│ Actions ─┼───►│  ┌─────────────────┐      ┌─────────────────┐               │
│          │    │  │   App Server    │      │  Queue Server   │               │
└──────────┘    │  │    (GCE VM)     │      │    (GCE VM)     │               │
                │  ├─────────────────┤      ├─────────────────┤               │
      ┌─────────┼─►│ • Nginx         │◄────►│ • Redis         │               │
      │         │  │ • Django + DRF  │      │ • RabbitMQ      │◄──┐           │
  Flutter       │  │ • LangChain     │      │ • Celery Worker │   │           │
   Client       │  │ • Gunicorn      │      │ • Celery Beat   │   │           │
                │  └────────┬────────┘      └────────┬────────┘   │           │
                │           │                        │            │           │
                │           │         ┌──────────────┘            │           │
                │           │         │                           │           │
                │           ▼         ▼                           │           │
                │  ┌─────────────────────┐    ┌───────────────────┴─────────┐ │
                │  │     Cloud SQL       │    │        외부 API             │ │
                │  │      (MySQL)        │    │  • OpenAI (ChatGPT)         │ │
                │  └─────────────────────┘    │  • Google Vision API        │ │
                │                             │  • fashn-ai                 │ │
                │  ┌─────────────────┐        └─────────────────────────────┘ │
                │  │  Search Server  │                                        │
                │  │    (GCE VM)     │        ┌─────────────────┐             │
                │  ├─────────────────┤        │   Monitoring    │             │
                │  │ • OpenSearch    │◄───────│    (GCE VM)     │             │
                │  │   (검색용)      │        ├─────────────────┤             │
                │  └─────────────────┘        │ • Prometheus    │──►┌───────┐ │
                │                             │ • Grafana       │   │ Slack │ │
                │                             │ • cAdvisor      │   └───────┘ │
                │                             │ • Fluent Bit    │             │
                │                             │ • OpenSearch    │             │
                │                             │   (로깅용)      │             │
                │                             └─────────────────┘             │
                └─────────────────────────────────────────────────────────────┘
```

## 서버 구성

| VM | 구성 요소 | 권장 스펙 | 역할 |
|-----|----------|----------|------|
| **App Server** | Nginx, Django, DRF, LangChain, Gunicorn | e2-medium (2 vCPU, 4GB) | 웹 API 처리 |
| **Queue Server** | Redis, RabbitMQ, Celery Worker/Beat | e2-medium (2 vCPU, 4GB) | 비동기 작업, 외부 API 호출 |
| **Search Server** | OpenSearch | e2-medium (2 vCPU, 4GB) | 검색 엔진 |
| **Monitoring** | Prometheus, Grafana, cAdvisor, Fluent Bit, OpenSearch | e2-small (2 vCPU, 2GB) | 모니터링, 로깅 |
| **Cloud SQL** | MySQL 8.0 | db-f1-micro ~ db-n1-standard-1 | 데이터베이스 |

## 서비스 포트

| 서버 | 서비스 | 포트 | 접근 |
|------|--------|------|------|
| App | Nginx | 80, 443 | 외부 |
| App | Django | 8000 | 내부 |
| Queue | Redis | 6379 | 내부 |
| Queue | RabbitMQ | 5672, 15672 | 내부 |
| Search | OpenSearch | 9200 | 내부 |
| Monitoring | Grafana | 3000 | 외부 |
| Monitoring | Prometheus | 9090 | 내부 |
| Monitoring | OpenSearch Dashboards | 5601 | 내부 |

## 배포 순서

### 1. GCP 초기 설정

```bash
# gcloud 인증
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# VPC 생성
gcloud compute networks create team-g-vpc --subnet-mode=custom
gcloud compute networks subnets create team-g-subnet \
    --network=team-g-vpc \
    --region=asia-northeast3 \
    --range=10.0.0.0/24

# 방화벽 규칙
gcloud compute firewall-rules create allow-internal \
    --network=team-g-vpc --allow=tcp,udp,icmp --source-ranges=10.0.0.0/24

gcloud compute firewall-rules create allow-http \
    --network=team-g-vpc --allow=tcp:80,tcp:443 --target-tags=web-server

gcloud compute firewall-rules create allow-grafana \
    --network=team-g-vpc --allow=tcp:3000 --target-tags=monitoring
```

### 2. Cloud SQL 생성

```bash
gcloud sql instances create team-g-mysql \
    --database-version=MYSQL_8_0 \
    --tier=db-f1-micro \
    --region=asia-northeast3 \
    --network=team-g-vpc \
    --no-assign-ip

gcloud sql databases create team_g_db --instance=team-g-mysql
gcloud sql users create dbuser --instance=team-g-mysql --password=YOUR_PASSWORD
```

### 3. VM 생성

```bash
# Queue Server (먼저)
gcloud compute instances create queue-server \
    --zone=asia-northeast3-a \
    --machine-type=e2-medium \
    --network=team-g-vpc \
    --subnet=team-g-subnet \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=20GB

# Search Server
gcloud compute instances create search-server \
    --zone=asia-northeast3-a \
    --machine-type=e2-medium \
    --network=team-g-vpc \
    --subnet=team-g-subnet \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=50GB

# Monitoring Server
gcloud compute instances create monitoring-server \
    --zone=asia-northeast3-a \
    --machine-type=e2-small \
    --network=team-g-vpc \
    --subnet=team-g-subnet \
    --tags=monitoring \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=30GB

# App Server
gcloud compute instances create app-server \
    --zone=asia-northeast3-a \
    --machine-type=e2-medium \
    --network=team-g-vpc \
    --subnet=team-g-subnet \
    --tags=web-server \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=20GB
```

### 4. Docker 설치 (모든 VM)

```bash
# SSH 접속 후
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
exit  # 재접속
```

### 5. 내부 IP 확인

```bash
gcloud compute instances list --format="table(name,networkInterfaces[0].networkIP)"
```

### 6. 서버별 배포

#### Queue Server
```bash
gcloud compute ssh queue-server --zone=asia-northeast3-a
git clone YOUR_REPO_URL && cd Team_G_Backend/deploy/queue-server
cp .env.example .env && nano .env
docker-compose up -d
```

#### Search Server
```bash
gcloud compute ssh search-server --zone=asia-northeast3-a
cd Team_G_Backend/deploy/search-server
docker-compose up -d
```

#### Monitoring Server
```bash
gcloud compute ssh monitoring-server --zone=asia-northeast3-a
cd Team_G_Backend/deploy/monitoring-server
# prometheus.yml, alertmanager.yml에서 IP 수정
nano prometheus.yml
nano alertmanager.yml  # SLACK_WEBHOOK_URL 설정
cp .env.example .env && nano .env
docker-compose up -d
```

#### App Server
```bash
gcloud compute ssh app-server --zone=asia-northeast3-a
cd Team_G_Backend/deploy/app-server
cp .env.example .env && nano .env
docker-compose up -d
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser
docker-compose exec web python manage.py collectstatic --noinput
```

## GitHub Actions 설정

### Secrets 설정

GitHub Repository → Settings → Secrets에 추가:

| Secret | 설명 |
|--------|------|
| `GCP_PROJECT_ID` | GCP 프로젝트 ID |
| `GCP_SA_KEY` | 서비스 계정 JSON 키 |
| `SLACK_WEBHOOK_URL` | Slack Webhook URL |

### 서비스 계정 생성

```bash
# 서비스 계정 생성
gcloud iam service-accounts create github-actions \
    --display-name="GitHub Actions"

# 권한 부여
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:github-actions@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/compute.instanceAdmin.v1"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:github-actions@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/storage.admin"

# 키 생성
gcloud iam service-accounts keys create key.json \
    --iam-account=github-actions@$PROJECT_ID.iam.gserviceaccount.com
```

## 접속 정보

| 서비스 | URL | 비고 |
|--------|-----|------|
| API | http://APP_SERVER_EXTERNAL_IP | |
| Admin | http://APP_SERVER_EXTERNAL_IP/admin | |
| Grafana | http://MONITORING_SERVER_EXTERNAL_IP:3000 | admin/admin |
| RabbitMQ | http://QUEUE_SERVER_IP:15672 | 내부망 |
| OpenSearch | http://MONITORING_SERVER_IP:5601 | 로그 |
