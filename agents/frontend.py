"""
Frontend Agent producer.

orchestrator 계약: producer(inputs: dict) -> body: dict
  - 최종 반환은 반드시 dict(Pydantic 객체를 model_dump()). canonical 비교(No Impact)가 깨지면 안 된다.
  - 모델 호출은 llm(prompt) -> str 인터페이스로 분리. real은 Claude 서브에이전트, offline은 결정적 mock.

이 에이전트만 Pydantic으로 응답을 구조화·검증한다(다른 에이전트는 건드리지 않음).
코드 본문은 body에 넣지 않고 별도 파일(artifact)로 쓰고, body에는 화면 명세와 경로/메타만 둔다.
입력: wireframe(화면 구조), design_system(토큰·컴포넌트), backend(API 스펙).
"""

import json
import os
import re
import hashlib
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, field_validator, model_validator

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

AGENT_NAME = "agent.frontend"
SYSTEM_PROMPT = Path(__file__).with_name("agent_frontend.md").read_text(encoding="utf-8")
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "_run_frontend" / "artifacts"
REAL_MODEL_DEFAULT = "claude-sonnet-4-6"

# real 모드 지시(화면·컴포넌트 기반 프런트 산출 — 단발 1-pass. 반복·tool 루프 없음).
REAL_MODE_INSTRUCTION = (
    "\n\n## real 모드 지시(화면·컴포넌트 기반 프런트 산출 — 단발 1-pass)\n"
    "입력의 wireframe(screens)·design_system(토큰·컴포넌트)·backend(api_spec.endpoints)·ux·discovery를 받아, "
    "각 wireframe 화면을 구성하는 프런트 산출(components·data_calls·uses_tokens·states·navigation)을 생성한다.\n"
    "1. 빈 산출 금지: wireframe.screens가 있으면 screens는 비어선 안 된다. 각 화면은 대응 산출을 가진다.\n"
    "2. 발명 금지(멤버십): screen_ref는 wireframe.screens 화면명에서만, components.component_ref는 palette(wireframe.design_component_palette + design_system 컴포넌트)에서만, "
    "data_calls.endpoint_ref는 backend 엔드포인트에서만, outcome_mapping.code는 backend success/error code에서만, uses_tokens는 design_system 토큰에서만. 새 화면·컴포넌트·엔드포인트·토큰 창작 금지.\n"
    "3. 토큰만(하드코딩 색 금지): 색·간격·radius는 uses_tokens(design_system 토큰명)로만 참조한다. hex 색을 직접 쓰지 않는다.\n"
    "4. 외부 식별자: data_calls.path_params는 public_key만(내부 id/_id/pk/_pk 금지).\n"
    "5. navigation: navigation은 선택이다. 넣으려면 target_screen_ref를 wireframe 내 실제 화면명으로 반드시 채운다(null·누락 금지). "
    "마땅한 이동 대상이 없으면 그 화면의 navigation은 null로 둔다. 단일 화면(screens 1개)이면 모든 navigation은 null.\n"
    "6. 근거 없는 loading/empty 상태는 만들지 말고 open_questions로(API 사용 화면 대상).\n"
    "7. 출력은 JSON 하나만: {\"screens\":[{screen_ref, origin, components:[{component_ref,section}], "
    "data_calls:[{endpoint_ref,method,path_params,outcome_mapping:[{code,ui_hint}]}], states, uses_tokens, navigation}], "
    "\"open_questions\":[...], \"explicit_not_implemented\":[...], \"provenance\":{...}}. "
    "screen_index 등 인덱스는 시스템이 입력에서 주입하므로 출력에 없어도 된다. 설명·코드펜스 금지. 단발 1-pass(반복·도구 호출 없음)."
)

# backend가 실제 생성하는 outcome code별 UI 힌트(보완·세부, inference). 코드 자체는 backend에서만 옴.
UI_HINT = {
    "OK": "데이터 렌더링",
    "CREATED": "생성 완료 피드백",
    "NO_CONTENT": "삭제 완료 피드백",
    "VALIDATION_ERROR": "입력 오류 인라인 안내",
    "UNAUTHENTICATED": "로그인 화면 유도",
    "FORBIDDEN": "권한 없음 안내",
    "NOT_FOUND": "리소스 없음 안내",
}

