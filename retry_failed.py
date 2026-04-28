"""
네트워크 오류로 누락된 지역 재수집 스크립트
실패한 테이블별 지역 코드를 하드코딩 + collection_log EMPTY 삭제 후 재수집
"""
import os, sys, sqlite3
sys.path.insert(0, '/Users/kimminseok/Desktop/realestate')
sys.stdout.reconfigure(line_buffering=True)
from molit_collector import Config, MolitCollector, REGION_CODES

cfg = Config(api_key=os.getenv('MOLIT_API_KEY', ''))
c = MolitCollector(cfg)

DB = '/Users/kimminseok/Desktop/realestate/realestate.db'

# ── 테이블별 네트워크 오류 지역 코드 ───────────────────────────
FAILED = {
    # house_rent/commercial_trade/industrial_trade: 재수집 완료 (2026-04-27)
    'house_rent': [],
    'commercial_trade': [],
    'industrial_trade': [],
    # land_trade: EMPTY 자동 탐지로 처리
    'land_trade': [],
}

# land_trade EMPTY 지역 자동 탐지
conn = sqlite3.connect(DB)
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
if 'land_trade' in tables:
    land_empty = [r[0] for r in conn.execute(
        "SELECT DISTINCT region_code FROM collection_log WHERE table_name='land_trade' AND status='EMPTY'"
    )]
    FAILED['land_trade'] = land_empty
    print(f"land_trade EMPTY 탐지: {len(land_empty)}개 지역")
conn.close()

# ── 테이블 → 수집유형 매핑 ───────────────────────────────────
TABLE_TO_TRADE = {
    'house_rent':      '단독다가구_전월세',
    'commercial_trade':'상업업무용_매매',
    'industrial_trade':'공장창고_매매',
    'land_trade':      '토지_매매',
}

def clear_empty(table, region_codes):
    if not region_codes:
        return
    conn = sqlite3.connect(DB)
    placeholders = ','.join('?' for _ in region_codes)
    deleted = conn.execute(
        f"DELETE FROM collection_log WHERE table_name=? AND region_code IN ({placeholders}) AND status='EMPTY'",
        [table] + region_codes
    ).rowcount
    conn.commit()
    conn.close()
    print(f"  EMPTY 삭제: {table} {len(region_codes)}개 지역 {deleted}건")

print("===== 네트워크 오류 지역 재수집 시작 =====")

for table, codes in FAILED.items():
    if not codes:
        print(f"\n[skip] {table}: 재수집 대상 없음")
        continue
    trade_type = TABLE_TO_TRADE[table]
    regions = {k: v for k, v in REGION_CODES.items() if v in codes}
    print(f"\n[{table}] {trade_type} 재수집 — {len(regions)}개 지역")
    clear_empty(table, codes)
    c.collect(trade_types=[trade_type], regions=regions, start_ym='202301')

print("\n===== 재수집 완료 =====")
c.show_stats()
c.close()
