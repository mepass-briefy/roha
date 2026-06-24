"""
PgStore 검증: STORE=db면 PgStore(Neon), 아니면 기존 파일 Store. orchestrator는 무수정.
strategy mock 한 노드를 실제 실행해 Neon의 records/record_versions/events에 들어가는지 확인하고,
RLS(다른 project_pk로는 안 보이는지)를 간단히 점검한다.

사용:
  STORE=db python db/demo_pg.py      # Neon
  python db/demo_pg.py               # 파일 모드(기존 Store)
"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))
sys.path.insert(0, str(BASE / "db"))

from orchestrator import Store, Orchestrator, canonical_hash
import strategy as strategy_agent
import json

WF = json.loads((BASE / "workflow" / "site-build.v1.json").read_text(encoding="utf-8"))
PROJECT = 9001
MODE = os.environ.get("STORE", "file")
print(f"[demo_pg] STORE={MODE}")

# ---- 호출부 스위치: STORE=db면 PgStore, 아니면 파일 Store ----
if MODE == "db":
    from pg_store import PgStore
    import psycopg
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
    # 재실행 멱등: 이 검증 project 데이터 정리(FK 순서). projects/workflows row는 유지.
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as _c:
        with _c.cursor() as _cur:
            _cur.execute("SELECT set_config('app.current_project', %s, false)", (str(PROJECT),))
            for _t in ("record_validations", "record_versions", "runs", "events", "records"):
                _cur.execute(f"DELETE FROM {_t} WHERE project_pk = %s", (PROJECT,))
    store = PgStore(PROJECT, workflow=WF)
else:
    import shutil
    root = str(BASE / "_run_pg")
    if Path(root).exists():
        shutil.rmtree(root)
    store = Store(root, PROJECT)

orc = Orchestrator(store, WF, {
    "strategy": strategy_agent.make_producer(),  # mock(결정적)
    "policy": lambda inputs: {"service_rules": ["placeholder"]},
})

# intake 시드(파일 Store와 동일 절차: append_version 먼저, save_head 나중)
intake_body = {"site_character": "풋살 소셜매치 예약", "requirements": ["개인 신청"],
               "seed_competitors": ["PLAB", "아이엠그라운드"],
               "unique_angles": ["매니저 배정 자동화", "정산 투명성"]}
ver_pk = store.next_pk()
head_pk = store.next_pk()
store.append_version({"pk": ver_pk, "type": "intake", "record_pk": head_pk, "version": 1,
                      "body": intake_body, "body_hash": canonical_hash(intake_body),
                      "derived_from": [], "produced_by_run": None})
store.save_head({"pk": head_pk, "type": "intake", "project_pk": PROJECT,
                 "current_version": 1, "current_version_pk": ver_pk, "status": "confirmed"})

print("tick ->", orc.tick())  # strategy 산출
sh = store.head("strategy")
sv = store.version("strategy", sh["current_version"])
print("strategy head status:", sh["status"], "version:", sh["current_version"])
print("strategy competitors 수:", len(sv["body"]["competitors"]))
print("events 수:", len(store.events()))

if MODE == "db":
    print("\n=== Neon 직접 SELECT 검증 ===")
    import psycopg
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_project', %s, false)", (str(PROJECT),))
            cur.execute("SELECT type, status, current_version FROM records WHERE project_pk=%s ORDER BY type", (PROJECT,))
            print("records:", cur.fetchall())
            cur.execute("SELECT r.type, rv.version, rv.body_hash FROM record_versions rv "
                        "JOIN records r ON rv.record_pk=r.pk WHERE rv.project_pk=%s ORDER BY r.type, rv.version", (PROJECT,))
            print("record_versions:", cur.fetchall())
            cur.execute("SELECT event_type, count(*) FROM events WHERE project_pk=%s GROUP BY event_type ORDER BY event_type", (PROJECT,))
            print("events by type:", cur.fetchall())
            cur.execute("SELECT provenance->>'competitors' FROM record_versions rv JOIN records r ON rv.record_pk=r.pk "
                        "WHERE rv.project_pk=%s AND r.type='strategy'", (PROJECT,))
            print("strategy provenance.competitors:", cur.fetchone())

            print("\n=== RLS 점검: 테넌트 격리(non-bypassrls role 기준) ===")
            cur.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user")
            print("현재 연결 role의 BYPASSRLS:", cur.fetchone()[0],
                  "(True면 owner 연결은 RLS 우회 -> 격리는 non-bypassrls role에서 강제)")
            # bypassrls 없는 role로 전환해 실제 격리를 확인한다.
            cur.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='rls_check') "
                        "THEN CREATE ROLE rls_check NOLOGIN; END IF; END $$;")
            cur.execute("GRANT SELECT ON records TO rls_check")
            cur.execute("GRANT rls_check TO CURRENT_USER")  # owner가 SET ROLE 하려면 멤버여야
            cur.execute("SET ROLE rls_check")
            cur.execute("SELECT set_config('app.current_project', '8888', false)")
            cur.execute("SELECT count(*) FROM records WHERE project_pk=%s", (PROJECT,))
            other_ctx = cur.fetchone()[0]
            cur.execute("SELECT set_config('app.current_project', %s, false)", (str(PROJECT),))
            cur.execute("SELECT count(*) FROM records WHERE project_pk=%s", (PROJECT,))
            own_ctx = cur.fetchone()[0]
            cur.execute("RESET ROLE")
            print(f"non-bypassrls role: 8888 컨텍스트에서 9001 records 보이는 수 = {other_ctx} (격리시 0)")
            print(f"non-bypassrls role: 9001 컨텍스트에서 9001 records 보이는 수 = {own_ctx} (자기 테넌트)")
            print("RLS 격리 작동:", other_ctx == 0 and own_ctx > 0)

print("\nDONE")