CONTRACT_RULES = """## 계약 규칙(주입)
1. screen_ref는 wireframe.screens 안에서만, endpoint_ref는 backend 엔드포인트 안에서만, component_ref는 palette 안에서만, uses_tokens는 design_system 토큰 안에서만(발명 금지).
2. backend 응답 구조(success/data, error/code) 그대로 처리. 외부 식별자는 public_key만(내부 PK 금지).
3. outcome_mapping code는 backend success/error code(UNAUTHENTICATED/FORBIDDEN/NOT_FOUND/VALIDATION_ERROR/OK/CREATED)만. 도메인 특수 case는 open_questions.
4. navigation은 화면 수 > 1일 때만. 다중이면 target_screen_ref 필수(wireframe 내). 단일이면 null.
5. loading/empty/error/success 상태 근거가 wireframe/backend에 없으면 만들지 말고 open_questions(API 사용 화면 대상).
6. screen_ref/component_ref/endpoint_ref/token 중 누락 시 화면 미생성 + open_questions.
"""

PK_SUFFIXES = ("_id", "_pk")
PK_NAMES = ("id", "pk")

# Open Question 전파용 패턴(상위 산출물 open_questions 파싱). 입력 사실 기반, 발명 없음.
_PATH_RE = re.compile(r"(POST|GET|PUT|PATCH|DELETE)\s+(/api/v1/[\w/{}-]+)")
_FEAT_RE = re.compile(r"기능 '([^']+)'")
_SEM_RE = re.compile(r"의미색 '([^']+)'")


def _propagate_open_questions(wireframe, design_system, backend, screens):
    """상위 입력의 open_questions가 frontend 산출에 영향을 줄 때만 전파 기록(단순 복사 금지).
    입력 사실 기반: 상위 open_question이 실제 있고 frontend가 그 대상을 쓸 때만 기록(No-Fabrication 유지).
    반환: (propagated_open_questions[list], explicit_not_implemented[list of dict])."""
    propagated = []
    explicit_ni = []
    used_eps = {dc["endpoint_ref"] for s in screens for dc in s["data_calls"]}
    used_tokens = {t for s in screens for t in s["uses_tokens"]}
    bk_endpoints = backend.get("api_spec", {}).get("endpoints", [])
    ep_by_pm = {(e["path"], e["method"]): e["endpoint_id"] for e in bk_endpoints}

    # backend open_questions -> frontend가 그 endpoint를 호출할 때만 영향
    for oq in backend.get("open_questions", []):
        m = _PATH_RE.search(oq)
        if not m:
            continue
        method, path = m.group(1), m.group(2)
        eid = ep_by_pm.get((path, method))
        if not eid or eid not in used_eps:
            continue
        if "요청 본문 필드" in oq or "request" in oq.lower():
            propagated.append(f"[전파:backend] endpoint_ref={eid}({method} {path})의 request schema 미정 -> 입력 폼 정의 불가 (상위: {oq})")
        elif "409" in oq or "특수 case" in oq:
            propagated.append(f"[전파:backend] endpoint_ref={eid}({method} {path})의 도메인 특수 case 미정 -> 해당 실패 UI 정의 불가 (상위: {oq})")
        else:
            propagated.append(f"[전파:backend] endpoint_ref={eid} 관련 상위 미정 영향 (상위: {oq})")

    # wireframe open_questions -> 미배치 기능은 화면 구현 불가(Silent Omission 방지)
    for oq in wireframe.get("open_questions", []):
        if "화면 배치 미정" in oq or "미생성" in oq:
            fm = _FEAT_RE.search(oq)
            feat = fm.group(1) if fm else oq
            explicit_ni.append({
                "item": f"기능 '{feat}' 화면",
                "reason": "wireframe 미배치로 frontend 화면 구현 불가",
                "source_open_question": oq,
            })

    # design_system open_questions -> 해당 토큰을 frontend가 실제 사용할 때만 전파
    for oq in design_system.get("open_questions", []):
        sm = _SEM_RE.search(oq)
        if not sm:
            continue
        tok = f"color-{sm.group(1)}"
        if tok in used_tokens:
            propagated.append(f"[전파:design_system] 토큰 {tok} 미확정 -> 해당 스타일 확정 불가 (상위: {oq})")

    return propagated, explicit_ni


