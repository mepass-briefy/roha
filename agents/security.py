"""
Security Agent producer.

orchestrator 계약: producer(inputs: dict) -> body: dict
모델 호출은 llm(system, user) -> str 인터페이스로 분리한다.
  - real: 요구를 보안 관점으로 분석하는 Claude 서브에이전트로 교체되는 자리
  - offline: 결정적. intake.requirements만 사용. 키워드 기반 도출. 발명 금지.

본 에이전트는 body만 반환한다. 버전/derived_from/status는 orchestrator 책임.
"""

import json
from pathlib import Path

AGENT_NAME = "agent.security"
SYSTEM_PROMPT = Path(__file__).with_name("agent_security.md").read_text(encoding="utf-8")

CORE_ORIGINS = ("fact", "human")  # 핵심 보안 의무에 허용되는 출처

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


def build_user_prompt(intake: dict) -> str:
    return json.dumps({"intake": intake}, ensure_ascii=False)


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


def produce(inputs: dict, llm=offline_llm) -> dict:
    intake = inputs["intake"]
    discovery = inputs.get("discovery", {})  # v12: discovery 입력 연결(받기만, 활용은 real 단계 프롬프트에서)
    raw = llm(SYSTEM_PROMPT, build_user_prompt(intake))
    raw = raw.replace("```json", "").replace("```", "").strip()
    body = json.loads(raw)
    return validate(body)


def make_producer(llm=offline_llm):
    """orchestrator에 등록할 producer(inputs)->body 클로저. llm 주입은 클로저로 처리(구조 변경 없음)."""
    def producer(inputs):
        return produce(inputs, llm=llm)
    return producer
