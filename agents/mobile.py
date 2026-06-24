"""
Mobile Agent producer.

orchestrator 계약: producer(inputs: dict) -> body: dict
입력·계약은 Frontend와 동일(wireframe·design_system·backend). 차이는 모바일 특성뿐.
  - 최종 반환은 반드시 dict(Pydantic 객체를 model_dump()). canonical 비교(No Impact) 유지.
  - 모델 호출은 llm(prompt) -> str. real은 Claude 서브에이전트, offline은 결정적 mock.

모바일 고유(bottom nav / 터치 타겟 / 다크모드 / safe area)는 design_system·wireframe에 근거가 있을 때만 적용.
코드 본문은 body에 넣지 않고 별도 파일(artifact)로 쓰고, body에는 화면 명세와 경로/메타만 둔다.
"""

import json
import re
import hashlib
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, field_validator, model_validator

AGENT_NAME = "agent.mobile"
SYSTEM_PROMPT = Path(__file__).with_name("agent_mobile.md").read_text(encoding="utf-8")
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "_run_mobile" / "artifacts"

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
1. screen_ref∈wireframe, endpoint_ref∈backend, component_ref∈palette, uses_tokens∈design token만(발명 금지).
2. backend 응답 구조(success/data, error/code) 그대로 처리. 외부 식별자는 public_key만(내부 PK 금지).
3. outcome_mapping code는 backend success/error code만. 도메인 특수 case는 open_questions.
4. 단일 화면이면 navigation null. 다중이면 bottom-tab + target_screen_ref(wireframe 내).
5. 입력 부족 미구현은 open_questions 또는 explicit_not_implemented(Silent Omission 금지).
6. 모바일 요소(터치타겟/다크모드/safe area)는 design_system 근거 있을 때만. 없으면 open_questions.
"""

PK_SUFFIXES = ("_id", "_pk")
PK_NAMES = ("id", "pk")

_PATH_RE = re.compile(r"(POST|GET|PUT|PATCH|DELETE)\s+(/api/v1/[\w/{}-]+)")
_FEAT_RE = re.compile(r"기능 '([^']+)'")
_SEM_RE = re.compile(r"의미색 '([^']+)'")

INTERACTIVE = ("button", "input", "nav")


def _propagate_open_questions(wireframe, design_system, backend, screens):
    """Frontend와 동일 정책. 상위 open_question이 mobile 산출에 영향 줄 때만 전파(단순 복사 금지, 영향 함께 기록).
    입력 사실 기반(No-Fabrication). 반환: (propagated[list], explicit_not_implemented[list])."""
    propagated = []
    explicit_ni = []
    used_eps = {dc["endpoint_ref"] for s in screens for dc in s["data_calls"]}
    used_tokens = {t for s in screens for t in s["uses_tokens"]}
    bk_endpoints = backend.get("api_spec", {}).get("endpoints", [])
    ep_by_pm = {(e["path"], e["method"]): e["endpoint_id"] for e in bk_endpoints}

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

    for oq in wireframe.get("open_questions", []):
        if "화면 배치 미정" in oq or "미생성" in oq:
            fm = _FEAT_RE.search(oq)
            feat = fm.group(1) if fm else oq
            explicit_ni.append({
                "item": f"기능 '{feat}' 화면",
                "reason": "wireframe 미배치로 mobile 화면 구현 불가",
                "source_open_question": oq,
            })

    for oq in design_system.get("open_questions", []):
        sm = _SEM_RE.search(oq)
        if not sm:
            continue
        tok = f"color-{sm.group(1)}"
        if tok in used_tokens:
            propagated.append(f"[전파:design_system] 토큰 {tok} 미확정 -> 해당 스타일 확정 불가 (상위: {oq})")

    return propagated, explicit_ni


# ---------------- Pydantic 모델 (Frontend와 동일 + 모바일 필드) ----------------
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


class MobileScreen(BaseModel):
    screen_ref: str
    origin: str = "fact"
    components: List[ComponentUse] = []
    data_calls: List[DataCall] = []
    states: Optional[dict] = None
    uses_tokens: List[str] = []
    navigation: Optional[dict] = None
    # 모바일 고유(근거 있을 때만 채움, 없으면 None)
    touch_target: Optional[dict] = None
    dark_mode: Optional[dict] = None
    safe_area: Optional[dict] = None

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


class MobileBody(BaseModel):
    platform: str = "mobile"
    screen_index: List[str]
    endpoint_index: List[str]
    outcome_code_index: List[str]
    component_palette: List[str]
    token_index: List[str]
    screens: List[MobileScreen]
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
            if s.screen_ref not in screens_set:
                raise ValueError(f"발명된 screen_ref '{s.screen_ref}' (wireframe에 없음)")
            if s.screen_ref in seen:
                raise ValueError(f"중복 screen_ref '{s.screen_ref}'")
            seen.add(s.screen_ref)
            for c in s.components:
                if c.component_ref not in palette:
                    raise ValueError(f"발명된 component_ref '{c.component_ref}' (palette에 없음)")
            for t in s.uses_tokens:
                if t not in tokens:
                    raise ValueError(f"design token 밖의 값 '{t}' (token_index에 없음)")
            for dc in s.data_calls:
                if dc.endpoint_ref not in eps:
                    raise ValueError(f"발명된 endpoint_ref '{dc.endpoint_ref}' (backend에 없음)")
                for o in dc.outcome_mapping:
                    if o.code not in codes:
                        raise ValueError(f"발명된 outcome code '{o.code}' (backend success/error_cases에 없음)")
            if s.navigation is not None:
                if not multi:
                    raise ValueError(f"단일 화면은 navigation 미적용(화면 '{s.screen_ref}')")
                tgt = s.navigation.get("target_screen_ref")
                if not tgt:
                    raise ValueError(f"다중 화면 navigation은 target_screen_ref 필수(화면 '{s.screen_ref}')")
                if tgt not in screens_set:
                    raise ValueError(f"발명된 target_screen_ref '{tgt}' (wireframe에 없음)")
        return self


# ---------------- 프롬프트 조합 ----------------
def build_prompt(wireframe: dict, design_system: dict, backend: dict):
    return [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + CONTRACT_RULES},
        {"role": "user", "content": json.dumps(
            {"wireframe": wireframe, "design_system": design_system, "backend": backend}, ensure_ascii=False)},
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


def offline_llm(prompt) -> str:
    """결정적 mock. wireframe/design_system/backend 입력에서만 모바일 화면 구성. 발명 금지."""
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

    # 모바일 고유 근거(design_system에서만)
    acc = ds.get("accessibility", {}) or {}
    touch_min = acc.get("min_touch_target")
    dark_tokens = {c["token"] for c in ds.get("color_tokens", []) if c.get("mode") == "dark"}
    safe_inset = acc.get("safe_area") or acc.get("safe_area_inset")
    multi = len(screen_names) > 1

    screens = []
    open_questions = []

    if not palette:
        open_questions.append("design_system 컴포넌트 없음: 화면 배치 불가(No-Fabrication)")
    if not wf_screens:
        open_questions.append("wireframe.screens 없음: 화면 구조 도출 불가")

    for wscreen in wf_screens:
        sref = wscreen.get("screen")
        secs = wscreen.get("sections", [])
        missing = []

        components = []
        for sec in secs:
            for c in sec.get("components", []):
                if c in palette_set:
                    components.append({"component_ref": c, "section": sec.get("section")})
        if not components:
            missing.append("component_ref")

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

        uses_tokens = sorted({t for c in components for t in ds_comp_tokens.get(c["component_ref"], [])
                              if t in token_set})
        if not uses_tokens:
            missing.append("design token")

        if not sref or sref not in screen_names:
            missing.append("screen_ref")

        if missing:
            open_questions.append(f"화면 '{sref}' 미생성(Blocking): 누락 {missing}")
            continue

        if api_used:
            open_questions.append(
                f"화면 '{sref}'(API 사용): loading/empty 상태 근거가 wireframe/backend에 없음 -> 미구현(검토 필요). "
                f"success/error는 outcome_mapping으로 처리")

        # 모바일 고유: 근거 있을 때만 적용, 없으면 open_questions
        touch_target = None
        if touch_min:
            interactive = sorted({c["component_ref"] for c in components if c["component_ref"] in INTERACTIVE})
            touch_target = {"min_size": touch_min, "applies_to": interactive}
        else:
            open_questions.append(f"화면 '{sref}': 터치 타겟 근거(design_system.accessibility.min_touch_target) 없음 -> 미적용")

        dark_mode = None
        if dark_tokens:
            overrides = sorted(set(uses_tokens) & dark_tokens)
            dark_mode = {"enabled": True, "dark_token_overrides": overrides}
        else:
            open_questions.append(f"화면 '{sref}': 다크 토큰(mode==dark) 없음 -> 다크모드 미적용(임의 색 발명 금지)")

        safe_area = None
        if safe_inset:
            safe_area = {"inset": safe_inset}
        else:
            open_questions.append(f"화면 '{sref}': safe-area 근거가 design_system/wireframe에 없음 -> 미적용(검토 필요)")

        # Navigation: 단일 화면이면 미적용(null), 다중이면 bottom-tab
        navigation = None
        if multi:
            navigation = {"pattern": "bottom-tab",
                          "items": list(screen_names),
                          "target_screen_ref": next((n for n in screen_names if n != sref), None),
                          "uses_component": "nav" if "nav" in palette_set else None}

        screens.append({
            "screen_ref": sref, "origin": "fact",
            "components": components, "data_calls": data_calls,
            "states": None, "uses_tokens": uses_tokens, "navigation": navigation,
            "touch_target": touch_target, "dark_mode": dark_mode, "safe_area": safe_area,
        })

    propagated, explicit_ni = _propagate_open_questions(wf, ds, bk, screens)
    open_questions.extend(propagated)

    result = {
        "platform": "mobile",
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
            "touch_target": "fact", "dark_mode": "fact", "safe_area": "open",
            "propagated_open_questions": "fact", "explicit_not_implemented": "fact",
        },
    }
    return json.dumps(result, ensure_ascii=False)


def execute(wireframe: dict, design_system: dict, backend: dict, llm=offline_llm) -> str:
    prompt = build_prompt(wireframe, design_system, backend)
    return llm(prompt)


def _render_stub(s: MobileScreen) -> str:
    comps = ", ".join(c.component_ref for c in s.components)
    calls = ", ".join(d.endpoint_ref for d in s.data_calls)
    touch = s.touch_target.get("min_size") if s.touch_target else "n/a"
    dark = "on" if s.dark_mode else "off"
    return (
        "// Auto-generated mobile screen stub (do not edit by hand)\n"
        f"// screen_ref: {s.screen_ref}\n"
        f"// components: {comps}\n"
        f"// data_calls: {calls}\n"
        f"// touch_target: {touch} | dark_mode: {dark}\n\n"
        "export function MobileScreen() {\n"
        f"  // render: {comps}\n"
        f"  // calls: {calls}\n"
        "  throw new Error('not implemented');\n"
        "}\n"
    )


def produce(inputs: dict, llm=offline_llm, artifact_dir: Path = DEFAULT_ARTIFACT_DIR) -> dict:
    wireframe = inputs["wireframe"]
    design_system = inputs.get("design_system", {})
    backend = inputs.get("backend", {})
    raw = execute(wireframe, design_system, backend, llm)
    spec = json.loads(raw)
    spec["artifact_refs"] = []

    mb = MobileBody(**spec)

    artifact_dir = Path(artifact_dir)
    screens_dir = artifact_dir / "screens"
    screens_dir.mkdir(parents=True, exist_ok=True)
    refs = []
    for i, s in enumerate(mb.screens):
        code = _render_stub(s)
        rel = f"screens/mobile-screen-{i + 1}.jsx"
        (artifact_dir / rel).write_text(code, encoding="utf-8")
        refs.append({
            "path": rel, "kind": "mobile_screen_stub",
            "checksum": hashlib.sha256(code.encode("utf-8")).hexdigest()[:16],
            "bytes": len(code.encode("utf-8")), "screen_ref": s.screen_ref,
        })

    spec["artifact_refs"] = refs
    final = MobileBody(**spec)
    return final.model_dump()


def make_producer(llm=offline_llm, artifact_dir: Path = DEFAULT_ARTIFACT_DIR):
    """orchestrator에 등록할 producer(inputs)->body 클로저. llm·artifact_dir 주입은 클로저로(구조 변경 없음)."""
    def producer(inputs):
        return produce(inputs, llm=llm, artifact_dir=artifact_dir)
    return producer
