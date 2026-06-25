"""
Frontend Agent E2E 검증.
intake -> strategy -> ux -> security -> design_system -> features -> wireframe -> backend -> frontend 까지 돌려
계약 준수, 제약 강제, orchestrator 결합, Pydantic 검증을 확인한다.
오프라인 모드(결정적). site-build.v8 워크플로(frontend 노드)를 사용한다. 기존 데모/워크플로는 그대로 둔다.
"""
import os, sys, shutil, json, copy
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

print("\n=== Open Question 전파 실측 ===")
prop = [q for q in b["open_questions"] if q.startswith("[전파:")]
print("전파된 open_questions 수:", len(prop))
for q in prop:
    print("  -", q)
bk_req = [q for q in prop if "request schema 미정" in q]
print("backend POST 요청 필드 미정 -> frontend 표면화:", len(bk_req) > 0, f"({len(bk_req)}건)")
print("\nexplicit_not_implemented(알지만 입력 부족으로 미구현):")
for e in b["explicit_not_implemented"]:
    print(f"  - item={e['item']} | reason={e['reason']}")
wf_ni = [e for e in b["explicit_not_implemented"] if "wireframe 미배치" in e["reason"]]
print("wireframe 미배치 보완 기능 기록 수:", len(wf_ni), "(기대 2)")

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


# 새 게이트 레벨 분리: offline 정상 산출은 ERROR 0(FAIL 아님).
print("\n=== 게이트 레벨 분리(contract_levels) ===")
import gate_review
gr = gate_review.run_review_gate("frontend", b)
print("offline status =", gr["status"], "| ERROR 수 =", len(gr["reasons"]))
for e in gr["reasons"]:
    print("  ERROR:", e)
assert gr["status"] != "FAIL", f"정상 frontend가 FAIL: {gr['reasons']}"

# [7] real 산출이 새 기준에서 통과(FAIL 아님). FRONTEND_MODE=real일 때만.
# 주의: offline 파이프라인은 design_system(component/foundation) vs wireframe·frontend(component_specs/color_tokens)
# 상위 shape 불일치(선행 통합 갭, BACKLOG)로 빈 화면을 낸다. real frontend 자체 검증을 위해
# frontend 계약 형상에 맞춘 일관 입력(wireframe·design_system·backend)을 직접 구성해 단발 real을 확인한다.
if os.environ.get("FRONTEND_MODE") == "real":
    print("\n=== [real] 화면·컴포넌트 기반 프런트 산출(계약 형상 일관 입력) ===")
    WF_IN = {
        "screens": [
            {"screen": "신청 목록", "sections": [{"section": "목록", "components": ["table", "card"], "feature_refs": ["개인 신청"]}]},
            {"screen": "정산 내역", "sections": [{"section": "내역", "components": ["table"], "feature_refs": ["정산 확인"]}]},
        ],
        "design_component_palette": ["table", "card", "button", "input"],
        "navigation": {"pattern": "left-sidebar"}, "open_questions": [],
    }
    DS_IN = {
        "component_specs": [
            {"component": "table", "uses_tokens": ["color-primary", "r-md"]},
            {"component": "card", "uses_tokens": ["color-surface", "sp-2"]},
            {"component": "button", "uses_tokens": ["color-primary"]},
            {"component": "input", "uses_tokens": ["color-outline", "r-sm"]},
        ],
        "color_tokens": [{"token": "color-primary"}, {"token": "color-surface"}, {"token": "color-outline"}],
        "spacing": [{"token": "sp-2"}], "radius": [{"token": "r-md"}, {"token": "r-sm"}], "open_questions": [],
    }
    def _ep(eid, method, path, feat, succ, err):
        return {"endpoint_id": eid, "method": method, "path": path, "feature_ref": feat, "security_ref": "ctrl",
                "success_cases": [{"code": succ, "http_status": 200, "description": "d"}],
                "error_cases": [{"code": err, "http_status": 400, "description": "d"}]}
    BK_IN = {"api_spec": {"endpoints": [
        _ep("ep-applications-list", "GET", "/api/v1/applications", "개인 신청", "OK", "VALIDATION_ERROR"),
        _ep("ep-applications-get", "GET", "/api/v1/applications/{public_key}", "개인 신청", "OK", "NOT_FOUND"),
        _ep("ep-settlements-list", "GET", "/api/v1/settlements", "정산 확인", "OK", "FORBIDDEN"),
    ]}, "open_questions": []}
    disc = {"goal_interpretation": {"inferred_dimensions": [{"dimension": "정산 신뢰", "basis": "goal"}],
                                    "candidate_metrics": [], "assumptions": []},
            "requirement_normalization": [{"id": "R-01", "statement": "개인 신청", "origin": "explicit"},
                                          {"id": "R-02", "statement": "정산 확인", "origin": "explicit"}]}
    rb = frontend_agent.produce({"wireframe": WF_IN, "design_system": DS_IN, "backend": BK_IN,
                                 "ux": {}, "discovery": disc}, llm=frontend_agent.real_llm, artifact_dir=ARTIFACT_DIR)
    scr = rb["screens"]
    print(f"screens {len(scr)}개:")
    for s in scr:
        print(f"  {s['screen_ref']} | comps={[c['component_ref'] for c in s['components']]} | calls={[d['endpoint_ref'] for d in s['data_calls']]} | tokens={s['uses_tokens'][:4]}")
    grr = gate_review.run_review_gate("frontend", rb)
    print("real 게이트 status =", grr["status"], "| ERROR 수 =", len(grr["reasons"]))
    for e in grr["reasons"]:
        print("  ERROR:", e)
    # (a) 비어있지 않음 (b) 화면별 구성 (c) 멤버십 근거 (d) 토큰 참조(하드코딩 0)
    import re as _re
    hard = [t for s in scr for t in s["uses_tokens"] if _re.search(r"#[0-9A-Fa-f]{3,8}", str(t))]
    print("(a) 비어있지 않음:", len(scr) > 0, "| (d) 하드코딩 색:", hard or "없음")
    assert len(scr) > 0 and grr["status"] != "FAIL" and not hard
    print("[real] 검증 통과(Pydantic 멤버십 + 게이트 ERROR 0, 하드코딩 0)")
print("게이트 ERROR 0 통과")
