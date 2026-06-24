"""
Frontend Agent E2E 검증.
intake -> strategy -> ux -> security -> design_system -> features -> wireframe -> backend -> frontend 까지 돌려
계약 준수, 제약 강제, orchestrator 결합, Pydantic 검증을 확인한다.
오프라인 모드(결정적). site-build.v8 워크플로(frontend 노드)를 사용한다. 기존 데모/워크플로는 그대로 둔다.
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
import frontend as frontend_agent
from frontend import FrontendBody, Screen, ComponentUse, DataCall, OutcomeUI
from pydantic import ValidationError

ROOT = str(BASE / "_run_frontend")
PROJECT = 101
if Path(ROOT).exists():
    shutil.rmtree(ROOT)

WF = json.loads((BASE / "workflow" / "site-build.v8.json").read_text(encoding="utf-8"))

ARTIFACT_DIR = Path(ROOT) / "artifacts"
PRODUCERS = {
    "strategy": strategy_agent.make_producer(),
    "ux": ux_agent.make_producer(),
    "security": security_agent.make_producer(),
    "design_system": ds_agent.make_producer(),
    "features": features_agent.make_producer(),
    "wireframe": wireframe_agent.make_producer(),
    "backend": backend_agent.make_producer(artifact_dir=ARTIFACT_DIR),
    "frontend": frontend_agent.make_producer(artifact_dir=ARTIFACT_DIR),
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

# strategy~backend 7개 노드를 순서대로 산출·승인 후 frontend 산출
for _ in range(7):
    picked = orc.tick()
    print(f"=== tick: {picked} ===")
    orc.human_confirm(picked)
print("=== tick: frontend ===", orc.tick())

fh = store.head("frontend")
fv = store.version("frontend", fh["current_version"])
b = fv["body"]

print("\n=== 산출된 frontend body ===")
print(json.dumps(b, ensure_ascii=False, indent=2))

print("\n=== 검증 ===")
print("반환 타입 dict(Pydantic 아님):", type(b).__name__)
print("screen_index(wireframe 유래):", b["screen_index"])
print("endpoint_index(backend 유래) 수:", len(b["endpoint_index"]))
print("outcome_code_index(backend 유래):", b["outcome_code_index"])
print("component_palette:", b["component_palette"])
scr = b["screens"]
print("화면 수:", len(scr))
for s in scr:
    print(f"  screen_ref={s['screen_ref']!r} origin={s['origin']} "
          f"components={[c['component_ref'] for c in s['components']]} "
          f"data_calls={[d['endpoint_ref'] for d in s['data_calls']]} "
          f"navigation={s['navigation']}")
    for d in s["data_calls"]:
        print(f"      {d['endpoint_ref']}: path_params={d['path_params']} "
              f"outcome={[o['code'] for o in d['outcome_mapping']]}")
print("모든 screen_ref ⊆ screen_index:", all(s["screen_ref"] in b["screen_index"] for s in scr))
print("모든 component_ref ⊆ palette:",
      all(c["component_ref"] in b["component_palette"] for s in scr for c in s["components"]))
print("모든 endpoint_ref ⊆ endpoint_index:",
      all(d["endpoint_ref"] in b["endpoint_index"] for s in scr for d in s["data_calls"]))
print("모든 outcome code ⊆ outcome_code_index:",
      all(o["code"] in b["outcome_code_index"] for s in scr for d in s["data_calls"] for o in d["outcome_mapping"]))
print("모든 uses_tokens ⊆ token_index:",
      all(t in b["token_index"] for s in scr for t in s["uses_tokens"]))
print("내부 PK 미사용(path_params는 public_key만):",
      all(p == "public_key" for s in scr for d in s["data_calls"] for p in d["path_params"]))
print("단일 화면이라 navigation 미적용:", all(s["navigation"] is None for s in scr) and len(b["screen_index"]) == 1)
print("artifact_refs(코드는 body 밖, 파일로):")
for a in b["artifact_refs"]:
    print(f"  {a['path']} kind={a['kind']} checksum={a['checksum']} bytes={a['bytes']} screen_ref={a['screen_ref']!r}")
print("실제 파일 존재:", all((ARTIFACT_DIR / a["path"]).exists() for a in b["artifact_refs"]))
print("body에 코드 본문 없음:", "throw new Error" not in json.dumps(b, ensure_ascii=False))
print("State Contract 검토(API 사용 화면 상태 open_questions):")
for q in b["open_questions"]:
    print("  -", q)
print("derived_from(불변, wireframe/design_system/backend 핀):", fv["derived_from"])

# ===== Blocking Rule 실측: design token 누락 시 화면 미생성 + open_questions =====
print("\n=== Blocking Rule 실측: design token 결손 -> 화면 차단 ===")
wf_body = store.version("wireframe", store.head("wireframe")["current_version"])["body"]
ds_body = store.version("design_system", store.head("design_system")["current_version"])["body"]
bk_body = store.version("backend", store.head("backend")["current_version"])["body"]
ds_no_tokens = copy.deepcopy(ds_body)
ds_no_tokens["color_tokens"] = []
ds_no_tokens["spacing"] = []
ds_no_tokens["radius"] = []
# component_specs의 uses_tokens도 비워 token 근거 제거
for c in ds_no_tokens.get("component_specs", []):
    c["uses_tokens"] = []
blocked = frontend_agent.produce({"wireframe": wf_body, "design_system": ds_no_tokens, "backend": bk_body},
                                 artifact_dir=ARTIFACT_DIR)
print("차단 후 screens 수:", len(blocked["screens"]), "(0이면 전부 차단)")
print("Blocking open_questions:", [q for q in blocked["open_questions"] if "Blocking" in q])

# ===== 제약 차단 실측 (Pydantic) =====
def base_body(**over):
    body = {
        "screen_index": ["메인"], "endpoint_index": ["ep-applications-list"],
        "outcome_code_index": ["OK", "VALIDATION_ERROR"],
        "component_palette": ["card", "button"], "token_index": ["color-accent", "r-md"],
        "screens": [{"screen_ref": "메인", "origin": "fact",
                     "components": [{"component_ref": "card", "section": "s"}],
                     "data_calls": [{"endpoint_ref": "ep-applications-list", "method": "GET",
                                     "path_params": ["public_key"],
                                     "outcome_mapping": [{"code": "OK", "ui_hint": "x"}]}],
                     "states": None, "uses_tokens": ["color-accent"], "navigation": None}],
        "artifact_refs": [], "provenance": {"screens": "per_item"},
    }
    body.update(over)
    return body


def screen_with(**over):
    sc = {"screen_ref": "메인", "origin": "fact",
          "components": [{"component_ref": "card", "section": "s"}],
          "data_calls": [{"endpoint_ref": "ep-applications-list", "method": "GET",
                          "path_params": ["public_key"], "outcome_mapping": [{"code": "OK", "ui_hint": "x"}]}],
          "states": None, "uses_tokens": ["color-accent"], "navigation": None}
    sc.update(over)
    return sc


def expect_block(label, body):
    try:
        FrontendBody(**body)
        print(f"{label} -> FAIL: 통과되면 안 됨")
    except ValidationError as e:
        print(f"{label} -> 정상 차단:", e.errors()[0]["msg"])


print("\n=== 제약 차단 실측 ===")
expect_block("1. wireframe에 없는 screen_ref",
             base_body(screens=[screen_with(screen_ref="유령화면")]))
expect_block("2. backend에 없는 endpoint_ref",
             base_body(screens=[screen_with(data_calls=[{"endpoint_ref": "ep-없음", "method": "GET",
                                                          "path_params": [], "outcome_mapping": []}])]))
expect_block("3. backend에 없는 outcome code",
             base_body(screens=[screen_with(data_calls=[{"endpoint_ref": "ep-applications-list", "method": "GET",
                                                          "path_params": [],
                                                          "outcome_mapping": [{"code": "TEAPOT", "ui_hint": "x"}]}])]))
expect_block("4. 정의 밖 component_ref",
             base_body(screens=[screen_with(components=[{"component_ref": "carousel", "section": "s"}])]))
expect_block("5. design token 밖의 값",
             base_body(screens=[screen_with(uses_tokens=["color-없음"])]))
expect_block("6. 내부 PK 사용(path_params)",
             base_body(screens=[screen_with(data_calls=[{"endpoint_ref": "ep-applications-list", "method": "GET",
                                                          "path_params": ["application_id"],
                                                          "outcome_mapping": [{"code": "OK", "ui_hint": "x"}]}])]))
