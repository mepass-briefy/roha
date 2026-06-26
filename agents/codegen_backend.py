"""
Backend codegen 에이전트 — 검증된 backend 명세 -> 작동 Python 백엔드 코드(충실 번역).

두 층 분리:
  1) 아키텍처 층(build_architecture): 언어 무관 IR. 명세에서 "무엇을 구현하나"만 결정
     (엔티티->데이터 모델, 엔드포인트->라우트, 식별자 3종, FK, 계층). 언어가 바뀌어도 동일.
  2) 언어 투영 층(project_python): 아키텍처 IR -> Python(FastAPI + SQLAlchemy + SQLite) 코드.
     언어는 design_system seed처럼 갈아끼우는 변수(LANG_PROJECTORS). 나중에 Java 투영 추가 시 아키텍처 층 재사용.

원칙: 충실 번역. 명세에 없는 엔티티·엔드포인트·필드 창작 0. 규칙수준 기본값(타입 매핑 등)만 코드 관용으로 채우고 기록.
식별자 3종: pk(내부 bigint), business_key(운영), public_key(외부). 외부 경로는 public_key만.
"""
import json
import re
from pathlib import Path

# ---------------- 아키텍처 층(언어 무관) ----------------

# 명세 필드 type -> 논리 타입(언어 무관 canonical). 규칙수준 기본 매핑(코드 관용, 기록 대상).
_LOGICAL = {
    "string": "string", "str": "string", "text": "text",
    "integer": "integer", "int": "integer", "bigint": "bigint",
    "decimal": "decimal", "number": "decimal", "float": "decimal",
    "boolean": "boolean", "bool": "boolean",
    "datetime": "datetime", "timestamp": "datetime", "date": "date",
    "enum": "enum", "json": "json", "uuid": "string",
}
DEFAULT_LOGICAL = "string"  # 미지 타입 -> string(기록). 발명 아님(타입 상세 부재의 코드 관용 기본).


def _logical_type(t):
    return _LOGICAL.get(str(t or "").strip().lower(), DEFAULT_LOGICAL)


def _table_of(entity_name):
    """엔티티명 -> 테이블명(소문자). FK 해소의 기준."""
    return re.sub(r"[^a-z0-9_]", "", str(entity_name).strip().lower())


def _match_entity_table(resource, tables):
    """경로 리소스(보통 복수: applications) <-> 엔티티 테이블(단수: application) 관용 매칭.
    규칙수준 복수/단수 정규화(코드 관용, 발명 아님). 매칭 없으면 None."""
    if not resource:
        return None
    r = _table_of(resource)
    if r in tables:
        return r
    cands = set()
    if r.endswith("ies"):
        cands.add(r[:-3] + "y")
    if r.endswith("s"):
        cands.add(r[:-1])
    if r.endswith("y"):
        cands.add(r[:-1] + "ies")
    cands.add(r + "s")
    for c in cands:
        if c in tables:
            return c
    return None


def build_architecture(spec: dict) -> dict:
    """backend 명세 -> 언어 무관 아키텍처 IR. Python 지식 0."""
    entities_spec = spec.get("entities", []) or []
    table_names = {_table_of(e.get("name")) for e in entities_spec}

    entities = []
    for e in entities_spec:
        name = e.get("name")
        table = _table_of(name)
        cols = []
        # 식별자 3종(명세 규칙 그대로): pk 내부, business_key 운영, public_key 외부
        cols.append({"name": "pk", "logical_type": "pk", "nullable": False, "fk": None, "role": "internal_pk"})
        cols.append({"name": "business_key", "logical_type": "biz_key", "nullable": False, "fk": None, "role": "business_key"})
        cols.append({"name": "public_key", "logical_type": "pub_key", "nullable": False, "fk": None, "role": "public_key"})
        # 도메인 필드(명세 fields). *_pk 는 FK 후보.
        for f in (e.get("fields", []) or []):
            fname = f.get("name")
            if fname in ("pk", "business_key", "public_key"):
                continue  # 식별자는 위에서 처리(중복 방지)
            fk = None
            m = re.match(r"^(.+)_pk$", str(fname or ""))
            if m and _table_of(m.group(1)) in table_names:
                fk = {"table": _table_of(m.group(1)), "column": "pk"}
            cols.append({"name": fname, "logical_type": _logical_type(f.get("type")),
                         "nullable": True, "fk": fk, "role": "domain"})
        entities.append({"name": name, "table": table, "columns": cols,
                         "relations": e.get("relations", []) or []})

    routes = []
    for ep in (spec.get("api_spec", {}).get("endpoints", []) or []):
        path = ep.get("path", "")
        method = ep.get("method", "GET")
        external_param = "public_key" if "{public_key}" in path else None
        # resource = path의 마지막 비-파라미터 세그먼트
        segs = [s for s in path.split("/") if s and not s.startswith("{")]
        resource = segs[-1] if segs else None
        # kind
        if method == "POST":
            kind = "create"
        elif method in ("PUT", "PATCH"):
            kind = "update"
        elif method == "DELETE":
            kind = "delete"
        elif external_param:
            kind = "item"
        else:
            kind = "list"
        req = [{"name": rf.get("name"), "logical_type": _logical_type(rf.get("type")),
                "required": bool(rf.get("required")),
                "constraints": {k: rf.get(k) for k in ("format", "min", "max", "enum") if rf.get(k) is not None}}
               for rf in (ep.get("request_schema", []) or [])]
        entity_table = _match_entity_table(resource, table_names)
        routes.append({
            "op_id": ep.get("endpoint_id"), "method": method, "path": path,
            "external_param": external_param, "resource": resource,
            "entity_table": entity_table, "kind": kind,
            "request_fields": req,
            "success": [{"code": c.get("code"), "http_status": c.get("http_status")} for c in (ep.get("success_cases", []) or [])],
            "errors": [{"code": c.get("code"), "http_status": c.get("http_status")} for c in (ep.get("error_cases", []) or [])],
            "pagination": ep.get("pagination"),
            "exposure": ep.get("exposure", "internal"),
        })

    return {"entities": entities, "routes": routes,
            "response_contract": spec.get("api_spec", {}).get("response_contract", {})}


