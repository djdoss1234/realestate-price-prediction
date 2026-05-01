"""
부동산 가격 예측 ML 파이프라인 v4
================================
realestate.db (국토부 실거래가) 기반
- 매매 모델: 아파트 + 연립다세대 + 오피스텔 + 단독다가구
- 전세 모델: 아파트 + 연립다세대 + 오피스텔 + 단독다가구 (monthlyRent=0)
- 월세 모델: 아파트 + 연립다세대 + 오피스텔 + 단독다가구 (monthlyRent>0)

단계:
  1. DB 로딩 및 전처리
  2. 피처 엔지니어링 (건축연수, 층비율, rolling 평균가, 물건유형 등)
  3. LightGBM K-Fold 학습
  4. SHAP 피처 중요도 시각화 (매매 모델만)
  5. 저평가 단지 탐지 → undervalued_full.csv (물건유형·거래유형 포함)
"""

import sqlite3
import pandas as pd
import numpy as np
import warnings
import os
import requests
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

warnings.filterwarnings("ignore")


def _load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"\''))

_load_dotenv()


# ============================================================
# SECTION 1. 상수 정의
# ============================================================

BRAND_MAP = {
    "래미안": 3, "자이": 3, "힐스테이트": 3, "푸르지오": 3,
    "아크로": 3, "디에이치": 3, "르엘": 3,
    "롯데캐슬": 2, "e편한세상": 2, "아이파크": 2, "SK뷰": 2,
    "더샵": 2, "위브": 2, "리슈빌": 2, "한화포레나": 2,
    "호반베르디움": 2, "중흥S-클래스": 2,
}

AREA_BINS   = [0, 40, 60, 85, 115, 500]
AREA_LABELS = ["소형", "중소형", "중형", "대형", "초대형"]

PROPERTY_TYPE_MAP = {0: "아파트", 1: "연립다세대", 2: "오피스텔", 3: "단독다가구"}
PROPERTY_TYPE_MAP_INV = {v: k for k, v in PROPERTY_TYPE_MAP.items()}

# 매매 모델 피처 (물건유형 포함)
_MACRO = [
    "기준금리", "대출금리", "금리변화_3개월", "금리변화_6개월",
    "M2잔액", "M2증가율_3개월", "가계대출잔액", "경기선행지수",
    "소비자물가지수", "소비자물가상승률", "소비자심리지수",
]
_SGG = ["시도_인구수", "시군구_학원수"]

TRADE_FEATURE_COLS = [
    "전용면적", "평형", "층", "건축연수", "층비율", "브랜드_프리미엄",
    "거래년도", "거래월", "거래분기", "이사시즌여부", "명절직전여부",
    "지역코드_num",
    "단지_직전3개월가", "단지_직전6개월가", "단지_직전12개월가",
    "가격변화율_3개월", "가격변화율_6개월", "단지_거래량_3개월",
    "시군구_직전3개월가", "시군구_직전6개월가",
    "전세가율", "물건유형",
    *_MACRO, *_SGG,
]

JEONSE_FEATURE_COLS = [
    "전용면적", "평형", "층", "건축연수", "층비율", "브랜드_프리미엄",
    "거래년도", "거래월", "거래분기", "이사시즌여부", "명절직전여부",
    "지역코드_num",
    "단지_직전3개월가", "단지_직전6개월가", "단지_직전12개월가",
    "가격변화율_3개월", "가격변화율_6개월", "단지_거래량_3개월",
    "시군구_직전3개월가", "시군구_직전6개월가",
    "물건유형",
    *_MACRO, *_SGG,
]

WOLSE_FEATURE_COLS = [
    "전용면적", "평형", "층", "건축연수", "층비율", "브랜드_프리미엄",
    "거래년도", "거래월", "거래분기", "이사시즌여부", "명절직전여부",
    "지역코드_num",
    "단지_직전3개월가", "단지_직전6개월가", "단지_직전12개월가",
    "가격변화율_3개월", "가격변화율_6개월", "단지_거래량_3개월",
    "시군구_직전3개월가", "시군구_직전6개월가",
    "보증금", "물건유형",
    *_MACRO, *_SGG,
]

FEATURE_COLS = TRADE_FEATURE_COLS  # 하위호환

RATE_COLS = [
    "기준금리", "대출금리", "금리변화_3개월", "금리변화_6개월",
    "M2잔액", "M2증가율_3개월", "가계대출잔액", "경기선행지수",
    "소비자물가지수", "소비자물가상승률", "소비자심리지수",
]

SGG_FEATURE_COLS = ["시도_인구수", "시군구_학원수"]


# ============================================================
# SECTION 1-B. 한국은행 ECOS 거시지표 로더
# ============================================================

def load_macro_from_db(db_path: str = "realestate.db", start_ym: str = "202201") -> pd.DataFrame:
    """ecos_macro 테이블에서 거시지표 로드 (API 없이 사용 가능)."""
    try:
        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql(
                "SELECT * FROM ecos_macro WHERE ym >= ? ORDER BY ym",
                conn, params=(start_ym,)
            )
        if df.empty:
            return pd.DataFrame()
        rename = {
            "base_rate":               "기준금리",
            "mortgage_rate":           "대출금리",
            "m2_trillion":             "M2잔액",
            "m2_growth_3m":            "M2증가율_3개월",
            "leading_index":           "경기선행지수",
            "household_loan_trillion": "가계대출잔액",
            "rate_chg_3m":             "금리변화_3개월",
            "rate_chg_6m":             "금리변화_6개월",
            "cpi":                     "소비자물가지수",
            "cpi_growth_12m":          "소비자물가상승률",
            "ccsi":                    "소비자심리지수",
        }
        df = df.rename(columns=rename)
        loaded = [c for c in RATE_COLS if c in df.columns]
        print(f"  거시지표 DB 로드: {len(df)}개월 | {loaded}")
        return df[["ym"] + loaded]
    except Exception as e:
        print(f"  [경고] ecos_macro DB 로드 실패: {e}")
        return pd.DataFrame()


