"""
Neon(PostgreSQL)에 DDL v2 스키마를 적용한다. orchestrator는 건드리지 않는다(이번엔 DB 연결 안 함).

연결 문자열은 roha 폴더의 .env(DATABASE_URL)에서 load_dotenv로 읽는다(코드에 박지 않음).
.env는 .gitignore에 등록돼 커밋되지 않는다. db/schema.sql을 실행하고(idempotent),
8개 테이블 생성 여부를 information_schema로 검증한다.

사용:
  .env 에 DATABASE_URL=postgresql://...@...neon.tech/...?sslmode=require 를 두고
  python db/setup_db.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# roha 폴더의 .env에서 환경변수 로드(이미 설정된 환경변수는 덮어쓰지 않음).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

EXPECTED_TABLES = [
    "projects", "workflows", "records", "record_versions",
    "record_validations", "runs", "events", "artifacts",
]


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL 환경변수 없음. 연결 문자열을 환경변수로 제공하세요(코드에 박지 마세요).")
        return 2
    try:
        import psycopg
    except ImportError:
        print("ERROR: psycopg 미설치. pip install 'psycopg[binary]'")
        return 2

    schema_sql = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
    role_path = Path(__file__).with_name("create_app_role.sql")
    role_sql = role_path.read_text(encoding="utf-8") if role_path.exists() else None

    try:
        with psycopg.connect(url, autocommit=True) as conn:
            with conn.cursor() as cur:
                # DDL 적용(idempotent)
                cur.execute(schema_sql)
                # 운영용 non-bypassrls role 생성(idempotent)
                if role_sql:
                    cur.execute(role_sql)
                # 검증: public 스키마의 기대 테이블 존재 확인
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                    "ORDER BY table_name"
                )
                present = [r[0] for r in cur.fetchall()]
                # RLS 활성 테이블 확인
                cur.execute(
                    "SELECT relname FROM pg_class "
                    "WHERE relrowsecurity = true AND relnamespace = 'public'::regnamespace "
                    "ORDER BY relname"
                )
                rls = [r[0] for r in cur.fetchall()]
    except Exception as e:
        print(f"ERROR: DB 연결/실행 실패: {type(e).__name__}: {e}")
        return 1

    missing = [t for t in EXPECTED_TABLES if t not in present]
    print("=== public 테이블 목록 ===")
    for t in present:
        mark = " (기대)" if t in EXPECTED_TABLES else ""
        print(f"  - {t}{mark}")
    print(f"\n기대 8개 테이블 모두 존재: {not missing}")
    if missing:
        print(f"누락: {missing}")
    print(f"RLS 활성 테이블: {rls}")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
