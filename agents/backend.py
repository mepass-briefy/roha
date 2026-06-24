"""
Backend (API) Agent producer.

orchestrator 계약: producer(inputs: dict) -> body: dict
  - 최종 반환은 반드시 dict다(Pydantic 객체를 model_dump()로 변환). canonical 비교(No Impact)가 깨지면 안 된다.
  - 모델 호출은 llm(prompt) -> str 인터페이스로 분리한다. real은 Claude 서브에이전트, offline은 결정적 mock.

이 에이전트만 Pydantic으로 응답을 구조화·검증한다(다른 에이전트는 건드리지 않음).
코드 본문은 body에 넣지 않고 별도 파일(artifact)로 쓰고, body에는 경로/메타와 api_spec만 둔다.
"""

import json
import re
import hashlib
from pathlib import Path
from typing import List, Optional, Any

from pydantic import BaseModel, field_validator

AGENT_NAME = "agent.backend"
SYSTEM_PROMPT = Path(__file__).with_name("agent_backend.md").read_text(encoding="utf-8")
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "_run_backend" / "artifacts"

# 고정 Response Contract (임의 변경 금지)
RESPONSE_CONTRACT = {
    "success": {"success": True, "data": {}},
    "error": {"success": False, "error": {"code": "", "message": ""}},
}

# 동적 프롬프트에 주입할 계약 규칙(4~14 요약)
CONTRACT_RULES = """## 계약 규칙(주입)
1. /api/v1 prefix, resource 기반 REST, URL kebab-case. Collection=/resources, Item=/resources/{public_key}. URL에 id/pk 노출 금지.
2. 외부 노출은 public_key만. business_key는 검색·운영, PK는 내부 FK(외부 미노출).
3. Response Contract 고정: 성공 {success:true,data:{}}, 실패 {success:false,error:{code,message}}.
4. 모든 endpoint는 endpoint_id, feature_ref, security_ref 필수. 참조는 입력 features/security 안에서만.
5. request 필드는 type,required,format,min/max,enum(해당시) 명시.
6. 가변·대량 목록만 cursor pagination(cursor,limit / items,next_cursor). 제외 판단은 메모.
7. 모든 endpoint는 success_cases/error_cases 필수({code,http_status,description}).
8. error.code는 그 endpoint error_cases 코드만 허용.
9. 표준 case(200/201/204/400/401/403/404)는 메서드·권한에서 자동 도출(inference). 도메인 특수(409/202 등)는 근거 있을 때만, 없으면 open_questions.
10. acceptance는 features.acceptance_criteria에서 매핑. 근거 없으면 open_questions.
"""

CORE_ORIGINS = ("fact", "human")
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

# 기능 키워드 -> 영문 리소스(결정적). 매칭 없으면 리소스 도출 불가로 open_questions.
RESOURCE_RULES = [
    ("신청", "applications"), ("예약", "reservations"), ("정산", "settlements"),
    ("매치", "matches"), ("후기", "reviews"), ("회원", "members"), ("결제", "payments"),
]

_SEG_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*$")


# ---------------- Pydantic 모델 (B: 검증) ----------------
class RequestField(BaseModel):
    name: str
    type: str
    required: bool
    format: str
    min: Optional[Any] = None
    max: Optional[Any] = None
    enum: Optional[List[Any]] = None

    @field_validator("name", "type", "format")
    @classmethod
    def _non_empty(cls, v, info):
        if not v or not str(v).strip():
            raise ValueError(f"request 필드 '{info.field_name}' 생략 금지(type/required/format 명시 필수)")
        return v


class OutcomeCase(BaseModel):
    code: str
    http_status: int
    description: str

    @field_validator("code")
    @classmethod
    def _code_non_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("outcome case code 누락")
        return v