def fetch_macro_rates(start_ym: str = "202201", db_path: str = "realestate.db") -> pd.DataFrame:
    """거시지표 로드: ecos_macro DB 우선 → ECOS API fallback.

    Returns:
        ym | 기준금리 | 대출금리 | 금리변화_3개월 | 금리변화_6개월
           | M2잔액 | M2증가율_3개월 | 가계대출잔액 | 경기선행지수
           | 소비자물가지수 | 소비자물가상승률 | 소비자심리지수
    """
    db_df = load_macro_from_db(db_path, start_ym)
    if not db_df.empty:
        return db_df

    api_key = os.getenv("ECOS_API_KEY", "")
    if not api_key:
        print("  [경고] ECOS_API_KEY 없음 — 거시지표 피처 NaN으로 채움")
        return pd.DataFrame()

    end_ym = datetime.now().strftime("%Y%m")
    now = datetime.now()

    def _fetch_m(stat_code: str, item_code: str, col: str) -> pd.DataFrame:
        """월별(M) 데이터 조회"""
        url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}"
               f"/json/kr/1/200/{stat_code}/M/{start_ym}/{end_ym}/{item_code}")
        try:
            rows = requests.get(url, timeout=15).json().get("StatisticSearch", {}).get("row", [])
            return pd.DataFrame([(r["TIME"], float(r["DATA_VALUE"])) for r in rows], columns=["ym", col])
        except Exception as e:
            print(f"  [경고] ECOS {col} 조회 실패: {e}")
            return pd.DataFrame()

    def _fetch_q(stat_code: str, item_code: str, col: str) -> pd.DataFrame:
        """분기(Q) 데이터 조회 후 월별로 forward-fill 변환"""
        start_q = f"{start_ym[:4]}Q1"
        end_q   = f"{now.year}Q{(now.month - 1) // 3 + 1}"
        url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}"
               f"/json/kr/1/200/{stat_code}/Q/{start_q}/{end_q}/{item_code}")
        try:
            rows = requests.get(url, timeout=15).json().get("StatisticSearch", {}).get("row", [])
            if not rows:
                return pd.DataFrame()
            # YYYYQn → 분기 시작월 YYYYMM으로 변환
            q_to_start = {"Q1": "01", "Q2": "04", "Q3": "07", "Q4": "10"}
            quarterly = pd.DataFrame(
                [(r["TIME"][:4] + q_to_start[r["TIME"][4:]], float(r["DATA_VALUE"])) for r in rows],
                columns=["ym", col],
            )
            # 분기→월 forward-fill (12개월 범위 생성 후 merge)
            all_months = pd.DataFrame({"ym": pd.date_range(
                start=f"{start_ym[:4]}-{start_ym[4:]}-01",
                end=f"{now.year}-{now.month:02d}-01", freq="MS"
            ).strftime("%Y%m")})
            quarterly["ym"] = quarterly["ym"].astype(str)
            merged = all_months.merge(quarterly, on="ym", how="left")
            merged[col] = merged[col].ffill()
            return merged
        except Exception as e:
            print(f"  [경고] ECOS {col}(분기) 조회 실패: {e}")
            return pd.DataFrame()

    base   = _fetch_m("722Y001", "0101000",    "기준금리")
    mort   = _fetch_m("121Y006", "BECBLA0302", "대출금리")
    m2     = _fetch_m("161Y006", "BBHA00",     "M2잔액")
    lead   = _fetch_m("901Y067", "I16A",       "경기선행지수")
    hloan  = _fetch_q("151Y001", "1100000",    "가계대출잔액")

    if base.empty:
        return pd.DataFrame()

    rates = base
    for df in [mort, m2, lead, hloan]:
        if not df.empty:
            rates = rates.merge(df, on="ym", how="left")

    rates = rates.sort_values("ym").reset_index(drop=True)
    rates["금리변화_3개월"] = rates["기준금리"].diff(3).round(4)
    rates["금리변화_6개월"] = rates["기준금리"].diff(6).round(4)

    if "M2잔액" in rates.columns:
        # 단위: 십억원 → 조원 (가독성), 3개월 전 대비 증가율(%)
        rates["M2잔액"]        = (rates["M2잔액"] / 1_000).round(1)
        rates["M2증가율_3개월"] = rates["M2잔액"].pct_change(3).mul(100).round(4)
    if "가계대출잔액" in rates.columns:
        rates["가계대출잔액"] = (rates["가계대출잔액"] / 1_000).round(1)  # 십억→조원

    loaded = [c for c in RATE_COLS if c in rates.columns]
    print(f"  거시지표 로드: {len(rates)}개월 ({rates['ym'].iloc[0]}~{rates['ym'].iloc[-1]}) | {loaded}")
    return rates


# ============================================================
# SECTION 2. DB 로더
# ============================================================

class DBLoader:
    """realestate.db에서 각 테이블 로딩"""

    def __init__(self, db_path: str = "realestate.db"):
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"DB 파일 없음: {db_path}")
        self.db_path = db_path

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _table_exists(self, table: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            )
            return cur.fetchone() is not None

    def table_stats(self) -> None:
        with self._conn() as conn:
            try:
                stats = pd.read_sql("""
                    SELECT table_name,
                           SUM(row_count)  AS 총건수,
                           MIN(year_month) AS 시작월,
                           MAX(year_month) AS 종료월
                    FROM collection_log WHERE status='OK'
                    GROUP BY table_name ORDER BY table_name
                """, conn)
                print(stats.to_string(index=False))
            except Exception as e:
                print(f"  stats 조회 실패: {e}")

    def load_trade(self, limit: int = None, start_ym: str = None) -> pd.DataFrame:
        """apt_trade 로딩"""
        cond = ("WHERE dealAmount > 0 AND floor != '' AND buildYear != '' "
                "AND excluUseAr != '' AND (cdealType IS NULL OR cdealType != 'O')")
        if start_ym:
            yr, mo = start_ym[:4], int(start_ym[4:])
            cond += (f" AND (CAST(dealYear AS INT) > {yr} OR "
                     f"(CAST(dealYear AS INT) = {yr} AND CAST(dealMonth AS INT) >= {mo}))")
        q = f"""
            SELECT aptNm, buildYear, dealAmount,
                   dealYear, dealMonth, dealDay,
                   excluUseAr, floor, sggCd, umdNm,
                   estateAgentSggNm, dealingGbn
            FROM apt_trade {cond}
            {"LIMIT " + str(limit) if limit else ""}
        """
        with self._conn() as conn:
            df = pd.read_sql(q, conn)
        print(f"  apt_trade 로드: {len(df):,}건")
        return df

    def load_villa_trade(self, limit: int = None, start_ym: str = None) -> pd.DataFrame:
        """villa_trade 로딩 (mhouseNm → aptNm 통일)"""
        if not self._table_exists("villa_trade"):
            print("  villa_trade 없음 (스킵)")
            return pd.DataFrame()
        cond = ("WHERE dealAmount > 0 AND floor != '' AND buildYear != '' "
                "AND excluUseAr != ''")
        if start_ym:
            yr, mo = start_ym[:4], int(start_ym[4:])
            cond += (f" AND (CAST(dealYear AS INT) > {yr} OR "
                     f"(CAST(dealYear AS INT) = {yr} AND CAST(dealMonth AS INT) >= {mo}))")
        q = f"""
            SELECT mhouseNm AS aptNm, buildYear, dealAmount,
                   dealYear, dealMonth, dealDay,
                   excluUseAr, floor, sggCd, umdNm,
                   estateAgentSggNm, dealingGbn
            FROM villa_trade {cond}
            {"LIMIT " + str(limit) if limit else ""}
        """
        with self._conn() as conn:
            df = pd.read_sql(q, conn)
        print(f"  villa_trade 로드: {len(df):,}건")
        return df

    def load_rent(self, limit: int = None) -> pd.DataFrame:
        """apt_rent 전월세 로딩"""
        q = f"""
            SELECT aptNm, buildYear, deposit, monthlyRent,
                   dealYear, dealMonth, excluUseAr, sggCd, umdNm
            FROM apt_rent
            WHERE deposit > 0 AND excluUseAr != ''
            {"LIMIT " + str(limit) if limit else ""}
        """
        with self._conn() as conn:
            df = pd.read_sql(q, conn)
        print(f"  apt_rent 로드: {len(df):,}건")
        return df

    def load_villa_rent(self, limit: int = None) -> pd.DataFrame:
        """villa_rent 전월세 로딩 (mhouseNm → aptNm 통일)"""
        if not self._table_exists("villa_rent"):
            print("  villa_rent 없음 (스킵)")
            return pd.DataFrame()
        q = f"""
            SELECT mhouseNm AS aptNm, buildYear, deposit, monthlyRent,
                   dealYear, dealMonth, excluUseAr, sggCd, umdNm
            FROM villa_rent
            WHERE deposit > 0 AND excluUseAr != ''
            {"LIMIT " + str(limit) if limit else ""}
        """
        with self._conn() as conn:
            df = pd.read_sql(q, conn)
        print(f"  villa_rent 로드: {len(df):,}건")
        return df

    def load_officetel_trade(self, limit: int = None, start_ym: str = None) -> pd.DataFrame:
        """officetel_trade 로딩 (offiNm → aptNm 통일)"""
        if not self._table_exists("officetel_trade"):
            print("  officetel_trade 없음 (스킵)")
            return pd.DataFrame()
        cond = "WHERE dealAmount > 0 AND floor != '' AND buildYear != '' AND excluUseAr != ''"
        if start_ym:
            yr, mo = start_ym[:4], int(start_ym[4:])
            cond += (f" AND (CAST(dealYear AS INT) > {yr} OR "
                     f"(CAST(dealYear AS INT) = {yr} AND CAST(dealMonth AS INT) >= {mo}))")
        q = f"""
            SELECT offiNm AS aptNm, buildYear, dealAmount,
                   dealYear, dealMonth, dealDay,
                   excluUseAr, floor, sggCd, umdNm,
                   estateAgentSggNm, dealingGbn
            FROM officetel_trade {cond}
            {"LIMIT " + str(limit) if limit else ""}
        """
        with self._conn() as conn:
            df = pd.read_sql(q, conn)
        print(f"  officetel_trade 로드: {len(df):,}건")
        return df

    def load_officetel_rent(self, limit: int = None) -> pd.DataFrame:
        """officetel_rent 전월세 로딩 (offiNm → aptNm 통일)"""
        if not self._table_exists("officetel_rent"):
            print("  officetel_rent 없음 (스킵)")
            return pd.DataFrame()
        q = f"""
            SELECT offiNm AS aptNm, buildYear, deposit, monthlyRent,
                   dealYear, dealMonth, excluUseAr, floor, sggCd, umdNm
            FROM officetel_rent
            WHERE deposit > 0 AND excluUseAr != ''
            {"LIMIT " + str(limit) if limit else ""}
        """
        with self._conn() as conn:
            df = pd.read_sql(q, conn)
        print(f"  officetel_rent 로드: {len(df):,}건")
        return df

    def load_house_trade(self, limit: int = None, start_ym: str = None) -> pd.DataFrame:
        """house_trade 로딩 (totalFloorAr→excluUseAr, 읍면동 기반 단지명)"""
        if not self._table_exists("house_trade"):
            print("  house_trade 없음 (스킵)")
            return pd.DataFrame()
        cond = "WHERE dealAmount > 0 AND buildYear != '' AND totalFloorAr != ''"
        if start_ym:
            yr, mo = start_ym[:4], int(start_ym[4:])
            cond += (f" AND (CAST(dealYear AS INT) > {yr} OR "
                     f"(CAST(dealYear AS INT) = {yr} AND CAST(dealMonth AS INT) >= {mo}))")
        q = f"""
            SELECT (sggCd || '_' || umdNm) AS aptNm,
                   buildYear, dealAmount,
                   dealYear, dealMonth, dealDay,
                   totalFloorAr AS excluUseAr,
                   NULL AS floor,
                   sggCd, umdNm,
                   '' AS estateAgentSggNm,
                   NULL AS dealingGbn
            FROM house_trade {cond}
            {"LIMIT " + str(limit) if limit else ""}
        """
        with self._conn() as conn:
            df = pd.read_sql(q, conn)
        print(f"  house_trade 로드: {len(df):,}건")
        return df

    def load_house_rent(self, limit: int = None) -> pd.DataFrame:
        """house_rent 전월세 로딩 (totalFloorAr→excluUseAr, 읍면동 기반 단지명)"""
        if not self._table_exists("house_rent"):
            print("  house_rent 없음 (스킵)")
            return pd.DataFrame()
        q = f"""
            SELECT (sggCd || '_' || umdNm) AS aptNm,
                   buildYear, deposit, monthlyRent,
                   dealYear, dealMonth,
                   totalFloorAr AS excluUseAr,
                   NULL AS floor,
                   sggCd, umdNm
            FROM house_rent
            WHERE deposit > 0 AND totalFloorAr != ''
            {"LIMIT " + str(limit) if limit else ""}
        """
        with self._conn() as conn:
            df = pd.read_sql(q, conn)
        print(f"  house_rent 로드: {len(df):,}건")
        return df

    def load_sgg_features(self) -> pd.DataFrame:
        """시도 인구수(kosis_population) + 시군구 학원수(academy_info) 로드.

        Returns DataFrame with columns:
            sido_cd (2자리) | 시도_인구수
            sgg_nm          | 시군구_학원수
        """
        with self._conn() as conn:
            # 시도 인구수 — 최신 연도
            pop = pd.read_sql("""
                SELECT sgg_cd AS sido_cd, population AS 시도_인구수
                FROM kosis_population
                WHERE year = (SELECT MAX(year) FROM kosis_population)
                  AND LENGTH(sgg_cd) = 2
                  AND sgg_cd != '00'
            """, conn)

            # 시군구 학원 수 — sgg_nm(시군구명) 기준 집계
            aca = pd.read_sql("""
                SELECT sgg_nm AS sgg_nm_raw, COUNT(*) AS 시군구_학원수
                FROM academy_info
                WHERE sgg_nm IS NOT NULL AND sgg_nm != ''
                  AND status = '개원'
                GROUP BY sgg_nm
            """, conn)

        return pop, aca


