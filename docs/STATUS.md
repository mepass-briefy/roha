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

### 3.2 features: real LLM + 4분류 태깅 + web_search ON/OFF 완료 (커밋 e552d2b)

1. real_llm(strategy 패턴 재사용): Anthropic messages API, 키는 .env(load_dotenv). mock 유지, FEATURES_MODE로 선택.
2. 4분류 태깅: Explicit=fact / Derived=inference / Operational=inference(operational) / Business=open_question(자동 채택 금지). validate가 category·origin·source 정합 강제.
3. web_search ON/OFF(FEATURES_SEARCH): ON이면 strategy 경쟁사의 '기능'만 조사 -> Competitive Reference(fact + 출처 URL). "경쟁사에 있으니 우리도"는 자동 채택 금지 -> Business로 open_questions 분리. 검색에 없는 건 생성 금지.
4. 게이트(gate_review)에 features 검사 추가(4분류 태깅/Business 자동채택 금지/Fabrication). 음성 테스트 통과.
5. 실측: mock exit 0 / real off(Explicit 3·Derived 2·Business 4건 open_questions) / real on(Competitive 6건 fact+실URL·채택 Business 6건 open_questions). 위장·자동채택 없음.

### 3.3 나머지 7개 에이전트: 여전히 offline Mock

ux, security, design_system, wireframe, backend, frontend, mobile은 아직 offline 결정적 Mock이다(외부 web 호출 없음, 산출 재현 가능). real 전환 대기. real 전환 시 채워질 부분

1. design_system: 도메인 시드 도출(strategy.positioning 도메인 식별 -> 한국 상위 서비스 주색 web_search 분석). 현재는 reference token 즉시 적용 + Material baseline fallback, image/url은 open_questions.
2. backend: POST 요청 본문 필드 등 도메인 스키마(현재 open_questions).

real 완료: strategy(real+검색), features(real+ON/OFF 검색).

### 3.4 검증된 real 전환 패턴 (다른 에이전트 전환 시 적용)

strategy·features에서 검증된 패턴이다. 다른 에이전트 real 전환 시 이 형태를 따른다.

1. real_llm = Anthropic messages API 호출(키는 ANTHROPIC_API_KEY 환경변수, 코드에 박지 않음). 실패는 mock 폴백 없이 RuntimeError로 드러냄.
2. server-side web_search 도구 연결(type "web_search_20250305", max_uses 제한).
3. real 모드 지시: "검색 결과에 없는 회사·수치·URL은 생성 금지(No-Fabrication), 확인 못 한 항목은 open_questions에 기록".
4. provenance 값은 정확히 한 단어("fact"/"inference"/"human"). 설명 텍스트를 붙이지 않는다(validate가 정확 일치를 요구).
5. fact 항목(경쟁사·수치)은 검색 출처(URL)를 둔다. mock 모드는 그대로 유지(make_producer(llm=...)로 선택).

## 4. BACKLOG 현황 (B1~B7)

| 번호 | 내용 요약 | 성격 |
|---|---|---|
| B1 | producer 계약이 실행 메타(model_id/tokens/cost)를 runs에 싣지 못함. 계약을 producer(inputs)->(body, run_meta)로 확장 필요 | 계약 확장 |
| B2 | 검증 방식 Pydantic 공통 모듈로 통일. 현재 backend/frontend/mobile만 Pydantic, 나머지는 if문 | 구조 변경 |
| B3 | 외부 공개(exposure=public) endpoint의 인증·rate limit. 현재 endpoint는 전부 internal | 정책·구조 변경 |
| B4 | 게이트 결과의 orchestrator 훅 연결 + FAIL 시 되돌림(Performance Outcomes) | 구조·정책 변경 |
| B5 | Review Gate의 파이프라인 교차(전파) 검사. 상위 open_question 하위 전파 여부, Silent Omission 탐지, 전파 누락 시 FAIL. 게이트가 다중 record를 받는 구조 확장 | 구조 확장 |
| B6 | real 모드 web_search 도구 연결. strategy·features 해소. 나머지 에이전트(design_system 도메인 시드 등)로의 확장은 남음 | real 전환 |
| B7 | strategy real이 입력 도메인을 web_search에 안정적으로 고정하지 못함(풋살 입력을 코딩 교육으로 오인하는 비결정성 관찰). 시스템 프롬프트에 도메인 고정 강화 필요. Goal(goal_analysis) 연결로 완화되는지 먼저 관찰 후 대응 | real 품질 |

추가 보류: design_system real 모드 도메인 시드 도출과 image/url 분석(B 트랙·real LLM 선행).

