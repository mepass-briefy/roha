"""
Wireframe Agent producer.

orchestrator 계약: producer(inputs: dict) -> body: dict
모델 호출은 llm(system, user) -> str 인터페이스로 분리한다.
  - real: 기능·컴포넌트·정보구조를 종합하는 Claude 서브에이전트로 교체되는 자리
  - offline: 결정적. features.features, design_system.component_specs, ux.information_architecture만 사용.

ux 정보구조의 화면을 핵심(fact)으로, 섹션 배치·컴포넌트 선택·navigation은 세부(inference)로 둔다.
본 에이전트는 body만 반환한다. 버전/derived_from/status는 orchestrator 책임.
"""

import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

AGENT_NAME = "agent.wireframe"
SYSTEM_PROMPT = Path(__file__).with_name("agent_wireframe.md").read_text(encoding="utf-8")

CORE_ORIGINS = ("fact", "human")
ALLOWED_ORIGINS = ("fact", "human", "inference")
REAL_MODEL_DEFAULT = "claude-sonnet-4-6"

# 기능 성격별 컴포넌트 선호(결정적). 실제 사용은 palette 교집합으로 제한한다.
INPUT_KEYWORDS = ("신청", "예약", "작성", "등록", "입력")
LIST_KEYWORDS = ("확인", "조회", "목록", "정산", "내역")

# real 모드 지시: 기능별 화면 구성(빈 화면 금지). 검색 없음(추론).
REAL_MODE_INSTRUCTION = (
    "\n\n## real 모드 지시(기능별 화면 구성 — 빈 화면 금지)\n"
    "1. features.features의 각 기능과 ux.user_flows·information_architecture를 받아, 그 기능이 사용자에게 완결되려면 필요한 화면·섹션·navigation을 구성한다. "
    "기능마다 필요한 화면이 다르다 — 모든 기능에 같은 화면 틀을 붙이는 고정 레이아웃 금지.\n"
    "2. 빈 화면 금지: features에 기능이 있으면 screens는 절대 비어선 안 된다. 핵심(fact) 기능은 반드시 대응 화면을 가진다. "
    "ux.information_architecture가 비어 있어도 features에서 화면을 도출한다.\n"
    "3. discovery(goal_interpretation·requirement_normalization)를 참고해 목표 달성에 핵심인 화면을 우선·명확히 배치한다.\n"
    "4. 발명 금지: 각 screen의 source는 핵심이면 \"ux:<화면>\" 또는 \"feature:<기능>\"(origin fact|human), 파생이면 \"derived:<근거>\"(origin inference). "
    "섹션의 components는 design_system.component_specs(palette) 안에서만, feature_refs는 features.features 안에서만 참조한다(없는 것 발명 금지).\n"
    "5. provenance: design_component_palette=\"fact\", feature_index=\"fact\", screens=\"per_item\", sections=\"inference\", navigation=\"inference\". "
    "body에 \"open_questions\": [] 포함. 출력은 출력 스키마의 JSON 객체 하나만(설명 텍스트·코드펜스 금지)."
)


def build_user_prompt(features: dict, design_system: dict, ux: dict, discovery=None) -> str:
    disc = {k: (discovery or {}).get(k) for k in ("goal_interpretation", "requirement_normalization")}
    return json.dumps({"features": features, "design_system": design_system, "ux": ux, "discovery": disc},
                      ensure_ascii=False)


