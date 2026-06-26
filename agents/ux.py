"""
UX Agent producer.

orchestrator 계약: producer(inputs: dict) -> body: dict
모델 호출은 llm(system, user) -> str 인터페이스로 분리한다.
  - real: 요구를 사용자 관점으로 구조화하는 Claude 서브에이전트로 교체되는 자리
  - offline: 결정적. intake.requirements와 strategy 입력만 사용. 발명 금지.

본 에이전트는 body만 반환한다. 버전/derived_from/status는 orchestrator 책임.
"""

import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

AGENT_NAME = "agent.ux"
SYSTEM_PROMPT = Path(__file__).with_name("agent_ux.md").read_text(encoding="utf-8")

CORE_ORIGINS = ("fact", "human")  # 핵심 요구(primary_tasks)에 허용되는 출처
REAL_MODEL_DEFAULT = "claude-sonnet-4-6"

# real 모드 지시: discovery 기반 사용자 관점 구조화(기능별 사고). 검색 없음(추론).
REAL_MODE_INSTRUCTION = (
    "\n\n## real 모드 지시(discovery 기반 사용자 관점 구조화 — 기능별 사고)\n"
    "1. 입력의 discovery.requirement_normalization(정리된 R-)을 기반으로 primary_tasks를 만든다. "
    "intake.requirements 원문을 1:1 복사하지 말 것 — discovery가 정리·해석한 R-를 출발점으로 '사용자가 이 요구를 어떻게 수행하는가' 관점의 태스크로 구조화한다.\n"
    "2. 기능별 사고: 그 기능이 사용자에게 완결되려면 필요한 화면·흐름(user_flows·information_architecture)을 그 기능의 성격에서 도출한다. "
    "모든 태스크에 같은 단계(진입->수행->확인->완료)를 붙이는 고정 템플릿 금지 — 기능마다 흐름이 다르다(예: 예약은 가용성 확인·확정·취소 흐름, 정산은 내역 확인·검증·이의 흐름).\n"
    "3. discovery.goal_interpretation(목표 차원·후보 지표)을 참고해 어떤 태스크·흐름이 목표 달성에 핵심인지 판단한다. "
    "discovery.proposed_requirements(상용 제안)는 흐름·원칙에 녹일 수 있으면 user_flows/ux_principles로 반영한다(단, primary_tasks는 고객이 말한 요구 기반).\n"
    "4. No-Fabrication: 각 primary_task는 source_requirement(어느 R-에서 왔는지, R-id 또는 요구 원문) 필수. discovery 요구에 근거 없는 태스크 생성 금지. "
    "origin은 \"fact\"(요구 원문 출처) 또는 \"human\".\n"
    "5. 내부 일관성: user_flows.task와 information_architecture.tasks는 primary_tasks의 task 이름만 참조(새 task 발명 금지).\n"
    "6. provenance: primary_tasks=\"fact\"(또는 human), user_flows·information_architecture·ux_principles=\"inference\". body에 \"open_questions\": [] 포함. "
    "출력은 출력 스키마의 JSON 객체 하나만(설명 텍스트·코드펜스 금지)."
)


def build_user_prompt(intake: dict, strategy: dict, discovery: dict = None) -> str:
    disc = {k: (discovery or {}).get(k) for k in
            ("goal_interpretation", "requirement_normalization", "proposed_requirements")}
    return json.dumps({"intake": intake, "strategy": strategy, "discovery": disc}, ensure_ascii=False)


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


def _extract_json(text: str) -> str:
    text = text.replace("```json", "").replace("```", "").strip()
    i, j = text.find("{"), text.rfind("}")
    return text[i:j + 1] if i != -1 and j != -1 and j > i else text


def make_real_llm(model=REAL_MODEL_DEFAULT, max_tokens=16000):
    """real llm(system, user) -> str. Anthropic messages API(검색 없음, 추론).
    실패(SDK 미설치/키 없음/네트워크/API 에러)는 RuntimeError — produce에서 offline 폴백."""
    def real_llm(system: str, user: str) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError("real 모드 불가: anthropic SDK 미설치") from e
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("real 모드 불가: ANTHROPIC_API_KEY 없음")
        client = anthropic.Anthropic(api_key=api_key)
        try:
            resp = client.messages.create(
                model=model, max_tokens=max_tokens,
                system=system + REAL_MODE_INSTRUCTION,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:
            raise RuntimeError(f"real 모드 Anthropic API 호출 실패: {type(e).__name__}: {e}") from e
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if not text:
            raise RuntimeError("real 모드: Anthropic 응답에 텍스트 없음")
        return _extract_json(text)
    return real_llm


real_llm = make_real_llm()


def produce(inputs: dict, llm=offline_llm) -> dict:
    intake = inputs["intake"]
    strategy = inputs.get("strategy", {})
    discovery = inputs.get("discovery", {})  # v12: discovery 입력(real 프롬프트가 사용자 태스크 구조화에 사용)
    up = build_user_prompt(intake, strategy, discovery)
    try:
        raw = llm(SYSTEM_PROMPT, up)
    except RuntimeError:
        raw = offline_llm(SYSTEM_PROMPT, up)  # real 실패 -> offline 폴백
    raw = raw.replace("```json", "").replace("```", "").strip()
    body = json.loads(raw)
    return validate(body)


def make_producer(llm=offline_llm):
    """orchestrator에 등록할 producer(inputs)->body 클로저. mock: make_producer(). real: make_producer(real_llm)."""
    def producer(inputs):
        return produce(inputs, llm=llm)
    return producer
