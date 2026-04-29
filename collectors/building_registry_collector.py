"""
국토교통부 건축물대장 수집기
==============================
수집 항목:
  - 건축물대장 표제부  → building_registry

API: data.go.kr → 국토교통부_건축물대장정보서비스
     (BldRgstHubService / getBrTitleInfo)

주요 활용 피처:
  - 건물 연령 (useAprDay → build_year)
  - 층수 (grndFlrCnt), 연면적, 건폐율/용적률
  - 주용도 (아파트 / 단독 / 다가구 등)
  - 구조 (철근콘크리트 등)

데이터 접근 방식:
  - API는 sigunguCd + bjdongCd 두 값이 모두 필요
  - apt_trade 의 (sggCd, umdCd) 조합을 기반으로 수집
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"

DDL = """
CREATE TABLE IF NOT EXISTS building_registry (
    mgm_pk         TEXT    PRIMARY KEY,
    sigungu_cd     TEXT    NOT NULL,
    bjdong_cd      TEXT,
    plat_plc       TEXT,
    new_plat_plc   TEXT,
    bld_nm         TEXT,
    use_apr_day    TEXT,
    build_year     INTEGER,
    grnd_flr_cnt   INTEGER,
    ugrnd_flr_cnt  INTEGER,
    tot_area       REAL,
    plat_area      REAL,
    arch_area      REAL,
    bc_rat         REAL,
    vl_rat         REAL,
    main_purps_cd  TEXT,
    main_purps_nm  TEXT,
    strct_cd       TEXT,
    strct_nm       TEXT,
    hhld_cnt       INTEGER,
    fmly_cnt       INTEGER,
    collected_at   TEXT DEFAULT (datetime('now'))
)"""

IDX_SIGUNGU = "CREATE INDEX IF NOT EXISTS idx_bldg_sigungu ON building_registry(sigungu_cd)"
IDX_YEAR    = "CREATE INDEX IF NOT EXISTS idx_bldg_year ON building_registry(build_year)"


class BuildingRegistryCollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key = api_key or os.getenv("DATA_GO_KR_API_KEY", "")
        self.db_path = db_path
        self.session = requests.Session()
        self._init_table()

    def _init_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL)
            conn.execute(IDX_SIGUNGU)
            conn.execute(IDX_YEAR)

    def _fetch_page(self, sigungu_cd: str, bjdong_cd: str,
                    page: int = 1, rows: int = 100) -> tuple[list, int]:
        if not self.api_key:
            log.warning("DATA_GO_KR_API_KEY 없음 — 건축물대장 수집 스킵")
            return [], 0
        try:
            params = {
                "serviceKey": self.api_key,
                "numOfRows":  rows,
                "pageNo":     page,
                "_type":      "json",
                "sigunguCd":  sigungu_cd,
                "bjdongCd":   bjdong_cd,
            }
            resp = self.session.get(BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
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
            log.error("건축물대장 수집 오류 [%s/%s p%d]: %s", sigungu_cd, bjdong_cd, page, e)
            return [], 0

    def _upsert(self, conn, rows: list) -> int:
        count = 0
        for r in rows:
            pk = str(r.get("mgmBldrgstPk", "")).strip()
            if not pk:
                continue
            use_apr = str(r.get("useAprDay", "")).strip()
            build_year = int(use_apr[:4]) if len(use_apr) >= 4 and use_apr[:4].isdigit() else None
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO building_registry
                    (mgm_pk, sigungu_cd, bjdong_cd, plat_plc, new_plat_plc, bld_nm,
                     use_apr_day, build_year, grnd_flr_cnt, ugrnd_flr_cnt,
                     tot_area, plat_area, arch_area, bc_rat, vl_rat,
                     main_purps_cd, main_purps_nm, strct_cd, strct_nm,
                     hhld_cnt, fmly_cnt)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    pk,
                    str(r.get("sigunguCd", "")),
                    str(r.get("bjdongCd", "")),
                    r.get("platPlc", ""),
                    r.get("newPlatPlc", ""),
                    r.get("bldNm", ""),
                    use_apr or None,
                    build_year,
                    _to_int(r.get("grndFlrCnt")),
                    _to_int(r.get("ugrndFlrCnt")),
                    _to_float(r.get("totArea")),
                    _to_float(r.get("platArea")),
                    _to_float(r.get("archArea")),
                    _to_float(r.get("bcRat")),
                    _to_float(r.get("vlRat")),
                    str(r.get("mainPurpsCd", "")),
                    r.get("mainPurpsCdNm", ""),
                    str(r.get("strctCd", "")),
                    r.get("strctCdNm", ""),
                    _to_int(r.get("hhldCnt")),
                    _to_int(r.get("fmlyCnt")),
                ))
                count += 1
            except Exception:
                pass
        return count

    def collect_pair(self, sigungu_cd: str, bjdong_cd: str,
                     rows_per_page: int = 100) -> int:
        """(시군구, 법정동) 한 쌍 전체 수집 (페이징)"""
        _, total = self._fetch_page(sigungu_cd, bjdong_cd, rows=1)
        if total == 0:
            return 0

        inserted = 0
        pages = (total + rows_per_page - 1) // rows_per_page
        log.debug("건축물대장 [%s/%s] %d건 / %d페이지", sigungu_cd, bjdong_cd, total, pages)

        for page in range(1, pages + 1):
            rows, _ = self._fetch_page(sigungu_cd, bjdong_cd, page=page, rows=rows_per_page)
            if not rows:
                time.sleep(0.5)
                continue
            with sqlite3.connect(self.db_path) as conn:
                inserted += self._upsert(conn, rows)
            time.sleep(0.3)

        return inserted

    def _load_pairs_from_db(self) -> list[tuple[str, str]]:
        """거래 DB에서 (sggCd, umdCd) 조합 추출"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute("""
                    SELECT DISTINCT sggCd, umdCd
                    FROM apt_trade
                    WHERE sggCd IS NOT NULL AND umdCd IS NOT NULL
                      AND sggCd != '' AND umdCd != ''
                    ORDER BY sggCd, umdCd
                """).fetchall()
            return [(r[0], r[1]) for r in rows]
        except Exception as e:
            log.warning("거래 DB에서 코드 로드 실패: %s", e)
            return []

    def collect_all(self, pairs: list[tuple[str, str]] = None,
                    sigungu_codes: list[str] = None) -> dict:
        """전국 또는 지정 (시군구, 법정동) 수집

        Args:
            pairs: [(sigunguCd, bjdongCd), ...] — 직접 지정
            sigungu_codes: 시군구 코드만 지정 시 DB에서 해당 법정동 자동 추출
        """
        if pairs:
            target = pairs
        else:
            all_pairs = self._load_pairs_from_db()
            if sigungu_codes:
                target = [(s, b) for s, b in all_pairs if s in set(sigungu_codes)]
            else:
                target = all_pairs

        if not target:
            log.warning("수집 대상 (시군구, 법정동) 쌍 없음 — 건축물대장 수집 스킵")
            return {"total": 0, "pairs": 0}

        total = 0
        for sigungu_cd, bjdong_cd in target:
            n = self.collect_pair(sigungu_cd, bjdong_cd)
            total += n

        log.info("건축물대장 전체 수집 완료: %d건 (%d 법정동)", total, len(target))
        return {"total": total, "pairs": len(target)}


def _to_int(v) -> Optional[int]:
    try:    return int(str(v).replace(",", ""))
    except: return None


def _to_float(v) -> Optional[float]:
    try:    return float(str(v).replace(",", ""))
    except: return None


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO)
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = BuildingRegistryCollector()
    # 강남구 역삼동만 테스트
    result = c.collect_pair("11680", "10100")
    print("결과:", result)
