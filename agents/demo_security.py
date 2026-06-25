"""
Security Agent E2E 검증.
intake -> security 까지 돌려 계약 준수, 제약 강제, orchestrator 결합을 확인한다.
오프라인 모드(결정적). site-build.v3 워크플로(security 노드)를 사용한다. v1/v2와 기존 데모는 그대로 둔다.
"""
import os, sys, shutil, json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))

from orchestrator import Store, Orchestrator, canonical_hash
import security as security_agent

ROOT = str(BASE / "_run_security")
PROJECT = 51
if Path(ROOT).exists():
    shutil.rmtree(ROOT)

WF = json.loads((BASE / "workflow" / "site-build.v3.json").read_text(encoding="utf-8"))

# 실제 Security Agent를 producer로 등록(offline llm).
PRODUCERS = {
    "security": security_agent.make_producer(),
}

store = Store(ROOT, PROJECT)
orc = Orchestrator(store, WF, PRODUCERS)

# intake 시드. requirements가 보안 통제의 출처(추론 0%).
intake_body = {
    "site_character": "풋살 소셜매치 예약",
    "requirements": ["개인 신청", "매치 예약", "정산 확인", "후기 작성"],
}
ver_pk = store.next_pk()
head = {"pk": store.next_pk(), "type": "intake", "project_pk": PROJECT,
        "current_version": 1, "current_version_pk": ver_pk, "status": "confirmed"}
store.append_version({"pk": ver_pk, "type": "intake", "record_pk": head["pk"], "version": 1,
                      "body": intake_body, "body_hash": canonical_hash(intake_body),
                      "derived_from": [], "produced_by_run": None})
store.save_head(head)

print("=== tick: orchestrator가 security 선택(deps = intake confirmed) ===")
print("선택:", orc.tick())

print("\n=== 산출된 security body ===")
sh = store.head("security")
sv = store.version("security", sh["current_version"])
print(json.dumps(sv["body"], ensure_ascii=False, indent=2))

print("\n=== 검증 ===")
b = sv["body"]
controls = [r["control"] for r in b["security_requirements"]]
print("security_requirements(추론 0%, fact):", controls)
print("  모두 source_requirement 보유:", all(r["source_requirement"] for r in b["security_requirements"]))
print("  모두 origin=fact:", all(r["origin"] == "fact" for r in b["security_requirements"]))
print("data_classification(추론 0%, fact):", [(d["data"], d["sensitivity"]) for d in b["data_classification"]])
print("  모두 source_requirement 보유:", all(d["source_requirement"] for d in b["data_classification"]))
threat_ok = all(t["mitigated_by"] in controls for t in b["threat_model"])
print("threat_model(inference) 발명 통제 참조 없음:", threat_ok)
print("open_questions(미매칭 요구 정직 표기):", b["open_questions"])
print("security head status:", sh["status"], "(in_review = 사람 게이트 대기)")
print("security derived_from(불변 provenance):", sv["derived_from"])

print("\n=== 제약 강제 확인: No-Fabrication (source_requirement 없는 통제) ===")
try:
    security_agent.validate({
        "security_requirements": [{"control": "유령 통제", "category": "x", "origin": "fact"}],
        "data_classification": [], "threat_model": [],
        "open_questions": [], "provenance": {"security_requirements": "fact"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)

print("\n=== 제약 강제 확인: 근거 없는 통제 발명(threat가 없는 control 참조) ===")
try:
    security_agent.validate({
        "security_requirements": [{"control": "인증·세션 보호", "category": "authn_session",
                                   "source_requirement": "로그인", "origin": "fact"}],
        "data_classification": [],
        "threat_model": [{"threat": "임의 위협", "mitigated_by": "존재하지 않는 통제"}],
        "open_questions": [],
        "provenance": {"security_requirements": "fact", "threat_model": "inference"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)

print("\n=== 제약 강제 확인: 핵심 의무 추론 금지(security_requirements origin=inference) ===")
try:
    security_agent.validate({
        "security_requirements": [{"control": "추측 통제", "category": "x",
                                   "source_requirement": "x", "origin": "inference"}],
        "data_classification": [], "threat_model": [],
        "open_questions": [], "provenance": {"security_requirements": "fact"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)


# ── [real] 기능별 보안 사고 검증(SECURITY_MODE=real일 때만) ──
INFLUENCER_INTAKE = {
    "site_character": "인플루언서 캠페인 관리",
    "requirements": ["인플루언서 캠페인 추적", "광고주 의뢰 계약금", "국내외 통화 정산",
                     "인플루언서 검증", "계약관리·정산 어드민", "권한별 회원가입"],
    "target_platform": "both",
}
INFLUENCER_DISCOVERY = {
    "goal_interpretation": {"inferred_dimensions": [], "candidate_metrics": [], "assumptions": []},
    "requirement_normalization": [
        {"id": "R-01", "statement": "인플루언서 캠페인 진행을 추적한다", "origin": "explicit"},
        {"id": "R-02", "statement": "광고주 의뢰에 계약금을 건다", "origin": "explicit"},
        {"id": "R-03", "statement": "국내외 인플루언서를 현지 통화로 정산한다", "origin": "explicit"},
        {"id": "R-04", "statement": "실제 활동 인플루언서인지 검증한다", "origin": "explicit"},
        {"id": "R-05", "statement": "계약 관리·정산을 하는 어드민이 있다", "origin": "explicit"},
        {"id": "R-06", "statement": "광고주·인플루언서가 권한별로 회원가입한다", "origin": "explicit"},
    ],
    "proposed_requirements": [
        {"id": "P-01", "statement": "다통화 정산 환율 기준·기록·감사 로그", "category": "data-integrity",
         "rationale": "환율 기준·이력 없으면 정산 분쟁", "basis": "R-03", "origin": "proposed"},
    ],
    "open_questions": [], "target_platform": "both",
    "provenance": {"goal_interpretation": "inference", "requirement_normalization": "per_item",
                   "proposed_requirements": "inference", "target_platform": "fact"},
}

if os.environ.get("SECURITY_MODE") == "real":
    print("\n=== [real] 기능별 보안 사고(인플루언서) ===")
    rb = security_agent.produce({"intake": INFLUENCER_INTAKE, "discovery": INFLUENCER_DISCOVERY},
                                llm=security_agent.real_llm)
    reqs = rb["security_requirements"]
    print(f"security_requirements {len(reqs)}건:")
    for r in reqs:
        print(f"  control: {r['control']}  | src: {r.get('source_requirement')}")
    def tied(r, *kw):
        return any(k in str(r.get("source_requirement", "")) for k in kw)
    admin = [r["control"] for r in reqs if tied(r, "어드민", "관리", "R-05")]
    settle = [r["control"] for r in reqs if tied(r, "정산", "통화", "R-03")]
    print("어드민(R-05) 통제:", admin)
    print("정산(R-03) 통제:", settle)
    print("어드민 통제 ∩ 정산 통제 겹침:", (set(admin) & set(settle)) or "없음(기능별 다름 = 사고 성공)")
    print("모든 통제 source_requirement 보유:", all(r.get("source_requirement") for r in reqs))
    print(f"통제 다양성: 고유 {len(set(r['control'] for r in reqs))} / 전체 {len(reqs)} (전부 동일이면 고정 체크리스트)")
    assert all(r.get("source_requirement") for r in reqs), "source_requirement 누락"
    print("[real] 검증 통과(validate 포함)")
