"""
Goal Analysis Agent 검증. intake(Goal 포함) -> goal_analysis.
mock / real(GOAL_MODE=real) 스위치. 검색 없음. 기존 워크플로/데모는 그대로 둔다.
site-build.v10(goal_analysis 노드 추가) 사용.
"""
import os, sys, shutil, json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))

from orchestrator import Store, Orchestrator, canonical_hash
import goal_analysis as goal_agent
import gate_test
import gate_review

GMODE = os.environ.get("GOAL_MODE", "mock")
print(f"[demo_goal_analysis] GOAL_MODE={GMODE}")
G_LLM = goal_agent.real_llm if GMODE == "real" else goal_agent.offline_llm

ROOT = str(BASE / "_run_goal")
PROJECT = 121
if Path(ROOT).exists():
    shutil.rmtree(ROOT)

WF = json.loads((BASE / "workflow" / "site-build.v10.json").read_text(encoding="utf-8"))
PRODUCERS = {"goal_analysis": goal_agent.make_producer(G_LLM)}

store = Store(ROOT, PROJECT)
orc = Orchestrator(store, WF, PRODUCERS)

# intake에 Goal 추가(하위호환: Goal은 선택 필드, 기존 site_character/requirements 유지)
intake_body = {
    "site_character": "풋살 소셜매치 예약",
    "requirements": ["개인 신청", "매치 예약"],
    "goal": {
        "statement": "동네 풋살 모임을 활성화하고 싶다",   # 막연한 목표(고객 언어)
        "details": {},                                      # 추가 정보 비움
    },
}
ver_pk = store.next_pk()
head_pk = store.next_pk()
store.append_version({"pk": ver_pk, "type": "intake", "record_pk": head_pk, "version": 1,
                      "body": intake_body, "body_hash": canonical_hash(intake_body),
                      "derived_from": [], "produced_by_run": None})
store.save_head({"pk": head_pk, "type": "intake", "project_pk": PROJECT,
                 "current_version": 1, "current_version_pk": ver_pk, "status": "confirmed"})

print("=== tick: goal_analysis ===", orc.tick())
gh = store.head("goal_analysis")
gv = store.version("goal_analysis", gh["current_version"])
b = gv["body"]

print("\n=== 산출 (요약) ===")
print("inferred_dimensions:")
for d in b["inferred_dimensions"]:
    print(f"  - {d.get('dimension')}  (basis={d.get('basis')})")
print("candidate_metrics:")
for m in b["candidate_metrics"]:
    print(f"  - {m.get('metric')} (conf={m.get('confidence')}, rationale={str(m.get('rationale'))[:40]})")
print("assumptions:")
for a in b["assumptions"]:
    print(f"  - {a.get('assumption')}")
print("open_questions:", b["open_questions"])
print("provenance:", b["provenance"])

print("\n=== No-Fabrication·추론 층 검증 ===")
all_inf = all(b["provenance"].get(k) == "inference" for k in ("inferred_dimensions", "candidate_metrics", "assumptions"))
print("모든 산출 provenance=inference(단정 없음):", all_inf)
print("불확실성 open_questions로 남김:", len(b["open_questions"]) > 0)
print("goal_analysis head status:", gh["status"], "(in_review = 사람 확정 대기)")

print("\n=== 게이트(test/review) ===")
t = gate_test.run_test_gate("goal_analysis", b)
r = gate_review.run_review_gate("goal_analysis", b)
print(f"TEST={t['status']} REVIEW={r['status']} (warns={len(t['warnings'])})")

print("\n=== 제약 차단(validate) ===")
def block(label, body):
    try:
        goal_agent.validate(body)
        print(f"{label} -> FAIL: 통과되면 안 됨")
    except ValueError as e:
        print(f"{label} -> 정상 차단: {str(e)[:70]}")

block("산출을 fact로 단정(provenance 위반)",
      {"inferred_dimensions": [{"dimension": "x", "basis": "y"}], "candidate_metrics": [], "assumptions": [],
       "open_questions": [], "provenance": {"inferred_dimensions": "fact"}})
block("metric 누락",
      {"inferred_dimensions": [], "candidate_metrics": [{"dimension": "x"}], "assumptions": [],
       "open_questions": [], "provenance": {"candidate_metrics": "inference"}})
