# 하네스 DB DDL 설계 v2 (PostgreSQL)

DDL v1을 대체한다. Append-Only Version Store, Event Log, Agent Version Metadata, Cost Tracking, Multi-Tenant Boundary, Artifact Registry를 반영한다. 데이터 모델이 우선이며, Append-Only 전환 후 derived_from, stale 전파, No Impact가 어떤 테이블 구조로 구현되는지를 중심으로 설계한다.

## 0. 설계 핵심

### 0.1 두 개의 불변 로그 + 가변 투영

| 구분 | 테이블 | 성격 |
|---|---|---|
| 불변 콘텐츠 로그 | record_versions | 버전별 내용. append만. 재현의 근거 |
| 불변 이벤트 로그 | events | 일어난 모든 사건. append만. 감사의 근거 |
| 가변 현재 투영 | records(head), record_validations | 현재 상태. 위 두 로그에서 재구성 가능 |

records의 head 포인터와 record_validations는 mutable이지만, 둘 다 record_versions와 events에서 재구성 가능한 투영이다. 진실은 두 불변 로그에 있다.

### 0.2 provenance와 validation의 분리 (가장 중요)

Append-Only 전환이 강제하는 개념 분리다.

| 개념 | 저장 위치 | 가변성 | 의미 |
|---|---|---|---|
| derived_from | record_versions | 불변 | 이 내용을 만든 정확한 입력 버전. 재현용 |
| validation | record_validations | 가변 | 이 내용이 상위의 어느 버전까지 무영향 검증됐는가. stale 판정용 |

v1에서는 derived_from 하나가 두 역할을 겸했다. Append-Only에서는 derived_from를 불변으로 두어야 하므로, stale 판정을 위한 가변 정보를 validation으로 분리한다. No Impact 재실행은 새 버전을 만들지 않고 validation만 전진시킨다.

## 1. projects (테넌트 루트)

```sql
CREATE TABLE projects (
  pk             BIGINT PRIMARY KEY,
  business_key   VARCHAR(64)  NOT NULL,
  public_key     VARCHAR(12),
  name           VARCHAR(255) NOT NULL,
  workflow_pk    BIGINT NOT NULL,
  workflow_ver   INT    NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_projects_business_key UNIQUE (business_key),
  CONSTRAINT uq_projects_public_key   UNIQUE (public_key),
  CONSTRAINT fk_projects_workflow FOREIGN KEY (workflow_pk) REFERENCES workflows(pk),
  CONSTRAINT uq_projects_pk_for_fk UNIQUE (pk)   -- 복합 FK 테넌트 가드용
);
```

## 2. workflows (DAG 정의, 전역 템플릿)

테넌트 스코프가 아니다. 프로젝트가 버전 핀으로 참조한다.

```sql
CREATE TABLE workflows (
  pk            BIGINT PRIMARY KEY,
  workflow_key  VARCHAR(64) NOT NULL,
  version       INT NOT NULL,
  status        VARCHAR(16) NOT NULL DEFAULT 'draft',
  nodes         JSONB NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_workflows_key_version UNIQUE (workflow_key, version),
  CONSTRAINT ck_workflows_status CHECK (status IN ('draft','active','deprecated'))
);
CREATE UNIQUE INDEX uq_workflows_one_active
  ON workflows (workflow_key) WHERE status = 'active';
```

## 3. records (head 포인터)

(project, type)당 1행. 현재 버전과 현재 상태를 가리키는 가변 포인터다. 내용은 갖지 않는다.

