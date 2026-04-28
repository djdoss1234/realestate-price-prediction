"""
한국부동산원 청약 정보 API 수집기
===================================
수집 항목:
  - 아파트 청약 공고 목록        → subscription_notice
  - 청약 결과 (경쟁률, 당첨가점)  → subscription_result

API 키 발급: https://www.reb.or.kr/reb/brd/m_40/view.do (부동산원 OpenAPI)
공공데이터포털: https://www.data.go.kr (아파트분양정보서비스)
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

# 공공데이터포털 아파트 분양정보 API
NOTICE_URL = "https://apis.data.go.kr/B552555/APTInfoService/getAPTNoticeInfo"
RESULT_URL = "https://apis.data.go.kr/B552555/APTInfoService/getAPTResultInfo"

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

    def _get(self, url: str, params: dict) -> list[dict]:
        if not self.api_key:
            log.warning("DATA_GO_KR_API_KEY 없음 — 청약 수집 스킵")
            return []
        p = {"serviceKey": self.api_key, "numOfRows": 100, "pageNo": 1,
             "resultType": "json", **params}
        rows = []
        while True:
            try:
                resp = self.session.get(url, params=p, timeout=30)
                resp.raise_for_status()
                body = resp.json().get("response", {}).get("body", {})
                items = body.get("items", {})
                batch = items.get("item", []) if isinstance(items, dict) else []
                if isinstance(batch, dict):
                    batch = [batch]
                rows.extend(batch)
                total = int(body.get("totalCount", 0))
                if len(rows) >= total or not batch:
                    break
                p["pageNo"] += 1
                time.sleep(0.3)
            except Exception as e:
                log.error("청약 API 오류: %s", e)
                break
        return rows

    def collect_notices(self, start_ym: str = "202301") -> int:
        rows = self._get(NOTICE_URL, {"startRcritPblancDe": start_ym + "01"})
        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            for r in rows:
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO subscription_notice
                        (house_manage_no, house_nm, sgg_cd, sgg_nm,
                         supply_count, recruit_from, recruit_to,
                         move_in_year, move_in_month, min_price_10k, max_price_10k)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        r.get("houseManageNo"), r.get("houseNm"),
                        r.get("sggCd"), r.get("sggNm"),
                        _to_int(r.get("totSuplyHshldco")),
                        r.get("rcritPblancDe"), r.get("subscrptRceptEndDe"),
                        _to_int(r.get("mvnPrearngeYm", "")[:4] if r.get("mvnPrearngeYm") else None),
                        _to_int(r.get("mvnPrearngeYm", "")[4:6] if r.get("mvnPrearngeYm") else None),
                        _to_int(r.get("lllotNm")),
                        _to_int(r.get("lllotNm")),
                    ))
                    inserted += 1
                except Exception as e:
                    log.debug("청약공고 저장 실패: %s", e)
        log.info("subscription_notice 저장: %d건", inserted)
        return inserted

    def collect_results(self, start_ym: str = "202301") -> int:
        rows = self._get(RESULT_URL, {"startRcritPblancDe": start_ym + "01"})
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
                        r.get("houseManageNo"),
                        r.get("hssplyTypeCd"),
                        _to_float(r.get("compttRt")),
                        _to_int(r.get("mnmumScre")),
                        _to_int(r.get("mxmumScre")),
                        _to_float(r.get("avrgScre")),
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