def validate(body: dict) -> dict:
    """합의된 제약을 코드로 강제한다. 위반 시 raise."""
    required = {"design_component_palette", "feature_index", "screens",
                "navigation", "open_questions", "provenance"}
    missing = required - set(body)
    if missing:
        raise ValueError(f"wireframe body 필드 누락: {missing}")

    palette = set(body["design_component_palette"])
    feature_set = set(body["feature_index"])
    prov = body["provenance"]

    seen = set()
    has_sections = False
    for s in body["screens"]:
        name = s.get("screen")
        if not name:
            raise ValueError("screen 이름 누락")
        if not s.get("source"):
            raise ValueError(f"No-Fabrication 위반: source 없는 화면 '{name}'")
        origin = s.get("origin")
        if origin not in ALLOWED_ORIGINS:
            raise ValueError(f"허용되지 않은 origin '{origin}' (화면 '{name}')")
        src = s["source"]
        # 추론 층 분리: 핵심 화면은 ux:/feature: 근거+fact|human, 파생 화면은 derived:+inference
        if origin in CORE_ORIGINS:
            if not (src.startswith("ux:") or src.startswith("feature:")):
                raise ValueError(f"추론 층 분리 위반: 핵심 화면 '{name}'의 source는 ux:/feature:여야 함(현재 '{src}')")
        else:
            if not src.startswith("derived:"):
                raise ValueError(f"추론 층 분리 위반: 파생 화면 '{name}'의 source는 derived:여야 함(현재 '{src}')")
        if name in seen:
            raise ValueError(f"중복 화면명: '{name}'")
        seen.add(name)
        # 섹션 무결성: components ⊆ palette, feature_refs ⊆ feature_index
        for sec in s.get("sections", []):
            has_sections = True
            for c in sec.get("components", []):
                if c not in palette:
                    raise ValueError(f"발명된 컴포넌트 참조 in 화면 '{name}' 섹션 '{sec.get('section')}': '{c}' (palette에 없음)")
            for fr in sec.get("feature_refs", []):
                if fr not in feature_set:
                    raise ValueError(f"발명된 기능 참조 in 화면 '{name}' 섹션 '{sec.get('section')}': '{fr}' (feature_index에 없음)")

    if body["design_component_palette"] and prov.get("design_component_palette") != "fact":
        raise ValueError("provenance.design_component_palette는 fact여야 함")
    if body["feature_index"] and prov.get("feature_index") != "fact":
        raise ValueError("provenance.feature_index는 fact여야 함")
    if body["screens"] and prov.get("screens") != "per_item":
        raise ValueError("provenance.screens는 per_item이어야 함(화면별 origin 표기)")
    if has_sections and prov.get("sections") != "inference":
        raise ValueError("provenance.sections는 inference여야 함")

    return body


def _pick_components(task, palette):
    """기능 성격에 따라 palette 내에서 결정적으로 컴포넌트를 고른다. 발명 없음."""
    want = []
    if any(k in task for k in INPUT_KEYWORDS):
        want += ["input", "button"]
    if any(k in task for k in LIST_KEYWORDS):
        want += ["table", "card"]
    if not want:
        want = ["card"]
    picked = [c for c in want if c in palette]
    return picked or [c for c in ("card", "button") if c in palette]


def offline_llm(system: str, user: str) -> str:
    """결정적 오프라인 모드. features/design_system/ux 입력만 사용. 발명 금지."""
    payload = json.loads(user)
    features = payload.get("features", {}) or {}
    design_system = payload.get("design_system", {}) or {}
    ux = payload.get("ux", {}) or {}

    palette = [c["component"] for c in design_system.get("component_specs", [])]
    palette_set = set(palette)
    feat_list = features.get("features", [])
    feature_index = [f["feature"] for f in feat_list]
    feature_set = set(feature_index)
    # 핵심(fact) 기능만 화면 배치 대상. 보완(inference) 기능은 별도 표기.
    core_features = {f["feature"] for f in feat_list if f.get("origin") in CORE_ORIGINS}
    enh_features = [f["feature"] for f in feat_list if f.get("origin") not in CORE_ORIGINS]

    ia = ux.get("information_architecture", [])
    screens = []
    open_questions = []

    if not palette:
        open_questions.append("design_system 컴포넌트 없음: 화면 배치 불가(No-Fabrication)")
    if not ia:
        open_questions.append("ux.information_architecture 없음: 화면 구조 도출 불가")

    if palette and ia:
        for s in ia:
            sname = s.get("screen")
            sections = []
            for task in s.get("tasks", []):
                if task in feature_set:
                    sections.append({
                        "section": f"{task} 영역",
                        "components": _pick_components(task, palette_set),
                        "feature_refs": [task],
                    })
                else:
                    open_questions.append(f"화면 '{sname}'의 task '{task}'에 대응 기능 없음: 검토 필요")
            screens.append({
                "screen": sname,
                "source": f"ux:{sname}",
                "origin": "fact",
                "sections": sections,
            })

    # 보완 기능은 핵심 화면 구조에 포함하지 않고 정직하게 표기
    for ef in enh_features:
        open_questions.append(f"보완 기능 '{ef}' 화면 배치 미정: 검토 필요")

    navigation = {
        "pattern": "left-sidebar" if len(screens) > 1 else "single-screen",
        "items": [sc["screen"] for sc in screens],
        "uses_component": "nav" if "nav" in palette_set else None,
    }

    body = {
        "design_component_palette": palette,
        "feature_index": feature_index,
        "screens": screens,
        "navigation": navigation,
        "open_questions": open_questions,
        "provenance": {
            "design_component_palette": "fact",
            "feature_index": "fact",
            "screens": "per_item",
            "sections": "inference",
            "navigation": "inference",
        },
    }
    return json.dumps(body, ensure_ascii=False)


