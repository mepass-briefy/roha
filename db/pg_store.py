"""
PgStore: orchestrator.Store와 동일한 공개 인터페이스를 Neon(PostgreSQL)로 구현한다.

orchestrator.py·에이전트·게이트는 수정하지 않는다. orchestrator는 Store를 덕타이핑으로만 쓰므로,
같은 시그니처의 PgStore를 주입하면 코드 수정 없이 DB 백엔드로 교체된다.

이번 범위: records / record_versions / record_validations / runs / events 5개 테이블.
projects·workflows는 FK를 위해 최소 row만 생성. artifacts는 범위 밖(기존처럼 파일 경로 메타만).

연결 문자열은 .env의 DATABASE_URL(load_dotenv). RLS는 연결 세션에 app.current_project를 설정해 강제.
"""

import os
import json
import time
import hashlib
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_PK_SEQ = "harness_pk_seq"


class PgStore:
    """orchestrator.Store와 동일한 공개 메서드(head/save_head/version/append_version/
    validations/save_validations/save_run/emit/events/next_pk)를 제공한다."""

    def __init__(self, project_pk: int, workflow: dict = None, dsn: str = None):
        self.project_pk = project_pk
        dsn = dsn or os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError("PgStore: DATABASE_URL 없음(.env 또는 환경변수 필요)")
        self.conn = psycopg.connect(dsn, autocommit=True)
        self._ensure_sequence()
        # RLS: 이 세션의 테넌트 고정
        with self.conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_project', %s, false)", (str(project_pk),))
        self.workflow_pk = self._ensure_workflow(workflow)
        self._ensure_project()

    # ---- 초기화(projects/workflows 최소 채움) ----
    def _ensure_sequence(self):
        with self.conn.cursor() as cur:
            cur.execute(f"CREATE SEQUENCE IF NOT EXISTS {_PK_SEQ} START 1001")

    def _ensure_workflow(self, workflow):
        wf = workflow or {"workflow_key": "default", "version": 1, "status": "active", "nodes": []}
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workflows (pk, workflow_key, version, status, nodes) "
                f"VALUES (nextval('{_PK_SEQ}'), %s, %s, %s, %s) "
                "ON CONFLICT (workflow_key, version) DO UPDATE SET status = EXCLUDED.status "
                "RETURNING pk",
                (wf.get("workflow_key", "default"), wf.get("version", 1),
                 wf.get("status", "active"), Jsonb(wf.get("nodes", []))),
            )
            self._workflow_ver = wf.get("version", 1)
            return cur.fetchone()[0]

    def _ensure_project(self):
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO projects (pk, business_key, name, workflow_pk, workflow_ver) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (pk) DO NOTHING",
                (self.project_pk, f"PROJ-{self.project_pk}", f"project {self.project_pk}",
                 self.workflow_pk, self._workflow_ver),
            )

    # ---- next_pk (DB 시퀀스) ----
    def next_pk(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT nextval('{_PK_SEQ}')")
            return int(cur.fetchone()[0])

    # ---- head (records) ----
    def head(self, rtype: str):
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT pk, type, current_version, current_version_pk, status "
                "FROM records WHERE project_pk = %s AND type = %s",
                (self.project_pk, rtype),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {"pk": row[0], "type": row[1], "project_pk": self.project_pk,
                "current_version": row[2], "current_version_pk": row[3], "status": row[4]}

    def save_head(self, head: dict):
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO records (pk, project_pk, type, current_version, current_version_pk, status) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (project_pk, type) DO UPDATE SET "
                "current_version = EXCLUDED.current_version, "
                "current_version_pk = EXCLUDED.current_version_pk, "
                "status = EXCLUDED.status, updated_at = now()",
                (head["pk"], self.project_pk, head["type"], head["current_version"],
                 head.get("current_version_pk"), head["status"]),
            )

    # ---- versions (immutable) ----
    def version(self, rtype: str, v: int):
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT rv.pk, r.type, rv.record_pk, rv.version, rv.body, rv.body_hash, "
                "rv.derived_from, rv.produced_by_run, rv.provenance "
                "FROM record_versions rv JOIN records r ON rv.record_pk = r.pk "
                "WHERE r.project_pk = %s AND r.type = %s AND rv.version = %s",
                (self.project_pk, rtype, v),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {"pk": row[0], "type": row[1], "record_pk": row[2], "version": row[3],
                "body": row[4], "body_hash": row[5], "derived_from": row[6],
                "produced_by_run": row[7], "provenance": row[8]}

    def append_version(self, ver: dict):
        # orchestrator는 append_version을 save_head보다 먼저 호출한다. FK(record_pk->records) 충족을 위해
        # records에 해당 record_pk가 없으면 stub row를 먼저 만든다(곧 save_head가 갱신).
        body = ver.get("body", {})
        provenance = ver.get("provenance")
        if provenance is None and isinstance(body, dict):
            provenance = body.get("provenance", {})
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO records (pk, project_pk, type, current_version, current_version_pk, status) "
                "VALUES (%s, %s, %s, 0, NULL, 'draft') ON CONFLICT (pk) DO NOTHING",
                (ver["record_pk"], self.project_pk, ver["type"]),
            )
            try:
                cur.execute(
                    "INSERT INTO record_versions (pk, record_pk, project_pk, version, body, body_hash, "
                    "derived_from, provenance, produced_by_run) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (ver["pk"], ver["record_pk"], self.project_pk, ver["version"],
                     Jsonb(body), ver["body_hash"], Jsonb(ver.get("derived_from", [])),
                     Jsonb(provenance or {}), ver.get("produced_by_run")),
                )
            except psycopg.errors.UniqueViolation as e:
                raise RuntimeError("immutable violation: version already exists") from e

    # ---- validations ----
    def validations(self):
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT record_version_pk, parent_record_pk, parent_version_pinned, parent_version_validated "
                "FROM record_validations WHERE project_pk = %s",
                (self.project_pk,),
            )
            rows = cur.fetchall()
        return [{"record_version_pk": r[0], "parent_record_pk": r[1],
                 "parent_version_pinned": r[2], "parent_version_validated": r[3]} for r in rows]

    def save_validations(self, rows):
        # 외부 계약: 전달된 rows가 현재 전체 상태(파일 Store는 통째 덮어씀).
        # 내부는 행 단위 upsert + 빠진 행 삭제로 동일 상태를 만든다.
        with self.conn.cursor() as cur:
            keys = [(r["record_version_pk"], r["parent_record_pk"]) for r in rows]
            if keys:
                cur.execute(
                    "DELETE FROM record_validations WHERE project_pk = %s "
                    "AND (record_version_pk, parent_record_pk) NOT IN "
                    "(SELECT (k->>0)::bigint, (k->>1)::bigint FROM jsonb_array_elements(%s) k)",
                    (self.project_pk, Jsonb([[a, b] for a, b in keys])),
                )
            else:
                cur.execute("DELETE FROM record_validations WHERE project_pk = %s", (self.project_pk,))
            for r in rows:
                cur.execute(
                    "INSERT INTO record_validations (record_version_pk, parent_record_pk, project_pk, "
                    "parent_version_pinned, parent_version_validated) VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (record_version_pk, parent_record_pk) DO UPDATE SET "
                    "parent_version_pinned = EXCLUDED.parent_version_pinned, "
                    "parent_version_validated = EXCLUDED.parent_version_validated, updated_at = now()",
                    (r["record_version_pk"], r["parent_record_pk"], self.project_pk,
                     r["parent_version_pinned"], r["parent_version_validated"]),
                )

    # ---- runs ----
    def save_run(self, run: dict):
        # 파일 dict와 DB 컬럼 차이 보정: workflow_pk(고정), input_signature_hash(계산).
        sig = run.get("input_signature_hash")
        if not sig:
            sig = hashlib.sha256(
                json.dumps(run.get("input_refs", []), sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:64]
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO runs (pk, project_pk, workflow_pk, workflow_ver, node_id, produces_type, "
                "input_refs, input_signature_hash, run_status, attempt, model_id, agent_version, "
                "prompt_version, input_tokens, output_tokens, cost_usd) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (pk) DO UPDATE SET run_status = EXCLUDED.run_status, "
                "attempt = EXCLUDED.attempt, input_tokens = EXCLUDED.input_tokens, "
                "output_tokens = EXCLUDED.output_tokens, cost_usd = EXCLUDED.cost_usd",
                (run["pk"], self.project_pk, self.workflow_pk, run.get("workflow_ver", self._workflow_ver),
                 run["node_id"], run["produces_type"], Jsonb(run.get("input_refs", [])), sig,
                 run.get("run_status", "queued"), run.get("attempt", 1), run.get("model_id"),
                 run.get("agent_version"), run.get("prompt_version"),
                 run.get("input_tokens"), run.get("output_tokens"), run.get("cost_usd")),
            )

    # ---- events (append-only) ----
    def emit(self, event_type, subject_type, subject_pk, payload, actor="system",
             record_pk=None, record_version=None, run_pk=None):
        pk = self.next_pk()
        ts = round(time.time(), 3)
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO events (pk, project_pk, event_type, subject_type, subject_pk, "
                "record_pk, record_version, run_pk, payload, actor) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (pk, self.project_pk, event_type, subject_type, subject_pk,
                 record_pk, record_version, run_pk, Jsonb(payload), Jsonb({"kind": actor})),
            )
        # 반환은 파일 Store와 동일 구조(ts 포함)로 유지
        return {"pk": pk, "project_pk": self.project_pk, "event_type": event_type,
                "subject_type": subject_type, "subject_pk": subject_pk, "record_pk": record_pk,
                "record_version": record_version, "run_pk": run_pk, "payload": payload,
                "actor": actor, "ts": ts}

    def events(self):
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT pk, event_type, subject_type, subject_pk, record_pk, record_version, "
                "run_pk, payload, actor, extract(epoch from created_at) "
                "FROM events WHERE project_pk = %s ORDER BY pk",
                (self.project_pk,),
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            actor = r[8]
            actor = actor.get("kind") if isinstance(actor, dict) else actor
            out.append({"pk": r[0], "project_pk": self.project_pk, "event_type": r[1],
                        "subject_type": r[2], "subject_pk": r[3], "record_pk": r[4],
                        "record_version": r[5], "run_pk": r[6], "payload": r[7],
                        "actor": actor, "ts": round(r[9], 3) if r[9] is not None else None})
        return out
