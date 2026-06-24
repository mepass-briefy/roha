"""
Discovery Agent 검증. intake(Goal + requirements) -> discovery.
mock / real(DISCOVERY_MODE=real) 스위치. 검색 없음. site-build.v11(discovery 노드) 사용.
기존 워크플로/데모는 그대로 둔다.
"""
import os, sys, shutil, json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))

from orchestrator import Store, Orchestrator, canonical_hash
import discovery as discovery_agent
import gate_test
import gate_review

DMODE = os.environ.get("DISCOVERY_MODE", "mock")
print(f"[demo_discovery] DISCOVERY_MODE={DMODE}")
D_LLM = discovery_agent.real_llm if DMODE == "real" else discovery_agent.offline_llm

ROOT = str(BASE / "_run_discovery")
PROJECT = 131
if Path(ROOT).exists():
    shutil.rmtree(ROOT)

WF = json.loads((BASE / "workflow" / "site-build.v11.json").read_text(encoding="utf-8"))
PRODUCERS = {"discovery": discovery_agent.make_producer(D_LLM)}

store = Store(ROOT, PROJECT)
orc = Orchestrator(store, WF, PRODUCERS)

# 막연한 Goal + 막연한 요구(고객 언어)
intake_body = {
    "site_character": "풋살 소셜매치 예약",
    "goal": {"statement": "동네 풋살 모임을 활성화하고 싶다", "details": {}},
    "requirements": ["예약되면 좋겠고", "평일에 사람 모으고 싶다"],
}
ver_pk = store.next_pk()
head_pk = store.next_pk()
store.append_version({"pk": ver_pk, "type": "intake", "record_pk": head_pk, "version": 1,
                      "body": intake_body, "body_hash": canonical_hash(intake_body),
                      "derived_from": [], "produced_by_run": None})
store.save_head({"pk": head_pk, "type": "intake", "project_pk": PROJECT,
                 "current_version": 1, "current_version_pk": ver_pk, "status": "confirmed"})

print("=== tick: discovery ===", orc.tick())
dh = store.head("discovery")
dv = store.version("discovery", dh["current_version"])
b = dv["body"]

print("\n=== goal_interpretation ===")
gi = b["goal_interpretation"]
for d in gi["inferred_dimensions"]:
    print(f"  dim: {d.get('dimension')} (basis={d.get('basis')})")
for m in gi["candidate_metrics"]:
    print(f"  metric: {m.get('metric')} (conf={m.get('confidence')})")
print("\n=== requirement_normalization ===")
for r in b["requirement_normalization"]:
    print(f"  {r.get('id')} [{r.get('origin')}] {r.get('statement')}")
print("\nopen_questions:", b["open_questions"])
print("provenance:", b["provenance"])

print("\n=== No-Fabrication·경계 검증 ===")
print("goal_interpretation provenance=inference:", b["provenance"].get("goal_interpretation") == "inference")
print("requirement 각 항목 origin/statement 보유:",
      all(r.get("origin") in ("explicit", "context-inferred") and r.get("statement") for r in b["requirement_normalization"]))
print("requirement_normalization provenance=per_item:", b["provenance"].get("requirement_normalization") == "per_item")
# 고객이 말 안 한 흔한 기능(결제/리뷰/채팅)이 explicit로 들어갔는지(위장) 점검
FAB_HINTS = ("결제", "리뷰", "채팅", "지도", "랭킹", "쿠폰")
fabricated = [r for r in b["requirement_normalization"]
              if r.get("origin") == "explicit" and any(h in (r.get("statement") or "") for h in FAB_HINTS)]
print("고객 미언급 기능이 explicit로 위장?:", "있음(문제)" if fabricated else "없음 OK")

print("\n=== 게이트(test/review) ===")
t = gate_test.run_test_gate("discovery", b)
r = gate_review.run_review_gate("discovery", b)
print(f"TEST={t['status']} REVIEW={r['status']} (warns={len(t['warnings'])})")

print("\n=== 게이트 음성 테스트 ===")
def gate_block(label, body):
    rr = gate_review.run_review_gate("discovery", body)
    flag = next((x for x in rr["reasons"] if "fabrication" in x or "origin" in x or "statement" in x), rr["reasons"][:1])
    print(f"{label} -> REVIEW={rr['status']} | {flag}")

# 원문 근거 없는 요구(statement 없음) 주입 -> FAIL
gate_block("원문 근거 없는 요구(statement 없음)", {
    "goal_interpretation": {"inferred_dimensions": [], "candidate_metrics": [], "assumptions": []},
    "requirement_normalization": [{"id": "R-09", "origin": "explicit"}],
    "open_questions": [], "provenance": {"goal_interpretation": "inference", "requirement_normalization": "per_item"}})
# 정상 -> 현재 산출 그대로
print("정상 산출 REVIEW:", gate_review.run_review_gate("discovery", b)["status"])
