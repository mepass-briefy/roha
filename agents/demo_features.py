"""
Features Agent 검증. intake -> strategy -> ux -> security -> features.
mock / real(FEATURES_MODE=real) / real+search(FEATURES_SEARCH=on) 스위치.
strategy/ux/security는 mock(입력 제공), features만 모드 전환. 기존 워크플로/데모는 그대로 둔다.
"""
import os, sys, shutil, json
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))

from orchestrator import Store, Orchestrator, canonical_hash
import strategy as strategy_agent
import ux as ux_agent
import security as security_agent
import features as features_agent

FMODE = os.environ.get("FEATURES_MODE", "mock")
FSEARCH = os.environ.get("FEATURES_SEARCH", "off")
print(f"[demo_features] FEATURES_MODE={FMODE} FEATURES_SEARCH={FSEARCH}")
if FMODE == "real":
    F_LLM = features_agent.make_real_llm(use_search=(FSEARCH == "on"))
else:
    F_LLM = features_agent.offline_llm

ROOT = str(BASE / "_run_features")
PROJECT = 71
if Path(ROOT).exists():
    shutil.rmtree(ROOT)

WF = json.loads((BASE / "workflow" / "site-build.v5.json").read_text(encoding="utf-8"))

PRODUCERS = {
    "strategy": strategy_agent.make_producer(),
    "ux": ux_agent.make_producer(),
    "security": security_agent.make_producer(),
    "features": features_agent.make_producer(F_LLM),
}

store = Store(ROOT, PROJECT)
orc = Orchestrator(store, WF, PRODUCERS)

intake_body = {
    "site_character": "풋살 소셜매치 예약",
    "requirements": ["개인 신청", "매치 예약", "정산 확인"],
    "seed_competitors": ["PLAB", "아이엠그라운드"],
    "unique_angles": ["매니저 배정 자동화", "정산 투명성"],
}
ver_pk = store.next_pk()
head = {"pk": store.next_pk(), "type": "intake", "project_pk": PROJECT,
        "current_version": 1, "current_version_pk": ver_pk, "status": "confirmed"}
store.append_version({"pk": ver_pk, "type": "intake", "record_pk": head["pk"], "version": 1,
                      "body": intake_body, "body_hash": canonical_hash(intake_body),
                      "derived_from": [], "produced_by_run": None})
store.save_head(head)

for node in ("strategy", "ux", "security"):
    picked = orc.tick()
    orc.human_confirm(picked)
print("=== tick: features ===", orc.tick())

fh = store.head("features")
fv = store.version("features", fh["current_version"])
b = fv["body"]

print("\n=== features 산출 (요약) ===")
for f in b["features"]:
    print(f"  [{f.get('category')}] {f['feature']}  (origin={f['origin']}, src={f['source'][:48]})")
print("category 분포:", dict(Counter(f.get("category") for f in b["features"])))
print("open_questions:", b["open_questions"])

print("\n=== 4분류·계약 검증 ===")
CATS = ("Explicit", "Derived", "Operational", "Competitive")
print("모든 기능 4분류 태깅:", all(f.get("category") in CATS for f in b["features"]))
print("features에 Business 없음(자동 채택 금지):", all(f.get("category") != "Business" for f in b["features"]))
print("모든 기능 source 보유:", all(f.get("source") for f in b["features"]))
comp = [f for f in b["features"] if f.get("category") == "Competitive"]
print("Competitive Reference 수:", len(comp), "(search on일 때 기대)")
for f in comp:
    print(f"  - {f['feature']} | URL: {f['source']}")
biz_oq = [q for q in b["open_questions"] if "[Business]" in q or "Business" in q]
print("Business -> open_questions 전환 수:", len(biz_oq))
for q in biz_oq:
    print("  -", q)

print("\n=== 제약 차단(validate) ===")
def block(label, feats, prov=None):
    body = {"features": feats, "open_questions": [], "provenance": prov or {"features": "per_item"}}
    try:
        features_agent.validate(body)
        print(f"{label} -> FAIL: 통과되면 안 됨")
    except ValueError as e:
        print(f"{label} -> 정상 차단: {str(e)[:70]}")

block("source 없는 기능", [{"feature": "유령", "category": "Explicit", "origin": "fact", "priority": "high"}])
block("4분류 태깅 누락", [{"feature": "무분류", "source": "ux:x", "origin": "fact", "priority": "high"}])
block("Business를 features에 넣음", [{"feature": "사업판단", "category": "Business", "source": "derived:x", "origin": "inference"}])
block("Competitive인데 source가 URL 아님",
      [{"feature": "경쟁참고", "category": "Competitive", "source": "ux:x", "origin": "fact"}],
      {"features": "per_item"})


# 새 게이트 레벨 분리: 정상 features 산출은 ERROR 0(FAIL 아님). real/offline 공통.
print("\n=== 게이트 레벨 분리(contract_levels) ===")
import gate_review
gr = gate_review.run_review_gate("features", b)
print("status =", gr["status"], "| ERROR 수 =", len(gr["reasons"]))
for e in gr["reasons"]:
    print("  ERROR:", e)
print("WARN(품질/커버리지) 예:", [w for w in gr["warnings"] if w.startswith("[")][:3])
assert gr["status"] != "FAIL", f"정상 features 산출이 FAIL: {gr['reasons']}"
print("게이트 ERROR 0 통과")
