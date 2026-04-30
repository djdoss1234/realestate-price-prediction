"""
경찰청 범죄통계 수집기
======================
수집 항목:
  - 시도별 범죄 발생/검거 현황 → crime_stats

API 키: DATA_GO_KR_API_KEY (B552055)
엔드포인트: https://apis.data.go.kr/B552055/CrmnlStatService/getCrmnlStatInfo
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://apis.data.go.kr/B552055/CrmnlStatService/getCrmnlStatInfo"

DDL = """
CREATE TABLE IF NOT EXISTS crime_stats (
    sgg_cd        TEXT NOT NULL,
    sgg_nm        TEXT,
    year          INTEGER NOT NULL,
    crime_type    TEXT NOT NULL,    -- 범죄유형(살인/강도/절도 등)
    occur_cnt     INTEGER,          -- 발생건수
    arrest_cnt    INTEGER,          -- 검거건수
    collected_at  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sgg_cd, year, crime_type)
)"""


class CrimeCollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key = api_key or os.getenv("DATA_GO_KR_API_KEY", "")
        self.db_path = db_path
        self.session = requests.Session()
        self._init_table()

    def _init_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL)

    def _get_pages(self, extra_params: dict = None) -> list[dict]:
        if not self.api_key:
            log.warning("DATA_GO_KR_API_KEY 없음 — 범죄통계 수집 스킵")
            return []
        p = {
            "serviceKey": self.api_key,
            "numOfRows":  100,
            "pageNo":     1,
            "resultType": "json",
            **(extra_params or {}),
        }
        rows = []
        while True:
            try:
                resp = self.session.get(BASE_URL, params=p, timeout=30)
                if resp.status_code != 200:
                    log.warning("범죄통계 API HTTP %d: %s", resp.status_code, resp.text[:200])
                    break
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
                log.error("범죄통계 API 오류: %s", e)
                break
        return rows

    def collect_stats(self, start_year: int = 2020) -> int:
        from datetime import date
        end_year = date.today().year - 1  # 전년도까지만 확정치 제공
        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            for year in range(start_year, end_year + 1):
                rows = self._get_pages({"crimeYear": str(year)})
                for r in rows:
                    try:
                        conn.execute("""
                            INSERT OR REPLACE INTO crime_stats
                            (sgg_cd, sgg_nm, year, crime_type, occur_cnt, arrest_cnt)
                            VALUES (?,?,?,?,?,?)
                        """, (
                            r.get("sidoCd") or r.get("sggCd") or r.get("areaCd"),
                            r.get("sidoNm") or r.get("sggNm") or r.get("areaNm"),
                            year,
                            r.get("crimeType") or r.get("crimeNm") or r.get("crime"),
                            _to_int(r.get("occurCnt") or r.get("occurNum")),
                            _to_int(r.get("arrestCnt") or r.get("arrestNum")),
                        ))
                        inserted += 1
                    except Exception as e:
                        log.debug("범죄통계 저장 실패: %s", e)
                time.sleep(0.5)
        log.info("crime_stats 저장: %d건", inserted)
        return inserted

    def collect_all(self, start_year: int = 2020) -> dict:
        return {"stats": self.collect_stats(start_year)}


def _to_int(v) -> Optional[int]:
    try:    return int(str(v).replace(",", ""))
    except: return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os; os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = CrimeCollector()
    print(c.collect_all())
