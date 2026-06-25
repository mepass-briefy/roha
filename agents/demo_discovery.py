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
    "context": "기존 풋살장 운영 업체. 주말은 차는데 평일이 빔.",
    "target_platform": "both",
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
print("target_platform(저장된 입력값):", b["target_platform"], "| provenance:", b["provenance"].get("target_platform"))
print("provenance:", b["provenance"])

# target_platform이 intake record에 저장됐는지(C7)
intake_saved = store.version("intake", store.head("intake")["current_version"])["body"]
print("intake record에 target_platform 저장:", intake_saved.get("target_platform"))
print("intake record에 context 저장:", bool(intake_saved.get("context")))

print("\n=== [케이스2] Context 없음 -> '고객이 누구인지' open_question ===")
no_ctx_intake = {"goal": {"statement": "동네 풋살 모임을 활성화하고 싶다"}, "requirements": ["예약되면 좋겠고"]}
b2 = discovery_agent.produce({"intake": no_ctx_intake}, llm=D_LLM)
ctx_oq = [q for q in b2["open_questions"] if "누구" in q or "context" in q.lower()]
print("context 미제공 open_question:", ctx_oq[:2])
print("target_platform(미지정->기본):", b2["target_platform"])
tp_oq = [q for q in b2["open_questions"] if "target_platform" in q]
print("target_platform 미지정 open_question:", tp_oq[:1])

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

print("\n=== proposed_requirements: offline은 사고 불가 -> 비움 + real 안내 ===")
if DMODE == "mock":
    print("offline proposed_requirements(빈 값이어야):", b["proposed_requirements"])
    assert b["proposed_requirements"] == [], "offline은 고정 매핑 금지 -> 빈 배열이어야 함"
    real_oq = [q for q in b["open_questions"] if "real" in q and "proposed" in q]
    print("real 모드 필요 open_question:", real_oq[:1])
    assert real_oq, "offline에서 'proposed는 real 필요' 안내가 open_questions에 있어야 함"
else:
    print("(real 모드: b의 proposed는 사고 산출이므로 빈 값이 아님 — 아래 판별 블록에서 검증)")
print("provenance.proposed_requirements:", b["provenance"].get("proposed_requirements"))

# 기능별 사고 판별(real 전용): R-03(국내외 정산) vs R-06(어드민) 제안이 서로 다른가 + 환율/통화가 나오는가.
if DMODE == "real":
    print("\n=== [real] 기능별 사고 판별(인플루언서 케이스) ===")
    INF = {
        "goal": {"statement": "인플루언서 캠페인 관리 프로덕트를 만들고 싶다", "details": {}},
        "requirements": [
            "인플루언서들의 캠페인 추적 기능이 필요합니다.",                              # R-01
            "광고주의 의뢰는 계약금이 걸려야 합니다.",                                    # R-02
            "인플루언서들은 국내,외에 포진되어 있어 그들의 통화로 정산이 되어야 합니다.",  # R-03 국내외 정산
            "실제 활동하는 인플루언서인지 검증이 필요합니다.",                            # R-04
            "내가 확인하고 계약 관리를 하며 정산을 하는 어드민이 있어야 합니다.",          # R-05 어드민
        ],
        "context": "인플루언서 마케팅 매칭 플랫폼", "target_platform": "both",
    }
    bi = discovery_agent.produce({"intake": INF}, llm=D_LLM)
    props = bi["proposed_requirements"]
    print(f"proposed {len(props)}건:")
    for p in props:
        print(f"  {p['id']} [{p.get('category')}] basis={p.get('basis')}")
        print(f"      stmt: {p['statement']}")
        print(f"      why : {p['rationale']}")
    # 사고 판별: basis의 R-참조로 정산(R-03) vs 어드민(R-05) 제안을 분리해 내용이 다른지 본다.
    settle = [p for p in props if "R-03" in p.get("basis", "")]
    admin = [p for p in props if "R-05" in p.get("basis", "")]
    fx = [p for p in props if any(k in (p["statement"] + p["rationale"]) for k in ("환율", "통화", "외화", "exchange"))]
    settle_stmts, admin_stmts = {p["statement"] for p in settle}, {p["statement"] for p in admin}
    print(f"\n정산(R-03 기반) 제안: {[p['id'] for p in settle]}")
    print(f"어드민(R-05 기반) 제안: {[p['id'] for p in admin]}")
    print("핵심 판별 — 정산 제안 ∩ 어드민 제안 내용 겹침:",
          (settle_stmts & admin_stmts) or "없음 (서로 다른 요건 = 기능별 사고 성공)")
    print("결정적 증거 — 환율/통화 처리 제안(국내외 정산 사고에서만 도출):",
          [p["id"] for p in fx] or "없음(미검출=사고 실패 의심)")
    print("환율 제안이 정산(R-03) 사고에서 나왔는가:", bool(fx) and all("R-03" in p.get("basis", "") for p in fx))
    print("각 proposed basis+rationale 실내용 보유:",
          all(p.get("basis") and p.get("rationale") and len(p["rationale"]) > 10 for p in props))
