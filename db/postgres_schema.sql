-- PostgreSQL DDL — 부동산 가격 예측 프로젝트
-- Generated from SQLite schema + new collector tables
-- Usage: psql -U realestate -d realestate -f db/postgres_schema.sql

-- ── 실거래가 원본 테이블 ───────────────────────────────────────

CREATE TABLE IF NOT EXISTS apt_trade (
    id                  BIGSERIAL PRIMARY KEY,
    "aptDong"           TEXT,
    "aptNm"             TEXT,
    "aptSeq"            TEXT,
    "bonbun"            TEXT,
    "bubun"             TEXT,
    "buildYear"         TEXT,
    "buyerGbn"          TEXT,
    "cdealDay"          TEXT,
    "cdealType"         TEXT,
    "dealAmount"        INTEGER,
    "dealDay"           TEXT,
    "dealMonth"         TEXT,
    "dealYear"          TEXT,
    "dealingGbn"        TEXT,
    "estateAgentSggNm"  TEXT,
    "excluUseAr"        TEXT,
    "floor"             TEXT,
    "jibun"             TEXT,
    "landCd"            TEXT,
    "landLeaseholdGbn"  TEXT,
    "rgstDate"          TEXT,
    "roadNm"            TEXT,
    "roadNmBonbun"      TEXT,
    "roadNmBubun"       TEXT,
    "roadNmCd"          TEXT,
    "roadNmSeq"         TEXT,
    "roadNmSggCd"       TEXT,
    "roadNmbCd"         TEXT,
    "sggCd"             TEXT,
    "slerGbn"           TEXT,
    "umdCd"             TEXT,
    "umdNm"             TEXT,
    지역코드             TEXT,
    수집년월             TEXT,
    수집일시             TEXT
);

CREATE INDEX IF NOT EXISTS idx_apt_trade_sgg ON apt_trade ("sggCd");
CREATE INDEX IF NOT EXISTS idx_apt_trade_apt ON apt_trade ("aptNm");
CREATE INDEX IF NOT EXISTS idx_apt_trade_deal ON apt_trade ("dealYear", "dealMonth");


CREATE TABLE IF NOT EXISTS apt_rent (
    id                  BIGSERIAL PRIMARY KEY,
    "aptNm"             TEXT,
    "aptSeq"            TEXT,
    "buildYear"         TEXT,
    "contractTerm"      TEXT,
    "contractType"      TEXT,
    "dealDay"           TEXT,
    "dealMonth"         TEXT,
    "dealYear"          TEXT,
    "deposit"           INTEGER,
    "excluUseAr"        TEXT,
    "floor"             TEXT,
    "jibun"             TEXT,
    "monthlyRent"       INTEGER,
    "preDeposit"        INTEGER,
    "preMonthlyRent"    INTEGER,
    "roadnm"            TEXT,
    "roadnmbcd"         TEXT,
    "roadnmbonbun"      TEXT,
    "roadnmbubun"       TEXT,
    "roadnmcd"          TEXT,
    "roadnmseq"         TEXT,
    "roadnmsggcd"       TEXT,
    "sggCd"             TEXT,
    "umdNm"             TEXT,
    "useRRRight"        TEXT,
    지역코드             TEXT,
    수집년월             TEXT,
    수집일시             TEXT
);

CREATE INDEX IF NOT EXISTS idx_apt_rent_sgg ON apt_rent ("sggCd");
CREATE INDEX IF NOT EXISTS idx_apt_rent_apt ON apt_rent ("aptNm");
CREATE INDEX IF NOT EXISTS idx_apt_rent_deal ON apt_rent ("dealYear", "dealMonth");


CREATE TABLE IF NOT EXISTS villa_trade (
    id                  BIGSERIAL PRIMARY KEY,
    "buildYear"         TEXT,
    "buyerGbn"          TEXT,
    "cdealDay"          TEXT,
    "cdealType"         TEXT,
    "dealAmount"        INTEGER,
    "dealDay"           TEXT,
    "dealMonth"         TEXT,
    "dealYear"          TEXT,
    "dealingGbn"        TEXT,
    "estateAgentSggNm"  TEXT,
    "excluUseAr"        TEXT,
    "floor"             TEXT,
    "houseType"         TEXT,
    "jibun"             TEXT,
    "landAr"            TEXT,
    "mhouseNm"          TEXT,
    "rgstDate"          TEXT,
    "sggCd"             TEXT,
    "slerGbn"           TEXT,
    "umdNm"             TEXT,
    지역코드             TEXT,
    수집년월             TEXT,
    수집일시             TEXT
);

