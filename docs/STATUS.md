# 진행 상태 (STATUS)

하네스 구현 진행 상태 정리 문서다. 정리용이며 구현·정책을 바꾸지 않는다. 설계는 CLAUDE.md와 docs/harness-ddl-v2.md를 따른다. 아래 내용은 실측(파일 존재·git log·demo 실행) 기반이다.

## 1. 완료된 에이전트·게이트

각 에이전트는 표준 형태(agent_*.md + *.py + demo_*.py) 3파일이 존재하며, demo는 PYTHONUTF8 없이 exit 0으로 검증됐다. producer 반환은 모두 dict이고 orchestrator canonical 비교(No Impact)와 호환된다. orchestrator.py는 인코딩 버그 수정 외 변경하지 않았다.

### 1.1 정의 단계 (6종)

| 에이전트 | 입력 | 산출 | 도입 커밋 |
|---|---|---|---|
| strategy | intake | competitors/market_gaps/options | 0cd8e10 (41b85e8 인코딩) |
| ux | intake, strategy | primary_tasks/user_flows/IA | 8d5efcb (41b85e8) |
| security | intake | security_requirements/data_classification/threat_model | b3aefa4 |
| design_system | intake, strategy, ux | Material 3 tonal(color/surface/semantic/component/governance) + tokens traceability | 98856b7, 재정의 a9cf47a |
| features | intake, strategy, ux, security | features(+acceptance, security_controls 매핑) | 8b2230f |
| wireframe | ux, design_system, features | screens/sections/navigation | 46a8e3c |

### 1.2 구축 단계 (3종)

| 에이전트 | 입력 | 산출 | 도입 커밋 |
|---|---|---|---|
| backend | features, security | api_spec(endpoints) + artifact(route stub) | bfaa22b (exposure 29c9858, requirements 1766854) |
| frontend | wireframe, design_system, backend | screens + artifact + open_question 전파 | c418f77 (전파 2316fc4) |
| mobile | wireframe, design_system, backend | screens + 모바일 요소(터치/다크/safe area) + artifact | 61418df |

backend/frontend/mobile은 Pydantic으로 응답을 구조화·검증한다. 나머지는 validate()의 if문으로 계약을 강제한다(BACKLOG B2).

### 1.3 게이트 (2종)

| 게이트 | 성격 | 도입 커밋 |
|---|---|---|
| gate_test | '도는가'(dict 구조, Pydantic 검증, artifact 파일 존재, demo exit code) | 9df55ec |
| gate_review | '계약을 지켰는가'(각 에이전트 validate()/모델 계약) + design_system 토큰 traceability 검사 | 9df55ec, traceability 78308fe·3f6f451 |

gate_review의 design_system traceability 검사: 모든 토큰 token_key/value/origin 존재, reference-* origin은 source_reference_id 존재, baseline origin은 source 없음. 위반 시 FAIL + 토큰 명시. 단일 산출물 범위이며 frontend·mobile 전파 교차검사는 하지 않는다(B5).

게이트는 producer가 아니라 검사기다. workflow 노드로 등록하지 않으며, producer 완료 후 명시적으로 호출한다. 등급은 PASS/WARN/FAIL 3단계, FAIL이어도 재생성 루프를 돌리지 않는다.

### 1.4 워크플로 버전

v1(strategy/policy 검증) ~ v9(mobile 포함). 기존 버전·데모를 수정하지 않고 새 버전을 추가하는 방식으로 노드를 결합했다.

## 2. 현재 전파 상태

design_system 재정의(a9cf47a)로 산출 구조가 바뀌었다(color_tokens/component_specs 평면 구조 -> Material 3 레이어 + tokens 단위 traceability). 이로 인해 design_system을 입력으로 받는 frontend·mobile은 현재 stale 상태다.

1. 정상이며 의도된 결과다. design_system만 닫고 전파된 stale은 그대로 둔다.
2. 미해소다. frontend·mobile이 새 design_system 구조(tokens/foundation)를 읽도록 갱신·재실행해야 해소된다.
3. 게이트 demo(demo_gate)는 이 stale을 반영해, frontend가 빈 산출이면 frontend 위반 주입을 스킵하도록 가드돼 있다.

## 3. real 모드 전환 현황

모든 에이전트는 모델 호출을 `llm(...) -> str` 인터페이스로 분리해 두었고, 교체 지점은 각 에이전트 make_producer(llm=...)이며 구조 변경 없이 클로저 주입으로 처리된다.

### 3.1 strategy: real LLM + web_search 완료 (커밋 ba3b8c8)

