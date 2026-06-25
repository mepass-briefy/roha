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
import string
import secrets
import hashlib
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_PK_SEQ = "harness_pk_seq"
_BIZ_SEQ = "harness_business_seq"          # business_key 순번(ROHA0001 ...)
_PUBKEY_ALPHABET = string.ascii_letters + string.digits
_BIZ_PREFIX = "ROHA"                        # 접두 4 대문자(고정). 오버플로 시 base-26 올림.


def _gen_public_key(n=12):
    """API·URL 전송용 public_key(난수, 불변). 화면에 ID로 표시하지 않음(식별자 3종 중 전송용)."""
    return "".join(secrets.choice(_PUBKEY_ALPHABET) for _ in range(n))


def _roll_prefix(base: str, inc: int) -> str:
    """4 대문자 접두를 base-26(A=0..Z=25, 오른쪽이 최하위)으로 inc만큼 올린다. 'ROHA'+1 -> 'ROHB'."""
    num = 0
    for ch in base:
        num = num * 26 + (ord(ch) - 65)
    num += inc
    out = []
    for _ in range(4):
        out.append(chr(65 + num % 26))
        num //= 26
    return "".join(reversed(out))


def _gen_business_key(n: int) -> str:
    """사람용 business_key. n은 1부터의 순번. 형식: 접두 4 대문자 + 4자리(0001..9999).
    9999 초과 시 접두를 한 칸 올리고 숫자를 0001로 되돌린다(ROHA9999 -> ROHB0001)."""
    digits = (n - 1) % 9999 + 1
    block = (n - 1) // 9999
    prefix = _roll_prefix(_BIZ_PREFIX, block)
    return f"{prefix}{digits:04d}"


def _mime_for(path: str) -> str:
    if path.endswith(".py"):
        return "text/x-python"
    if path.endswith((".jsx", ".js", ".tsx", ".ts")):
        return "text/javascript"
    return "application/octet-stream"


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
            cur.execute(f"CREATE SEQUENCE IF NOT EXISTS {_BIZ_SEQ} START 1")

    def _ensure_workflow(self, workflow):
        wf = workflow or {"workflow_key": "default", "version": 1, "status": "active", "nodes": []}
        key = wf.get("workflow_key", "default")
        ver = wf.get("version", 1)
        status = wf.get("status", "active")
        with self.conn.cursor() as cur:
            # 한 workflow_key당 active는 하나(uq_workflows_one_active). 새 버전을 active로 올릴 때
            # 같은 key의 다른 active 버전을 deprecated로 내린다(버전 관리).
            if status == "active":
                cur.execute(
                    "UPDATE workflows SET status = 'deprecated' "
                    "WHERE workflow_key = %s AND version <> %s AND status = 'active'",
                    (key, ver),
                )
            cur.execute(
                "INSERT INTO workflows (pk, workflow_key, version, status, nodes) "
                f"VALUES (nextval('{_PK_SEQ}'), %s, %s, %s, %s) "
                "ON CONFLICT (workflow_key, version) DO UPDATE SET "
                "status = EXCLUDED.status, nodes = EXCLUDED.nodes RETURNING pk",
                (key, ver, status, Jsonb(wf.get("nodes", []))),
            )
            self._workflow_ver = ver
            return cur.fetchone()[0]

    def _ensure_project(self):
        # 식별자 3종: PK(내부, 비노출), business_key(사람용 ID·UI 노출, ROHA0001 순번),
        # public_key(API·URL 전송용, 난수·불변).
        # 존재하면 그대로 둔다(business_key 순번을 매 요청마다 소모하지 않도록 INSERT 전 확인).
        # business_key 순번은 신규 INSERT 시점에만 nextval로 부여(=불변).
        with self.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM projects WHERE pk = %s", (self.project_pk,))
            if cur.fetchone():
                return
            cur.execute(f"SELECT nextval('{_BIZ_SEQ}')")
            business_key = _gen_business_key(int(cur.fetchone()[0]))
            cur.execute(
                "INSERT INTO projects (pk, business_key, public_key, name, workflow_pk, workflow_ver) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (pk) DO NOTHING",
                (self.project_pk, business_key, _gen_public_key(),
                 f"project {self.project_pk}", self.workflow_pk, self._workflow_ver),
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
                    "derived_from, provenance, artifact_refs, produced_by_run) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (ver["pk"], ver["record_pk"], self.project_pk, ver["version"],
                     Jsonb(body), ver["body_hash"], Jsonb(ver.get("derived_from", [])),
                     Jsonb(provenance or {}),
                     Jsonb(body.get("artifact_refs", []) if isinstance(body, dict) else []),
                     ver.get("produced_by_run")),
                )
            except psycopg.errors.UniqueViolation as e:
                raise RuntimeError("immutable violation: version already exists") from e

            # artifacts 적재: body.artifact_refs(backend/frontend/mobile이 채움)를 artifacts 테이블에.
            # 실제 바이너리가 아니라 경로·메타 중심(현재 구조 유지). 중복 checksum은 무시.
            run_pk = ver.get("produced_by_run")
            for a in (body.get("artifact_refs", []) if isinstance(body, dict) else []):
                path = a.get("path", "")
                cur.execute(
                    "INSERT INTO artifacts (pk, project_pk, public_key, type, mime, uri, checksum, "
                    "size_bytes, produced_by_run) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (project_pk, checksum) DO NOTHING",
                    (self.next_pk(), self.project_pk, _gen_public_key(), a.get("kind", "artifact"),
                     _mime_for(path), path, a.get("checksum", ""), a.get("bytes", 0), run_pk),
                )

            # runs 컬럼 보정: orchestrator가 가진 정보(record_pk, version)로 output_record_pk/version 채움.
            # model_id/tokens/cost 등은 producer가 안 실어줌 -> BACKLOG B1.
            if run_pk:
                cur.execute(
                    "UPDATE runs SET output_record_pk = %s, output_version = %s "
                    "WHERE pk = %s AND project_pk = %s",
                    (ver["record_pk"], ver["version"], run_pk, self.project_pk),
                )

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
