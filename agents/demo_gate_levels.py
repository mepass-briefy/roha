"""
게이트 레벨 분리 검증: 계약 위반=ERROR(FAIL, 차단) vs 품질 미달=WARN(통과).
backend·wireframe 대상. orchestrator·에이전트 산출 로직 무수정(게이트 판정만).

[8]  회귀: offline 정상 산출은 ERROR 0(FAIL 아님).
[9]  음성 4종: (a)빈 entities (b)발명 source (c)식별자 누락 (d)외부 pk 노출 -> 각각 FAIL.
[10] WARN: fields 빈약/커버리지 일부 결손 -> WARN(통과, EXIT 0).
"""
import sys, shutil, copy
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(BASE / "agents"))

import backend as backend_agent
import wireframe as wireframe_agent
import gate_review

TMP = BASE / "_run_gatelevels"
if TMP.exists():
    shutil.rmtree(TMP)

# ---- 정상(offline) 산출 만들기 ----
BE_FEATURES = {"features": [
    {"feature": "개인 신청", "origin": "fact", "security_controls": ["개인정보(PII) 보호·최소수집"], "acceptance_criteria": ["신청 가능"]},
    {"feature": "정산 확인", "origin": "fact", "security_controls": ["정산 데이터 무결성·접근통제"], "acceptance_criteria": ["정산 조회"]},
]}
BE_SECURITY = {"security_requirements": [
    {"control": "개인정보(PII) 보호·최소수집"}, {"control": "정산 데이터 무결성·접근통제"}]}
good_be = backend_agent.produce({"features": BE_FEATURES, "security": BE_SECURITY}, artifact_dir=TMP / "be")

WF_FEATURES = {"features": [{"feature": "개인 신청", "origin": "fact"}, {"feature": "정산 확인", "origin": "fact"}]}
WF_DS = {"component_specs": [{"component": "input"}, {"component": "button"}, {"component": "table"}, {"component": "card"}]}
WF_UX = {"information_architecture": [{"screen": "메인", "tasks": ["개인 신청", "정산 확인"]}]}
good_wf = wireframe_agent.produce({"features": WF_FEATURES, "design_system": WF_DS, "ux": WF_UX}, llm=wireframe_agent.offline_llm)


def gate(rt, b):
    return gate_review.run_review_gate(rt, b)


def show(label, res):
    errs = [r for r in res["reasons"]]
    print(f"  {label}: status={res['status']}")
    for e in errs:
        print(f"      ERROR: {e}")


print("=== [8] 회귀: offline 정상 산출은 ERROR 0(FAIL 아님) ===")
gbe, gwf = gate("backend", good_be), gate("wireframe", good_wf)
show("backend(offline)", gbe)
show("wireframe(offline)", gwf)
print("  backend WARN 예:", [w for w in gbe["warnings"] if w.startswith("[")][:3])
print("  wireframe WARN 예:", [w for w in gwf["warnings"] if w.startswith("[")][:3])
assert gbe["status"] != "FAIL", "정상 backend가 FAIL이면 안 됨"
assert gwf["status"] != "FAIL", "정상 wireframe가 FAIL이면 안 됨"


def has_tag(res, tag):
    return any(tag in r for r in res["reasons"])


print("\n=== [9] 음성 4종(backend) -> 각각 FAIL ===")
# (a) 빈 entities
a = copy.deepcopy(good_be); a["entities"] = []
ra = gate("backend", a); show("(a) entities=[]", ra)
assert ra["status"] == "FAIL" and has_tag(ra, "[빈 산출]")
# (b) 발명 source(형식 위반)
b = copy.deepcopy(good_be); b["entities"][0]["source"] = "ghost-no-prefix"
rb = gate("backend", b); show("(b) 발명 source", rb)
assert rb["status"] == "FAIL" and has_tag(rb, "[발명]")
# (c) 식별자 3종 누락
c = copy.deepcopy(good_be); c["entities"][0]["identifiers"].pop("public_key", None)
rc = gate("backend", c); show("(c) 식별자 누락", rc)
assert rc["status"] == "FAIL" and has_tag(rc, "[식별자 3종]")
# (d) 외부 pk 노출
d = copy.deepcopy(good_be); d["api_spec"]["endpoints"][0]["path"] = "/api/v1/applications/{id}"
rd = gate("backend", d); show("(d) 외부 pk 노출", rd)
assert rd["status"] == "FAIL" and has_tag(rd, "[외부 public_key]")

print("\n=== [9+] 음성(wireframe) -> FAIL ===")
e = copy.deepcopy(good_wf); e["screens"] = []
re_ = gate("wireframe", e); show("(e) screens=[]", re_)
assert re_["status"] == "FAIL" and has_tag(re_, "[빈 산출]")
f = copy.deepcopy(good_wf)
f["screens"][0]["sections"][0]["feature_refs"] = ["없는기능"]
rf = gate("wireframe", f); show("(f) 발명 기능참조", rf)
assert rf["status"] == "FAIL" and has_tag(rf, "[발명]")

print("\n=== [10] WARN: 품질 미달은 통과(FAIL 아님) ===")
# 빈약: offline backend는 fields=[] -> [품질] 빈약 WARN, 그러나 status WARN(통과)
qwarns = [w for w in gbe["warnings"] if "[품질]" in w or "[커버리지]" in w]
print("  backend 품질/커버리지 WARN:", qwarns[:4])
assert gbe["status"] == "WARN" and not gbe["reasons"], "빈약 산출은 WARN(통과)이어야 함"
# 커버리지 일부 결손(backend): 엔드포인트만 있고 엔티티 없는 기능 추가 -> WARN
cov = copy.deepcopy(good_be)
extra_ep = copy.deepcopy(cov["api_spec"]["endpoints"][0])
extra_ep["endpoint_id"] = "ep-x-extra"; extra_ep["feature_ref"] = "정산 확인"
cov["api_spec"]["endpoints"].append(extra_ep)
# 정산 엔티티 제거해 커버리지 결손 유발(단, settlements 엔티티가 있으면 제거)
cov["entities"] = [en for en in cov["entities"] if "settlement" not in en["name"].lower()]
rcov = gate("backend", cov); show("(cov) 일부 커버리지 결손", rcov)
print("  -> WARN:", [w for w in rcov["warnings"] if "[커버리지]" in w])
assert rcov["status"] == "WARN" and not rcov["reasons"], "일부 커버리지 결손은 WARN(통과)"

shutil.rmtree(TMP)
print("\nDONE")
