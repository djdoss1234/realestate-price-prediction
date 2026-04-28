# 부동산 실거래가 예측 & 저평가 탐지 시스템

국토교통부 실거래가 공개시스템 데이터를 기반으로 아파트·연립다세대·오피스텔·단독다가구의 **매매·전세·월세** 가격을 예측하고, 시세 대비 저평가된 매물을 자동으로 탐지하는 ML 파이프라인 + REST API + 대시보드입니다.

## 주요 기능

- **실거래가 수집**: 국토교통부 OPEN API로 전국 시군구 실거래 데이터 자동 수집
- **LightGBM 예측 모델**: 매매·전세·월세 3개 모델, 5-Fold K-Fold 앙상블
- **저평가 탐지**: 예측가 대비 괴리율 계산 → 시세 대비 저렴한 매물 자동 탐지
- **REST API**: FastAPI 기반, 지역·거래유형·물건유형별 필터링
- **대시보드**: 카카오맵 연동 지도 시각화, 시도/시군구 2단계 지역 선택

## 기술 스택

| 영역 | 기술 |
|------|------|
| 언어 | Python 3.13 |
| ML | LightGBM, SHAP, scikit-learn |
| API | FastAPI, Uvicorn |
| 데이터 | SQLite, Pandas |
| 거시지표 | 한국은행 ECOS API (기준금리·대출금리·M2·가계대출·경기선행지수) |
| 지도 | 카카오맵 JavaScript SDK |
| 수집 자동화 | cron + Python |

## 피처 목록 (30개)

| 카테고리 | 피처 |
|----------|------|
| 물건 | 전용면적, 평형, 층, 건축연수, 층비율, 물건유형 |
| 단지 | 브랜드_프리미엄, 단지_직전3·6·12개월가, 단지_거래량_3개월 |
| 지역 | 지역코드_num, 시군구_직전3·6개월가 |
| 시세 | 가격변화율_3·6개월, 전세가율 |
| 시간 | 거래년도, 거래월, 거래분기, 이사시즌여부, 명절직전여부 |
| 거시 | 기준금리, 대출금리, 금리변화_3·6개월, M2잔액, M2증가율_3개월, 가계대출잔액, 경기선행지수 |

## 실행 방법

### 1. 환경 설정

```bash
python -m venv venv
source venv/bin/activate
pip install lightgbm fastapi uvicorn pandas scikit-learn shap python-dotenv requests tqdm
```

### 2. API 키 설정

```bash
cp .env.example .env
# .env 파일에 키 입력
```

`.env` 형식:
```
MOLIT_API_KEY=your_molit_key      # 국토교통부 실거래가 API
ECOS_API_KEY=your_ecos_key        # 한국은행 ECOS API
KAKAO_MAP_KEY=your_kakao_key      # 카카오맵 (dashboard.html에 직접 입력)
```

### 3. 데이터 수집

```bash
python molit_collector.py
```

### 4. 모델 학습

```bash
python realestate_ml.py
# 완료 후 pipeline_trade.pkl, pipeline_jeonse.pkl, pipeline_wolse.pkl 생성
```

### 5. API 서버 시작

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

### 6. 대시보드 열기

`dashboard.html`을 브라우저에서 열거나 HTTP 서버로 서빙

---

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 및 모델 로드 여부 |
| GET | `/undervalued` | 저평가 매물 목록 |
| GET | `/predict` | 단건 가격 예측 |
| GET | `/regions` | 시군구 목록 |
| GET | `/search` | 단지명 검색 |
| GET | `/history` | 실거래 이력 조회 |

### `/undervalued` 파라미터

| 파라미터 | 설명 | 예시 |
|----------|------|------|
| `region` | 시도(앞 2자리) 또는 시군구 코드 | `11` (서울), `11680` (강남구) |
| `deal_type` | 거래유형 | `매매` / `전세` / `월세` |
| `property_type` | 물건유형 | `아파트` / `연립다세대` |
| `max_gap` | 괴리율 상한 (음수일수록 더 저평가) | `-15` |
| `limit` | 결과 개수 | `20` |

---

## 스크린샷

### 대시보드 메인

> 전국 저평가 매물을 지도에 표시. 시도 버튼 → 시군구 드롭다운 2단계 필터링

![대시보드](screenshots/dashboard.png)

### 저평가 매물 카드

> 단지명·지역·면적·층수·실거래가·예측가·괴리율·보증금 표시

![매물카드](screenshots/card.png)

### SHAP 피처 중요도

> 가격 예측에 영향을 미친 피처 순위 (단지 직전 거래가가 가장 높은 영향)

![SHAP](screenshots/shap_importance.png)

---

## 자동 수집 (cron)

매일 자정 미수집 지역 토지 실거래 데이터 자동 보완:

```bash
# crontab -e
0 0 * * * /path/to/venv/bin/python /path/to/morning_collect.py >> morning_collect.log 2>&1
```

---

## 모델 성능 (v8, n_estimators=500)

| 모델 | MAE | R² | 학습 데이터 |
|------|-----|----|------------|
| 매매 | — | — | 1,816,283건 |
| 전세 | — | — | 2,638,218건 |
| 월세 | 2만원 | 0.9681 | — |

---

## 데이터 출처

- [국토교통부 실거래가 공개시스템](https://rtms.molit.go.kr)
- [한국은행 ECOS](https://ecos.bok.or.kr)
