"""
국토부 공시지가 API 수집기
============================
수집 항목:
  - 표준지 공시지가 (필지별)      → land_price_standard
  - 개별 공시지가 (필지별)        → land_price_individual
  - 시군구별 평균 공시지가        → land_price_sgg_avg

API 키 발급: https://www.data.go.kr (국토교통부_표준지공시지가정보서비스)
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

STANDARD_URL   = "https://apis.data.go.kr/1613000/LandPriceService/getLandPriceInfo"
INDIVIDUAL_URL = "https://apis.data.go.kr/1613000/IndvdLandPriceService/getIndvdLandPriceInfo"

DDL_STANDARD = """
CREATE TABLE IF NOT EXISTS land_price_standard (
    pnu         TEXT PRIMARY KEY,
    sgg_cd      TEXT,
    umd_cd      TEXT,
    jibun       TEXT,
    land_area   REAL,
    land_price  INTEGER,
    land_use    TEXT,
    base_year   INTEGER,
    collected_at TEXT DEFAULT (datetime('now'))
)"""

DDL_INDIVIDUAL = """
CREATE TABLE IF NOT EXISTS land_price_individual (
    pnu         TEXT NOT NULL,
    sgg_cd      TEXT,
    jibun       TEXT,
    land_price  INTEGER,
    base_year   INTEGER,
    collected_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (pnu, base_year)
)"""

DDL_SGG_AVG = """
CREATE TABLE IF NOT EXISTS land_price_sgg_avg (
    sgg_cd        TEXT NOT NULL,
    base_year     INTEGER NOT NULL,
    avg_price_m2  REAL,
    median_price_m2 REAL,
    sample_count  INTEGER,
    collected_at  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sgg_cd, base_year)
)"""


class LandPriceCollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key = api_key or os.getenv("MOLIT_API_KEY", "")
        self.db_path = db_path
        self.session = requests.Session()
        self._init_tables()

    def _init_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL_STANDARD)
            conn.execute(DDL_INDIVIDUAL)
            conn.execute(DDL_SGG_AVG)

    def _get(self, url: str, params: dict) -> list[dict]:
        if not self.api_key:
            log.warning("MOLIT_API_KEY 없음 — 공시지가 수집 스킵")
            return []
        p = {"serviceKey": self.api_key, "numOfRows": 100, "pageNo": 1,
             "resultType": "json", **params}
        rows, page = [], 1
        while True:
            p["pageNo"] = page
            try:
                resp = self.session.get(url, params=p, timeout=30)
                resp.raise_for_status()
                body = resp.json().get("response", {}).get("body", {})
                items = body.get("items", {})
                batch = items.get("item", []) if isinstance(items, dict) else []
                if isinstance(batch, dict):
                    batch = [batch]
                if not batch:
                    break
                rows.extend(batch)
                total = int(body.get("totalCount", 0))
                if len(rows) >= min(total, 5000):
                    break
                page += 1
                time.sleep(0.3)
            except Exception as e:
                log.error("공시지가 API 오류: %s", e)
                break
        return rows

    def collect_standard(self, sgg_cd: str, base_year: int = 2024) -> int:
        rows = self._get(STANDARD_URL, {
            "ldCode":   sgg_cd,
            "stdrYear": str(base_year),
        })
        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            for r in rows:
                pnu = r.get("pnu") or f"{sgg_cd}_{r.get('lnbrMnnm','')}_{r.get('lnbrSlno','')}"
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO land_price_standard
                        (pnu, sgg_cd, umd_cd, jibun, land_area, land_price, land_use, base_year)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (
                        pnu, sgg_cd, r.get("ldCode"),
                        f"{r.get('lnbrMnnm','')}-{r.get('lnbrSlno','')}",
                        _to_float(r.get("lndpclAr")),
                        _to_int(r.get("pblntfPclnd")),
                        r.get("lndcgrCodeNm"),
                        base_year,
                    ))
                    inserted += 1
                except Exception:
                    pass
        log.info("land_price_standard [%s/%d]: %d건", sgg_cd, base_year, inserted)
        return inserted

    def collect_all_sgg(self, base_year: int = 2024):
        """DB의 모든 시군구 공시지가 수집 후 평균 집계"""
        with sqlite3.connect(self.db_path) as conn:
            sggs = [r[0] for r in conn.execute(
                "SELECT DISTINCT sggCd FROM apt_trade WHERE sggCd IS NOT NULL ORDER BY sggCd"
            ).fetchall()]

        total = 0
        for sgg_cd in sggs:
            cnt = self.collect_standard(str(sgg_cd), base_year)
            total += cnt
            time.sleep(0.5)

        self._build_sgg_avg(base_year)
        log.info("공시지가 전체 수집 완료: %d건", total)
        return total

    def _build_sgg_avg(self, base_year: int):
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT sgg_cd,
                       AVG(CAST(land_price AS REAL) / NULLIF(land_area, 0)),
                       COUNT(*)
                FROM land_price_standard
                WHERE base_year = ? AND land_area > 0 AND land_price > 0
                GROUP BY sgg_cd
            """, (base_year,)).fetchall()

            for sgg_cd, avg_price, cnt in rows:
                conn.execute("""
                    INSERT OR REPLACE INTO land_price_sgg_avg
                    (sgg_cd, base_year, avg_price_m2, sample_count)
                    VALUES (?,?,?,?)
                """, (sgg_cd, base_year, round(avg_price, 0) if avg_price else None, cnt))
        log.info("land_price_sgg_avg 집계 완료: %d개 시군구", len(rows))


def _to_int(v) -> Optional[int]:
    try:    return int(str(v).replace(",", ""))
    except: return None

def _to_float(v) -> Optional[float]:
    try:    return float(str(v).replace(",", ""))
    except: return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os; os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = LandPriceCollector()
    print(c.collect_standard("11680", 2024))  # 강남구 테스트
