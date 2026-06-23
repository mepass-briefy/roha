"""
Strategy Agent E2E 검증.
intake를 시드하고 실제 Strategy Agent producer로 strategy를 산출한다.
오프라인 모드(결정적). 검증 포인트: 계약 준수, 제약 강제, orchestrator 결합.
"""
import sys, shutil, json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))

from orchestrator import Store, Orchestrator, canonical_hash
import strategy as strategy_agent

ROOT = str(BASE / "_run_strategy")
PROJECT = 31
if Path(ROOT).exists():
    shutil.rmtree(ROOT)

WF = json.loads((BASE / "workflow" / "site-build.v1.json").read_text())

# 실제 Strategy Agent를 producer로 등록. policy는 아직 mock.
PRODUCERS = {
    "strategy": strategy_agent.make_producer(),       # 실제 에이전트(offline llm)
    "policy": lambda inputs: {"service_rules": ["placeholder"]},  # 다음 우선순위
}

store = Store(ROOT, PROJECT)
orc = Orchestrator(store, WF, PRODUCERS)

# intake 시드. unique_angles는 사람 제공 각도(있어야 wow_points 생성).
intake_body = {
    "site_character": "풋살 소셜매치 예약",
    "requirements": ["개인 신청"],
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

print("=== tick: orchestrator가 strategy 선택 ===")
picked = orc.tick()
print("선택:", picked)

print("\n=== 산출된 strategy body ===")
sv = store.version("strategy", store.head("strategy")["current_version"])
print(json.dumps(sv["body"], ensure_ascii=False, indent=2))

print("\n=== 검증 ===")
b = sv["body"]
print("competitors 수:", len(b["competitors"]), "(모두 source_url 보유:",
      all(c["source_url"] for c in b["competitors"]), ")")
print("unique_angles(human):", b["unique_angles"])
print("wow_points(inference, gap × angle):", b["wow_points"])
print("chosen:", b["chosen"], "(사람이 고를 자리)")
print("strategy head status:", store.head("strategy")["status"], "(in_review = 사람 게이트 대기)")

# 제약 위반 케이스: source_url 없는 경쟁사
print("\n=== 제약 강제 확인: No-Fabrication ===")
try:
    strategy_agent.validate({"competitors": [{"name": "X"}], "market_gaps": [], "unique_angles": [],
                             "wow_points": [], "options": [], "chosen": None,
                             "provenance": {"competitors": "fact"}})
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)
