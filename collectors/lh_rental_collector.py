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

    def _get_period(self, start_dt: str, end_dt: str) -> list[dict]:
        """LH API 응답: [{dsSch:[]}, {dsList:[], resHeader:[]}] 커스텀 포맷"""
        if not self.api_key:
            log.warning("DATA_GO_KR_API_KEY 없음 — LH임대 수집 스킵")
            return []
        try:
            resp = self.session.get(BASE_URL, params={
                "serviceKey": self.api_key,
                "resultType": "json",
                "PAN_ST_DT":  start_dt,
                "PAN_ED_DT":  end_dt,
            }, timeout=60)
            if resp.status_code != 200:
                log.warning("LH임대 API HTTP %d: %s", resp.status_code, resp.text[:200])
                return []
            data = resp.json()
            if isinstance(data, list):
                for chunk in data:
                    if "dsList" in chunk:
                        return chunk["dsList"] or []
            return []
        except Exception as e:
            log.error("LH임대 API 오류 [%s~%s]: %s", start_dt, end_dt, e)
            return []

    def collect_notices(self, start_ym: str = "202001") -> int:
        from datetime import date
        import calendar
        start_year = int(start_ym[:4])
        start_mon  = int(start_ym[4:6])
        today = date.today()
        rows_all = []
        # 월별로 쪼개서 조회 (전체 범위는 timeout)
        y, m = start_year, start_mon
        while (y, m) <= (today.year, today.month):
            last_day = calendar.monthrange(y, m)[1]
            rows = self._get_period(f"{y}{m:02d}01", f"{y}{m:02d}{last_day:02d}")
            rows_all.extend(rows)
            if m == 12: y, m = y+1, 1
            else: m += 1
            time.sleep(0.3)
        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            for r in rows_all:
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO lh_rental
                        (pblanc_no, house_nm, house_secd_nm, sgg_cd, sgg_nm,
                         supply_count, pblanc_de, rcept_bgnde, rcept_endde,
                         mvn_prearnge_ym, rent_type_nm, bsns_mby_nm, hssply_adres)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        r.get("PAN_NO") or r.get("pblancNo"),
                        r.get("AIS_TP_CD_NM") or r.get("houseNm"),
                        r.get("RENT_GBN_NM") or r.get("houseSecdNm"),
                        r.get("CNP_CD") or r.get("sggCd"),
                        r.get("CNP_CD_NM") or r.get("sggNm"),
                        _to_int(r.get("TOT_SUPLY_HSHLDCO") or r.get("totSuplyHshldco")),
                        r.get("PAN_DT") or r.get("pblancDe"),
                        r.get("RCRIT_PD_BEG_DT") or r.get("rceptBgnde"),
                        r.get("RCRIT_PD_END_DT") or r.get("rceptEndde"),
                        r.get("MVN_PREARNGE_YM") or r.get("mvnPrearngeYm"),
                        r.get("RENT_GBN") or r.get("rentTypeNm"),
                        r.get("BSNS_MBY_NM") or r.get("bsnsMbyNm"),
                        r.get("HSSPLY_ADRES") or r.get("hssplyAdres"),
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