# ---------------- Pydantic 모델 ----------------
class OutcomeUI(BaseModel):
    code: str
    ui_hint: str


class DataCall(BaseModel):
    endpoint_ref: str
    method: str
    path_params: List[str] = []
    outcome_mapping: List[OutcomeUI] = []

    @field_validator("path_params")
    @classmethod
    def _no_internal_pk(cls, v):
        for p in v:
            if p in PK_NAMES or p.endswith(PK_SUFFIXES):
                raise ValueError(f"내부 PK 사용 금지: '{p}' (외부 식별자는 public_key만)")
        return v


class ComponentUse(BaseModel):
    component_ref: str
    section: str


class ScreenStates(BaseModel):
    loading: Optional[str] = None
    empty: Optional[str] = None
    error: Optional[str] = None
    success: Optional[str] = None


class Screen(BaseModel):
    screen_ref: str
    origin: str = "fact"
    components: List[ComponentUse] = []
    data_calls: List[DataCall] = []
    states: Optional[ScreenStates] = None
    uses_tokens: List[str] = []
    navigation: Optional[dict] = None

    @field_validator("screen_ref")
    @classmethod
    def _sref(cls, v):
        if not v or not v.strip():
            raise ValueError("screen_ref 없는 화면 생성 금지(Traceability)")
        return v


class ArtifactRef(BaseModel):
    path: str
    kind: str
    checksum: str
    bytes: int
    screen_ref: Optional[str] = None


class FrontendBody(BaseModel):
    screen_index: List[str]
    endpoint_index: List[str]
    outcome_code_index: List[str]
    component_palette: List[str]
    token_index: List[str]
    screens: List[Screen]
    artifact_refs: List[ArtifactRef] = []
    open_questions: List[str] = []
    explicit_not_implemented: List[dict] = []
    provenance: dict

    @model_validator(mode="after")
    def _cross_refs(self):
        screens_set = set(self.screen_index)
        eps = set(self.endpoint_index)
        codes = set(self.outcome_code_index)
        palette = set(self.component_palette)
        tokens = set(self.token_index)
        multi = len(self.screen_index) > 1

        seen = set()
        for s in self.screens:
            # Traceability: screen_ref ∈ wireframe
            if s.screen_ref not in screens_set:
                raise ValueError(f"발명된 screen_ref '{s.screen_ref}' (wireframe에 없음)")
            if s.screen_ref in seen:
                raise ValueError(f"중복 screen_ref '{s.screen_ref}'")
            seen.add(s.screen_ref)
            # component_ref ∈ palette
            for c in s.components:
                if c.component_ref not in palette:
                    raise ValueError(f"발명된 component_ref '{c.component_ref}' (palette에 없음)")
            # uses_tokens ∈ design token
            for t in s.uses_tokens:
                if t not in tokens:
                    raise ValueError(f"design token 밖의 값 '{t}' (token_index에 없음)")
            # data_calls: endpoint_ref ∈ backend, outcome code ∈ backend codes
            for dc in s.data_calls:
                if dc.endpoint_ref not in eps:
                    raise ValueError(f"발명된 endpoint_ref '{dc.endpoint_ref}' (backend에 없음)")
                for o in dc.outcome_mapping:
                    if o.code not in codes:
                        raise ValueError(f"발명된 outcome code '{o.code}' (backend success/error_cases에 없음)")
            # Navigation Contract
            if s.navigation is not None:
                if not multi:
                    raise ValueError(f"단일 화면은 navigation 미적용(화면 '{s.screen_ref}')")
                tgt = s.navigation.get("target_screen_ref")
                if not tgt:
                    raise ValueError(f"다중 화면 navigation은 target_screen_ref 필수(화면 '{s.screen_ref}')")
                if tgt not in screens_set:
                    raise ValueError(f"발명된 target_screen_ref '{tgt}' (wireframe에 없음)")
        return self