```sql
CREATE TABLE records (
  pk                  BIGINT PRIMARY KEY,
  project_pk          BIGINT NOT NULL,
  type                VARCHAR(32) NOT NULL,
  business_key        VARCHAR(64),
  public_key          VARCHAR(12),
  current_version     INT NOT NULL DEFAULT 0,
  current_version_pk  BIGINT,                 -- record_versions.pk (현재 버전)
  status              VARCHAR(16) NOT NULL DEFAULT 'draft',
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_records_project FOREIGN KEY (project_pk) REFERENCES projects(pk),
  CONSTRAINT ck_records_status
    CHECK (status IN ('draft','in_review','confirmed','rejected','stale')),
  CONSTRAINT uq_records_project_type UNIQUE (project_pk, type),
  CONSTRAINT uq_records_public_key UNIQUE (public_key),
  CONSTRAINT uq_records_business_key UNIQUE (project_pk, business_key),
  CONSTRAINT uq_records_project_pk UNIQUE (project_pk, pk)  -- 복합 FK 가드
);
CREATE INDEX ix_records_project_status ON records (project_pk, status);
```

status는 head의 현재 상태다. stale은 confirmed와 별개 값으로, confirmed 집합에 포함되지 않는다(정책 2.2).

## 4. record_versions (불변 콘텐츠 로그)

버전마다 1행. UPDATE·DELETE 금지. body, body_hash, derived_from(불변 provenance)를 가진다.

```sql
CREATE TABLE record_versions (
  pk             BIGINT PRIMARY KEY,
  record_pk      BIGINT NOT NULL,            -- head FK
  project_pk     BIGINT NOT NULL,            -- 테넌트 일관성
  version        INT NOT NULL,
  body           JSONB NOT NULL DEFAULT '{}',
  body_hash      VARCHAR(64) NOT NULL,       -- canonical serialization 해시
  derived_from   JSONB NOT NULL DEFAULT '[]',-- [{parent_record_pk, parent_version, parent_version_pk}] 불변
  provenance     JSONB NOT NULL DEFAULT '{}',
  artifact_refs  JSONB NOT NULL DEFAULT '[]',-- [artifact_pk ...] 외부 자산은 여기로만
  produced_by_run BIGINT,                    -- runs.pk
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_rv_record FOREIGN KEY (record_pk) REFERENCES records(pk),
  CONSTRAINT fk_rv_project_record
    FOREIGN KEY (project_pk, record_pk) REFERENCES records(project_pk, pk), -- 테넌트 가드
  CONSTRAINT uq_rv_record_version UNIQUE (record_pk, version),
  CONSTRAINT uq_rv_pk_for_fk UNIQUE (pk)
);
CREATE INDEX ix_rv_record ON record_versions (record_pk);

-- 불변 강제: 애플리케이션 롤에서 UPDATE/DELETE 권한 회수 또는 트리거로 차단
-- REVOKE UPDATE, DELETE ON record_versions FROM app_role;
```

Append-Only의 핵심 효과: derived_from의 parent_version_pk가 record_versions의 불변 행을 직접 가리키므로, 버전 핀이 비로소 옛 버전 내용 복원까지 연결된다. 완전 재현이 가능해진다.

body에 바이너리 적재 금지. 외부 자산은 artifact_refs로만 참조한다(8절).

## 5. record_validations (가변 stale 판정·영향도 투영)

DDL v1의 record_dependencies를 대체한다. 현재 버전의 의존 간선에 "검증된 상위 버전"을 더한 구조다. stale 판정과 영향도 역방향 조회를 모두 담당한다.

```sql
CREATE TABLE record_validations (
  record_version_pk        BIGINT NOT NULL,  -- 하위(현재 버전)
  parent_record_pk         BIGINT NOT NULL,  -- 상위 head
  project_pk               BIGINT NOT NULL,
  parent_version_pinned    INT NOT NULL,     -- 실제 소비한 버전(= derived_from)
  parent_version_validated INT NOT NULL,     -- 무영향 검증된 최신 상위 버전(가변)
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT pk_record_validations PRIMARY KEY (record_version_pk, parent_record_pk),
  CONSTRAINT fk_rval_child FOREIGN KEY (record_version_pk) REFERENCES record_versions(pk),
  CONSTRAINT fk_rval_parent FOREIGN KEY (parent_record_pk) REFERENCES records(pk)
);
-- 영향도 역방향 조회: 특정 상위에 의존하며 아직 검증 안 된 하위
CREATE INDEX ix_rval_parent ON record_validations (parent_record_pk, parent_version_validated);
```

