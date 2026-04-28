"""
한국은행 ECOS 거시지표 수집기
================================
수집 항목:
  - 기준금리          (722Y001 / 0101000)   → ecos_base_rate
  - 주택담보대출금리  (121Y006 / BECBLA0302) → ecos_mortgage_rate
  - M2 통화량         (161Y006 / BBHA00)     → ecos_money_supply
  - 경기선행지수      (901Y067 / I16A)       → ecos_leading_index
  - 가계대출잔액 (분기)(151Y001 / 1100000)  → ecos_household_loan

API: https://ecos.bok.or.kr (한국은행 경제통계시스템)
키 발급: https://ecos.bok.or.kr/#/ApiKeyInfo/BasicInfo
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

ECOS_BASE_URL = "https://ecos.bok.or.kr/api/StatisticSearch"

# (stat_code, item_code, column_name, freq, unit_desc)
INDICATORS = [
    ("722Y001", "0101000",    "base_rate",      "M", "기준금리(%)"),
    ("121Y006", "BECBLA0302", "mortgage_rate",  "M", "주택담보대출금리(%)"),
    ("161Y006", "BBHA00",     "m2_billion",     "M", "M2통화량(십억원)"),
    ("901Y067", "I16A",       "leading_index",  "M", "경기선행지수"),
    ("151Y001", "1100000",    "household_loan_billion", "Q", "가계대출잔액(십억원)"),
]

DDL = """
CREATE TABLE IF NOT EXISTS ecos_macro (
    ym           TEXT    NOT NULL,   -- YYYYMM
    base_rate    REAL,               -- 기준금리 (%)
    mortgage_rate REAL,              -- 주택담보대출금리 (%)
    m2_trillion   REAL,              -- M2 (조원)
    m2_growth_3m  REAL,              -- M2 전3개월 대비 증가율 (%)
    leading_index REAL,              -- 경기선행지수
    household_loan_trillion REAL,    -- 가계대출잔액 (조원, 분기 forward-fill)
    rate_chg_3m  REAL,               -- 기준금리 3개월 변화
    rate_chg_6m  REAL,               -- 기준금리 6개월 변화
    collected_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (ym)
)"""


class EcosCollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key = api_key or os.getenv("ECOS_API_KEY", "")
        self.db_path = db_path
        self.session = requests.Session()
        self._init_table()

    def _init_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL)

    def _fetch(self, stat: str, item: str, freq: str, start: str, end: str) -> dict[str, float]:
        if not self.api_key:
            return {}
        url = (f"{ECOS_BASE_URL}/{self.api_key}/json/kr/1/500"
               f"/{stat}/{freq}/{start}/{end}/{item}")
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            rows = resp.json().get("StatisticSearch", {}).get("row", [])
            return {r["TIME"]: float(r["DATA_VALUE"]) for r in rows if r.get("DATA_VALUE")}
        except Exception as e:
            log.warning("ECOS fetch 실패 [%s/%s]: %s", stat, item, e)
            return {}

    def collect(self, start_ym: str = "202001") -> int:
        if not self.api_key:
            log.warning("ECOS_API_KEY 없음 — 수집 스킵")
            return 0

        from datetime import datetime
        now    = datetime.now()
        end_ym = now.strftime("%Y%m")
        end_q  = f"{now.year}Q{(now.month - 1) // 3 + 1}"
        start_q = f"{start_ym[:4]}Q1"

        base  = self._fetch("722Y001", "0101000",    "M", start_ym, end_ym)
        mort  = self._fetch("121Y006", "BECBLA0302", "M", start_ym, end_ym)
        m2    = self._fetch("161Y006", "BBHA00",     "M", start_ym, end_ym)
        lead  = self._fetch("901Y067", "I16A",       "M", start_ym, end_ym)

        # 분기 데이터 → 분기 시작월로 키 변환
        q2m  = {"Q1": "01", "Q2": "04", "Q3": "07", "Q4": "10"}
        raw_q = self._fetch("151Y001", "1100000", "Q", start_q, end_q)
        hloan = {
            t[:4] + q2m[t[4:]]: v / 1_000  # 십억→조원
            for t, v in raw_q.items()
            if len(t) == 6 and t[4:] in q2m
        }

        yms = sorted(set(base))
        if not yms:
            log.warning("ECOS 기준금리 데이터 없음")
            return 0

        # forward-fill: 분기 가계대출, 미공표 항목
        last_loan: Optional[float] = None
        last_vals = {c: None for c in ["mortgage_rate", "m2_trillion", "leading_index"]}
        records: list[dict] = []

        for i, ym in enumerate(yms):
            b  = base.get(ym)
            m  = mort.get(ym)
            m2v = m2.get(ym)
            lv  = lead.get(ym)

            b3 = round(b - base.get(yms[i-3], b), 4) if i >= 3 and b is not None else 0.0
            b6 = round(b - base.get(yms[i-6], b), 4) if i >= 6 and b is not None else 0.0
            m2_tri = m2v / 1_000 if m2v is not None else None  # 십억→조원

            if ym in hloan:
                last_loan = hloan[ym]

            # forward-fill 미공표 항목
            for col, val in [("mortgage_rate", m), ("m2_trillion", m2_tri), ("leading_index", lv)]:
                if val is not None:
                    last_vals[col] = val
                else:
                    val = last_vals[col]
                if col == "mortgage_rate": m = val
                if col == "m2_trillion":   m2_tri = val
                if col == "leading_index": lv = val

            records.append({
                "ym":              ym,
                "base_rate":       b,
                "mortgage_rate":   m,
                "m2_trillion":     m2_tri,
                "m2_growth_3m":    None,   # 아래에서 계산
                "leading_index":   lv,
                "household_loan_trillion": last_loan,
                "rate_chg_3m":     b3,
                "rate_chg_6m":     b6,
            })

        # M2 증가율_3개월 계산
        for i, rec in enumerate(records):
            if i >= 3:
                cur = rec["m2_trillion"]
                prv = records[i-3]["m2_trillion"]
                if cur is not None and prv and prv != 0:
                    rec["m2_growth_3m"] = round((cur - prv) / prv * 100, 4)

        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO ecos_macro
                (ym, base_rate, mortgage_rate, m2_trillion, m2_growth_3m,
                 leading_index, household_loan_trillion, rate_chg_3m, rate_chg_6m)
                VALUES (:ym, :base_rate, :mortgage_rate, :m2_trillion, :m2_growth_3m,
                        :leading_index, :household_loan_trillion, :rate_chg_3m, :rate_chg_6m)
            """, records)

        log.info("ecos_macro 저장: %d건", len(records))
        return len(records)

    def load_rates(self) -> dict[str, dict]:
        """DB에서 거시지표 로드 → api.py _fetch_rates() 대체용"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT ym, base_rate, mortgage_rate, m2_trillion, m2_growth_3m,
                       leading_index, household_loan_trillion, rate_chg_3m, rate_chg_6m
                FROM ecos_macro ORDER BY ym
            """).fetchall()
        return {
            r[0]: {
                "기준금리":          r[1],
                "대출금리":          r[2],
                "M2잔액":            r[3],
                "M2증가율_3개월":    r[4],
                "경기선행지수":      r[5],
                "가계대출잔액":      r[6],
                "금리변화_3개월":    r[7],
                "금리변화_6개월":    r[8],
            }
            for r in rows
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os; os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = EcosCollector()
    print(c.collect(start_ym="202001"))
    rates = c.load_rates()
    latest = sorted(rates)[-1] if rates else None
    print(f"최신 월: {latest}", rates.get(latest) if latest else {})