CREATE INDEX IF NOT EXISTS idx_villa_trade_sgg ON villa_trade ("sggCd");


CREATE TABLE IF NOT EXISTS villa_rent (
    id                  BIGSERIAL PRIMARY KEY,
    "buildYear"         TEXT,
    "contractTerm"      TEXT,
    "contractType"      TEXT,
    "dealDay"           TEXT,
    "dealMonth"         TEXT,
    "dealYear"          TEXT,
    "deposit"           INTEGER,
    "excluUseAr"        TEXT,
    "floor"             TEXT,
    "houseType"         TEXT,
    "jibun"             TEXT,
    "mhouseNm"          TEXT,
    "monthlyRent"       INTEGER,
    "preDeposit"        INTEGER,
    "preMonthlyRent"    INTEGER,
    "sggCd"             TEXT,
    "umdNm"             TEXT,
    "useRRRight"        TEXT,
    지역코드             TEXT,
    수집년월             TEXT,
    수집일시             TEXT
);


CREATE TABLE IF NOT EXISTS house_trade (
    id                  BIGSERIAL PRIMARY KEY,
    "buildYear"         TEXT,
    "buyerGbn"          TEXT,
    "cdealDay"          TEXT,
    "cdealType"         TEXT,
    "dealAmount"        INTEGER,
    "dealDay"           TEXT,
    "dealMonth"         TEXT,
    "dealYear"          TEXT,
    "dealingGbn"        TEXT,
    "estateAgentSggNm"  TEXT,
    "houseType"         TEXT,
    "jibun"             TEXT,
    "plottageAr"        TEXT,
    "sggCd"             TEXT,
    "slerGbn"           TEXT,
    "totalFloorAr"      TEXT,
    "umdNm"             TEXT,
    지역코드             TEXT,
    수집년월             TEXT,
    수집일시             TEXT
);


CREATE TABLE IF NOT EXISTS house_rent (
    id                  BIGSERIAL PRIMARY KEY,
    "buildYear"         TEXT,
    "contractTerm"      TEXT,
    "contractType"      TEXT,
    "dealDay"           TEXT,
    "dealMonth"         TEXT,
    "dealYear"          TEXT,
    "deposit"           INTEGER,
    "houseType"         TEXT,
    "monthlyRent"       INTEGER,
    "preDeposit"        INTEGER,
    "preMonthlyRent"    INTEGER,
    "sggCd"             TEXT,
    "totalFloorAr"      TEXT,
    "umdNm"             TEXT,
    "useRRRight"        TEXT,
    지역코드             TEXT,
    수집년월             TEXT,
    수집일시             TEXT
);


CREATE TABLE IF NOT EXISTS officetel_trade (
    id                  BIGSERIAL PRIMARY KEY,
    "buildYear"         TEXT,
    "buyerGbn"          TEXT,
    "cdealDay"          TEXT,
    "cdealType"         TEXT,
    "dealAmount"        INTEGER,
    "dealDay"           TEXT,
    "dealMonth"         TEXT,
    "dealYear"          TEXT,
    "dealingGbn"        TEXT,
    "estateAgentSggNm"  TEXT,
    "excluUseAr"        TEXT,
    "floor"             TEXT,
    "jibun"             TEXT,
    "offiNm"            TEXT,
    "sggCd"             TEXT,
    "sggNm"             TEXT,
    "slerGbn"           TEXT,
    "umdNm"             TEXT,
    지역코드             TEXT,
    수집년월             TEXT,
    수집일시             TEXT
);


CREATE TABLE IF NOT EXISTS officetel_rent (
    id                  BIGSERIAL PRIMARY KEY,
    "buildYear"         TEXT,
    "contractTerm"      TEXT,
    "contractType"      TEXT,
    "dealDay"           TEXT,
    "dealMonth"         TEXT,
    "dealYear"          TEXT,
    "deposit"           INTEGER,
    "excluUseAr"        TEXT,
    "floor"             TEXT,
    "jibun"             TEXT,
    "monthlyRent"       INTEGER,
    "offiNm"            TEXT,
    "preDeposit"        INTEGER,
    "preMonthlyRent"    INTEGER,
    "sggCd"             TEXT,
    "sggNm"             TEXT,
    "umdNm"             TEXT,
    "useRRRight"        TEXT,
    지역코드             TEXT,
    수집년월             TEXT,
    수집일시             TEXT
);


