# BACKLOG (구조 변경 필요. 즉시 수정 금지)

현재 구조 위에서 구현 중 발견된, 구조 변경이 필요한 항목. 오케스트레이터 안정화 이후 검토.

## B1. producer 계약이 실행 메타를 반환하지 못함

1. 현상: orchestrator의 producer 계약은 `producer(inputs) -> body`다. 실제 에이전트가 쓴 model_id, input_tokens, output_tokens, cost_usd를 runs에 실을 경로가 없다.
2. 현재 회피: runs에 고정 문자열(mock-deterministic-1)을 기록 중.
3. 필요한 변경: 계약을 `producer(inputs) -> (body, run_meta)`로 확장하고 orchestrator.run_node가 run_meta를 runs에 반영.
4. 영향: orchestrator.run_node, 모든 에이전트 producer. 구조 변경이라 backlog.
5. 연관: DDL v2의 Agent Version Metadata, Cost Tracking 컬럼은 이미 존재. 채울 경로만 없음.

## B2. 검증 방식 Pydantic 공통 모듈로 통일

1. 현상: Backend Agent만 Pydantic 모델·field_validator로 응답을 구조화·검증한다. 나머지 에이전트(strategy/ux/security/design_system/features/wireframe)는 validate() 안의 if문으로 제약을 강제한다.
2. 현재 회피: 에이전트별로 검증 방식이 다름(backend=Pydantic, 그 외=if문). 동작은 동일하게 제약을 강제하고 producer 반환은 모두 dict로 일관.
3. 필요한 변경: 공통 Pydantic 모델/검증 모듈을 만들어 전 에이전트의 validate를 통일. 각 에이전트 body 스키마를 모델로 정의하고 producer는 model_dump()로 dict 반환.
4. 영향: 전 에이전트의 validate/produce. 구조 변경이라 backlog. 지금은 건드리지 않는다.

## B3. 외부 공개(exposure=public) endpoint의 인증·rate limit

1. 현상: Backend Agent의 endpoint에 exposure 필드(internal|public)를 추가했으나 현재 전부 internal이다. 외부 공개용 endpoint(exposure=public)는 아직 없다.
2. 현재 회피: 모든 endpoint exposure=internal. 외부 공개 정책 미정의.
3. 필요한 변경: exposure=public endpoint 도입 시 외부 인증(API key/OAuth 등)과 rate limit 정책을 엔드포인트 계약에 추가해야 한다. 어떤 endpoint를 public으로 노출할지 판단과 정책 모델링이 선행.
4. 영향: backend.py 계약(엔드포인트 계약에 인증/rate limit 필드), 보안 통제 매핑. 정책·구조 변경이라 backlog. 지금은 건드리지 않는다.

## B4. 게이트 결과의 orchestrator 훅 연결 + FAIL 시 되돌림(Performance Outcomes)

1. 현상: Test/Review 게이트(agents/gate_test.py, gate_review.py)는 producer 완료 후 명시적으로 호출하는 독립 검사기다. PASS/WARN/FAIL과 사유만 반환하고, orchestrator와 자동 연결되지 않는다.
2. 현재 회피: 게이트는 검사만 한다. FAIL이어도 재생성 루프·agent 재실행·workflow 재시도를 하지 않고 사유만 보고한다(설계 동결 준수).
3. 필요한 변경: 게이트 결과를 orchestrator 훅으로 자동 연결하고, FAIL 시 해당 노드를 되돌리거나(rollback) 재실행 정책에 태우는 Performance Outcomes 흐름. on_upstream_change/gate와 별개 축인지 결정 필요.
4. 영향: orchestrator.py(결정 루프·상태 전이), workflow 노드 정의. 구조·정책 변경이라 backlog. 지금은 건드리지 않는다.

## B5. Review Gate의 파이프라인 교차(전파) 검사

1. 현상: frontend는 상위(wireframe/design_system/backend)의 open_questions가 자기 산출에 영향을 줄 때 open_questions로 전파하고, 입력 부족 미구현은 explicit_not_implemented로 기록한다. 그러나 게이트(gate_review)는 단일 산출물의 자기 계약만 검사하고, 전파가 제대로 됐는지(상위 open_question이 하위로 이어졌는지)는 검사하지 않는다.
2. 현재 회피: 전파는 각 에이전트(현재 frontend)가 자체적으로 기록. 게이트는 교차 검사를 하지 않는다.
3. 필요한 변경: Review Gate가 파이프라인 교차 검사를 하도록 확장. 상위 open_question의 하위 전파 여부 점검, Silent Omission 탐지(입력 부족 항목이 open_questions/explicit_not_implemented 어디에도 없으면 누락), Open Question 전파 누락 시 FAIL. 게이트가 단일 record가 아니라 상·하위 record를 함께 받는 구조 확장 필요.
4. 영향: gate_review.py 시그니처(다중 record 입력), 게이트 호출부. 구조 확장이라 backlog. 지금은 건드리지 않는다.
