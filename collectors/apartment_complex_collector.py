"""
국토교통부 공동주택단지 정보 수집기
=======================================
수집 항목:
  - 공동주택단지목록 → apt_complex
  - 공동주택기본정보 → apt_complex (단지코드 기준 상세)

API: data.go.kr
  - 공동주택단지목록: 1611000/AptListService/getLegaldongAptList
  - 공동주택기본정보: 1611000/AptBasisInfoService/getAphusBassInfo

주요 활용:
  - kaptCode: 공동주택 단지코드 (청약홈, 학군 등 연결 키)
  - 총세대수, 최고층수, 단지 규모
  - 준공일, 건설사, 난방방식

NOTE: API 승인 후 활성화 대기 중 (2026-04-28 기준)
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

LIST_URL  = "https://apis.data.go.kr/1611000/AptListService/getLegaldongAptList"
BASIS_URL = "https://apis.data.go.kr/1611000/AptBasisInfoService/getAphusBassInfo"

DDL = """
CREATE TABLE IF NOT EXISTS apt_complex (
    kapt_code      TEXT    PRIMARY KEY,
    kapt_name      TEXT,
    sigungu_cd     TEXT,
    bjdong_cd      TEXT,
    bjdong_nm      TEXT,
    build_year     INTEGER,
    total_units    INTEGER,
    max_floors     INTEGER,
    min_floors     INTEGER,
    heat_type      TEXT,
    constructor    TEXT,
    management_nm  TEXT,
    road_nm_addr   TEXT,
    jibun_addr     TEXT,
    lat            REAL,
    lon            REAL,
    collected_at   TEXT DEFAULT (datetime('now'))
)"""

IDX = "CREATE INDEX IF NOT EXISTS idx_cmpx_sgg ON apt_complex(sigungu_cd)"


class ApartmentComplexCollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key = api_key or os.getenv("DATA_GO_KR_API_KEY", "")
        self.db_path = db_path
        self.session = requests.Session()
        self._init_table()

    def _init_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL)
            conn.execute(IDX)

    def _fetch_list_page(self, ldong_cd: str, page: int = 1,
                         rows: int = 100) -> tuple[list, int]:
        """법정동코드로 단지목록 조회"""
        if not self.api_key:
            return [], 0
        try:
            params = {
                "serviceKey": self.api_key,
                "numOfRows":  rows,
                "pageNo":     page,
                "_type":      "json",
                "ldongCd":    ldong_cd,
            }
            resp = self.session.get(LIST_URL, params=params, timeout=30)
            if resp.status_code != 200:
                log.debug("공동주택단지목록 API 미활성 [%s]: HTTP %d", ldong_cd, resp.status_code)
                return [], 0
            body = resp.json().get("response", {}).get("body", {})
            total = int(body.get("totalCount", 0))
            items = body.get("items", {})
            if not items:
                return [], total
            rows_data = items.get("item", [])
            if isinstance(rows_data, dict):
                rows_data = [rows_data]
            return rows_data, total
        except Exception as e:
            log.error("공동주택단지목록 오류 [%s]: %s", ldong_cd, e)
            return [], 0

    def _fetch_basis(self, kapt_code: str) -> Optional[dict]:
        """단지코드로 기본정보 조회"""
        if not self.api_key:
            return None
        try:
            params = {
                "serviceKey": self.api_key,
                "_type":      "json",
                "kaptCode":   kapt_code,
            }
            resp = self.session.get(BASIS_URL, params=params, timeout=30)
            if resp.status_code != 200:
                return None
            body = resp.json().get("response", {}).get("body", {})
            items = body.get("item", None) or body.get("items", {}).get("item", None)
            if isinstance(items, list) and items:
                return items[0]
            if isinstance(items, dict):
                return items
            return None
        except Exception as e:
            log.error("공동주택기본정보 오류 [%s]: %s", kapt_code, e)
            return None

    def _upsert(self, conn, r: dict, basis: dict = None) -> bool:
        kapt_code = str(r.get("kaptCode", "")).strip()
        if not kapt_code:
            return False
        b = basis or {}
        use_apr = str(b.get("kaptUsedate", "")).strip()
        build_year = int(use_apr[:4]) if len(use_apr) >= 4 and use_apr[:4].isdigit() else None
        try:
            conn.execute("""
                INSERT OR REPLACE INTO apt_complex
                (kapt_code, kapt_name, sigungu_cd, bjdong_cd, bjdong_nm,
                 build_year, total_units, max_floors, min_floors,
                 heat_type, constructor, management_nm, road_nm_addr, jibun_addr)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                kapt_code,
                r.get("kaptName", "") or b.get("kaptName", ""),
                str(r.get("sigunguCd", ""))[:5],
                str(r.get("bjdongCd", ""))[:5],
                r.get("bjdongNm", ""),
                build_year,
                _to_int(b.get("kaptTothhCnt")),
                _to_int(b.get("kaptMaxFloor")),
                _to_int(b.get("kaptMinFloor")),
                b.get("kaptHeatMethd", ""),
                b.get("kaptBuilder", ""),
                b.get("kaptMngrNm", ""),
                b.get("roadNmAddr", ""),
                b.get("jibunAddr", ""),
            ))
            return True
        except Exception:
            return False

    def collect_by_ldong(self, ldong_cd: str, fetch_basis: bool = True) -> int:
        """법정동 단위로 단지목록 + 기본정보 수집"""
        rows, total = self._fetch_list_page(ldong_cd, rows=1)
        if total == 0:
            return 0

        rows_per_page = 100
        pages = (total + rows_per_page - 1) // rows_per_page
        inserted = 0

        for page in range(1, pages + 1):
            items, _ = self._fetch_list_page(ldong_cd, page=page, rows=rows_per_page)
            with sqlite3.connect(self.db_path) as conn:
                for item in items:
                    basis = None
                    if fetch_basis:
                        kapt_code = str(item.get("kaptCode", "")).strip()
                        if kapt_code:
                            basis = self._fetch_basis(kapt_code)
                            time.sleep(0.1)
                    if self._upsert(conn, item, basis):
                        inserted += 1
            time.sleep(0.3)

        return inserted

    def collect_all(self, db_path: str = None) -> dict:
        """거래 DB 기반 전체 법정동 수집"""
        source_db = db_path or self.db_path
        try:
            with sqlite3.connect(source_db) as conn:
                pairs = conn.execute("""
                    SELECT DISTINCT sggCd || umdCd as ldong_cd
                    FROM apt_trade
                    WHERE sggCd IS NOT NULL AND umdCd IS NOT NULL
                """).fetchall()
            ldong_codes = [r[0] for r in pairs]
        except Exception as e:
            log.warning("거래 DB 법정동 코드 로드 실패: %s", e)
            ldong_codes = []

        if not ldong_codes:
            log.warning("수집 대상 법정동 없음")
            return {"total": 0, "ldong_count": 0}

        total = 0
        for ldong in ldong_codes:
            n = self.collect_by_ldong(ldong)
            total += n

        return {"total": total, "ldong_count": len(ldong_codes)}


def _to_int(v) -> Optional[int]:
    try:    return int(str(v).replace(",", ""))
    except: return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = ApartmentComplexCollector()
    # 강남구 역삼동 테스트 (ldongCd = sggCd + umdCd)
    result = c.collect_by_ldong("1168010100")
    print("결과:", result)
