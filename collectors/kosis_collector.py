"""
통계청 KOSIS API 수집기
========================
수집 항목:
  - 주민등록 인구 (시군구별)       → kosis_population
  - 주민등록 세대수 (시군구별)      → kosis_household
  - 지역별 고용률                  → kosis_employment
  - 1인당 지역내총생산(GRDP)       → kosis_income

API 키 발급: https://kosis.kr/openapi/
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://kosis.kr/openapi/Param/statisticsParamData.do"

# KOSIS 통계표 코드 (고정)
STAT_CODES = {
    "population":  {"orgId": "101", "tblId": "DT_1B040A3", "itmId": "T20", "objL1": "ALL", "objL2": "ALL"},
    "household":   {"orgId": "101", "tblId": "DT_1JC1516", "itmId": "T1",  "objL1": "ALL"},
    "employment":  {"orgId": "101", "tblId": "DT_1DE7126T", "itmId": "T10", "objL1": "ALL"},
    "income":      {"orgId": "402", "tblId": "DT_402001N01", "itmId": "T10", "objL1": "ALL"},
}

DDL = {
    "kosis_population": """
        CREATE TABLE IF NOT EXISTS kosis_population (
            sgg_cd      TEXT NOT NULL,
            sgg_nm      TEXT,
            year        INTEGER NOT NULL,
            population  INTEGER,
            collected_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (sgg_cd, year)
        )""",
    "kosis_household": """
        CREATE TABLE IF NOT EXISTS kosis_household (
            sgg_cd      TEXT NOT NULL,
            sgg_nm      TEXT,
            year        INTEGER NOT NULL,
            households  INTEGER,
            collected_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (sgg_cd, year)
        )""",
    "kosis_employment": """
        CREATE TABLE IF NOT EXISTS kosis_employment (
            sgg_cd         TEXT NOT NULL,
            sgg_nm         TEXT,
            year           INTEGER NOT NULL,
            employment_rate REAL,
            collected_at   TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (sgg_cd, year)
        )""",
    "kosis_income": """
        CREATE TABLE IF NOT EXISTS kosis_income (
            sgg_cd      TEXT NOT NULL,
            sgg_nm      TEXT,
            year        INTEGER NOT NULL,
            grdp_per_cap REAL,
            collected_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (sgg_cd, year)
        )""",
}


class KosisCollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key  = api_key or os.getenv("KOSIS_API_KEY", "")
        self.db_path  = db_path
        self.session  = requests.Session()
        self.session.headers.update({"User-Agent": "RealEstate-Collector/1.0"})
        self._init_tables()

    def _init_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            for ddl in DDL.values():
                conn.execute(ddl)

    def _fetch(self, stat_key: str, start_year: int = 2020, end_year: int = 2024) -> list[dict]:
        if not self.api_key:
            log.warning("KOSIS_API_KEY 없음 — 수집 스킵")
            return []
        code = STAT_CODES[stat_key]
        params = {
            "method":    "getList",
            "apiKey":    self.api_key,
            "format":    "json",
            "jsonVD":    "Y",
            "startPrdDe": str(start_year),
            "endPrdDe":   str(end_year),
            **code,
        }
        try:
            resp = self.session.get(BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            log.warning("KOSIS 응답 이상: %s", str(data)[:200])
        except Exception as e:
            log.error("KOSIS %s 수집 실패: %s", stat_key, e)
        return []

    def collect_population(self, start_year: int = 2020):
        rows = self._fetch("population", start_year)
        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            for r in rows:
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO kosis_population (sgg_cd, sgg_nm, year, population) VALUES (?,?,?,?)",
                        (r.get("C1"), r.get("C1_NM"), int(r.get("PRD_DE", 0)), _to_int(r.get("DT")))
                    )
                    inserted += 1
                except Exception:
                    pass
        log.info("kosis_population 저장: %d건", inserted)
        return inserted

    def collect_household(self, start_year: int = 2020):
        rows = self._fetch("household", start_year)
        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            for r in rows:
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO kosis_household (sgg_cd, sgg_nm, year, households) VALUES (?,?,?,?)",
                        (r.get("C1"), r.get("C1_NM"), int(r.get("PRD_DE", 0)), _to_int(r.get("DT")))
                    )
                    inserted += 1
                except Exception:
                    pass
        log.info("kosis_household 저장: %d건", inserted)
        return inserted

    def collect_employment(self, start_year: int = 2020):
        rows = self._fetch("employment", start_year)
        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            for r in rows:
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO kosis_employment (sgg_cd, sgg_nm, year, employment_rate) VALUES (?,?,?,?)",
                        (r.get("C1"), r.get("C1_NM"), int(r.get("PRD_DE", 0)), _to_float(r.get("DT")))
                    )
                    inserted += 1
                except Exception:
                    pass
        log.info("kosis_employment 저장: %d건", inserted)
        return inserted

    def collect_income(self, start_year: int = 2020):
        rows = self._fetch("income", start_year)
        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            for r in rows:
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO kosis_income (sgg_cd, sgg_nm, year, grdp_per_cap) VALUES (?,?,?,?)",
                        (r.get("C1"), r.get("C1_NM"), int(r.get("PRD_DE", 0)), _to_float(r.get("DT")))
                    )
                    inserted += 1
                except Exception:
                    pass
        log.info("kosis_income 저장: %d건", inserted)
        return inserted

    def collect_all(self, start_year: int = 2020) -> dict:
        log.info("KOSIS 전체 수집 시작 (from %d)", start_year)
        return {
            "population":  self.collect_population(start_year),
            "household":   self.collect_household(start_year),
            "employment":  self.collect_employment(start_year),
            "income":      self.collect_income(start_year),
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
    c = KosisCollector()
    print(c.collect_all())
