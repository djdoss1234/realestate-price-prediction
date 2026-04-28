"""
부동산 가격 예측 FastAPI 서버
==============================
시작:  uvicorn api:app --reload --host 0.0.0.0 --port 8000
문서:  http://localhost:8000/docs

사전 조건:
  python realestate_ml.py  ← pipeline.pkl, undervalued_full.csv 생성
"""

import os
import pickle
import sqlite3
import requests
import concurrent.futures
from datetime import datetime
from typing import List, Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


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

# ── 상수 ─────────────────────────────────────────────────────
DB_PATH               = "realestate.db"
PIPELINE_PATH         = "pipeline.pkl"
PIPELINE_TRADE_PATH   = "pipeline_trade.pkl"
PIPELINE_JEONSE_PATH  = "pipeline_jeonse.pkl"
PIPELINE_WOLSE_PATH   = "pipeline_wolse.pkl"
UNDERVALUED_PATH      = "undervalued_full.csv"
CURRENT_YEAR          = 2026

BRAND_MAP = {
    "래미안": 3, "자이": 3, "힐스테이트": 3, "푸르지오": 3,
    "아크로": 3, "디에이치": 3, "르엘": 3,
    "롯데캐슬": 2, "e편한세상": 2, "아이파크": 2, "SK뷰": 2,
    "더샵": 2, "위브": 2, "리슈빌": 2, "한화포레나": 2,
    "호반베르디움": 2, "중흥S-클래스": 2,
}

