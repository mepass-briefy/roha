# BACKLOG (구조 변경 필요. 즉시 수정 금지)

현재 구조 위에서 구현 중 발견된, 구조 변경이 필요한 항목. 오케스트레이터 안정화 이후 검토.

## B1. producer 계약이 실행 메타를 반환하지 못함

1. 현상: orchestrator의 producer 계약은 `producer(inputs) -> body`다. 실제 에이전트가 쓴 model_id, input_tokens, output_tokens, cost_usd를 runs에 실을 경로가 없다.
2. 현재 회피: runs에 고정 문자열(mock-deterministic-1)을 기록 중.
3. 필요한 변경: 계약을 `producer(inputs) -> (body, run_meta)`로 확장하고 orchestrator.run_node가 run_meta를 runs에 반영.
4. 영향: orchestrator.run_node, 모든 에이전트 producer. 구조 변경이라 backlog.
5. 연관: DDL v2의 Agent Version Metadata, Cost Tracking 컬럼은 이미 존재. 채울 경로만 없음.
