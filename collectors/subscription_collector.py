"""
청약홈 아파트 청약 공고 수집기
=================================
수집 항목:
  - 아파트 청약 공고 목록 → subscription_notice
  - 주택 유형별 경쟁률    → subscription_result

API: api.odcloud.kr ApplyhomeInfoDetailSvc
  - 공고: https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail
  - 경쟁: https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetailRanking
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

NOTICE_URL = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail"
RESULT_URL = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetailRanking"

DDL_NOTICE = """
CREATE TABLE IF NOT EXISTS subscription_notice (
    house_manage_no   TEXT PRIMARY KEY,
    house_nm          TEXT,
    sgg_cd            TEXT,
    sgg_nm            TEXT,
    supply_count      INTEGER,
    recruit_from      TEXT,
    recruit_to        TEXT,
    move_in_year      INTEGER,
    move_in_month     INTEGER,
    min_price_10k     INTEGER,
    max_price_10k     INTEGER,
    collected_at      TEXT DEFAULT (datetime('now'))
)"""

DDL_RESULT = """
CREATE TABLE IF NOT EXISTS subscription_result (
    house_manage_no   TEXT NOT NULL,
    supply_type       TEXT,
    competition_rate  REAL,
    winner_score_min  INTEGER,
    winner_score_max  INTEGER,
    winner_score_avg  REAL,
    collected_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (house_manage_no, supply_type)
)"""


class SubscriptionCollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key = api_key or os.getenv("DATA_GO_KR_API_KEY", "")
        self.db_path = db_path
        self.session = requests.Session()
        self._init_tables()

    def _init_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL_NOTICE)
            conn.execute(DDL_RESULT)

    def _get(self, url: str, extra_params: dict = None) -> list[dict]:
        if not self.api_key:
            log.warning("DATA_GO_KR_API_KEY 없음 — 청약 수집 스킵")
            return []
        p = {
            "page":       1,
            "perPage":    1000,
            "serviceKey": self.api_key,
            **(extra_params or {}),
        }
        rows = []
        while True:
            try:
                resp = self.session.get(url, params=p, timeout=30)
                resp.raise_for_status()
                js = resp.json()
                batch = js.get("data", [])
                if not isinstance(batch, list):
                    log.warning("청약 API 응답 형식 오류: %s", str(js)[:200])
                    break
                rows.extend(batch)
                total = int(js.get("totalCount", 0))
                if len(rows) >= total or not batch:
                    break
                p["page"] += 1
                time.sleep(0.3)
            except Exception as e:
                log.error("청약 API 오류: %s", e)
                break
        log.info("청약 API %s 응답 %d건", url.split("/")[-1], len(rows))
        return rows

    def collect_notices(self, start_ym: str = "202301") -> int:
        start_date = start_ym + "01"
        rows = self._get(NOTICE_URL, {
            "cond[RCRIT_PBLANC_DE::GTE]": start_date,
        })
        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            for r in rows:
                try:
                    mvy = str(r.get("MOVE_IN_PREARNGE_YM") or "")
                    conn.execute("""
                        INSERT OR REPLACE INTO subscription_notice
                        (house_manage_no, house_nm, sgg_cd, sgg_nm,
                         supply_count, recruit_from,
                         move_in_year, move_in_month)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (
                        r.get("HOUSE_MANAGE_NO"),
                        r.get("HOUSE_NM"),
                        r.get("SUBSCRPT_AREA_CODE"),
                        r.get("SUBSCRPT_AREA_CODE_NM"),
                        _to_int(r.get("TOT_SUPLY_HSHLDCO")),
                        r.get("RCRIT_PBLANC_DE"),
                        _to_int(mvy[:4]) if len(mvy) >= 4 else None,
                        _to_int(mvy[4:6]) if len(mvy) >= 6 else None,
                    ))
                    inserted += 1
                except Exception as e:
                    log.debug("청약공고 저장 실패: %s", e)
        log.info("subscription_notice 저장: %d건", inserted)
        return inserted

    def collect_results(self, start_ym: str = "202301") -> int:
        start_date = start_ym + "01"
        rows = self._get(RESULT_URL, {
            "cond[RCRIT_PBLANC_DE::GTE]": start_date,
        })
        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            for r in rows:
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO subscription_result
                        (house_manage_no, supply_type,
                         competition_rate, winner_score_min,
                         winner_score_max, winner_score_avg)
                        VALUES (?,?,?,?,?,?)
                    """, (
                        r.get("HOUSE_MANAGE_NO"),
                        r.get("HOUSE_TYPE_CD") or r.get("HSSPLY_AREA"),
                        _to_float(r.get("COMPTT_RT")),
                        _to_int(r.get("MNMUM_SCRE")),
                        _to_int(r.get("MXMUM_SCRE")),
                        _to_float(r.get("AVRG_SCRE")),
                    ))
                    inserted += 1
                except Exception as e:
                    log.debug("청약결과 저장 실패: %s", e)
        log.info("subscription_result 저장: %d건", inserted)
        return inserted

    def collect_all(self, start_ym: str = "202301") -> dict:
        return {
            "notices": self.collect_notices(start_ym),
            "results": self.collect_results(start_ym),
        }


def _to_int(v) -> Optional[int]:
    try:    return int(str(v).replace(",", ""))
    except: return None

def _to_float(v) -> Optional[float]:
    try:    return float(str(v).replace(",", ""))
    except: return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os; os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = SubscriptionCollector()
    print(c.collect_all())
