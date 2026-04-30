# 부동산 실거래가 예측 & 저평가 탐지 시스템

국토교통부 실거래가 + 16개 외부 API를 수집·통합하여 아파트·연립다세대·오피스텔·단독다가구의 **매매·전세·월세** 가격을 예측하고, 시세 대비 저평가된 매물을 자동 탐지하는 ML 파이프라인 + REST API + 대시보드입니다.

## 기술 스택

| 영역 | 기술 |
|------|------|
| 언어 | Python 3.13 |
| ML | LightGBM, SHAP, scikit-learn |
| API 서버 | FastAPI, Uvicorn |
| 보안 | JWT, Rate Limiting (SlowAPI), CORS |
| 데이터베이스 | SQLite (기본) / PostgreSQL (운영) |
| 캐시 | Redis (예측 결과 1시간 TTL) |
| 수집 자동화 | Apache Airflow 2.x (DAG) |
| 지도 | 카카오맵 JavaScript SDK |
| 알림 | Slack Webhook |

## 데이터 소스 (16개 API)

| 수집기 | 출처 | 수집 내용 | 테이블 |
|--------|------|-----------|--------|
| molit_collector | 국토부 RTMS | 실거래가 (매매·전세·월세) | apt_trade, apt_rent, villa_*, officetel_*, house_*, land_trade 등 |
| ecos_collector | 한국은행 ECOS | 기준금리·대출금리·M2·경기선행지수 | ecos_macro |
| kosis_collector | 통계청 KOSIS | 인구·세대수·고용률·지역소득 | kosis_population, kosis_employment, kosis_household, kosis_income |
| kakao_poi_collector | 카카오맵 API | 아파트 단지 좌표 (지하철·편의시설 연계) | kakao_poi |
| subscription_collector | 청약홈 API | 청약 공고·결과·경쟁률 | subscription_notice, subscription_result |
| weather_collector | 기상청 API | 기상특보 발령 이력 (홍수·태풍·폭설) | weather_risk, weather_anomaly |
| land_price_collector | 국토부 공시지가 | 표준지·개별 공시지가, 시군구 평균 | land_price_standard, land_price_individual, land_price_sgg_avg |
| school_collector | NEIS API | 전국 학교 정보·학군 점수 | school_info, school_district_score |
| academy_collector | NEIS API | 학원 정보·통계 | academy_info, academy_stats |
| commercial_district_collector | 소상공인진흥공단 | 반경 1km 내 상가업소 | commercial_district |
| crime_collector | 경찰청 | 시도별 범죄 발생·검거 현황 | crime_stats |
| lh_rental_collector | LH | 공공임대주택 공급정보 | lh_rental |
| unsold_house_collector | 국토부 | 시군구별 미분양주택 현황 | unsold_house_monthly |
| building_registry_collector | 국토부 | 건축물대장 (연면적·층수·용도) | building_registry |
| apt_complex_collector | 한국부동산원 | 공동주택단지 기본정보 | apt_complex |
| apt_complex_identity_collector | 한국부동산원 | 단지코드 ↔ 단지명 매핑 | kapt_identity |
| seoul_population_collector | 서울시 | 서울 생활인구 (행정동별) | seoul_living_pop |

## 아키텍처

```
┌─────────────────────────────────────────┐
│           데이터 수집 레이어              │
│  molit_collector  + 16개 외부 API 수집기 │
│  Airflow DAG (매일 02:00 / 매주 월 03:00)│
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│              데이터베이스                │
│   SQLite (개발) / PostgreSQL (운영)      │
│   40개 테이블, ~1.8GB                   │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│             ML 파이프라인                │
│  LightGBM × 3 (매매·전세·월세)           │
│  5-Fold 앙상블, 30개 피처               │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│          FastAPI REST API               │
│  JWT 인증 · Rate Limit · CORS           │
│  Redis 캐시 (예측 1h, 저평가 30m)       │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│            대시보드 (HTML)               │
│   카카오맵 지도 + 저평가 매물 카드       │
└─────────────────────────────────────────┘
```

## 실행 방법

### 1. 환경 설정

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. API 키 설정

```bash
cp .env.example .env
# .env 파일 편집
```