# ---------------- 언어 투영 층: Python(FastAPI + SQLAlchemy + SQLite) ----------------

_PY_SA_TYPE = {
    "pk": "BigInteger", "biz_key": "String(32)", "pub_key": "String(16)",
    "string": "String(255)", "text": "Text", "integer": "Integer", "bigint": "BigInteger",
    "decimal": "Numeric(18, 2)", "boolean": "Boolean", "datetime": "DateTime",
    "date": "Date", "enum": "String(64)", "json": "JSON",
}
_PY_PYD_TYPE = {
    "string": "str", "text": "str", "integer": "int", "bigint": "int",
    "decimal": "float", "boolean": "bool", "datetime": "datetime", "date": "date",
    "enum": "str", "json": "dict",
}


def _py_models(arch):
    L = ["from sqlalchemy import (Column, BigInteger, Integer, String, Text, Numeric, Boolean,",
         "                        DateTime, Date, JSON, ForeignKey)",
         "from database import Base", "", ""]
    for e in arch["entities"]:
        L.append(f"class {e['name']}(Base):")
        L.append(f'    __tablename__ = "{e["table"]}"')
        for c in e["columns"]:
            sa = _PY_SA_TYPE.get(c["logical_type"], "String(255)")
            if c["role"] == "internal_pk":
                # bigint PK. SQLite는 INTEGER PRIMARY KEY만 autoincrement -> 방언 variant(아키텍처는 bigint 유지).
                L.append(f'    pk = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)  # 내부 PK(외부 미노출)')
            elif c["role"] == "business_key":
                L.append(f'    business_key = Column(String(32), unique=True, index=True, nullable=False)  # 운영 키')
            elif c["role"] == "public_key":
                L.append(f'    public_key = Column(String(16), unique=True, index=True, nullable=False)  # 외부 노출 키')
            elif c["fk"]:
                L.append(f'    {c["name"]} = Column(BigInteger, ForeignKey("{c["fk"]["table"]}.pk"), nullable=True)  # FK')
            else:
                L.append(f'    {c["name"]} = Column({sa}, nullable={c["nullable"]})')
        L.append("")
    return "\n".join(L) + "\n"


def _py_database():
    return '''"""SQLite 프로토타입 DB(격리·삭제 용이). 운영 DB(Neon 등)는 DATABASE_URL로 교체 가능."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./app.db")
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    import models  # noqa: F401  (모델 등록)
    Base.metadata.create_all(bind=engine)


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'''


def _py_identifiers(arch):
    tables = [e["table"] for e in arch["entities"]]
    return f'''"""식별자 3종 생성. business_key=ROHA 순번류(운영), public_key=난수 10~12(외부). pk는 DB autoincrement(내부)."""
import secrets, string
from itertools import count

_PREFIX = "ROHA"
_SEQ = {{ {", ".join(f'"{t}": count(1)' for t in tables)} }}
_ALPHABET = string.ascii_letters + string.digits


def next_business_key(table: str) -> str:
    n = next(_SEQ.get(table, count(1)))
    return f"{{_PREFIX}}{{n:04d}}"


def new_public_key() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(secrets.choice([10, 11, 12])))
'''