stale 판정: head H의 current_version_pk에 대한 행 중, parent_version_validated < 상위 head.current_version 이고 상위가 confirmed면 H는 stale.

No Impact 처리: parent_version_validated만 전진. 새 버전 생성 없음.

## 6. runs (실행 인스턴스 + Agent Version + Cost)

```sql
CREATE TABLE runs (
  pk                   BIGINT PRIMARY KEY,
  project_pk           BIGINT NOT NULL,
  workflow_pk          BIGINT NOT NULL,
  workflow_ver         INT    NOT NULL,
  node_id              VARCHAR(32) NOT NULL,
  produces_type        VARCHAR(32) NOT NULL,
  input_refs           JSONB NOT NULL DEFAULT '[]',
  input_signature_hash VARCHAR(64) NOT NULL,
  output_record_pk     BIGINT,
  output_version       INT,                  -- 산출 버전(No Impact면 null)
  run_status           VARCHAR(16) NOT NULL DEFAULT 'queued',
  attempt              INT NOT NULL DEFAULT 1,
  error                JSONB,
  cancel_reason        VARCHAR(32),
  -- Agent Version Metadata
  agent_version        VARCHAR(32),
  prompt_version       VARCHAR(32),
  model_id             VARCHAR(64),          -- 정확한 버전 문자열. 별칭 금지
  params               JSONB,
  -- Cost Tracking
  input_tokens         INT,
  output_tokens        INT,
  cost_usd             NUMERIC(12,6),
  started_at           TIMESTAMPTZ,
  ended_at             TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_runs_project FOREIGN KEY (project_pk) REFERENCES projects(pk),
  CONSTRAINT fk_runs_workflow FOREIGN KEY (workflow_pk) REFERENCES workflows(pk),
  CONSTRAINT ck_runs_status
    CHECK (run_status IN ('queued','running','succeeded','failed','cancelled'))
);
CREATE UNIQUE INDEX uq_runs_inflight
  ON runs (project_pk, node_id, input_signature_hash)
  WHERE run_status IN ('queued','running');
CREATE INDEX ix_runs_project_status ON runs (project_pk, run_status);
CREATE INDEX ix_runs_node_cost ON runs (project_pk, node_id);  -- 비용 집계용
```

## 7. events (불변 Event Log)

INSERT 전용. 모든 상태 전이, Run 생명주기, stale 전파, No Impact를 append한다.

```sql
CREATE TABLE events (
  pk             BIGINT PRIMARY KEY,         -- snowflake. 전역 순서
  project_pk     BIGINT NOT NULL,
  event_type     VARCHAR(40) NOT NULL,
  subject_type   VARCHAR(16) NOT NULL,       -- record|run|workflow|artifact
  subject_pk     BIGINT NOT NULL,
  record_pk      BIGINT,
  record_version INT,
  run_pk         BIGINT,
  payload        JSONB NOT NULL DEFAULT '{}',
  actor          JSONB NOT NULL DEFAULT '{}',-- {kind: system|human|agent_run, user_pk?, run_pk?}
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_events_project FOREIGN KEY (project_pk) REFERENCES projects(pk),
  CONSTRAINT ck_events_subject
    CHECK (subject_type IN ('record','run','workflow','artifact'))
);
CREATE INDEX ix_events_project_seq  ON events (project_pk, pk);
CREATE INDEX ix_events_type         ON events (project_pk, event_type);
CREATE INDEX ix_events_record       ON events (record_pk);

-- 불변 강제: REVOKE UPDATE, DELETE ON events FROM app_role;
```

이벤트 카탈로그(최소)

| event_type | payload 핵심 |
|---|---|
| record_version_created | version, body_hash, derived_from |
| record_state_changed | from, to, trigger(예: upstream@version) |
| run_state_changed | from, to, attempt, error, cancel_reason |
| stale_propagated | parent_record_pk, parent_version, trigger |
| rerun_no_impact | run_pk, body_hash, parent_record_pk, advanced_to_version |

