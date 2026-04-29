"""
국토교통부 미분양주택현황 수집기
==================================
수집 항목:
  - 시군구별 월별 미분양 세대수    → unsold_house_monthly
  - 준공 후 미분양 (악성 미분양)   → unsold_house_monthly.after_completion

API: data.go.kr → 국토교통부_미분양주택현황조회
     (신청 필요: getUnsolHouseInfo2)

시도코드:
  11=서울, 26=부산, 27=대구, 28=인천, 29=광주, 30=대전, 31=울산
  36=세종, 41=경기, 42=강원, 43=충북, 44=충남, 45=전북, 46=전남
  47=경북, 48=경남, 50=제주
"""

import logging
import os
import sqlite3
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://apis.data.go.kr/1613000/UnsolHouseInfoService2/getUnsolHouseInfo2"

SIDO_CODES = [
    "11", "26", "27", "28", "29", "30", "31",
    "36", "41", "42", "43", "44", "45", "46",
    "47", "48", "50",
]

DDL = """
CREATE TABLE IF NOT EXISTS unsold_house_monthly (
    sgg_cd             TEXT    NOT NULL,
    sgg_nm             TEXT,
    sido_cd            TEXT,
    sido_nm            TEXT,
    base_ym            TEXT    NOT NULL,   -- YYYYMM
    unsold_total       INTEGER,            -- 전체 미분양 세대수
    unsold_after_comp  INTEGER,            -- 준공 후 미분양 (악성)
    unsold_public      INTEGER,            -- 공공분양
    unsold_private     INTEGER,            -- 민간분양
    collected_at       TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sgg_cd, base_ym)
)"""


class UnsoldHouseCollector:
    def __init__(self, api_key: str = "", db_path: str = "realestate.db"):
        self.api_key = api_key or os.getenv("DATA_GO_KR_API_KEY", "")
        self.db_path = db_path
        self.session = requests.Session()
        self._init_table()

    def _init_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(DDL)

    def _fetch_sido(self, sido_cd: str, base_ym: str) -> list[dict]:
        """특정 시도의 특정 월 미분양 현황 조회"""
        if not self.api_key:
            log.warning("DATA_GO_KR_API_KEY 없음 — 미분양 수집 스킵")
            return []
        try:
            resp = self.session.get(BASE_URL, params={
                "serviceKey": self.api_key,
                "numOfRows":  100,
                "pageNo":     1,
                "resultType": "json",
                "landCd":     sido_cd,
                "stdrMt":     base_ym,   # YYYYMM
            }, timeout=30)
            resp.raise_for_status()
            body = resp.json().get("response", {}).get("body", {})
            items = body.get("items", {})
            if not items:
                return []
            rows = items.get("item", [])
            if isinstance(rows, dict):
                rows = [rows]
            return rows
        except Exception as e:
            log.error("미분양 수집 오류 [%s/%s]: %s", sido_cd, base_ym, e)
            return []

    def collect_month(self, base_ym: str) -> int:
        """특정 월 전국 미분양 수집 (시도별 순차 요청)"""
        inserted = 0
        for sido_cd in SIDO_CODES:
            rows = self._fetch_sido(sido_cd, base_ym)
            if not rows:
                time.sleep(0.2)
                continue

            with sqlite3.connect(self.db_path) as conn:
                for r in rows:
                    sgg_cd = str(r.get("sigunguCd", "")).strip()
                    if not sgg_cd:
                        continue
                    try:
                        conn.execute("""
                            INSERT OR REPLACE INTO unsold_house_monthly
                            (sgg_cd, sgg_nm, sido_cd, sido_nm, base_ym,
                             unsold_total, unsold_after_comp, unsold_public, unsold_private)
                            VALUES (?,?,?,?,?,?,?,?,?)
                        """, (
                            sgg_cd,
                            r.get("sigunguNm", ""),
                            sido_cd,
                            r.get("sidoNm", ""),
                            base_ym,
                            _to_int(r.get("unslHouseHold")),
                            _to_int(r.get("aftrCmplUnslHouseHold")),
                            _to_int(r.get("pubcHouseHold")),
                            _to_int(r.get("prvtHouseHold")),
                        ))
                        inserted += 1
                    except Exception:
                        pass
            time.sleep(0.3)

        log.info("unsold_house_monthly [%s]: %d건", base_ym, inserted)
        return inserted

    def collect_range(self, start_ym: str = "202001", end_ym: str = None) -> dict:
        """기간별 미분양 현황 수집"""
        from datetime import datetime

        if end_ym is None:
            end_ym = datetime.now().strftime("%Y%m")

        # YYYYMM 리스트 생성
        def _ym_list(s, e):
            result = []
            y, m = int(s[:4]), int(s[4:])
            ey, em = int(e[:4]), int(e[4:])
            while (y, m) <= (ey, em):
                result.append(f"{y:04d}{m:02d}")
                m += 1
                if m > 12:
                    m = 1
                    y += 1
            return result

        months = _ym_list(start_ym, end_ym)
        total = 0
        for ym in months:
            n = self.collect_month(ym)
            total += n
            log.info("미분양 수집 진행: %s (%d건)", ym, n)

        log.info("미분양 전체 수집 완료: %d건 (%s ~ %s)", total, start_ym, end_ym)
        return {"total": total, "months": len(months)}

    def get_sgg_trend(self, sgg_cd: str) -> list[dict]:
        """시군구별 미분양 추이 조회 (분석용)"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT base_ym, unsold_total, unsold_after_comp
                FROM unsold_house_monthly
                WHERE sgg_cd = ?
                ORDER BY base_ym
            """, (sgg_cd,)).fetchall()
        return [{"ym": r[0], "total": r[1], "after_comp": r[2]} for r in rows]


def _to_int(v) -> Optional[int]:
    try:    return int(str(v).replace(",", ""))
    except: return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os; os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c = UnsoldHouseCollector()
    # 최근 6개월 수집
    from datetime import datetime, timedelta
    from dateutil.relativedelta import relativedelta
    now = datetime.now()
    start = (now - relativedelta(months=6)).strftime("%Y%m")
    print(c.collect_range(start_ym=start))
