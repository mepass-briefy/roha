"""
Goal Analysis Agent producer.

orchestrator 계약: producer(inputs: dict) -> body: dict
모델 호출은 llm(system, user) -> str 인터페이스로 분리한다.
  - real: Anthropic messages API(검색 없음). 키는 .env의 ANTHROPIC_API_KEY. 실패 시 mock 폴백 없이 RuntimeError.
  - offline(mock): 결정적. Goal.statement/details만 사용.

역할은 Goal을 '확정'이 아니라 '해석·가설 제안'. 모든 산출은 provenance=inference(단정 금지). 확정은 사람(Workbench).
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

AGENT_NAME = "agent.goal_analysis"
SYSTEM_PROMPT = Path(__file__).with_name("agent_goal_analysis.md").read_text(encoding="utf-8")

REAL_MODEL_DEFAULT = "claude-sonnet-4-6"
INFERENCE_KEYS = ("inferred_dimensions", "candidate_metrics", "assumptions")

REAL_MODE_INSTRUCTION = (
    "\n\n## real 모드 지시(Goal 해석)\n"
    "Goal(statement + details)을 해석해 가설을 제안한다. 목표를 확정하지 않는다(확정은 사람).\n"
    "1. 모든 산출(inferred_dimensions, candidate_metrics, assumptions)은 추론이다. provenance 값은 정확히 \"inference\" 한 단어만 쓴다(설명 텍스트 금지).\n"
    "2. No-Fabrication: Goal에 없는 지표·차원을 fact처럼 단정하지 않는다. 불확실하면 open_questions에 남긴다.\n"
    "3. statement가 막연하면 candidate_metrics를 inference로 제안하되 단정하지 말고 confidence(low/medium)로 불확실성을 표기한다.\n"
    "4. 검색하지 않는다(목표 해석은 외부 사실이 아니라 추론).\n"
    "5. 출력은 출력 스키마의 JSON 객체 하나만(코드펜스/설명 금지). 각 dimension·metric·assumption에 basis를 단다."
)


def build_user_prompt(intake: dict) -> str:
    return json.dumps({"goal": (intake or {}).get("goal", {}), "requirements": (intake or {}).get("requirements", [])},
                      ensure_ascii=False)


def _extract_json(text: str) -> str:
    text = text.replace("```json", "").replace("```", "").strip()
    i, j = text.find("{"), text.rfind("}")
    return text[i:j + 1] if i != -1 and j != -1 and j > i else text


def validate(body: dict) -> dict:
    """합의된 제약을 코드로 강제한다. 위반 시 raise."""
    required = {"inferred_dimensions", "candidate_metrics", "assumptions", "open_questions", "provenance"}
    missing = required - set(body)
    if missing:
        raise ValueError(f"goal_analysis body 필드 누락: {missing}")

    prov = body["provenance"]
    # 추론 층 분리: 이 에이전트 산출은 모두 inference(확정 금지)
    for key in INFERENCE_KEYS:
        if body[key] and prov.get(key) != "inference":
            raise ValueError(f"goal_analysis는 해석·가설만 한다: provenance.{key}는 'inference'여야 함(단정 금지, 현재 '{prov.get(key)}')")

    # No-Fabrication: 각 항목은 구조를 갖춰야(빈 단정 방지)
    for d in body["inferred_dimensions"]:
        if not d.get("dimension"):
            raise ValueError("inferred_dimensions 항목에 dimension 누락")
    for m in body["candidate_metrics"]:
        if not m.get("metric"):
            raise ValueError("candidate_metrics 항목에 metric 누락")
    return body


def offline_llm(system: str, user: str) -> str:
    """결정적 mock. Goal.statement/details만 사용. 발명 금지. 모든 산출 inference."""
    payload = json.loads(user)
    goal = payload.get("goal", {}) or {}
    statement = (goal.get("statement") or "").strip()
    details = goal.get("details") or {}

    if not statement:
        body = {
            "inferred_dimensions": [], "candidate_metrics": [], "assumptions": [],
            "open_questions": ["Goal.statement 없음: 목표 해석 불가. 고객 언어의 목표 서술 필요."],
            "provenance": {k: "inference" for k in INFERENCE_KEYS},
        }
        return json.dumps(body, ensure_ascii=False)

    inferred_dimensions = [
        {"dimension": f"'{statement}'에서 해석된 핵심 성과 차원(확인 필요)", "basis": "goal.statement"},
    ]
    candidate_metrics = [
        {"metric": "활성 참여자 수(제안)", "dimension": inferred_dimensions[0]["dimension"],
         "rationale": "활성화 목표로 해석한 일반 가정", "confidence": "low"},
    ]
    assumptions = [
        {"assumption": "목표가 사용자 활성화/참여 중심이라고 가정", "basis": "goal.statement 해석"},
    ]
    open_questions = [
        "목표의 구체적 성공 기준(목표 수치·기간)이 statement에 없음: 확정 필요.",
    ]
    if not details:
        open_questions.append("goal.details(대상 사용자·지표·제약) 미제공: 차원·지표 해석의 불확실성 큼.")

    body = {
        "inferred_dimensions": inferred_dimensions,
        "candidate_metrics": candidate_metrics,
        "assumptions": assumptions,
        "open_questions": open_questions,
        "provenance": {k: "inference" for k in INFERENCE_KEYS},
    }
    return json.dumps(body, ensure_ascii=False)


def make_real_llm(model=REAL_MODEL_DEFAULT, max_tokens=4096):
    """real llm(system, user) -> str. Anthropic messages API(검색 없음).
    실패(SDK 미설치/키 없음/네트워크/API 에러)는 mock 폴백 없이 RuntimeError."""
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
    raw = llm(SYSTEM_PROMPT, build_user_prompt(intake))
    raw = raw.replace("```json", "").replace("```", "").strip()
    body = json.loads(raw)
    return validate(body)


def make_producer(llm=offline_llm):
    """orchestrator에 등록할 producer(inputs)->body 클로저. mock: make_producer(). real: make_producer(real_llm)."""
    def producer(inputs):
        return produce(inputs, llm=llm)
    return producer