## 4b. DB 전환 현황 (B 트랙 1단계 완료)

파일 기반 SSOT를 Neon Postgres로 옮기는 1단계가 완료됐다. orchestrator.py는 수정하지 않았다(Store 인터페이스로만 결합).

### 4b.1 완료

1. Neon에 DDL v2 적용(커밋 5fe41d6): 8개 테이블 + 인덱스 + RLS. db/schema.sql(idempotent), db/setup_db.py(.env의 DATABASE_URL).
2. PgStore(커밋 94d8d30): orchestrator.Store와 동일한 공개 메서드 10종을 Neon으로 구현(db/pg_store.py). 스위치는 호출부(db/demo_pg.py) STORE=db / 파일.
3. DB 전환 완성(커밋 bd86f5c): 8개 테이블 전부 PgStore 경로로 적재.
   - records / record_versions / record_validations / runs / events: 직결.
   - artifacts: append_version이 body.artifact_refs(backend/frontend/mobile 산출)를 적재(경로·mime·checksum·size, 중복 checksum 무시).
   - projects: 식별자 3종 충족 — PK(내부) / business_key(PROJ-*) / public_key(난수 12자·외부·불변).
   - workflows: 외부 workflow JSON을 노드·버전 포함 적재.
   - runs 보정: produced_by_run으로 output_record_pk/output_version 채움.
4. 실측(STORE=db): 8개 테이블 적재 확인. 파일 모드(STORE 미설정)·DB 모드 멱등 재실행 모두 exit 0.

### 4b.2 남은 부분

1. runs의 model_id/tokens/cost는 producer가 실어주지 못해 비어 있다 — BACKLOG B1과 연결.
2. artifacts는 경로·메타 중심이며 실제 바이너리 저장은 범위 밖(오브젝트 스토리지 단계).

### 4b.3 운영 주의 (RLS)

1. RLS는 테넌트 6개 테이블에 ENABLE + FORCE.
2. 격리는 BYPASSRLS가 없는 role로 연결할 때만 강제된다. Neon 기본 owner(neondb_owner)는 BYPASSRLS=True라 owner 연결은 우회한다(정상 Postgres 동작).
3. 운영용 non-bypassrls role harness_app을 생성했다(db/create_app_role.sql). 실측: harness_app 기준으로 다른 테넌트 컨텍스트 0행, 자기 테넌트 정상 조회(격리 작동).
4. API 단계에서 앱을 이 harness_app role(BYPASSRLS 없음)로 연결할 예정이다. 비밀번호·LOGIN은 배포 시 설정.

## 4c. 로컬 API 서버 (B 트랙, 커밋 6eb2321)

FastAPI로 게이트 단위 실행 API를 올렸다. orchestrator/에이전트/게이트/run_harness 로직은 호출만 한다(무수정, run_harness.build_producers 재사용).

1. 엔드포인트 5종: POST /projects(요구->public_key), POST /projects/{public_key}/run(한 칸=다음 READY 노드 동기 실행+게이트 결과), GET /status, GET /records, POST /approve.
2. 게이트가 요청 경계: run은 한 단계만 동기 실행하고 반환(백그라운드·폴링 없음). human 게이트에서 멈추고 approve로 진행. 게이트 결과는 events(gate_result)로 DB 기록.
3. STORE=db 기본(.env). real/mock은 환경변수. 식별자 3종: 외부는 public_key만, 내부 PK 비노출(records 응답 type/status/version/body만, 실측 확인).
4. 실측: mock 플로우(projects->run->status->approve->run->records), real strategy를 API 경로로 1단계 실행 -> Neon 적재 -> API records 읽기 확인.

## 4d. Goal 도입 + Goal Analysis 에이전트 (커밋 507c6eb)

파이프라인 맨 앞에 Goal을 추가하고 Goal Analysis 에이전트를 신규로 만들었다.

1. intake에 goal{statement(필수), details(선택)} 선택 필드 추가(하위호환). Goal 없으면 기존 에이전트 정상 동작(Goal 무시), goal_analysis만 사용.
2. goal_analysis(real): Goal을 확정이 아니라 해석·가설 제안. 산출 inferred_dimensions/candidate_metrics/assumptions/open_questions가 전부 provenance=inference. 검색 없음(목표 해석은 추론). GOAL_MODE=real|mock.
3. 실측: 막연한 Goal("동네 풋살 모임 활성화", details 비움)을 단정 없이 해석(4차원·5지표·confidence·6 open_questions). 게이트 TEST/REVIEW WARN.
4. workflow v10: goal_analysis를 intake 다음·strategy 앞에 추가(depends_on intake). gate_review에 goal_analysis 매핑 추가(검사기 확장).

