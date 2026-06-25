"""
[1단계 검증] v12에서 discovery 산출이 strategy·ux·security·features의 inputs에 전달되는지,
그리고 받기만 했으므로 기존 산출에 회귀가 없는지(v11과 동일) 확인한다.
mock·파일 Store. orchestrator·게이트·에이전트 로직 무수정(데모는 producer를 래핑해 입력 키만 관찰).
"""
import sys, json, shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(BASE / "agents")); sys.path.insert(0, str(BASE / "db"))

from orchestrator import Store, Orchestrator, canonical_hash
import run_harness
import discovery as discovery_agent
import gate_test
import gate_review

INTAKE = {
    "site_character": "풋살 소셜매치 예약",
    "goal": {"statement": "동네 풋살 모임을 활성화하고 싶다", "details": {}},
    "requirements": ["개인 신청", "매치 예약", "정산 확인"],
    "context": "기존 풋살장 운영 업체. 주말은 차는데 평일이 빔.",
    "target_platform": "both",
    "seed_competitors": ["PLAB"], "unique_angles": ["정산 투명성"], "brand_tokens": {},
}
TARGET = ["strategy", "ux", "security", "features"]


def run(wf_name, project_pk, capture=None):
    WF = json.loads((BASE / "workflow" / wf_name).read_text(encoding="utf-8"))
    art = BASE / "_run_wiring" / f"art{project_pk}"
    root = str(BASE / "_run_wiring" / f"s{project_pk}")
    if Path(root).exists():
        shutil.rmtree(root)
    base = run_harness.build_producers(art)
    base["discovery"] = discovery_agent.make_producer(discovery_agent.offline_llm)
    if capture is not None:
        def wrap(name, fn):
            def w(inputs):
                capture[name] = list(inputs.keys())
                return fn(inputs)
            return w
        prod = {k: wrap(k, v) for k, v in base.items()}
    else:
        prod = base
    store = Store(root, project_pk)
    orc = Orchestrator(store, WF, prod)
    ver_pk = store.next_pk(); head_pk = store.next_pk()
    store.append_version({"pk": ver_pk, "type": "intake", "record_pk": head_pk, "version": 1,
                          "body": INTAKE, "body_hash": canonical_hash(INTAKE), "derived_from": [], "produced_by_run": None})
    store.save_head({"pk": head_pk, "type": "intake", "project_pk": project_pk,
                     "current_version": 1, "current_version_pk": ver_pk, "status": "confirmed"})
    gates = {}
    while True:
        picked = orc.tick()
        if picked is None:
            break
        head = store.head(picked); body = store.version(picked, head["current_version"])["body"]
        t = gate_test.run_test_gate(picked, body, artifact_base=art)
        r = gate_review.run_review_gate(picked, body)
        gates[picked] = (t["status"], r["status"])
        if t["status"] == "FAIL" or r["status"] == "FAIL":
            print("  GATE FAIL:", picked, (t["reasons"] + r["reasons"])[:2]); break
        orc.human_confirm(picked)
        if picked == "features":
            break
    bodies = {}
    for rt in TARGET + ["discovery"]:
        h = store.head(rt)
        if h:
            bodies[rt] = store.version(rt, h["current_version"])["body"]
    return bodies, gates


print("=== v12 실행: discovery 입력 전달 캡처 ===")
cap = {}
b12, g12 = run("site-build.v12.json", 91001, capture=cap)
for n in TARGET:
    keys = cap.get(n, [])
    print(f"  {n:9} inputs={keys} | discovery 전달: {'discovery' in keys}")
    assert "discovery" in keys, f"{n}가 discovery를 받지 못함"
print("  게이트:", {k: f"{t}/{r}" for k, (t, r) in g12.items()})
for n, (t, r) in g12.items():
    assert t in ("PASS", "WARN") and r in ("PASS", "WARN"), f"{n} 게이트 실패"

print("\n=== v11 실행: 회귀 비교 기준(discovery 미연결) ===")
b11, g11 = run("site-build.v11.json", 91002)
v11_keys = {}
# v11에선 strategy/security 부모에 discovery 없음 — 참고로만
print("\n=== 회귀: v11 vs v12 산출 동일(받기만 했으니 출력 불변) ===")
for n in TARGET:
    h11, h12 = canonical_hash(b11[n]), canonical_hash(b12[n])
    print(f"  {n:9}: {'동일 OK' if h11 == h12 else '다름(회귀!)'}")
    assert h11 == h12, f"{n} 회귀 발생(받기만 했는데 출력이 바뀜)"

print("\n검증 통과: discovery가 strategy·ux·security·features 입력으로 전달됨 + 기존 산출 회귀 없음.")
print("DONE")
