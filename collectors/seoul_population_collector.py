"""
서울시 생활인구 수집기
========================
수집 항목:
  - 행정동별 생활인구 (연령대별) → seoul_living_pop

API: data.seoul.go.kr → 서울생활인구_내국인 (SPOP_LOCAL_RESD_DONG)
API key: SEOUL_DATA_API_KEY

ML 활용:
  - 동별 인구 밀도 피처
  - 30~40대 비중 (실수요자 연령대) 피처
  - 0~9세 비중 (육아 수요) 피처
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

BASE_URL = "http://openapi.seoul.go.kr:8088/{key}/json/SPOP_LOCAL_RESD_DONG/{start}/{end}/"

DDL = """
CREATE TABLE IF NOT EXISTS seoul_living_pop (
    dong_cd        TEXT    NOT NULL,
    std_date       TEXT    NOT NULL,
    tot_pop        REAL,
    pop_0_9        REAL,
    pop_10_19      REAL,
    pop_20_29      REAL,
    pop_30_39      REAL,
    pop_40_49      REAL,
    pop_50_59      REAL,
    pop_60_plus    REAL,
    ratio_30_49    REAL,
    ratio_young    REAL,
    collected_at   TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (dong_cd, std_date)
)"""

IDX = "CREATE INDEX IF NOT EXISTS idx_seoulpop_dong ON seoul_living_pop(dong_cd)"


class SeoulPopulationCollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key = api_key or os.getenv("SEOUL_DATA_API_KEY", "")
        self.db_path = db_path
        self.session = requests.Session()
        self._init_table()

    def _init_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL)
            conn.execute(IDX)

    def _fetch_page(self, start: int, end: int) -> tuple[list, int]:
        if not self.api_key:
            log.warning("SEOUL_DATA_API_KEY 없음 — 서울 생활인구 수집 스킵")
            return [], 0
        try:
            url = BASE_URL.format(key=self.api_key, start=start, end=end)
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            body = resp.json().get("SPOP_LOCAL_RESD_DONG", {})
            result = body.get("RESULT", {})
            if result.get("CODE", "") != "INFO-000":
                log.warning("서울 생활인구 API 오류: %s", result.get("MESSAGE", ""))
                return [], 0
            total = body.get("list_total_count", 0)
            rows = body.get("row", [])
            return rows, total
        except Exception as e:
            log.error("서울 생활인구 수집 오류 [%d~%d]: %s", start, end, e)
            return [], 0

    def _parse_row(self, r: dict) -> Optional[tuple]:
        dong_cd = str(r.get("ADSTRD_CODE_SE", "")).strip()
        std_date = str(r.get("STDR_DE_ID", "")).strip()
        if not dong_cd or not std_date:
            return None

        def f(k): return _to_float(r.get(k, 0)) or 0.0

        # 성별 합산
        p0  = f("MALE_F0T9_LVPOP_CO")  + f("FEMALE_F0T9_LVPOP_CO")
        p10 = f("MALE_F10T14_LVPOP_CO") + f("MALE_F15T19_LVPOP_CO") + \
              f("FEMALE_F10T14_LVPOP_CO") + f("FEMALE_F15T19_LVPOP_CO")
        p20 = f("MALE_F20T24_LVPOP_CO") + f("MALE_F25T29_LVPOP_CO") + \
              f("FEMALE_F20T24_LVPOP_CO") + f("FEMALE_F25T29_LVPOP_CO")
        p30 = f("MALE_F30T34_LVPOP_CO") + f("MALE_F35T39_LVPOP_CO") + \
              f("FEMALE_F30T34_LVPOP_CO") + f("FEMALE_F35T39_LVPOP_CO")
        p40 = f("MALE_F40T44_LVPOP_CO") + f("MALE_F45T49_LVPOP_CO") + \
              f("FEMALE_F40T44_LVPOP_CO") + f("FEMALE_F45T49_LVPOP_CO")
        p50 = f("MALE_F50T54_LVPOP_CO") + f("MALE_F55T59_LVPOP_CO") + \
              f("FEMALE_F50T54_LVPOP_CO") + f("FEMALE_F55T59_LVPOP_CO")
        p60 = f("MALE_F60T64_LVPOP_CO") + f("MALE_F65T69_LVPOP_CO") + \
              f("MALE_F70T74_LVPOP_CO") + \
              f("FEMALE_F60T64_LVPOP_CO") + f("FEMALE_F65T69_LVPOP_CO") + \
              f("FEMALE_F70T74_LVPOP_CO")

        tot = _to_float(r.get("TOT_LVPOP_CO")) or 0.0
        ratio_30_49 = (p30 + p40) / tot if tot > 0 else None
        ratio_young = p0 / tot if tot > 0 else None

        return (dong_cd, std_date, tot, p0, p10, p20, p30, p40, p50, p60,
                ratio_30_49, ratio_young)

    def collect_latest(self) -> int:
        """최신 1회분 전체 수집 (약 854,000건 → 서울 424개 동)"""
        page_size = 1000
        first, total = self._fetch_page(1, 1)
        if total == 0:
            return 0

        log.info("서울 생활인구 총 %d건 수집 시작", total)
        inserted = 0
        pages = (total + page_size - 1) // page_size

        for p in range(pages):
            start = p * page_size + 1
            end = min(start + page_size - 1, total)
            rows, _ = self._fetch_page(start, end)
            if not rows:
                time.sleep(0.5)
                continue
            with sqlite3.connect(self.db_path) as conn:
                for r in rows:
                    parsed = self._parse_row(r)
                    if not parsed:
                        continue
                    try:
                        conn.execute("""
                            INSERT OR REPLACE INTO seoul_living_pop
                            (dong_cd, std_date, tot_pop, pop_0_9, pop_10_19,
                             pop_20_29, pop_30_39, pop_40_49, pop_50_59,
                             pop_60_plus, ratio_30_49, ratio_young)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """, parsed)
                        inserted += 1
                    except Exception:
                        pass
            time.sleep(0.2)
            if p % 10 == 0:
                log.info("서울 생활인구 진행: %d/%d페이지", p + 1, pages)

        log.info("서울 생활인구 수집 완료: %d건", inserted)
        return inserted

    def get_dong_summary(self) -> list[dict]:
        """동별 최신 인구 요약 조회"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT dong_cd, std_date, tot_pop, ratio_30_49, ratio_young
                FROM seoul_living_pop
                WHERE std_date = (SELECT MAX(std_date) FROM seoul_living_pop)
                ORDER BY tot_pop DESC
            """).fetchall()
        return [{"dong_cd": r[0], "std_date": r[1], "tot_pop": r[2],
                 "ratio_30_49": r[3], "ratio_young": r[4]} for r in rows]


def _to_float(v) -> Optional[float]:
    try:    return float(str(v).replace(",", ""))
    except: return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = SeoulPopulationCollector()
    n = c.collect_latest()
    print(f"서울 생활인구 {n}건 수집")
    summary = c.get_dong_summary()
    print("인구 상위 5개 동:")
    for d in summary[:5]:
        print(f"  {d['dong_cd']}: {d['tot_pop']:.0f}명, 30~49세 비중 {(d['ratio_30_49'] or 0)*100:.1f}%")
