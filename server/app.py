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
TOTAL_STEPS = len(NODE_ORDER)  # 진행도(완료 노드/전체)


@app.get("/projects")
def list_projects(tab: str = "active", sort: str = "recent", page: int = 1, page_size: int = 20,
                  date_from: str | None = None, date_to: str | None = None):
    # 목록: 탭(active|done) + 정렬(recent|incomplete) + 날짜 필터 + 페이징. soft-deleted 제외.
    # 외부 식별자 public_key만 노출(내부 PK 비노출).
    tab = tab if tab in ("active", "done") else "active"
    where = ["coalesce(lc.deleted, false) = false", "coalesce(lc.status, 'active') = %s"]
    args = [tab]
    if date_from:
        where.append("p.created_at >= %s"); args.append(date_from)
    if date_to:
        where.append("p.created_at <= %s"); args.append(date_to)
    wsql = " AND ".join(where)
    order = "p.created_at DESC" if sort != "incomplete" else "confirmed_n ASC, p.created_at DESC"
    page = max(1, int(page)); page_size = min(100, max(1, int(page_size)))
    offset = (page - 1) * page_size

    base_from = ("FROM projects p "
                 "LEFT JOIN project_lifecycle lc ON lc.project_pk = p.pk "
                 "LEFT JOIN records ir ON ir.project_pk = p.pk AND ir.type = 'intake' "
                 "LEFT JOIN record_versions rv ON rv.pk = ir.current_version_pk")
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            f"SELECT p.public_key, p.business_key, p.created_at, coalesce(lc.status,'active') AS status, "
            f"(SELECT count(*) FROM records r WHERE r.project_pk = p.pk AND r.status = 'confirmed') AS confirmed_n, "
            f"rv.body {base_from} WHERE {wsql} ORDER BY {order} LIMIT %s OFFSET %s",
            args + [page_size, offset])
        rows = cur.fetchall()
        cur.execute(f"SELECT count(*) {base_from} WHERE {wsql}", args)
        total = cur.fetchone()[0]
    out = []
    for public_key, business_key, created_at, status, confirmed_n, body in rows:
        title = None
        if isinstance(body, dict):
            title = body.get("site_character") or (body.get("goal") or {}).get("statement")
        # business_key = 화면에 노출되는 사람용 ID, public_key = API·URL 호출용(경로 전송).
        out.append({"public_key": public_key, "business_key": business_key,
                    "created_at": str(created_at), "status": status,
                    "progress": {"confirmed": confirmed_n, "total": TOTAL_STEPS},
                    "title": title or "(제목 없음)"})
    return {"projects": out, "page": page, "page_size": page_size, "total": total,
            "tab": tab, "sort": sort}


def _set_lifecycle(public_key, **fields):
    pk = _project_pk(public_key)
    cols = ", ".join(fields.keys())
    ph = ", ".join(["%s"] * len(fields))
    upd = ", ".join(f"{k} = EXCLUDED.{k}" for k in fields)
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            f"INSERT INTO project_lifecycle (project_pk, {cols}, updated_at) VALUES (%s, {ph}, now()) "
            f"ON CONFLICT (project_pk) DO UPDATE SET {upd}, updated_at = now()",
            [pk] + list(fields.values()))
    return pk


@app.post("/projects/{public_key}/complete")
def complete_project(public_key: str):
    _set_lifecycle(public_key, status="done")
    return {"public_key": public_key, "status": "done"}


@app.post("/projects/{public_key}/reopen")
def reopen_project(public_key: str):
    _set_lifecycle(public_key, status="active")
    return {"public_key": public_key, "status": "active"}