CREATE TABLE IF NOT EXISTS land_trade (
    id                  BIGSERIAL PRIMARY KEY,
    "cdealDay"          TEXT,
    "cdealType"         TEXT,
    "dealAmount"        INTEGER,
    "dealArea"          TEXT,
    "dealDay"           TEXT,
    "dealMonth"         TEXT,
    "dealYear"          TEXT,
    "dealingGbn"        TEXT,
    "estateAgentSggNm"  TEXT,
    "jibun"             TEXT,
    "jimok"             TEXT,
    "landUse"           TEXT,
    "sggCd"             TEXT,
    "sggNm"             TEXT,
    "shareDealingType"  TEXT,
    "umdNm"             TEXT,
    지역코드             TEXT,
    수집년월             TEXT,
    수집일시             TEXT
);


CREATE TABLE IF NOT EXISTS commercial_trade (
    id                  BIGSERIAL PRIMARY KEY,
    "buildYear"         TEXT,
    "buildingAr"        TEXT,
    "buildingType"      TEXT,
    "buildingUse"       TEXT,
    "buyerGbn"          TEXT,
    "cdealDay"          TEXT,
    "cdealType"         TEXT,
    "dealAmount"        INTEGER,
    "dealDay"           TEXT,
    "dealMonth"         TEXT,
    "dealYear"          TEXT,
    "dealingGbn"        TEXT,
    "estateAgentSggNm"  TEXT,
    "floor"             TEXT,
    "jibun"             TEXT,
    "landUse"           TEXT,
    "plottageAr"        TEXT,
    "sggCd"             TEXT,
    "sggNm"             TEXT,
    "shareDealingType"  TEXT,
    "slerGbn"           TEXT,
    "umdNm"             TEXT,
    지역코드             TEXT,
    수집년월             TEXT,
    수집일시             TEXT
);


CREATE TABLE IF NOT EXISTS industrial_trade (
    id                  BIGSERIAL PRIMARY KEY,
    "buildYear"         TEXT,
    "buildingAr"        TEXT,
    "buildingType"      TEXT,
    "buildingUse"       TEXT,
    "buyerGbn"          TEXT,
    "cdealDay"          TEXT,
    "cdealType"         TEXT,
    "dealAmount"        INTEGER,
    "dealDay"           TEXT,
    "dealMonth"         TEXT,
    "dealYear"          TEXT,
    "dealingGbn"        TEXT,
    "estateAgentSggNm"  TEXT,
    "floor"             TEXT,
    "jibun"             TEXT,
    "landUse"           TEXT,
    "plottageAr"        TEXT,
    "sggCd"             TEXT,
    "sggNm"             TEXT,
    "shareDealingType"  TEXT,
    "slerGbn"           TEXT,
    "umdNm"             TEXT,
    지역코드             TEXT,
    수집년월             TEXT,
    수집일시             TEXT
);


CREATE TABLE IF NOT EXISTS apt_presale (
    id                  BIGSERIAL PRIMARY KEY,
    "aptNm"             TEXT,
    "buyerGbn"          TEXT,
    "cdealDay"          TEXT,
    "cdealType"         TEXT,
    "dealAmount"        INTEGER,
    "dealDay"           TEXT,
    "dealMonth"         TEXT,
    "dealYear"          TEXT,
    "dealingGbn"        TEXT,
    "estateAgentSggNm"  TEXT,
    "excluUseAr"        TEXT,
    "floor"             TEXT,
    "jibun"             TEXT,
    "ownershipGbn"      TEXT,
    "sggCd"             TEXT,
    "sggNm"             TEXT,
    "slerGbn"           TEXT,
    "umdNm"             TEXT,
    지역코드             TEXT,
    수집년월             TEXT,
    수집일시             TEXT
);


-- ── 수집 로그 ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS collection_log (
    id          BIGSERIAL PRIMARY KEY,
    table_name  TEXT      NOT NULL,
    region_code TEXT      NOT NULL,
    year_month  TEXT      NOT NULL,
    row_count   INTEGER,
    status      TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (table_name, region_code, year_month)
);


-- ── KOSIS 거시통계 ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kosis_population (
    sgg_cd       TEXT    NOT NULL,
    year         INTEGER NOT NULL,
    population   INTEGER,
    households   INTEGER,
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (sgg_cd, year)
);

CREATE TABLE IF NOT EXISTS kosis_household (
    sgg_cd            TEXT    NOT NULL,
    year              INTEGER NOT NULL,
    total_households  INTEGER,
    single_households INTEGER,
    avg_members       REAL,
    collected_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (sgg_cd, year)
);

