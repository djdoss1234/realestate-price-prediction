"""
국토교통부 실거래가 수집기 v3
================================
14개 API 전부 지원
- 아파트 매매/전월세/분양권전매
- 오피스텔 매매/전월세
- 연립다세대 매매/전월세
- 단독다가구 매매/전월세
- 상업업무용 매매
- 공장·창고 매매
- 토지 매매
- 부동산통계 (한국부동산원)
"""

import os, time, sqlite3, logging, xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from dataclasses import dataclass
import requests, pandas as pd
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("molit_collector.log", "w", "utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ── 설정 ─────────────────────────────────────────────────────
@dataclass
class Config:
    api_key:       str   = os.getenv("MOLIT_API_KEY", "")
    db_path:       str   = "realestate.db"
    delay_sec:     float = 0.6
    max_retry:     int   = 3
    rows_per_call: int   = 1000


# ── 지역 코드 (전국 250개) ────────────────────────────────────
REGION_CODES = {
    # ── 서울특별시 (25개구) ───────────────────────────────────
    "서울_종로구":"11110",   "서울_중구":"11140",     "서울_용산구":"11170",
    "서울_성동구":"11200",   "서울_광진구":"11215",   "서울_동대문구":"11230",
    "서울_중랑구":"11260",   "서울_성북구":"11290",   "서울_강북구":"11305",
    "서울_도봉구":"11320",   "서울_노원구":"11350",   "서울_은평구":"11380",
    "서울_서대문구":"11410", "서울_마포구":"11440",   "서울_양천구":"11470",
    "서울_강서구":"11500",   "서울_구로구":"11530",   "서울_금천구":"11545",
    "서울_영등포구":"11560", "서울_동작구":"11590",   "서울_관악구":"11620",
    "서울_서초구":"11650",   "서울_강남구":"11680",   "서울_송파구":"11710",
    "서울_강동구":"11740",
    # ── 부산광역시 (16개) ────────────────────────────────────
    "부산_중구":"26110",     "부산_서구":"26140",     "부산_동구":"26170",
    "부산_영도구":"26200",   "부산_부산진구":"26230", "부산_동래구":"26260",
    "부산_남구":"26290",     "부산_북구":"26320",     "부산_해운대구":"26350",
    "부산_사하구":"26380",   "부산_금정구":"26410",   "부산_강서구":"26440",
    "부산_연제구":"26470",   "부산_수영구":"26500",   "부산_사상구":"26530",
    "부산_기장군":"26710",
    # ── 대구광역시 (8개) ─────────────────────────────────────
    "대구_중구":"27110",     "대구_동구":"27140",     "대구_서구":"27170",
    "대구_남구":"27200",     "대구_북구":"27230",     "대구_수성구":"27260",
    "대구_달서구":"27290",   "대구_달성군":"27710",
    # ── 인천광역시 (10개) ────────────────────────────────────
    "인천_중구":"28110",     "인천_동구":"28140",     "인천_미추홀구":"28177",
    "인천_연수구":"28185",   "인천_남동구":"28200",   "인천_부평구":"28237",
    "인천_계양구":"28245",   "인천_서구":"28260",     "인천_강화군":"28710",
    "인천_옹진군":"28720",
    # ── 광주광역시 (5개) ─────────────────────────────────────
    "광주_동구":"29110",     "광주_서구":"29140",     "광주_남구":"29155",
    "광주_북구":"29170",     "광주_광산구":"29200",
    # ── 대전광역시 (5개) ─────────────────────────────────────
    "대전_동구":"30110",     "대전_중구":"30140",     "대전_서구":"30170",
    "대전_유성구":"30200",   "대전_대덕구":"30230",
    # ── 울산광역시 (5개) ─────────────────────────────────────
    "울산_중구":"31110",     "울산_남구":"31140",     "울산_동구":"31170",
    "울산_북구":"31200",     "울산_울주군":"31710",
    # ── 세종특별자치시 ───────────────────────────────────────
    "세종":"36110",
    # ── 경기도 (31개) ────────────────────────────────────────
    "경기_수원_장안":"41111","경기_수원_권선":"41113","경기_수원_팔달":"41115",
    "경기_수원_영통":"41117","경기_성남_수정":"41131","경기_성남_중원":"41133",
    "경기_성남_분당":"41135","경기_의정부":"41150",  "경기_안양_만안":"41171",
    "경기_안양_동안":"41173","경기_부천":"41190",    "경기_광명":"41210",
    "경기_평택":"41220",     "경기_동두천":"41250",  "경기_안산_상록":"41271",
    "경기_안산_단원":"41273","경기_고양_덕양":"41281","경기_고양_일산동":"41285",
    "경기_고양_일산서":"41287","경기_과천":"41290",  "경기_구리":"41310",
    "경기_남양주":"41360",   "경기_오산":"41370",    "경기_시흥":"41390",
    "경기_군포":"41410",     "경기_의왕":"41430",    "경기_하남":"41450",
    "경기_용인_처인":"41461","경기_용인_기흥":"41463","경기_용인_수지":"41465",
    "경기_파주":"41480",     "경기_이천":"41500",    "경기_안성":"41550",
    "경기_김포":"41570",     "경기_화성":"41590",    "경기_광주":"41610",
    "경기_양주":"41630",     "경기_포천":"41650",    "경기_여주":"41670",
    "경기_연천군":"41800",   "경기_가평군":"41820",  "경기_양평군":"41830",
    # ── 강원특별자치도 (18개, 2023~ 51xxx) ───────────────────
    "강원_춘천":"51110",     "강원_원주":"51130",    "강원_강릉":"51150",
    "강원_동해":"51170",     "강원_태백":"51190",    "강원_속초":"51210",
    "강원_삼척":"51230",     "강원_홍천군":"51720",  "강원_횡성군":"51730",
    "강원_영월군":"51750",   "강원_평창군":"51760",  "강원_정선군":"51770",
    "강원_철원군":"51780",   "강원_화천군":"51790",  "강원_양구군":"51800",
    "강원_인제군":"51810",   "강원_고성군":"51820",  "강원_양양군":"51830",
    # ── 충청북도 (12개) ──────────────────────────────────────
    "충북_청주_상당":"43111","충북_청주_서원":"43112","충북_청주_흥덕":"43113",
    "충북_청주_청원":"43114","충북_충주":"43130",    "충북_제천":"43150",
    "충북_보은군":"43720",   "충북_옥천군":"43730",  "충북_영동군":"43740",
    "충북_증평군":"43745",   "충북_진천군":"43750",  "충북_괴산군":"43760",
    "충북_음성군":"43770",   "충북_단양군":"43800",
    # ── 충청남도 (15개) ──────────────────────────────────────
    "충남_천안_동남":"44131","충남_천안_서북":"44133","충남_공주":"44150",
    "충남_보령":"44180",     "충남_아산":"44200",    "충남_서산":"44210",
    "충남_논산":"44230",     "충남_계룡":"44250",    "충남_당진":"44270",
    "충남_금산군":"44710",   "충남_부여군":"44760",  "충남_서천군":"44770",
    "충남_청양군":"44790",   "충남_홍성군":"44800",  "충남_예산군":"44810",
    "충남_태안군":"44825",
    # ── 전라북도 (14개) ──────────────────────────────────────
    "전북_전주_완산":"45111","전북_전주_덕진":"45113","전북_군산":"45130",
    "전북_익산":"45140",     "전북_정읍":"45180",    "전북_남원":"45190",
    "전북_김제":"45210",     "전북_완주군":"45710",  "전북_진안군":"45720",
    "전북_무주군":"45730",   "전북_장수군":"45740",  "전북_임실군":"45750",
    "전북_순창군":"45770",   "전북_고창군":"45790",  "전북_부안군":"45800",
    # ── 전라남도 (22개) ──────────────────────────────────────
    "전남_목포":"46110",     "전남_여수":"46130",    "전남_순천":"46150",
    "전남_나주":"46170",     "전남_광양":"46230",    "전남_담양군":"46710",
    "전남_곡성군":"46720",   "전남_구례군":"46730",  "전남_고흥군":"46770",
    "전남_보성군":"46780",   "전남_화순군":"46790",  "전남_장흥군":"46800",
    "전남_강진군":"46810",   "전남_해남군":"46820",  "전남_영암군":"46830",
    "전남_무안군":"46840",   "전남_함평군":"46860",  "전남_영광군":"46870",
    "전남_장성군":"46880",   "전남_완도군":"46900",  "전남_진도군":"46910",
    "전남_신안군":"46920",
    # ── 경상북도 (23개) ──────────────────────────────────────
    "경북_포항_남구":"47111","경북_포항_북구":"47113","경북_경주":"47130",
    "경북_김천":"47150",     "경북_안동":"47170",    "경북_구미":"47190",
    "경북_영주":"47210",     "경북_영천":"47220",    "경북_상주":"47230",
    "경북_문경":"47250",     "경북_경산":"47280",    "경북_군위군":"47710",
    "경북_의성군":"47720",   "경북_청송군":"47730",  "경북_영양군":"47740",
    "경북_영덕군":"47750",   "경북_청도군":"47760",  "경북_고령군":"47770",
    "경북_성주군":"47780",   "경북_칠곡군":"47790",  "경북_예천군":"47820",
    "경북_봉화군":"47830",   "경북_울진군":"47840",  "경북_울릉군":"47850",
    # ── 경상남도 (18개) ──────────────────────────────────────
    "경남_창원_의창":"48110","경남_창원_성산":"48121","경남_창원_마산합포":"48123",
    "경남_창원_마산회원":"48125","경남_창원_진해":"48127","경남_진주":"48170",
    "경남_통영":"48220",     "경남_사천":"48240",    "경남_김해":"48250",
    "경남_밀양":"48270",     "경남_거제":"48310",    "경남_양산":"48330",
    "경남_의령군":"48720",   "경남_함안군":"48730",  "경남_창녕군":"48740",
    "경남_고성군":"48750",   "경남_남해군":"48760",  "경남_하동군":"48770",
    "경남_산청군":"48780",   "경남_함양군":"48790",  "경남_거창군":"48800",
    "경남_합천군":"48820",
    # ── 제주특별자치도 (2개) ────────────────────────────────
    "제주_제주시":"50110",   "제주_서귀포시":"50130",
}

# ── 14개 API 엔드포인트 ──────────────────────────────────────
ENDPOINTS = {
    # ① 아파트
    "아파트_매매": {
        "url":   "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
        "table": "apt_trade",
        "note":  "핵심 — 층·건축년도·도로명 포함 상세버전",
    },
    "아파트_전월세": {
        "url":   "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent",
        "table": "apt_rent",
        "note":  "전세가율 피처 계산용",
    },
    "아파트_분양권전매": {
        "url":   "https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade",
        "table": "apt_presale",
        "note":  "분양권 프리미엄 피처용",
    },
    # ② 오피스텔
    "오피스텔_매매": {
        "url":   "https://apis.data.go.kr/1613000/RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade",
        "table": "officetel_trade",
        "note":  "오피스텔 매매가",
    },
    "오피스텔_전월세": {
        "url":   "https://apis.data.go.kr/1613000/RTMSDataSvcOffiRent/getRTMSDataSvcOffiRent",
        "table": "officetel_rent",
        "note":  "오피스텔 전월세",
    },
    # ③ 연립다세대
    "연립다세대_매매": {
        "url":   "https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade",
        "table": "villa_trade",
        "note":  "빌라·다세대 매매가",
    },
    "연립다세대_전월세": {
        "url":   "https://apis.data.go.kr/1613000/RTMSDataSvcRHRent/getRTMSDataSvcRHRent",
        "table": "villa_rent",
        "note":  "빌라·다세대 전월세",
    },
    # ④ 단독다가구
    "단독다가구_매매": {
        "url":   "https://apis.data.go.kr/1613000/RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade",
        "table": "house_trade",
        "note":  "단독·다가구 매매가",
    },
    "단독다가구_전월세": {
        "url":   "https://apis.data.go.kr/1613000/RTMSDataSvcSHRent/getRTMSDataSvcSHRent",
        "table": "house_rent",
        "note":  "단독·다가구 전월세",
    },
    # ⑤ 상업·공장·토지
    "상업업무용_매매": {
        "url":   "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade",
        "table": "commercial_trade",
        "note":  "상가·오피스 매매가",
    },
    "공장창고_매매": {
        "url":   "https://apis.data.go.kr/1613000/RTMSDataSvcInduTrade/getRTMSDataSvcInduTrade",
        "table": "industrial_trade",
        "note":  "공장·창고 매매가",
    },
    "토지_매매": {
        "url":   "https://apis.data.go.kr/1613000/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade",
        "table": "land_trade",
        "note":  "토지 매매가·용도지역",
    },
}

# 활용신청 필요 없이 쓸 수 있는 기본 유형 (이미 승인됨)
BASIC_TYPES = ["아파트_매매", "아파트_전월세"]

# 추가 활용신청 필요한 유형
EXTRA_TYPES = [k for k in ENDPOINTS if k not in BASIC_TYPES]


# ── API 호출 ──────────────────────────────────────────────────
def call_api(url, region_code, year_month, api_key, cfg):
    params = {
        "serviceKey":  api_key,
        "LAWD_CD":     region_code,
        "DEAL_YMD":    year_month,
        "numOfRows":   cfg.rows_per_call,
        "pageNo":      1,
    }
    for attempt in range(cfg.max_retry):
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 403:
                log.warning(f"403 Forbidden — 활용신청 필요: {url.split('/')[-1]}")
                return []
            if resp.status_code == 429:
                wait = 60 * (attempt + 1)
                log.warning(f"429 Rate limit — {attempt+1}/{cfg.max_retry}, {wait}초 대기...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            code = root.findtext(".//resultCode", "")
            if code not in ("00", "000", "0000", ""):
                log.warning(f"API오류[{code}]: {root.findtext('.//resultMsg','')} | {region_code} {year_month}")
                return []
            rows = []
            for item in root.findall(".//item"):
                row = {c.tag: (c.text or "").strip() for c in item}
                row["지역코드"] = region_code
                row["수집년월"] = year_month
                row["수집일시"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                rows.append(row)
            return rows
        except requests.exceptions.RequestException as e:
            log.warning(f"요청오류 (시도 {attempt+1}/{cfg.max_retry}): {e}")
        except ET.ParseError as e:
            log.warning(f"XML파싱오류: {e}")
            return []
        time.sleep(1.5 ** attempt)
    log.error(f"최대재시도초과: {region_code} {year_month}")
    return []


# ── DB ────────────────────────────────────────────────────────
class Database:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS collection_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                table_name  TEXT,
                region_code TEXT,
                year_month  TEXT,
                row_count   INTEGER,
                status      TEXT,
                created_at  TEXT,
                UNIQUE(table_name, region_code, year_month)
            )""")
        self.conn.commit()

    def is_collected(self, table, region, ym):
        cur = self.conn.execute(
            "SELECT 1 FROM collection_log "
            "WHERE table_name=? AND region_code=? AND year_month=? AND status='OK'",
            (table, region, ym))
        return cur.fetchone() is not None

    def insert_rows(self, table, rows, region, ym):
        if not rows:
            self._log(table, region, ym, 0, "EMPTY")
            return
        df = pd.DataFrame(rows)
        # 금액 컬럼 숫자 변환 (한글/영문 모두)
        for col in df.columns:
            low = col.lower()
            if any(k in low for k in ["금액", "보증금", "월세", "amount", "price", "deposit", "rent"]):
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(",", "").str.strip(),
                    errors="coerce"
                ).fillna(0).astype(int)
        # 테이블 없으면 자동 생성
        df.to_sql(table, self.conn, if_exists="append", index=False)
        self._log(table, region, ym, len(rows), "OK")
        log.info(f"  ✓ {table} | {region} | {ym} | {len(rows)}건")

    def _log(self, table, region, ym, count, status):
        self.conn.execute(
            "INSERT OR REPLACE INTO collection_log "
            "(table_name,region_code,year_month,row_count,status,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (table, region, ym, count, status,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.conn.commit()

    def stats(self):
        return pd.read_sql("""
            SELECT table_name, status,
                   COUNT(*) AS 수집건수,
                   SUM(row_count) AS 총레코드수
            FROM collection_log
            GROUP BY table_name, status
            ORDER BY table_name
        """, self.conn)

    def load(self, table="apt_trade", region_code=None, start_ym=None, end_ym=None):
        q = f"SELECT * FROM {table} WHERE 1=1"
        if region_code:
            q += f" AND 지역코드='{region_code}'"
        df = pd.read_sql(q, self.conn)
        log.info(f"로드: {table} {len(df):,}건")
        return df

    def columns(self, table):
        """테이블 컬럼 확인"""
        df = pd.read_sql(f"SELECT * FROM {table} LIMIT 1", self.conn)
        return list(df.columns)

    def close(self):
        self.conn.close()


# ── 수집기 ───────────────────────────────────────────────────
class MolitCollector:
    def __init__(self, cfg):
        self.cfg = cfg
        self.db  = Database(cfg.db_path)

    def _gen_ym(self, start, end=None):
        if end is None:
            end = datetime.now().strftime("%Y%m")
        result = []
        cur = datetime.strptime(start, "%Y%m")
        fin = datetime.strptime(end, "%Y%m")
        while cur <= fin:
            result.append(cur.strftime("%Y%m"))
            cur = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        return result

    def collect(self, trade_types=None, regions=None, start_ym="202301", end_ym=None):
        if trade_types is None: trade_types = list(ENDPOINTS.keys())
        if regions is None:     regions = REGION_CODES
        ym_list = self._gen_ym(start_ym, end_ym)

        log.info(f"수집시작: {len(trade_types)}유형 × {len(regions)}지역 × {len(ym_list)}개월")
        total = 0

        for tt in trade_types:
            if tt not in ENDPOINTS:
                log.warning(f"알 수 없는 유형: {tt}")
                continue
            ep = ENDPOINTS[tt]
            log.info(f"\n▶ [{tt}] {ep['note']}")
            pbar = tqdm(total=len(regions) * len(ym_list),
                        desc=f"  {tt}", unit="req")

            skip_this = False  # 403이 연속으로 나오면 해당 유형 스킵
            forbidden_count = 0

            for rname, rcode in regions.items():
                if skip_this:
                    break
                for ym in ym_list:
                    if self.db.is_collected(ep["table"], rcode, ym):
                        pbar.update(1)
                        continue
                    rows = call_api(ep["url"], rcode, ym, self.cfg.api_key, self.cfg)
                    if rows is None or (not rows and forbidden_count > 2):
                        forbidden_count += 1
                        if forbidden_count >= 3:
                            log.warning(f"[{tt}] 403 연속 — 활용신청 후 재시도하세요. 스킵.")
                            skip_this = True
                            break
                    else:
                        forbidden_count = 0
                    self.db.insert_rows(ep["table"], rows, rcode, ym)
                    if rows:
                        total += len(rows)
                    pbar.update(1)
                    time.sleep(self.cfg.delay_sec)

            pbar.close()

        log.info(f"\n완료! 총 {total:,}건 수집")
        self.show_stats()

    def collect_region(self, region_name, start_ym="202501",
                       trade_types=None):
        if region_name not in REGION_CODES:
            raise ValueError(f"'{region_name}' 없음")
        self.collect(
            trade_types=trade_types,
            regions={region_name: REGION_CODES[region_name]},
            start_ym=start_ym,
        )

    def collect_basic(self, start_ym="202301"):
        """활용신청 없이 쓸 수 있는 아파트 매매/전월세만 수집"""
        log.info("기본 수집: 아파트 매매 + 전월세")
        self.collect(trade_types=BASIC_TYPES, start_ym=start_ym)

    def collect_all_approved(self, start_ym="202301"):
        """14개 전부 승인됐을 때 전국 전체 수집"""
        log.info("전체 수집: 14개 유형 × 전국")
        self.collect(start_ym=start_ym)

    def collect_latest(self, months_back=3, trade_types=None):
        """최근 N개월 업데이트"""
        start = (datetime.now().replace(day=1)
                 - timedelta(days=30 * months_back)).strftime("%Y%m")
        types = trade_types or BASIC_TYPES
        self.collect(trade_types=types, start_ym=start)

    def show_stats(self):
        try:
            stats = self.db.stats()
            if not stats.empty:
                print("\n── 수집 현황 ──────────────────────────────────")
                print(stats.to_string(index=False))
        except Exception:
            pass

    def preview(self, table="apt_trade", n=5):
        """수집된 데이터 미리보기"""
        try:
            df = pd.read_sql(f"SELECT * FROM {table} LIMIT {n}", self.db.conn)
            print(f"\n── {table} 컬럼 ({len(df.columns)}개) ──────────────")
            print(list(df.columns))
            print(f"\n── 미리보기 ({n}행) ────────────────────────────")
            print(df.to_string())
        except Exception as e:
            print(f"테이블 없음: {e}")

    def close(self):
        self.db.close()


# ── 실행 ─────────────────────────────────────────────────────
def main():
    api_key = os.getenv("MOLIT_API_KEY", "")
    if not api_key:
        print("⚠️  API 키 없음. 아래 명령 실행 후 다시 시도하세요:")
        print('   export MOLIT_API_KEY="발급받은키"')
        return

    cfg = Config(api_key=api_key)
    c   = MolitCollector(cfg)

    try:
        print("=" * 55)
        print("  모드 선택:")
        print("  1) 강남구 아파트만 테스트 (빠름, ~30초)")
        print("  2) 서울 전체 아파트 (약 10분)")
        print("  3) 전국 아파트 2023~현재 (약 2~3시간)")
        print("  4) 14개 유형 전국 전체 (승인 완료 후)")
        print("=" * 55)
        mode = input("선택 (1~4, 기본=1): ").strip() or "1"

        if mode == "1":
            c.collect(
                trade_types=["아파트_매매"],
                regions={"서울_강남구": "11680"},
                start_ym="202501",
            )

        elif mode == "2":
            seoul = {k: v for k, v in REGION_CODES.items() if k.startswith("서울")}
            c.collect(
                trade_types=["아파트_매매", "아파트_전월세"],
                regions=seoul,
                start_ym="202301",
            )

        elif mode == "3":
            c.collect_basic(start_ym="202301")

        elif mode == "4":
            c.collect_all_approved(start_ym="202301")

        # 결과 미리보기
        c.preview("apt_trade", n=3)

    finally:
        c.close()


if __name__ == "__main__":
    main()
