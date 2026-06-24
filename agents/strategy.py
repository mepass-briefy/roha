"""
Strategy Agent producer.

orchestrator 계약: producer(inputs: dict) -> body: dict
모델 호출은 llm(system, user) -> str 인터페이스로 분리한다.
  - real: Anthropic messages API로 Claude 호출(이번 단계는 web_search 없이 모델 지식만).
  - offline: 결정적. intake가 제공한 seed_competitors만 사용. 발명 금지.

mock/real 선택은 make_producer(llm=...)로 한다. real 실패(키 없음/네트워크/API 에러)는
mock으로 조용히 폴백하지 않고 명확히 raise한다(어느 모드인지 혼동 방지).
본 에이전트는 body만 반환한다. 버전/derived_from/status는 orchestrator 책임.
"""

import json
import os
from pathlib import Path

AGENT_NAME = "agent.strategy"
SYSTEM_PROMPT = Path(__file__).with_name("agent_strategy.md").read_text(encoding="utf-8")

FIXED_AXES = ["기능", "수익모델", "온보딩", "불편지점"]

# real 모드 기본 모델. 필요 시 make_real_llm(model=...)로 교체.
REAL_MODEL_DEFAULT = "claude-sonnet-4-6"
# Anthropic server-side web_search 도구 식별자/기본 검색 횟수.
WEB_SEARCH_TOOL_TYPE = "web_search_20250305"
WEB_SEARCH_MAX_USES_DEFAULT = 5

# real 모드 추가 지시(web_search 연결: 검색으로 확인된 fact만, 환각 금지).
REAL_MODE_INSTRUCTION = (
    "\n\n## real 모드 지시(web_search 연결)\n"
    "1. web_search 도구로 실제 검색해 경쟁사·사실을 확인한다. 너의 기억만으로 회사를 단정하지 마라.\n"
    "2. No-Fabrication: 검색 결과에 없는 회사·수치·URL을 생성하지 않는다. competitors는 검색으로 확인된 실제 서비스만 넣고, "
    "source_url은 검색에서 확인한 공식 도메인을 정확히 기재한다.\n"
    "3. 검색으로 확인하지 못한 경쟁사·항목은 competitors에 넣지 말고, body의 \"open_questions\" 배열에 사유를 기록한다(검증 필요).\n"
    "4. provenance 값은 정확히 한 단어만 쓴다(설명 텍스트 금지): competitors·market_gaps=\"fact\", wow_points·options=\"inference\", unique_angles=\"human\".\n"
    "5. body에 \"open_questions\": [] 필드를 포함한다. chosen은 항상 null. unique_angles는 intake가 준 것만 사용한다.\n"
    "6. 최종 출력은 출력 스키마의 JSON 객체 하나만. 검색 과정 설명을 텍스트로 출력하지 마라."
)


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


def _extract_json(text: str) -> str:
    """text 블록 join 결과에서 JSON 객체만 추출(검색 설명 텍스트가 섞여도 안전)."""
    text = text.replace("```json", "").replace("```", "").strip()
    i, j = text.find("{"), text.rfind("}")
    return text[i:j + 1] if i != -1 and j != -1 and j > i else text


def make_real_llm(model=REAL_MODEL_DEFAULT, max_tokens=4096, max_searches=WEB_SEARCH_MAX_USES_DEFAULT):
    """real llm(system, user) -> str. Anthropic messages API + server-side web_search 도구.
    실패(SDK 미설치/키 없음/네트워크/API 에러)는 mock 폴백 없이 RuntimeError로 드러낸다."""
    def real_llm(system: str, user: str) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError("real 모드 불가: anthropic SDK 미설치 (pip install anthropic)") from e
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("real 모드 불가: ANTHROPIC_API_KEY 환경변수 없음 (mock으로 폴백하지 않음)")
        client = anthropic.Anthropic(api_key=api_key)
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system + REAL_MODE_INSTRUCTION,
                tools=[{"type": WEB_SEARCH_TOOL_TYPE, "name": "web_search", "max_uses": max_searches}],
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:
            raise RuntimeError(f"real 모드 Anthropic API 호출 실패: {type(e).__name__}: {e}") from e
        # server-side web_search는 단일 create 호출에서 처리된다. 최종 text 블록만 모은다.
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if not text:
            raise RuntimeError("real 모드: Anthropic 응답에 텍스트 없음(검색 후 최종 답변 없음)")
        return _extract_json(text)
    return real_llm


# 편의 인스턴스(기본 모델). 키/네트워크는 호출 시점에 검사된다.
real_llm = make_real_llm()


def produce(inputs: dict, llm=offline_llm) -> dict:
    intake = inputs["intake"]
    raw = llm(SYSTEM_PROMPT, build_user_prompt(intake))
    raw = raw.replace("```json", "").replace("```", "").strip()
    body = json.loads(raw)
    return validate(body)


def make_producer(llm=offline_llm):
    """orchestrator에 등록할 producer(inputs)->body 클로저. llm 주입은 클로저로 처리(구조 변경 없음).
    mock: make_producer() 또는 make_producer(offline_llm). real: make_producer(real_llm) 또는 make_producer(make_real_llm(model=...))."""
    def producer(inputs):
        return produce(inputs, llm=llm)
    return producer