### 4d.1 미연결 (의도된 보류)

strategy가 Goal Confirmed를 입력으로 받는 연결은 보류한다. Goal Confirmed는 Workbench에서 사람이 확정해야 생기므로 UI가 선행이다. 순서: Workbench UI -> Goal Confirmed -> strategy 연결.

## 4e. Discovery 단계 설계 확정 (미구현, 다음 작업)

코드는 아직 goal_analysis 상태다. 아래는 확정된 설계이며 다음 작업에서 구현한다.

1. 기존 goal_analysis를 Discovery로 확장·개명 예정.
2. 역할: 고객 언어 -> 시스템 언어 번역. 수행 3가지:
   - Goal Interpretation: 목표 해석(차원·후보지표·assumptions).
   - Requirement Normalization: 요구 -> IT 요구 리스트(real).
   - Open Question Extraction: 불확실한 것 추출.
3. 금지: 새 요구사항 생성 금지, 기능 제안 금지(그건 Features의 Goal-driven), 사업 판단 금지(그건 Business Decision). 전부 inference, 고객 말에 있는 것만.
4. 성공 기준: 좋은 아이디어가 아니라 왜곡 없는 이해.
5. 순서: Intake -> Discovery -> Gate(첫 검토: "AI가 고객 말을 올바르게 이해했나") -> Strategy.

## 4f. Workbench UI 프로토타입 방향 (이 세션 확정, 미구현)

1. 입력 화면: 목표(필수) + 맥락 Context(선택·권장) + 요구사항(선택, 텍스트, CRM은 붙여넣기).
2. Discovery 검토 화면: 최상위 = AI 이해 검토. 전부 추론으로 표시, 확인 필요 항목 분리, 확정 = 첫 게이트(Goal Confirmed + Requirement Confirmed).
3. 기능 정렬 화면: Goal Confirmed 기준. 기능 출처 4분류 표기, Business Decision은 사람 판단, Goal-driven 제안, 목표 커버리지 표시. 원본 불변, 수정은 Working Layer.
4. 디자인: Material 3.

## 4g. 미정·후속 설계

1. intake에 Context(고객·프로덕트 맥락) 추가 필요(미구현): Discovery가 Goal + Context로 해석. Context 없으면 "고객이 누구인지"를 open_question으로.
2. Working Layer 설계 미정: 원본 AI 산출 불변 + 사람 편집을 분리한다. 새 테이블 vs 새 버전(origin=human) 중 택1은 기능 정렬 화면 구현 시 결정.

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

## 7. 1주일 플랜 진행

하네스는 로컬에서 직접 실행한다(폴링·큐 없음). 게이트는 로컬 승인, UI는 조회 중심이다.

| 일차 | 작업 | 상태 |
|---|---|---|
| 1일차 | DB 전환(Neon DDL v2 + PgStore 8테이블 적재) | 완료(bd86f5c) |
| 2일차 | features real 전환 + 로컬 하네스 러너 | 완료(e552d2b, 770b7a2) |
| 3-4일차 | API 계층(FastAPI 5종 엔드포인트, 게이트 단위 실행) | 완료(6eb2321) |
| Goal | Goal 도입 + Goal Analysis 에이전트 | 완료(507c6eb) |
| 설계 | Discovery 단계 + Workbench UI 프로토타입 방향 확정 | 완료(설계만) |
| 다음 | Discovery 확장(goal_analysis -> discovery, Requirement Normalization 추가) | 예정 |
| 5-6일차 | Workbench UI 구현(Material 3) | 예정 |
| 연결 | strategy가 Confirmed(Goal/Requirement)를 입력으로 받게 연결 | 예정 |
| 7일차 | 통합 | 예정 |

설계 메모

1. 하네스 실행은 로컬 직접 실행. 별도 잡러너·폴링·큐를 두지 않는다(6절 배포 한계는 클라우드 동기 실행에만 해당).
2. 게이트(human gate) 승인은 로컬에서 한다. UI는 진행 상태·산출 조회 중심.
3. API는 harness_app(non-bypassrls) role로 DB에 연결해 RLS 격리를 강제한다.

### 후속 잔여(플랜과 별개)

1. 로컬 real LLM 전환: strategy 외 에이전트로 real_llm 확장(B6), BACKLOG B1 실행 메타 경로.
2. frontend·mobile stale 해소: 새 design_system 구조(tokens/foundation) 반영 후 게이트 B5로 토큰 역추적 보존 확인.