CREATE TABLE IF NOT EXISTS kosis_employment (
    sgg_cd          TEXT    NOT NULL,
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    employment_rate REAL,
    unemployment_rate REAL,
    collected_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (sgg_cd, year, month)
);

CREATE TABLE IF NOT EXISTS kosis_income (
    sgg_cd       TEXT    NOT NULL,
    year         INTEGER NOT NULL,
    avg_income   REAL,
    median_income REAL,
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (sgg_cd, year)
);


-- ── 카카오 POI ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kakao_poi (
    sgg_cd           TEXT    NOT NULL,
    umd_nm           TEXT    NOT NULL DEFAULT '',
    subway_cnt       INTEGER DEFAULT 0,
    subway_dist_m    REAL,
    elem_school_cnt  INTEGER DEFAULT 0,
    supermarket_cnt  INTEGER DEFAULT 0,
    hospital_cnt     INTEGER DEFAULT 0,
    convenience_cnt  INTEGER DEFAULT 0,
    collected_at     TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (sgg_cd, umd_nm)
);


-- ── 청약 정보 ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS subscription_notice (
    house_manage_no  TEXT    PRIMARY KEY,
    house_nm         TEXT,
    sgg_cd           TEXT,
    supply_count     INTEGER,
    rcrit_bsns_de    TEXT,
    rcept_bgnde      TEXT,
    rcept_endde      TEXT,
    pblancUrl        TEXT,
    collected_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscription_result (
    house_manage_no  TEXT    NOT NULL,
    type_nm          TEXT    NOT NULL,
    supply_count     INTEGER,
    competition_rate REAL,
    min_point        INTEGER,
    max_point        INTEGER,
    avg_point        REAL,
    collected_at     TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (house_manage_no, type_nm)
);


-- ── 기상 리스크 ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS weather_risk (
    sgg_cd       TEXT    NOT NULL,
    year         INTEGER NOT NULL,
    month        INTEGER NOT NULL,
    risk_score   REAL,
    event_cnt    INTEGER DEFAULT 0,
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (sgg_cd, year, month)
);

CREATE TABLE IF NOT EXISTS weather_anomaly (
    sgg_cd       TEXT    NOT NULL,
    year         INTEGER NOT NULL,
    avg_temp     REAL,
    max_temp     REAL,
    min_temp     REAL,
    avg_precip   REAL,
    temp_anomaly REAL,
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (sgg_cd, year)
);


-- ── 공시지가 ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS land_price_standard (
    pnu          TEXT    PRIMARY KEY,
    sgg_cd       TEXT,
    umd_cd       TEXT,
    jibun        TEXT,
    land_area    REAL,
    land_price   INTEGER,
    land_use     TEXT,
    base_year    INTEGER,
    collected_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_land_std_sgg ON land_price_standard (sgg_cd, base_year);

CREATE TABLE IF NOT EXISTS land_price_individual (
    pnu          TEXT    NOT NULL,
    sgg_cd       TEXT,
    jibun        TEXT,
    land_price   INTEGER,
    base_year    INTEGER,
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (pnu, base_year)
);

CREATE TABLE IF NOT EXISTS land_price_sgg_avg (
    sgg_cd          TEXT    NOT NULL,
    base_year       INTEGER NOT NULL,
    avg_price_m2    REAL,
    median_price_m2 REAL,
    sample_count    INTEGER,
    collected_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (sgg_cd, base_year)
);


-- ── 학교 정보 ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS school_info (
    school_code  TEXT    PRIMARY KEY,
    school_nm    TEXT,
    school_type  TEXT,
    sgg_cd       TEXT,
    sido_nm      TEXT,
    sgg_nm       TEXT,
    addr         TEXT,
    lat          REAL,
    lng          REAL,
    student_cnt  INTEGER,
    class_cnt    INTEGER,
    collected_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_school_info_sgg ON school_info (sgg_cd);

CREATE TABLE IF NOT EXISTS school_achievement (
    school_code  TEXT    NOT NULL,
    exam_year    INTEGER NOT NULL,
    subject      TEXT    NOT NULL DEFAULT '',
    below_basic  REAL,
    basic        REAL,
    proficient   REAL,
    advanced     REAL,
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (school_code, exam_year, subject)
);

CREATE TABLE IF NOT EXISTS school_district_score (
    sgg_cd          TEXT    NOT NULL,
    year            INTEGER NOT NULL,
    avg_score       REAL,
    school_cnt      INTEGER,
    high_school_cnt INTEGER,
    special_hs_cnt  INTEGER,
    grade           TEXT,
    collected_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (sgg_cd, year)
);
