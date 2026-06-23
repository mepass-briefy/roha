"""
UX Agent E2E 검증.
intake -> strategy(사람 승인) -> ux 까지 돌려 계약 준수, 제약 강제, orchestrator 결합을 확인한다.
오프라인 모드(결정적). site-build.v2 워크플로(ux 노드 추가)를 사용한다. v1과 demo_strategy는 그대로 둔다.
"""
import sys, shutil, json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))

from orchestrator import Store, Orchestrator, canonical_hash
import strategy as strategy_agent
import ux as ux_agent

ROOT = str(BASE / "_run_ux")
PROJECT = 41
if Path(ROOT).exists():
    shutil.rmtree(ROOT)

WF = json.loads((BASE / "workflow" / "site-build.v2.json").read_text(encoding="utf-8"))

# 실제 에이전트를 producer로 등록(둘 다 offline llm).
PRODUCERS = {
    "strategy": strategy_agent.make_producer(),
    "ux": ux_agent.make_producer(),
}

store = Store(ROOT, PROJECT)
orc = Orchestrator(store, WF, PRODUCERS)

# intake 시드. requirements가 UX 핵심 태스크의 출처(추론 0%).
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

print("=== tick 1: strategy 실행 ===")
print("선택:", orc.tick())
print("strategy status:", store.head("strategy")["status"], "(in_review = 사람 게이트 대기)")

print("\n=== 사람 게이트: strategy 승인 ===")
orc.human_confirm("strategy")
print("strategy status:", store.head("strategy")["status"])

print("\n=== tick 2: ux 실행(deps = intake+strategy confirmed) ===")
print("선택:", orc.tick())

print("\n=== 산출된 ux body ===")
uh = store.head("ux")
uv = store.version("ux", uh["current_version"])
print(json.dumps(uv["body"], ensure_ascii=False, indent=2))

print("\n=== 검증 ===")
b = uv["body"]
req = intake_body["requirements"]
task_names = [t["task"] for t in b["primary_tasks"]]
print("primary_tasks(추론 0%, fact):", task_names)
print("  요구와 1:1 일치:", task_names == req)
print("  모두 source_requirement 보유:", all(t["source_requirement"] for t in b["primary_tasks"]))
flow_tasks_ok = all(f["task"] in task_names for f in b["user_flows"])
ia_tasks_ok = all(all(t in task_names for t in s["tasks"]) for s in b["information_architecture"])
print("user_flows(inference) 발명 task 없음:", flow_tasks_ok)
print("IA(inference) 발명 task 없음:", ia_tasks_ok)
print("ux_principles(inference, strategy 근거):", b["ux_principles"])
print("open_questions:", b["open_questions"])
print("ux head status:", uh["status"], "(in_review = 사람 게이트 대기)")
print("ux derived_from(불변 provenance):", uv["derived_from"])

print("\n=== 제약 강제 확인: No-Fabrication (source_requirement 없는 태스크) ===")
try:
    ux_agent.validate({
        "primary_tasks": [{"task": "유령 기능", "origin": "fact"}],
        "user_flows": [], "information_architecture": [],
        "ux_principles": [], "open_questions": [],
        "provenance": {"primary_tasks": "fact"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)

print("\n=== 제약 강제 확인: 새 요구 발명(primary에 없는 task를 flow가 참조) ===")
try:
    ux_agent.validate({
        "primary_tasks": [{"task": "개인 신청", "source_requirement": "개인 신청", "origin": "fact"}],
        "user_flows": [{"task": "결제 분할", "steps": ["진입"]}],
        "information_architecture": [],
        "ux_principles": [], "open_questions": [],
        "provenance": {"primary_tasks": "fact", "user_flows": "inference"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)

print("\n=== 제약 강제 확인: 핵심 요구 추론 금지(primary_tasks origin=inference) ===")
try:
    ux_agent.validate({
        "primary_tasks": [{"task": "추측 태스크", "source_requirement": "x", "origin": "inference"}],
        "user_flows": [], "information_architecture": [],
        "ux_principles": [], "open_questions": [],
        "provenance": {"primary_tasks": "fact"},
    })
    print("FAIL: 통과되면 안 됨")
except ValueError as e:
    print("정상 차단:", e)
