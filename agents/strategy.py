"""
Strategy Agent producer.

orchestrator 계약: producer(inputs: dict) -> body: dict
모델 호출은 llm(system, user) -> str 인터페이스로 분리한다.
  - real: web_search 가능한 Claude 서브에이전트로 교체되는 자리
  - offline: 결정적. intake가 제공한 seed_competitors만 사용. 발명 금지.

본 에이전트는 body만 반환한다. 버전/derived_from/status는 orchestrator 책임.
"""

import json
from pathlib import Path

AGENT_NAME = "agent.strategy"
SYSTEM_PROMPT = Path(__file__).with_name("agent_strategy.md").read_text(encoding="utf-8")

FIXED_AXES = ["기능", "수익모델", "온보딩", "불편지점"]


def build_user_prompt(intake: dict) -> str:
    return json.dumps({"intake": intake}, ensure_ascii=False)


def validate(body: dict) -> dict:
    """합의된 제약을 코드로 강제한다. 위반 시 raise."""
    required = {"competitors", "market_gaps", "unique_angles", "wow_points", "options", "chosen", "provenance"}
    missing = required - set(body)
    if missing:
        raise ValueError(f"strategy body 필드 누락: {missing}")

    # No-Fabrication: 모든 competitor는 source_url 필수
    for c in body["competitors"]:
        if not c.get("source_url"):
            raise ValueError(f"No-Fabrication 위반: source_url 없는 경쟁사 '{c.get('name')}'")
        for ax in FIXED_AXES:
            c.setdefault("axes", {}).setdefault(ax, None)

    # 추론 표기 의무
    prov = body["provenance"]
    if prov.get("competitors") != "fact":
        raise ValueError("provenance.competitors는 fact여야 함")
    if body["unique_angles"] and prov.get("unique_angles") != "human":
        raise ValueError("provenance.unique_angles는 human이어야 함")
    if body["wow_points"] and prov.get("wow_points") != "inference":
        raise ValueError("provenance.wow_points는 inference여야 함")

    # chosen은 항상 null (사람이 고름)
    if body["chosen"] is not None:
        raise ValueError("chosen은 에이전트가 채우지 않는다")

    # wow_points는 gap ∩ angle. angle 없으면 wow 없음
    if body["wow_points"] and not body["unique_angles"]:
        raise ValueError("unique_angles 없이 wow_points 생성 불가")
    return body


def offline_llm(system: str, user: str) -> str:
    """결정적 오프라인 모드. intake.seed_competitors만 사용. 발명 금지."""
    intake = json.loads(user)["intake"]
    sc = intake.get("site_character", "서비스")
    seeds = intake.get("seed_competitors", [])
    angles = intake.get("unique_angles", [])  # 사람 제공 각도(있으면)

    competitors = [
        {"name": n, "source_url": "provided_in_intake",
         "axes": {"기능": None, "수익모델": None, "온보딩": None, "불편지점": None}}
        for n in seeds
    ]
    if competitors:
        market_gaps = [f"{sc} 영역에서 경쟁사 공통 미해결로 추정되는 지점(실데이터 검증 필요)"]
        gaps_prov = "inference"
    else:
        market_gaps = ["데이터 없음. 경쟁사 미제공"]
        gaps_prov = "fact"

    wow = [f"{g} × {a}" for g in market_gaps for a in angles] if (angles and competitors) else []
    options = [
        {"label": "A", "rationale": f"{sc} 핵심 기능 집중", "tradeoffs": "차별점 약함"},
        {"label": "B", "rationale": "와우포인트 중심 차별화", "tradeoffs": "구현 비용 큼"},
    ]
    body = {
        "competitors": competitors,
        "market_gaps": market_gaps,
        "unique_angles": angles,
        "wow_points": wow,
        "options": options,
        "chosen": None,
        "provenance": {
            "competitors": "fact",
            "market_gaps": gaps_prov,
            "unique_angles": "human",
            "wow_points": "inference",
            "options": "inference",
        },
    }
    return json.dumps(body, ensure_ascii=False)


def produce(inputs: dict, llm=offline_llm) -> dict:
    intake = inputs["intake"]
    raw = llm(SYSTEM_PROMPT, build_user_prompt(intake))
    raw = raw.replace("```json", "").replace("```", "").strip()
    body = json.loads(raw)
    return validate(body)


def make_producer(llm=offline_llm):
    """orchestrator에 등록할 producer(inputs)->body 클로저. llm 주입은 클로저로 처리(구조 변경 없음)."""
    def producer(inputs):
        return produce(inputs, llm=llm)
    return producer