# ---------------- 프롬프트 조합 (E10) ----------------
def build_prompt(wireframe: dict, design_system: dict, backend: dict, ux: dict = None, discovery: dict = None):
    """real 단계: 실제 계약 입력(wireframe·design_system·backend)에 ux·discovery 맥락 추가(목표·플로우 반영)."""
    disc = {k: (discovery or {}).get(k) for k in ("goal_interpretation", "requirement_normalization")}
    payload = {"wireframe": wireframe, "design_system": design_system, "backend": backend,
               "ux": ux or {}, "discovery": disc}
    return [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + CONTRACT_RULES},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _token_set(design_system: dict):
    toks = set()
    for c in design_system.get("color_tokens", []):
        toks.add(c["token"])
    for s in design_system.get("spacing", []):
        toks.add(s["token"])
    for r in design_system.get("radius", []):
        toks.add(r["token"])
    return toks


def _indexes(wf: dict, ds: dict, bk: dict) -> dict:
    """멤버십 인덱스(권위값)를 입력에서 결정적으로 계산한다. offline 산출과 동일 로직.
    real에서도 이 값을 주입해 LLM이 인덱스를 위조하지 못하게 한다(발명 검사 의미 보장)."""
    wf_screens = wf.get("screens", [])
    palette_set = set(wf.get("design_component_palette", [])) | {c["component"] for c in ds.get("component_specs", [])}
    endpoints = bk.get("api_spec", {}).get("endpoints", [])
    outcome_codes = sorted({c["code"] for e in endpoints for c in e["success_cases"]}
                           | {c["code"] for e in endpoints for c in e["error_cases"]})
    return {
        "screen_index": [s["screen"] for s in wf_screens],
        "endpoint_index": [e["endpoint_id"] for e in endpoints],
        "outcome_code_index": outcome_codes,
        "component_palette": sorted(palette_set),
        "token_index": sorted(_token_set(ds)),
    }