SGG_NAMES: dict[str, str] = {
    # 서울
    "11110":"서울 종로구","11140":"서울 중구","11170":"서울 용산구",
    "11200":"서울 성동구","11215":"서울 광진구","11230":"서울 동대문구",
    "11260":"서울 중랑구","11290":"서울 성북구","11305":"서울 강북구",
    "11320":"서울 도봉구","11350":"서울 노원구","11380":"서울 은평구",
    "11410":"서울 서대문구","11440":"서울 마포구","11470":"서울 양천구",
    "11500":"서울 강서구","11530":"서울 구로구","11545":"서울 금천구",
    "11560":"서울 영등포구","11590":"서울 동작구","11620":"서울 관악구",
    "11650":"서울 서초구","11680":"서울 강남구","11710":"서울 송파구",
    "11740":"서울 강동구",
    # 부산
    "26110":"부산 중구","26140":"부산 서구","26170":"부산 동구",
    "26200":"부산 영도구","26230":"부산 부산진구","26260":"부산 동래구",
    "26290":"부산 남구","26320":"부산 북구","26350":"부산 해운대구",
    "26380":"부산 사하구","26410":"부산 금정구","26440":"부산 강서구",
    "26470":"부산 연제구","26500":"부산 수영구","26530":"부산 사상구",
    "26710":"부산 기장군",
    # 대구
    "27110":"대구 중구","27140":"대구 동구","27170":"대구 서구",
    "27200":"대구 남구","27230":"대구 북구","27260":"대구 수성구",
    "27290":"대구 달서구","27710":"대구 달성군",
    # 인천
    "28110":"인천 중구","28140":"인천 동구","28177":"인천 미추홀구",
    "28185":"인천 연수구","28200":"인천 남동구","28237":"인천 부평구",
    "28245":"인천 계양구","28260":"인천 서구","28710":"인천 강화군",
    # 광주
    "29110":"광주 동구","29140":"광주 서구","29155":"광주 남구",
    "29170":"광주 북구","29200":"광주 광산구",
    # 대전
    "30110":"대전 동구","30140":"대전 중구","30170":"대전 서구",
    "30200":"대전 유성구","30230":"대전 대덕구",
    # 울산
    "31110":"울산 중구","31140":"울산 남구","31170":"울산 동구",
    "31200":"울산 북구","31710":"울산 울주군",
    # 세종
    "36110":"세종시",
    # 경기
    "41111":"경기 수원 장안구","41113":"경기 수원 권선구",
    "41115":"경기 수원 팔달구","41117":"경기 수원 영통구",
    "41131":"경기 성남 수정구","41133":"경기 성남 중원구",
    "41135":"경기 성남 분당구","41150":"경기 의정부시",
    "41171":"경기 안양 만안구","41173":"경기 안양 동안구",
    "41190":"경기 부천시","41210":"경기 광명시","41220":"경기 평택시",
    "41250":"경기 동두천시","41271":"경기 안산 상록구",
    "41273":"경기 안산 단원구","41281":"경기 고양 덕양구",
    "41285":"경기 고양 일산동구","41287":"경기 고양 일산서구",
    "41290":"경기 과천시","41310":"경기 구리시","41360":"경기 남양주시",
    "41370":"경기 오산시","41390":"경기 시흥시","41410":"경기 군포시",
    "41430":"경기 의왕시","41450":"경기 하남시",
    "41461":"경기 용인 처인구","41463":"경기 용인 기흥구",
    "41465":"경기 용인 수지구","41480":"경기 파주시",
    "41500":"경기 이천시","41550":"경기 안성시","41570":"경기 김포시",
    "41590":"경기 화성시","41610":"경기 광주시","41630":"경기 양주시",
    "41650":"경기 포천시","41670":"경기 여주시",
    "41800":"경기 연천군","41820":"경기 가평군","41830":"경기 양평군",
    # 강원 (구코드 42 + 신코드 51, 강원특별자치도 2023~)
    "42110":"강원 춘천시","42130":"강원 원주시","42150":"강원 강릉시",
    "42170":"강원 동해시","42190":"강원 태백시","42210":"강원 속초시",
    "42230":"강원 삼척시","42720":"강원 홍천군","42730":"강원 횡성군",
    "42750":"강원 영월군","42760":"강원 평창군","42770":"강원 정선군",
    "42820":"강원 고성군","42830":"강원 양양군",
    "51110":"강원 춘천시","51130":"강원 원주시","51150":"강원 강릉시",
    "51170":"강원 동해시","51190":"강원 태백시","51210":"강원 속초시",
    "51230":"강원 삼척시",
    # 충북
    "43111":"충북 청주 상당구","43112":"충북 청주 서원구",
    "43113":"충북 청주 흥덕구","43114":"충북 청주 청원구",
    "43130":"충북 충주시","43150":"충북 제천시",
    "43720":"충북 보은군","43730":"충북 옥천군","43740":"충북 영동군",
    "43745":"충북 증평군","43750":"충북 진천군","43760":"충북 괴산군",
    "43770":"충북 음성군","43800":"충북 단양군",
    # 충남
    "44131":"충남 천안 동남구","44133":"충남 천안 서북구",
    "44150":"충남 공주시","44180":"충남 보령시","44200":"충남 아산시",
    "44210":"충남 서산시","44230":"충남 논산시","44250":"충남 계룡시",
    "44270":"충남 당진시","44710":"충남 금산군","44760":"충남 부여군",
    "44770":"충남 서천군","44790":"충남 청양군",
    "44800":"충남 홍성군","44810":"충남 예산군","44825":"충남 태안군",
    # 전북
    "45111":"전북 전주 완산구","45113":"전북 전주 덕진구",
    "45130":"전북 군산시","45140":"전북 익산시","45180":"전북 정읍시",
    "45190":"전북 남원시","45210":"전북 김제시",
    # 전남
    "46110":"전남 목포시","46130":"전남 여수시","46150":"전남 순천시",
    "46170":"전남 나주시","46230":"전남 광양시",
    "46710":"전남 담양군","46720":"전남 곡성군","46730":"전남 구례군",
    "46770":"전남 고흥군","46780":"전남 보성군","46790":"전남 화순군",
    "46800":"전남 장흥군","46810":"전남 강진군","46820":"전남 해남군",
    "46830":"전남 영암군","46840":"전남 무안군","46860":"전남 함평군",
    "46870":"전남 영광군","46880":"전남 장성군","46900":"전남 완도군",
    "46910":"전남 진도군",
    # 경북
    "47111":"경북 포항 남구","47113":"경북 포항 북구",
    "47130":"경북 경주시","47150":"경북 김천시","47170":"경북 안동시",
    "47190":"경북 구미시","47210":"경북 영주시","47220":"경북 영천시",
    "47230":"경북 상주시","47250":"경북 문경시","47280":"경북 경산시",
    "47730":"경북 의성군","47750":"경북 청송군","47760":"경북 영양군",
    "47770":"경북 영덕군","47820":"경북 고령군","47830":"경북 성주군",
    "47840":"경북 칠곡군","47850":"경북 예천군",
    # 경남
    "48121":"경남 창원 성산구","48123":"경남 창원 마산합포구",
    "48125":"경남 창원 마산회원구","48127":"경남 창원 진해구",
    "48170":"경남 진주시","48220":"경남 통영시","48240":"경남 사천시",
    "48250":"경남 김해시","48270":"경남 밀양시","48310":"경남 거제시",
    "48330":"경남 양산시","48720":"경남 의령군","48730":"경남 함안군",
    "48740":"경남 창녕군","48820":"경남 고성군",
    # 강원특별자치도 군
    "51720":"강원 홍천군","51730":"강원 횡성군","51750":"강원 영월군",
    "51760":"강원 평창군","51770":"강원 정선군","51780":"강원 철원군",
    "51790":"강원 화천군","51800":"강원 양구군","51810":"강원 인제군",
    "51820":"강원 고성군","51830":"강원 양양군",
    # 제주
    "50110":"제주 제주시","50130":"제주 서귀포시",
}

