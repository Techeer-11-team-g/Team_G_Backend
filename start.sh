#!/bin/bash

# Team G Backend 시작 스크립트
cd "$(dirname "$0")"

# .env 파일에서 환경변수 로드
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# 가상환경 활성화
source venv/bin/activate

# 기존 프로세스 종료
pkill -f "runserver" 2>/dev/null
pkill -f "celery" 2>/dev/null
sleep 2

# Django 서버 시작
echo "Django 서버 시작..."
python manage.py runserver 0.0.0.0:8000 > /tmp/django.log 2>&1 &

# Celery 워커 시작 (큐별 분리)
echo "Celery 워커 시작..."

# 분석 전용 워커 (autoscale 2-4)
echo "  - analysis 큐 워커"
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES celery -A config worker -Q analysis -l info --autoscale=4,2 -n analysis@%h > /tmp/celery_analysis.log 2>&1 &

# 피팅 전용 워커 (동시 2개 - 빠른 응답)
echo "  - fitting 큐 워커"
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES celery -A config worker -Q fitting -l info -c 2 -n fitting@%h > /tmp/celery_fitting.log 2>&1 &

# 기본 큐 워커
echo "  - default 큐 워커"
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES celery -A config worker -Q default -l info -c 1 -n default@%h > /tmp/celery_default.log 2>&1 &

sleep 3

echo ""
echo "=== 서버 시작 완료 ==="
echo "Django: http://localhost:8000"
echo ""
echo "로그 파일:"
echo "  - Django: /tmp/django.log"
echo "  - Analysis 워커: /tmp/celery_analysis.log"
echo "  - Fitting 워커: /tmp/celery_fitting.log"
echo "  - Default 워커: /tmp/celery_default.log"
echo ""
ps aux | grep -E "runserver|celery" | grep -v grep
