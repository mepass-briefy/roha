"""
로컬 하네스 러너 (단일 진입점). 기존 orchestrator/PgStore/에이전트/게이트를 조합만 한다.
orchestrator·에이전트·게이트는 수정하지 않는다.

역할
  - 사용자 요구(서비스 성격 + 요구사항)를 입력받아 전체 파이프라인을 순차 실행.
  - STORE=db면 Neon(PgStore)에 산출 보존, 아니면 파일 Store.
  - 로컬 직접 실행(폴링·큐·백그라운드 없음). 한 명령으로 끝까지(--auto-approve) 또는 게이트까지.
  - real/mock은 각 에이전트의 기존 스위치(STRATEGY_MODE, FEATURES_MODE, FEATURES_SEARCH)를 따른다.

사용 예
  STORE=db STRATEGY_MODE=real FEATURES_MODE=real FEATURES_SEARCH=on \
    python run_harness.py --auto-approve --until features --project-pk 7777
  python run_harness.py --requirement-file req.json --auto-approve
"""
import os
import sys
import json
import argparse
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))
sys.path.insert(0, str(BASE / "db"))

from orchestrator import Store, Orchestrator, canonical_hash
import strategy as strategy_agent
import ux as ux_agent
import security as security_agent
import design_system as ds_agent
import features as features_agent
import wireframe as wireframe_agent
import backend as backend_agent
import frontend as frontend_agent
import gate_test
import gate_review

DEFAULT_REQUIREMENT = {
    "site_character": "풋살 소셜매치 예약",
    "requirements": ["개인 신청", "매치 예약", "정산 확인"],
    "seed_competitors": ["PLAB", "아이엠그라운드"],
    "unique_angles": ["매니저 배정 자동화", "정산 투명성"],
    "brand_tokens": {"accent": "#7C3AED", "success": "#16A34A", "font_family": "Inter, sans-serif"},
}

# v8: intake -> strategy -> ux -> security -> design_system -> features -> wireframe -> backend -> frontend
TENANT_TABLES = ("record_validations", "artifacts", "record_versions", "runs", "events", "records")


def build_producers(art_dir: Path):
    """real/mock 스위치는 기존 환경변수 패턴을 따른다(각 에이전트 무수정)."""
    strat_llm = strategy_agent.real_llm if os.environ.get("STRATEGY_MODE") == "real" else strategy_agent.offline_llm
    ux_llm = ux_agent.real_llm if os.environ.get("UX_MODE") == "real" else ux_agent.offline_llm
    sec_llm = security_agent.real_llm if os.environ.get("SECURITY_MODE") == "real" else security_agent.offline_llm
    ds_llm = ds_agent.real_llm if os.environ.get("DESIGN_SYSTEM_MODE") == "real" else ds_agent.offline_llm
    wf_llm = wireframe_agent.real_llm if os.environ.get("WIREFRAME_MODE") == "real" else wireframe_agent.offline_llm
    be_llm = backend_agent.real_llm if os.environ.get("BACKEND_MODE") == "real" else backend_agent.offline_llm
    if os.environ.get("FEATURES_MODE") == "real":
        feat_llm = features_agent.make_real_llm(use_search=(os.environ.get("FEATURES_SEARCH") == "on"))
    else:
        feat_llm = features_agent.offline_llm
    return {
        "strategy": strategy_agent.make_producer(strat_llm),
        "ux": ux_agent.make_producer(ux_llm),
        "security": security_agent.make_producer(sec_llm),
        "design_system": ds_agent.make_producer(ds_llm),
        "features": features_agent.make_producer(feat_llm),
        "wireframe": wireframe_agent.make_producer(wf_llm),
        "backend": backend_agent.make_producer(be_llm, artifact_dir=art_dir),
        "frontend": frontend_agent.make_producer(artifact_dir=art_dir),
    }


def _db_cleanup(project_pk):
    """DB 모드 재실행 멱등: 해당 project 데이터 정리(FK 순서). projects도 초기화."""
    import psycopg
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
        with c.cursor() as cur:
            cur.execute("SELECT set_config('app.current_project', %s, false)", (str(project_pk),))
            for t in TENANT_TABLES:
                cur.execute(f"DELETE FROM {t} WHERE project_pk = %s", (project_pk,))
            cur.execute("DELETE FROM projects WHERE pk = %s", (project_pk,))


def make_store(store_mode, project_pk, workflow):
    if store_mode == "db":
        from pg_store import PgStore
        _db_cleanup(project_pk)
        return PgStore(project_pk, workflow=workflow)
    root = str(BASE / "_run_harness")
    import shutil
    if Path(root).exists():
        shutil.rmtree(root)
    return Store(root, project_pk)


