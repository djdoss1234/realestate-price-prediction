"""
소상공인시장진흥공단 상가정보 수집기
=====================================
수집 항목:
  - 시군구별 상가업소 정보 → commercial_district

API 키: B553077 (DATA_GO_KR_API_KEY 동일)
엔드포인트: http://apis.data.go.kr/B553077/api/open/sdsc2/storeListInDong
주의: http:// 사용 (https 불가)
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

BASE_URL = "http://apis.data.go.kr/B553077/api/open/sdsc2/storeListInDong"

DDL = """
CREATE TABLE IF NOT EXISTS commercial_district (
    bizesId     TEXT PRIMARY KEY,
    bizesNm     TEXT,
    brchNm      TEXT,
    indsLclsCd  TEXT,
    indsLclsNm  TEXT,
    indsMclsNm  TEXT,
    indsSclsNm  TEXT,
    signguCd    TEXT,
    signguNm    TEXT,
    ldongCd     TEXT,
    ldongNm     TEXT,
    rdnmAdr     TEXT,
    lnoAdr      TEXT,
    lat         REAL,
    lon         REAL,
    collected_at TEXT DEFAULT (datetime('now'))
)"""

IDX = "CREATE INDEX IF NOT EXISTS idx_cd_sgg ON commercial_district(signguCd)"

# 주요 업종 대분류 (전체 수집 시 생략 가능)
INDS_LCL_CODES = None  # None이면 전 업종


class CommercialDistrictCollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key = api_key or os.getenv("DATA_GO_KR_API_KEY", "")
        self.db_path = db_path
        self.session = requests.Session()
        self._init_table()

    def _init_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL)
            conn.execute(IDX)

    def _fetch_page(self, signgu_cd: str, page: int = 1, page_size: int = 1000) -> tuple[list, int]:
        if not self.api_key:
            return [], 0
        params = {
            "key":       self.api_key,
            "divId":     "signguCd",
            "key_value": signgu_cd,
            "pageNo":    page,
            "pageSize":  page_size,
            "type":      "json",
        }
        try:
            resp = self.session.get(BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            js = resp.json()
            # 응답 구조: {"header": {...}, "body": {"totalCount": N, "items": {"item": [...]}}}
            body = js.get("body", {})
            total = int(body.get("totalCount", 0))
            items = body.get("items", {})
            if not items:
                return [], total
            batch = items.get("item", [])
            if isinstance(batch, dict):
                batch = [batch]
            return batch, total
        except Exception as e:
            log.error("상가정보 API 오류 [%s p%d]: %s", signgu_cd, page, e)
            return [], 0

    def collect_by_sigungu(self, signgu_cd: str) -> int:
        batch, total = self._fetch_page(signgu_cd, page=1, page_size=1)
        if total == 0:
            return 0

        pages = (total + 999) // 1000
        log.info("상가정보 %s: 총 %d건, %d페이지", signgu_cd, total, pages)
        inserted = 0

        for page in range(1, pages + 1):
            items, _ = self._fetch_page(signgu_cd, page=page, page_size=1000)
            with sqlite3.connect(self.db_path) as conn:
                for r in items:
                    try:
                        conn.execute("""
                            INSERT OR REPLACE INTO commercial_district
                            (bizesId, bizesNm, brchNm, indsLclsCd, indsLclsNm,
                             indsMclsNm, indsSclsNm, signguCd, signguNm,
                             ldongCd, ldongNm, rdnmAdr, lnoAdr, lat, lon)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """, (
                            r.get("bizesId"),
                            r.get("bizesNm"),
                            r.get("brchNm"),
                            r.get("indsLclsCd"),
                            r.get("indsLclsNm"),
                            r.get("indsMclsNm"),
                            r.get("indsSclsNm"),
                            r.get("signguCd"),
                            r.get("signguNm"),
                            r.get("ldongCd"),
                            r.get("ldongNm"),
                            r.get("rdnmAdr"),
                            r.get("lnoAdr"),
                            _to_float(r.get("lat")),
                            _to_float(r.get("lon")),
                        ))
                        inserted += 1
                    except Exception:
                        pass
            time.sleep(0.3)

        log.info("상가정보 %s 저장: %d건", signgu_cd, inserted)
        return inserted

    def collect_all(self, db_path: str = None) -> dict:
        """apt_trade DB의 시군구 코드 기반 전체 수집"""
        if not self.api_key:
            log.warning("DATA_GO_KR_API_KEY 없음 — 상가정보 수집 스킵")
            return {"total": 0}

        source_db = db_path or self.db_path
        try:
            with sqlite3.connect(source_db) as conn:
                sgg_list = [r[0] for r in conn.execute(
                    "SELECT DISTINCT sggCd FROM apt_trade WHERE sggCd IS NOT NULL ORDER BY sggCd"
                ).fetchall()]
        except Exception as e:
            log.warning("시군구 목록 로드 실패: %s", e)
            sgg_list = []

        if not sgg_list:
            log.warning("수집 대상 시군구 없음")
            return {"total": 0, "sgg_count": 0}

        total = 0
        for i, sgg_cd in enumerate(sgg_list, 1):
            n = self.collect_by_sigungu(sgg_cd)
            total += n
            log.info("진행: %d/%d 시군구 완료 (누적 %d건)", i, len(sgg_list), total)

        return {"total": total, "sgg_count": len(sgg_list)}


def _to_float(v) -> Optional[float]:
    try:    return float(str(v).replace(",", ""))
    except: return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os; os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = CommercialDistrictCollector()
    # 강남구 (11680) 테스트
    print(c.collect_by_sigungu("11680"))