1. real_llm이 Anthropic messages API + server-side web_search 도구로 동작한다(mock 모드는 그대로 유지, STRATEGY_MODE 또는 make_producer(llm)로 선택).
2. 실측: 검색 결과 기반으로 경쟁사가 실제로 정확하다(플랩풋볼 plabfootball.com / 아이엠그라운드 iamground.kr / 어반풋볼). 검색 없을 때의 환각(PLAB을 의류로 오인 등)이 해소됐다.
3. provenance.competitors=fact + source_url 보유 -> validate 통과(real demo exit 0). 검색으로 확인 못 한 항목은 open_questions로 분리.
4. BACKLOG B6의 strategy 해당분은 해소됐다. 다른 에이전트로의 web_search 확장은 B6에 남는다.

### 3.2 나머지 8개 에이전트: 여전히 offline Mock

ux, security, design_system, features, wireframe, backend, frontend, mobile은 아직 offline 결정적 Mock이다(외부 web 호출 없음, 산출 재현 가능). real 전환 대기 상태다. real 전환 시 채워질 부분

1. features: 핵심 기능에서 세부 기능으로 펼침(현재는 ux 태스크 1:1 + 와우포인트 보완).
2. design_system: 도메인 시드 도출(strategy.positioning 도메인 식별 -> 한국 상위 서비스 주색 web_search 분석). 현재는 reference token 즉시 적용 + Material baseline fallback, image/url은 open_questions.
3. backend: POST 요청 본문 필드 등 도메인 스키마(현재 open_questions).

### 3.3 검증된 real 전환 패턴 (다른 에이전트 전환 시 적용)

strategy에서 검증된 패턴이다. 다른 에이전트 real 전환 시 이 형태를 따른다.

1. real_llm = Anthropic messages API 호출(키는 ANTHROPIC_API_KEY 환경변수, 코드에 박지 않음). 실패는 mock 폴백 없이 RuntimeError로 드러냄.
2. server-side web_search 도구 연결(type "web_search_20250305", max_uses 제한).
3. real 모드 지시: "검색 결과에 없는 회사·수치·URL은 생성 금지(No-Fabrication), 확인 못 한 항목은 open_questions에 기록".
4. provenance 값은 정확히 한 단어("fact"/"inference"/"human"). 설명 텍스트를 붙이지 않는다(validate가 정확 일치를 요구).
5. fact 항목(경쟁사·수치)은 검색 출처(URL)를 둔다. mock 모드는 그대로 유지(make_producer(llm=...)로 선택).

## 4. BACKLOG 현황 (B1~B6)

| 번호 | 내용 요약 | 성격 |
|---|---|---|
| B1 | producer 계약이 실행 메타(model_id/tokens/cost)를 runs에 싣지 못함. 계약을 producer(inputs)->(body, run_meta)로 확장 필요 | 계약 확장 |
| B2 | 검증 방식 Pydantic 공통 모듈로 통일. 현재 backend/frontend/mobile만 Pydantic, 나머지는 if문 | 구조 변경 |
| B3 | 외부 공개(exposure=public) endpoint의 인증·rate limit. 현재 endpoint는 전부 internal | 정책·구조 변경 |
| B4 | 게이트 결과의 orchestrator 훅 연결 + FAIL 시 되돌림(Performance Outcomes) | 구조·정책 변경 |
| B5 | Review Gate의 파이프라인 교차(전파) 검사. 상위 open_question 하위 전파 여부, Silent Omission 탐지, 전파 누락 시 FAIL. 게이트가 다중 record를 받는 구조 확장 | 구조 확장 |
| B6 | real 모드 web_search 도구 연결. strategy 해당분 해소(커밋 ba3b8c8). 나머지 에이전트(특히 design_system 도메인 시드, features 펼침)로의 확장은 남음 | real 전환 |

추가 보류: design_system real 모드 도메인 시드 도출과 image/url 분석(B 트랙·real LLM 선행).

## 4b. DB 전환 현황 (B 트랙 1단계)

파일 기반 SSOT를 Neon Postgres로 옮기는 1단계가 진행됐다. orchestrator.py는 수정하지 않았다.

### 4b.1 완료

1. Neon에 DDL v2 적용(커밋 5fe41d6): 8개 테이블(projects/workflows/records/record_versions/record_validations/runs/events/artifacts) + 인덱스 + RLS 생성. db/schema.sql(idempotent), db/setup_db.py(.env의 DATABASE_URL).
2. PgStore(커밋 94d8d30): orchestrator.Store와 동일한 공개 메서드 10종을 Neon으로 구현(db/pg_store.py). orchestrator·에이전트·게이트 무수정, Store 인터페이스로만 결합.
3. 5개 테이블 매핑·실측: records/record_versions/record_validations/runs/events. STORE=db로 strategy mock 실행 시 Neon에 실제 적재 확인(provenance.competitors=fact 등).
4. 스위치: 호출부(db/demo_pg.py)에서 STORE=db면 PgStore, 아니면 기존 파일 Store(보존).

