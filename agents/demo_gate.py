"""
Test / Review Gate 검증.
기존 에이전트 산출물에 게이트를 실제로 적용한 결과를 보여준다.
게이트는 producer가 아니라 검사기다. workflow node 아님. 산출물을 읽고 검증만 한다.
오프라인 모드(결정적). 기존 데모/워크플로/orchestrator는 수정하지 않는다.
"""
import sys, shutil, copy
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))

import strategy as strategy_agent
import ux as ux_agent
import security as security_agent
import design_system as ds_agent
import features as features_agent
import wireframe as wireframe_agent
import backend as backend_agent
import frontend as frontend_agent
import gate_test
import gate_review

ROOT = Path(str(BASE / "_run_gate"))
if ROOT.exists():
    shutil.rmtree(ROOT)
ART = ROOT / "artifacts"

# 기존 producer를 호출해 산출물 body를 만든다(게이트가 아니라 데모가 산출물을 준비).
intake = {"site_character": "풋살 소셜매치 예약",
          "requirements": ["개인 신청", "매치 예약", "정산 확인"],
          "seed_competitors": ["PLAB", "아이엠그라운드"],
          "unique_angles": ["매니저 배정 자동화", "정산 투명성"],
          "brand_tokens": {"accent": "#7C3AED", "success": "#16A34A", "font_family": "Inter, sans-serif"}}
st = strategy_agent.produce({"intake": intake})
u = ux_agent.produce({"intake": intake, "strategy": st})
se = security_agent.produce({"intake": intake})
ds = ds_agent.produce({"intake": intake, "strategy": st, "ux": u})
ft = features_agent.produce({"intake": intake, "ux": u, "security": se, "strategy": st})
wf = wireframe_agent.produce({"features": ft, "design_system": ds, "ux": u})
bk = backend_agent.produce({"features": ft, "security": se}, artifact_dir=ART)
fe = frontend_agent.produce({"wireframe": wf, "design_system": ds, "backend": bk}, artifact_dir=ART)

records = [("strategy", st), ("ux", u), ("security", se), ("design_system", ds),
           ("features", ft), ("wireframe", wf), ("backend", bk), ("frontend", fe)]

print("=== 정상 산출물에 게이트 적용 (PASS 또는 WARN) ===")
print(f"{'record':14} {'TEST':6} {'REVIEW':6}  open_questions")
for name, body in records:
    t = gate_test.run_test_gate(name, body, artifact_base=ART, demo_exit_code=0)
    r = gate_review.run_review_gate(name, body)
    print(f"{name:14} {t['status']:6} {r['status']:6}  warns={len(t['warnings'])}")
    assert t["status"] in ("PASS", "WARN"), (name, t)
    assert r["status"] in ("PASS", "WARN"), (name, r)

print("\n=== 등급 규칙 확인 ===")
# strategy: open_questions 필드 없음 -> PASS, backend: open_questions 있음 -> WARN
t_st = gate_test.run_test_gate("strategy", st, artifact_base=ART)
t_bk = gate_test.run_test_gate("backend", bk, artifact_base=ART)
print("strategy TEST:", t_st["status"], "(open_questions 없음 -> PASS 기대)")
print("backend  TEST:", t_bk["status"], "(open_questions 존재 -> WARN 기대), warns:", len(t_bk["warnings"]))

print("\n=== 계약 위반 주입 -> Review FAIL ===")
# backend endpoint에서 feature_ref 제거(Traceability 위반)
bk_bad = copy.deepcopy(bk)
bk_bad["api_spec"]["endpoints"][0]["feature_ref"] = ""
r_bad = gate_review.run_review_gate("backend", bk_bad)
print("backend(feature_ref 제거) REVIEW:", r_bad["status"])
for reason in r_bad["reasons"]:
    print("  reason:", reason)
assert r_bad["status"] == "FAIL"

# frontend endpoint_ref 발명(backend에 없는 호출) -> Review FAIL
fe_bad = copy.deepcopy(fe)
fe_bad["screens"][0]["data_calls"][0]["endpoint_ref"] = "ep-없는-호출"
r_fe_bad = gate_review.run_review_gate("frontend", fe_bad)
print("frontend(발명 endpoint_ref) REVIEW:", r_fe_bad["status"])
for reason in r_fe_bad["reasons"]:
    print("  reason:", reason)
assert r_fe_bad["status"] == "FAIL"

print("\n=== artifact 파일 누락 -> Test FAIL ===")
t_missing = gate_test.run_test_gate("frontend", fe, artifact_base=ROOT / "_does_not_exist")
print("frontend(artifact base 결손) TEST:", t_missing["status"])
for reason in t_missing["reasons"]:
    print("  reason:", reason)
assert t_missing["status"] == "FAIL"

print("\n=== demo exit code != 0 -> Test FAIL ===")
t_exit = gate_test.run_test_gate("backend", bk, artifact_base=ART, demo_exit_code=1)
print("backend(demo_exit_code=1) TEST:", t_exit["status"], "reasons:", t_exit["reasons"])
assert t_exit["status"] == "FAIL"

print("\n=== 게이트는 검사만: 새 산출물·재실행 없음 ===")
print("게이트 반환 키:", sorted(gate_test.run_test_gate("ux", u).keys()))
print("FAIL이어도 재생성 루프 없음(사유만 보고).")
print("\nDONE")
