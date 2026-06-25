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
    "B-2. proposed_requirements: 상용·운영을 위해 '고객이 말하지 않았지만 필요한' 요구를 제안한다(requirement_normalization과 별도 층). "
    "각 항목 {id:\"P-01\".., statement, category, rationale, basis, origin:\"proposed\"}. "
    "이것은 R-(충실 정규화)를 오염시키지 않는다: R-은 고객이 말한 것만, P-는 그 말에서 도출되는 상용 함의의 제안이다. "
    "basis 필수(어느 고객 cue/R-항목/context 구절에서 도출됐는지). 근거 없는 제안은 fabrication이므로 금지. "
    "rationale 필수(왜 상용에 필요한가). 전부 사람 확정 전 '검토 필요'. provenance.proposed_requirements=\"inference\".\n"
    "  제안 대상 예(고객 cue가 있을 때만): 관리자/운영 언급 -> 역할 기반 접근 제어(RBAC)·폐쇄적 접근 구조(관리 기능 비공개), "
    "회원/가입/인증 언급 -> 인증·계정 보안 기준(비밀번호·세션·인가), 정산/결제/계약금 언급 -> 거래·정산 무결성·감사 로그, "
    "검증 언급 -> 신원·자격 검증 프로세스(승인 주체·기준·기록), 개인정보 언급 -> 개인정보 보호·최소수집·접근통제. "
    "cue가 없으면 해당 제안을 만들지 않는다(일반론 나열 금지).\n"
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


_PROPOSAL_RULES = [
    (["어드민", "관리자", "관리", "운영"],
     {"statement": "역할 기반 접근 제어(RBAC): 관리자·운영자와 일반 사용자의 권한을 분리한다.",
      "category": "access-control",
      "rationale": "관리/운영 주체와 다수 사용자 유형이 존재 — 상용은 권한 분리 없이는 운영·보안이 성립하지 않음."}),
    (["어드민", "관리자", "권한", "접근"],
     {"statement": "폐쇄적 접근 구조: 관리·운영 기능은 인증·인가된 사용자만 접근(공개 노출 금지).",
      "category": "access-control",
      "rationale": "관리 기능이 공개 경로에 노출되면 무단 접근 위험. 상용 기본 통제."}),
    (["회원", "가입", "로그인", "인증", "계정"],
     {"statement": "인증·계정 보안 기준(비밀번호 정책·세션 관리·인가 검사).",
      "category": "security",
      "rationale": "회원/가입을 언급 — 계정이 존재하면 인증·세션·인가는 필수 기반."}),
    (["정산", "결제", "계약금", "거래", "대금"],
     {"statement": "거래·정산 무결성과 감사 로그(금액·상태 변경 이력 추적·정산 검증).",
      "category": "data-integrity",
      "rationale": "금전 흐름을 언급 — 분쟁·오류 대비 변경 이력과 검증이 상용 필수."}),
    (["검증", "인증서", "자격", "실명"],
     {"statement": "신원·자격 검증 프로세스 정의(승인 주체·기준·기록).",
      "category": "operations",
      "rationale": "검증을 언급 — 누가 무엇을 어떤 기준으로 승인하는지 정의 필요."}),
]


def _propose(requirements, context):
    """결정적 제안 생성(mock). 고객 cue가 있을 때만 제안한다(근거 없는 일반론 금지)."""
    items = [(f"R-{i + 1:02d}", r) for i, r in enumerate(requirements)]
    ctx = context or ""

    def find_basis(keys):
        for rid, r in items:
            if any(k in r for k in keys):
                return f"{rid}: {r}"
        if ctx and any(k in ctx for k in keys):
            return "intake.context"
        return None

    out, seen = [], set()
    for keys, prop in _PROPOSAL_RULES:
        if prop["statement"] in seen:
            continue
        basis = find_basis(keys)
        if not basis:                     # 근거 없으면 제안하지 않음(No-Fabrication)
            continue
        seen.add(prop["statement"])
        out.append({"id": f"P-{len(out) + 1:02d}", **prop, "origin": PROPOSED_ORIGIN, "basis": basis})
    return out


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

    # proposed_requirements: 고객 cue에서 도출되는 상용 준비 제안(R-과 분리, 사람 확정 전).
    proposed_requirements = _propose(requirements, context)

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