# ── FastAPI 앱 ────────────────────────────────────────────────
app = FastAPI(
    title="부동산 가격 예측 API",
    description="국토부 실거래가 106만건 기반 LightGBM 예측 모델",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 전역 상태 ─────────────────────────────────────────────────
_pipeline:        Optional[dict]         = None   # 하위호환 (매매)
_pipeline_trade:  Optional[dict]         = None
_pipeline_jeonse: Optional[dict]         = None
_pipeline_wolse:  Optional[dict]         = None
_undervalued:     Optional[pd.DataFrame] = None
_rates:           Optional[dict]         = None   # {ym: {기준금리, 대출금리, ...}}


def _load_pipeline_file(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    base_dir = os.path.dirname(os.path.abspath(path))
    with open(path, "rb") as f:
        meta = pickle.load(f)
    abs_paths = []
    for lgb_path in meta["lgb_paths"]:
        abs_path = lgb_path if os.path.isabs(lgb_path) else os.path.join(base_dir, lgb_path)
        if not os.path.exists(abs_path):
            raise RuntimeError(f"LGB 모델 파일 없음: {abs_path}")
        abs_paths.append(abs_path)
    # fold 5개를 병렬 로딩 (I/O bound이라 thread 유효)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(abs_paths)) as ex:
        boosters = list(ex.map(lambda p: lgb.Booster(model_file=p), abs_paths))
    return {
        "boosters":           boosters,
        "medians":            pd.Series(meta["medians"]),
        "feature_cols":       meta["feature_cols"],
        "feature_importance": pd.Series(meta.get("feature_importance", {})),
        "saved_at":           meta.get("saved_at"),
    }


def _fetch_rates() -> dict:
    """ECOS API에서 거시지표 로드 → {ym: {col: val}} dict 반환"""
    api_key = os.getenv("ECOS_API_KEY", "")
    if not api_key:
        return {}
    now    = datetime.now()
    end_ym = now.strftime("%Y%m")

    def _get_m(stat, item):
        url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}"
               f"/json/kr/1/200/{stat}/M/202201/{end_ym}/{item}")
        try:
            rows = requests.get(url, timeout=10).json().get("StatisticSearch", {}).get("row", [])
            return {r["TIME"]: float(r["DATA_VALUE"]) for r in rows}
        except Exception:
            return {}

    def _get_q(stat, item):
        """분기 데이터 → 분기 시작월(YYYYMM) 기준 dict"""
        end_q = f"{now.year}Q{(now.month - 1) // 3 + 1}"
        url   = (f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}"
                 f"/json/kr/1/200/{stat}/Q/2022Q1/{end_q}/{item}")
        q2m   = {"Q1": "01", "Q2": "04", "Q3": "07", "Q4": "10"}
        try:
            rows = requests.get(url, timeout=10).json().get("StatisticSearch", {}).get("row", [])
            return {r["TIME"][:4] + q2m[r["TIME"][4:]]: float(r["DATA_VALUE"]) for r in rows}
        except Exception:
            return {}

    base  = _get_m("722Y001", "0101000")
    mort  = _get_m("121Y006", "BECBLA0302")
    m2    = _get_m("161Y006", "BBHA00")
    lead  = _get_m("901Y067", "I16A")
    hloan = _get_q("151Y001", "1100000")

    yms = sorted(set(base))
    # 분기 가계대출 → forward-fill
    last_loan: Optional[float] = None
    rates: dict = {}
    for i, ym in enumerate(yms):
        b  = base.get(ym)
        m  = mort.get(ym)
        b3 = round(b - base.get(yms[i-3], b), 4) if i >= 3 and b is not None else 0.0
        b6 = round(b - base.get(yms[i-6], b), 4) if i >= 6 and b is not None else 0.0
        m2v   = m2.get(ym)
        leadv = lead.get(ym)
        if ym in hloan:
            last_loan = hloan[ym] / 1_000  # 십억→조원
        m2_scaled = m2v / 1_000 if m2v is not None else None  # 십억→조원
        rates[ym] = {
            "기준금리":      b,
            "대출금리":      m,
            "금리변화_3개월": b3,
            "금리변화_6개월": b6,
            "M2잔액":        m2_scaled,
            "경기선행지수":   leadv,
            "가계대출잔액":   last_loan,
        }
    # M2증가율_3개월 계산
    yms_list = sorted(rates)
    for i, ym in enumerate(yms_list):
        prev_ym = yms_list[i - 3] if i >= 3 else None
        cur_m2  = rates[ym].get("M2잔액")
        prv_m2  = rates[prev_ym].get("M2잔액") if prev_ym else None
        if cur_m2 and prv_m2 and prv_m2 != 0:
            rates[ym]["M2증가율_3개월"] = round((cur_m2 - prv_m2) / prv_m2 * 100, 4)
        else:
            rates[ym]["M2증가율_3개월"] = None

    # null 값 forward-fill: 미공표 최신월은 직전 유효값으로 대체
    fill_cols = ["대출금리", "M2잔액", "M2증가율_3개월", "경기선행지수"]
    last_vals: dict = {c: None for c in fill_cols}
    for ym in yms_list:
        for col in fill_cols:
            if rates[ym].get(col) is not None:
                last_vals[col] = rates[ym][col]
            elif last_vals[col] is not None:
                rates[ym][col] = last_vals[col]

    return rates


