"""
Discovery Agent producer (goal_analysis 확장·개명).

orchestrator 계약: producer(inputs: dict) -> body: dict
모델 호출은 llm(system, user) -> str 인터페이스로 분리한다.
  - real: Anthropic messages API(검색 없음). 키는 .env의 ANTHROPIC_API_KEY. 실패 시 mock 폴백 없이 RuntimeError.
  - offline(mock): 결정적. Goal.statement/details와 requirements만 사용.

역할 = 고객 언어 -> 시스템 언어 번역(왜곡 없는 이해). 수행 3가지:
  goal_interpretation(목표 해석, 전부 inference) / requirement_normalization(요구->IT 리스트, 항목별 origin) / open_questions.
금지: 새 요구 생성·기능 제안·사업 판단. 고객 원문에 근거 없는 항목 출력 금지.
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

AGENT_NAME = "agent.discovery"
SYSTEM_PROMPT = Path(__file__).with_name("agent_discovery.md").read_text(encoding="utf-8")

REAL_MODEL_DEFAULT = "claude-sonnet-4-6"
GI_KEYS = ("inferred_dimensions", "candidate_metrics", "assumptions")
REQ_ORIGINS = ("explicit", "context-inferred")
PROPOSED_ORIGIN = "proposed"   # 제안 요구(상용 준비). 충실 정규화(R-)와 분리된 별도 추론 층.

REAL_MODE_INSTRUCTION = (
    "\n\n## real 모드 지시(Discovery = 고객 언어 -> 시스템 언어 번역)\n"
    "역할은 고객의 말을 왜곡 없이 이해·번역하는 것. 좋은 아이디어를 더하지 않는다.\n"
    "A. goal_interpretation: Goal.statement 해석(inferred_dimensions/candidate_metrics/assumptions). 전부 추론. "
    "provenance.goal_interpretation 값은 정확히 \"inference\" 한 단어.\n"
    "B. requirement_normalization: 고객의 막연한 요구를 구조화된 IT 요구 리스트로 정리. 각 항목 {id:\"R-01\".., statement, origin}. "
    "origin은 \"explicit\"(고객이 직접 말함) 또는 \"context-inferred\"(맥락 추론). provenance.requirement_normalization=\"per_item\".\n"
    "금지:\n"
    "1. 새 요구사항 생성 금지. 고객이 말한 것만 정리. 고객 말에 없는 요구(예: 결제·리뷰 등)를 만들면 fabrication.\n"
    "2. 기능 제안 금지(어떻게 만들지는 Features). 요구의 정리·해석까지만.\n"
    "3. 사업 판단 금지(채택·우선순위는 open_questions).\n"
    "4. 애매하면 requirement 항목으로 만들지 말고 open_questions로.\n"
    "B-2. proposed_requirements: 정규화한 각 R- 요구를 하나씩 보고, '이 기능이 실제 상용 제품으로 빈틈없이 완결되려면 충족돼야 하는데 "
    "고객이 말하지 않은 것'을 그 기능의 성격에서 추론한다(requirement_normalization과 별도 층, R-을 오염시키지 않는다). "
    "정해진 목록을 붙이지 말 것. 어떤 요구든 똑같은 항목(RBAC·접근통제·감사로그 같은 보안 세트)이 반복되면 그것은 사고가 아니라 목록 부착이며 거부된다. "
    "각 R-가 '무엇을 하는 기능인지'에서 출발해 그 기능 특유의 빠진 요건을 도출한다 — 정산이면 정산 특유, 어드민이면 어드민 특유로 서로 달라야 한다. "
    "맥락 반영: 같은 도메인도 요구·Context의 구체성에 따라 다르게 사고한다. "
    "예) '국내외 정산'(통화가 여럿)이면 환율·통화 변환·정산 시점 환율 기준처럼 그 요구의 구체성에서만 나오는 요건을 도출한다(목록이 아니라 그 요구가 무엇인지 생각한 결과). "
    "각 항목 {id:\"P-01\".., statement, category, rationale, basis, origin:\"proposed\"}. "
    "제약(No-Fabrication 유지): "
    "(1) basis 필수 — 어느 R-(또는 Context 구절)를 보고 사고했는지 명시. 근거 없는 제안은 fabrication이므로 금지. "
    "(2) rationale 필수 — 그것이 없으면 그 기능이 왜 상용으로 성립하지 않는지 실제 내용으로 설명. 설명 못 하면 그 제안은 제외. "
    "(3) 보수성 — '없으면 그 기능이 성립 안 하는' 필수에 가까운 것만. '있으면 좋은' 부가나 과한 상상(블록체인·AI 추천·게이미피케이션 등 그 기능 완결과 무관한 것)은 금지. "
    "(4) origin=\"proposed\", 전부 사람 확정 전 미확정. provenance.proposed_requirements=\"inference\".\n"
    "C. open_questions: 목표·요구 양쪽의 불확실성.\n"
    "D. Context 활용: intake.context(고객·프로덕트 맥락)가 있으면 Goal과 함께 해석한다. Context에서 끌어낸 것은 inference로 표기하고(단정 금지), "
    "Context 기반으로 정리한 요구는 origin=\"context-inferred\"로 둔다(고객이 직접 말한 explicit과 구분). "
    "Context를 근거로도 새 기능을 발명하지 않는다(맥락 추론은 '이 요구가 이 맥락에서 이렇게 해석된다'까지지, 새 요구 생성이 아니다). Context 없으면 '고객이 누구인지'를 open_question으로.\n"
    "E. target_platform: 입력값(fact)이다. 추론하지 말고 body.target_platform에 받은 값(web|mobile|both)을 그대로 싣는다. 없으면 \"미정\". provenance.target_platform=\"fact\".\n"
    "성공 기준은 좋은 아이디어가 아니라 왜곡 없는 이해. 원문 근거 없는 항목 출력 금지. 검색 안 함. 출력은 body JSON만(코드펜스/설명 금지)."
)


TARGET_PLATFORMS = ("web", "mobile", "both", "미정")


def build_user_prompt(intake: dict) -> str:
    intake = intake or {}
    return json.dumps({
        "goal": intake.get("goal", {}),
        "requirements": intake.get("requirements", []),
        "context": intake.get("context"),
        "target_platform": intake.get("target_platform"),
    }, ensure_ascii=False)


def _extract_json(text: str) -> str:
    text = text.replace("```json", "").replace("```", "").strip()
    i, j = text.find("{"), text.rfind("}")
    return text[i:j + 1] if i != -1 and j != -1 and j > i else text


def validate(body: dict) -> dict:
    """합의된 제약을 코드로 강제한다. 위반 시 raise."""
    required = {"goal_interpretation", "requirement_normalization", "proposed_requirements",
                "open_questions", "provenance", "target_platform"}
    missing = required - set(body)
    if missing:
        raise ValueError(f"discovery body 필드 누락: {missing}")

    prov = body["provenance"]

    # target_platform: 입력값(fact, 추론 아님). web|mobile|both|미정.
    tp = body.get("target_platform")
    if tp not in TARGET_PLATFORMS:
        raise ValueError(f"target_platform은 {TARGET_PLATFORMS} 중 하나여야 함(입력값, 현재 '{tp}')")
    if prov.get("target_platform") != "fact":
        raise ValueError("provenance.target_platform은 fact여야 함(입력값, 추론 아님)")
    gi = body["goal_interpretation"]
    if not isinstance(gi, dict):
        raise ValueError("goal_interpretation은 객체여야 함")
    gi_missing = set(GI_KEYS) - set(gi)
    if gi_missing:
        raise ValueError(f"goal_interpretation 필드 누락: {gi_missing}")

    # goal_interpretation은 전부 추론(단정 금지)
    if prov.get("goal_interpretation") != "inference":
        raise ValueError(f"goal_interpretation은 해석·가설만 한다: provenance.goal_interpretation='inference'여야 함(현재 '{prov.get('goal_interpretation')}')")
    for d in gi["inferred_dimensions"]:
        if not d.get("dimension"):
            raise ValueError("inferred_dimensions 항목에 dimension 누락")
    for m in gi["candidate_metrics"]:
        if not m.get("metric"):
            raise ValueError("candidate_metrics 항목에 metric 누락")

    # requirement_normalization: 항목별 origin + 원문 근거(statement)
    for r in body["requirement_normalization"]:
        if not r.get("id"):
            raise ValueError("requirement_normalization 항목에 id 누락")
        if not r.get("statement"):
            raise ValueError(f"No-Fabrication 위반: requirement '{r.get('id')}'에 statement(원문 근거) 없음")
        if r.get("origin") not in REQ_ORIGINS:
            raise ValueError(f"requirement '{r.get('id')}' origin은 explicit|context-inferred 여야 함(현재 '{r.get('origin')}')")
    if body["requirement_normalization"] and prov.get("requirement_normalization") != "per_item":
        raise ValueError("provenance.requirement_normalization은 per_item이어야 함(항목별 origin)")

    # proposed_requirements: 상용 준비 제안(별도 추론 층). R-을 오염시키지 않는다.
    # 각 항목은 basis(고객 cue 근거)+rationale 필수. 근거 없는 제안은 fabrication.
    proposed = body.get("proposed_requirements", [])
    if not isinstance(proposed, list):
        raise ValueError("proposed_requirements는 리스트여야 함")
    for p in proposed:
        if not p.get("id"):
            raise ValueError("proposed_requirements 항목에 id 누락")
        if not p.get("statement"):
            raise ValueError(f"proposed '{p.get('id')}'에 statement 없음")
        if not p.get("basis"):
            raise ValueError(f"No-Fabrication 위반: proposed '{p.get('id')}'에 basis(고객 cue 근거) 없음")
        if not p.get("rationale"):
            raise ValueError(f"proposed '{p.get('id')}'에 rationale(상용 필요 근거) 없음")
        if p.get("origin") != PROPOSED_ORIGIN:
            raise ValueError(f"proposed '{p.get('id')}' origin은 '{PROPOSED_ORIGIN}'여야 함(현재 '{p.get('origin')}')")
    if proposed and prov.get("proposed_requirements") != "inference":
        raise ValueError("provenance.proposed_requirements는 inference여야 함(제안=추론, 사람 확정 전)")
    return body


# proposed_requirements는 '기능별 사고'다(각 R-가 무엇인지에서 빠진 상용 요건을 추론).
# offline(규칙 기반)은 사고할 수 없고, 고정 cue->보안세트 매핑은 거부된 방식이므로 두지 않는다.
# 따라서 offline은 proposed를 비우고 'real 필요'를 open_questions로 표시한다. real 모드 지시(B-2)에 사고 절차가 있다.


def offline_llm(system: str, user: str) -> str:
    """결정적 mock. Goal과 requirements만 사용. 발명 금지. goal_interpretation은 inference, requirement는 explicit."""
    payload = json.loads(user)
    goal = payload.get("goal", {}) or {}
    statement = (goal.get("statement") or "").strip()
    details = goal.get("details") or {}
    requirements = payload.get("requirements", []) or []
    context = (payload.get("context") or "").strip()
    target_platform = payload.get("target_platform") or "미정"

    if statement:
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
        open_questions = ["목표의 구체적 성공 기준(목표 수치·기간)이 statement에 없음: 확정 필요."]
        if not details:
            open_questions.append("goal.details(대상 사용자·지표·제약) 미제공: 해석 불확실성 큼.")
    else:
        inferred_dimensions, candidate_metrics, assumptions = [], [], []
        open_questions = ["Goal.statement 없음: 목표 해석 불가. 고객 언어의 목표 서술 필요."]

    # Context 활용: 있으면 맥락을 가정(inference)으로 반영, 없으면 '고객이 누구인지' open_question.
    if context:
        assumptions.append({"assumption": f"맥락 반영(단정 아님): {context}", "basis": "intake.context"})
    else:
        open_questions.append("고객이 누구인지(intake.context) 미제공: 해석 불확실. context 권장.")

    # requirement_normalization: 고객이 준 requirements만 정리(새 요구 생성 금지). 전부 explicit.
    # (mock은 context 기반 context-inferred 요구를 만들지 않는다. 새 요구 발명 금지 — real이 맥락 해석.)
    requirement_normalization = [
        {"id": f"R-{i + 1:02d}", "statement": req, "origin": "explicit"}
        for i, req in enumerate(requirements)
    ]
    if not requirements:
        open_questions.append("요구사항 미제공: 정규화할 요구 없음.")

    # proposed_requirements: 기능별 사고(각 R-가 무엇인지에서 빠진 상용 요건 추론)는 real 모드에서만 가능.
    # offline은 규칙 기반이라 사고 불가 -> 비우고 안내(고정 매핑은 거부된 방식이므로 두지 않는다).
    proposed_requirements = []
    if requirements:
        open_questions.append("상용 빈틈 제안(proposed_requirements)은 각 요구를 기능별로 사고해야 함: offline은 사고 불가 -> real 모드(DISCOVERY_MODE=real) 필요(현재 빈 값).")

    # target_platform: 입력값(fact). 미지정이면 '미정'으로 저장 + open_question.
    if not payload.get("target_platform"):
        open_questions.append("target_platform 미지정: 기본 '미정'으로 저장(web|mobile|both 협의 필요).")

    body = {
        "goal_interpretation": {
            "inferred_dimensions": inferred_dimensions,
            "candidate_metrics": candidate_metrics,
            "assumptions": assumptions,
        },
        "requirement_normalization": requirement_normalization,
        "proposed_requirements": proposed_requirements,
        "open_questions": open_questions,
        "target_platform": target_platform,
        "provenance": {"goal_interpretation": "inference", "requirement_normalization": "per_item",
                       "proposed_requirements": "inference", "target_platform": "fact"},
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
