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
