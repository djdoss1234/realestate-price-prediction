#!/bin/bash
echo "[Airflow] 프로세스 종료 중..."
pkill -f "airflow scheduler" && echo "scheduler 종료" || echo "scheduler 없음"
pkill -f "airflow webserver" && echo "webserver 종료" || echo "webserver 없음"
pkill -f "gunicorn" 2>/dev/null
echo "완료"