@app.on_event("startup")
async def startup_event() -> None:
    global _pipeline, _pipeline_trade, _pipeline_jeonse, _pipeline_wolse, _undervalued, _rates

    # 3개 파이프라인 병렬 로딩
    def _load_trade():
        return _load_pipeline_file(PIPELINE_TRADE_PATH) or _load_pipeline_file(PIPELINE_PATH)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        f_trade  = ex.submit(_load_trade)
        f_jeonse = ex.submit(_load_pipeline_file, PIPELINE_JEONSE_PATH)
        f_wolse  = ex.submit(_load_pipeline_file, PIPELINE_WOLSE_PATH)
        _pipeline_trade  = f_trade.result()
        _pipeline_jeonse = f_jeonse.result()
        _pipeline_wolse  = f_wolse.result()

    _pipeline = _pipeline_trade  # 하위호환

    if _pipeline_trade is None:
        raise RuntimeError("pipeline_trade.pkl 없음. python realestate_ml.py 먼저 실행하세요.")

    try:
        _rates = _fetch_rates()
        print(f"✓ 금리 데이터 로드: {len(_rates)}개월")
    except Exception as e:
        print(f"  [경고] 금리 로드 실패: {e}")
        _rates = {}

    if os.path.exists(UNDERVALUED_PATH):
        _undervalued = pd.read_csv(UNDERVALUED_PATH)
        print(f"✓ 저평가 데이터 로드: {len(_undervalued):,}건")

    for name, pl in [("매매", _pipeline_trade), ("전세", _pipeline_jeonse), ("월세", _pipeline_wolse)]:
        if pl:
            print(f"✓ {name} 모델 로드 완료  (저장일: {pl['saved_at']}, 피처: {len(pl['feature_cols'])}개)")


# ── Pydantic 스키마 ───────────────────────────────────────────

class PredictRequest(BaseModel):
    apt_nm:        str            = Field(..., example="래미안블레스티지", description="아파트명")
    exclu_use_ar:  float          = Field(..., example=113.7,            description="전용면적 (㎡)")
    floor:         int            = Field(..., example=33,               description="층")
    sgg_cd:        str            = Field(..., example="11680",          description="시군구 코드")
    build_year:    int            = Field(..., example=2019,             description="건축연도")
    deal_type:     str            = Field("매매", example="매매",        description="거래유형 (매매/전세/월세)")
    deposit:       Optional[float]= Field(None,  example=5000.0,        description="보증금 만원 — 월세 예측 시 필수")
    property_type: int            = Field(0,     example=0,             description="물건유형 (0=아파트,1=연립다세대,2=오피스텔,3=단독다가구)")


class PredictResponse(BaseModel):
    apt_nm:          str
    exclu_use_ar:    float
    floor:           int
    deal_type:       str
    predicted_price: float   # 만원
    lower_bound:     float   # 만원 (95% 하한)
    upper_bound:     float   # 만원 (95% 상한)
    confidence:      float   # 0~1
    db_matched:      bool
    price_label:     str = "매매가"   # "매매가" / "전세 보증금" / "월세"
    price_unit:      str = "만원"


class UndervaluedItem(BaseModel):
    apt_nm:          str
    region:          str
    umd_nm:          str
    sgg_cd:          str
    exclu_use_ar:    float
    floor:           int
    deal_year:       int
    deal_month:      int
    actual_price:    float   # 만원
    predicted_price: float   # 만원
    gap_pct:         float   # 괴리율 (%)
    property_type:   str = "아파트"   # 물건유형 (아파트/연립다세대)
    deal_type:       str = "매매"     # 거래유형 (매매/전세/월세)
    deposit:         Optional[float] = None  # 보증금 만원 (전세/월세 전용)


class TrendPoint(BaseModel):
    year:      int
    month:     int
    avg_price: float   # 만원
    min_price: float
    max_price: float
    count:     int


class TrendResponse(BaseModel):
    apt_nm:       str
    exclu_use_ar: Optional[float]
    months:       int
    data:         List[TrendPoint]


class RentTrendPoint(BaseModel):
    year:             int
    month:            int
    avg_deposit:      float   # 보증금 평균 (만원)
    avg_monthly_rent: float   # 월세 평균 (만원, 전세는 0)
    jeonse_count:     int     # 전세 건수
    wolse_count:      int     # 월세 건수


class RentTrendResponse(BaseModel):
    apt_nm:       str
    exclu_use_ar: Optional[float]
    months:       int
    data:         List[RentTrendPoint]


# ── 내부 헬퍼 ────────────────────────────────────────────────

def _brand_premium(apt_nm: str) -> int:
    for brand, score in BRAND_MAP.items():
        if brand in apt_nm:
            return score
    return 1