def main():
    ap = argparse.ArgumentParser(description="로컬 하네스 러너")
    ap.add_argument("--requirement-file", help="요구 JSON 파일 경로(없으면 기본 샘플)")
    ap.add_argument("--project-pk", type=int, default=7777)
    ap.add_argument("--store", choices=["db", "file"], default=os.environ.get("STORE", "file"))
    ap.add_argument("--workflow", default="site-build.v8.json")
    ap.add_argument("--auto-approve", action="store_true", help="게이트 PASS/WARN이면 자동 승인하고 계속")
    ap.add_argument("--until", help="이 노드까지만 진행(예: features)")
    args = ap.parse_args()

    requirement = DEFAULT_REQUIREMENT
    if args.requirement_file:
        requirement = json.loads(Path(args.requirement_file).read_text(encoding="utf-8"))

    WF = json.loads((BASE / "workflow" / args.workflow).read_text(encoding="utf-8"))
    art_dir = BASE / "_run_harness" / "artifacts"
    print(f"[run_harness] store={args.store} project_pk={args.project_pk} workflow={args.workflow} "
          f"auto_approve={args.auto_approve} until={args.until}")
    print(f"[run_harness] STRATEGY_MODE={os.environ.get('STRATEGY_MODE', 'mock')} "
          f"FEATURES_MODE={os.environ.get('FEATURES_MODE', 'mock')} FEATURES_SEARCH={os.environ.get('FEATURES_SEARCH', 'off')}")

    store = make_store(args.store, args.project_pk, WF)
    orc = Orchestrator(store, WF, build_producers(art_dir))
    gates = {n["produces"]: n.get("gate") for n in WF["nodes"]}

    # intake 시드(요구 -> intake record, confirmed)
    ver_pk = store.next_pk()
    head_pk = store.next_pk()
    store.append_version({"pk": ver_pk, "type": "intake", "record_pk": head_pk, "version": 1,
                          "body": requirement, "body_hash": canonical_hash(requirement),
                          "derived_from": [], "produced_by_run": None})
    store.save_head({"pk": head_pk, "type": "intake", "project_pk": args.project_pk,
                     "current_version": 1, "current_version_pk": ver_pk, "status": "confirmed"})
    print("intake 시드 완료:", requirement.get("site_character"))

    # 파이프라인 순차 실행
    while True:
        picked = orc.tick()
        if picked is None:
            print("\n[run_harness] 더 진행할 READY 노드 없음(완료 또는 게이트 대기).")
            break
        head = store.head(picked)
        body = store.version(picked, head["current_version"])["body"]
        t = gate_test.run_test_gate(picked, body, artifact_base=art_dir)
        r = gate_review.run_review_gate(picked, body)
        # 게이트 결과를 DB(event)에 기록
        store.emit("gate_result", "record", head["pk"],
                   {"node": picked, "test": t["status"], "review": r["status"],
                    "reasons": (t["reasons"] + r["reasons"])[:5]},
                   actor="harness", record_pk=head["pk"], record_version=head["current_version"])
        print(f"  [{picked}] TEST={t['status']} REVIEW={r['status']} "
              f"(warns={len(t['warnings'])})")

        if t["status"] == "FAIL" or r["status"] == "FAIL":
            print(f"  -> 게이트 FAIL. 중단. reasons: {(t['reasons'] + r['reasons'])[:3]}")
            break

        if gates.get(picked) == "human" and not args.auto_approve:
            print(f"  -> [{picked}] human 게이트 대기. 로컬 승인 필요(--auto-approve 또는 승인 명령). DB에 게이트 상태 기록됨.")
            break

        orc.human_confirm(picked)
        if args.until and picked == args.until:
            print(f"\n[run_harness] --until {args.until} 도달. 종료.")
            break

    # 최종 상태 보고
    print("\n=== 최종 상태(노드별) ===")
    for n in WF["nodes"]:
        rt = n["produces"]
        h = store.head(rt)
        st = h["status"] if h else "(없음)"
        ver = h["current_version"] if h else "-"
        print(f"  {rt:14} status={st} v={ver}")

    if args.store == "db":
        print("\n=== Neon SELECT 검증(project={}) ===".format(args.project_pk))
        import psycopg
        from dotenv import load_dotenv
        load_dotenv(BASE / ".env")
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
            with c.cursor() as cur:
                cur.execute("SELECT set_config('app.current_project', %s, false)", (str(args.project_pk),))
                cur.execute("SELECT type, status, current_version FROM records WHERE project_pk=%s ORDER BY type", (args.project_pk,))
                print("records:", cur.fetchall())
                cur.execute("SELECT event_type, count(*) FROM events WHERE project_pk=%s GROUP BY event_type ORDER BY event_type", (args.project_pk,))
                print("events by type:", cur.fetchall())
                cur.execute("SELECT payload->>'node', payload->>'test', payload->>'review' FROM events "
                            "WHERE project_pk=%s AND event_type='gate_result' ORDER BY pk", (args.project_pk,))
                print("gate_result 기록:", cur.fetchall())


if __name__ == "__main__":
    main()
