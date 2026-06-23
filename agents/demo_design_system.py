"""
Design System Agent E2E 검증.
intake -> strategy -> ux -> design_system 까지 돌려 계약 준수, 제약 강제, orchestrator 결합을 확인한다.
오프라인 모드(결정적). site-build.v4 워크플로(design_system 노드)를 사용한다. 기존 데모/워크플로는 그대로 둔다.
"""
import sys, shutil, json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))

from orchestrator import Store, Orchestrator, canonical_hash
import strategy as strategy_agent
import ux as ux_agent
import design_system as ds_agent

ROOT = str(BASE / "_run_design_system")
PROJECT = 61
if Path(ROOT).exists():
    shutil.rmtree(ROOT)

WF = json.loads((BASE / "workflow" / "site-build.v4.json").read_text(encoding="utf-8"))

PRODUCERS = {
    "strategy": strategy_agent.make_producer(),
    "ux": ux_agent.make_producer(),
    "design_system": ds_agent.make_producer(),
}

store = Store(ROOT, PROJECT)
orc = Orchestrator(store, WF, PRODUCERS)

# intake 시드. brand_tokens가 핵심 색/폰트 근거(human). warning/danger는 일부러 미제공 -> open_questions 유도.
intake_body = {
    "site_character": "풋살 소셜매치 예약",
    "requirements": ["개인 신청", "매치 예약", "정산 확인"],
    "seed_competitors": ["PLAB", "아이엠그라운드"],
    "unique_angles": ["매니저 배정 자동화", "정산 투명성"],
    "brand_tokens": {"accent": "#7C3AED", "success": "#16A34A", "font_family": "Inter, sans-serif"},
}
ver_pk = store.next_pk()
head = {"pk": store.next_pk(), "type": "intake", "project_pk": PROJECT,
        "current_version": 1, "current_version_pk": ver_pk, "status": "confirmed"}
store.append_version({"pk": ver_pk, "type": "intake", "record_pk": head["pk"], "version": 1,
                      "body": intake_body, "body_hash": canonical_hash(intake_body),
                      "derived_from": [], "produced_by_run": None})
store.save_head(head)

# 정의 단계 파이프라인: strategy -> (confirm) -> ux -> (confirm) -> design_system
print("=== tick: strategy ===", orc.tick())
orc.human_confirm("strategy")
print("=== tick: ux ===", orc.tick())
orc.human_confirm("ux")
print("=== tick: design_system ===", orc.tick())

dh = store.head("design_system")
dv = store.version("design_system", dh["current_version"])
b = dv["body"]

print("\n=== 산출된 design_system body (요약) ===")
print(json.dumps({
    "color_tokens": b["color_tokens"],
    "typography": b["typography"],
    "component_specs": [c["component"] for c in b["component_specs"]],
    "icon": b["icon"],
    "accessibility": b["accessibility"],
    "open_questions": b["open_questions"],
    "provenance": b["provenance"],
}, ensure_ascii=False, indent=2))

print("\n=== css_variables_template ===")
print(b["css_variables_template"])

print("\n=== 검증 ===")
# origin 분류 집계
origins = {}
for c in b["color_tokens"]:
    origins[c["origin"]] = origins.get(c["origin"], 0) + 1
print("color_tokens origin 분포:", origins)
accent_tok = next((c for c in b["color_tokens"] if c["token"] == "color-accent"), None)
print("color-accent:", accent_tok["value"], "origin=", accent_tok["origin"], "source=", accent_tok["source"],
      "(입력 brand_tokens.accent와 일치:", accent_tok["value"] == intake_body["brand_tokens"]["accent"], ")")
tint_tok = next((c for c in b["color_tokens"] if c["token"] == "color-accent-tint"), None)
print("color-accent-tint(파생):", tint_tok["value"], "origin=", tint_tok["origin"], "(inference 표기:", tint_tok["origin"] == "inference", ")")
# 모든 color_token source 보유
print("모든 color_token source 보유:", all(c.get("source") for c in b["color_tokens"]))
# 컴포넌트 uses_tokens 무결성
defined = {c["token"] for c in b["color_tokens"]} | {s["token"] for s in b["spacing"]} | {r["token"] for r in b["radius"]}
comp_ok = all(all(tk in defined for tk in c["uses_tokens"]) for c in b["component_specs"])
print("컴포넌트 uses_tokens 모두 정의됨(발명 없음):", comp_ok)
print("component_specs:", [c["component"] for c in b["component_specs"]])
print("open_questions(미제공 의미색 등):", b["open_questions"])
print("design_system head status:", dh["status"], "(in_review = 사람 게이트 대기)")
print("derived_from(불변 provenance):", dv["derived_from"])

print("\n=== 제약 강제 확인: No-Fabrication (source 없는 color_token) ===")
try:
    ds_agent.validate({
        "color_tokens": [{"token": "color-x", "value": "#000000", "mode": "shared", "origin": "human"}],
        "typography": {}, "spacing": [], "radius": [], "elevation": [], "component_specs": [],
        "icon": {}, "accessibility": {}, "css_variables_template": "", "open_questions": [],
        "provenance": {"color_tokens": "per_token"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)

print("\n=== 제약 강제 확인: 추론 층 분리 (입력 토큰을 inference로 표기) ===")
try:
    ds_agent.validate({
        "color_tokens": [{"token": "color-accent", "value": "#7C3AED", "mode": "shared",
                          "origin": "inference", "source": "brand_tokens.accent"}],
        "typography": {}, "spacing": [], "radius": [], "elevation": [], "component_specs": [],
        "icon": {}, "accessibility": {}, "css_variables_template": "", "open_questions": [],
        "provenance": {"color_tokens": "per_token"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)

print("\n=== 제약 강제 확인: 발명된 토큰 참조 (컴포넌트가 미정의 토큰 참조) ===")
try:
    ds_agent.validate({
        "color_tokens": [{"token": "color-accent", "value": "#7C3AED", "mode": "shared",
                          "origin": "human", "source": "brand_tokens.accent"}],
        "typography": {}, "spacing": [], "radius": [], "elevation": [],
        "component_specs": [{"component": "button", "spec": {}, "uses_tokens": ["color-ghost"]}],
        "icon": {}, "accessibility": {}, "css_variables_template": "", "open_questions": [],
        "provenance": {"color_tokens": "per_token"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)
