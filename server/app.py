"""
로컬 웹 서버 (FastAPI). orchestrator/에이전트/게이트/run_harness 로직은 호출만 한다(수정 없음).

- .env에서 DATABASE_URL·키 로드. STORE=db 기본.
- 게이트 단위 실행: POST /run 은 한 칸(다음 READY 노드)만 동기 실행하고 결과 반환(백그라운드·폴링 없음).
- human 게이트에서 멈춤. POST /approve 로 승인해야 다음 칸 진행.
- 외부 식별자는 public_key만 노출(내부 PK 비노출).

실행:  uvicorn server.app:app --port 8000   (roha 루트에서)
"""
import os
import sys
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))
sys.path.insert(0, str(BASE / "db"))

from dotenv import load_dotenv
load_dotenv(BASE / ".env")
os.environ.setdefault("STORE", "db")

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from orchestrator import Orchestrator, canonical_hash
from pg_store import PgStore
import gate_test
import gate_review
import run_harness  # build_producers 재사용(호출만)
import discovery as discovery_agent

# v11: discovery 노드 포함(intake -> discovery -> strategy -> ...)
WF = json.loads((BASE / "workflow" / "site-build.v11.json").read_text(encoding="utf-8"))
ART = BASE / "_run_server" / "artifacts"
PRODUCERS = run_harness.build_producers(ART)
# discovery producer 추가(run_harness.build_producers엔 없음). 로직 무수정, 등록만. DISCOVERY_MODE 따름.
_disc_llm = discovery_agent.real_llm if os.environ.get("DISCOVERY_MODE") == "real" else discovery_agent.offline_llm
PRODUCERS["discovery"] = discovery_agent.make_producer(_disc_llm)
GATES = {n["produces"]: n.get("gate") for n in WF["nodes"]}
NODE_ORDER = [n["produces"] for n in WF["nodes"]]

app = FastAPI(title="harness local API")


# ---- 헬퍼 ----
def _conn():
    return psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)


def _project_pk(public_key: str) -> int:
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT pk FROM projects WHERE public_key = %s", (public_key,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="project not found")
    return row[0]


def _store(project_pk: int) -> PgStore:
    return PgStore(project_pk, workflow=WF)


def _orc(store):
    return Orchestrator(store, WF, PRODUCERS)


def _awaiting(store):
    """human 게이트에서 in_review로 멈춘 노드 목록."""
    return [rt for rt in NODE_ORDER
            if (h := store.head(rt)) and h["status"] == "in_review" and GATES.get(rt) == "human"]


# ---- 모델 ----
class CreateReq(BaseModel):
    site_character: str = ""
    requirements: list[str] = []
    goal: dict = {}                       # { statement, details } — discovery 입력
    context: str | None = None            # 고객·프로덕트 맥락(선택)
    target_platform: str = "미정"         # web|mobile|both|미정 (입력값, fact)
    seed_competitors: list[str] = []
    unique_angles: list[str] = []
    brand_tokens: dict = {}


# ---- 엔드포인트 ----
@app.post("/projects")
def create_project(req: CreateReq):
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT nextval('harness_pk_seq')")
        project_pk = int(cur.fetchone()[0])
    store = _store(project_pk)  # projects/workflows row 생성(public_key 포함)
    requirement = req.model_dump()
    ver_pk = store.next_pk()
    head_pk = store.next_pk()
    store.append_version({"pk": ver_pk, "type": "intake", "record_pk": head_pk, "version": 1,
                          "body": requirement, "body_hash": canonical_hash(requirement),
                          "derived_from": [], "produced_by_run": None})
    store.save_head({"pk": head_pk, "type": "intake", "project_pk": project_pk,
                     "current_version": 1, "current_version_pk": ver_pk, "status": "confirmed"})
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT public_key FROM projects WHERE pk = %s", (project_pk,))
        public_key = cur.fetchone()[0]
    return {"public_key": public_key, "site_character": requirement["site_character"], "status": "created"}


@app.post("/projects/{public_key}/run")
def run_step(public_key: str):
    store = _store(_project_pk(public_key))
    orc = _orc(store)
    picked = orc.tick()
    if picked is None:
        return {"ran": None, "awaiting_approval": _awaiting(store),
                "message": "실행할 READY 노드 없음(승인 필요 또는 완료)"}
    head = store.head(picked)
    body = store.version(picked, head["current_version"])["body"]
    t = gate_test.run_test_gate(picked, body, artifact_base=ART)
    r = gate_review.run_review_gate(picked, body)
    store.emit("gate_result", "record", head["pk"],
               {"node": picked, "test": t["status"], "review": r["status"],
                "reasons": (t["reasons"] + r["reasons"])[:5]},
               actor="api", record_pk=head["pk"], record_version=head["current_version"])
    awaiting = picked if (GATES.get(picked) == "human" and head["status"] == "in_review") else None
    return {
        "ran": picked,
        "gate": {"test": t["status"], "review": r["status"], "reasons": (t["reasons"] + r["reasons"])[:5]},
        "awaiting_approval": awaiting,
        "output_keys": list(body.keys()) if isinstance(body, dict) else None,
    }


@app.post("/projects/{public_key}/approve")
def approve(public_key: str):
    store = _store(_project_pk(public_key))
    orc = _orc(store)
    for rt in NODE_ORDER:
        h = store.head(rt)
        if h and h["status"] == "in_review":
            orc.human_confirm(rt)
            return {"approved": rt, "message": "다음 단계 진행 가능"}
    return {"approved": None, "message": "승인 대기 중인 노드 없음"}


@app.get("/projects/{public_key}/status")
def status(public_key: str):
    store = _store(_project_pk(public_key))
    nodes = []
    for rt in NODE_ORDER:
        h = store.head(rt)
        nodes.append({"node": rt, "status": h["status"] if h else None,
                      "version": h["current_version"] if h else None})
    return {"public_key": public_key, "nodes": nodes, "awaiting_approval": _awaiting(store)}


@app.get("/projects/{public_key}/records")
def records(public_key: str):
    pk = _project_pk(public_key)
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.current_project', %s, false)", (str(pk),))
        cur.execute(
            "SELECT r.type, r.status, r.current_version, rv.body "
            "FROM records r JOIN record_versions rv "
            "ON rv.record_pk = r.pk AND rv.version = r.current_version "
            "WHERE r.project_pk = %s ORDER BY r.type", (pk,))
        rows = cur.fetchall()
    # 내부 PK 비노출: type/status/version/body만
    return {"public_key": public_key,
            "records": [{"type": t, "status": s, "version": v, "body": b} for t, s, v, b in rows]}
