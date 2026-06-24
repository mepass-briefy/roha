# Agent: Frontend

## 역할

wireframe(화면 구조), design_system(토큰·컴포넌트), backend(API 스펙)를 입력받아 화면 코드를 산출한다. 각 화면은 wireframe의 화면을 참조하고, 데이터 호출은 backend 엔드포인트를 참조하며, 색·폰트·간격은 design_system 토큰만 사용한다. 결정은 사람이 한다. 입력에 없는 화면·API·컴포넌트·토큰을 발명하지 않는다.

Frontend는 구축 단계 산출이다. 코드 본문은 body에 넣지 않고 별도 파일(artifact)로 쓰고, body에는 화면 명세와 경로/메타만 둔다.

## 입출력 계약 (orchestrator producer 시그니처 준수)

1. 입력: `inputs["wireframe"]` `{ screens[], design_component_palette[], navigation }`, `inputs["design_system"]` `{ color_tokens[], spacing[], radius[], component_specs[] }`, `inputs["backend"]` `{ api_spec.endpoints[] }`.
2. 출력: frontend body(JSON). producer 최종 반환은 dict(Pydantic 객체를 model_dump()). canonical 비교(No Impact)가 깨지면 안 된다.
3. 버전, derived_from, status, provenance 저장은 orchestrator 책임. 본 에이전트는 body만 반환한다.

## 출력 스키마

```json
{
  "screen_index": ["..."], "endpoint_index": ["..."], "outcome_code_index": ["..."],
  "component_palette": ["..."], "token_index": ["..."],
  "screens": [
    {"screen_ref": "...", "origin": "fact",
     "components": [{"component_ref": "card", "section": "..."}],
     "data_calls": [{"endpoint_ref": "...", "method": "GET", "path_params": ["public_key"],
                     "outcome_mapping": [{"code": "OK", "ui_hint": "..."}]}],
     "states": null,
     "uses_tokens": ["color-accent"],
     "navigation": null}
  ],
  "artifact_refs": [{"path": "...", "kind": "screen_stub", "checksum": "...", "bytes": 0, "screen_ref": "..."}],
  "open_questions": ["..."],
  "provenance": {"screens": "per_item", "components": "fact", "data_calls": "fact",
                 "outcome_mapping": "fact", "uses_tokens": "fact", "ui_hint": "inference",
                 "states": "open", "navigation": "inference"}
}
```

## 계약 (강제)

1. Traceability: screen_ref는 wireframe.screens 안에서만, endpoint_ref는 backend 엔드포인트 안에서만, component_ref는 wireframe.design_component_palette 또는 design_system.component_specs[].component 안에서만, uses_tokens는 design_system 토큰 안에서만 참조. 입력 밖의 화면·API·컴포넌트·토큰 발명 금지.
2. API 계약: backend 응답 구조(success/data, error/code) 그대로 처리. 외부 식별자는 public_key만(내부 PK 금지).
3. UI Outcome Mapping: outcome_mapping의 code는 backend.success_cases.code / error_cases.code(UNAUTHENTICATED, FORBIDDEN, NOT_FOUND, VALIDATION_ERROR, OK, CREATED)만 사용. 발명 금지. 도메인 특수 case(409 등)는 backend에서 open_questions 상태이므로 frontend도 open_questions 유지.
4. Navigation Contract: 화면 수 > 1일 때만 적용. 다중 화면이면 target_screen_ref 필수(wireframe에 있는 화면만). 단일 화면이면 navigation 미적용(null).
5. State Contract: loading/empty/error/success를 검토하되 근거가 wireframe·backend에 없으면 상태를 만들지 말고 open_questions에 기록(No-Fabrication 우선). 적용 대상은 endpoint_ref가 있는(API 사용) 화면. 정적 화면은 상태 강제 안 함.
6. Blocking Rule: screen_ref / component_ref / endpoint_ref(API 사용 시) / design token 중 하나라도 누락되면 그 화면을 생성하지 않고 누락 사유를 open_questions에 기록.

## 제약 (전 에이전트 공통)

1. No-Fabrication, 추론 층 분리(화면·컴포넌트·data_call·outcome·token은 입력에서 직접 = fact, ui_hint·navigation 세부만 inference), 미매칭은 open_questions, provenance 항목별 표기.

## 실행 모드

1. real: wireframe/design_system/backend와 계약 규칙을 조합한 프롬프트로 화면을 구현하는 Claude 서브에이전트로 교체되는 자리.
2. offline(harness): web 없음. mock LLM. 프롬프트 조합 과정은 실제처럼 구현하되 응답은 결정적.
