-- 하네스 DB 스키마 (DDL v2, docs/harness-ddl-v2.md 기준)
-- idempotent: 반복 실행해도 안전(CREATE ... IF NOT EXISTS, 정책은 DROP 후 CREATE).
-- 적용 대상: Neon(PostgreSQL). 연결 문자열은 DATABASE_URL 환경변수에서 읽는다.

-- 2. workflows (전역 템플릿, projects가 FK로 참조하므로 먼저 생성)
CREATE TABLE IF NOT EXISTS workflows (
  pk            BIGINT PRIMARY KEY,
  workflow_key  VARCHAR(64) NOT NULL,
  version       INT NOT NULL,
  status        VARCHAR(16) NOT NULL DEFAULT 'draft',
  nodes         JSONB NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_workflows_key_version UNIQUE (workflow_key, version),
  CONSTRAINT ck_workflows_status CHECK (status IN ('draft','active','deprecated'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_workflows_one_active
  ON workflows (workflow_key) WHERE status = 'active';

-- 1. projects (테넌트 루트)
CREATE TABLE IF NOT EXISTS projects (
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
  CONSTRAINT uq_projects_pk_for_fk UNIQUE (pk)
);

-- 3. records (head 포인터)
CREATE TABLE IF NOT EXISTS records (
  pk                  BIGINT PRIMARY KEY,
  project_pk          BIGINT NOT NULL,
  type                VARCHAR(32) NOT NULL,
  business_key        VARCHAR(64),
  public_key          VARCHAR(12),
  current_version     INT NOT NULL DEFAULT 0,
  current_version_pk  BIGINT,
  status              VARCHAR(16) NOT NULL DEFAULT 'draft',
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_records_project FOREIGN KEY (project_pk) REFERENCES projects(pk),
  CONSTRAINT ck_records_status
    CHECK (status IN ('draft','in_review','confirmed','rejected','stale')),
  CONSTRAINT uq_records_project_type UNIQUE (project_pk, type),
  CONSTRAINT uq_records_public_key UNIQUE (public_key),
  CONSTRAINT uq_records_business_key UNIQUE (project_pk, business_key),
  CONSTRAINT uq_records_project_pk UNIQUE (project_pk, pk)
);
CREATE INDEX IF NOT EXISTS ix_records_project_status ON records (project_pk, status);

-- 4. record_versions (불변 콘텐츠 로그)
CREATE TABLE IF NOT EXISTS record_versions (
  pk             BIGINT PRIMARY KEY,
  record_pk      BIGINT NOT NULL,
  project_pk     BIGINT NOT NULL,
  version        INT NOT NULL,
  body           JSONB NOT NULL DEFAULT '{}',
  body_hash      VARCHAR(64) NOT NULL,
  derived_from   JSONB NOT NULL DEFAULT '[]',
  provenance     JSONB NOT NULL DEFAULT '{}',
  artifact_refs  JSONB NOT NULL DEFAULT '[]',
  produced_by_run BIGINT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_rv_record FOREIGN KEY (record_pk) REFERENCES records(pk),
  CONSTRAINT fk_rv_project_record
    FOREIGN KEY (project_pk, record_pk) REFERENCES records(project_pk, pk),
  CONSTRAINT uq_rv_record_version UNIQUE (record_pk, version),
  CONSTRAINT uq_rv_pk_for_fk UNIQUE (pk)
);
CREATE INDEX IF NOT EXISTS ix_rv_record ON record_versions (record_pk);

-- 5. record_validations (가변 stale 판정·영향도 투영)
CREATE TABLE IF NOT EXISTS record_validations (
  record_version_pk        BIGINT NOT NULL,
  parent_record_pk         BIGINT NOT NULL,
  project_pk               BIGINT NOT NULL,
  parent_version_pinned    INT NOT NULL,
  parent_version_validated INT NOT NULL,
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT pk_record_validations PRIMARY KEY (record_version_pk, parent_record_pk),
  CONSTRAINT fk_rval_child FOREIGN KEY (record_version_pk) REFERENCES record_versions(pk),
  CONSTRAINT fk_rval_parent FOREIGN KEY (parent_record_pk) REFERENCES records(pk)
);
CREATE INDEX IF NOT EXISTS ix_rval_parent ON record_validations (parent_record_pk, parent_version_validated);

-- 6. runs (실행 인스턴스 + Agent Version + Cost)
CREATE TABLE IF NOT EXISTS runs (
  pk                   BIGINT PRIMARY KEY,
  project_pk           BIGINT NOT NULL,
  workflow_pk          BIGINT NOT NULL,
  workflow_ver         INT    NOT NULL,
  node_id              VARCHAR(32) NOT NULL,
  produces_type        VARCHAR(32) NOT NULL,
  input_refs           JSONB NOT NULL DEFAULT '[]',
  input_signature_hash VARCHAR(64) NOT NULL,
  output_record_pk     BIGINT,
  output_version       INT,
  run_status           VARCHAR(16) NOT NULL DEFAULT 'queued',
  attempt              INT NOT NULL DEFAULT 1,
  error                JSONB,
  cancel_reason        VARCHAR(32),
  agent_version        VARCHAR(32),
  prompt_version       VARCHAR(32),
  model_id             VARCHAR(64),
  params               JSONB,
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
CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_inflight
  ON runs (project_pk, node_id, input_signature_hash)
  WHERE run_status IN ('queued','running');
CREATE INDEX IF NOT EXISTS ix_runs_project_status ON runs (project_pk, run_status);
CREATE INDEX IF NOT EXISTS ix_runs_node_cost ON runs (project_pk, node_id);

-- 7. events (불변 Event Log)
CREATE TABLE IF NOT EXISTS events (
  pk             BIGINT PRIMARY KEY,
  project_pk     BIGINT NOT NULL,
  event_type     VARCHAR(40) NOT NULL,
  subject_type   VARCHAR(16) NOT NULL,
  subject_pk     BIGINT NOT NULL,
  record_pk      BIGINT,
  record_version INT,
  run_pk         BIGINT,
  payload        JSONB NOT NULL DEFAULT '{}',
  actor          JSONB NOT NULL DEFAULT '{}',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_events_project FOREIGN KEY (project_pk) REFERENCES projects(pk),
  CONSTRAINT ck_events_subject
    CHECK (subject_type IN ('record','run','workflow','artifact'))
);
CREATE INDEX IF NOT EXISTS ix_events_project_seq  ON events (project_pk, pk);
CREATE INDEX IF NOT EXISTS ix_events_type         ON events (project_pk, event_type);
CREATE INDEX IF NOT EXISTS ix_events_record       ON events (record_pk);

-- 8. artifacts (Artifact Registry)
CREATE TABLE IF NOT EXISTS artifacts (
  pk             BIGINT PRIMARY KEY,
  project_pk     BIGINT NOT NULL,
  public_key     VARCHAR(12),
  type           VARCHAR(24) NOT NULL,
  mime           VARCHAR(64) NOT NULL,
  uri            TEXT NOT NULL,
  checksum       VARCHAR(64) NOT NULL,
  size_bytes     BIGINT NOT NULL,
  produced_by_run BIGINT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_artifacts_project FOREIGN KEY (project_pk) REFERENCES projects(pk),
  CONSTRAINT uq_artifacts_public_key UNIQUE (public_key),
  CONSTRAINT uq_artifacts_project_checksum UNIQUE (project_pk, checksum)
);

-- 9. Row-Level Security (테넌트 스코프). 세션 변수 app.current_project로 강제.
-- 정책은 IF NOT EXISTS 미지원이라 DROP 후 CREATE로 idempotent 처리.
-- current_setting(..., true)로 세션 변수 미설정 시 NULL(행 비노출), 에러 방지.
ALTER TABLE records             ENABLE ROW LEVEL SECURITY;
ALTER TABLE record_versions     ENABLE ROW LEVEL SECURITY;
ALTER TABLE record_validations  ENABLE ROW LEVEL SECURITY;
ALTER TABLE runs                ENABLE ROW LEVEL SECURITY;
ALTER TABLE events              ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifacts           ENABLE ROW LEVEL SECURITY;

-- FORCE: 테이블 owner 연결에도 RLS 적용(Neon 기본 role이 owner이므로 격리 강제에 필요).
ALTER TABLE records             FORCE ROW LEVEL SECURITY;
ALTER TABLE record_versions     FORCE ROW LEVEL SECURITY;
ALTER TABLE record_validations  FORCE ROW LEVEL SECURITY;
ALTER TABLE runs                FORCE ROW LEVEL SECURITY;
ALTER TABLE events              FORCE ROW LEVEL SECURITY;
ALTER TABLE artifacts           FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_records           ON records;
DROP POLICY IF EXISTS tenant_isolation_record_versions   ON record_versions;
DROP POLICY IF EXISTS tenant_isolation_record_validations ON record_validations;
DROP POLICY IF EXISTS tenant_isolation_runs              ON runs;
DROP POLICY IF EXISTS tenant_isolation_events            ON events;
DROP POLICY IF EXISTS tenant_isolation_artifacts         ON artifacts;

CREATE POLICY tenant_isolation_records ON records
  USING (project_pk = current_setting('app.current_project', true)::BIGINT);
CREATE POLICY tenant_isolation_record_versions ON record_versions
  USING (project_pk = current_setting('app.current_project', true)::BIGINT);
CREATE POLICY tenant_isolation_record_validations ON record_validations
  USING (project_pk = current_setting('app.current_project', true)::BIGINT);
CREATE POLICY tenant_isolation_runs ON runs
  USING (project_pk = current_setting('app.current_project', true)::BIGINT);
CREATE POLICY tenant_isolation_events ON events
  USING (project_pk = current_setting('app.current_project', true)::BIGINT);
CREATE POLICY tenant_isolation_artifacts ON artifacts
  USING (project_pk = current_setting('app.current_project', true)::BIGINT);

-- 10. project_lifecycle (server 전용 보조 테이블, 동결 8테이블 외)
-- 완료 표기·소프트 삭제. orchestrator·에이전트는 사용하지 않는다(UI/server만).
CREATE TABLE IF NOT EXISTS project_lifecycle (
  project_pk  BIGINT PRIMARY KEY,
  status      VARCHAR(16) NOT NULL DEFAULT 'active',  -- active|done
  deleted     BOOLEAN NOT NULL DEFAULT false,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_pl_project FOREIGN KEY (project_pk) REFERENCES projects(pk),
  CONSTRAINT ck_pl_status CHECK (status IN ('active','done'))
);
