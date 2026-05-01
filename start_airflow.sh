#!/bin/bash
# Airflow scheduler + webserver 실행 스크립트
# 사용법: bash start_airflow.sh

export AIRFLOW_HOME=/Users/kimminseok/Desktop/realestate/airflow_home
export REALESTATE_HOME=/Users/kimminseok/Desktop/realestate
export REALESTATE_DB=/Users/kimminseok/Desktop/realestate/realestate.db

# .env 로드
if [ -f "$REALESTATE_HOME/.env" ]; then
  set -a
  source "$REALESTATE_HOME/.env"
  set +a
fi

VENV="$REALESTATE_HOME/venv_airflow"
LOG_DIR="$AIRFLOW_HOME/logs"
mkdir -p "$LOG_DIR"

echo "[Airflow] AIRFLOW_HOME=$AIRFLOW_HOME"
echo "[Airflow] DAGs 폴더: $REALESTATE_HOME/dags"

# 기존 프로세스 종료
pkill -f "airflow scheduler" 2>/dev/null
pkill -f "airflow webserver" 2>/dev/null
sleep 2

# scheduler 백그라운드 실행
echo "[Airflow] scheduler 시작..."
nohup "$VENV/bin/airflow" scheduler >> "$LOG_DIR/scheduler.log" 2>&1 &
echo "scheduler PID: $!"

sleep 3

# webserver 백그라운드 실행 (포트 8080)
echo "[Airflow] webserver 시작 (http://localhost:8080)..."
nohup "$VENV/bin/airflow" webserver --port 8080 >> "$LOG_DIR/webserver.log" 2>&1 &
echo "webserver PID: $!"

echo ""
echo "✅ Airflow 실행 완료"
echo "   UI: http://localhost:8080  (admin / admin1234)"
echo "   로그: $LOG_DIR/"
echo "   종료: bash stop_airflow.sh"
