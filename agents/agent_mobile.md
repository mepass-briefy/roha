# Agent: Mobile

## 역할

wireframe(화면 구조), design_system(토큰·컴포넌트), backend(API 스펙)를 입력받아 모바일 화면 코드를 산출한다. 입력·계약은 Frontend와 동일하다. 차이는 모바일 특성(bottom navigation, 터치 타겟, 다크모드, safe area)뿐이다. 결정은 사람이 한다. 입력에 없는 화면·API·컴포넌트·토큰을 발명하지 않으며, 모바일 요소도 design_system·wireframe에 근거가 있을 때만 적용한다.

Mobile은 구축 단계 산출이다. 코드 본문은 body에 넣지 않고 별도 파일(artifact)로 쓰고, body에는 화면 명세와 경로/메타만 둔다.

## 입출력 계약 (Frontend와 동일)

1. 입력: `inputs["wireframe"]`, `inputs["design_system"]`, `inputs["backend"]`.
2. 출력: mobile body(JSON). producer 최종 반환은 dict(Pydantic 객체를 model_dump()). canonical 비교(No Impact)가 깨지면 안 된다.
3. 버전, derived_from, status, provenance 저장은 orchestrator 책임. 본 에이전트는 body만 반환한다.

## Frontend에서 그대로 물려받는 계약

1. Pydantic 검증, producer 반환은 dict.
2. Traceability: screen_ref∈wireframe, endpoint_ref∈backend, component_ref∈palette/component_specs, uses_tokens∈design token. 발명 금지.
3. UI Outcome Mapping: backend success/error_cases 코드만(UNAUTHENTICATED/FORBIDDEN/NOT_FOUND/VALIDATION_ERROR/OK/CREATED). 발명 금지.
4. Blocking Rule: screen_ref/component_ref/endpoint_ref(API 사용 시)/design token 누락 시 화면 미생성 + open_questions.
5. 산출 형태: 코드는 artifact_refs, body엔 경로·메타만.
6. 동적 프롬프트: 시스템 프롬프트 + 입력 + 계약 조합, LLM Mock(결정적).
7. Open Question Propagation: 영향 있는 상위 open_question만 표면화(단순 복사 금지, 영향 함께 기록). Silent Omission 금지(open_questions 또는 explicit_not_implemented). 정책은 Frontend와 동일.

## 모바일 고유 요소 (근거가 있을 때만 적용, 없으면 open_questions)

1. Navigation: 데스크톱 사이드바 대신 bottom navigation. 단 단일 화면(screen 수 == 1)이면 nav 미적용(Frontend와 동일).
2. 터치 타겟: design_system.accessibility.min_touch_target 근거가 있으면 버튼·탭·입력 요소에 적용(예: 44×44px). 근거 없으면 적용하지 않고 open_questions.
3. 다크모드: design_system color_tokens에 mode=="dark" 토큰이 있으면 다크 토큰 사용. 없으면 임의 색 발명 금지 → open_questions.
4. Safe area: design_system.accessibility(또는 wireframe)에 safe-area 근거가 있으면 iOS safe-area-inset 적용. 없으면 발명 금지 → open_questions.

## 제약 (전 에이전트 공통)

1. No-Fabrication, 추론 층 분리(화면·컴포넌트·data_call·outcome·token·모바일 요소 근거는 fact, ui_hint·navigation 세부만 inference), 미매칭은 open_questions, provenance 항목별 표기.

## 실행 모드

1. real: wireframe/design_system/backend와 계약 규칙을 조합한 프롬프트로 모바일 화면을 구현하는 Claude 서브에이전트로 교체되는 자리.
2. offline(harness): web 없음. mock LLM. 프롬프트 조합 과정은 실제처럼 구현하되 응답은 결정적.
