"""
discovery·wireframe 배치 분할 검증(결정적, real 무관).
fake staged llm으로 분할-병합 경로를 태워 [8] 합치기 정합·[9] 발명0(스키마)·동형을 확인한다.
"""
import sys, json
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(BASE / "agents"))
import discovery as disc
import wireframe as wf

# ---- discovery 분할 ----
def fake_disc(system, user):
    d = json.loads(user)
    reqs = d.get("requirements", [])
    body = {
        "goal_interpretation": {"inferred_dimensions": [{"dimension": "활성화", "basis": "goal"}],
                                "candidate_metrics": [{"metric": "참여수", "confidence": "low", "dimension": "활성화", "rationale": "r"}],
                                "assumptions": [{"assumption": "가정", "basis": "goal"}]},
        "requirement_normalization": [{"id": f"R-{i+1:02d}", "statement": r, "origin": "explicit"} for i, r in enumerate(reqs)],
        "proposed_requirements": ([{"id": "P-01", "statement": f"{reqs[0]} 빈틈", "category": "c",
                                    "rationale": "없으면 성립 안 함", "basis": "R-01", "origin": "proposed"}] if reqs else []),
        "open_questions": ["공통질문"],
        "target_platform": "both",
        "provenance": {"goal_interpretation": "inference", "requirement_normalization": "per_item",
                       "proposed_requirements": "inference", "target_platform": "fact"},
    }
    return json.dumps(body, ensure_ascii=False)

REQS = [f"요구{i}" for i in range(1, 23)]  # 22요구
print("=== discovery 배치 분할(22요구) ===")
body = disc.produce({"intake": {"requirements": REQS, "goal": {"statement": "g"}, "target_platform": "both"}}, llm=fake_disc)
rids = [r["id"] for r in body["requirement_normalization"]]
pids = [p["id"] for p in body["proposed_requirements"]]
print(" R- 수:", len(rids), "| 유일:", len(set(rids)) == len(rids), "| 첫·끝:", rids[0], rids[-1])
print(" P- 수:", len(pids), "| 유일:", len(set(pids)) == len(pids), "| ids:", pids)
print(" goal_interpretation dedupe:", {k: len(body["goal_interpretation"][k]) for k in disc.GI_KEYS})
print(" target_platform:", body["target_platform"], "| open_questions:", body["open_questions"])
import math
n_batches = math.ceil(22 / disc.DISC_BATCH)
b2_r_start = disc.DISC_BATCH + 1  # 2번째 배치의 R 시작 순번
assert len(rids) == 22 and len(set(rids)) == 22, "R- 22개 유일 아님"
assert len(pids) == n_batches and len(set(pids)) == n_batches, f"P- 배치당 1개={n_batches}개 유일 아님"
# basis renumber 검증: 2번째 배치 P의 basis가 R-{b2_r_start}로 치환됐는지
assert body["proposed_requirements"][1]["basis"] == f"R-{b2_r_start:02d}", f"basis 재번호 실패: {body['proposed_requirements'][1]['basis']}"
disc.validate(body)  # 스키마 동형(하류 무영향)
print(" PASS: 합치기 정합·스키마 동형·basis 추적 보존")

# ---- wireframe 분할 ----
def fake_wf(system, user):
    d = json.loads(user)
    ux = d.get("ux", {}); ds = d.get("design_system", {}); feats = d.get("features", {})
    ia = ux.get("information_architecture", [])
    palette = [c["component"] for c in ds.get("component_specs", [])]
    fidx = [f["feature"] for f in feats.get("features", [])]
    screens = [{"screen": s["screen"], "source": f"ux:{s['screen']}", "origin": "fact",
                "sections": [{"section": "영역", "components": palette[:1], "feature_refs": fidx[:1]}]} for s in ia]
    # 공통 화면을 매 배치가 함께 산출 -> 병합 dedupe로 1개만 남아야
    screens.insert(0, {"screen": "로그인", "source": "ux:로그인", "origin": "fact",
                       "sections": [{"section": "인증", "components": palette[:1], "feature_refs": fidx[:1]}]})
    body = {"design_component_palette": palette, "feature_index": fidx, "screens": screens,
            "navigation": {"pattern": "x", "items": [s["screen"] for s in screens]}, "open_questions": [],
            "provenance": {"design_component_palette": "fact", "feature_index": "fact", "screens": "per_item",
                           "sections": "inference", "navigation": "inference"}}
    return json.dumps(body, ensure_ascii=False)

print("\n=== wireframe 배치 분할(14 IA 화면 + 공통 중복) ===")
IA = [{"screen": f"화면{i}", "tasks": []} for i in range(1, 15)]
ux_in = {"information_architecture": IA}
ds_in = {"component_specs": [{"component": "card"}, {"component": "table"}]}
feat_in = {"features": [{"feature": "F1"}, {"feature": "F2"}]}
wb = wf.produce({"features": feat_in, "design_system": ds_in, "ux": ux_in, "discovery": {}}, llm=fake_wf)
names = [s["screen"] for s in wb["screens"]]
print(" 화면 수:", len(names), "| 유일:", len(set(names)) == len(names))
print(" 로그인(공통) 개수:", names.count("로그인"), "(1이어야 중복 차단)")
assert len(names) == len(set(names)), "화면명 중복(병합 dedupe 실패)"
assert names.count("로그인") == 1, "공통 화면 중복 차단 실패"
assert len([n for n in names if n.startswith("화면")]) == 14, "IA 14화면 누락"
wf.validate(wb)
print(" PASS: 공통 중복 0·14화면 보존·스키마 동형")

# ---- features 분할 ----
import features as ftr
def fake_feat(system, user):
    d = json.loads(user)
    tasks = [t["task"] for t in d.get("ux", {}).get("primary_tasks", [])]
    feats = [{"feature": t, "category": "Explicit", "source": f"ux:{t}", "origin": "fact",
              "priority": "medium", "acceptance_criteria": ["a"], "security_controls": []} for t in tasks]
    # 보완 기능을 매 배치가 함께 산출 -> 병합 dedupe로 1개만 남아야
    feats.append({"feature": "차별 기능: 공통보완", "category": "Derived", "source": "derived:strategy",
                  "origin": "inference", "priority": "low", "acceptance_criteria": [], "security_controls": []})
    return json.dumps({"features": feats, "open_questions": ["fq"],
                       "provenance": {"features": "per_item", "priority": "inference",
                                      "acceptance_criteria": "inference", "security_controls": "fact"}}, ensure_ascii=False)

print("\n=== features 배치 분할(22태스크 + 보완 중복) ===")
TASKS = [{"task": f"태스크{i}"} for i in range(1, 23)]
fb = ftr.produce({"intake": {"requirements": []}, "ux": {"primary_tasks": TASKS, "user_flows": []},
                  "security": {}, "strategy": {}, "discovery": {}}, llm=fake_feat)
fnames = [f["feature"] for f in fb["features"]]
print(" 기능 수:", len(fnames), "| 유일:", len(set(fnames)) == len(fnames))
print(" 보완(공통) 개수:", fnames.count("차별 기능: 공통보완"), "(1이어야 중복 차단)")
assert len([n for n in fnames if n.startswith("태스크")]) == 22, "22태스크 기능 누락"
assert fnames.count("차별 기능: 공통보완") == 1, "보완 기능 중복 차단 실패"
ftr.validate(fb)
print(" PASS: 보완 중복 0·22기능 보존·스키마 동형")
print("\nDONE")
