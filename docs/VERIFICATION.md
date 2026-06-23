# 하네스 A 경로 검증 (파일 기반 SSOT)

설계 문서(스키마 v2, 정책 v1.1, DDL v2)를 파일 기반 SSOT 위에서 실제로 구현해 검증한 결과다. DB 없이 파일과 JSONL로 record_versions, events, validations, runs를 흉내 내고, 오케스트레이터의 핵심 메커니즘이 작동하는지 확인했다.

## 구성

| 파일 | 역할 |
|---|---|
| workflow/site-build.v1.json | DAG 정의(intake → strategy → policy) |
| orchestrator.py | 저장 계층 + 오케스트레이터(상태 머신, 버전 핀, No Impact, 전파) |
| demo.py | 검증 시나리오 + mock producer(실제 에이전트 자리) |
| _run/ | 실행 후 생성된 파일 SSOT 상태 |

mock producer는 실제 에이전트가 들어갈 자리다. 여기서 검증하는 것은 에이전트 품질이 아니라 오케스트레이션 메커니즘이다.

## 검증 결과

### P1. 오케스트레이터가 status를 읽고 다음 노드를 고른다

tick() 호출 시 intake가 confirmed이므로 strategy를 READY로 판정해 선택, 이후 strategy가 confirmed되자 policy를 선택. DAG 정의를 데이터로 두고 상태만 보고 진행했다. 통과.

### P2. 사람 게이트가 흐름을 진행시킨다

run 성공 후 gate=human 노드는 in_review로 멈추고, human_confirm 호출 시 confirmed로 전이해 하위가 READY가 됐다. 통과.

### P3. 재실행 + No Impact

strategy를 competitors만 바꿔 재실행 → v2 생성 → 사람 승인 → policy가 strategy@v1에 검증돼 있어 stale 전파 → auto_rerun. policy producer는 positioning만 읽으므로 산출이 동일 → No Impact 처리됐다. 통과.

검증된 No Impact 동작

1. policy body_hash가 v1 생성과 재실행에서 동일(9c4f15a45cdca326).
2. 새 버전 미생성. policy는 v1 유지.
3. validation만 strategy@v2로 전진(pinned=1, validated=2).
4. status stale → confirmed 복귀.
5. events에 rerun_no_impact 기록.
6. policy version 미증가이므로 하위 전파 없음.

### provenance와 validation 분리 (핵심)

policy.v1의 derived_from은 strategy@v1을 불변으로 보존(재현용), validation은 strategy@v2로 전진(stale 판정용). 두 관심사가 파일 레벨에서 분리돼 동작함을 확인했다. Append-Only 전환이 강제한 이 분리가 stuck stale과 No Impact를 동시에 해결한다.

## 이벤트 로그(요약)

전 과정이 events.jsonl에 append-only로 남았다. record_version_created, record_state_changed, run_state_changed, stale_propagated, rerun_no_impact. 이 로그만으로 현재 상태(records, validations)를 재구성할 수 있다.

## 다음 단계

1. mock producer를 실제 에이전트(Claude Code 서브에이전트)로 교체. 첫 대상은 strategy의 ㉡(고유 각도) 인터뷰.
2. 노드 확장(features, ux, security, design_system). 같은 패턴의 반복.
3. 실패·재시도·input_superseded 경로 검증.
4. 운영 데이터가 쌓이면 보류한 12절 항목(canonical 규칙, on_upstream_change 기본값) 조정.
