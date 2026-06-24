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
from pathlib import Path

AGENT_NAME = "agent.wireframe"
SYSTEM_PROMPT = Path(__file__).with_name("agent_wireframe.md").read_text(encoding="utf-8")

CORE_ORIGINS = ("fact", "human")
ALLOWED_ORIGINS = ("fact", "human", "inference")

# 기능 성격별 컴포넌트 선호(결정적). 실제 사용은 palette 교집합으로 제한한다.
INPUT_KEYWORDS = ("신청", "예약", "작성", "등록", "입력")
LIST_KEYWORDS = ("확인", "조회", "목록", "정산", "내역")


def build_user_prompt(features: dict, design_system: dict, ux: dict) -> str:
    return json.dumps({"features": features, "design_system": design_system, "ux": ux},
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


def produce(inputs: dict, llm=offline_llm) -> dict:
    features = inputs["features"]
    design_system = inputs.get("design_system", {})
    ux = inputs.get("ux", {})
    raw = llm(SYSTEM_PROMPT, build_user_prompt(features, design_system, ux))
    raw = raw.replace("```json", "").replace("```", "").strip()
    body = json.loads(raw)
    return validate(body)


def make_producer(llm=offline_llm):
    """orchestrator에 등록할 producer(inputs)->body 클로저. llm 주입은 클로저로 처리(구조 변경 없음)."""
    def producer(inputs):
        return produce(inputs, llm=llm)
    return producer