## 8. artifacts (Artifact Registry 기본)

wireframe·PDF·이미지·검색결과·스크린샷. DB는 메타와 URI만, 실체는 오브젝트 스토리지.

```sql
CREATE TABLE artifacts (
  pk             BIGINT PRIMARY KEY,
  project_pk     BIGINT NOT NULL,
  public_key     VARCHAR(12),               -- lazy, 외부 노출용
  type           VARCHAR(24) NOT NULL,      -- wireframe|pdf|image|search_result|screenshot
  mime           VARCHAR(64) NOT NULL,
  uri            TEXT NOT NULL,             -- 오브젝트 스토리지 경로
  checksum       VARCHAR(64) NOT NULL,      -- 콘텐츠 주소화(무결성·중복제거)
  size_bytes     BIGINT NOT NULL,
  produced_by_run BIGINT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_artifacts_project FOREIGN KEY (project_pk) REFERENCES projects(pk),
  CONSTRAINT uq_artifacts_public_key UNIQUE (public_key),
  CONSTRAINT uq_artifacts_project_checksum UNIQUE (project_pk, checksum)
);
```

규칙: record_versions.body에 바이너리·base64 적재 금지. 외부 자산은 record_versions.artifact_refs가 artifacts.pk를 참조한다. 외부 접근은 public_key + 서명·만료 URL(D6 인가는 이후).

## 9. Multi-Tenant Boundary Enforcement

### 9.1 컬럼·복합 FK

1. 모든 테넌트 테이블은 project_pk NOT NULL을 가진다(workflows 제외, 전역 템플릿).
2. 교차 테넌트 참조를 복합 FK로 차단한다. 예: record_versions가 다른 테넌트의 record를 참조 못 하도록 (project_pk, record_pk) 복합 FK 사용(4절).

### 9.2 Row-Level Security (tenant scoped lookup)

세션 변수에 현재 테넌트를 두고 RLS로 강제한다. public_key 조회도 테넌트 경계 안에서만.

```sql
ALTER TABLE records ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_records ON records
  USING (project_pk = current_setting('app.current_project')::BIGINT);
-- record_versions, record_validations, runs, events, artifacts에 동일 적용
```

D6(인가 모델)은 이후지만, 경계 컬럼·복합 FK·RLS는 지금 박는다. 늦게 넣으면 소급이 위험하기 때문이다.

## 10. derived_from, stale 전파, No Impact 구현

핵심 메커니즘을 테이블 동작으로 정의한다.

### 10.1 버전 생성(내용 변경 시)

1. record_versions에 새 행 INSERT(version+1, body, body_hash, derived_from, produced_by_run).
2. records.head를 갱신(current_version, current_version_pk, status는 gate에 따라).
3. record_validations에 새 버전의 간선 INSERT(parent_version_pinned = parent_version_validated = 현재 상위 버전).
4. events에 record_version_created, record_state_changed append.

### 10.2 stale 전파(상위 confirmed + version 증가)

1. 상위 U head가 새 confirmed 버전 V_new를 얻음.
2. record_validations에서 parent_record_pk = U 이고 parent_version_validated < V_new 인 행을 찾는다(ix_rval_parent 사용).
3. 그 행의 record_version_pk가 하위 head의 current_version_pk이고 하위가 confirmed면, 하위 head.status를 stale로 전이.
4. events에 stale_propagated append.
5. 하위 on_upstream_change에 따라 재실행.

### 10.3 No Impact 처리(재실행 결과 동일)

1. 재실행 Run 성공. 저장 계층이 새 body_hash와 현재 버전 body_hash를 canonical 비교.
2. 동일하면 새 record_versions 행을 만들지 않는다.
3. record_validations에서 해당 (current_version_pk, parent_record_pk) 행의 parent_version_validated를 V_new로 전진.
4. head.status를 stale에서 confirmed로 복귀. current_version 유지.
5. events에 rerun_no_impact append(run_pk, body_hash, parent_record_pk, advanced_to_version=V_new).
6. version 미증가이므로 4절 전파 트리거 미충족. 하위 전파 없음.

