#!/bin/bash
# 아침 API quota 리셋 후 재실행
# - land_trade 미수집 지역 (208개)
# - 각 테이블 네트워크/429 오류 지역 retry
LOG=/Users/kimminseok/Desktop/realestate/morning_collect.log
cd /Users/kimminseok/Desktop/realestate

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 아침 재수집 시작 ===" | tee -a "$LOG"

# 1) land_trade: 미수집 지역 수집 (is_collected()가 EMPTY는 재시도)
python3 -u -c "
import os, sys
sys.path.insert(0, '/Users/kimminseok/Desktop/realestate')
sys.stdout.reconfigure(line_buffering=True)
from molit_collector import Config, MolitCollector
cfg = Config(api_key=os.getenv('MOLIT_API_KEY',''))
c = MolitCollector(cfg)
print('===== land_trade 재수집 =====')
c.collect(trade_types=['토지_매매'], start_ym='202301')
c.close()
" >> "$LOG" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] land_trade 완료, retry 시작..." | tee -a "$LOG"

# 2) 전체 오류 지역 retry
python3 -u retry_failed.py >> "$LOG" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 전체 완료 ===" | tee -a "$LOG"
