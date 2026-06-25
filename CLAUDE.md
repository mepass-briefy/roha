# 하네스 구현 온보딩 (Claude Code 새 대화용)

이 문서를 새 대화 첫 메시지로 붙인다. 첨부한 harness-ddl-v2.md와 함께 읽는다.

## 1. 무엇을 만드는가

AI 에이전트 기반 서비스 생성 플랫폼(Agent Platform)의 하네스. 사이트 성격과 요구사항을 입력하면, 에이전트들이 전략 → 정의 → 와이어프레임 → 프로토타입 → 구축을 단계별 사람 게이트와 함께 진행한다. 최종 목표는 셀프서비스 제품(B)이며, 지금은 파일 기반(A)으로 메커니즘을 검증한 뒤 그 위에 B를 얹는다.

## 2. 작업 원칙 (반드시 준수)

1. 설계는 동결됐다. 새로운 정책이나 구조 개선을 제안하지 않는다.
2. 현재 구조 위에서만 구현한다.
3. 발견한 문제는 TODO.md에 기록한다. 즉시 고치지 않는다.
4. 구조 변경이 필요하면 즉시 수정하지 말고 BACKLOG.md에 적재한다.
5. 목표는 플랫폼 설계가 아니라 End-to-End 서비스 생성 파이프라인 검증이다.
6. 출력 형식: em dash(—) 사용 금지. 구조 표현은 제목, 번호 목록, 표만 사용(불릿보다 번호 목록 선호).

## 2b. Protected Files (수정 금지)

다음 파일은 구조 검증 완료 상태다. 버그 수정 외 구조 변경 금지.

1. orchestrator.py (저장 계층 Store, 결정 루프, 상태 머신, Event Log, Append-Only Version Store가 모두 이 파일에 있음)

규칙

1. 위 파일은 리팩토링하지 않는다. UX Agent 등 새 producer를 만들다가 오케스트레이터를 다시 뜯지 않는다.
2. 구조 변경이 필요하면 BACKLOG.md에 기록하고 사용자 승인을 기다린다. 임의로 분리·재작성하지 않는다.
3. 새 에이전트는 orchestrator를 수정하지 않고 producer 계약(5절)으로만 결합한다.

## 3. 확정된 설계 (사실로 간주. 재논의 금지)

### 3.1 3층 아키텍처

1. Spec Record 층: 콘텐츠 SSOT. 콘텐츠 생명주기 상태(status).
2. Run 층: 실행 인스턴스. 실행 생명주기 상태(run_status). 콘텐츠 상태와 다른 축.
3. Workflow 층: DAG 정의(템플릿). 버전 관리되는 설정.

### 3.2 두 불변 로그 + 가변 투영

1. record_versions(불변 콘텐츠), events(불변 이벤트)가 진실.
2. records(head), record_validations는 위에서 재구성 가능한 현재 상태 투영.

### 3.3 식별자 3종

1. 내부 PK = bigint/snowflake. 모든 FK는 PK 참조. 외부 비노출.
2. Business Key = 사람이 읽는 ID. 형식 ROHA0001(접두 4 대문자 고정 + 4자리 순번, 0001부터 +1, 9999 초과 시 접두 base-26 올림 ROHA9999→ROHB0001). 검색·운영용. UI에 노출되는 프로젝트 ID는 이 키다.
3. Public Key = 10~12자 난수. API·URL 경로 전송용. lazy 생성, 불변. PK와 규칙적 연관 없음. 화면에 프로젝트 ID로 표시하지 않는다(fetch 경로에만 사용).

### 3.4 provenance와 validation 분리 (핵심)

1. derived_from(record_versions, 불변) = 이 내용을 만든 정확한 입력 버전. 재현용.
2. validation(record_validations, 가변) = 이 내용이 상위 어느 버전까지 무영향 검증됐는가. stale 판정용.

### 3.5 콘텐츠 상태 머신

상태: draft, in_review, confirmed, rejected, stale. stale은 confirmed 집합에서 제외된 별도 상태.

### 3.6 핵심 동작 규칙

