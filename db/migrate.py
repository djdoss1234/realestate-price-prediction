"""
SQLite → PostgreSQL 마이그레이션
==================================
사용법:
  export DATABASE_URL=postgresql://user:pass@localhost:5432/realestate
  python db/migrate.py [--tables apt_trade apt_rent ...]  [--batch-size 5000]

동작:
  1. postgres_schema.sql 실행 (테이블 생성)
  2. SQLite 각 테이블 → PostgreSQL COPY (배치 단위)
  3. 진행률 출력, 실패 시 해당 테이블 스킵 후 계속

주의: SQLite DB 파일 경로는 환경변수 REALESTATE_DB 또는 기본값 사용.
"""

import argparse
import io
import logging
import os
import sqlite3
import sys

log = logging.getLogger(__name__)
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)

SQLITE_PATH = os.getenv("REALESTATE_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "realestate.db"))
DATABASE_URL = os.getenv("DATABASE_URL", "")
SCHEMA_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "postgres_schema.sql")

ALL_TABLES = [
    "apt_trade", "apt_rent",
    "villa_trade", "villa_rent",
    "house_trade", "house_rent",
    "officetel_trade", "officetel_rent",
    "land_trade", "commercial_trade", "industrial_trade",
    "apt_presale", "collection_log",
    "kosis_population", "kosis_household", "kosis_employment", "kosis_income",
    "kakao_poi",
    "subscription_notice", "subscription_result",
    "weather_risk", "weather_anomaly",
    "land_price_standard", "land_price_individual", "land_price_sgg_avg",
    "school_info", "school_achievement", "school_district_score",
]


def _get_pg_conn():
    try:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    except ImportError:
        log.error("psycopg2 없음 — pip install psycopg2-binary")
        sys.exit(1)


def _apply_schema(pg_conn):
    if not os.path.exists(SCHEMA_PATH):
        log.error("postgres_schema.sql 없음: %s", SCHEMA_PATH)
        sys.exit(1)
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        ddl = f.read()
    with pg_conn.cursor() as cur:
        cur.execute(ddl)
    pg_conn.commit()
    log.info("스키마 적용 완료")


def _get_sqlite_columns(sqlite_conn, table: str) -> list[str]:
    rows = sqlite_conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


def _migrate_table(sqlite_conn, pg_conn, table: str, batch_size: int):
    cols = _get_sqlite_columns(sqlite_conn, table)
    if not cols:
        log.warning("SQLite에 테이블 없음: %s — 스킵", table)
        return 0

    total = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if total == 0:
        log.info("%-30s 0건 — 스킵", table)
        return 0

    # PostgreSQL 컬럼 중 'id' autoincrement는 제외 (BIGSERIAL)
    pg_cols = [c for c in cols if c != "id"]
    quoted  = [f'"{c}"' for c in pg_cols]
    placeholders = ",".join(["%s"] * len(pg_cols))

    inserted = 0
    offset   = 0

    with pg_conn.cursor() as cur:
        while offset < total:
            rows = sqlite_conn.execute(
                f"SELECT {','.join(quoted)} FROM \"{table}\" LIMIT ? OFFSET ?",
                (batch_size, offset)
            ).fetchall()
            if not rows:
                break

            buf = io.StringIO()
            for row in rows:
                line = "\t".join(
                    "\\N" if v is None else str(v).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")
                    for v in row
                )
                buf.write(line + "\n")
            buf.seek(0)

            col_str = ",".join(quoted)
            cur.copy_expert(
                f'COPY "{table}" ({col_str}) FROM STDIN',
                buf
            )
            inserted += len(rows)
            offset   += batch_size
            pct = inserted / total * 100
            log.info("%-30s %6d / %6d  (%.0f%%)", table, inserted, total, pct)

    pg_conn.commit()
    return inserted


def main():
    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL 마이그레이션")
    parser.add_argument("--tables",     nargs="*", default=ALL_TABLES, help="마이그레이션할 테이블 목록")
    parser.add_argument("--batch-size", type=int,  default=5000,       help="배치 크기 (기본 5000)")
    parser.add_argument("--schema-only",action="store_true",           help="스키마만 적용 (데이터 이전 안 함)")
    args = parser.parse_args()

    if not DATABASE_URL:
        log.error("DATABASE_URL 환경변수 필요: postgresql://user:pass@host:5432/dbname")
        sys.exit(1)

    if not os.path.exists(SQLITE_PATH):
        log.error("SQLite DB 없음: %s", SQLITE_PATH)
        sys.exit(1)

    pg_conn     = _get_pg_conn()
    sqlite_conn = sqlite3.connect(SQLITE_PATH)

    log.info("SQLite: %s", SQLITE_PATH)
    log.info("PostgreSQL: %s", DATABASE_URL.split("@")[-1])

    _apply_schema(pg_conn)

    if args.schema_only:
        log.info("--schema-only 지정 — 데이터 이전 생략")
        pg_conn.close()
        sqlite_conn.close()
        return

    total_rows = 0
    for table in args.tables:
        try:
            n = _migrate_table(sqlite_conn, pg_conn, table, args.batch_size)
            total_rows += n
        except Exception as e:
            log.error("테이블 마이그레이션 실패 [%s]: %s — 스킵", table, e)
            pg_conn.rollback()

    pg_conn.close()
    sqlite_conn.close()
    log.info("마이그레이션 완료 — 총 %d건", total_rows)


if __name__ == "__main__":
    main()
