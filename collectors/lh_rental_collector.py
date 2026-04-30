"""
LH 공공임대주택 공급정보 수집기
==================================
수집 항목:
  - LH 임대주택 단지정보 → lh_rental

API 키: DATA_GO_KR_API_KEY
엔드포인트: https://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"

DDL = """
CREATE TABLE IF NOT EXISTS lh_rental (
    pblanc_no       TEXT PRIMARY KEY,
    house_nm        TEXT,
    house_secd_nm   TEXT,   -- 임대유형(영구/50년/국민 등)
    sgg_cd          TEXT,
    sgg_nm          TEXT,
    supply_count    INTEGER,
    pblanc_de       TEXT,   -- 공고일
    rcept_bgnde     TEXT,   -- 접수 시작일
    rcept_endde     TEXT,   -- 접수 종료일
    mvn_prearnge_ym TEXT,   -- 입주예정월
    rent_type_nm    TEXT,   -- 임대료 유형
    bsns_mby_nm     TEXT,   -- 사업주체명
    hssply_adres    TEXT,   -- 공급위치
    collected_at    TEXT DEFAULT (datetime('now'))
)"""


class LhRentalCollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key = api_key or os.getenv("DATA_GO_KR_API_KEY", "")
        self.db_path = db_path
        self.session = requests.Session()
        self._init_table()

    def _init_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL)

    def _get_pages(self, extra_params: dict = None) -> list[dict]:
        if not self.api_key:
            log.warning("DATA_GO_KR_API_KEY 없음 — LH임대 수집 스킵")
            return []
        p = {
            "serviceKey": self.api_key,
            "numOfRows":  100,
            "pageNo":     1,
            "resultType": "json",
            **(extra_params or {}),
        }
        rows = []
        while True:
            try:
                resp = self.session.get(BASE_URL, params=p, timeout=30)
                if resp.status_code != 200:
                    log.warning("LH임대 API HTTP %d: %s", resp.status_code, resp.text[:200])
                    break
                resp.raise_for_status()
                body = resp.json().get("response", {}).get("body", {})
                items = body.get("items", {})
                batch = items.get("item", []) if isinstance(items, dict) else []
                if isinstance(batch, dict):
                    batch = [batch]
                rows.extend(batch)
                total = int(body.get("totalCount", 0))
                if len(rows) >= total or not batch:
                    break
                p["pageNo"] += 1
                time.sleep(0.3)
            except Exception as e:
                log.error("LH임대 API 오류: %s", e)
                break
        return rows

    def collect_notices(self, start_ym: str = "202001") -> int:
        rows = self._get_pages({"startRcritPblancDe": start_ym + "01"})
        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            for r in rows:
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO lh_rental
                        (pblanc_no, house_nm, house_secd_nm, sgg_cd, sgg_nm,
                         supply_count, pblanc_de, rcept_bgnde, rcept_endde,
                         mvn_prearnge_ym, rent_type_nm, bsns_mby_nm, hssply_adres)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        r.get("pblancNo") or r.get("PBLANC_NO"),
                        r.get("houseNm") or r.get("HOUSE_NM"),
                        r.get("houseSecdNm") or r.get("HOUSE_SECD_NM"),
                        r.get("sggCd") or r.get("SGG_CD"),
                        r.get("sggNm") or r.get("SGG_NM"),
                        _to_int(r.get("totSuplyHshldco") or r.get("TOT_SUPLY_HSHLDCO")),
                        r.get("pblancDe") or r.get("PBLANC_DE"),
                        r.get("rceptBgnde") or r.get("RCEPT_BGNDE"),
                        r.get("rceptEndde") or r.get("RCEPT_ENDDE"),
                        r.get("mvnPrearngeYm") or r.get("MVN_PREARNGE_YM"),
                        r.get("rentTypeNm") or r.get("RENT_TYPE_NM"),
                        r.get("bsnsMbyNm") or r.get("BSNS_MBY_NM"),
                        r.get("hssplyAdres") or r.get("HSSPLY_ADRES"),
                    ))
                    inserted += 1
                except Exception as e:
                    log.debug("LH임대 저장 실패: %s", e)
        log.info("lh_rental 저장: %d건", inserted)
        return inserted

    def collect_all(self, start_ym: str = "202001") -> dict:
        return {"notices": self.collect_notices(start_ym)}


def _to_int(v) -> Optional[int]:
    try:    return int(str(v).replace(",", ""))
    except: return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os; os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = LhRentalCollector()
    print(c.collect_all())
