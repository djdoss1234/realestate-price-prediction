"""
기상청 API 수집기
==================
수집 항목:
  - 자연재해 위험 지역 (특보 발령 이력)  → weather_risk
  - 시군구별 기상 이변 빈도              → weather_anomaly

API 키 발급: https://www.data.go.kr (기상청_기상특보 조회서비스)
"""

import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

log = logging.getLogger(__name__)

# 기상청 특보 API (공공데이터포털)
WARN_LIST_URL = "https://apis.data.go.kr/1360000/WthrWrnInfoService/getWthrWrnList"
WARN_STAT_URL = "https://apis.data.go.kr/1360000/WthrWrnInfoService/getWthrWrnStat"

DDL_RISK = """
CREATE TABLE IF NOT EXISTS weather_risk (
    area_cd       TEXT NOT NULL,
    area_nm       TEXT,
    warn_type     TEXT,        -- 호우/태풍/강풍/건조/풍랑 등
    warn_level    TEXT,        -- 주의보/경보
    issue_dt      TEXT,
    cancel_dt     TEXT,
    collected_at  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (area_cd, warn_type, issue_dt)
)"""

DDL_ANOMALY = """
CREATE TABLE IF NOT EXISTS weather_anomaly (
    sgg_cd        TEXT NOT NULL,
    year          INTEGER NOT NULL,
    flood_cnt     INTEGER DEFAULT 0,
    typhoon_cnt   INTEGER DEFAULT 0,
    heavy_snow_cnt INTEGER DEFAULT 0,
    total_warn_cnt INTEGER DEFAULT 0,
    risk_score    REAL,    -- 가중합산 위험지수
    collected_at  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sgg_cd, year)
)"""

# 특보 유형별 위험 가중치
WARN_WEIGHTS = {
    "호우경보": 3.0, "호우주의보": 1.5,
    "태풍경보": 4.0, "태풍주의보": 2.0,
    "강풍경보": 2.0, "강풍주의보": 1.0,
    "폭설경보": 2.5, "폭설주의보": 1.2,
    "건조경보": 1.5, "건조주의보": 0.8,
    "풍랑경보": 2.0, "풍랑주의보": 1.0,
}


class WeatherCollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key = api_key or os.getenv("DATA_GO_KR_API_KEY", "")
        self.db_path = db_path
        self.session = requests.Session()
        self._init_tables()

    def _init_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL_RISK)
            conn.execute(DDL_ANOMALY)

    def _get(self, url: str, params: dict) -> list[dict]:
        if not self.api_key:
            log.warning("DATA_GO_KR_API_KEY 없음 — 기상 수집 스킵")
            return []
        p = {"serviceKey": self.api_key, "numOfRows": 100, "pageNo": 1,
             "dataType": "JSON", **params}
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
                if len(rows) >= min(total, 1000) or not batch:
                    break
                p["pageNo"] += 1
                time.sleep(0.2)
            except Exception as e:
                log.error("기상청 API 오류: %s", e)
                break
        return rows

    def collect_warnings(self, start_date: str = "20230101", end_date: Optional[str] = None) -> int:
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")

        rows = self._get(WARN_LIST_URL, {
            "fromTmFc": start_date + "0000",    # API 요구 형식: YYYYMMDDHHMM
            "toTmFc":   end_date + "2359",
        })

        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            for r in rows:
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO weather_risk
                        (area_cd, area_nm, warn_type, warn_level, issue_dt, cancel_dt)
                        VALUES (?,?,?,?,?,?)
                    """, (
                        r.get("areaCode"), r.get("areaNm"),
                        r.get("warnVar"),  r.get("warnStress"),
                        r.get("tmFc"),     r.get("tmEf"),
                    ))
                    inserted += 1
                except Exception:
                    pass
        log.info("weather_risk 저장: %d건", inserted)
        return inserted

    def build_risk_scores(self) -> int:
        """weather_risk → 시군구별 연도별 위험지수 집계"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT area_cd, area_nm, warn_type, warn_level,
                       SUBSTR(issue_dt, 1, 4) AS year
                FROM weather_risk
                WHERE area_cd IS NOT NULL
            """).fetchall()

        # 시군구 코드 → 집계
        from collections import defaultdict
        agg: dict = defaultdict(lambda: {"flood": 0, "typhoon": 0, "snow": 0, "total": 0, "score": 0.0})

        for area_cd, area_nm, warn_type, warn_level, year in rows:
            key = (area_cd[:5] if area_cd else area_cd, int(year) if year else 0)
            label = f"{warn_type or ''}{warn_level or ''}"
            w = WARN_WEIGHTS.get(label, 0.5)
            agg[key]["total"] += 1
            agg[key]["score"] += w
            if "호우" in (warn_type or ""):
                agg[key]["flood"] += 1
            elif "태풍" in (warn_type or ""):
                agg[key]["typhoon"] += 1
            elif "폭설" in (warn_type or ""):
                agg[key]["snow"] += 1

        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            for (sgg_cd, year), v in agg.items():
                if not sgg_cd or not year:
                    continue
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO weather_anomaly
                        (sgg_cd, year, flood_cnt, typhoon_cnt,
                         heavy_snow_cnt, total_warn_cnt, risk_score)
                        VALUES (?,?,?,?,?,?,?)
                    """, (sgg_cd, year, v["flood"], v["typhoon"],
                          v["snow"], v["total"], round(v["score"], 2)))
                    inserted += 1
                except Exception:
                    pass
        log.info("weather_anomaly 저장: %d건", inserted)
        return inserted

    def collect_all(self, start_date: str = None) -> dict:
        # API 제한: 오늘 기준 6일 이내만 조회 가능
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=6)).strftime("%Y%m%d")
        warnings = self.collect_warnings(start_date)
        scores   = self.build_risk_scores()
        return {"warnings": warnings, "risk_scores": scores}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os; os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = WeatherCollector()
    print(c.collect_all())