def _py_response():
    return '''"""명세 response_contract 고정 래퍼. 외부는 이 형상으로만 응답. jsonable_encoder로 datetime/Decimal 직렬화."""
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder


def ok(data, status=200):
    return JSONResponse(status_code=status, content=jsonable_encoder({"success": True, "data": data}))


def fail(code: str, message: str, status: int):
    return JSONResponse(status_code=status, content=jsonable_encoder({"success": False, "error": {"code": code, "message": message}}))
'''


def _py_schemas(arch):
    L = ['"""명세 request_schema -> Pydantic 요청 모델(검증)."""',
         "from typing import Optional", "from datetime import datetime, date", "from pydantic import BaseModel", "", ""]
    # create/update 라우트의 request_fields로 요청 모델 생성
    seen = set()
    for r in arch["routes"]:
        if r["kind"] not in ("create", "update") or not r["request_fields"]:
            continue
        cls = "".join(w.capitalize() for w in re.split(r"[^a-zA-Z0-9]", str(r["op_id"] or "Req")) if w)
        if cls in seen:
            continue
        seen.add(cls)
        L.append(f"class {cls}(BaseModel):")
        body = [f for f in r["request_fields"] if f["name"] not in ("cursor", "limit")]
        if not body:
            L.append("    pass")
        for f in body:
            pt = _PY_PYD_TYPE.get(f["logical_type"], "str")
            if f["required"]:
                L.append(f'    {f["name"]}: {pt}')
            else:
                L.append(f'    {f["name"]}: Optional[{pt}] = None')
        L.append("")
        r["_req_model"] = cls
    return "\n".join(L) + "\n"


def _py_main(arch):
    ent_by_table = {e["table"]: e for e in arch["entities"]}
    L = ['"""FastAPI 앱. 명세 엔드포인트 충실 번역. 외부 경로는 public_key만. 식별자 3종 적용."""',
         "from fastapi import FastAPI, Depends, Request",
         "from sqlalchemy.orm import Session",
         "from sqlalchemy import select",
         "import models, schemas, coerce",
         "from database import init_db, get_session",
         "from identifiers import next_business_key, new_public_key",
         "from responses import ok, fail", "", "",
         "app = FastAPI(title='roha generated backend (spec->code)')", "",
         "@app.on_event('startup')",
         "def _startup():",
         "    init_db()", "", ""]

    def model_name(table):
        return ent_by_table[table]["name"] if table in ent_by_table else None

    def serialize(table):
        e = ent_by_table[table]
        ext = [c["name"] for c in e["columns"] if c["role"] != "internal_pk"]  # pk(내부) 비노출
        return ext

    for r in arch["routes"]:
        table = r.get("entity_table")
        mname = model_name(table) if table else None
        fn = re.sub(r"[^a-zA-Z0-9]", "_", str(r["op_id"] or "op"))
        deco = r["method"].lower()
        # 외부 경로: {public_key}만
        path = r["path"]
        if mname is None:
            # 명세에 엔티티 없는 리소스 -> 핸들러 자리만(충실 번역: 발명 금지, 미구현 명시)
            L.append(f'@app.{deco}("{path}")')
            L.append(f'def {fn}():')
            L.append(f'    return fail("NOT_FOUND", "리소스 엔티티 명세 없음: {table}", 404)')
            L.append("")
            continue
        succ = (r["success"][0]["http_status"] if r["success"] else 200)
        cols = serialize(table)
        if r["kind"] == "list":
            L += [f'@app.{deco}("{path}")',
                  f'def {fn}(cursor: int = 0, limit: int = 20, db: Session = Depends(get_session)):',
                  f'    rows = db.execute(select(models.{mname}).offset(cursor).limit(limit)).scalars().all()',
                  f'    items = [{{ {", ".join(f"\"{c}\": getattr(x, \"{c}\")" for c in cols)} }} for x in rows]',
                  f'    return ok({{"items": items, "next_cursor": cursor + len(items)}}, {succ})', ""]
        elif r["kind"] == "item":
            L += [f'@app.{deco}("{path}")',
                  f'def {fn}(public_key: str, db: Session = Depends(get_session)):',
                  f'    x = db.execute(select(models.{mname}).where(models.{mname}.public_key == public_key)).scalar_one_or_none()',
                  f'    if x is None:',
                  f'        return fail("NOT_FOUND", "리소스 없음", 404)',
                  f'    return ok({{ {", ".join(f"\"{c}\": getattr(x, \"{c}\")" for c in cols)} }}, {succ})', ""]
        elif r["kind"] == "create":
            req = r.get("_req_model")
            sig = f"payload: schemas.{req}, " if req else ""
            dom_cols = {c["name"]: c["logical_type"] for c in ent_by_table[table]["columns"] if c["role"] == "domain"}
            body_fields = [f["name"] for f in r["request_fields"] if f["name"] not in ("cursor", "limit")]
            L.append(f'@app.{deco}("{path}")')
            L.append(f'def {fn}({sig}db: Session = Depends(get_session)):')
            assigns = []
            for bf in body_fields:
                # 외부 FK 참조는 public_key로만 옴 -> 내부 pk로 조회·변환(식별자 3종 경계)
                if bf.endswith("_public_key"):
                    base = bf[: -len("_public_key")]
                    reftab = _match_entity_table(base, set(ent_by_table))
                    if reftab and (base + "_pk") in dom_cols:
                        refm = ent_by_table[reftab]["name"]
                        var = f"_ref_{base}"
                        L.append(f'    {var} = db.execute(select(models.{refm}).where(models.{refm}.public_key == payload.{bf})).scalar_one_or_none()')
                        L.append(f'    if {var} is None:')
                        L.append(f'        return fail("VALIDATION_ERROR", "{bf} 참조 없음", 400)')
                        assigns.append(f"{base}_pk={var}.pk")
                        continue
                if bf in dom_cols:
                    assigns.append(f'{bf}=coerce.to_db(getattr(payload, "{bf}", None), "{dom_cols[bf]}")')
                # else: 요청에만 있고 모델 컬럼 없는 필드 -> 무시(발명 금지)
            kw = ", ".join([f'business_key=next_business_key("{table}")', "public_key=new_public_key()"] + assigns)
            L.append(f'    x = models.{mname}({kw})')
            L.append(f'    db.add(x); db.commit(); db.refresh(x)')
            L.append(f'    return ok({{ {", ".join(f"\"{c}\": getattr(x, \"{c}\")" for c in cols)} }}, {succ})')
            L.append("")
        elif r["kind"] in ("update", "delete"):
            L += [f'@app.{deco}("{path}")',
                  f'def {fn}(public_key: str, db: Session = Depends(get_session)):',
                  f'    x = db.execute(select(models.{mname}).where(models.{mname}.public_key == public_key)).scalar_one_or_none()',
                  f'    if x is None:',
                  f'        return fail("NOT_FOUND", "리소스 없음", 404)',
                  (f'    db.delete(x); db.commit()' if r["kind"] == "delete" else f'    db.commit()'),
                  f'    return ok({{"public_key": public_key}}, {succ})', ""]
    return "\n".join(L) + "\n"