# ============================================================
# SECTION 3. 피처 엔지니어링
# ============================================================

class FeatureEngineer:
    """원시 데이터 → ML 피처 변환"""

    def __init__(self):
        self.current_year = 2026

    def clean_trade(self, df: pd.DataFrame) -> pd.DataFrame:
        """매매 원시 데이터 정제 (apt_trade / villa_trade 공통)"""
        df = df.copy()

        df["전용면적"]     = pd.to_numeric(df["excluUseAr"], errors="coerce")
        df["층"]           = pd.to_numeric(df.get("floor", pd.Series(dtype=str)).astype(str).str.strip(), errors="coerce")
        df["건축년도"]     = pd.to_numeric(df["buildYear"], errors="coerce")
        df["지역코드_num"] = pd.to_numeric(df["sggCd"], errors="coerce")

        valid = (
            df["전용면적"].between(10, 500) &
            df["건축년도"].between(1960, 2026) &
            df["dealAmount"].between(1000, 2_000_000)
        )
        if "층" in df.columns and df["층"].notna().any():
            valid = valid & (df["층"].between(1, 100) | df["층"].isna())
        df = df[valid].copy()
        df["층"] = df["층"].fillna(1)  # 단독다가구 등 floor 없는 경우 기본값

        df["건축연수"]     = self.current_year - df["건축년도"]
        df["평형"]         = df["전용면적"] / 3.305785
        df["거래년도"]     = pd.to_numeric(df["dealYear"], errors="coerce").astype("Int64")
        df["거래월"]       = pd.to_numeric(df["dealMonth"], errors="coerce").astype("Int64")
        df["거래일"]       = pd.to_datetime(
            df["dealYear"].astype(str) + df["dealMonth"].astype(str).str.zfill(2) + "01",
            format="%Y%m%d", errors="coerce"
        )
        df["ym"]           = df["dealYear"].astype(str) + df["dealMonth"].astype(str).str.zfill(2)
        df["거래분기"]     = ((df["거래월"] - 1) // 3 + 1)
        df["이사시즌여부"] = df["거래월"].isin([2, 3, 8, 9]).astype(int)
        df["명절직전여부"] = df["거래월"].isin([1, 9]).astype(int)

        df = df.rename(columns={
            "aptNm":            "단지명",
            "umdNm":            "읍면동",
            "estateAgentSggNm": "지역명",
            "dealAmount":       "거래금액",
        })
        df["면적구간"] = pd.cut(df["전용면적"], bins=AREA_BINS, labels=AREA_LABELS)

        return df.dropna(subset=["거래일", "전용면적", "건축년도"]).reset_index(drop=True)

    def clean_rent(self, df: pd.DataFrame) -> pd.DataFrame:
        """전월세 원시 데이터 정제 (apt_rent / villa_rent 공통)"""
        df = df.copy()

        df["전용면적"]     = pd.to_numeric(df["excluUseAr"], errors="coerce")
        df["층"]           = pd.to_numeric(df.get("floor", pd.Series(dtype=str)).astype(str).str.strip(), errors="coerce")
        df["건축년도"]     = pd.to_numeric(df["buildYear"], errors="coerce")
        df["지역코드_num"] = pd.to_numeric(df["sggCd"], errors="coerce")
        df["보증금"]       = pd.to_numeric(df["deposit"], errors="coerce")
        df["월세"]         = pd.to_numeric(df["monthlyRent"], errors="coerce").fillna(0)

        valid = (
            df["전용면적"].between(10, 500) &
            df["건축년도"].between(1960, 2026) &
            df["보증금"].between(100, 500_000)
        )
        if "층" in df.columns and df["층"].notna().any():
            valid = valid & (df["층"].between(1, 100) | df["층"].isna())
        df = df[valid].copy()

        df["건축연수"]     = self.current_year - df["건축년도"]
        df["평형"]         = df["전용면적"] / 3.305785
        df["거래년도"]     = pd.to_numeric(df["dealYear"], errors="coerce").astype("Int64")
        df["거래월"]       = pd.to_numeric(df["dealMonth"], errors="coerce").astype("Int64")
        df["거래일"]       = pd.to_datetime(
            df["dealYear"].astype(str) + df["dealMonth"].astype(str).str.zfill(2) + "01",
            format="%Y%m%d", errors="coerce"
        )
        df["ym"]           = df["dealYear"].astype(str) + df["dealMonth"].astype(str).str.zfill(2)
        df["거래분기"]     = ((df["거래월"] - 1) // 3 + 1)
        df["이사시즌여부"] = df["거래월"].isin([2, 3, 8, 9]).astype(int)
        df["명절직전여부"] = df["거래월"].isin([1, 9]).astype(int)
        df["거래금액"]     = df["보증금"]  # rolling 함수 호환용

        df = df.rename(columns={"aptNm": "단지명", "umdNm": "읍면동"})
        df["면적구간"] = pd.cut(df["전용면적"], bins=AREA_BINS, labels=AREA_LABELS)
        if "층" not in df.columns:
            df["층"] = 1

        return df.dropna(subset=["거래일", "전용면적", "건축년도", "보증금"]).reset_index(drop=True)

    def build_brand_feature(self, df: pd.DataFrame) -> pd.DataFrame:
        def _score(name: str) -> int:
            for brand, score in BRAND_MAP.items():
                if brand in str(name):
                    return score
            return 1
        df = df.copy()
        df["브랜드_프리미엄"] = df["단지명"].apply(_score)
        return df

    def build_max_floor(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        max_floor = df.groupby("단지명")["층"].transform("max")
        df["최고층_단지"] = max_floor
        df["층비율"] = df["층"] / max_floor.clip(lower=1)
        return df

    def build_apt_rolling(self, df: pd.DataFrame) -> pd.DataFrame:
        """단지 + 면적구간 기준 rolling 평균가 / 거래량 (거래금액 기준)"""
        print("  단지별 rolling 피처 계산 중 (시간 소요)...")
        df = df.copy().sort_values("거래일").reset_index(drop=True)

        grp = df.groupby(["단지명", "면적구간"])["거래금액"]

        for window, label in [(3, "3개월"), (6, "6개월"), (12, "12개월")]:
            df[f"단지_직전{label}가"] = grp.transform(
                lambda x, w=window: x.shift(1).rolling(w, min_periods=1).mean()
            )

        base3 = df["단지_직전3개월가"].replace(0, np.nan)
        base6 = df["단지_직전6개월가"].replace(0, np.nan)
        df["가격변화율_3개월"] = (df["거래금액"] - base3) / base3 * 100
        df["가격변화율_6개월"] = (df["거래금액"] - base6) / base6 * 100

        df["단지_거래량_3개월"] = grp.transform(
            lambda x: x.shift(1).rolling(3, min_periods=1).count()
        )
        return df

    def build_sgg_rolling(self, df: pd.DataFrame) -> pd.DataFrame:
        """시군구 월간 rolling 평균가 (거래금액 기준)"""
        print("  시군구별 rolling 피처 계산 중...")
        monthly = (
            df.groupby(["sggCd", "ym"])["거래금액"]
            .mean()
            .reset_index(name="sgg_avg")
            .sort_values(["sggCd", "ym"])
        )
        for w, label in [(3, "3개월"), (6, "6개월")]:
            monthly[f"시군구_직전{label}가"] = (
                monthly.groupby("sggCd")["sgg_avg"]
                .transform(lambda x, ww=w: x.shift(1).rolling(ww, min_periods=1).mean())
            )
        merge_cols = ["sggCd", "ym", "시군구_직전3개월가", "시군구_직전6개월가"]
        df = df.merge(monthly[merge_cols], on=["sggCd", "ym"], how="left")
        return df

    def build_rent_ratio(self, trade_df: pd.DataFrame, rent_df: pd.DataFrame) -> pd.DataFrame:
        """전세가율 계산 (apt+villa rent 통합 사용)"""
        print("  전세가율 계산 중...")
        jeonse = rent_df[rent_df["monthlyRent"] == 0].copy()
        jeonse["excluUseAr_f"] = pd.to_numeric(jeonse["excluUseAr"], errors="coerce")
        jeonse = jeonse.dropna(subset=["excluUseAr_f", "deposit"])
        jeonse["면적구간"] = pd.cut(jeonse["excluUseAr_f"], bins=AREA_BINS, labels=AREA_LABELS)
        jeonse["ym"] = (jeonse["dealYear"].astype(str) +
                        jeonse["dealMonth"].astype(str).str.zfill(2))
        jeonse = jeonse.rename(columns={"aptNm": "단지명"})

        monthly_dep = (
            jeonse.groupby(["단지명", "면적구간", "ym"])["deposit"]
            .mean().reset_index(name="avg_deposit")
        )
        trade_df = trade_df.merge(monthly_dep, on=["단지명", "면적구간", "ym"], how="left")

        overall_dep = (
            jeonse.groupby(["단지명", "면적구간"])["deposit"]
            .mean().reset_index(name="overall_deposit")
        )
        trade_df = trade_df.merge(overall_dep, on=["단지명", "면적구간"], how="left")
        trade_df["avg_deposit"] = trade_df["avg_deposit"].fillna(trade_df["overall_deposit"])
        trade_df["전세가율"] = (trade_df["avg_deposit"] / trade_df["거래금액"] * 100).clip(0, 200)

        covered = trade_df["전세가율"].notna().sum()
        total   = len(trade_df)
        print(f"  전세가율 커버리지: {covered:,}/{total:,}건 ({covered/total*100:.1f}%)")
        trade_df.drop(columns=["avg_deposit", "overall_deposit"], errors="ignore", inplace=True)
        return trade_df

    def build_all_trade(self, trade_df: pd.DataFrame,
                        rent_df: Optional[pd.DataFrame] = None,
                        rates_df: Optional[pd.DataFrame] = None,
                        pop_df: Optional[pd.DataFrame] = None,
                        aca_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """매매 데이터 전체 피처 엔지니어링 (apt+villa 통합)"""
        print("\n[1/6] 데이터 정제...")
        df = self.clean_trade(trade_df)
        print(f"  정제 후: {len(df):,}건")
        print("[2/6] 기본 피처 생성...")
        df = self.build_brand_feature(df)
        df = self.build_max_floor(df)
        print("[3/6] Rolling 가격 피처 생성...")
        df = self.build_apt_rolling(df)
        df = self.build_sgg_rolling(df)
        print("[4/6] 전세가율 계산...")
        if rent_df is not None and not rent_df.empty:
            df = self.build_rent_ratio(df, rent_df)
        else:
            df["전세가율"] = np.nan
        print("[5/6] 금리 피처 병합...")
        df = self.build_rate_feature(df, rates_df)
        print("[6/6] 시도·시군구 외부 피처 병합...")
        df = self.build_sgg_external(df, pop_df or pd.DataFrame(), aca_df or pd.DataFrame())
        print("  피처 엔지니어링 완료.")
        return df

    def build_all_jeonse(self, rent_df: pd.DataFrame,
                         rates_df: Optional[pd.DataFrame] = None,
                         pop_df: Optional[pd.DataFrame] = None,
                         aca_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """전세 데이터 전체 피처 엔지니어링"""
        print("\n[1/6] 데이터 정제...")
        df = self.clean_rent(rent_df)
        df = df[df["월세"] == 0].copy()
        print(f"  정제 후 전세: {len(df):,}건")
        print("[2/6] 기본 피처 생성...")
        df = self.build_brand_feature(df)
        df = self.build_max_floor(df)
        print("[3/6] Rolling 보증금 피처 생성...")
        df = self.build_apt_rolling(df)
        df = self.build_sgg_rolling(df)
        print("[4/6] 금리 피처 병합...")
        df = self.build_rate_feature(df, rates_df)
        print("[5/6] 시도·시군구 외부 피처 병합...")
        df = self.build_sgg_external(df, pop_df or pd.DataFrame(), aca_df or pd.DataFrame())
        print("[6/6] 피처 엔지니어링 완료.")
        return df

    def build_all_wolse(self, rent_df: pd.DataFrame,
                        rates_df: Optional[pd.DataFrame] = None,
                        pop_df: Optional[pd.DataFrame] = None,
                        aca_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """월세 데이터 전체 피처 엔지니어링"""
        print("\n[1/6] 데이터 정제...")
        df = self.clean_rent(rent_df)
        df = df[df["월세"] > 0].copy()
        df["거래금액"] = df["월세"]
        print(f"  정제 후 월세: {len(df):,}건")
        print("[2/6] 기본 피처 생성...")
        df = self.build_brand_feature(df)
        df = self.build_max_floor(df)
        print("[3/6] Rolling 월세 피처 생성...")
        df = self.build_apt_rolling(df)
        df = self.build_sgg_rolling(df)
        print("[4/6] 금리 피처 병합...")
        df = self.build_rate_feature(df, rates_df)
        print("[5/6] 시도·시군구 외부 피처 병합...")
        df = self.build_sgg_external(df, pop_df or pd.DataFrame(), aca_df or pd.DataFrame())
        print("[6/6] 피처 엔지니어링 완료.")
        return df

    def build_rate_feature(self, df: pd.DataFrame,
                           rates_df: Optional[pd.DataFrame]) -> pd.DataFrame:
        """기준금리·대출금리 월별 merge"""
        if rates_df is None or rates_df.empty:
            for col in RATE_COLS:
                df[col] = np.nan
            return df
        rate_cols = ["ym"] + [c for c in RATE_COLS if c in rates_df.columns]
        return df.merge(rates_df[rate_cols], on="ym", how="left")

    def build_sgg_external(self, df: pd.DataFrame,
                           pop_df: pd.DataFrame,
                           aca_df: pd.DataFrame) -> pd.DataFrame:
        """시도 인구수·시군구 학원수 병합.

        - pop_df: sido_cd(2자리) | 시도_인구수
        - aca_df: sgg_nm_raw | 시군구_학원수
        """
        # 시도_인구수: sggCd 앞 2자리로 join
        if not pop_df.empty:
            df["_sido_cd"] = df["sggCd"].astype(str).str[:2]
            df = df.merge(pop_df, left_on="_sido_cd", right_on="sido_cd", how="left")
            df.drop(columns=["_sido_cd", "sido_cd"], errors="ignore", inplace=True)
        else:
            df["시도_인구수"] = np.nan

        # 시군구_학원수: estateAgentSggNm (시군구명) 으로 join
        if not aca_df.empty and "estateAgentSggNm" in df.columns:
            # 시군구명 정규화: '강남구' 형태로 맞추기
            df["_sgg_nm"] = df["estateAgentSggNm"].astype(str).str.strip()
            df = df.merge(aca_df.rename(columns={"sgg_nm_raw": "_sgg_nm"}),
                          on="_sgg_nm", how="left")
            df.drop(columns=["_sgg_nm"], errors="ignore", inplace=True)
        else:
            df["시군구_학원수"] = np.nan

        print(f"  시도_인구수 커버리지: {df['시도_인구수'].notna().sum():,}/{len(df):,}건")
        print(f"  시군구_학원수 커버리지: {df['시군구_학원수'].notna().sum():,}/{len(df):,}건")
        return df

    # ── 구버전 호환 ──
    def build_all(self, trade_df, rent_df=None):
        return self.build_all_trade(trade_df, rent_df)


# ============================================================
# SECTION 4. ML 모델 — LightGBM K-Fold
# ============================================================

try:
    import lightgbm as lgb
    from sklearn.model_selection import KFold
    from sklearn.metrics import mean_absolute_error, r2_score
    HAS_LGB = True
except ImportError:
    HAS_LGB = False


@dataclass
class ModelConfig:
    n_folds:        int   = 5
    n_estimators:   int   = 500
    learning_rate:  float = 0.05
    num_leaves:     int   = 127
    min_data_leaf:  int   = 50
    feature_frac:   float = 0.8
    bagging_frac:   float = 0.8
    lambda_l1:      float = 0.1
    lambda_l2:      float = 0.1
    early_stopping: int   = 50


class RealEstatePriceModel:
    """K-Fold LightGBM 앙상블 + SHAP 해석"""

    def __init__(self, config: ModelConfig = ModelConfig()):
        self.config = config
        self.models: list = []
        self.feature_importance: Optional[pd.Series] = None
        self.oof_preds: Optional[np.ndarray] = None

    def train(self, X: pd.DataFrame, y: pd.Series) -> dict:
        if not HAS_LGB:
            raise ImportError("pip install lightgbm")

        kf   = KFold(n_splits=self.config.n_folds, shuffle=True, random_state=42)
        oof  = np.zeros(len(X))
        imps = np.zeros(len(X.columns))
        maes = []

        params = {
            "objective":        "regression",
            "metric":           "mae",
            "learning_rate":    self.config.learning_rate,
            "num_leaves":       self.config.num_leaves,
            "min_data_in_leaf": self.config.min_data_leaf,
            "feature_fraction": self.config.feature_frac,
            "bagging_fraction": self.config.bagging_frac,
            "bagging_freq":     1,
            "lambda_l1":        self.config.lambda_l1,
            "lambda_l2":        self.config.lambda_l2,
            "verbose":         -1,
        }

        for fold, (tr_idx, val_idx) in enumerate(kf.split(X)):
            X_tr, X_val = X.iloc[tr_idx], X.iloc[val_idx]
            y_tr, y_val = y.iloc[tr_idx], y.iloc[val_idx]

            dtrain = lgb.Dataset(X_tr, label=y_tr)
            dval   = lgb.Dataset(X_val, label=y_val, reference=dtrain)

            model = lgb.train(
                params, dtrain,
                num_boost_round=self.config.n_estimators,
                valid_sets=[dval],
                callbacks=[
                    lgb.early_stopping(self.config.early_stopping),
                    lgb.log_evaluation(-1),
                ],
            )
            self.models.append(model)
            oof[val_idx] = model.predict(X_val)
            imps += model.feature_importance(importance_type="gain")

            mae = mean_absolute_error(y_val, oof[val_idx])
            r2  = r2_score(y_val, oof[val_idx])
            maes.append(mae)
            print(f"  Fold {fold+1} | MAE: {mae:,.0f}만원 | R²: {r2:.4f}")

        self.oof_preds = oof
        self.feature_importance = pd.Series(
            imps / self.config.n_folds, index=X.columns
        ).sort_values(ascending=False)

        total_mae = mean_absolute_error(y, oof)
        total_r2  = r2_score(y, oof)
        rmse      = np.sqrt(((y - oof) ** 2).mean())
        print(f"\n  ── 최종 OOF 결과 ──────────────────")
        print(f"  MAE : {total_mae:,.0f}만원")
        print(f"  RMSE: {rmse:,.0f}만원")
        print(f"  R²  : {total_r2:.4f}")
        return {"mae": total_mae, "rmse": rmse, "r2": total_r2, "fold_maes": maes}

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        preds = np.array([m.predict(X) for m in self.models])
        return preds.mean(axis=0)

    def explain_single(self, X: pd.DataFrame, idx: int = 0) -> None:
        try:
            import shap
            explainer   = shap.TreeExplainer(self.models[0])
            single_row  = X.iloc[[idx]]
            shap_values = explainer.shap_values(single_row)
            row_shap    = pd.Series(shap_values[0], index=X.columns)
            row_shap    = row_shap.reindex(row_shap.abs().sort_values(ascending=False).index)
            base        = explainer.expected_value
            pred        = base + shap_values[0].sum()
            print(f"\n  ── SHAP 단건 설명 (index={idx}) ─────────────")
            print(f"  기준가: {base:,.0f}만원  →  예측가: {pred:,.0f}만원\n")
            for feat, val in row_shap.head(10).items():
                sign = "▲" if val > 0 else "▼"
                print(f"  {sign} {feat:<30} {val:+,.0f}만원")
        except ImportError:
            print("  pip install shap")


# ============================================================
# SECTION 5. SHAP 시각화
# ============================================================

class SHAPAnalyzer:

    def plot_importance(self, importance: pd.Series, save_path: str = "shap_importance.png") -> None:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            top = importance.head(20)
            fig, ax = plt.subplots(figsize=(10, 8))
            colors = ["#2196F3" if i < 5 else "#64B5F6" for i in range(len(top))]
            ax.barh(range(len(top)), top.values, color=colors)
            ax.set_yticks(range(len(top)))
            ax.set_yticklabels(top.index, fontsize=11)
            ax.invert_yaxis()
            ax.set_xlabel("Feature Importance (Gain)", fontsize=12)
            ax.set_title("피처 중요도 TOP 20 (LightGBM Gain)", fontsize=14, pad=15)
            plt.tight_layout()
            plt.savefig(save_path, dpi=150)
            plt.close()
            print(f"  저장: {save_path}")
        except ImportError:
            print("  pip install matplotlib")

    def plot_summary(self, models: list, X: pd.DataFrame, save_path: str = "shap_summary.png") -> None:
        try:
            import shap
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            sample = X.sample(min(500, len(X)), random_state=42)
            explainer   = shap.TreeExplainer(models[0])
            shap_values = explainer.shap_values(sample)
            plt.figure(figsize=(12, 9))
            shap.summary_plot(shap_values, sample, show=False, max_display=20)
            plt.tight_layout()
            plt.savefig(save_path, dpi=150, bbox_inches="tight")
            plt.close()
            print(f"  저장: {save_path}")
        except Exception as e:
            print(f"  SHAP summary 오류: {e}")

    def plot_dependence(self, models: list, X: pd.DataFrame,
                        feature: str, save_path: str = None) -> None:
        try:
            import shap
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            sample      = X.sample(min(500, len(X)), random_state=42)
            explainer   = shap.TreeExplainer(models[0])
            shap_values = explainer.shap_values(sample)
            path = save_path or f"shap_dep_{feature}.png"
            plt.figure(figsize=(8, 6))
            shap.dependence_plot(feature, shap_values, sample, show=False)
            plt.tight_layout()
            plt.savefig(path, dpi=150)
            plt.close()
            print(f"  저장: {path}")
        except Exception as e:
            print(f"  Dependence plot 오류: {e}")


# ============================================================
# SECTION 6. 파이프라인 저장 / 저평가 탐지
# ============================================================

def save_pipeline(model: RealEstatePriceModel,
                  medians: pd.Series,
                  feature_cols: list,
                  path: str = "pipeline.pkl") -> None:
    import pickle
    base = path.replace(".pkl", "")

    lgb_paths = []
    for i, booster in enumerate(model.models):
        lgb_path = f"{base}_fold{i}.lgb"
        booster.save_model(lgb_path)
        lgb_paths.append(lgb_path)

    payload = {
        "lgb_paths":    lgb_paths,
        "n_folds":      len(model.models),
        "medians":      medians.to_dict(),
        "feature_cols": feature_cols,
        "feature_importance": (
            model.feature_importance.to_dict()
            if model.feature_importance is not None else {}
        ),
        "saved_at": datetime.now().isoformat(),
    }
    with open(path, "wb") as f:
        pickle.dump(payload, f, protocol=5)

    total_mb = sum(os.path.getsize(p) for p in lgb_paths) / 1024 / 1024
    meta_mb  = os.path.getsize(path) / 1024 / 1024
    print(f"  파이프라인 저장: {path} ({meta_mb:.1f} MB)")
    print(f"  LGB 모델 저장: {len(lgb_paths)}개 fold ({total_mb:.1f} MB)")


def find_undervalued(df: pd.DataFrame, model: RealEstatePriceModel,
                     X: pd.DataFrame, threshold_pct: float = -10.0,
                     pred: Optional[np.ndarray] = None) -> pd.DataFrame:
    if pred is None:
        pred = model.predict(X)
    result = df.iloc[:len(pred)].copy()
    result["예측가_만원"]   = pred
    result["실거래가_만원"] = result["거래금액"]
    result["괴리율_%"] = (
        (result["실거래가_만원"] - result["예측가_만원"]) /
        result["예측가_만원"] * 100
    )
    n0 = len(result)

    if "dealingGbn" in result.columns:
        result = result[~result["dealingGbn"].str.contains("직거래", na=False)]
    n1 = len(result)

    apt_avg = result.groupby("단지명")["실거래가_만원"].transform("mean")
    result  = result[(result["실거래가_만원"] / apt_avg.replace(0, np.nan)).between(0.5, 2.0)]
    n2 = len(result)

    apt_cnt = result.groupby("단지명")["실거래가_만원"].transform("count")
    result  = result[apt_cnt >= 5]
    n3 = len(result)

    print(f"  필터 전: {n0:,}건")
    print(f"  직거래 제거 후: {n1:,}건 (-{n0-n1:,}건)")
    print(f"  이상치 제거 후: {n2:,}건 (-{n1-n2:,}건)")
    print(f"  소규모단지 제거 후: {n3:,}건 (-{n2-n3:,}건)")

    undervalued = result[result["괴리율_%"] < threshold_pct].copy()
    undervalued = undervalued.sort_values("괴리율_%")

    want = ["단지명", "지역명", "읍면동", "sggCd", "전용면적", "층",
            "거래년도", "거래월", "실거래가_만원", "예측가_만원", "괴리율_%"]
    cols = [c for c in want if c in undervalued.columns]
    return undervalued[cols].head(30)


def save_undervalued_full(df: pd.DataFrame, model: RealEstatePriceModel,
                          X: pd.DataFrame,
                          pred: Optional[np.ndarray] = None,
                          path: str = "undervalued_full.csv",
                          deal_type: str = "매매") -> pd.DataFrame:
    """API /undervalued용 저평가 목록 저장 (물건유형·거래유형 컬럼 포함)"""
    if pred is None:
        pred = model.predict(X)
    result = df.iloc[:len(pred)].copy()
    result["예측가_만원"]   = pred
    result["실거래가_만원"] = result["거래금액"]
    result["괴리율_%"] = (
        (result["실거래가_만원"] - result["예측가_만원"]) /
        result["예측가_만원"] * 100
    )

    if "dealingGbn" in result.columns:
        result = result[~result["dealingGbn"].str.contains("직거래", na=False)]
    apt_avg = result.groupby("단지명")["실거래가_만원"].transform("mean")
    result  = result[(result["실거래가_만원"] / apt_avg.replace(0, np.nan)).between(0.5, 2.0)]
    apt_cnt = result.groupby("단지명")["실거래가_만원"].transform("count")
    result  = result[apt_cnt >= 5]

    full = result[result["괴리율_%"] < -10.0].sort_values("괴리율_%")

    # 물건유형 한국어 변환
    if "물건유형" in full.columns:
        full["물건유형"] = full["물건유형"].map(PROPERTY_TYPE_MAP).fillna("아파트")
    else:
        full["물건유형"] = "아파트"
    full["거래유형"] = deal_type

    # 지역명 없으면 빈 문자열
    if "지역명" not in full.columns:
        full["지역명"] = ""

    save_cols = ["단지명", "지역명", "읍면동", "sggCd", "전용면적", "층",
                 "거래년도", "거래월", "실거래가_만원", "예측가_만원", "괴리율_%",
                 "물건유형", "거래유형", "보증금"]
    save_cols = [c for c in save_cols if c in full.columns]
    out = full[save_cols]

    if path != "_skip":
        out.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"  저평가 목록: {path}  ({len(out):,}건)")

    return out


# ============================================================
# SECTION 7. 학습 데이터 준비 헬퍼
# ============================================================

def _prepare_X(df: pd.DataFrame, feature_cols: list) -> tuple:
    available = [c for c in feature_cols if c in df.columns]
    missing   = [c for c in feature_cols if c not in df.columns]
    if missing:
        print(f"  누락 피처 (스킵): {missing}")
    X = df[available].copy()
    for col in X.columns:
        X[col] = pd.to_numeric(X[col], errors="coerce")
    medians = X.median()
    X = X.fillna(medians)
    return X, medians, available


def _print_importance(model: RealEstatePriceModel) -> None:
    print(f"\n  {'피처':<30} {'중요도':>10}")
    print(f"  {'─'*42}")
    max_imp = model.feature_importance.max()
    for feat, imp in model.feature_importance.items():
        bar = "█" * int(imp / max_imp * 25)
        print(f"  {feat:<30} {bar}")


# ============================================================
# SECTION 8. 개별 모델 파이프라인
# ============================================================

def run_trade_pipeline(loader: DBLoader, fe: FeatureEngineer,
                       sample_n: int = None,
                       start_ym: str = "202301",
                       rates_df: Optional[pd.DataFrame] = None,
                       pop_df: Optional[pd.DataFrame] = None,
                       aca_df: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    print("\n" + "="*60)
    print("  [매매 모델] 아파트 + 연립다세대 + 오피스텔 + 단독다가구 매매가 예측")
    print("="*60)

    # ── 데이터 로드 ─────────────────────────────────────────
    apt   = loader.load_trade(limit=sample_n, start_ym=start_ym)
    apt["물건유형"] = 0
    villa = loader.load_villa_trade(limit=sample_n, start_ym=start_ym)
    if not villa.empty:
        villa["물건유형"] = 1
    offi  = loader.load_officetel_trade(limit=sample_n, start_ym=start_ym)
    if not offi.empty:
        offi["물건유형"] = 2
    house = loader.load_house_trade(limit=sample_n, start_ym=start_ym)
    if not house.empty:
        house["물건유형"] = 3

    parts = [apt]
    for df_part in [villa, offi, house]:
        if not df_part.empty:
            parts.append(df_part)
    trade_df = pd.concat(parts, ignore_index=True)

    rent_n     = (sample_n * 3) if sample_n else None
    apt_rent   = loader.load_rent(limit=rent_n)
    villa_rent = loader.load_villa_rent(limit=rent_n)
    rent_df    = pd.concat([apt_rent, villa_rent], ignore_index=True) if not villa_rent.empty else apt_rent

    # ── 피처 엔지니어링 ─────────────────────────────────────
    print("\n[Step 2] 피처 엔지니어링")
    df = fe.build_all_trade(trade_df, rent_df, rates_df, pop_df, aca_df)

    # ── 학습 데이터 준비 ─────────────────────────────────────
    print("\n[Step 3] 학습 데이터 준비")
    X, medians, available = _prepare_X(df, TRADE_FEATURE_COLS)
    y = df["거래금액"]
    valid_mask = y.notna() & (y > 0)
    X, y = X[valid_mask].reset_index(drop=True), y[valid_mask].reset_index(drop=True)
    df_aligned = df[valid_mask].reset_index(drop=True)
    print(f"  학습 피처: {len(available)}개  |  학습 데이터: {len(X):,}건")

    if not HAS_LGB:
        print("  LightGBM 미설치")
        return None

    # ── 학습 ────────────────────────────────────────────────
    print("\n[Step 4] LightGBM K-Fold 학습")
    model = RealEstatePriceModel()
    metrics = model.train(X, y)

    _print_importance(model)

    # ── SHAP (매매 모델만) ───────────────────────────────────
    print("\n[Step 5] SHAP 시각화")
    analyzer = SHAPAnalyzer()
    analyzer.plot_importance(model.feature_importance, "shap_importance.png")
    analyzer.plot_summary(model.models, X, "shap_summary.png")
    top_feat = model.feature_importance.index[0]
    analyzer.plot_dependence(model.models, X, top_feat, f"shap_dep_{top_feat}.png")
    model.explain_single(X, idx=len(X) - 1)

    # ── 저평가 탐지 ─────────────────────────────────────────
    print("\n[Step 6] 저평가 탐지 (괴리율 < -10%)")
    all_preds = model.predict(X)
    undervalued = find_undervalued(df_aligned, model, X, pred=all_preds)
    print(f"  저평가 {len(undervalued)}건 (Top 30)")
    if len(undervalued) > 0:
        pd.set_option("display.float_format", "{:,.0f}".format)
        print(undervalued.drop(columns=["sggCd"], errors="ignore").to_string(index=False))
        undervalued.to_csv("undervalued_units.csv", index=False, encoding="utf-8-sig")

    # ── 저장 ────────────────────────────────────────────────
    print("\n[Step 7] 모델 저장")
    result_df = save_undervalued_full(df_aligned, model, X, pred=all_preds,
                                      path="_skip", deal_type="매매")
    save_pipeline(model, medians, available, path="pipeline_trade.pkl")
    save_pipeline(model, medians, available, path="pipeline.pkl")  # 하위호환

    print(f"  MAE: {metrics['mae']:,.0f}만원  R²: {metrics['r2']:.4f}")
    return result_df


def run_jeonse_pipeline(loader: DBLoader, fe: FeatureEngineer,
                        sample_n: int = None,
                        rates_df: Optional[pd.DataFrame] = None,
                        pop_df: Optional[pd.DataFrame] = None,
                        aca_df: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    print("\n" + "="*60)
    print("  [전세 모델] 아파트 + 연립다세대 + 오피스텔 + 단독다가구 전세 보증금 예측")
    print("="*60)

    rent_n     = (sample_n * 3) if sample_n else None
    apt_rent   = loader.load_rent(limit=rent_n)
    apt_rent["물건유형"] = 0
    villa_rent = loader.load_villa_rent(limit=rent_n)
    if not villa_rent.empty:
        villa_rent["물건유형"] = 1
    offi_rent  = loader.load_officetel_rent(limit=rent_n)
    if not offi_rent.empty:
        offi_rent["물건유형"] = 2
    house_rent = loader.load_house_rent(limit=rent_n)
    if not house_rent.empty:
        house_rent["물건유형"] = 3

    parts = [apt_rent]
    for df_part in [villa_rent, offi_rent, house_rent]:
        if not df_part.empty:
            parts.append(df_part)
    rent_df = pd.concat(parts, ignore_index=True)

    print("\n[Step 2] 피처 엔지니어링")
    df = fe.build_all_jeonse(rent_df, rates_df, pop_df, aca_df)

    print("\n[Step 3] 학습 데이터 준비")
    X, medians, available = _prepare_X(df, JEONSE_FEATURE_COLS)
    y = df["보증금"]
    valid_mask = y.notna() & (y > 0)
    X, y = X[valid_mask].reset_index(drop=True), y[valid_mask].reset_index(drop=True)
    df_aligned = df[valid_mask].reset_index(drop=True)
    print(f"  학습 피처: {len(available)}개  |  학습 데이터: {len(X):,}건")

    if not HAS_LGB:
        return None

    print("\n[Step 4] LightGBM K-Fold 학습")
    model = RealEstatePriceModel()
    metrics = model.train(X, y)
    _print_importance(model)

    print("\n[Step 5] 저평가 탐지 (보증금 괴리율 < -10%)")
    all_preds = model.predict(X)
    result_df = save_undervalued_full(df_aligned, model, X, pred=all_preds,
                                      path="_skip", deal_type="전세")
    save_pipeline(model, medians, available, path="pipeline_jeonse.pkl")

    print(f"  MAE: {metrics['mae']:,.0f}만원  R²: {metrics['r2']:.4f}")
    return result_df


def run_wolse_pipeline(loader: DBLoader, fe: FeatureEngineer,
                       sample_n: int = None,
                       rates_df: Optional[pd.DataFrame] = None,
                       pop_df: Optional[pd.DataFrame] = None,
                       aca_df: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    print("\n" + "="*60)
    print("  [월세 모델] 아파트 + 연립다세대 + 오피스텔 + 단독다가구 월세 예측")
    print("="*60)

    rent_n     = (sample_n * 3) if sample_n else None
    apt_rent   = loader.load_rent(limit=rent_n)
    apt_rent["물건유형"] = 0
    villa_rent = loader.load_villa_rent(limit=rent_n)
    if not villa_rent.empty:
        villa_rent["물건유형"] = 1
    offi_rent  = loader.load_officetel_rent(limit=rent_n)
    if not offi_rent.empty:
        offi_rent["물건유형"] = 2
    house_rent = loader.load_house_rent(limit=rent_n)
    if not house_rent.empty:
        house_rent["물건유형"] = 3

    parts = [apt_rent]
    for df_part in [villa_rent, offi_rent, house_rent]:
        if not df_part.empty:
            parts.append(df_part)
    rent_df = pd.concat(parts, ignore_index=True)

    print("\n[Step 2] 피처 엔지니어링")
    df = fe.build_all_wolse(rent_df, rates_df, pop_df, aca_df)

    print("\n[Step 3] 학습 데이터 준비")
    X, medians, available = _prepare_X(df, WOLSE_FEATURE_COLS)
    y = df["월세"]
    valid_mask = y.notna() & (y > 0)
    X, y = X[valid_mask].reset_index(drop=True), y[valid_mask].reset_index(drop=True)
    df_aligned = df[valid_mask].reset_index(drop=True)
    print(f"  학습 피처: {len(available)}개  |  학습 데이터: {len(X):,}건")

    if not HAS_LGB:
        return None

    print("\n[Step 4] LightGBM K-Fold 학습")
    model = RealEstatePriceModel()
    metrics = model.train(X, y)
    _print_importance(model)

    print("\n[Step 5] 저평가 탐지 (월세 괴리율 < -10%)")
    all_preds = model.predict(X)
    result_df = save_undervalued_full(df_aligned, model, X, pred=all_preds,
                                      path="_skip", deal_type="월세")
    save_pipeline(model, medians, available, path="pipeline_wolse.pkl")

    print(f"  MAE: {metrics['mae']:,.0f}만원  R²: {metrics['r2']:.4f}")
    return result_df


# ============================================================
# SECTION 9. 전체 파이프라인 실행
# ============================================================

def run_pipeline(db_path: str = "realestate.db",
                 sample_n: int = None,
                 start_ym: str = "202301",
                 modes: tuple = ("매매", "전세", "월세")) -> None:
    """
    3개 모델 순차 실행 → undervalued_full.csv 통합 저장

    Args:
        db_path:  DB 파일 경로
        sample_n: 매매 데이터 샘플 수 (None=전체)
        start_ym: 데이터 시작 년월
        modes:    실행할 모델 ("매매", "전세", "월세")
    """
    print("=" * 60)
    print("  부동산 ML 파이프라인 v5")
    print(f"  실행 모드: {', '.join(modes)}")
    print("=" * 60)

    loader = DBLoader(db_path)
    print("\n[Step 1] DB 데이터 현황")
    loader.table_stats()

    fe = FeatureEngineer()

    print("\n[Step 1-B] 거시지표 로드 (ecos_macro DB → ECOS API fallback)")
    rates_df = fetch_macro_rates(start_ym="202201", db_path=db_path)

    print("\n[Step 1-C] 시도·시군구 외부 피처 로드")
    try:
        pop_df, aca_df = loader.load_sgg_features()
        print(f"  시도 인구: {len(pop_df)}개 시도 | 학원: {aca_df['시군구_학원수'].sum():,.0f}개소 ({len(aca_df)}개 시군구)")
    except Exception as e:
        print(f"  [경고] 외부 피처 로드 실패: {e}")
        pop_df, aca_df = pd.DataFrame(), pd.DataFrame()

    results = []

    if "매매" in modes:
        r = run_trade_pipeline(loader, fe, sample_n, start_ym, rates_df, pop_df, aca_df)
        if r is not None:
            results.append(r)

    if "전세" in modes:
        r = run_jeonse_pipeline(loader, fe, sample_n, rates_df, pop_df, aca_df)
        if r is not None:
            results.append(r)

    if "월세" in modes:
        r = run_wolse_pipeline(loader, fe, sample_n, rates_df, pop_df, aca_df)
        if r is not None:
            results.append(r)

    # ── undervalued_full.csv 통합 ────────────────────────────
    # 부분 실행 시 스킵된 모드의 기존 데이터 보존
    skipped = [m for m in ["매매", "전세", "월세"] if m not in modes]
    if skipped and os.path.exists("undervalued_full.csv"):
        existing = pd.read_csv("undervalued_full.csv")
        if "거래유형" not in existing.columns:
            existing["거래유형"] = "매매"
        if "물건유형" not in existing.columns:
            existing["물건유형"] = "아파트"
        for mode in skipped:
            mode_df = existing[existing["거래유형"] == mode].copy()
            if not mode_df.empty:
                results.insert(0, mode_df)
                print(f"\n  ✓ 기존 {mode} 결과 보존: {len(mode_df):,}건")

    if results:
        combined = pd.concat(results, ignore_index=True).sort_values("괴리율_%")
        combined.to_csv("undervalued_full.csv", index=False, encoding="utf-8-sig")
        print(f"\n  ✓ 통합 저평가 목록: undervalued_full.csv  ({len(combined):,}건)")
        print(f"    거래유형별: {combined['거래유형'].value_counts().to_dict()}")
        print(f"    물건유형별: {combined['물건유형'].value_counts().to_dict()}")

    print("\n" + "=" * 60)
    print("  완료")
    print("=" * 60)


# ============================================================
# SECTION 10. 진입점
# ============================================================

if __name__ == "__main__":
    import sys

    # python realestate_ml.py [sample_n] [start_ym] [modes]
    # 예) python realestate_ml.py           ← 전체, 3모델 모두
    #     python realestate_ml.py 200000    ← 샘플, 3모델
    #     python realestate_ml.py 0 202301 매매   ← 매매 모델만
    sample_n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] != "0" else None
    start_ym = sys.argv[2] if len(sys.argv) > 2 else "202301"
    modes    = tuple(sys.argv[3:]) if len(sys.argv) > 3 else ("매매", "전세", "월세")

    run_pipeline(
        db_path="realestate.db",
        sample_n=sample_n,
        start_ym=start_ym,
        modes=modes,
    )
