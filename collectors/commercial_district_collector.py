"""
소상공인시장진흥공단 상가정보 수집기
=====================================
수집 항목:
  - 아파트 단지 반경 500m 내 상가업소 → commercial_district

API 키: DATA_GO_KR_API_KEY (serviceKey)
엔드포인트: http://apis.data.go.kr/B553077/api/open/sdsc2/storeListInRadius
  - storeListInDong 은 파라미터 오류로 사용 불가, storeListInRadius 사용
  - cx=경도, cy=위도, radius=미터 단위

수집 전략:
  - kakao_poi 테이블의 아파트 단지 좌표 기반으로 반경 500m 상가 수집
  - bizesId PRIMARY KEY로 중복 자동 제거
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

BASE_URL = "http://apis.data.go.kr/B553077/api/open/sdsc2/storeListInRadius"

DDL = """
CREATE TABLE IF NOT EXISTS commercial_district (
    bizesId      TEXT PRIMARY KEY,
    bizesNm      TEXT,
    brchNm       TEXT,
    indsLclsCd   TEXT,
    indsLclsNm   TEXT,
    indsMclsNm   TEXT,
    indsSclsNm   TEXT,
    signguCd     TEXT,
    signguNm     TEXT,
    adongCd      TEXT,
    adongNm      TEXT,
    rdnmAdr      TEXT,
    lnoAdr       TEXT,
    lat          REAL,
    lon          REAL,
    collected_at TEXT DEFAULT (datetime('now'))
)"""

IDX = "CREATE INDEX IF NOT EXISTS idx_cd_sgg ON commercial_district(signguCd)"


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

    def _fetch_page(self, cx: float, cy: float, radius: int = 500,
                    page: int = 1, page_size: int = 1000) -> tuple[list, int]:
        if not self.api_key:
            return [], 0
        try:
            resp = self.session.get(BASE_URL, params={
                "serviceKey": self.api_key,
                "cx":         cx,
                "cy":         cy,
                "radius":     radius,
                "pageNo":     page,
                "pageSize":   page_size,
                "type":       "json",
            }, timeout=30)
            resp.raise_for_status()
            body = resp.json().get("body", {})
            total = int(body.get("totalCount", 0))
            items = body.get("items", [])
            if isinstance(items, dict):
                items = [items]
            return items or [], total
        except Exception as e:
            log.error("상가정보 API 오류 [%.4f,%.4f]: %s", cx, cy, e)
            return [], 0

    def collect_around_point(self, cx: float, cy: float, radius: int = 500) -> int:
        _, total = self._fetch_page(cx, cy, radius, page=1, page_size=1)
        if total == 0:
            return 0

        pages = (total + 999) // 1000
        inserted = 0
        for page in range(1, pages + 1):
            items, _ = self._fetch_page(cx, cy, radius, page=page, page_size=1000)
            with sqlite3.connect(self.db_path) as conn:
                for r in items:
                    try:
                        conn.execute("""
                            INSERT OR REPLACE INTO commercial_district
                            (bizesId, bizesNm, brchNm, indsLclsCd, indsLclsNm,
                             indsMclsNm, indsSclsNm, signguCd, signguNm,
                             adongCd, adongNm, rdnmAdr, lnoAdr, lat, lon)
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
                            r.get("adongCd"),
                            r.get("adongNm"),
                            r.get("rdnmAdr"),
                            r.get("lnoAdr"),
                            _to_float(r.get("lat")),
                            _to_float(r.get("lon")),
                        ))
                        inserted += 1
                    except Exception:
                        pass
            time.sleep(0.2)
        return inserted

    def collect_all(self, radius: int = 1000) -> dict:
        """kakao_poi 기반 1km 그리드 좌표로 상가 수집 (중복 API 호출 최소화)"""
        if not self.api_key:
            log.warning("DATA_GO_KR_API_KEY 없음 — 상가정보 수집 스킵")
            return {"total": 0}

        with sqlite3.connect(self.db_path) as conn:
            # 1km 격자로 rounding (위도 0.009도 ≈ 1km, 경도 0.011도 ≈ 1km)
            apts = conn.execute("""
                SELECT DISTINCT
                    ROUND(lat / 0.009) * 0.009  AS grid_lat,
                    ROUND(lng / 0.011) * 0.011  AS grid_lng
                FROM kakao_poi
                WHERE lat IS NOT NULL AND lng IS NOT NULL
                  AND lat BETWEEN 33 AND 38.5
                  AND lng BETWEEN 125 AND 131
                ORDER BY grid_lat, grid_lng
            """).fetchall()

        total = 0
        for i, (cy, cx) in enumerate(apts, 1):
            n = self.collect_around_point(cx, cy, radius)
            total += n
            if i % 100 == 0:
                log.info("상가수집 진행: %d/%d 격자 (누적 %d건)", i, len(apts), total)
            time.sleep(0.5)  # 429 방지: 초당 2건 이하

        log.info("상가정보 수집 완료: %d건", total)
        return {"total": total, "grid_count": len(apts)}


def _to_float(v) -> Optional[float]:
    try:    return float(str(v).replace(",", ""))
    except: return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os; os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = CommercialDistrictCollector()
    # 강남역 반경 500m 테스트
    print(c.collect_around_point(127.027, 37.499, radius=500))