def _build_features(req: PredictRequest, pipeline: dict) -> tuple[pd.DataFrame, bool]:
    """
    요청 파라미터 + DB 실거래 이력 + 금리 데이터로 피처 벡터 구성.
    deal_type에 따라 매매/전세/월세 rolling 소스를 다르게 쿼리.
    Returns (X: DataFrame, db_matched: bool)
    """
    feature_cols = pipeline["feature_cols"]
    medians      = pipeline["medians"]
    now          = datetime.now()
    deal_type    = req.deal_type

    feat: dict = {
        "전용면적":        req.exclu_use_ar,
        "평형":            req.exclu_use_ar / 3.305785,
        "층":              req.floor,
        "건축연수":        CURRENT_YEAR - req.build_year,
        "브랜드_프리미엄": _brand_premium(req.apt_nm),
        "거래년도":        now.year,
        "거래월":          now.month,
        "거래분기":        (now.month - 1) // 3 + 1,
        "이사시즌여부":    int(now.month in [2, 3, 8, 9]),
        "명절직전여부":    int(now.month in [1, 9]),
        "지역코드_num":    int(req.sgg_cd),
        "물건유형":        req.property_type,
    }

    # 월세 모델: 보증금 필수 입력
    if deal_type == "월세" and req.deposit is not None:
        feat["보증금"] = req.deposit

    # 거시지표 피처 (현재 월 기준)
    if _rates:
        ym = now.strftime("%Y%m")
        rate_row = _rates.get(ym) or _rates.get(sorted(_rates)[-1])
        if rate_row:
            for col in ["기준금리", "대출금리", "금리변화_3개월", "금리변화_6개월",
                        "M2잔액", "M2증가율_3개월", "가계대출잔액", "경기선행지수"]:
                if rate_row.get(col) is not None:
                    feat[col] = rate_row[col]

    db_matched = False
    ar_lo, ar_hi = req.exclu_use_ar - 5, req.exclu_use_ar + 5

    try:
        with sqlite3.connect(DB_PATH) as conn:

            if deal_type == "매매":
                # ── 단지 매매 rolling ──────────────────────────
                rows = conn.execute(
                    """SELECT CAST(dealAmount AS REAL), CAST(floor AS INT)
                       FROM apt_trade
                       WHERE aptNm=? AND CAST(excluUseAr AS REAL) BETWEEN ? AND ?
                         AND (cdealType IS NULL OR cdealType!='O')
                         AND (dealingGbn IS NULL OR dealingGbn NOT LIKE '%직거래%')
                       ORDER BY dealYear DESC, dealMonth DESC LIMIT 20""",
                    (req.apt_nm, ar_lo, ar_hi),
                ).fetchall()
                if rows:
                    db_matched = True
                    prices = np.array([r[0] for r in rows if r[0]], dtype=float)
                    floors = np.array([r[1] for r in rows if r[1]], dtype=float)
                    feat["단지_직전3개월가"]  = prices[:3].mean()
                    feat["단지_직전6개월가"]  = prices[:6].mean()
                    feat["단지_직전12개월가"] = prices[:12].mean()
                    feat["단지_거래량_3개월"] = float(min(len(prices), 3))
                    p3, p6 = feat["단지_직전3개월가"], feat["단지_직전6개월가"]
                    feat["가격변화율_3개월"] = (p3 - p6) / p6 * 100 if p6 > 0 else 0.0
                    feat["가격변화율_6개월"] = 0.0
                    feat["층비율"] = req.floor / max(floors.max() if len(floors) else req.floor, req.floor, 1)
                    avg_dep = conn.execute(
                        "SELECT AVG(CAST(deposit AS REAL)) FROM apt_rent "
                        "WHERE aptNm=? AND monthlyRent=0 AND CAST(excluUseAr AS REAL) BETWEEN ? AND ?",
                        (req.apt_nm, ar_lo, ar_hi),
                    ).fetchone()[0]
                    if avg_dep and p3 > 0:
                        feat["전세가율"] = float(avg_dep / p3 * 100)
                sgg = conn.execute(
                    "SELECT AVG(CAST(dealAmount AS REAL)) FROM apt_trade "
                    "WHERE sggCd=? AND (cdealType IS NULL OR cdealType!='O') "
                    "GROUP BY dealYear,dealMonth ORDER BY dealYear DESC,dealMonth DESC LIMIT 7",
                    (req.sgg_cd,),
                ).fetchall()
                sgg_p = np.array([r[0] for r in sgg if r[0]], dtype=float)
                if len(sgg_p):
                    feat["시군구_직전3개월가"] = sgg_p[:3].mean()
                    feat["시군구_직전6개월가"] = sgg_p[:6].mean()

            elif deal_type == "전세":
                # ── 단지 전세 보증금 rolling ───────────────────
                rows = conn.execute(
                    """SELECT CAST(deposit AS REAL), CAST(floor AS INT)
                       FROM apt_rent
                       WHERE aptNm=? AND CAST(excluUseAr AS REAL) BETWEEN ? AND ?
                         AND CAST(monthlyRent AS REAL)=0
                       ORDER BY dealYear DESC, dealMonth DESC LIMIT 20""",
                    (req.apt_nm, ar_lo, ar_hi),
                ).fetchall()
                if rows:
                    db_matched = True
                    prices = np.array([r[0] for r in rows if r[0]], dtype=float)
                    floors = np.array([r[1] for r in rows if r[1]], dtype=float)
                    feat["단지_직전3개월가"]  = prices[:3].mean()
                    feat["단지_직전6개월가"]  = prices[:6].mean()
                    feat["단지_직전12개월가"] = prices[:12].mean()
                    feat["단지_거래량_3개월"] = float(min(len(prices), 3))
                    p3, p6 = feat["단지_직전3개월가"], feat["단지_직전6개월가"]
                    feat["가격변화율_3개월"] = (p3 - p6) / p6 * 100 if p6 > 0 else 0.0
                    feat["가격변화율_6개월"] = 0.0
                    feat["층비율"] = req.floor / max(floors.max() if len(floors) else req.floor, req.floor, 1)
                sgg = conn.execute(
                    "SELECT AVG(CAST(deposit AS REAL)) FROM apt_rent "
                    "WHERE sggCd=? AND CAST(monthlyRent AS REAL)=0 "
                    "GROUP BY dealYear,dealMonth ORDER BY dealYear DESC,dealMonth DESC LIMIT 7",
                    (req.sgg_cd,),
                ).fetchall()
                sgg_p = np.array([r[0] for r in sgg if r[0]], dtype=float)
                if len(sgg_p):
                    feat["시군구_직전3개월가"] = sgg_p[:3].mean()
                    feat["시군구_직전6개월가"] = sgg_p[:6].mean()

            elif deal_type == "월세":
                # ── 단지 월세 rolling ──────────────────────────
                rows = conn.execute(
                    """SELECT CAST(monthlyRent AS REAL), CAST(floor AS INT)
                       FROM apt_rent
                       WHERE aptNm=? AND CAST(excluUseAr AS REAL) BETWEEN ? AND ?
                         AND CAST(monthlyRent AS REAL)>0
                       ORDER BY dealYear DESC, dealMonth DESC LIMIT 20""",
                    (req.apt_nm, ar_lo, ar_hi),
                ).fetchall()
                if rows:
                    db_matched = True
                    prices = np.array([r[0] for r in rows if r[0]], dtype=float)
                    floors = np.array([r[1] for r in rows if r[1]], dtype=float)
                    feat["단지_직전3개월가"]  = prices[:3].mean()
                    feat["단지_직전6개월가"]  = prices[:6].mean()
                    feat["단지_직전12개월가"] = prices[:12].mean()
                    feat["단지_거래량_3개월"] = float(min(len(prices), 3))
                    p3, p6 = feat["단지_직전3개월가"], feat["단지_직전6개월가"]
                    feat["가격변화율_3개월"] = (p3 - p6) / p6 * 100 if p6 > 0 else 0.0
                    feat["가격변화율_6개월"] = 0.0
                    feat["층비율"] = req.floor / max(floors.max() if len(floors) else req.floor, req.floor, 1)
                sgg = conn.execute(
                    "SELECT AVG(CAST(monthlyRent AS REAL)) FROM apt_rent "
                    "WHERE sggCd=? AND CAST(monthlyRent AS REAL)>0 "
                    "GROUP BY dealYear,dealMonth ORDER BY dealYear DESC,dealMonth DESC LIMIT 7",
                    (req.sgg_cd,),
                ).fetchall()
                sgg_p = np.array([r[0] for r in sgg if r[0]], dtype=float)
                if len(sgg_p):
                    feat["시군구_직전3개월가"] = sgg_p[:3].mean()
                    feat["시군구_직전6개월가"] = sgg_p[:6].mean()

    except Exception as e:
        print(f"[WARN] DB 조회 오류: {e}")

    # 미설정 피처 → 훈련 median으로 대체
    for col in feature_cols:
        if col not in feat or (isinstance(feat.get(col), float) and np.isnan(feat[col])):
            feat[col] = float(medians.get(col, 0))

    X = pd.DataFrame([{col: feat.get(col, 0.0) for col in feature_cols}])
    return X, db_matched


