#!/usr/bin/env python3
"""자정 cron: land_trade 미수집 지역 + 실패 지역 retry"""
import os, sys, datetime
os.chdir("/Users/kimminseok/Desktop/realestate")
sys.stdout.reconfigure(line_buffering=True)

# .env 파일에서 API 키 로딩 (cron은 환경변수 없음)
_env = "/Users/kimminseok/Desktop/realestate/.env"
if os.path.exists(_env):
    with open(_env) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                _k = _k.strip(); _v = _v.strip().strip('"\'')
                if not os.environ.get(_k):  # 비어있거나 미설정이면 덮어쓰기
                    os.environ[_k] = _v

LOG = "/Users/kimminseok/Desktop/realestate/morning_collect.log"

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

log("=== 아침 재수집 시작 ===")

# 1) land_trade 미수집 지역
try:
    from molit_collector import Config, MolitCollector
    api_key = os.getenv("MOLIT_API_KEY", "")
    cfg = Config(api_key=api_key)
    c = MolitCollector(cfg)
    log("land_trade 재수집 시작")
    c.collect(trade_types=["토지_매매"], start_ym="202301")
    c.close()
    log("land_trade 완료")
except Exception as e:
    log(f"land_trade 오류: {e}")

# 2) 실패 지역 retry
try:
    import importlib.util, subprocess
    retry_path = "/Users/kimminseok/Desktop/realestate/retry_failed.py"
    if os.path.exists(retry_path):
        result = subprocess.run(
            [sys.executable, retry_path],
            capture_output=True, text=True, timeout=3600
        )
        log(f"retry 완료 (exit={result.returncode})")
        if result.stdout: log(result.stdout[-500:])
except Exception as e:
    log(f"retry 오류: {e}")

log("=== 전체 완료 ===")
