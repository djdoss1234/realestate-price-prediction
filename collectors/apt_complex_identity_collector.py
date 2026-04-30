"""
한국부동산원 공동주택 단지 식별정보 수집기
=============================================
수집 항목:
  - 아파트 단지코드(kaptCode) ↔ 단지명·시군구코드 매핑 → kapt_identity

API 키: DATA_GO_KR_API_KEY
  - 단지목록: https://apis.data.go.kr/1613000/AptListService3/getLegaldongAptList3
  - 단지기본: https://apis.data.go.kr/1613000/AptBasisInfoServiceV4/getAphusBassInfoV4

활용 목적:
  - apt_trade(실거래) ↔ kakao_poi ↔ school_info 등 데이터셋 간 단지코드 조인키
  - kaptCode는 청약홈·학군정보·관리비 등과 연결되는 마스터키
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

LIST_URL  = "https://apis.data.go.kr/1613000/AptListService3/getLegaldongAptList3"
BASIS_URL = "https://apis.data.go.kr/1613000/AptBasisInfoServiceV4/getAphusBassInfoV4"

DDL = """
CREATE TABLE IF NOT EXISTS kapt_identity (
    kapt_code     TEXT PRIMARY KEY,
    kapt_name     TEXT,
    sigungu_cd    TEXT,
    bjdong_cd     TEXT,
    bjdong_nm     TEXT,
    road_nm_addr  TEXT,
    jibun_addr    TEXT,
    lat           REAL,
    lon           REAL,
    build_year    INTEGER,
    total_units   INTEGER,
    collected_at  TEXT DEFAULT (datetime('now'))
)"""

IDX = "CREATE INDEX IF NOT EXISTS idx_kapt_id_sgg ON kapt_identity(sigungu_cd)"
IDX2 = "CREATE INDEX IF NOT EXISTS idx_kapt_id_nm ON kapt_identity(kapt_name)"


class AptComplexIdentityCollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key = api_key or os.getenv("DATA_GO_KR_API_KEY", "")
        self.db_path = db_path
        self.session = requests.Session()
        self._init_table()

    def _init_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL)
            conn.execute(IDX)
            conn.execute(IDX2)

    def _fetch_list(self, bjd_cd: str, page: int = 1, rows: int = 100) -> tuple[list, int]:
        if not self.api_key:
            return [], 0
        try:
            params = {
                "serviceKey": self.api_key,
                "numOfRows":  rows,
                "pageNo":     page,
                "_type":      "json",
                "bjdCode":    bjd_cd,
            }
            resp = self.session.get(LIST_URL, params=params, timeout=30)
            if resp.status_code != 200:
                return [], 0
            body = resp.json().get("response", {}).get("body", {})
            total = int(body.get("totalCount", 0))
            items = body.get("items", [])
            if not items:
                return [], total
            if isinstance(items, dict):
                items = items.get("item", [])
            if isinstance(items, dict):
                items = [items]
            return items or [], total
        except Exception as e:
            log.debug("단지목록 오류 [%s]: %s", bjd_cd, e)
        return [], 0

    def _fetch_basis(self, kapt_code: str) -> Optional[dict]:
        if not self.api_key:
            return None
        try:
            resp = self.session.get(BASIS_URL, params={
                "serviceKey": self.api_key,
                "_type":      "json",
                "kaptCode":   kapt_code,
            }, timeout=30)
            if resp.status_code != 200:
                return None
            body = resp.json().get("response", {}).get("body", {})
            item = body.get("item")
            if isinstance(item, list) and item:
                return item[0]
            if isinstance(item, dict):
                return item
        except Exception as e:
            log.debug("단지기본 오류 [%s]: %s", kapt_code, e)
        return None

    def collect_by_sgg(self, bjd_cd: str) -> int:
        _, total = self._fetch_list(bjd_cd, rows=1)
        if total == 0:
            return 0

        pages = (total + 99) // 100
        inserted = 0
        for page in range(1, pages + 1):
            items, _ = self._fetch_list(bjd_cd, page=page, rows=100)
            with sqlite3.connect(self.db_path) as conn:
                for r in items:
                    kapt_code = str(r.get("kaptCode", "")).strip()
                    if not kapt_code:
                        continue
                    basis = self._fetch_basis(kapt_code)
                    b = basis or {}
                    bjd = str(r.get("bjdCode", "")).strip()
                    use_dt = str(b.get("kaptUsedate", "")).strip()
                    build_year = int(use_dt[:4]) if len(use_dt) >= 4 and use_dt[:4].isdigit() else None
                    try:
                        conn.execute("""
                            INSERT OR REPLACE INTO kapt_identity
                            (kapt_code, kapt_name, sigungu_cd, bjdong_cd, bjdong_nm,
                             road_nm_addr, jibun_addr, build_year, total_units)
                            VALUES (?,?,?,?,?,?,?,?,?)
                        """, (
                            kapt_code,
                            r.get("kaptName") or b.get("kaptName"),
                            bjd[:5] if bjd else None,
                            bjd[5:] if len(bjd) >= 10 else None,
                            r.get("as3") or r.get("as2"),
                            b.get("doroJuso"),
                            b.get("kaptAddr"),
                            build_year,
                            _to_int(b.get("hoCnt")),
                        ))
                        inserted += 1
                    except Exception:
                        pass
                    time.sleep(0.1)
            time.sleep(0.3)

        log.info("kapt_identity [%s]: %d건", bjd_cd, inserted)
        return inserted

    def collect_all(self) -> dict:
        if not self.api_key:
            log.warning("DATA_GO_KR_API_KEY 없음 — 단지식별정보 수집 스킵")
            return {"total": 0}

        with sqlite3.connect(self.db_path) as conn:
            bjd_list = [r[0] for r in conn.execute("""
                SELECT DISTINCT sggCd || umdCd
                FROM apt_trade
                WHERE sggCd IS NOT NULL AND umdCd IS NOT NULL
                ORDER BY 1
            """).fetchall()]

        if not bjd_list:
            return {"total": 0, "bjd_count": 0}

        total = 0
        for i, bjd_cd in enumerate(bjd_list, 1):
            n = self.collect_by_sgg(str(bjd_cd))
            total += n
            if i % 50 == 0:
                log.info("단지식별 진행: %d/%d 법정동 (누적 %d건)", i, len(bjd_list), total)

        return {"total": total, "bjd_count": len(bjd_list)}


def _to_int(v) -> Optional[int]:
    try:    return int(str(v).replace(",", ""))
    except: return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os; os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = AptComplexIdentityCollector()
    # 강남구 테스트
    print(c.collect_by_sgg("11680"))
