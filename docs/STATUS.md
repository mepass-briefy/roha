# 진행 상태 (STATUS)

하네스 구현 진행 상태 정리 문서다. 이 문서는 정리용이며 구현·정책을 바꾸지 않는다. 설계는 CLAUDE.md와 docs/harness-ddl-v2.md를 따른다.

## 1. 완료된 에이전트·게이트

모든 에이전트는 7절 표준 형태(agent_*.md + *.py + demo_*.py)로 구현됐고, 각 demo는 PYTHONUTF8 없이 exit 0으로 검증됐다. producer 반환은 모두 dict이며 orchestrator의 canonical 비교(No Impact)와 호환된다. orchestrator.py는 인코딩 버그 수정 외 변경하지 않았다.

### 1.1 정의 단계 (6)

| 에이전트 | 입력 | 산출 | 도입 커밋 |
|---|---|---|---|
| strategy | intake | competitors/market_gaps/options 등 | 0cd8e10 (이후 41b85e8 인코딩) |
| ux | intake, strategy | primary_tasks/user_flows/IA | 8d5efcb (이후 41b85e8) |
| security | intake | security_requirements/data_classification/threat_model | b3aefa4 |
| design_system | intake, strategy, ux | color/typography/spacing/component_specs/CSS 변수 | 98856b7 |
| features | intake, strategy, ux, security | features(+acceptance, security_controls 매핑) | 8b2230f |
| wireframe | ux, design_system, features | screens/sections/navigation | 46a8e3c |

### 1.2 구축 단계 (3)

| 에이전트 | 입력 | 산출 | 도입 커밋 |
|---|---|---|---|
| backend | features, security | api_spec(endpoints) + artifact(route stub) | bfaa22b (+ exposure 29c9858, requirements 1766854) |
| frontend | wireframe, design_system, backend | screens(data_calls/outcome_mapping) + artifact | c418f77 (+ 전파 2316fc4) |
| mobile | wireframe, design_system, backend | screens + 모바일 요소(터치/다크/safe area) + artifact | 61418df |

backend/frontend/mobile은 Pydantic으로 응답을 구조화·검증한다. 나머지 에이전트는 validate()의 if문으로 계약을 강제한다(차이는 BACKLOG B2).

### 1.3 게이트 (2)

| 게이트 | 성격 | 도입 커밋 |
|---|---|---|
| gate_test | '도는가'(dict 구조, Pydantic 검증, artifact 파일 존재, demo exit code) | 9df55ec |
| gate_review | '계약을 지켰는가'(각 에이전트 validate()/모델 계약만 재사용) | 9df55ec |

게이트는 producer가 아니라 검사기다. workflow 노드로 등록하지 않으며, producer 완료 후 명시적으로 호출한다. 결과 등급은 PASS/WARN/FAIL 3단계이고, FAIL이어도 재생성 루프를 돌리지 않는다.

### 1.4 워크플로 버전

워크플로는 버전 핀 설정이며 누적으로 추가됐다. v1(strategy/policy 검증) ~ v9(mobile 포함 전체 파이프라인). 기존 버전과 데모는 수정하지 않고 새 버전을 추가하는 방식으로 노드를 결합했다.

## 2. 보류 / BACKLOG

| 번호 | 항목 | 성격 |
|---|---|---|
| B1 | producer 계약이 실행 메타(model_id/tokens/cost)를 runs에 싣지 못함 | 계약 확장(구조 변경) |
| B2 | 검증 방식 Pydantic 공통 모듈로 통일(현재 backend/frontend/mobile만 Pydantic, 나머지는 if문) | 구조 변경 |
| B3 | 외부 공개(exposure=public) endpoint의 인증·rate limit. 현재 endpoint는 전부 internal | 정책·구조 변경 |
| B4 | 게이트 결과의 orchestrator 훅 연결 + FAIL 시 되돌림(Performance Outcomes) | 구조·정책 변경 |
| B5 | Review Gate의 파이프라인 교차(전파) 검사. 상위 open_question 하위 전파 여부, Silent Omission 탐지, 전파 누락 시 FAIL | 구조 확장 |

추가 보류 사항

1. 디자인 시스템 값 확정: 의미색(warning/danger) 등 브랜드 토큰 미제공분은 표준값 제안 + open_questions 상태. 사람 확정 필요.
2. real 모드 전환: 아래 3절.
3. B 트랙(셀프서비스 제품): 현재 A 트랙(파일 기반 메커니즘 검증) 위에 얹는 단계. 메커니즘 검증 완료 후 진행.

## 3. 현재 전부 offline Mock

모든 에이전트는 `llm(system, user) -> str`(또는 backend/frontend/mobile은 `llm(prompt) -> str`) 인터페이스로 모델 호출을 분리해 두었고, 현재 데모는 전부 offline 결정적 Mock으로 동작한다. 외부 web 호출이 없으며 산출은 재현 가능(canonical 동일)하다.

real 모드(web_search 가능한 Claude 서브에이전트)로 llm을 교체하면 채워질 부분

1. strategy: competitors.axes(기능/수익모델/온보딩/불편지점)와 market_gaps를 실데이터로 채움(현재 seed_competitors만, placeholder는 provenance=inference로 정직 표기).
2. design_system: positioning/ux_principles를 반영한 브랜드 톤 구성. 현재는 brand_tokens 입력 + 결정적 파생.
3. backend: POST 요청 본문 필드 등 도메인 스키마(현재 open_questions). 도메인 특수 case(409 등) 근거 판단.
4. frontend/mobile: 실제 화면 코드(현재 artifact는 스텁). loading/empty 등 상태 구현 근거 판단.
5. 교체 지점은 각 에이전트 make_producer(llm=real_llm)이며, 구조 변경 없이 클로저 주입으로 처리된다.

## 4. open_questions 현황 (성격별 분류)

각 에이전트 산출의 open_questions는 무시·생략 없이 기록된다(frontend/mobile은 상위 전파분과 explicit_not_implemented까지 포함). 성격별 분류는 다음과 같다.

### 4.1 입력 부족으로 못 정한 것

1. design_system: 의미색 warning/danger 미제공(brand_tokens에 없음). 표준값 제안 + 확인 필요.
2. backend: POST 요청 본문 필드 미정(applications/reservations/settlements). 도메인 입력 필요.
3. mobile: safe-area 근거가 design_system/wireframe에 없음. 미적용.

### 4.2 근거 없어 발명 안 한 것 (No-Fabrication 우선)

1. backend: 409 중복 등 도메인 특수 case 근거 없음. 표준 case만 생성.
2. frontend/mobile: loading/empty 상태 근거가 wireframe/backend에 없음. 미구현(success/error는 outcome_mapping으로 처리).

### 4.3 현재 구조 한계로 보류한 것

1. wireframe: 보완 기능(strategy 와우포인트, origin=inference)은 단일 화면 IA에 배치 대상 아님.
2. frontend/mobile: 위 미배치 보완 기능은 explicit_not_implemented로 명시(wireframe 미배치로 화면 구현 불가).
3. 단일 화면 구조라 navigation(데스크톱 사이드바 / 모바일 bottom nav)은 미적용. 다중 화면 전환 시 적용.

### 4.4 전파(교차) 관찰

1. backend의 POST 요청 필드·특수 case 미정은 frontend/mobile open_questions로 표면화된다(영향 있는 항목만, 입력 사실 기반).
2. 전파의 게이트 차원 교차 검사는 아직 없다(B5).