def offline_llm(prompt) -> str:
    """결정적 mock. wireframe/design_system/backend 입력에서만 화면을 구성. 발명 금지."""
    user = next(m["content"] for m in prompt if m["role"] == "user")
    data = json.loads(user)
    wf = data.get("wireframe", {}) or {}
    ds = data.get("design_system", {}) or {}
    bk = data.get("backend", {}) or {}

    wf_screens = wf.get("screens", [])
    screen_names = [s["screen"] for s in wf_screens]
    palette = list(wf.get("design_component_palette", []))
    palette_set = set(palette) | {c["component"] for c in ds.get("component_specs", [])}
    token_set = _token_set(ds)
    ds_comp_tokens = {c["component"]: c.get("uses_tokens", []) for c in ds.get("component_specs", [])}

    endpoints = bk.get("api_spec", {}).get("endpoints", [])
    endpoint_index = [e["endpoint_id"] for e in endpoints]
    outcome_codes = sorted({c["code"] for e in endpoints for c in e["success_cases"]}
                           | {c["code"] for e in endpoints for c in e["error_cases"]})
    eps_by_feature = {}
    for e in endpoints:
        eps_by_feature.setdefault(e["feature_ref"], []).append(e)

    screens = []
    open_questions = []
    multi = len(screen_names) > 1

    for wscreen in wf_screens:
        sref = wscreen.get("screen")
        secs = wscreen.get("sections", [])
        missing = []

        # components (palette 안에서만)
        components = []
        for sec in secs:
            for c in sec.get("components", []):
                if c in palette_set:
                    components.append({"component_ref": c, "section": sec.get("section")})
        if not components:
            missing.append("component_ref")

        # data_calls: 화면 섹션 feature_refs와 같은 backend 엔드포인트
        feat_refs = {fr for sec in secs for fr in sec.get("feature_refs", [])}
        data_calls = []
        for e in endpoints:
            if e["feature_ref"] in feat_refs:
                path_params = ["public_key"] if "{public_key}" in e["path"] else []
                data_calls.append({
                    "endpoint_ref": e["endpoint_id"], "method": e["method"],
                    "path_params": path_params,
                    "outcome_mapping": [{"code": c["code"], "ui_hint": UI_HINT.get(c["code"], c["code"])}
                                        for c in (e["success_cases"] + e["error_cases"])],
                })
        api_used = bool(data_calls)

        # uses_tokens: 화면 컴포넌트들이 쓰는 design_system 토큰(토큰 안에서만)
        uses_tokens = sorted({t for c in components for t in ds_comp_tokens.get(c["component_ref"], [])
                              if t in token_set})
        if not uses_tokens:
            missing.append("design token")

        if not sref or sref not in screen_names:
            missing.append("screen_ref")

        # Blocking Rule
        if missing:
            open_questions.append(f"화면 '{sref}' 미생성(Blocking): 누락 {missing}")
            continue

        # State Contract: API 사용 화면은 상태 검토. loading/empty 근거 없음 -> 미구현 + open_questions.
        if api_used:
            open_questions.append(
                f"화면 '{sref}'(API 사용): loading/empty 상태 근거가 wireframe/backend에 없음 -> 미구현(검토 필요). "
                f"success/error는 outcome_mapping으로 처리")

        # Navigation Contract: 단일 화면이면 미적용(null)
        navigation = None
        if multi:
            navigation = {"pattern": wf.get("navigation", {}).get("pattern"), "target_screen_ref": None}

        screens.append({
            "screen_ref": sref, "origin": "fact",
            "components": components, "data_calls": data_calls,
            "states": None, "uses_tokens": uses_tokens, "navigation": navigation,
        })

    # Open Question Propagation + Dependency Gap + Silent Omission(입력 사실 기반)
    propagated, explicit_ni = _propagate_open_questions(wf, ds, bk, screens)
    open_questions.extend(propagated)

    result = {
        "screen_index": screen_names,
        "endpoint_index": endpoint_index,
        "outcome_code_index": outcome_codes,
        "component_palette": sorted(palette_set),
        "token_index": sorted(token_set),
        "screens": screens,
        "open_questions": open_questions,
        "explicit_not_implemented": explicit_ni,
        "provenance": {
            "screens": "per_item", "components": "fact", "data_calls": "fact",
            "outcome_mapping": "fact", "uses_tokens": "fact", "ui_hint": "inference",
            "states": "open", "navigation": "inference",
            "propagated_open_questions": "fact", "explicit_not_implemented": "fact",
        },
    }
    return json.dumps(result, ensure_ascii=False)


def _extract_json(text: str) -> str:
    text = text.replace("```json", "").replace("```", "").strip()
    i, j = text.find("{"), text.rfind("}")
    return text[i:j + 1] if i != -1 and j != -1 and j > i else text


def make_real_llm(model=REAL_MODEL_DEFAULT, max_tokens=16000):
    """real llm(prompt_messages) -> str. Anthropic messages API(검색 없음, 단발 1-pass).
    실패(SDK 미설치/키 없음/네트워크/API 에러)는 RuntimeError — execute에서 offline 폴백."""
    def real_llm(prompt) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError("real 모드 불가: anthropic SDK 미설치") from e
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("real 모드 불가: ANTHROPIC_API_KEY 없음")
        system = next(m["content"] for m in prompt if m["role"] == "system") + REAL_MODE_INSTRUCTION
        user = next(m["content"] for m in prompt if m["role"] == "user")
        client = anthropic.Anthropic(api_key=api_key)
        try:
            resp = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                          messages=[{"role": "user", "content": user}])
        except Exception as e:
            raise RuntimeError(f"real 모드 Anthropic API 호출 실패: {type(e).__name__}: {e}") from e
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if not text:
            raise RuntimeError("real 모드: Anthropic 응답에 텍스트 없음")
        return _extract_json(text)
    return real_llm


