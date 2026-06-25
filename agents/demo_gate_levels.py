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
import features as features_agent
import design_system as ds_agent
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

print("\n=== features 게이트 레벨(311f7e7 틀 동일) ===")
FT_INTAKE = {"site_character": "x", "requirements": ["개인 신청"]}
FT_UX = {"primary_tasks": [{"task": "개인 신청"}], "user_flows": [{"task": "개인 신청", "steps": ["진입", "수행"]}]}
FT_STRATEGY = {"wow_points": ["정산 투명성"]}
FT_SECURITY = {"security_requirements": []}
good_ft = features_agent.produce({"intake": FT_INTAKE, "ux": FT_UX, "security": FT_SECURITY, "strategy": FT_STRATEGY},
                                 llm=features_agent.offline_llm)

print("\n--- [7/8] 회귀: offline 정상 features는 ERROR 0 ---")
gft = gate("features", good_ft); show("features(offline)", gft)
print("  WARN 예:", [w for w in gft["warnings"] if w.startswith("[")][:3])
assert gft["status"] != "FAIL", "정상 features가 FAIL이면 안 됨"

print("\n--- [5] 음성 2종(features) -> 각각 FAIL ---")
# (a) 빈 features
fa = copy.deepcopy(good_ft); fa["features"] = []
rfa = gate("features", fa); show("(a) features=[]", rfa)
assert rfa["status"] == "FAIL" and has_tag(rfa, "[빈 산출]")
# (b) 발명 source(discovery:/strategy: 같은 미정의 prefix는 features 계약에 없음 -> 발명)
fb = copy.deepcopy(good_ft); fb["features"][0]["source"] = "discovery:goal"
rfb = gate("features", fb); show("(b) 발명 source", rfb)
assert rfb["status"] == "FAIL" and has_tag(rfb, "[발명]")

print("\n--- [6] WARN: 빈약(수용기준 없음)은 통과 ---")
fc = copy.deepcopy(good_ft)
for f in fc["features"]:
    f["source"] = "ux:개인 신청" if f["category"] == "Explicit" else "derived:x"
    f["acceptance_criteria"] = []  # 수용 기준 비움 -> 빈약 WARN
rfc = gate("features", fc); show("(c) 수용기준 빈약", rfc)
print("  -> WARN:", [w for w in rfc["warnings"] if "[품질]" in w][:3])
assert rfc["status"] == "WARN" and not rfc["reasons"], "빈약 features는 WARN(통과)이어야 함"

print("\n=== design_system 게이트 레벨(311f7e7 틀 동일) ===")
good_ds = ds_agent.produce({"intake": {"references": [
    {"reference_id": "roha", "type": "token", "value": {"color.primary": "#3F51B5"}, "source": "brand"}]},
    "strategy": {}, "ux": {}})
print("\n--- [6/7/8] 회귀: 정상 design_system은 ERROR 0 ---")
gds = gate("design_system", good_ds); show("design_system(인디고)", gds)
print("  component 13종:", len(good_ds["component_specs"]), "| WARN 예:", [w for w in gds["warnings"] if w.startswith("[")][:2])
assert gds["status"] != "FAIL", "정상 design_system이 FAIL이면 안 됨"
assert len(good_ds["component_specs"]) == 13, "컴포넌트 13종이어야 함"

print("\n--- [7] 음성 2종(design_system) -> 각각 FAIL ---")
# (a) 빈 component
da = copy.deepcopy(good_ds); da["component_specs"] = []
rda = gate("design_system", da); show("(a) component_specs=[]", rda)
assert rda["status"] == "FAIL" and has_tag(rda, "[빈 산출]")
# (b) 하드코딩 색(토큰 대신 hex)
db = copy.deepcopy(good_ds)
db["component_specs"][0]["states"]["enabled"]["bg"] = "#FF0000"
rdb = gate("design_system", db); show("(b) 하드코딩 색", rdb)
assert rdb["status"] == "FAIL" and has_tag(rdb, "[하드코딩 색]")

