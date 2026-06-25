"""
Review Gate — '계약을 지켰는가' 검사기(Validator). producer가 아니다.

"더 좋은가"가 아니라 "계약을 지켰는가"만 판단한다. 새 아키텍처·라이브러리·리팩토링·컴포넌트 제안 금지.
중요: 검사 기준은 각 에이전트의 agent_*.md와 validate()(backend/frontend는 Pydantic 모델)에 이미 정의된 계약만 쓴다.
게이트가 새 기준을 발명하지 않는다(게이트도 No-Fabrication 적용). 에이전트 타입별로 실제 계약을 적용한다.

검사 항목(각 에이전트 계약에 이미 포함): Traceability(필수 ref), No-Fabrication(source 없는 항목),
Contract Compliance(각 에이전트 계약), Provenance(항목별 표기), Required References.

결과 등급(3단계):
  계약 위반 없음 + open_questions 없음 -> PASS
  계약 위반 없음 + open_questions/품질 경고만 -> WARN
  계약 위반 존재 -> FAIL
반환: {"status": "PASS|WARN|FAIL", "reasons": [...], "warnings": [...]}

두 레벨 분리(backend·wireframe·features·design_system): 계약 위반=ERROR=reasons(FAIL, 차단) vs 품질 미달=WARN=warnings(통과, EXIT 0).
에이전틱 루프가 없으므로 '지금 막으면 자동 복구 수단이 없는 것'만 ERROR로 한다.
  ERROR(차단): 빈 산출(entities/endpoints/screens/features/component=[]), 발명(source 근거 형식 위반·미존재 참조),
    식별자 3종 결손(backend), 외부 public_key 위반(backend), 하드코딩 색·WCAG 위반(design_system).
  WARN(통과): 빈약(fields·수용기준 부족·관계 미모델링), 커버리지 일부 결손, 컴포넌트 상태 누락, 권고(네이밍 등).
  features는 식별자 3종·외부 public_key 비해당. design_system은 토큰 엔진이 결정적(WCAG 보장)이라 정상 산출은 ERROR 0.
재생성 루프·agent 재실행·orchestrator 수정 금지. FAIL(ERROR)이면 사유만 보고한다.
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


def _ident_empty(val):
    return val is None or (isinstance(val, str) and not val.strip()) or (isinstance(val, (dict, list)) and not val)


def contract_levels(record_type, body):
    """계약 위반=ERROR(reasons, 차단) vs 품질 미달=WARN(warnings, 통과)을 항목별로 분리한다.
    backend·wireframe 공통 규칙은 공유, 산출물별 항목(entities/endpoints vs screens)만 분기.
    게이트는 body만 본다(입력 미참조): 멤버십 발명(입력 대조)은 producer 교차검증에서 차단됨.
    여기서 다루는 발명은 body 내부 규칙(source 형식 / wireframe는 palette·feature_index 멤버십).
    에이전틱 루프가 없으므로 '지금 막으면 자동 복구 수단이 없는 것'만 ERROR.
    """
    errors, warns = [], []

    if record_type == "backend":
        api = body.get("api_spec") or {}
        endpoints = api.get("endpoints") or []
        entities = body.get("entities") or []
        # 1) 빈 산출 = ERROR(하류 계약 깨짐)
        if not entities:
            errors.append("[빈 산출] backend entities=[] — 핵심 기능이 있으면 엔티티는 반드시 존재")
        if not endpoints:
            errors.append("[빈 산출] backend endpoints=[] — 핵심 기능이 있으면 엔드포인트는 반드시 존재")
        entity_feats = set()
        for e in entities:
            nm = e.get("name", "?")
            src = str(e.get("source", ""))
            # 2) 발명(형식): source는 feature:/ux: 근거
            if src.startswith("feature:") or src.startswith("ux:"):
                entity_feats.add(src.split(":", 1)[1])
            else:
                errors.append(f"[발명] entity '{nm}' source가 feature:/ux: 근거 아님('{src}')")
            # 3) 식별자 3종 누락
            ids = e.get("identifiers") or {}
            for k in ("pk", "business_key", "public_key"):
                if _ident_empty(ids.get(k)):
                    errors.append(f"[식별자 3종] entity '{nm}' '{k}' 결손")
            # 5) 품질: 도메인 필드 빈약
            if len(e.get("fields") or []) < 2:
                warns.append(f"[품질] entity '{nm}' 도메인 필드 빈약(fields {len(e.get('fields') or [])}개)")
        # 5) 품질: 관계 미모델링
        if entities and not any((e.get("relations") or []) for e in entities):
            warns.append("[품질] 엔티티 간 관계(relations) 미모델링")
        for ep in endpoints:
            eid = ep.get("endpoint_id", "?")
            # 2) 발명/Traceability: feature_ref·security_ref 필수
            if not ep.get("feature_ref"):
                errors.append(f"[발명] endpoint '{eid}' feature_ref 결손(Traceability)")
            if not ep.get("security_ref"):
                errors.append(f"[발명] endpoint '{eid}' security_ref 결손(Traceability)")
            # 4) 외부 public_key: 경로 파라미터는 {public_key}만, id/pk 노출 금지
            for seg in str(ep.get("path", "")).split("/"):
                if seg.startswith("{") and seg.endswith("}"):
                    if seg != "{public_key}":
                        errors.append(f"[외부 public_key] endpoint '{eid}' 경로 파라미터 '{seg}'(외부는 public_key만)")
                elif seg in ("id", "pk"):
                    errors.append(f"[외부 public_key] endpoint '{eid}' 경로에 내부 식별자 '{seg}' 노출")
        # 6) 커버리지(품질): 엔드포인트만 있고 대응 엔티티 없는 기능(일부 결손)
        ep_feats = {ep.get("feature_ref") for ep in endpoints if ep.get("feature_ref")}
        uncov = sorted(f for f in ep_feats if f and f not in entity_feats)
        if entities and uncov:
            warns.append(f"[커버리지] 엔티티 없는 기능(엔드포인트만): {uncov}")

    elif record_type == "wireframe":
        screens = body.get("screens") or []
        palette = set(body.get("design_component_palette") or [])
        feat_index = set(body.get("feature_index") or [])
        # 1) 빈 산출 = ERROR
        if not screens:
            errors.append("[빈 산출] wireframe screens=[] — 핵심 기능이 있으면 화면은 반드시 존재")
        covered = set()
        for s in screens:
            nm = s.get("screen", "?")
            src = str(s.get("source", ""))
            origin = s.get("origin")
            # 2) 발명(형식): 핵심=ux:/feature:, 파생=derived:
            if origin in ("fact", "human"):
                if not (src.startswith("ux:") or src.startswith("feature:")):
                    errors.append(f"[발명] 핵심 화면 '{nm}' source가 ux:/feature: 근거 아님('{src}')")
            else:
                if not src.startswith("derived:"):
                    errors.append(f"[발명] 파생 화면 '{nm}' source가 derived: 아님('{src}')")
            secs = s.get("sections") or []
            if not secs:
                warns.append(f"[품질] 화면 '{nm}' 섹션 없음")
            for sec in secs:
                # 2) 발명(멤버십, body 내부): components⊆palette, feature_refs⊆feature_index
                for c in sec.get("components", []):
                    if c not in palette:
                        errors.append(f"[발명] 화면 '{nm}' 컴포넌트 '{c}'가 palette에 없음")
                for fr in sec.get("feature_refs", []):
                    if fr not in feat_index:
                        errors.append(f"[발명] 화면 '{nm}' 기능참조 '{fr}'가 feature_index에 없음")
                    else:
                        covered.add(fr)
        # 6) 커버리지(품질): 어떤 화면에도 배치 안 된 기능(일부 결손)
        uncov = sorted(f for f in feat_index if f not in covered)
        if screens and uncov:
            warns.append(f"[커버리지] 화면에 배치되지 않은 기능: {uncov}")

    elif record_type == "features":
        feats = body.get("features") or []
        # 1) 빈 산출 = ERROR
        if not feats:
            errors.append("[빈 산출] features=[] — 요구가 있으면 기능은 반드시 존재")
        # 발명(형식): source는 features 계약의 근거 prefix만(ux:/requirement:/derived:/http).
        # discovery:/strategy: 같은 미정의 prefix는 features 계약에 없음. 멤버십 발명(입력 대조)은
        # body에 discovery_index가 없어 producer 교차검증에서 차단(유지) — 게이트는 형식만.
        VALID_SRC = ("ux:", "requirement:", "derived:", "http://", "https://")
        for f in feats:
            nm = f.get("feature", "?")
            src = str(f.get("source", ""))
            if not src:
                errors.append(f"[발명] feature '{nm}' source 결손(근거 없음)")
            elif not src.startswith(VALID_SRC):
                errors.append(f"[발명] feature '{nm}' source가 근거 형식 아님('{src}') — ux:/requirement:/derived:/http 만 허용")
            # 5) 품질: 완결성(수용 기준) 빈약
            if not (f.get("acceptance_criteria") or []):
                warns.append(f"[품질] feature '{nm}' 수용 기준(acceptance_criteria) 빈약")
        # 6) 커버리지(품질): discovery 목표 대조는 body에 discovery_index가 없어 생략(형식 검사로 유지).

    elif record_type == "design_system":
        import re as _re
        import design_system as _ds
        _HEXLIT = _re.compile(r"#[0-9A-Fa-f]{3,8}\b")

        def _has_hex(obj):
            if isinstance(obj, str):
                return bool(_HEXLIT.search(obj))
            if isinstance(obj, dict):
                return any(_has_hex(v) for v in obj.values())
            if isinstance(obj, list):
                return any(_has_hex(v) for v in obj)
            return False

        comps = body.get("component") or []
        # 1) 빈 산출 = ERROR
        if not comps:
            errors.append("[빈 산출] design_system component=[] — 컴포넌트가 비어선 안 됨")
        for c in comps:
            nm = c.get("component", "?")
            # 2) 하드코딩 색 = ERROR: 컴포넌트는 토큰 키만 참조(states·uses_tokens에 hex 직접 금지)
            if _has_hex(c.get("states", {})) or _has_hex(c.get("uses_tokens", [])):
                errors.append(f"[하드코딩 색] component '{nm}'가 토큰 대신 hex 색을 직접 참조")
            # 5) 품질: 상태/토큰 참조 누락 = WARN
            if not c.get("states"):
                warns.append(f"[품질] component '{nm}' 상태(states) 누락")
            if not c.get("uses_tokens"):
                warns.append(f"[품질] component '{nm}' uses_tokens 미참조")
        # 3) WCAG 위반 = ERROR: 의미색 4토큰(엔진 보장) 대비 미달이면 차단
        col = (body.get("foundation") or {}).get("color") or {}
        for name in ("success", "warning", "danger"):
            for mode in ("light", "dark"):
                cm = col.get(mode) or {}
                if all(k in cm for k in (name, f"on-{name}", "surface")):
                    if (_ds._contrast(cm[f"on-{name}"], cm[name]) < _ds.WCAG_AA
                            or _ds._contrast(cm[name], cm["surface"]) < _ds.WCAG_AA):
                        errors.append(f"[WCAG] {mode} 의미색 '{name}' 대비 미달(4.5:1)")

    return errors, warns


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

    # backend·wireframe·features·design_system: 계약 위반=ERROR(reasons, 차단) vs 품질 미달=WARN(warnings, 통과) 항목별 분리.
    # (빈 산출 / 발명 / 식별자 3종(backend) / 외부 public_key(backend) / 하드코딩 색·WCAG(design_system) = ERROR. 빈약 / 커버리지 / 상태 누락 = WARN.)
    if record_type in ("backend", "wireframe", "features", "design_system"):
        errs, qwarns = contract_levels(record_type, body)
        reasons.extend(errs)
        warnings.extend(qwarns)

    # open_questions 존재는 WARN
    warnings.extend(body.get("open_questions", []) or [])
    return _result(reasons, warnings)
