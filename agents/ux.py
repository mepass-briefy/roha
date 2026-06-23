"""
UX Agent producer.

orchestrator 계약: producer(inputs: dict) -> body: dict
모델 호출은 llm(system, user) -> str 인터페이스로 분리한다.
  - real: 요구를 사용자 관점으로 구조화하는 Claude 서브에이전트로 교체되는 자리
  - offline: 결정적. intake.requirements와 strategy 입력만 사용. 발명 금지.

본 에이전트는 body만 반환한다. 버전/derived_from/status는 orchestrator 책임.
"""

import json
from pathlib import Path

AGENT_NAME = "agent.ux"
SYSTEM_PROMPT = Path(__file__).with_name("agent_ux.md").read_text(encoding="utf-8")

CORE_ORIGINS = ("fact", "human")  # 핵심 요구(primary_tasks)에 허용되는 출처


def build_user_prompt(intake: dict, strategy: dict) -> str:
    return json.dumps({"intake": intake, "strategy": strategy}, ensure_ascii=False)


def validate(body: dict) -> dict:
    """합의된 제약을 코드로 강제한다. 위반 시 raise."""
    required = {"primary_tasks", "user_flows", "information_architecture",
                "ux_principles", "open_questions", "provenance"}
    missing = required - set(body)
    if missing:
        raise ValueError(f"ux body 필드 누락: {missing}")

    prov = body["provenance"]

    # No-Fabrication + 추론 0%(핵심 요구): 모든 primary_task는 source_requirement와 fact|human origin
    task_names = set()
    for t in body["primary_tasks"]:
        if not t.get("source_requirement"):
            raise ValueError(f"No-Fabrication 위반: source_requirement 없는 태스크 '{t.get('task')}'")
        if t.get("origin") not in CORE_ORIGINS:
            raise ValueError(f"추론 층 분리 위반: 핵심 태스크 '{t.get('task')}' origin은 fact|human이어야 함")
        task_names.add(t["task"])

    # primary_tasks 자체의 provenance도 핵심 요구이므로 추론 0%
    if body["primary_tasks"] and prov.get("primary_tasks") not in CORE_ORIGINS:
        raise ValueError("provenance.primary_tasks는 fact|human이어야 함(핵심 요구 추론 0%)")

    # 보완·세부는 inference 표기 의무
    if body["user_flows"] and prov.get("user_flows") != "inference":
        raise ValueError("provenance.user_flows는 inference여야 함")
    if body["information_architecture"] and prov.get("information_architecture") != "inference":
        raise ValueError("provenance.information_architecture는 inference여야 함")
    if body["ux_principles"] and prov.get("ux_principles") != "inference":
        raise ValueError("provenance.ux_principles는 inference여야 함")

    # 내부 일관성(새 요구 발명 금지): flow/IA가 참조하는 task는 primary_tasks 안에서만
    for f in body["user_flows"]:
        if f.get("task") not in task_names:
            raise ValueError(f"발명된 task in user_flow: '{f.get('task')}' (primary_tasks에 없음)")
    for s in body["information_architecture"]:
        for t in s.get("tasks", []):
            if t not in task_names:
                raise ValueError(f"발명된 task in IA 화면 '{s.get('screen')}': '{t}' (primary_tasks에 없음)")

    return body


def offline_llm(system: str, user: str) -> str:
    """결정적 오프라인 모드. intake.requirements와 strategy만 사용. 발명 금지."""
    payload = json.loads(user)
    intake = payload["intake"]
    strategy = payload.get("strategy", {}) or {}

    requirements = intake.get("requirements", [])

    # primary_tasks: 요구에서 1:1. 추론 0%(fact).
    primary_tasks = [
        {"task": req, "source_requirement": req, "origin": "fact"}
        for req in requirements
    ]
    task_names = [t["task"] for t in primary_tasks]

    # user_flows: 각 태스크의 달성 단계(보완·세부, inference). 일반 단계만. 새 task 도입 없음.
    user_flows = [
        {"task": t, "steps": ["진입", f"{t} 수행", "확인", "완료"]}
        for t in task_names
    ]

    # information_architecture: 태스크를 화면으로 묶음(보완·세부, inference). 참조 task는 primary 안에서만.
    information_architecture = (
        [{"screen": "메인", "purpose": "핵심 태스크 진입점", "tasks": list(task_names)}]
        if task_names else []
    )

    # ux_principles: strategy의 unique_angles + wow_points에서만 도출(inference). 근거 없으면 비움.
    basis = list(strategy.get("unique_angles", [])) + list(strategy.get("wow_points", []))
    ux_principles = [f"{b}을(를) 사용자 흐름에서 우선 노출" for b in basis]

    open_questions = []
    if not requirements:
        open_questions.append("intake.requirements 없음. 핵심 태스크 도출 불가")
    if not basis:
        open_questions.append("strategy.unique_angles/wow_points 없음. UX 원칙 근거 부족")

    body = {
        "primary_tasks": primary_tasks,
        "user_flows": user_flows,
        "information_architecture": information_architecture,
        "ux_principles": ux_principles,
        "open_questions": open_questions,
        "provenance": {
            "primary_tasks": "fact",
            "user_flows": "inference",
            "information_architecture": "inference",
            "ux_principles": "inference",
        },
    }
    return json.dumps(body, ensure_ascii=False)


def produce(inputs: dict, llm=offline_llm) -> dict:
    intake = inputs["intake"]
    strategy = inputs.get("strategy", {})
    raw = llm(SYSTEM_PROMPT, build_user_prompt(intake, strategy))
    raw = raw.replace("```json", "").replace("```", "").strip()
    body = json.loads(raw)
    return validate(body)


def make_producer(llm=offline_llm):
    """orchestrator에 등록할 producer(inputs)->body 클로저. llm 주입은 클로저로 처리(구조 변경 없음)."""
    def producer(inputs):
        return produce(inputs, llm=llm)
    return producer