print("\n--- [6] 색 역할 토큰 참조 확인(토글->checked, 탭->tab, 사이드바->menu-sel) ---")
cmap = {c["component"]: c for c in good_ds["component_specs"]}
tog = cmap["toggle"]["states"]["on"]["bg"]; tab = cmap["tab"]["states"]["active"]
side = cmap["sidebar"]["states"]["nav-active"]["bg"]
print("  toggle.on.bg =", tog, "| tab.active =", tab, "| sidebar.nav-active.bg =", side)
assert tog == "color.light.checked", "토글은 checked 참조"
assert tab["bg"] == "color.light.tab-bg" and tab["fg"] == "color.light.tab-fg", "탭은 tab-bg/tab-fg 참조"
assert side == "color.light.menu-sel", "사이드바 활성메뉴는 menu-sel 참조"
print("  역할 토큰 값(인디고): checked =", good_ds["foundation"]["color"]["light"]["checked"],
      "| active =", good_ds["foundation"]["color"]["light"]["active"])

print("\n=== frontend 게이트 레벨(311f7e7 틀 동일, 멤버십=body 인덱스) ===")
def fe_screen(**over):
    s = {"screen_ref": "메인", "origin": "fact",
         "components": [{"component_ref": "card", "section": "s"}],
         "data_calls": [{"endpoint_ref": "ep-applications-list", "method": "GET",
                         "path_params": ["public_key"], "outcome_mapping": [{"code": "OK", "ui_hint": "x"}]}],
         "states": None, "uses_tokens": ["color-accent"], "navigation": None}
    s.update(over)
    return s

def fe_body(**over):
    b = {"screen_index": ["메인"], "endpoint_index": ["ep-applications-list"],
         "outcome_code_index": ["OK", "VALIDATION_ERROR"], "component_palette": ["card", "button"],
         "token_index": ["color-accent", "r-md"], "screens": [fe_screen()],
         "artifact_refs": [], "explicit_not_implemented": [], "provenance": {"screens": "per_item"}}
    b.update(over)
    return b

good_fe = fe_body()
print("\n--- [9] 회귀: 정상 frontend는 ERROR 0 ---")
gfe = gate("frontend", good_fe); show("frontend(정상)", gfe)
assert gfe["status"] != "FAIL"

print("\n--- [8] 음성 3종(frontend) -> 각각 FAIL ---")
# (a) 빈 산출(구현할 화면 있는데 screens=[])
fea = fe_body(screens=[]); rfea = gate("frontend", fea); show("(a) screens=[]", rfea)
assert rfea["status"] == "FAIL" and has_tag(rfea, "[빈 산출]")
# (b) 발명(멤버십 위반: palette 밖 component)
feb = fe_body(screens=[fe_screen(components=[{"component_ref": "carousel", "section": "s"}])])
rfeb = gate("frontend", feb); show("(b) 발명 component_ref", rfeb)
assert rfeb["status"] == "FAIL" and has_tag(rfeb, "[발명]")
# (c) 하드코딩 색(uses_tokens에 hex)
fec = fe_body(screens=[fe_screen(uses_tokens=["#FF0000"])])
rfec = gate("frontend", fec); show("(c) 하드코딩 색", rfec)
assert rfec["status"] == "FAIL" and has_tag(rfec, "[하드코딩 색]")

print("\n--- [8] WARN: 빈약/일부 커버리지 -> 통과 ---")
# 빈약: 컴포넌트·데이터콜 없는 화면
few = fe_body(screen_index=["메인", "빈화면"],
              screens=[fe_screen(), {"screen_ref": "빈화면", "origin": "fact", "components": [],
                                     "data_calls": [], "states": None, "uses_tokens": [], "navigation": None}])
