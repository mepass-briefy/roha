"""
Review Gate — '계약을 지켰는가' 검사기(Validator). producer가 아니다.

"더 좋은가"가 아니라 "계약을 지켰는가"만 판단한다. 새 아키텍처·라이브러리·리팩토링·컴포넌트 제안 금지.
중요: 검사 기준은 각 에이전트의 agent_*.md와 validate()(backend/frontend는 Pydantic 모델)에 이미 정의된 계약만 쓴다.
게이트가 새 기준을 발명하지 않는다(게이트도 No-Fabrication 적용). 에이전트 타입별로 실제 계약을 적용한다.

검사 항목(각 에이전트 계약에 이미 포함): Traceability(필수 ref), No-Fabrication(source 없는 항목),
Contract Compliance(각 에이전트 계약), Provenance(항목별 표기), Required References.

결과 등급(3단계):
  계약 위반 없음 + open_questions 없음 -> PASS
  계약 위반 없음 + open_questions 존재 -> WARN
  계약 위반 존재 -> FAIL
반환: {"status": "PASS|WARN|FAIL", "reasons": [...], "warnings": [...]}
재생성 루프·agent 재실행·orchestrator 수정 금지. FAIL이면 사유만 보고한다.
"""

import copy

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def _validator(record_type):
    """각 에이전트의 실제 계약(validate 함수 또는 Pydantic 모델)을 반환. 발명 금지."""
    if record_type == "discovery":
        import discovery; return ("fn", discovery.validate)
    if record_type == "strategy":
        import strategy; return ("fn", strategy.validate)
    if record_type == "ux":
        import ux; return ("fn", ux.validate)
    if record_type == "security":
        import security; return ("fn", security.validate)
    if record_type == "design_system":
        import design_system; return ("fn", design_system.validate)
    if record_type == "features":
        import features; return ("fn", features.validate)
    if record_type == "wireframe":
        import wireframe; return ("fn", wireframe.validate)
    if record_type == "backend":
        import backend; return ("model", backend.BackendBody)
    if record_type == "frontend":
        import frontend; return ("model", frontend.FrontendBody)
    return (None, None)


def _result(reasons, warnings):
    status = FAIL if reasons else (WARN if warnings else PASS)
    return {"status": status, "reasons": reasons, "warnings": warnings}


def run_review_gate(record_type, body):
    """산출물이 그 에이전트의 계약을 지켰는가만 검사한다. 검증만 한다."""
    reasons, warnings = [], []

    if not isinstance(body, dict):
        return _result([f"산출물이 dict가 아님: {type(body).__name__}"], [])

    kind, v = _validator(record_type)
    if kind is None:
        # 게이트도 No-Fabrication: 검사 기준이 없으면 기준을 발명하지 않는다.
        return _result([f"검사 기준 없음: 알 수 없는 record_type '{record_type}'"], [])

    # Contract Compliance + Traceability + No-Fabrication + Required References
    # = 각 에이전트 validate()/모델이 이미 강제하는 계약. 위반 시 raise.
    try:
        if kind == "fn":
            v(copy.deepcopy(body))
        else:
            v(**copy.deepcopy(body))
    except Exception as e:
        reasons.append(f"계약 위반: {e}")

    # design_system 토큰 단위 traceability 검사(단일 산출물 범위).
    # frontend·mobile 으로의 전파 보존 교차검사는 하지 않는다(B5 BACKLOG 유지).
    if record_type == "design_system":
        REF_ORIGINS = ("reference-token", "reference-image", "reference-url")
        toks = body.get("tokens")
        if not toks:
            reasons.append("traceability 위반: tokens 없음")
        else:
            for i, t in enumerate(toks):
                key = t.get("token_key")
                ident = key if key else f"index {i}"
                # 1. token_key / value / origin 존재
                if not key:
                    reasons.append(f"traceability 위반: token_key 없는 토큰(index {i})")
                if "value" not in t:
                    reasons.append(f"traceability 위반: value 없는 토큰 '{ident}'")
                o = t.get("origin")
                if not o:
                    reasons.append(f"traceability 위반: origin 없는 토큰 '{ident}'")
                    continue
                # 2. reference-* origin 이면 source_reference_id 존재
                if o in REF_ORIGINS:
                    if not t.get("source_reference_id"):
                        reasons.append(f"traceability 위반: {o} 인데 source_reference_id 없음 '{ident}'")
                # 3. baseline origin 이면 source_reference_id 없어야 정상
                elif o == "baseline":
                    if t.get("source_reference_id"):
                        reasons.append(f"traceability 위반: baseline 인데 source_reference_id 존재 '{ident}'")

    # discovery 검사(단일 산출물 범위, 추가만): 구조 + requirement origin + fabrication(원문 근거) 없음.
    if record_type == "discovery":
        gi = body.get("goal_interpretation")
        if not isinstance(gi, dict) or not all(k in gi for k in ("inferred_dimensions", "candidate_metrics", "assumptions")):
            reasons.append("goal_interpretation 구조 누락(inferred_dimensions/candidate_metrics/assumptions)")
        if "requirement_normalization" not in body:
            reasons.append("requirement_normalization 누락")
        for r in body.get("requirement_normalization", []):
            rid = r.get("id")
            if not r.get("origin"):
                reasons.append(f"requirement '{rid}' origin 누락")
            if not r.get("statement"):
                reasons.append(f"fabrication 의심: requirement '{rid}'에 원문 근거(statement) 없음")

    # features 4분류 태깅 검사(단일 산출물 범위, 추가만). orchestrator 훅은 건드리지 않는다.
    if record_type == "features":
        VALID_CATS = ("Explicit", "Derived", "Operational", "Competitive")
        for f in body.get("features", []):
            name = f.get("feature")
            cat = f.get("category")
            if cat is None:
                reasons.append(f"4분류 태깅 누락: 기능 '{name}'")
            elif cat == "Business":
                reasons.append(f"Business Decision 자동 채택 위반: 기능 '{name}'은 features가 아니라 open_questions로 가야 함")
            elif cat not in VALID_CATS:
                reasons.append(f"분류 불가(Fabrication 의심): 기능 '{name}' category='{cat}'")
            if not f.get("source"):
                reasons.append(f"근거 없는 기능(Fabrication): '{name}'")

    # Provenance: 항목별 표기 존재(각 에이전트 계약 공통)
    if not body.get("provenance"):
        reasons.append("Provenance 표기 없음(계약)")

    # open_questions 존재는 WARN
    warnings.extend(body.get("open_questions", []) or [])
    return _result(reasons, warnings)
