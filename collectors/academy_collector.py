"""
NEIS 학원·교습소 정보 수집기
===============================
수집 항목:
  - 시도교육청별 전체 학원·교습소 목록 → academy_info
  - 시군구별 학원 수 집계              → academy_stats

API: open.neis.go.kr → 학원교습소정보 (acaInsTiInfo)
API key: NEIS_API_KEY

ML 활용:
  - 시군구·동별 학원 수 (입시/보습/예체능 구분)
  - 학군 피처 강화 (학교 수 + 학원 수 + 학원 종류)
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://open.neis.go.kr/hub/acaInsTiInfo"

ATPT_CODES = {
    "B10": "서울", "C10": "부산", "D10": "대구", "E10": "인천",
    "F10": "광주", "G10": "대전", "H10": "울산", "I10": "세종",
    "J10": "경기", "K10": "강원", "M10": "충북", "N10": "충남",
    "P10": "전북", "Q10": "전남", "R10": "경북", "S10": "경남", "T10": "제주",
}

REALM_CATEGORIES = {
    "입시": "입시.검정 및 보습",
    "예체능": "예능",
    "외국어": "국제화",
    "직업": "직업기술",
    "기타": "기타",
}

DDL_INFO = """
CREATE TABLE IF NOT EXISTS academy_info (
    aca_asnum      TEXT    PRIMARY KEY,
    atpt_code      TEXT,
    sido_nm        TEXT,
    sgg_nm         TEXT,
    aca_nm         TEXT,
    aca_type       TEXT,
    status         TEXT,
    realm_nm       TEXT,
    le_ord_nm      TEXT,
    addr           TEXT,
    estbl_ymd      TEXT,
    total_capacity INTEGER,
    collected_at   TEXT DEFAULT (datetime('now'))
)"""

DDL_STATS = """
CREATE TABLE IF NOT EXISTS academy_stats (
    sgg_nm         TEXT    NOT NULL,
    sido_nm        TEXT,
    total_cnt      INTEGER,
    entrance_cnt   INTEGER,
    arts_cnt       INTEGER,
    lang_cnt       INTEGER,
    math_cnt       INTEGER,
    science_cnt    INTEGER,
    updated_at     TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sgg_nm)
)"""


class AcademyCollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key = api_key or os.getenv("NEIS_API_KEY", "")
        self.db_path = db_path
        self.session = requests.Session()
        self._init_tables()

    def _init_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL_INFO)
            conn.execute(DDL_STATS)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_aca_sgg ON academy_info(sgg_nm)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_aca_realm ON academy_info(realm_nm)")

    def _fetch_page(self, atpt_code: str, page: int = 1,
                    rows: int = 1000) -> tuple[list, int]:
        if not self.api_key:
            log.warning("NEIS_API_KEY 없음 — 학원 수집 스킵")
            return [], 0
        try:
            params = {
                "KEY":               self.api_key,
                "Type":              "json",
                "pIndex":            page,
                "pSize":             rows,
                "ATPT_OFCDC_SC_CODE": atpt_code,
                "REG_STTUS_NM":      "개원",  # 현재 운영 중인 학원만
            }
            resp = self.session.get(BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json().get("acaInsTiInfo", [])
            if not data or len(data) < 2:
                return [], 0
            total = data[0]["head"][0]["list_total_count"]
            rows_data = data[1].get("row", [])
            return rows_data, total
        except Exception as e:
            log.error("학원 수집 오류 [%s p%d]: %s", atpt_code, page, e)
            return [], 0

    def _upsert(self, conn, rows: list) -> int:
        count = 0
        for r in rows:
            asnum = str(r.get("ACA_ASNUM", "")).strip()
            if not asnum:
                continue
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO academy_info
                    (aca_asnum, atpt_code, sido_nm, sgg_nm, aca_nm, aca_type,
                     status, realm_nm, le_ord_nm, addr, estbl_ymd, total_capacity)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    asnum,
                    r.get("ATPT_OFCDC_SC_CODE", ""),
                    r.get("ATPT_OFCDC_SC_NM", ""),
                    r.get("ADMST_ZONE_NM", ""),
                    r.get("ACA_NM", ""),
                    r.get("ACA_INSTI_SC_NM", ""),
                    r.get("REG_STTUS_NM", ""),
                    r.get("REALM_SC_NM", ""),
                    r.get("LE_ORD_NM", ""),
                    (r.get("FA_RDNMA", "") or "") + " " + (r.get("FA_RDNDA", "") or ""),
                    r.get("ESTBL_YMD", "") or None,
                    _to_int(r.get("TOFOR_SMTOT")),
                ))
                count += 1
            except Exception:
                pass
        return count

    def collect_sido(self, atpt_code: str) -> int:
        """시도교육청 단위 전체 수집"""
        _, total = self._fetch_page(atpt_code, rows=1)
        if total == 0:
            return 0

        rows_per_page = 1000
        pages = (total + rows_per_page - 1) // rows_per_page
        inserted = 0
        sido_nm = ATPT_CODES.get(atpt_code, atpt_code)
        log.info("학원 수집 [%s] %d건 / %d페이지", sido_nm, total, pages)

        for page in range(1, pages + 1):
            rows, _ = self._fetch_page(atpt_code, page=page, rows=rows_per_page)
            if not rows:
                time.sleep(0.3)
                continue
            with sqlite3.connect(self.db_path) as conn:
                inserted += self._upsert(conn, rows)
            time.sleep(0.2)

        log.info("학원 [%s]: %d건 저장", sido_nm, inserted)
        return inserted

    def collect_all(self) -> dict:
        """전국 수집"""
        total = 0
        for code in ATPT_CODES:
            n = self.collect_sido(code)
            total += n
        self.update_stats()
        return {"total": total}

    def update_stats(self):
        """시군구별 학원 수 집계 갱신"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM academy_stats")
            conn.execute("""
                INSERT INTO academy_stats
                    (sgg_nm, sido_nm, total_cnt,
                     entrance_cnt, arts_cnt, lang_cnt, math_cnt, science_cnt)
                SELECT
                    sgg_nm,
                    MAX(sido_nm),
                    COUNT(*),
                    SUM(CASE WHEN realm_nm LIKE '%입시%' OR realm_nm LIKE '%보습%' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN realm_nm LIKE '%예능%' OR realm_nm LIKE '%체육%' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN le_ord_nm LIKE '%외국어%' OR aca_nm LIKE '%영어%' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN aca_nm LIKE '%수학%' OR aca_nm LIKE '%math%' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN aca_nm LIKE '%과학%' OR aca_nm LIKE '%science%' THEN 1 ELSE 0 END)
                FROM academy_info
                WHERE sgg_nm IS NOT NULL AND sgg_nm != ''
                GROUP BY sgg_nm
            """)
        log.info("academy_stats 집계 갱신 완료")

    def get_stats(self) -> list[dict]:
        """시군구별 학원 수 조회"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT sgg_nm, sido_nm, total_cnt, entrance_cnt, arts_cnt,
                       lang_cnt, math_cnt, science_cnt
                FROM academy_stats ORDER BY total_cnt DESC
            """).fetchall()
        cols = ["sgg_nm","sido_nm","total_cnt","entrance_cnt","arts_cnt",
                "lang_cnt","math_cnt","science_cnt"]
        return [dict(zip(cols, r)) for r in rows]


def _to_int(v) -> Optional[int]:
    try:    return int(str(v).replace(",", ""))
    except: return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = AcademyCollector()
    # 서울만 테스트
    n = c.collect_sido("B10")
    print(f"서울 학원 {n}건 수집")
    stats = c.get_stats()
    print("서울 상위 5개 시군구:")
    for s in stats[:5]:
        print(f"  {s['sgg_nm']}: 총 {s['total_cnt']}개 (입시 {s['entrance_cnt']}개)")