real_llm = make_real_llm()


def execute(wireframe: dict, design_system: dict, backend: dict, ux: dict = None, discovery: dict = None, llm=offline_llm) -> str:
    prompt = build_prompt(wireframe, design_system, backend, ux, discovery)
    try:
        return llm(prompt)
    except RuntimeError:
        return offline_llm(prompt)  # real 실패 -> offline 폴백


def _render_stub(s: Screen) -> str:
    comps = ", ".join(c.component_ref for c in s.components)
    calls = ", ".join(d.endpoint_ref for d in s.data_calls)
    return (
        "// Auto-generated screen stub (do not edit by hand)\n"
        f"// screen_ref: {s.screen_ref}\n"
        f"// components: {comps}\n"
        f"// data_calls: {calls}\n"
        f"// uses_tokens: {', '.join(s.uses_tokens)}\n\n"
        "export function Screen() {\n"
        f"  // render: {comps}\n"
        f"  // calls: {calls}\n"
        "  throw new Error('not implemented');\n"
        "}\n"
    )


def produce(inputs: dict, llm=offline_llm, artifact_dir: Path = DEFAULT_ARTIFACT_DIR) -> dict:
    wireframe = inputs["wireframe"]
    design_system = inputs.get("design_system", {})
    backend = inputs.get("backend", {})
    ux = inputs.get("ux", {})
    discovery = inputs.get("discovery", {})  # v15: 목표·플로우 맥락(real 프롬프트)
    raw = execute(wireframe, design_system, backend, ux, discovery, llm)
    spec = json.loads(raw)
    spec["artifact_refs"] = []
    # 멤버십 인덱스는 입력에서 권위값으로 강제 주입(LLM 위조 차단 -> 발명 검사 의미 보장). offline은 동일값이라 무영향.
    spec.update(_indexes(wireframe, design_system, backend))
    # real 산출 방어적 정규화(단발, 루프 없음): explicit_not_implemented는 dict 리스트(문자열이면 래핑), open_questions는 문자열 리스트.
    eni = spec.get("explicit_not_implemented") or []
    spec["explicit_not_implemented"] = [e if isinstance(e, dict) else {"item": str(e), "reason": "real 보고"} for e in eni]
    spec["open_questions"] = [q if isinstance(q, str) else json.dumps(q, ensure_ascii=False) for q in (spec.get("open_questions") or [])]

    # Pydantic 검증(계약 강제: screen_ref/endpoint_ref/component_ref/token/outcome 멤버십). 위반 시 여기서 raise.
    fb = FrontendBody(**spec)

    # D9: 코드는 artifact 파일로, body에는 경로/메타만.
    artifact_dir = Path(artifact_dir)
    screens_dir = artifact_dir / "screens"
    screens_dir.mkdir(parents=True, exist_ok=True)
    refs = []
    for i, s in enumerate(fb.screens):
        code = _render_stub(s)
        rel = f"screens/screen-{i + 1}.jsx"
        (artifact_dir / rel).write_text(code, encoding="utf-8")
        refs.append({
            "path": rel, "kind": "screen_stub",
            "checksum": hashlib.sha256(code.encode("utf-8")).hexdigest()[:16],
            "bytes": len(code.encode("utf-8")), "screen_ref": s.screen_ref,
        })

    spec["artifact_refs"] = refs
    final = FrontendBody(**spec)
    return final.model_dump()


def make_producer(llm=offline_llm, artifact_dir: Path = DEFAULT_ARTIFACT_DIR):
    """orchestrator에 등록할 producer(inputs)->body 클로저. llm·artifact_dir 주입은 클로저로(구조 변경 없음)."""
    def producer(inputs):
        return produce(inputs, llm=llm, artifact_dir=artifact_dir)
    return producer
