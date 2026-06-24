"""
Test Gate — '도는가' 검사기(Validator). producer가 아니다.

산출물 body(+artifact 파일)를 읽고 검증만 한다. 새 body·artifact 생성 금지, 내부에서 다른 agent 재실행 금지.
검사 범위(이것만): Pydantic 검증 통과, 반환 구조(dict), artifact_refs 파일 실제 존재, demo exit code.
계약 해석·개선 의견 생성 금지.

결과 등급(3단계):
  계약 위반 없음 + open_questions 없음 -> PASS
  계약 위반 없음 + open_questions 존재 -> WARN
  계약 위반 존재 -> FAIL
반환: {"status": "PASS|WARN|FAIL", "reasons": [...], "warnings": [...]}
"""

import copy
from pathlib import Path

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def _pydantic_model(record_type):
    """Pydantic을 쓰는 에이전트만 해당 모델 반환(backend/frontend). 없으면 None."""
    if record_type == "backend":
        import backend
        return backend.BackendBody
    if record_type == "frontend":
        import frontend
        return frontend.FrontendBody
    return None


def _result(reasons, warnings):
    status = FAIL if reasons else (WARN if warnings else PASS)
    return {"status": status, "reasons": reasons, "warnings": warnings}


def run_test_gate(record_type, body, *, artifact_base=None, demo_exit_code=None):
    """산출물이 '도는가'를 검사한다. 검증만 하고 아무것도 만들지 않는다."""
    reasons, warnings = [], []

    # 1. producer 반환 구조: dict
    if not isinstance(body, dict):
        return _result([f"producer 반환이 dict가 아님: {type(body).__name__}"], [])

    # 2. Pydantic 검증 통과(해당 타입만)
    model = _pydantic_model(record_type)
    if model is not None:
        try:
            model(**copy.deepcopy(body))
        except Exception as e:
            reasons.append(f"Pydantic 검증 실패: {e}")

    # 3. artifact_refs 파일 실제 존재
    for a in body.get("artifact_refs", []):
        rel = a.get("path", "")
        p = (Path(artifact_base) / rel) if artifact_base else Path(rel)
        if not p.exists():
            reasons.append(f"artifact 파일 없음: {rel}")

    # 4. demo exit code(주어졌을 때만). 게이트가 직접 실행하지 않는다.
    if demo_exit_code is not None and demo_exit_code != 0:
        reasons.append(f"demo exit code {demo_exit_code} != 0")

    # open_questions 존재는 FAIL이 아니라 WARN
    warnings.extend(body.get("open_questions", []) or [])
    return _result(reasons, warnings)
