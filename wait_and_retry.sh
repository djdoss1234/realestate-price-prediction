#!/bin/bash
# Phase 4 (PID 26449) 완료 대기 후 retry 자동 실행
PID=26449
LOG=/Users/kimminseok/Desktop/realestate/retry_failed.log

echo "[$(date '+%H:%M:%S')] Phase 4 (PID $PID) 완료 대기 중..."
while kill -0 $PID 2>/dev/null; do
    sleep 30
done
echo "[$(date '+%H:%M:%S')] Phase 4 완료! retry 시작..."

cd /Users/kimminseok/Desktop/realestate
nohup python3 -u retry_failed.py >> "$LOG" 2>&1
echo "[$(date '+%H:%M:%S')] retry 완료. 로그: $LOG"