# ── 엔드포인트 ────────────────────────────────────────────────

@app.post(
    "/predict",
    response_model=PredictResponse,
    summary="아파트 가격 예측",
    tags=["예측"],
)
def predict(req: PredictRequest) -> PredictResponse:
    """
    아파트 기본 정보를 받아 예상 매매가를 반환합니다.

    - **predicted_price**: 예측 매매가 (만원)
    - **lower_bound / upper_bound**: 95% 신뢰 구간 (±2σ)
    - **confidence**: 신뢰도 (1 - σ/μ, 0~1)
    - **db_matched**: DB 실거래 이력 매칭 여부 (false면 median 대체)
    """
    pipeline_map = {"매매": _pipeline_trade, "전세": _pipeline_jeonse, "월세": _pipeline_wolse}
    pipeline = pipeline_map.get(req.deal_type)
    if pipeline is None:
        raise HTTPException(400, f"deal_type='{req.deal_type}' 모델 미로드 (매매/전세/월세)")
    if req.deal_type == "월세" and req.deposit is None:
        raise HTTPException(400, "월세 예측 시 deposit(보증금) 필수")

    X, db_matched = _build_features(req, pipeline)
    preds_arr = np.array([b.predict(X.values) for b in pipeline["boosters"]])
    pred  = float(preds_arr.mean())
    std   = float(preds_arr.std())
    lower = pred - 2 * std
    upper = pred + 2 * std
    conf  = float(max(0.0, 1.0 - std / pred)) if pred > 0 else 0.0

    label_map = {"매매": "매매가", "전세": "전세 보증금", "월세": "월세"}

    return PredictResponse(
        apt_nm=req.apt_nm,
        exclu_use_ar=req.exclu_use_ar,
        floor=req.floor,
        deal_type=req.deal_type,
        predicted_price=round(pred),
        lower_bound=round(max(lower, 0)),
        upper_bound=round(upper),
        confidence=round(conf, 4),
        db_matched=db_matched,
        price_label=label_map.get(req.deal_type, "매매가"),
    )