@app.delete("/projects/{public_key}")
def soft_delete_project(public_key: str):
    _set_lifecycle(public_key, deleted=True)
    return {"public_key": public_key, "deleted": True}


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
        cur.execute("SELECT public_key, business_key FROM projects WHERE pk = %s", (project_pk,))
        public_key, business_key = cur.fetchone()
    return {"public_key": public_key, "business_key": business_key,
            "site_character": requirement["site_character"], "status": "created"}


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
    pk = _project_pk(public_key)
    store = _store(pk)
    nodes = []
    for rt in NODE_ORDER:
        h = store.head(rt)
        nodes.append({"node": rt, "status": h["status"] if h else None,
                      "version": h["current_version"] if h else None})
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT business_key FROM projects WHERE pk = %s", (pk,))
        business_key = cur.fetchone()[0]
    return {"public_key": public_key, "business_key": business_key,
            "nodes": nodes, "awaiting_approval": _awaiting(store)}


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


class EditBodyReq(BaseModel):
    body: dict


@app.put("/projects/{public_key}/records/discovery")
def edit_discovery(public_key: str, req: EditBodyReq):
    """사람이 수정/삭제/답변한 Discovery body를 새 append-only 버전으로 저장한다.
    orchestrator·에이전트 무수정 — create_project와 동일하게 PgStore로 버전만 기록한다.
    의미 변경(canonical_hash 변화) 시에만 version+1. status는 보존(검토 단계 편집 가정).
    하드삭제 = 새 버전 body에서 항목 제거(이전 버전 이력은 append-only로 보존)."""
    store = _store(_project_pk(public_key))
    head = store.head("discovery")
    if not head:
        raise HTTPException(status_code=404, detail="discovery record 없음(아직 실행 전)")
    new_body = req.body
    if not isinstance(new_body, dict):
        raise HTTPException(status_code=400, detail="body는 객체여야 함")
    # 편집이 닿는 부분만 구조 검증(깨진 수정 차단). 전체 스키마 validate는 구버전 레코드를
    # 거부할 수 있어 쓰지 않는다. 지표는 비어 있으면 안 되고, open_questions는 리스트여야 한다.
    gi = new_body.get("goal_interpretation")
    if not isinstance(gi, dict) or not isinstance(gi.get("candidate_metrics", []), list):
        raise HTTPException(status_code=400, detail="goal_interpretation.candidate_metrics 구조 오류")
    for m in gi.get("candidate_metrics", []):
        if not isinstance(m, dict) or not str(m.get("metric") or "").strip():
            raise HTTPException(status_code=400, detail="지표(metric)는 빈 값일 수 없습니다")
    if not isinstance(new_body.get("open_questions", []), list):
        raise HTTPException(status_code=400, detail="open_questions는 리스트여야 함")

    # 변경 판정은 내용 기준(클라이언트가 보낸 body vs 현재 body). human_edited 표기는
    # 저장 시점에만 붙여 '내용 무변경 no-op'이 새 버전을 만들지 않게 한다(동결 규칙 3.6.2).
    cur_ver = store.version("discovery", head["current_version"])
    if canonical_hash(new_body) == canonical_hash(cur_ver["body"]):
        return {"changed": False, "version": head["current_version"], "status": head["status"]}

    prov = dict(new_body.get("provenance") or {})
    prov["human_edited"] = True
    new_body["provenance"] = prov
    new_hash = canonical_hash(new_body)
    new_version = head["current_version"] + 1
    ver_pk = store.next_pk()
    store.append_version({"pk": ver_pk, "type": "discovery", "record_pk": head["pk"],
                          "version": new_version, "body": new_body, "body_hash": new_hash,
                          "derived_from": cur_ver.get("derived_from") or [], "produced_by_run": None})
    store.save_head({"pk": head["pk"], "type": "discovery", "current_version": new_version,
                     "current_version_pk": ver_pk, "status": head["status"]})
    store.emit("human_edit", "record", head["pk"],
               {"node": "discovery", "from_version": head["current_version"], "to_version": new_version},
               actor="human", record_pk=head["pk"], record_version=new_version)
    return {"changed": True, "version": new_version, "status": head["status"]}
