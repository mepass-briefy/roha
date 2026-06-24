-- 운영용 non-bypassrls role. 앱이 이 role로 연결하면 RLS(app.current_project)가 강제된다.
-- Neon 기본 owner(neondb_owner)는 BYPASSRLS=True라 owner 연결은 RLS를 우회한다(테넌트 격리 안 됨).
-- 따라서 운영 앱은 이 harness_app role로 연결해야 한다.
--
-- 실제 연결 전환은 API 단계에서 한다. 지금은 role 생성 + 권한 부여만.
-- 비밀번호/연결 활성화는 배포 시 별도로 설정한다(여기에 비밀번호를 박지 않는다):
--   ALTER ROLE harness_app LOGIN PASSWORD '<배포 시 비밀 관리>';
-- 그 후 그 role의 DATABASE_URL로 앱을 연결하면, RLS가 강제되어 테넌트 격리가 동작한다.

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'harness_app') THEN
    -- NOLOGIN: 지금은 SET ROLE 검증용. 배포 시 위 ALTER ROLE로 LOGIN 활성화.
    -- NOBYPASSRLS(기본): RLS 우회 안 함 -> 정책 강제.
    CREATE ROLE harness_app NOLOGIN NOBYPASSRLS;
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO harness_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO harness_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO harness_app;

-- 이후 생성되는 객체에도 기본 권한 부여(스키마 재적용 대비).
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO harness_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO harness_app;