@app.get(
    "/undervalued",
    response_model=List[UndervaluedItem],
    summary="저평가 단지 목록",
    tags=["분석"],
)
def undervalued(
    region:        Optional[str]   = Query(None, example="11680",  description="시군구 코드 또는 시도 앞 2자리 (생략 시 전국)"),
    deal_type:     Optional[str]   = Query(None, example="매매",   description="거래유형 필터 (매매/전세/월세)"),
    property_type: Optional[str]   = Query(None, example="아파트", description="물건유형 필터 (아파트/연립다세대)"),
    max_gap:       Optional[float] = Query(None, example=-10,      description="괴리율 상한 (예: -10 → -10% 이하만)"),
    limit:         int             = Query(20,   ge=1, le=200,     description="반환 건수"),
) -> List[UndervaluedItem]:
    if _undervalued is None or _undervalued.empty:
        raise HTTPException(404, "저평가 데이터 없음. python realestate_ml.py 실행 후 재시작하세요.")

    df = _undervalued.copy()

    # 공공임대·불완전 레코드 제외
    if "단지명" in df.columns:
        df = df[~df["단지명"].str.contains("임대|LH|SH|공공", na=False, regex=True)]
        # 주소번지만 있는 이름 제외: (82), (643-9), 11680_일원동 등
        df = df[~df["단지명"].str.match(r'^\(?\d+[\-\d]*\)?$|^\d{5}_', na=False)]
    # 층 데이터 없는 레코드 제외 (불완전한 거래 데이터)
    if "층" in df.columns:
        df = df[pd.to_numeric(df["층"], errors="coerce").fillna(0) > 0]
    # 거래유형별 최소 실거래가 필터 (이상 거래 제외)
    if "실거래가_만원" in df.columns and "거래유형" in df.columns:
        min_price = df["거래유형"].map({"매매": 2000, "전세": 500, "월세": 10})
        df = df[df["실거래가_만원"] >= min_price.fillna(0)]

    if region:
        if "sggCd" not in df.columns:
            raise HTTPException(400, "sggCd 컬럼 없음. 모델 재학습 후 재시작하세요.")
        sgg = df["sggCd"].astype(str)
        df = df[sgg.str.startswith(str(region))] if len(str(region)) <= 2 else df[sgg == str(region)]
        if df.empty:
            raise HTTPException(404, f"region={region} 저평가 단지 없음")

    if deal_type and "거래유형" in df.columns:
        df = df[df["거래유형"] == deal_type]

    if property_type and "물건유형" in df.columns:
        df = df[df["물건유형"] == property_type]

    if "예측가_만원" in df.columns:
        df = df[df["예측가_만원"] > 0]
    if "괴리율_%" in df.columns:
        # max_gap: 괴리율 상한 (예: -10 → gap이 -10% 이하인 것만, 즉 10% 이상 저평가)
        ceiling = max_gap if max_gap is not None else -1
        df = df[(df["괴리율_%"] <= ceiling) & (df["괴리율_%"] >= -100)]

    df = df.sort_values("괴리율_%").head(limit)

    return [
        UndervaluedItem(
            apt_nm=str(r.get("단지명", "")),
            region=str(v if not pd.isna(v := r.get("지역명")) and v else SGG_NAMES.get(str(r.get("sggCd", "")), "")),
            umd_nm=str(r.get("읍면동") or ""),
            sgg_cd=str(r.get("sggCd", "")),
            exclu_use_ar=float(r.get("전용면적", 0) or 0),
            floor=int(r.get("층", 0) if pd.notna(r.get("층", 0)) else 0),
            deal_year=int(r.get("거래년도", 0)),
            deal_month=int(r.get("거래월", 0)),
            actual_price=float(r.get("실거래가_만원", 0)),
            predicted_price=float(r.get("예측가_만원", 0)),
            gap_pct=float(r.get("괴리율_%", 0)),
            property_type=str(r.get("물건유형", "아파트")),
            deal_type=str(r.get("거래유형", "매매")),
            deposit=float(r["보증금"]) if "보증금" in r and pd.notna(r.get("보증금")) else None,
        )
        for _, r in df.iterrows()
    ]


@app.get(
    "/trend",
    response_model=TrendResponse,
    summary="아파트 실거래가 추이",
    tags=["분석"],
)
def trend(
    apt_nm:       str            = Query(...,  example="래미안블레스티지", description="아파트명 (부분 일치)"),
    exclu_use_ar: Optional[float]= Query(None, example=113.7,            description="전용면적 ±5㎡ 필터 (생략 시 전체)"),
    months:       int            = Query(12,   ge=1, le=36,              description="조회 개월 수"),
) -> TrendResponse:
    """
    최근 N개월 실거래가 월별 추이를 반환합니다.
    (직거래·계약해제 제외)
    """
    area_params_base: list = [f"%{apt_nm}%"]
    area_sql = ""
    if exclu_use_ar is not None:
        area_sql = "AND CAST(excluUseAr AS REAL) BETWEEN ? AND ?"
        area_params_base += [exclu_use_ar - 5, exclu_use_ar + 5]

    excl_filter = "(cdealType IS NULL OR cdealType != 'O') AND (dealingGbn IS NULL OR dealingGbn NOT LIKE '%직거래%')"

    def _sub(table: str, nm_col: str) -> str:
        return f"""
        SELECT dealYear, dealMonth, CAST(dealAmount AS REAL) AS amount
        FROM {table}
        WHERE {nm_col} LIKE ?
          {area_sql}
          AND {excl_filter}"""

    query = f"""
        SELECT dealYear, dealMonth,
               AVG(amount) AS avg_price,
               MIN(amount) AS min_price,
               MAX(amount) AS max_price,
               COUNT(*) AS cnt
        FROM (
            {_sub('apt_trade',       'aptNm')}
            UNION ALL
            {_sub('villa_trade',     'mhouseNm')}
            UNION ALL
            {_sub('officetel_trade', 'offiNm')}
        )
        GROUP BY dealYear, dealMonth
        ORDER BY dealYear DESC, dealMonth DESC
        LIMIT ?
    """
    area_params = area_params_base * 3 + [months]

    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(query, area_params).fetchall()
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")

    if not rows:
        raise HTTPException(404, f"'{apt_nm}' 거래 데이터 없음")

    rows_sorted = sorted(rows, key=lambda r: (r[0], r[1]))
    return TrendResponse(
        apt_nm=apt_nm,
        exclu_use_ar=exclu_use_ar,
        months=len(rows_sorted),
        data=[
            TrendPoint(
                year=int(r[0]),
                month=int(r[1]),
                avg_price=round(float(r[2])),
                min_price=round(float(r[3])),
                max_price=round(float(r[4])),
                count=int(r[5]),
            )
            for r in rows_sorted
        ],
    )