rfew = gate("frontend", few); show("(w1) 빈약 화면", rfew)
print("  -> WARN:", [w for w in rfew["warnings"] if "[품질]" in w])
assert rfew["status"] == "WARN" and not rfew["reasons"]
# 커버리지: wireframe 화면 일부 미구현
fecov = fe_body(screen_index=["메인", "미구현화면"], screens=[fe_screen()])
rfecov = gate("frontend", fecov); show("(w2) 일부 커버리지 결손", rfecov)
print("  -> WARN:", [w for w in rfecov["warnings"] if "[커버리지]" in w])
assert rfecov["status"] == "WARN" and not rfecov["reasons"]

print("\n=== mobile 게이트 레벨(frontend와 동일 틀, 멤버십=body 인덱스) ===")
def mb_screen(**over):
    s = {"screen_ref": "메인", "origin": "fact",
         "components": [{"component_ref": "card", "section": "s"}],
         "data_calls": [{"endpoint_ref": "ep-applications-list", "method": "GET",
                         "path_params": ["public_key"], "outcome_mapping": [{"code": "OK", "ui_hint": "x"}]}],
         "states": None, "uses_tokens": ["color-accent"], "navigation": None,
         "touch_target": None, "dark_mode": None, "safe_area": None}
    s.update(over)
    return s

def mb_body(**over):
    b = {"platform": "mobile", "screen_index": ["메인"], "endpoint_index": ["ep-applications-list"],
         "outcome_code_index": ["OK", "VALIDATION_ERROR"], "component_palette": ["card", "button"],
         "token_index": ["color-accent", "r-md"], "screens": [mb_screen()],
         "artifact_refs": [], "explicit_not_implemented": [], "provenance": {"screens": "per_item"}}
    b.update(over)
    return b

good_mb = mb_body()
print("\n--- [10] 회귀: 정상 mobile은 ERROR 0 ---")
gmb = gate("mobile", good_mb); show("mobile(정상)", gmb)
assert gmb["status"] != "FAIL"

print("\n--- [8] 음성 3종(mobile) -> 각각 FAIL ---")
# (a) 빈 산출(구현할 화면 있는데 screens=[])
mba = mb_body(screens=[]); rmba = gate("mobile", mba); show("(a) screens=[]", rmba)
assert rmba["status"] == "FAIL" and has_tag(rmba, "[빈 산출]")
# (b) 발명(멤버십 위반: palette 밖 component)
mbb = mb_body(screens=[mb_screen(components=[{"component_ref": "carousel", "section": "s"}])])
rmbb = gate("mobile", mbb); show("(b) 발명 component_ref", rmbb)
assert rmbb["status"] == "FAIL" and has_tag(rmbb, "[발명]")
# (c) 하드코딩 색(uses_tokens에 hex)
mbc = mb_body(screens=[mb_screen(uses_tokens=["#FF0000"])])
rmbc = gate("mobile", mbc); show("(c) 하드코딩 색", rmbc)
assert rmbc["status"] == "FAIL" and has_tag(rmbc, "[하드코딩 색]")

print("\n--- [8] WARN: 빈약/일부 커버리지 -> 통과 ---")
mbw = mb_body(screen_index=["메인", "빈화면"],
              screens=[mb_screen(), {"screen_ref": "빈화면", "origin": "fact", "components": [],
                                     "data_calls": [], "states": None, "uses_tokens": [], "navigation": None,
                                     "touch_target": None, "dark_mode": None, "safe_area": None}])
rmbw = gate("mobile", mbw); show("(w1) 빈약 화면", rmbw)
print("  -> WARN:", [w for w in rmbw["warnings"] if "[품질]" in w])
assert rmbw["status"] == "WARN" and not rmbw["reasons"]
mbcov = mb_body(screen_index=["메인", "미구현화면"], screens=[mb_screen()])
rmbcov = gate("mobile", mbcov); show("(w2) 일부 커버리지 결손", rmbcov)
print("  -> WARN:", [w for w in rmbcov["warnings"] if "[커버리지]" in w])
assert rmbcov["status"] == "WARN" and not rmbcov["reasons"]

shutil.rmtree(TMP)
print("\nDONE")
