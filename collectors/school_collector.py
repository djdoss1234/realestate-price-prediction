"""
학교알리미 API 수집기
=======================
수집 항목:
  - 학교 기본 정보 (위치, 유형)     → school_info
  - 학업성취도 (시험 결과)           → school_achievement
  - 학군 등급 (시군구별 점수화)       → school_district_score

API: 교육통계서비스 (https://www.data.go.kr)
     학교알리미 (https://www.schoolinfo.go.kr) - 일부 항목
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

# NEIS 학교정보 (open.neis.go.kr)
SCHOOL_URL       = "https://open.neis.go.kr/hub/schoolInfo"
ACHIEVEMENT_URL  = "https://open.neis.go.kr/hub/SchoolAchievementInfo"

DDL_SCHOOL = """
CREATE TABLE IF NOT EXISTS school_info (
    school_code  TEXT PRIMARY KEY,
    school_nm    TEXT,
    school_type  TEXT,    -- 초/중/고
    sgg_cd       TEXT,
    sido_nm      TEXT,
    sgg_nm       TEXT,
    addr         TEXT,
    lat          REAL,
    lng          REAL,
    student_cnt  INTEGER,
    class_cnt    INTEGER,
    collected_at TEXT DEFAULT (datetime('now'))
)"""

DDL_ACHIEVE = """
CREATE TABLE IF NOT EXISTS school_achievement (
    school_code  TEXT NOT NULL,
    exam_year    INTEGER NOT NULL,
    subject      TEXT,
    below_basic  REAL,    -- 기초미달 비율(%)
    basic        REAL,    -- 기초 비율(%)
    proficient   REAL,    -- 보통 비율(%)
    advanced     REAL,    -- 우수 비율(%)
    collected_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (school_code, exam_year, subject)
)"""

DDL_DISTRICT = """
CREATE TABLE IF NOT EXISTS school_district_score (
    sgg_cd       TEXT NOT NULL,
    year         INTEGER NOT NULL,
    avg_score    REAL,    -- 시군구 평균 학업 점수 (0~100)
    school_cnt   INTEGER,
    high_school_cnt INTEGER,
    special_hs_cnt  INTEGER,  -- 특목고/자사고 수
    grade        TEXT,    -- S/A/B/C/D
    collected_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sgg_cd, year)
)"""

SCORE_GRADE = [(90, "S"), (80, "A"), (70, "B"), (60, "C"), (0, "D")]


class SchoolCollector:
    def __init__(self, api_key: str = "", neis_key: str = "", db_path: str = "realestate.db"):
        self.api_key  = api_key  or os.getenv("DATA_GO_KR_API_KEY", "")
        self.neis_key = neis_key or os.getenv("NEIS_API_KEY", "")
        self.db_path  = db_path
        self.session  = requests.Session()
        self._init_tables()

    def _init_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL_SCHOOL)
            conn.execute(DDL_ACHIEVE)
            conn.execute(DDL_DISTRICT)

    def collect_schools(self, sido_cd: str = "") -> int:
        if not self.neis_key:
            log.warning("NEIS_API_KEY 없음 — 학교목록 수집 스킵")
            return 0

        school_types = ["초등학교", "중학교", "고등학교"]
        inserted = 0

        for stype in school_types:
            page = 1
            while True:
                params = {
                    "KEY":              self.neis_key,
                    "Type":             "json",
                    "pIndex":           page,
                    "pSize":            1000,
                    "SCHUL_KND_SC_NM":  stype,
                }
                if sido_cd:
                    params["ATPT_OFCDC_SC_NM"] = sido_cd

                try:
                    resp = self.session.get(SCHOOL_URL, params=params, timeout=30)
                    resp.raise_for_status()
                    data = resp.json()
                    items = data.get("schoolInfo", [{}])
                    if len(items) < 2:
                        break
                    batch = items[1].get("row", [])
                    if not batch:
                        break

                    with sqlite3.connect(self.db_path) as conn:
                        for r in batch:
                            try:
                                conn.execute("""
                                    INSERT OR REPLACE INTO school_info
                                    (school_code, school_nm, school_type, sgg_cd,
                                     sido_nm, sgg_nm, addr, lat, lng,
                                     student_cnt, class_cnt)
                                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                                """, (
                                    r.get("SD_SCHUL_CODE"),
                                    r.get("SCHUL_NM"),
                                    stype,
                                    r.get("LCTN_SC_NM"),        # 소재지구분명(시군구 대신)
                                    r.get("ATPT_OFCDC_SC_NM"),  # 시도교육청명
                                    r.get("LCTN_SC_NM"),
                                    r.get("ORG_RDNMA"),          # 도로명주소
                                    _to_float(r.get("LATIT_VALUE")),
                                    _to_float(r.get("LONGT_VALUE")),
                                    None, None,
                                ))
                                inserted += 1
                            except Exception:
                                pass

                    if len(batch) < 1000:
                        break
                    page += 1
                    time.sleep(0.2)
                except Exception as e:
                    log.error("학교 수집 오류 [%s p%d]: %s", stype, page, e)
                    break
            log.info("school_info [%s]: %d건 누적", stype, inserted)

        log.info("school_info 저장: %d건", inserted)
        return inserted

    def collect_achievement(self, year: int = 2023) -> int:
        if not self.neis_key:
            log.warning("NEIS_API_KEY 없음 — 학업성취도 수집 스킵")
            return 0

        inserted = 0
        offset, size = 1, 100
        while True:
            try:
                resp = self.session.get(ACHIEVEMENT_URL, params={
                    "KEY":        self.neis_key,
                    "Type":       "json",
                    "pIndex":     offset,
                    "pSize":      size,
                    "SCHUL_YEAR": str(year),
                }, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                items = data.get("SchoolAchievementInfo", [{}])
                if len(items) < 2:
                    break
                rows = items[1].get("row", [])
                if not rows:
                    break

                with sqlite3.connect(self.db_path) as conn:
                    for r in rows:
                        try:
                            conn.execute("""
                                INSERT OR REPLACE INTO school_achievement
                                (school_code, exam_year, subject,
                                 below_basic, basic, proficient, advanced)
                                VALUES (?,?,?,?,?,?,?)
                            """, (
                                r.get("SCHUL_CODE"), year,
                                r.get("ATCH_FILE_CREAT_YM"),
                                _to_float(r.get("BELW_BASIC_RATE")),
                                _to_float(r.get("BASIC_RATE")),
                                _to_float(r.get("PROFC_RATE")),
                                _to_float(r.get("ADVANC_RATE")),
                            ))
                            inserted += 1
                        except Exception:
                            pass
                offset += 1
                time.sleep(0.2)
            except Exception as e:
                log.error("학업성취도 수집 오류: %s", e)
                break

        log.info("school_achievement 저장: %d건", inserted)
        return inserted

    def build_district_scores(self, year: int = 2023) -> int:
        """시군구별 학군 등급 산출"""
        with sqlite3.connect(self.db_path) as conn:
            # 시군구별 학교 수, 학생 수
            school_agg = conn.execute("""
                SELECT sgg_cd,
                       COUNT(*) AS school_cnt,
                       SUM(CASE WHEN school_type='고등학교' THEN 1 ELSE 0 END) AS hs_cnt
                FROM school_info
                WHERE sgg_cd IS NOT NULL
                GROUP BY sgg_cd
            """).fetchall()

            # 시군구별 학업 성취도 평균 (우수+보통 비율)
            achieve_agg = conn.execute("""
                SELECT si.sgg_cd,
                       AVG((sa.advanced + sa.proficient)) AS avg_score
                FROM school_achievement sa
                JOIN school_info si ON sa.school_code = si.school_code
                WHERE sa.exam_year = ?
                  AND sa.advanced IS NOT NULL
                  AND sa.proficient IS NOT NULL
                GROUP BY si.sgg_cd
            """, (year,)).fetchall()

        achieve_map = {r[0]: r[1] for r in achieve_agg}
        inserted = 0

        with sqlite3.connect(self.db_path) as conn:
            for sgg_cd, school_cnt, hs_cnt in school_agg:
                score = achieve_map.get(sgg_cd, 65.0)  # 데이터 없으면 평균값
                grade = next(g for threshold, g in SCORE_GRADE if score >= threshold)
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO school_district_score
                        (sgg_cd, year, avg_score, school_cnt, high_school_cnt, grade)
                        VALUES (?,?,?,?,?,?)
                    """, (sgg_cd, year, round(score, 2), school_cnt, hs_cnt, grade))
                    inserted += 1
                except Exception:
                    pass

        log.info("school_district_score 저장: %d건", inserted)
        return inserted

    def collect_all(self, year: int = 2023) -> dict:
        return {
            "schools":     self.collect_schools(),
            "achievement": self.collect_achievement(year),
            "districts":   self.build_district_scores(year),
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
    c = SchoolCollector()
    print(c.collect_all())