@app.get(
    "/rent_trend",
    response_model=RentTrendResponse,
    summary="전월세 보증금·월세 추이",
    tags=["분석"],
)
def rent_trend(
    apt_nm:       str            = Query(...,  example="래미안블레스티지", description="아파트명 (부분 일치)"),
    exclu_use_ar: Optional[float]= Query(None, example=113.7,            description="전용면적 ±5㎡ 필터"),
    months:       int            = Query(12,   ge=1, le=36,              description="조회 개월 수"),
) -> RentTrendResponse:
    area_params: list = [f"%{apt_nm}%"]
    area_sql = ""
    if exclu_use_ar is not None:
        area_sql = "AND CAST(excluUseAr AS REAL) BETWEEN ? AND ?"
        area_params += [exclu_use_ar - 5, exclu_use_ar + 5]

    query = f"""
        SELECT dealYear, dealMonth,
               AVG(CAST(deposit AS REAL))       AS avg_deposit,
               AVG(CASE WHEN CAST(monthlyRent AS REAL) > 0
                        THEN CAST(monthlyRent AS REAL) END) AS avg_monthly_rent,
               SUM(CASE WHEN CAST(monthlyRent AS REAL) = 0 THEN 1 ELSE 0 END) AS jeonse_count,
               SUM(CASE WHEN CAST(monthlyRent AS REAL) > 0 THEN 1 ELSE 0 END) AS wolse_count
        FROM apt_rent
        WHERE aptNm LIKE ?
          {area_sql}
        GROUP BY dealYear, dealMonth
        ORDER BY dealYear DESC, dealMonth DESC
        LIMIT ?
    """
    area_params.append(months)

    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(query, area_params).fetchall()
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")

    if not rows:
        raise HTTPException(404, f"'{apt_nm}' 전월세 데이터 없음")

    rows_sorted = sorted(rows, key=lambda r: (r[0], r[1]))
    return RentTrendResponse(
        apt_nm=apt_nm,
        exclu_use_ar=exclu_use_ar,
        months=len(rows_sorted),
        data=[
            RentTrendPoint(
                year=int(r[0]),
                month=int(r[1]),
                avg_deposit=round(float(r[2]) if r[2] else 0),
                avg_monthly_rent=round(float(r[3]) if r[3] else 0),
                jeonse_count=int(r[4]),
                wolse_count=int(r[5]),
            )
            for r in rows_sorted
        ],
    )


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse("dashboard.html", media_type="text/html")


@app.get("/regions", tags=["분석"], summary="전체 시군구 목록")
def get_regions() -> list[dict]:
    """DB에 존재하는 모든 시군구 코드 + 지역명 반환"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT DISTINCT sggCd FROM apt_trade WHERE sggCd IS NOT NULL ORDER BY sggCd"
        ).fetchall()

    result = []
    for (raw,) in rows:
        cd = str(raw).strip()
        if cd:
            result.append({"sgg_cd": cd, "name": SGG_NAMES.get(cd, cd)})
    return result


@app.get("/health", tags=["시스템"])
def health() -> dict:
    """서버 상태 확인"""
    def _pl_info(pl):
        if pl is None:
            return {"loaded": False}
        return {"loaded": True, "n_folds": len(pl["boosters"]),
                "feature_count": len(pl["feature_cols"]), "saved_at": pl.get("saved_at")}
    return {
        "status":             "ok",
        "models": {
            "매매": _pl_info(_pipeline_trade),
            "전세": _pl_info(_pipeline_jeonse),
            "월세": _pl_info(_pipeline_wolse),
        },
        "rates_loaded":       bool(_rates),
        "rates_months":       len(_rates) if _rates else 0,
        "macro_features":     {k: (_rates.get(sorted(_rates)[-1], {}).get(k) if _rates else None)
                               for k in ["기준금리","대출금리","M2잔액","가계대출잔액","경기선행지수"]},
        "undervalued_loaded": _undervalued is not None,
        "undervalued_count":  len(_undervalued) if _undervalued is not None else 0,
    }