### 10.4 중점 시나리오 검증

strategy v2 → policy v5(confirmed), strategy v3 확정 → policy stale → auto_rerun → policy 결과 동일.

| 단계 | 테이블 동작 |
|---|---|
| strategy v3 확정 | record_versions에 strategy v3 INSERT, strategy head.current_version=3, status=confirmed. events: record_version_created, record_state_changed |
| 전파 | record_validations에서 parent=strategy, validated<3 인 policy v5 행 탐색. policy head.status → stale. events: stale_propagated |
| 재실행 | runs INSERT(input strategy@v3). 성공 |
| 결과 동일 | body_hash 일치. 새 버전 미생성 |
| validation 전진 | policy v5 행의 parent_version_validated = 3으로 갱신 |
| 상태 복귀 | policy head.status stale → confirmed. current_version=5 유지 |
| No Impact 기록 | events: rerun_no_impact(advanced_to_version=3) |
| 하위 전파 | version 미증가로 전파 없음 |

제시한 4구조(자동 confirmed, No Impact 이벤트, version 미증가, 하위 전파 없음) 모두 적절하며, "derived_from 재핀"은 Append-Only에서 "validation 전진"으로 구현된다. policy v5의 derived_from(불변)은 strategy@v2 그대로 보존되어 재현성을 지키고, stale 판정은 validation이 담당한다. 두 관심사가 깨끗이 분리된다.

## 11. 검토 질문 답변

### 11.1 record_dependencies를 유지할 것인가

대체한다. record_validations로 진화시킨다. 의존 간선에 parent_version_validated(가변)를 더해, 영향도 역방향 조회와 stale 판정을 한 테이블이 담당한다. 별도 불변 간선 테이블은 두지 않는다. 불변 간선 정보는 이미 record_versions.derived_from에 있기 때문이다.

### 11.2 Event Log만으로 재구성 가능한가

가능하다. events는 모든 버전 생성·상태 전이·validation 전진을 담으므로, records·record_validations는 events 재생으로 복원된다. 단 record_versions의 body는 events 재생이 아니라 자체 불변 로그로 보존한다. 즉 진실은 두 불변 로그(record_versions, events)에 있고, 나머지는 재구성 가능한 투영이다. 라이브 조회는 투영을, 감사·복구는 로그를 쓴다.

### 11.3 Impact Analysis Engine 최소 컬럼

미래 엔진이 필요로 할 최소 데이터다. 지금부터 쌓여야 한다.

| 용도 | 테이블.컬럼 |
|---|---|
| 의존 결합도 | record_validations(parent_record_pk, parent_version_pinned, parent_version_validated) |
| 재실행 낭비 빈도 | events(event_type=rerun_no_impact, created_at) |
| 재실행 낭비 비용 | runs(node_id, produces_type, cost_usd, input_tokens, output_tokens) |
| 블라스트 반경 | record_versions(version, derived_from) |
| 에이전트 결정성 | runs(node_id, model_id) + events(rerun_no_impact 비율) |
| 추세 | events(created_at) |

이 컬럼들이 갖춰지면 엔진 자체는 읽기 연산이라 나중에 붙여도 된다.

## 12. 부채 자리 / 다음 단계

| 부채 | 상태 |
|---|---|
| D6 인가 모델 | 경계·RLS는 반영, 권한 검사 계층은 이후 |
| Audit 뷰 | events 위 읽기 계층, 이후 |
| Impact Analysis Engine | 데이터 확보 완료, 엔진 이후 |
| Workflow Migration | 선행 조건 충족, 이후 |

다음 단계 후보

1. canonical serialization 규칙 상세(키 정렬, 공백·널 정규화, artifact_refs 포함 여부).
2. on_upstream_change 노드별 기본값 매트릭스.
3. 불변 강제 방식 확정(권한 회수 또는 트리거).