1. 버전 핀: derived_from, input_refs는 {ref, version}으로 고정.
2. version 증가는 저장 계층이 canonical body 비교로 판정. 의미 변경에만 +1. 단순 승인·재저장은 유지.
3. No Impact: 재실행 산출이 동일하면 새 버전 미생성, validation만 전진, stale 해제, rerun_no_impact 이벤트 기록, 하위 전파 없음.
4. stuck stale 방지: 동일 산출이어도 validation 전진과 stale 해제는 항상 수행.
5. 전파 트리거: confirmed 전이 + version 증가 동시 충족. 캐스케이드는 한 홉씩.
6. gate(승인 정책)와 on_upstream_change(재생성 정책)는 독립 2축. gate=auto는 결정적 노드에만.

### 3.7 전 에이전트 공통 제약

1. No-Fabrication: 실데이터 없이 경쟁사·수치 생성 금지. 근거 없으면 데이터 없음으로 표기.
2. 추론 층 분리: 문제 정의·핵심 요구는 추론 0%. 보완·세부만 허용. 판별: 그 추론을 빼면 무엇을 만드나가 바뀌면 금지.
3. 추론 표기 의무: provenance에 fact/inference/human 표기.

## 4. 현재 구현 상태 (이미 한 것을 다시 만들지 않는다)

### 완료

1. Orchestrator Skeleton (orchestrator.py: 저장 계층 + 결정 루프 + 상태 머신)
2. Event Log (orchestrator.py 내 events.jsonl append-only)
3. Append-Only Version Store (orchestrator.py 내 record_versions + head)
4. Strategy Agent (agents/agent_strategy.md + agents/strategy.py, E2E 검증 완료)
5. Validation / No Impact 검증 (demo.py, demo_strategy.py)

### 미완료

1. UX Agent
2. Security Agent
3. Design System Agent
4. Features Agent
5. Wireframe Agent
6. Frontend Agent
7. Backend Agent
8. Mobile Agent
9. Test Agent
10. Review Agent

주의: 위 완료 항목은 단일 파일 orchestrator.py 안에 모두 들어 있다. event_store.py, append_only_store.py 같은 분리 파일은 존재하지 않는다. 분리는 구조 변경이므로 BACKLOG 대상이다.

## 4b. 검증 완료 범위 (다시 만들 필요 없음)

DAG 노드 실행, Human Gate 승인, Stale 전파, Auto Rerun, No Impact 처리, Validation 전진, Append-Only Provenance. 파일 기반 스켈레톤(orchestrator.py)으로 검증 완료.

## 5. 계약 (구현 시 지킬 인터페이스)

1. 에이전트 = producer. 시그니처: `producer(inputs: dict) -> body: dict`.
2. 에이전트는 body만 반환. 버전·derived_from·status·provenance 저장은 orchestrator 책임.
3. 모델 호출은 `llm(system, user) -> str` 인터페이스로 분리. real 모드(web_search 가능)와 offline 모드(결정적) 둘 다 지원.
4. 알려진 한계(BACKLOG B1): producer가 body만 반환해 model_id·tokens·cost를 runs에 실을 경로 없음. 구조 변경이라 backlog. 지금은 건드리지 않는다.

## 6. 우선순위 (이 순서로 구현)

1. Strategy Agent (구현·검증 완료)
2. UX Agent
3. Security Agent
4. Design System Agent
5. Features Agent

UX, Security, Design System은 스킬 성격이다. 정의 단계에서 1회 산출(producer)되고, 이후 Features와 Wireframe이 참조한다. 산출 자체는 다른 노드와 같은 producer 패턴.

## 7. 에이전트 구현 표준 형태 (Strategy 기준)

각 에이전트는 두 파일로 만든다.

1. agents/agent_<name>.md: 시스템 프롬프트, 입출력 계약, 절차, 제약. Claude Code 서브에이전트 프롬프트로도 재사용.
2. agents/<name>.py: producer 어댑터. build_user_prompt, validate(제약 코드 강제), offline_llm(결정적), produce(inputs, llm), make_producer(llm).

검증은 agents/demo_<name>.py로 intake부터 해당 노드까지 돌려 계약 준수와 제약 강제를 확인한다.

## 8. 첫 작업 지시

harness-ddl-v2.md를 읽고 3절과 일치하는지 확인한다. 그다음 우선순위 2번 UX Agent를 7절 표준 형태로 구현한다. 새 설계 제안 없이, 발견 문제는 TODO/BACKLOG에 기록하며 진행한다.