### 4b.2 미완

1. projects/workflows: FK를 위한 최소 row만 생성한다(실제 프로젝트·워크플로 관리 로직 아님).
2. artifacts: 적재 범위 밖(BACKLOG). 현재는 에이전트가 파일 경로 메타만 record_versions.artifact_refs에 남긴다.
3. runs 일부 컬럼(input_signature_hash는 계산으로 채우나 model_id/tokens/cost는 producer가 실어주지 못함) 미충족 — BACKLOG B1과 연결.

### 4b.3 운영 주의 (RLS)

1. RLS 정책은 8개 중 테넌트 6개 테이블에 ENABLE + FORCE 설정돼 있다.
2. 격리는 BYPASSRLS가 없는 role로 연결할 때만 강제된다. Neon 기본 owner(neondb_owner)는 BYPASSRLS=True라 owner 연결은 RLS를 우회한다(정상 Postgres 동작).
3. 실측: non-bypassrls role 기준으로 다른 테넌트 컨텍스트에서 0행, 자기 테넌트에서 정상 조회(격리 작동 확인).
4. 운영 앱은 BYPASSRLS 없는 전용 role로 연결해야 한다.

## 5. open_questions 현황 (성격별 분류)

각 산출의 open_questions는 무시·생략 없이 기록된다. frontend/mobile은 상위 전파분과 explicit_not_implemented까지 포함한다.

### 5.1 입력 부족으로 못 정한 것

1. design_system: 브랜드 reference 미제공 시 baseline 세트(Material seed + Pretendard + Tabler) 사용 중 기록. token 제공 색이 WCAG AA 미달이면 적용하되 경고.
2. backend: POST 요청 본문 필드 미정(도메인 입력 필요).
3. mobile: safe-area 근거가 design_system/wireframe에 없으면 미적용.

### 5.2 근거 없어 발명 안 한 것 (No-Fabrication 우선)

1. backend: 409 중복 등 도메인 특수 case 근거 없음. 표준 case만 생성.
2. frontend/mobile: loading/empty 상태 근거가 wireframe/backend에 없음. 미구현(success/error는 outcome_mapping).
3. design_system: image/url reference는 offline 분석 불가. real 모드 필요.

### 5.3 현재 구조 한계로 보류한 것

1. wireframe: 보완 기능(와우포인트, origin=inference)은 단일 화면 IA에 배치 대상 아님.
2. frontend/mobile: 위 미배치 보완 기능은 explicit_not_implemented로 명시.
3. 단일 화면 구조라 navigation(데스크톱 사이드바 / 모바일 bottom nav) 미적용. 다중 화면 전환 시 적용.
4. design_system: pattern·motion 레이어는 근거 없음으로 보류(자리만).

## 6. 알려진 배포 한계 (무료 플랜 기준)

1. Vercel 무료(Hobby) 플랜은 함수 실행 기본 10초, Fluid Compute로 최대 1분이다. 하네스 전체 파이프라인(정의 6 + 구축 3 + 게이트)을 한 요청에서 동기 실행하는 것은 불가하다.
2. Vercel 무료에는 UI와 짧은 API만 적합하다. 하네스 실행은 로컬 또는 별도 잡러너 + 비동기(큐·폴링·웹훅)로 돌려야 한다.
3. 현재는 로컬 실행 단계이므로 이 한계는 B 트랙(API + 서버 + UI)에서만 해당한다.

## 7. 다음 후보 단계

1. DB 적재 완성: 나머지 3개 테이블(artifacts 적재, projects/workflows 실제 관리)을 PgStore/호출부에 채워 8개 테이블을 모두 사용한다. runs 실행 메타는 B1과 함께.
2. API 계층: 단일 노드 트리거·상태 조회 등 짧은 API를 PgStore 위에 올린다(6절 배포 한계 고려, 오케스트레이션 본체는 비동기 서버/잡러너).
3. UI 연결: 진행 상태·게이트 승인·산출 열람 UI를 API에 연결(B 트랙).
4. 로컬 real LLM 전환: strategy 외 에이전트로 real_llm 확장(B6), BACKLOG B1 실행 메타 경로 검토.
5. frontend·mobile stale 해소: 새 design_system 구조(tokens/foundation)를 읽도록 갱신·재실행 후 게이트 B5로 토큰 역추적 보존 확인.
