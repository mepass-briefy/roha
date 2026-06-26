"""
Security Agent producer.

orchestrator 계약: producer(inputs: dict) -> body: dict
모델 호출은 llm(system, user) -> str 인터페이스로 분리한다.
  - real: 요구를 보안 관점으로 분석하는 Claude 서브에이전트로 교체되는 자리
  - offline: 결정적. intake.requirements만 사용. 키워드 기반 도출. 발명 금지.

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

AGENT_NAME = "agent.security"
SYSTEM_PROMPT = Path(__file__).with_name("agent_security.md").read_text(encoding="utf-8")

CORE_ORIGINS = ("fact", "human")  # 핵심 보안 의무에 허용되는 출처
REAL_MODEL_DEFAULT = "claude-sonnet-4-6"

# real 모드 지시: 기능별 보안 사고(고정 체크리스트 금지). 검색 없음(추론).
REAL_MODE_INSTRUCTION = (
    "\n\n## real 모드 지시(기능별 보안 사고)\n"
    "1. 입력의 discovery.requirement_normalization(정리된 R-)과 proposed_requirements를 본다. 각 요구된 기능을 보고, "
    "그 기능이 상용으로 안전하려면 필요한 보안 통제를 그 기능의 성격에서 도출한다(intake.requirements 키워드 매칭이 아니라).\n"
    "2. 기능마다 다른 통제: 어드민이면 어드민에 필요한 통제(역할 분리·관리 기능 접근통제·감사 로그), 정산이면 정산에 필요한 통제(거래 무결성·금액/상태 변경 추적·정산 검증), "
    "인증/회원이면 계정·세션 통제. 모든 요구에 같은 보안 세트를 붙이는 고정 체크리스트 금지 — 기능마다 통제가 다르다(discovery.proposed_requirements의 기능별 사고와 일관).\n"
    "3. No-Fabrication: 각 security_requirement는 source_requirement(어느 R-/요구에서 도출했는지) 필수. 근거 없는 통제 생성 금지. origin은 \"fact\" 또는 \"human\". "
    "data_classification 항목도 source_requirement 필수.\n"
    "4. 내부 일관성: threat_model의 mitigated_by는 security_requirements의 control 이름만 참조(새 통제 발명 금지). threat_model은 inference.\n"
    "5. provenance: security_requirements=\"fact\"(또는 human), data_classification=\"fact\", threat_model=\"inference\". body에 \"open_questions\": [] 포함. "
    "출력은 출력 스키마의 JSON 객체 하나만(설명 텍스트·코드펜스 금지)."
)

# 요구 텍스트에 포함되면 해당 보안 통제를 트리거하는 키워드 룰(결정적, 발명 아님).
# (키워드, 통제, 카테고리, 민감데이터 분류[있으면])
KEYWORD_RULES = [
    ("결제", "결제 데이터 보호(전송·저장 암호화, 토큰화)", "data_protection", ("결제정보", "high")),
    ("정산", "정산 데이터 무결성·접근통제", "integrity_access", ("재무데이터", "high")),
    ("개인", "개인정보(PII) 보호·최소수집", "privacy", ("개인식별정보", "high")),
    ("신청", "신청 입력 검증·권한 확인", "input_authz", None),
    ("예약", "예약 변조 방지·동시성 제어", "integrity_access", None),
    ("로그인", "인증·세션 보호", "authn_session", ("자격증명", "high")),
    ("회원", "계정 보호·인가 경계", "authn_session", ("계정정보", "medium")),
]


def build_user_prompt(intake: dict, discovery: dict = None) -> str:
    disc = {k: (discovery or {}).get(k) for k in
            ("goal_interpretation", "requirement_normalization", "proposed_requirements")}
    return json.dumps({"intake": intake, "discovery": disc}, ensure_ascii=False)


def validate(body: dict) -> dict:
    """합의된 제약을 코드로 강제한다. 위반 시 raise."""
    required = {"security_requirements", "data_classification", "threat_model",
                "open_questions", "provenance"}
    missing = required - set(body)
    if missing:
        raise ValueError(f"security body 필드 누락: {missing}")

    prov = body["provenance"]

    # No-Fabrication + 추론 0%(핵심 의무): 모든 통제는 source_requirement와 fact|human origin
    controls = set()
    for r in body["security_requirements"]:
        if not r.get("source_requirement"):
            raise ValueError(f"No-Fabrication 위반: source_requirement 없는 통제 '{r.get('control')}'")
        if r.get("origin") not in CORE_ORIGINS:
            raise ValueError(f"추론 층 분리 위반: 핵심 통제 '{r.get('control')}' origin은 fact|human이어야 함")
        controls.add(r["control"])

    if body["security_requirements"] and prov.get("security_requirements") not in CORE_ORIGINS:
        raise ValueError("provenance.security_requirements는 fact|human이어야 함(핵심 의무 추론 0%)")

    # data_classification도 핵심 의무: source_requirement 필수 + 추론 0%
    for d in body["data_classification"]:
        if not d.get("source_requirement"):
            raise ValueError(f"No-Fabrication 위반: source_requirement 없는 데이터 분류 '{d.get('data')}'")
    if body["data_classification"] and prov.get("data_classification") not in CORE_ORIGINS:
        raise ValueError("provenance.data_classification은 fact|human이어야 함(핵심 의무 추론 0%)")

    # 보완·세부(threat_model)는 inference 표기 의무
    if body["threat_model"] and prov.get("threat_model") != "inference":
        raise ValueError("provenance.threat_model은 inference여야 함")

    # 내부 일관성(근거 없는 통제 발명 금지): threat의 mitigated_by는 security_requirements 안에서만
    for t in body["threat_model"]:
        if t.get("mitigated_by") not in controls:
            raise ValueError(f"발명된 통제 참조 in threat_model: '{t.get('mitigated_by')}' (security_requirements에 없음)")

    return body


def offline_llm(system: str, user: str) -> str:
    """결정적 오프라인 모드. intake.requirements만 사용. 키워드 기반 도출. 발명 금지."""
    intake = json.loads(user)["intake"]
    requirements = intake.get("requirements", [])

    security_requirements = []
    data_classification = []
    matched_reqs = set()
    seen_controls = set()
    seen_data = set()

    for req in requirements:
        for kw, control, category, data in KEYWORD_RULES:
            if kw in req:
                matched_reqs.add(req)
                if control not in seen_controls:
                    security_requirements.append({
                        "control": control, "category": category,
                        "source_requirement": req, "origin": "fact",
                    })
                    seen_controls.add(control)
                if data and data[0] not in seen_data:
                    data_classification.append({
                        "data": data[0], "sensitivity": data[1], "source_requirement": req,
                    })
                    seen_data.add(data[0])

    # threat_model: 각 통제에 대응하는 위협(보완·세부, inference). control 안에서만 참조.
    threat_model = [
        {"threat": f"{r['control']} 미흡 시 발생 가능한 침해", "mitigated_by": r["control"]}
        for r in security_requirements
    ]

    open_questions = []
    if not requirements:
        open_questions.append("intake.requirements 없음. 보안 통제 도출 불가")
    for req in requirements:
        if req not in matched_reqs:
            open_questions.append(f"요구 '{req}'의 보안 영향 미상(키워드 룰 미매칭). 실분석 필요")

    body = {
        "security_requirements": security_requirements,
        "data_classification": data_classification,
        "threat_model": threat_model,
        "open_questions": open_questions,
        "provenance": {
            "security_requirements": "fact",
            "data_classification": "fact",
            "threat_model": "inference",
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
    discovery = inputs.get("discovery", {})  # v12: discovery 입력(real 프롬프트가 기능별 보안 사고에 사용)
    up = build_user_prompt(intake, discovery)
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
