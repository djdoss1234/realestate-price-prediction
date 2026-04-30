"""
카카오맵 Local API - POI 수집기
================================
수집 항목 (단지 좌표 기준 반경):
  - 지하철역 거리·개수 (반경 1km)
  - 학교 개수 (반경 500m)
  - 편의시설: 대형마트·편의점·병원 (반경 500m)

API 키 발급: https://developers.kakao.com (REST API 키)
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

KEYWORD_URL  = "https://dapi.kakao.com/v2/local/search/keyword.json"
CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"

# 카카오 카테고리 코드
CAT = {
    "subway":       "SW8",   # 지하철역
    "school_elem":  "SC4",   # 초등학교
    "school_mid":   "SC4",   # 중학교 (필터로 구분)
    "supermarket":  "MT1",   # 대형마트
    "convenience":  "CS2",   # 편의점
    "hospital":     "HP8",   # 병원
    "pharmacy":     "PM9",   # 약국
    "park":         "AT4",   # 관광명소(공원 포함)
}

DDL = """
CREATE TABLE IF NOT EXISTS kakao_poi (
    apt_nm       TEXT NOT NULL,
    sgg_cd       TEXT,
    lat          REAL,
    lng          REAL,
    subway_cnt   INTEGER DEFAULT 0,
    subway_dist_m REAL,
    elem_school_cnt INTEGER DEFAULT 0,
    supermarket_cnt INTEGER DEFAULT 0,
    convenience_cnt INTEGER DEFAULT 0,
    hospital_cnt INTEGER DEFAULT 0,
    collected_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (apt_nm, sgg_cd)
)"""


class KakaoPOICollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key = api_key or os.getenv("KAKAO_REST_API_KEY", "")
        self.db_path = db_path
        self.session = requests.Session()
        if self.api_key:
            self.session.headers["Authorization"] = f"KakaoAK {self.api_key}"
        self._init_table()

    def _init_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL)

    def _search_category(self, category: str, lat: float, lng: float, radius: int = 1000) -> list[dict]:
        if not self.api_key:
            return []
        try:
            resp = self.session.get(CATEGORY_URL, params={
                "category_group_code": category,
                "x": lng, "y": lat,
                "radius": radius,
                "size": 15,
            }, timeout=10)
            resp.raise_for_status()
            return resp.json().get("documents", [])
        except Exception as e:
            log.warning("카카오 카테고리(%s) 조회 실패: %s", category, e)
            return []

    def _haversine(self, lat1, lng1, lat2, lng2) -> float:
        """두 좌표 간 거리 (미터)"""
        import math
        R = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lng2 - lng1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    def collect_poi(self, apt_nm: str, sgg_cd: str, lat: float, lng: float) -> dict:
        """단일 단지 POI 수집"""
        if not self.api_key:
            log.warning("KAKAO_REST_API_KEY 없음 — 스킵")
            return {}

        subways    = self._search_category("SW8", lat, lng, radius=1000)
        elem_sch   = self._search_category("SC4", lat, lng, radius=500)
        markets    = self._search_category("MT1", lat, lng, radius=500)
        convs      = self._search_category("CS2", lat, lng, radius=500)
        hospitals  = self._search_category("HP8", lat, lng, radius=500)

        nearest_dist = None
        if subways:
            dists = [self._haversine(lat, lng, float(d["y"]), float(d["x"])) for d in subways]
            nearest_dist = round(min(dists), 1)

        result = {
            "apt_nm":          apt_nm,
            "sgg_cd":          sgg_cd,
            "lat":             lat,
            "lng":             lng,
            "subway_cnt":      len(subways),
            "subway_dist_m":   nearest_dist,
            "elem_school_cnt": len(elem_sch),
            "supermarket_cnt": len(markets),
            "convenience_cnt": len(convs),
            "hospital_cnt":    len(hospitals),
        }

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO kakao_poi
                (apt_nm, sgg_cd, lat, lng, subway_cnt, subway_dist_m,
                 elem_school_cnt, supermarket_cnt, convenience_cnt, hospital_cnt)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                apt_nm, sgg_cd, lat, lng,
                result["subway_cnt"], result["subway_dist_m"],
                result["elem_school_cnt"], result["supermarket_cnt"],
                result["convenience_cnt"], result["hospital_cnt"],
            ))

        time.sleep(0.1)   # Kakao API 초당 10회 제한
        return result

    def _get_coord_by_keyword(self, apt_nm: str, umd_nm: str) -> Optional[tuple[float, float]]:
        """Kakao 키워드 검색으로 단지 좌표 반환 (lat, lng)"""
        if not self.api_key:
            return None
        query = f"{umd_nm} {apt_nm}"
        try:
            resp = self.session.get(KEYWORD_URL, params={
                "query": query, "size": 1,
            }, timeout=10)
            resp.raise_for_status()
            docs = resp.json().get("documents", [])
            if docs:
                return float(docs[0]["y"]), float(docs[0]["x"])
        except Exception as e:
            log.warning("좌표 검색 실패 [%s]: %s", query, e)
        return None

    def collect_from_db(self, limit: int = 1000):
        """apt_trade DB에서 단지 목록을 가져와 Kakao 키워드 검색으로 좌표 취득 후 POI 수집"""
        with sqlite3.connect(self.db_path) as conn:
            apts = conn.execute("""
                SELECT DISTINCT aptNm, sggCd, umdNm
                FROM apt_trade
                WHERE aptNm NOT IN (SELECT apt_nm FROM kakao_poi)
                GROUP BY aptNm, sggCd
                LIMIT ?
            """, (limit,)).fetchall()

        total = len(apts)
        log.info("POI 수집 대상: %d개 단지", total)
        results = []
        for i, (apt_nm, sgg_cd, umd_nm) in enumerate(apts, 1):
            try:
                coord = self._get_coord_by_keyword(str(apt_nm), str(umd_nm or ""))
                if coord is None:
                    log.debug("좌표 없음 스킵: %s %s", apt_nm, umd_nm)
                    continue
                lat, lng = coord
                r = self.collect_poi(str(apt_nm), str(sgg_cd), lat, lng)
                if r:
                    results.append(r)
            except Exception as e:
                log.warning("POI 수집 실패 [%s]: %s", apt_nm, e)
            if i % 500 == 0:
                log.info("진행: %d/%d (%.1f%%)", i, total, i/total*100)
        log.info("POI 수집 완료: %d건", len(results))
        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os; os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = KakaoPOICollector()
    # 테스트: 래미안대치팰리스 (강남구)
    print(c.collect_poi("래미안대치팰리스", "11680", 37.4951, 127.0640))