LANG_PROJECTORS = {"python": None}  # 아래에서 등록(투영 함수 묶음)


def _py_coerce():
    return '''"""요청 값 -> DB 컬럼 논리타입 강제 변환(request_schema 타입에 의존하지 않고 컬럼 기준)."""
from datetime import datetime, date
from decimal import Decimal


def to_db(v, kind):
    if v is None:
        return None
    if kind == "datetime" and isinstance(v, str):
        return datetime.fromisoformat(v)
    if kind == "date" and isinstance(v, str):
        return date.fromisoformat(v)
    if kind == "decimal" and not isinstance(v, Decimal):
        return Decimal(str(v))
    return v
'''


def project_python(arch: dict) -> dict:
    """아키텍처 IR -> Python 파일 묶음(path->content). Python 관용은 이 층에만."""
    files = {}
    files["coerce.py"] = _py_coerce()
    files["database.py"] = _py_database()
    files["models.py"] = _py_models(arch)
    files["identifiers.py"] = _py_identifiers(arch)
    files["responses.py"] = _py_response()
    files["schemas.py"] = _py_schemas(arch)   # _req_model 주석 부착(아래 main이 사용)
    files["main.py"] = _py_main(arch)
    files["requirements.txt"] = "fastapi\nuvicorn\nsqlalchemy\npydantic\n"
    return files


LANG_PROJECTORS["python"] = project_python


def generate(spec: dict, out_dir, language: str = "python") -> dict:
    """명세 -> 코드 파일 생성. 아키텍처 층 -> 언어 투영 층. 반환: 생성 파일 경로 목록 + 아키텍처 요약."""
    arch = build_architecture(spec)
    projector = LANG_PROJECTORS.get(language)
    if projector is None:
        raise ValueError(f"미지원 언어 투영: {language} (지원: {list(LANG_PROJECTORS)})")
    files = projector(arch)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for rel, content in files.items():
        p = out / rel
        p.write_text(content, encoding="utf-8")
        written.append(str(p))
    return {"language": language, "out_dir": str(out),
            "entities": [e["name"] for e in arch["entities"]],
            "routes": [f'{r["method"]} {r["path"]}' for r in arch["routes"]],
            "files": written, "architecture": arch}


if __name__ == "__main__":
    import sys
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    out = sys.argv[2] if len(sys.argv) > 2 else "workspaces/generated/backend"
    r = generate(spec, out)
    print(json.dumps({k: r[k] for k in ("language", "out_dir", "entities", "routes", "files")}, ensure_ascii=False, indent=1))