class Endpoint(BaseModel):
    endpoint_id: str
    method: str
    path: str
    feature_ref: str
    security_ref: str
    request_schema: List[RequestField] = []
    success_cases: List[OutcomeCase]
    error_cases: List[OutcomeCase]
    acceptance_criteria: List[str] = []
    pagination: Optional[dict] = None
    provenance: dict = {}

    @field_validator("endpoint_id")
    @classmethod
    def _eid(cls, v):
        if not v or not v.strip():
            raise ValueError("endpoint_id 필수")
        return v

    @field_validator("method")
    @classmethod
    def _method(cls, v):
        if v not in HTTP_METHODS:
            raise ValueError(f"허용되지 않은 method '{v}'")
        return v

    @field_validator("feature_ref")
    @classmethod
    def _feature_ref(cls, v):
        if not v or not v.strip():
            raise ValueError("feature_ref 없는 endpoint 생성 금지(Traceability)")
        return v

    @field_validator("security_ref")
    @classmethod
    def _security_ref(cls, v):
        if not v or not v.strip():
            raise ValueError("security_ref 없는 권한/검증 생성 금지(Traceability)")
        return v

    @field_validator("path")
    @classmethod
    def _path(cls, v):
        if not v.startswith("/api/v1/"):
            raise ValueError(f"Naming 위반: /api/v1 prefix 필요 ('{v}')")
        segs = [s for s in v.split("/") if s]  # api, v1, ...
        for seg in segs[2:]:
            if seg.startswith("{") and seg.endswith("}"):
                inner = seg[1:-1]
                if inner != "public_key":
                    raise ValueError(f"URL 내부 식별자 노출 금지: '{seg}' (path param은 {{public_key}}만)")
            else:
                if seg in ("id", "pk"):
                    raise ValueError(f"URL 내부 식별자 노출 금지: '{seg}'")
                if not _SEG_RE.match(seg):
                    raise ValueError(f"kebab-case 위반: '{seg}'")
        return v

    @field_validator("success_cases", "error_cases")
    @classmethod
    def _cases_non_empty(cls, v, info):
        if not v:
            raise ValueError(f"{info.field_name} 필수(Outcome Contract)")
        return v


class ApiSpec(BaseModel):
    response_contract: dict
    endpoints: List[Endpoint]

    @field_validator("response_contract")
    @classmethod
    def _fixed_contract(cls, v):
        if v != RESPONSE_CONTRACT:
            raise ValueError("Response Contract 포맷 임의 변경 금지")
        return v


class ArtifactRef(BaseModel):
    path: str
    kind: str
    checksum: str
    bytes: int
    endpoint_id: Optional[str] = None


class BackendBody(BaseModel):
    api_spec: ApiSpec
    artifact_refs: List[ArtifactRef] = []
    open_questions: List[str] = []
    provenance: dict


# ---------------- Response 헬퍼 (C11: error.code enum 강제) ----------------
def success_response(data: dict) -> dict:
    return {"success": True, "data": data}


def error_response(endpoint: Endpoint, code: str, message: str) -> dict:
    allowed = {c.code for c in endpoint.error_cases}
    if code not in allowed:
        raise ValueError(f"error.code '{code}'는 endpoint '{endpoint.endpoint_id}'의 error_cases에 없음(외부 코드 차단)")
    return {"success": False, "error": {"code": code, "message": message}}


# ---------------- 표준/도메인 case 도출 (C9: 2층 분리) ----------------
def _standard_cases(method, kind):
    common_err = [
        {"code": "VALIDATION_ERROR", "http_status": 400, "description": "요청 검증 실패"},
        {"code": "UNAUTHENTICATED", "http_status": 401, "description": "인증 필요"},
        {"code": "FORBIDDEN", "http_status": 403, "description": "권한 없음"},
    ]
    not_found = {"code": "NOT_FOUND", "http_status": 404, "description": "리소스 없음"}
    if method == "GET" and kind == "list":
        return [{"code": "OK", "http_status": 200, "description": "조회 성공"}], list(common_err)
    if method == "GET" and kind == "item":
        return [{"code": "OK", "http_status": 200, "description": "조회 성공"}], common_err + [not_found]
    if method == "POST":
        return [{"code": "CREATED", "http_status": 201, "description": "생성 성공"}], list(common_err)
    if method in ("PUT", "PATCH"):
        return [{"code": "OK", "http_status": 200, "description": "수정 성공"}], common_err + [not_found]
    if method == "DELETE":
        return [{"code": "NO_CONTENT", "http_status": 204, "description": "삭제 성공"}], common_err + [not_found]
    return [{"code": "OK", "http_status": 200, "description": "성공"}], list(common_err)


