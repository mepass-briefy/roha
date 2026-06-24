"""
Mobile Agent E2E 검증.
intake -> strategy -> ux -> security -> design_system -> features -> wireframe -> backend -> mobile 까지 돌려
계약 준수, 제약 강제, 전파, 모바일 고유 요소를 확인한다.
오프라인 모드(결정적). site-build.v9 워크플로(mobile 노드)를 사용한다. 기존 데모/워크플로는 그대로 둔다.
"""
import sys, shutil, json, copy
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
import backend as backend_agent
import mobile as mobile_agent
from mobile import MobileBody, MobileScreen, DataCall, ComponentUse, OutcomeUI
from pydantic import ValidationError

ROOT = str(BASE / "_run_mobile")
PROJECT = 111
if Path(ROOT).exists():
    shutil.rmtree(ROOT)

WF = json.loads((BASE / "workflow" / "site-build.v9.json").read_text(encoding="utf-8"))

ARTIFACT_DIR = Path(ROOT) / "artifacts"
PRODUCERS = {
    "strategy": strategy_agent.make_producer(),
    "ux": ux_agent.make_producer(),
    "security": security_agent.make_producer(),
    "design_system": ds_agent.make_producer(),
    "features": features_agent.make_producer(),
    "wireframe": wireframe_agent.make_producer(),
    "backend": backend_agent.make_producer(artifact_dir=ARTIFACT_DIR),
    "mobile": mobile_agent.make_producer(artifact_dir=ARTIFACT_DIR),
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

# strategy~backend 7개 노드를 순서대로 산출·승인 후 mobile 산출
for _ in range(7):
    picked = orc.tick()
    print(f"=== tick: {picked} ===")
    orc.human_confirm(picked)
print("=== tick: mobile ===", orc.tick())

mh = store.head("mobile")
mv = store.version("mobile", mh["current_version"])
b = mv["body"]

print("\n=== 검증 (Frontend와 동일 계약) ===")
print("반환 타입 dict:", type(b).__name__, "| platform:", b["platform"])
scr = b["screens"]
print("screen_index:", b["screen_index"], "| 화면 수:", len(scr))
print("모든 screen_ref ⊆ screen_index:", all(s["screen_ref"] in b["screen_index"] for s in scr))
print("모든 component_ref ⊆ palette:", all(c["component_ref"] in b["component_palette"] for s in scr for c in s["components"]))
print("모든 endpoint_ref ⊆ endpoint_index:", all(d["endpoint_ref"] in b["endpoint_index"] for s in scr for d in s["data_calls"]))
print("모든 outcome code ⊆ outcome_code_index:",
      all(o["code"] in b["outcome_code_index"] for s in scr for d in s["data_calls"] for o in d["outcome_mapping"]))
print("모든 uses_tokens ⊆ token_index:", all(t in b["token_index"] for s in scr for t in s["uses_tokens"]))
print("내부 PK 미사용:", all(p == "public_key" for s in scr for d in s["data_calls"] for p in d["path_params"]))

print("\n=== 모바일 고유 요소(근거 있을 때만 적용) ===")
for s in scr:
    print(f"  screen='{s['screen_ref']}' navigation={s['navigation']}")
    print(f"    touch_target={s['touch_target']}")
    print(f"    dark_mode={s['dark_mode']}")
    print(f"    safe_area={s['safe_area']}")
print("단일 화면이라 bottom nav 미적용(navigation None):", all(s["navigation"] is None for s in scr) and len(b["screen_index"]) == 1)
print("터치 타겟 근거 있음 -> 적용:", all(s["touch_target"] for s in scr))
print("다크 토큰 근거 있음 -> 다크모드 적용:", all(s["dark_mode"] for s in scr))
print("safe area 근거 없음 -> 미적용(None) + open_questions:",
      all(s["safe_area"] is None for s in scr) and any("safe-area" in q for q in b["open_questions"]))

print("\n=== Open Question 전파 (Frontend와 동일 정책) ===")
prop = [q for q in b["open_questions"] if q.startswith("[전파:")]
print("전파된 open_questions 수:", len(prop))
bk_req = [q for q in prop if "request schema 미정" in q]
bk_409 = [q for q in prop if "도메인 특수 case" in q]
print("backend POST 요청필드 미정 표면화:", len(bk_req), "건 | 409 등 특수 case:", len(bk_409), "건")
print("explicit_not_implemented(wireframe 미배치):")
for e in b["explicit_not_implemented"]:
    print(f"  - {e['item']} | {e['reason']}")
print("wireframe 미배치 기능 기록 수:", len(b["explicit_not_implemented"]), "(기대 2)")

print("\n=== artifact (코드는 body 밖) ===")
for a in b["artifact_refs"]:
    print(f"  {a['path']} kind={a['kind']} bytes={a['bytes']} 존재={ (ARTIFACT_DIR / a['path']).exists() }")
print("body에 코드 본문 없음:", "throw new Error" not in json.dumps(b, ensure_ascii=False))
print("derived_from(불변, wireframe/design_system/backend 핀):", mv["derived_from"])

# ===== 제약 차단 실측 (Frontend와 동일 6종) =====
def base_body(**over):
    body = {
        "platform": "mobile", "screen_index": ["메인"], "endpoint_index": ["ep-applications-list"],
        "outcome_code_index": ["OK", "VALIDATION_ERROR"],
        "component_palette": ["card", "button"], "token_index": ["color-accent", "r-md"],
        "screens": [{"screen_ref": "메인", "origin": "fact",
                     "components": [{"component_ref": "card", "section": "s"}],
                     "data_calls": [{"endpoint_ref": "ep-applications-list", "method": "GET",
                                     "path_params": ["public_key"],
                                     "outcome_mapping": [{"code": "OK", "ui_hint": "x"}]}],
                     "states": None, "uses_tokens": ["color-accent"], "navigation": None,
                     "touch_target": None, "dark_mode": None, "safe_area": None}],
        "artifact_refs": [], "provenance": {"screens": "per_item"},
    }
    body.update(over)
    return body


def screen_with(**over):
    sc = {"screen_ref": "메인", "origin": "fact",
          "components": [{"component_ref": "card", "section": "s"}],
          "data_calls": [{"endpoint_ref": "ep-applications-list", "method": "GET",
                          "path_params": ["public_key"], "outcome_mapping": [{"code": "OK", "ui_hint": "x"}]}],
          "states": None, "uses_tokens": ["color-accent"], "navigation": None,
          "touch_target": None, "dark_mode": None, "safe_area": None}
    sc.update(over)
    return sc


def expect_block(label, body):
    try:
        MobileBody(**body)
        print(f"{label} -> FAIL: 통과되면 안 됨")
    except ValidationError as e:
        print(f"{label} -> 정상 차단:", e.errors()[0]["msg"])


print("\n=== 제약 차단 실측 (6종, Frontend와 동일) ===")
expect_block("1. wireframe에 없는 screen_ref", base_body(screens=[screen_with(screen_ref="유령화면")]))
expect_block("2. backend에 없는 endpoint_ref",
             base_body(screens=[screen_with(data_calls=[{"endpoint_ref": "ep-없음", "method": "GET",
                                                          "path_params": [], "outcome_mapping": []}])]))
expect_block("3. backend에 없는 outcome code",
             base_body(screens=[screen_with(data_calls=[{"endpoint_ref": "ep-applications-list", "method": "GET",
                                                          "path_params": [],
                                                          "outcome_mapping": [{"code": "TEAPOT", "ui_hint": "x"}]}])]))
expect_block("4. 정의 밖 component_ref", base_body(screens=[screen_with(components=[{"component_ref": "carousel", "section": "s"}])]))
expect_block("5. design token 밖의 값", base_body(screens=[screen_with(uses_tokens=["color-없음"])]))
expect_block("6. 내부 PK 사용",
             base_body(screens=[screen_with(data_calls=[{"endpoint_ref": "ep-applications-list", "method": "GET",
                                                          "path_params": ["application_id"],
                                                          "outcome_mapping": [{"code": "OK", "ui_hint": "x"}]}])]))

# Blocking Rule: design token 결손 -> 화면 미생성
print("\n=== Blocking Rule 실측: design token 결손 -> 화면 차단 ===")
wf_body = store.version("wireframe", store.head("wireframe")["current_version"])["body"]
ds_body = store.version("design_system", store.head("design_system")["current_version"])["body"]
bk_body = store.version("backend", store.head("backend")["current_version"])["body"]
ds_no_tokens = copy.deepcopy(ds_body)
ds_no_tokens["color_tokens"] = []
ds_no_tokens["spacing"] = []
ds_no_tokens["radius"] = []
for c in ds_no_tokens.get("component_specs", []):
    c["uses_tokens"] = []
blocked = mobile_agent.produce({"wireframe": wf_body, "design_system": ds_no_tokens, "backend": bk_body},
                               artifact_dir=ARTIFACT_DIR)
print("차단 후 screens 수:", len(blocked["screens"]), "(0이면 전부 차단)")
print("Blocking open_questions:", [q for q in blocked["open_questions"] if "Blocking" in q])
