"""
Backend (API) Agent E2E 검증.
intake -> strategy -> ux -> security -> features -> backend 까지 돌려
계약 준수, 제약 강제, orchestrator 결합, Pydantic 검증을 확인한다.
오프라인 모드(결정적). site-build.v7 워크플로(backend 노드)를 사용한다. 기존 데모/워크플로는 그대로 둔다.
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
import features as features_agent
import backend as backend_agent
from backend import Endpoint, OutcomeCase, RequestField, error_response, build_prompt
from pydantic import ValidationError

ROOT = str(BASE / "_run_backend")
PROJECT = 91
if Path(ROOT).exists():
    shutil.rmtree(ROOT)

WF = json.loads((BASE / "workflow" / "site-build.v7.json").read_text(encoding="utf-8"))

ARTIFACT_DIR = Path(ROOT) / "artifacts"
PRODUCERS = {
    "strategy": strategy_agent.make_producer(),
    "ux": ux_agent.make_producer(),
    "security": security_agent.make_producer(),
    "features": features_agent.make_producer(),
    "backend": backend_agent.make_producer(artifact_dir=ARTIFACT_DIR),
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

# strategy -> ux -> security -> features (각 승인) 후 backend 산출
for _ in range(4):
    picked = orc.tick()
    print(f"=== tick: {picked} ===")
    orc.human_confirm(picked)
print("=== tick: backend ===", orc.tick())

bh = store.head("backend")
bv = store.version("backend", bh["current_version"])
b = bv["body"]

print("\n=== 동적 프롬프트 조합 확인(E15) ===")
prompt = build_prompt(store.version("features", store.head("features")["current_version"])["body"],
                      store.version("security", store.head("security")["current_version"])["body"])
print("프롬프트 메시지 수:", len(prompt), "| roles:", [m["role"] for m in prompt])
print("system에 계약 규칙 주입됨:", "계약 규칙(주입)" in prompt[0]["content"])
print("user에 features/security 입력 포함:", '"features"' in prompt[1]["content"] and '"security"' in prompt[1]["content"])

print("\n=== 산출된 backend body (api_spec 요약 + artifact 메타) ===")
print("response_contract 고정:", b["api_spec"]["response_contract"] == backend_agent.RESPONSE_CONTRACT)
for ep in b["api_spec"]["endpoints"]:
    print(f"  {ep['method']:6} {ep['path']:34} feature_ref={ep['feature_ref']!r} security_ref={ep['security_ref'][:14]!r}... "
          f"succ={[c['code'] for c in ep['success_cases']]} err={[c['code'] for c in ep['error_cases']]}"
          f"{' [pagination]' if ep['pagination'] else ''}")
print("\nartifact_refs(코드는 body 밖, 파일로):")
for a in b["artifact_refs"]:
    print(f"  {a['path']}  kind={a['kind']} checksum={a['checksum']} bytes={a['bytes']}")
print("실제 파일 존재 확인:", all((ARTIFACT_DIR / a["path"]).exists() for a in b["artifact_refs"]))
print("body에 코드 본문 없음(artifact만):", "def handle_" not in json.dumps(b, ensure_ascii=False))

print("\n=== 검증 ===")
print("반환 타입 dict(Pydantic 아님):", type(b).__name__)
print("URL은 모두 /api/v1, public_key만 노출:",
      all(e["path"].startswith("/api/v1/") for e in b["api_spec"]["endpoints"]) and
      all(("{" not in seg) or seg == "{public_key}" for e in b["api_spec"]["endpoints"] for seg in e["path"].split("/")))
print("모든 endpoint feature_ref/security_ref 보유:",
      all(e["feature_ref"] and e["security_ref"] for e in b["api_spec"]["endpoints"]))
print("list endpoint만 pagination:",
      all((e["pagination"] is not None) == e["endpoint_id"].endswith("-list") for e in b["api_spec"]["endpoints"]))
print("open_questions(도메인 필드/특수 case 근거 없음 표기):")
for q in b["open_questions"]:
    print("  -", q)
print("backend head status:", bh["status"], "(in_review = 사람 게이트 대기)")
print("derived_from(불변, features/security 핀):", bv["derived_from"])

# ===== 제약 차단 실측 (J22) =====
# 유효 endpoint 골격(차단 테스트의 베이스)
GOOD_SUCC = [OutcomeCase(code="OK", http_status=200, description="ok")]
GOOD_ERR = [OutcomeCase(code="VALIDATION_ERROR", http_status=400, description="bad")]


def base_kwargs(**over):
    kw = dict(endpoint_id="ep-x", method="GET", path="/api/v1/applications",
              feature_ref="개인 신청", security_ref="개인정보(PII) 보호·최소수집",
              request_schema=[], success_cases=GOOD_SUCC, error_cases=GOOD_ERR,
              acceptance_criteria=[], pagination=None, provenance={})
    kw.update(over)
    return kw


print("\n=== 제약 강제 1: feature_ref 없는 endpoint 차단 ===")
try:
    Endpoint(**base_kwargs(feature_ref=""))
    print("FAIL: 통과되면 안 됨")
except ValidationError as e:
    print("정상 차단:", e.errors()[0]["msg"])

print("\n=== 제약 강제 2: security_ref 없는 권한 차단 ===")
try:
    Endpoint(**base_kwargs(security_ref=""))
    print("FAIL: 통과되면 안 됨")
except ValidationError as e:
    print("정상 차단:", e.errors()[0]["msg"])

print("\n=== 제약 강제 3: URL에 내부 PK 노출 차단 ===")
try:
    Endpoint(**base_kwargs(path="/api/v1/applications/{id}"))
    print("FAIL: 통과되면 안 됨")
except ValidationError as e:
    print("정상 차단:", e.errors()[0]["msg"])

print("\n=== 제약 강제 4: error_cases에 없는 error.code 차단 ===")
ep_ok = Endpoint(**base_kwargs())
try:
    error_response(ep_ok, "NOT_FOUND", "없음")  # error_cases에 VALIDATION_ERROR만 있음
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)

print("\n=== (보너스) request 필드 format 생략 차단 ===")
try:
    RequestField(name="x", type="string", required=True, format="")
    print("FAIL: 통과되면 안 됨")
except ValidationError as e:
    print("정상 차단:", e.errors()[0]["msg"])


# ── offline 엔티티(식별자 3종) 확인 ──
print("\n=== 엔티티(데이터 모델) — 식별자 3종 ===")
for e in b.get("entities", []):
    ids = e["identifiers"]
    print(f"  {e['name']:14} source={e['source']!r} pk/business/public 보유:",
          bool(ids.get("pk") and ids.get("business_key") and ids.get("public_key")))
print("엔티티 비어있지 않음(features 있음):", len(b.get("entities", [])) > 0)
assert b.get("entities"), "features가 있는데 entities가 비었음"
assert all(e["source"].startswith(("feature:", "ux:")) for e in b["entities"]), "entity source 근거 위반"

# ── [real] 기능 기반 엔티티·API 설계(BACKEND_MODE=real일 때만) ──
if os.environ.get("BACKEND_MODE") == "real":
    print("\n=== [real] 기능 기반 엔티티·API(features·ux·discovery 기반) ===")
    feats = store.version("features", store.head("features")["current_version"])["body"]
    sec = store.version("security", store.head("security")["current_version"])["body"]
    uxb = store.version("ux", store.head("ux")["current_version"])["body"]
    disc = {
        "goal_interpretation": {"inferred_dimensions": [{"dimension": "예약 성사·정산 신뢰", "basis": "goal"}],
                                "candidate_metrics": [], "assumptions": []},
        "requirement_normalization": [{"id": f"R-{i+1:02d}", "statement": r, "origin": "explicit"}
                                      for i, r in enumerate(intake_body["requirements"])],
        "proposed_requirements": [],
    }
    rb = backend_agent.produce({"features": feats, "security": sec, "ux": uxb, "discovery": disc},
                               llm=backend_agent.real_llm, artifact_dir=ARTIFACT_DIR)
    ents = rb["entities"]; eps = rb["api_spec"]["endpoints"]
    print(f"entities {len(ents)}개:")
    for e in ents:
        ids = e["identifiers"]
        print(f"  {e['name']} | source={e['source']} | 3키:{bool(ids['pk'] and ids['business_key'] and ids['public_key'])} | fields={[f['name'] for f in e.get('fields',[])][:5]} | rel={[r.get('to') for r in e.get('relations',[])]}")
    print(f"endpoints {len(eps)}개:")
    for ep in eps[:8]:
        print(f"  {ep['method']:6} {ep['path']:30} feature_ref={ep['feature_ref']!r}")
    # 검증
    print("(a) 비어있지 않음:", len(ents) > 0 and len(eps) > 0)
    print("(b) 기능별 다양성: 고유 엔티티", len({e['name'] for e in ents}), "/ 고유 feature_ref", len({ep['feature_ref'] for ep in eps}))
    src_ok = all(e['source'].startswith(('feature:', 'ux:')) for e in ents) and all(ep['feature_ref'] for ep in eps)
    print("(c) source feature:/ux: 근거:", src_ok)
    key3 = all(e['identifiers']['pk'] and e['identifiers']['business_key'] and e['identifiers']['public_key'] for e in ents)
    pub_only = all(('{' not in seg) or seg == '{public_key}' for ep in eps for seg in ep['path'].split('/'))
    print("(d) 식별자 3종 + 외부 public_key만:", key3 and pub_only)
    assert len(ents) > 0 and len(eps) > 0 and src_ok and key3 and pub_only
    # 새 게이트 레벨 분리: real 정상 산출은 ERROR 0(FAIL 아님)
    import gate_review
    gr = gate_review.run_review_gate("backend", rb)
    print("게이트(레벨 분리): status =", gr["status"], "| ERROR 수 =", len(gr["reasons"]))
    assert gr["status"] != "FAIL", f"real 정상 산출이 FAIL: {gr['reasons']}"
    print("[real] 검증 통과(Pydantic + 발명금지 교차검증 + 게이트 ERROR 0)")