def _extract_json(text: str) -> str:
    text = text.replace("```json", "").replace("```", "").strip()
    i, j = text.find("{"), text.rfind("}")
    return text[i:j + 1] if i != -1 and j != -1 and j > i else text


def make_real_llm(model=REAL_MODEL_DEFAULT, max_tokens=8192):
    """real llm(system, user) -> str. Anthropic messages API(검색 없음, 추론).
    실패(SDK 미설치/키 없음/네트워크/API 에러)는 RuntimeError — produce에서 offline 폴백."""
    def real_llm(system: str, user: str) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError("real 모드 불가: anthropic SDK 미설치") from e
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("real 모드 불가: ANTHROPIC_API_KEY 없음")
        client = anthropic.Anthropic(api_key=api_key)
        try:
            resp = client.messages.create(
                model=model, max_tokens=max_tokens,
                system=system + REAL_MODE_INSTRUCTION,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:
            raise RuntimeError(f"real 모드 Anthropic API 호출 실패: {type(e).__name__}: {e}") from e
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if not text:
            raise RuntimeError("real 모드: Anthropic 응답에 텍스트 없음")
        return _extract_json(text)
    return real_llm


real_llm = make_real_llm()


WF_SPLIT_THRESHOLD = 6   # ux IA 화면이 이 이상이면 real에서 배치 분할(대형 브리프 truncation 해소)
WF_BATCH = 4             # 배치 크기(ux IA가 역할별로 정렬돼 있어 순서 배치가 역할별 분할이 된다)


def _merge_wireframe(parts: list) -> dict:
    """배치 산출들 -> 하나의 wireframe 산출(기존 스키마 동형). 화면명 dedupe(공통 화면 먼저 정의·중복 차단)."""
    palette, feat_idx = [], []
    screens, oq = [], []
    seen = set()
    for b in parts:
        if not palette:
            palette = b.get("design_component_palette") or []
        if not feat_idx:
            feat_idx = b.get("feature_index") or []
        for s in (b.get("screens") or []):
            nm = s.get("screen")
            if nm in seen:
                continue
            seen.add(nm)
            screens.append(s)
        oq += b.get("open_questions") or []
    nav = {"pattern": "left-sidebar" if len(screens) > 1 else "single-screen",
           "items": [s["screen"] for s in screens],
           "uses_component": "nav" if "nav" in set(palette) else None}
    return {"design_component_palette": palette, "feature_index": feat_idx, "screens": screens,
            "navigation": nav, "open_questions": list(dict.fromkeys(oq)),
            "provenance": {"design_component_palette": "fact", "feature_index": "fact",
                           "screens": "per_item", "sections": "inference", "navigation": "inference"}}


def produce(inputs: dict, llm=offline_llm) -> dict:
    features = inputs["features"]
    design_system = inputs.get("design_system", {})
    ux = inputs.get("ux", {})
    discovery = inputs.get("discovery", {})  # v13: 목표·요구를 화면 구성에 반영(real 프롬프트)
    ia = (ux or {}).get("information_architecture", []) or []
    # 대형 브리프(real): ux IA 화면을 배치로 나눠 호출 -> 각 호출 화면 수가 작아 truncation 해소. 합친 결과는 기존 스키마 동형.
    if llm is not offline_llm and len(ia) >= WF_SPLIT_THRESHOLD:
        parts = []
        for i in range(0, len(ia), WF_BATCH):
            ux_sub = dict(ux)
            ux_sub["information_architecture"] = ia[i:i + WF_BATCH]
            up = build_user_prompt(features, design_system, ux_sub, discovery)
            try:
                raw = llm(SYSTEM_PROMPT, up)
            except RuntimeError:
                raw = offline_llm(SYSTEM_PROMPT, up)
            parts.append(json.loads(_extract_json(raw)))
        return validate(_merge_wireframe(parts))
    # 단일 경로(offline 또는 소형 real). 기존 동작 보존.
    up = build_user_prompt(features, design_system, ux, discovery)
    try:
        raw = llm(SYSTEM_PROMPT, up)
    except RuntimeError:
        raw = offline_llm(SYSTEM_PROMPT, up)
    body = json.loads(_extract_json(raw))
    return validate(body)


def make_producer(llm=offline_llm):
    """orchestrator에 등록할 producer(inputs)->body 클로저. mock: make_producer(). real: make_producer(real_llm)."""
    def producer(inputs):
        return produce(inputs, llm=llm)
    return producer