def _resolve_resource(feature_name):
    for kw, res in RESOURCE_RULES:
        if kw in feature_name:
            return res
    return None


def build_prompt(features: dict, security: dict):
    """E15: 시스템 프롬프트 + 입력 데이터 + 계약 규칙을 조합한 메시지 배열."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + CONTRACT_RULES},
        {"role": "user", "content": json.dumps({"features": features, "security": security}, ensure_ascii=False)},
    ]


def offline_llm(prompt) -> str:
    """결정적 mock. 프롬프트 메시지의 user 입력에서 endpoints를 생성한다. 발명 금지."""
    user = next(m["content"] for m in prompt if m["role"] == "user")
    data = json.loads(user)
    features = data.get("features", {}) or {}
    security = data.get("security", {}) or {}

    feat_list = features.get("features", [])
    control_set = {r.get("control") for r in security.get("security_requirements", [])}

    endpoints = []
    open_questions = []

    for f in feat_list:
        if f.get("origin") not in CORE_ORIGINS:
            continue  # 보완(inference) 기능은 API 핵심 도출 대상 아님
        fname = f["feature"]
        # security_ref: 입력 security 통제 안에서만(발명 금지)
        sec_ref = next((c for c in f.get("security_controls", []) if c in control_set), None)
        if not sec_ref:
            open_questions.append(f"기능 '{fname}': 입력 security에 매핑되는 통제 없음 -> 권한 정의 보류")
            continue
        resource = _resolve_resource(fname)
        if not resource:
            open_questions.append(f"기능 '{fname}': 리소스명 도출 불가(키워드 미매칭) -> 입력 확인 필요")
            continue
        acc = f.get("acceptance_criteria", [])
        if not acc:
            open_questions.append(f"기능 '{fname}': acceptance_criteria 근거 없음")

        # 1) Collection GET (가변·대량 목록 가정 -> cursor pagination)
        succ, err = _standard_cases("GET", "list")
        endpoints.append({
            "endpoint_id": f"ep-{resource}-list", "method": "GET", "path": f"/api/v1/{resource}",
            "feature_ref": fname, "security_ref": sec_ref,
            "request_schema": [
                {"name": "cursor", "type": "string", "required": False, "format": "opaque-cursor", "min": None, "max": None, "enum": None},
                {"name": "limit", "type": "integer", "required": False, "format": "int32", "min": 1, "max": 100, "enum": None},
            ],
            "success_cases": succ, "error_cases": err,
            "acceptance_criteria": list(acc),
            "pagination": {"request": ["cursor", "limit"], "response": ["items", "next_cursor"]},
            "provenance": {"standard_cases": "inference", "feature_ref": "fact", "security_ref": "fact", "request_schema": "inference"},
        })
        # 2) Collection POST (create) — 도메인 요청 필드는 근거 없음 -> open_questions
        succ, err = _standard_cases("POST", "create")
        open_questions.append(f"POST /api/v1/{resource}: 요청 본문 필드는 도메인 정의 필요(발명 금지)")
        open_questions.append(f"POST /api/v1/{resource}: 409 중복 등 도메인 특수 case 근거 없음 -> 확인 필요")
        endpoints.append({
            "endpoint_id": f"ep-{resource}-create", "method": "POST", "path": f"/api/v1/{resource}",
            "feature_ref": fname, "security_ref": sec_ref,
            "request_schema": [],
            "success_cases": succ, "error_cases": err,
            "acceptance_criteria": list(acc),
            "pagination": None,
            "provenance": {"standard_cases": "inference", "feature_ref": "fact", "security_ref": "fact", "request_schema": "inference"},
        })
        # 3) Item GET (public_key만 노출)
        succ, err = _standard_cases("GET", "item")
        endpoints.append({
            "endpoint_id": f"ep-{resource}-get", "method": "GET", "path": f"/api/v1/{resource}/{{public_key}}",
            "feature_ref": fname, "security_ref": sec_ref,
            "request_schema": [
                {"name": "public_key", "type": "string", "required": True, "format": "public-key", "min": None, "max": None, "enum": None},
            ],
            "success_cases": succ, "error_cases": err,
            "acceptance_criteria": list(acc),
            "pagination": None,
            "provenance": {"standard_cases": "inference", "feature_ref": "fact", "security_ref": "fact", "request_schema": "inference"},
        })

    result = {
        "api_spec": {"response_contract": RESPONSE_CONTRACT, "endpoints": endpoints},
        "open_questions": open_questions,
        "provenance": {"endpoints": "per_item", "request_schema": "inference",
                       "acceptance_criteria": "fact", "domain_cases": "fact"},
    }
    return json.dumps(result, ensure_ascii=False)


def execute(features: dict, security: dict, llm=offline_llm) -> str:
    """E15/E16: 프롬프트 조합 후 (mock) LLM 호출."""
    prompt = build_prompt(features, security)
    return llm(prompt)


def _render_stub(ep: Endpoint) -> str:
    """결정적 라우트 스텁 코드. body가 아니라 artifact로 나간다(F17)."""
    fn = ep.endpoint_id.replace("-", "_")
    return (
        "# Auto-generated route stub (do not edit by hand)\n"
        f"# endpoint_id: {ep.endpoint_id}\n"
        f"# {ep.method} {ep.path}\n"
        f"# feature_ref: {ep.feature_ref}\n"
        f"# security_ref: {ep.security_ref}\n\n"
        f"def handle_{fn}(request):\n"
        f"    \"\"\"{ep.method} {ep.path}\"\"\"\n"
        "    raise NotImplementedError\n"
    )


def produce(inputs: dict, llm=offline_llm, artifact_dir: Path = DEFAULT_ARTIFACT_DIR) -> dict:
    features = inputs["features"]
    security = inputs.get("security", {})
    raw = execute(features, security, llm)
    spec = json.loads(raw)

    # B: Pydantic 검증(엔드포인트 계약 강제). 위반 시 여기서 raise.
    api_spec = ApiSpec(**spec["api_spec"])

    # F17: 코드는 artifact 파일로, body에는 경로/메타만.
    artifact_dir = Path(artifact_dir)
    routes_dir = artifact_dir / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    artifact_refs = []
    for ep in api_spec.endpoints:
        code = _render_stub(ep)
        rel = f"routes/{ep.endpoint_id}.py"
        (artifact_dir / rel).write_text(code, encoding="utf-8")
        artifact_refs.append(ArtifactRef(
            path=rel, kind="route_stub",
            checksum=hashlib.sha256(code.encode("utf-8")).hexdigest()[:16],
            bytes=len(code.encode("utf-8")), endpoint_id=ep.endpoint_id,
        ))

    body_model = BackendBody(
        api_spec=api_spec, artifact_refs=artifact_refs,
        open_questions=spec["open_questions"], provenance=spec["provenance"],
    )
    # A2: 반드시 dict 반환(canonical 비교용)
    return body_model.model_dump()


def make_producer(llm=offline_llm, artifact_dir: Path = DEFAULT_ARTIFACT_DIR):
    """orchestrator에 등록할 producer(inputs)->body 클로저. llm·artifact_dir 주입은 클로저로(구조 변경 없음)."""
    def producer(inputs):
        return produce(inputs, llm=llm, artifact_dir=artifact_dir)
    return producer