`.env` 예시:
```env
# 국토교통부 실거래가 API (data.go.kr)
MOLIT_API_KEY=your_key_here
DATA_GO_KR_API_KEY=your_key_here

# 한국은행 ECOS API
ECOS_API_KEY=your_key_here

# NEIS 교육통계 API
NEIS_API_KEY=your_key_here

# 카카오 REST API
KAKAO_REST_API_KEY=your_key_here

# Slack 알림 (선택)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# PostgreSQL (선택, 미설정 시 SQLite 사용)
DATABASE_URL=postgresql://user:pass@localhost:5432/realestate

# Redis (선택, 미설정 시 캐시 비활성화)
REDIS_URL=redis://localhost:6379/0
REDIS_ENABLED=true
```

### 3. 데이터 수집

```bash
# 전체 수집기 실행
python run_collectors.py all

# 개별 수집기 실행
python run_collectors.py ecos
python run_collectors.py kosis
python run_collectors.py apt_identity
# 기타: apt_complex, building, subscription, weather, academy,
#        seoul_pop, commercial, lh_rental, crime, school, land_price,
#        unsold, kakao
```

### 4. 실거래가 수집 (국토부 RTMS)

```bash
python molit_collector.py
```

### 5. ML 모델 학습

```bash
python realestate_ml.py
# 완료 후 pipeline_trade.pkl, pipeline_jeonse.pkl, pipeline_wolse.pkl 생성
```

### 6. API 서버 실행

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
# API 문서: http://localhost:8000/docs
```

### 7. 대시보드

`dashboard.html`을 브라우저에서 열거나:
```bash
python -m http.server 3000
# http://localhost:3000/dashboard.html
```

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태·모델 로드·Redis 캐시 현황 |
| GET | `/undervalued` | 저평가 매물 목록 (지역·거래유형·괴리율 필터) |
| GET | `/predict` | 단건 가격 예측 |
| GET | `/regions` | 시도·시군구 목록 |
| GET | `/search` | 단지명 검색 |
| GET | `/history` | 실거래 이력 조회 |
| POST | `/auth/token` | JWT 토큰 발급 |
| DELETE | `/admin/cache` | 전체 캐시 초기화 (관리자) |

## Airflow DAG

```
dags/
├── daily_trade_dag.py   # 매일 02:00 — 실거래가 수집 + 주말 재학습
└── weekly_stats_dag.py  # 매주 월 03:00 — 통계청·ECOS·공시지가·학교·기상 등
```

실패 시 Slack `#realestate-alerts` 채널로 자동 알림.

## 모델 피처 (30개)

| 카테고리 | 피처 |
|----------|------|
| 물건 | 전용면적, 평형, 층, 건축연수, 층비율, 물건유형 |
| 단지 | 브랜드_프리미엄, 단지_직전3·6·12개월가, 단지_거래량_3개월 |
| 지역 | 지역코드_num, 시군구_직전3·6개월가 |
| 시세 | 가격변화율_3·6개월, 전세가율 |
| 시간 | 거래년도, 거래월, 거래분기, 이사시즌여부, 명절직전여부 |
| 거시 | 기준금리, 대출금리, 금리변화_3·6개월, M2잔액, M2증가율_3개월, 가계대출잔액, 경기선행지수 |

## 스크린샷

### 대시보드 메인
전국 저평가 매물을 지도에 표시. 시도 버튼 → 시군구 드롭다운 2단계 필터링.

![대시보드](screenshots/dashboard.png)

### 저평가 매물 카드
단지명·지역·면적·층수·실거래가·예측가·괴리율 표시.

![매물카드](screenshots/card.png)

### SHAP 피처 중요도
단지 직전 거래가가 예측에 가장 큰 영향.

![SHAP](screenshots/shap_importance.png)

## 데이터 출처

- [국토교통부 실거래가 공개시스템](https://rtms.molit.go.kr)
- [한국은행 ECOS](https://ecos.bok.or.kr)
- [통계청 KOSIS](https://kosis.kr)
- [공공데이터포털](https://www.data.go.kr)
- [NEIS 교육통계](https://open.neis.go.kr)
- [카카오 개발자](https://developers.kakao.com)
