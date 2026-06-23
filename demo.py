"""
검증 데모. 우선순위 1~3을 파일 SSOT 위에서 실제 실행한다.

mock producer 설계:
  strategy: intake에서 생성
  policy: strategy의 'positioning'만 읽는다. (competitors는 안 읽음)
          -> strategy의 competitors만 바뀌면 policy 결과는 동일 -> No Impact 유도
"""
import sys, shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from orchestrator import Store, Orchestrator, canonical_hash

ROOT = str(BASE / "_run")
PROJECT = 31

# 깨끗한 상태로 시작
if Path(ROOT).exists():
    shutil.rmtree(ROOT)

import json
WF = json.loads((BASE / "workflow" / "site-build.v1.json").read_text())


# ---- mock producers (실제 에이전트가 들어갈 자리) ----
def produce_strategy(inputs):
    intake = inputs["intake"]
    return {
        "positioning": f"{intake['site_character']} 차별화 포지셔닝",
        "competitors": intake.get("seed_competitors", ["A", "B"]),
    }

def produce_policy(inputs):
    strategy = inputs["strategy"]
    # positioning만 읽는다. competitors는 의도적으로 무시.
    return {"service_rules": [f"{strategy['positioning']} 기반 정책"]}

PRODUCERS = {"strategy": produce_strategy, "policy": produce_policy}


def line(t): print("\n" + "=" * 8 + " " + t + " " + "=" * 8)
def snap(o): 
    for k, v in o.status_snapshot().items():
        print(f"  {k:10} state={v['state']:12} status={v['status']} v{v['version']}")


store = Store(ROOT, PROJECT)
orc = Orchestrator(store, WF, PRODUCERS)

# intake는 사람이 입력하는 노드. confirmed로 시드한다.
line("SEED intake (human)")
ver_pk = store.next_pk()
intake_body = {"site_character": "풋살 소셜매치 예약", "requirements": ["개인 신청"], "seed_competitors": ["PLAB", "아이엠그라운드"]}
head = {"pk": store.next_pk(), "type": "intake", "project_pk": PROJECT,
        "current_version": 1, "current_version_pk": ver_pk, "status": "confirmed"}
store.append_version({"pk": ver_pk, "type": "intake", "record_pk": head["pk"], "version": 1,
                      "body": intake_body, "body_hash": canonical_hash(intake_body),
                      "derived_from": [], "produced_by_run": None})
store.save_head(head)
store.emit("record_version_created", "record", head["pk"], {"version": 1}, record_pk=head["pk"])
store.emit("record_state_changed", "record", head["pk"], {"from": "draft", "to": "confirmed", "trigger": "human_seed"}, actor="human", record_pk=head["pk"])
snap(orc)

# ---- 우선순위 1: 오케스트레이터가 status 읽고 다음 노드를 고른다 ----
line("[P1] tick -> 다음 노드 선택")
picked = orc.tick()
print(f"  오케스트레이터가 고른 노드: {picked}")
snap(orc)

# ---- 우선순위 2: 사람 게이트 ----
line("[P2] human confirm strategy")
orc.human_confirm("strategy")
snap(orc)

line("[P1] tick -> policy 선택")
picked = orc.tick()
print(f"  오케스트레이터가 고른 노드: {picked}")
line("[P2] human confirm policy")
orc.human_confirm("policy")
snap(orc)
print("  => intake/strategy/policy 모두 confirmed. 파이프라인 1차 완료")

# ---- 우선순위 3: 재실행 + No Impact ----
line("[P3] strategy 재실행 (competitors만 변경 -> policy 무영향 유도)")
# 외부 변화 시뮬레이션: intake의 seed_competitors를 바꾼 새 intake 버전이 아니라,
# strategy producer가 다른 competitors를 내도록 입력을 바꿔 재생성한다.
PRODUCERS["strategy"] = lambda inputs: {
    "positioning": f"{inputs['intake']['site_character']} 차별화 포지셔닝",  # 동일
    "competitors": ["PLAB", "아이엠그라운드", "신규경쟁사"],                  # 변경
}
res = orc.run_node("strategy")
print(f"  strategy 재실행 결과 changed={res['changed']} -> v{res['version']} (in_review 예상)")
snap(orc)

line("[P2] human confirm strategy (v2) -> 전파 발생")
orc.human_confirm("strategy")
print("  strategy confirmed v2. policy는 strategy@v1에 검증돼 있어 stale 전파 + auto_rerun 예상")
snap(orc)

line("결과 확인")
pol = store.head("policy")
print(f"  policy status={pol['status']} version={pol['current_version']}")
print("  policy producer는 positioning만 읽으므로 competitors 변경은 무영향 -> No Impact 기대")

# ---- 이벤트 로그 출력 ----
line("EVENT LOG (events.jsonl)")
for ev in store.events():
    pl = ev["payload"]
    extra = ""
    if ev["event_type"] == "rerun_no_impact":
        extra = " <-- 상위 변경, 하위 무영향 사실을 기록"
    print(f"  #{ev['pk']} {ev['event_type']:22} subj={ev['subject_type']}:{ev['subject_pk']} {json.dumps(pl, ensure_ascii=False)[:70]}{extra}")
