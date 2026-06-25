"""
Wireframe Agent E2E 검증.
intake -> strategy -> ux -> security -> design_system -> features -> wireframe 까지 돌려
계약 준수, 제약 강제, orchestrator 결합을 확인한다.
오프라인 모드(결정적). site-build.v6 워크플로(wireframe 노드)를 사용한다. 기존 데모/워크플로는 그대로 둔다.
"""
import os, sys, shutil, json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))

from orchestrator import Store, Orchestrator, canonical_hash
import strategy as strategy_agent
import ux as ux_agent
import security as security_agent
import design_system as ds_agent
import features as features_agent
import wireframe as wireframe_agent

ROOT = str(BASE / "_run_wireframe")
PROJECT = 81
if Path(ROOT).exists():
    shutil.rmtree(ROOT)

WF = json.loads((BASE / "workflow" / "site-build.v6.json").read_text(encoding="utf-8"))

PRODUCERS = {
    "strategy": strategy_agent.make_producer(),
    "ux": ux_agent.make_producer(),
    "security": security_agent.make_producer(),
    "design_system": ds_agent.make_producer(),
    "features": features_agent.make_producer(),
    "wireframe": wireframe_agent.make_producer(),
}

store = Store(ROOT, PROJECT)
orc = Orchestrator(store, WF, PRODUCERS)

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

# 정의 단계 파이프라인: 핵심 5종을 순서대로 산출·승인 후 wireframe 산출
for _ in range(5):
    picked = orc.tick()
    print(f"=== tick: {picked} ===")
    orc.human_confirm(picked)
print("=== tick: wireframe ===", orc.tick())

wh = store.head("wireframe")
wv = store.version("wireframe", wh["current_version"])
b = wv["body"]

print("\n=== 산출된 wireframe body ===")
print(json.dumps(b, ensure_ascii=False, indent=2))

print("\n=== 검증 ===")
palette = set(b["design_component_palette"])
feature_set = set(b["feature_index"])
print("design_component_palette(fact, design_system 유래):", b["design_component_palette"])
print("feature_index(fact, features 유래):", b["feature_index"])
all_fact = all(s["origin"] == "fact" for s in b["screens"])
print("screens(모두 fact, ux 정보구조 기반):", [s["screen"] for s in b["screens"]], "| 모두 fact:", all_fact)
comp_ok = all(c in palette for s in b["screens"] for sec in s["sections"] for c in sec["components"])
fref_ok = all(fr in feature_set for s in b["screens"] for sec in s["sections"] for fr in sec["feature_refs"])
print("섹션 components 모두 palette 내(발명 없음):", comp_ok)
print("섹션 feature_refs 모두 feature_index 내(발명 없음):", fref_ok)
print("화면 섹션 구성:")
for s in b["screens"]:
    for sec in s["sections"]:
        print(f"  - [{s['screen']}] {sec['section']}: components={sec['components']} feature_refs={sec['feature_refs']}")
print("navigation:", b["navigation"])
print("open_questions:", b["open_questions"])
print("wireframe head status:", wh["status"], "(in_review = 사람 게이트 대기)")
print("derived_from(불변 provenance, ux/design_system/features 핀):")
for d in wv["derived_from"]:
    print("  ", d)

print("\n=== 제약 강제 확인: No-Fabrication (source 없는 화면) ===")
try:
    wireframe_agent.validate({
        "design_component_palette": ["card"], "feature_index": ["개인 신청"],
        "screens": [{"screen": "유령 화면", "origin": "fact", "sections": []}],
        "navigation": {}, "open_questions": [],
        "provenance": {"design_component_palette": "fact", "feature_index": "fact", "screens": "per_item"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)

print("\n=== 제약 강제 확인: 발명된 컴포넌트 참조(palette 밖) ===")
try:
    wireframe_agent.validate({
        "design_component_palette": ["card"], "feature_index": ["개인 신청"],
        "screens": [{"screen": "메인", "source": "ux:메인", "origin": "fact",
                     "sections": [{"section": "신청", "components": ["carousel"], "feature_refs": ["개인 신청"]}]}],
        "navigation": {}, "open_questions": [],
        "provenance": {"design_component_palette": "fact", "feature_index": "fact",
                       "screens": "per_item", "sections": "inference"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)

print("\n=== 제약 강제 확인: 발명된 기능 참조(feature_index 밖) ===")
try:
    wireframe_agent.validate({
        "design_component_palette": ["card"], "feature_index": ["개인 신청"],
        "screens": [{"screen": "메인", "source": "ux:메인", "origin": "fact",
                     "sections": [{"section": "결제", "components": ["card"], "feature_refs": ["결제 분할"]}]}],
        "navigation": {}, "open_questions": [],
        "provenance": {"design_component_palette": "fact", "feature_index": "fact",
                       "screens": "per_item", "sections": "inference"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)


# ── [real] 기능별 화면 구성 검증(빈 화면 금지). WIREFRAME_MODE=real일 때만 ──
if os.environ.get("WIREFRAME_MODE") == "real":
    print("\n=== [real] 기능별 화면 구성(features·ux·discovery 기반) ===")
    # 위 offline 파이프라인이 만든 실제 features/design_system/ux를 입력으로 재사용.
    feats = store.version("features", store.head("features")["current_version"])["body"]
    dsb = store.version("design_system", store.head("design_system")["current_version"])["body"]
    uxb = store.version("ux", store.head("ux")["current_version"])["body"]
    disc = {
        "goal_interpretation": {"inferred_dimensions": [{"dimension": "예약 성사", "basis": "goal"}],
                                "candidate_metrics": [], "assumptions": []},
        "requirement_normalization": [{"id": f"R-{i+1:02d}", "statement": r, "origin": "explicit"}
                                      for i, r in enumerate(intake_body["requirements"])],
    }
    rb = wireframe_agent.produce({"features": feats, "design_system": dsb, "ux": uxb, "discovery": disc},
                                 llm=wireframe_agent.real_llm)
    screens = rb["screens"]
    print(f"screens {len(screens)}개 (어제 []빈 화면 문제 해결 확인):")
    for s in screens:
        secs = [sec.get("section") for sec in s.get("sections", [])]
        print(f"  [{s['screen']}] source={s.get('source')} origin={s.get('origin')} sections={secs}")
    print("screens 비어있지 않음:", len(screens) > 0)
    src_ok = all(str(s.get("source", "")).startswith(("ux:", "feature:", "derived:")) for s in screens)
    print("모든 screen source가 ux:/feature:/derived: 근거:", src_ok)
    palette = set(rb["design_component_palette"]); fset = set(rb["feature_index"])
    comp_ok = all(c in palette for s in screens for sec in s.get("sections", []) for c in sec.get("components", []))
    fref_ok = all(fr in fset for s in screens for sec in s.get("sections", []) for fr in sec.get("feature_refs", []))
    print("컴포넌트 발명 없음:", comp_ok, "| 기능 참조 발명 없음:", fref_ok)
    assert len(screens) > 0, "features가 있는데 screens가 비었음(빈 화면 문제)"
    assert src_ok, "screen source 근거 위반"
    # 새 게이트 레벨 분리: real 정상 산출은 ERROR 0(FAIL 아님)
    import gate_review
    gr = gate_review.run_review_gate("wireframe", rb)
    print("게이트(레벨 분리): status =", gr["status"], "| ERROR 수 =", len(gr["reasons"]))
    assert gr["status"] != "FAIL", f"real 정상 산출이 FAIL: {gr['reasons']}"
    print("[real] 검증 통과(validate + 게이트 ERROR 0, 빈 화면 없음)")
