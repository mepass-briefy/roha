"""
Features Agent producer.

orchestrator 계약: producer(inputs: dict) -> body: dict
모델 호출은 llm(system, user) -> str 인터페이스로 분리한다.
  - real: 태스크·통제·전략을 종합하는 Claude 서브에이전트로 교체되는 자리
  - offline: 결정적. ux.primary_tasks, ux.user_flows, security.security_requirements, strategy.wow_points만 사용.

핵심 기능은 ux 태스크에서 직접(fact), 보완 기능은 strategy 와우포인트에서(inference), 보안 통제를 매핑한다.
본 에이전트는 body만 반환한다. 버전/derived_from/status는 orchestrator 책임.
"""

import json
from pathlib import Path

AGENT_NAME = "agent.features"
SYSTEM_PROMPT = Path(__file__).with_name("agent_features.md").read_text(encoding="utf-8")

CORE_ORIGINS = ("fact", "human")
ALLOWED_ORIGINS = ("fact", "human", "inference")


def build_user_prompt(intake: dict, ux: dict, security: dict, strategy: dict) -> str:
    return json.dumps({"intake": intake, "ux": ux, "security": security, "strategy": strategy},
                      ensure_ascii=False)


def validate(body: dict) -> dict:
    """합의된 제약을 코드로 강제한다. 위반 시 raise."""
    required = {"features", "open_questions", "provenance"}
    missing = required - set(body)
    if missing:
        raise ValueError(f"features body 필드 누락: {missing}")

    prov = body["provenance"]
    names = set()
    has_acceptance = False

    for f in body["features"]:
        name = f.get("feature")
        if not name:
            raise ValueError("feature 이름 누락")
        if not f.get("source"):
            raise ValueError(f"No-Fabrication 위반: source 없는 기능 '{name}'")
        origin = f.get("origin")
        if origin not in ALLOWED_ORIGINS:
            raise ValueError(f"허용되지 않은 origin '{origin}' (기능 '{name}')")
        src = f["source"]
        # 추론 층 분리: 핵심 기능은 ux:/requirement: 근거+fact|human, 보완 기능은 derived:+inference
        if origin in CORE_ORIGINS:
            if not (src.startswith("ux:") or src.startswith("requirement:")):
                raise ValueError(f"추론 층 분리 위반: 핵심 기능 '{name}'의 source는 ux:/requirement:여야 함(현재 '{src}')")
        else:  # inference
            if not src.startswith("derived:"):
                raise ValueError(f"추론 층 분리 위반: 보완 기능 '{name}'의 source는 derived:여야 함(현재 '{src}')")
        if f.get("acceptance_criteria"):
            has_acceptance = True
        # 중복 기능명 금지(혼란·발명 방지)
        if name in names:
            raise ValueError(f"중복 기능명: '{name}'")
        names.add(name)

    if body["features"] and prov.get("features") != "per_item":
        raise ValueError("provenance.features는 per_item이어야 함(기능별 origin 표기)")
    if has_acceptance and prov.get("acceptance_criteria") != "inference":
        raise ValueError("provenance.acceptance_criteria는 inference여야 함")
    if any(f.get("security_controls") for f in body["features"]) and prov.get("security_controls") != "fact":
        raise ValueError("provenance.security_controls는 fact여야 함(security 통제 참조)")

    return body


def offline_llm(system: str, user: str) -> str:
    """결정적 오프라인 모드. ux/security/strategy 입력만 사용. 발명 금지."""
    payload = json.loads(user)
    ux = payload.get("ux", {}) or {}
    security = payload.get("security", {}) or {}
    strategy = payload.get("strategy", {}) or {}

    primary_tasks = [t["task"] for t in ux.get("primary_tasks", [])]
    flows_by_task = {f["task"]: f.get("steps", []) for f in ux.get("user_flows", [])}
    wow_points = strategy.get("wow_points", [])

    # 같은 요구에서 나온 보안 통제를 task에 매핑 (ux task == requirement, control.source_requirement == requirement)
    controls_by_req = {}
    for r in security.get("security_requirements", []):
        controls_by_req.setdefault(r.get("source_requirement"), []).append(r.get("control"))

    features = []
    open_questions = []

    if not primary_tasks:
        open_questions.append("ux.primary_tasks 없음: 핵심 기능 도출 불가")

    for i, task in enumerate(primary_tasks):
        steps = flows_by_task.get(task, [])
        acceptance = [f"{s} 가능" for s in steps] if steps else [f"{task} 완료 가능"]
        controls = controls_by_req.get(task, [])
        features.append({
            "feature": task,
            "source": f"ux:{task}",
            "origin": "fact",
            "priority": "high" if i == 0 else "medium",
            "acceptance_criteria": acceptance,
            "security_controls": controls,
        })
        if not controls:
            open_questions.append(f"기능 '{task}'에 매핑된 보안 통제 없음: 검토 필요")

    # 보완 기능: 와우포인트 기반(inference)
    for w in wow_points:
        features.append({
            "feature": f"차별 기능: {w}",
            "source": "derived:strategy.wow_point",
            "origin": "inference",
            "priority": "low",
            "acceptance_criteria": [],
            "security_controls": [],
        })

    body = {
        "features": features,
        "open_questions": open_questions,
        "provenance": {
            "features": "per_item",
            "priority": "inference",
            "acceptance_criteria": "inference",
            "security_controls": "fact",
        },
    }
    return json.dumps(body, ensure_ascii=False)


def produce(inputs: dict, llm=offline_llm) -> dict:
    intake = inputs["intake"]
    ux = inputs.get("ux", {})
    security = inputs.get("security", {})
    strategy = inputs.get("strategy", {})
    raw = llm(SYSTEM_PROMPT, build_user_prompt(intake, ux, security, strategy))
    raw = raw.replace("```json", "").replace("```", "").strip()
    body = json.loads(raw)
    return validate(body)


def make_producer(llm=offline_llm):
    """orchestrator에 등록할 producer(inputs)->body 클로저. llm 주입은 클로저로 처리(구조 변경 없음)."""
    def producer(inputs):
        return produce(inputs, llm=llm)
    return producer
