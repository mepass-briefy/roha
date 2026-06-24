"""
Features Agent E2E 검증.
intake -> strategy -> ux -> security -> features 까지 돌려 계약 준수, 제약 강제, orchestrator 결합을 확인한다.
오프라인 모드(결정적). site-build.v5 워크플로(features 노드)를 사용한다. 기존 데모/워크플로는 그대로 둔다.
"""
import sys, shutil, json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))

from orchestrator import Store, Orchestrator, canonical_hash
import strategy as strategy_agent
import ux as ux_agent
import security as security_agent
import features as features_agent

ROOT = str(BASE / "_run_features")
PROJECT = 71
if Path(ROOT).exists():
    shutil.rmtree(ROOT)

WF = json.loads((BASE / "workflow" / "site-build.v5.json").read_text(encoding="utf-8"))

PRODUCERS = {
    "strategy": strategy_agent.make_producer(),
    "ux": ux_agent.make_producer(),
    "security": security_agent.make_producer(),
    "features": features_agent.make_producer(),
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

# 정의 단계: strategy -> ux -> security -> features (각 사람 게이트 승인)
for node in ("strategy", "ux", "security"):
    picked = orc.tick()
    print(f"=== tick: {picked} ===")
    orc.human_confirm(picked)
print("=== tick: features ===", orc.tick())

fh = store.head("features")
fv = store.version("features", fh["current_version"])
b = fv["body"]

print("\n=== 산출된 features body ===")
print(json.dumps(b, ensure_ascii=False, indent=2))

print("\n=== 검증 ===")
core = [f for f in b["features"] if f["origin"] == "fact"]
enh = [f for f in b["features"] if f["origin"] == "inference"]
print("핵심 기능(fact, ux 태스크 기반):", [f["feature"] for f in core])
print("  모두 source가 ux:/requirement:", all(f["source"].startswith(("ux:", "requirement:")) for f in core))
print("보완 기능(inference, derived):", [f["feature"] for f in enh])
print("  모두 source가 derived:", all(f["source"].startswith("derived:") for f in enh))
print("기능별 security_controls 매핑:")
for f in core:
    print(f"  - {f['feature']}: {f['security_controls']}")
print("모든 feature source 보유:", all(f.get("source") for f in b["features"]))
print("priority 분포:", {f["feature"]: f["priority"] for f in b["features"]})
print("open_questions:", b["open_questions"])
print("features head status:", fh["status"], "(in_review = 사람 게이트 대기)")
print("derived_from(불변 provenance, intake/strategy/ux/security 핀):")
for d in fv["derived_from"]:
    print("  ", d)

print("\n=== 제약 강제 확인: No-Fabrication (source 없는 기능) ===")
try:
    features_agent.validate({
        "features": [{"feature": "유령 기능", "origin": "fact", "priority": "high"}],
        "open_questions": [], "provenance": {"features": "per_item"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)

print("\n=== 제약 강제 확인: 추론 층 분리 (핵심 기능에 derived source) ===")
try:
    features_agent.validate({
        "features": [{"feature": "임의 기능", "source": "derived:추측", "origin": "fact", "priority": "high"}],
        "open_questions": [], "provenance": {"features": "per_item"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)

print("\n=== 제약 강제 확인: 보완 기능에 ux source(inference인데 ux:) ===")
try:
    features_agent.validate({
        "features": [{"feature": "임의 보완", "source": "ux:개인 신청", "origin": "inference", "priority": "low"}],
        "open_questions": [], "provenance": {"features": "per_item"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)
