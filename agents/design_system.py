"""
Design System Agent producer.

orchestrator 계약: producer(inputs: dict) -> body: dict
모델 호출은 llm(system, user) -> str 인터페이스로 분리한다.
  - real: positioning/ux_principles를 반영하는 Claude 서브에이전트로 교체되는 자리
  - offline: 결정적. intake.brand_tokens와 ux_principles만 사용. 색 파생은 결정적 알고리즘. 발명 금지.

산출물은 제품 UI용 디자인 시스템(색/타이포/간격/라운드/엘리베이션/컴포넌트/아이콘/접근성/CSS 변수)이다.
본 에이전트는 body만 반환한다. 버전/derived_from/status는 orchestrator 책임.
"""

import json
from pathlib import Path

AGENT_NAME = "agent.design_system"
SYSTEM_PROMPT = Path(__file__).with_name("agent_design_system.md").read_text(encoding="utf-8")

ALLOWED_ORIGINS = ("fact", "human", "inference", "baseline")

# 시스템 베이스라인(브랜드 무관, WCAG/SaaS 관례). 라이트 중립 팔레트.
LIGHT_NEUTRALS = [
    ("color-bg-base", "#FFFFFF", "페이지 기본 배경"),
    ("color-bg-subtle", "#F8FAFC", "테이블 헤더, 사이드바 배경"),
    ("color-surface", "#FFFFFF", "카드, 인풋 배경"),
    ("color-border", "#E2E8F0", "기본 보더"),
    ("color-text-primary", "#1E293B", "본문, 제목"),
    ("color-text-secondary", "#64748B", "서브 텍스트"),
    ("color-text-muted", "#94A3B8", "플레이스홀더, 컬럼 헤더"),
]
# 다크 중립 팔레트. 라이트 중립의 다크 모드 변환(파생, inference).
DARK_NEUTRALS = [
    ("color-bg-base", "#111116", "앱 기본 배경"),
    ("color-surface", "#1C1C28", "카드"),
    ("color-border", "#2E2E3E", "카드 테두리, 구분선"),
    ("color-text-primary", "#FFFFFF", "제목, 주요 수치"),
    ("color-text-secondary", "#A0A0C0", "서브 텍스트"),
    ("color-text-muted", "#6E6E8A", "타임스탬프, 레이블"),
]
SPACING = [
    ("sp-1", "4px", "아이콘-텍스트 gap"), ("sp-2", "8px", "배지 패딩"),
    ("sp-3", "12px", "nav gap, 셀 패딩"), ("sp-4", "16px", "섹션/카드 패딩"),
    ("sp-6", "24px", "카드 패딩(Web)"), ("sp-10", "40px", "페이지 헤더 offset"),
]
RADIUS = [
    ("r-sm", "4px", "뱃지, 태그"), ("r-md", "6px", "버튼, 인풋"),
    ("r-lg", "10px", "카드, 패널"), ("r-xl", "16px", "모바일 카드"),
]
ELEVATION = [
    ("shadow-soft", "0 1px 3px rgba(0,0,0,0.06)", "Web hover/focus"),
    ("focus-ring", "0 0 0 3px rgba(37,99,235,0.10)", "인풋 focus"),
    ("shadow-none", "none", "Mobile(배경 대비로만 계층)"),
]
SEMANTIC_DEFAULTS = [
    ("success", "#22C55E", "성공 상태, Active 뱃지"),
    ("warning", "#D97706", "경고, Delayed 뱃지"),
    ("danger", "#DC2626", "위험, Critical 뱃지"),
]
SYSTEM_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


def build_user_prompt(intake: dict, ux: dict, strategy: dict) -> str:
    return json.dumps({"intake": intake, "ux": ux, "strategy": strategy}, ensure_ascii=False)


def _hex(c):
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _mix(hex1, hex2, w):
    """hex1에 hex2를 비율 w로 섞는다. 결정적 파생."""
    r1, g1, b1 = _hex(hex1)
    r2, g2, b2 = _hex(hex2)
    r = round(r1 * (1 - w) + r2 * w)
    g = round(g1 * (1 - w) + g2 * w)
    b = round(b1 * (1 - w) + b2 * w)
    return "#{:02X}{:02X}{:02X}".format(r, g, b)


def _check_origin(origin, source, where):
    """source 형식과 origin 정합성을 강제한다(추론 층 분리)."""
    if not source:
        raise ValueError(f"No-Fabrication 위반: source 없는 항목 '{where}'")
    if origin not in ALLOWED_ORIGINS:
        raise ValueError(f"허용되지 않은 origin '{origin}' ({where})")
    if source.startswith("brand_tokens"):
        if origin not in ("fact", "human"):
            raise ValueError(f"추론 층 분리 위반: 입력 토큰 '{where}'는 fact|human이어야 함(현재 {origin})")
    elif source.startswith("derived"):
        if origin != "inference":
            raise ValueError(f"추론 층 분리 위반: 파생 토큰 '{where}'는 inference여야 함(현재 {origin})")
    elif source.startswith("baseline"):
        if origin != "baseline":
            raise ValueError(f"추론 층 분리 위반: 베이스라인 '{where}'는 baseline이어야 함(현재 {origin})")


def validate(body: dict) -> dict:
    """합의된 제약을 코드로 강제한다. 위반 시 raise."""
    required = {"color_tokens", "typography", "spacing", "radius", "elevation",
                "component_specs", "icon", "accessibility", "css_variables_template",
                "open_questions", "provenance"}
    missing = required - set(body)
    if missing:
        raise ValueError(f"design_system body 필드 누락: {missing}")

    defined_tokens = set()

    # color_tokens: source 필수(No-Fabrication) + origin/source 정합성(추론 층 분리)
    for c in body["color_tokens"]:
        _check_origin(c.get("origin"), c.get("source"), f"color_token:{c.get('token')}")
        defined_tokens.add(c["token"])

    if body["color_tokens"] and body["provenance"].get("color_tokens") != "per_token":
        raise ValueError("provenance.color_tokens는 per_token이어야 함(토큰별 origin 표기)")

    # typography.font_family도 핵심 토큰 규칙 적용
    ff = body["typography"].get("font_family")
    if ff:
        _check_origin(ff.get("origin"), ff.get("source"), "typography.font_family")

    # spacing/radius 토큰을 정의 집합에 추가
    for s in body["spacing"]:
        defined_tokens.add(s["token"])
    for r in body["radius"]:
        defined_tokens.add(r["token"])

    # 컴포넌트 uses_tokens 무결성: 정의된 토큰만 참조(발명 금지)
    for comp in body["component_specs"]:
        for tk in comp.get("uses_tokens", []):
            if tk not in defined_tokens:
                raise ValueError(f"발명된 토큰 참조 in component '{comp.get('component')}': '{tk}' (정의되지 않음)")

    return body


def offline_llm(system: str, user: str) -> str:
    """결정적 오프라인 모드. brand_tokens와 ux_principles만 사용. 발명 금지."""
    payload = json.loads(user)
    intake = payload["intake"]
    ux = payload.get("ux", {}) or {}
    strategy = payload.get("strategy", {}) or {}

    brand = intake.get("brand_tokens", {}) or {}
    ux_principles = ux.get("ux_principles", [])
    accent = brand.get("accent")

    color_tokens = []
    component_specs = []
    open_questions = []

    if not accent:
        # No-Fabrication: 근거(accent) 없으면 색·컴포넌트를 만들지 않는다.
        open_questions.append("브랜드 accent 토큰 미제공: 색 토큰·컴포넌트 생성 불가(No-Fabrication)")
    else:
        # 핵심: 입력 accent (human)
        color_tokens.append({"token": "color-accent", "value": accent, "mode": "shared",
                             "origin": "human", "source": "brand_tokens.accent",
                             "usage": "CTA 버튼, 활성 탭, 링크"})
        # 파생: tint(밝게), hover(어둡게) — inference
        color_tokens.append({"token": "color-accent-tint", "value": _mix(accent, "#FFFFFF", 0.90),
                             "mode": "light", "origin": "inference",
                             "source": "derived: color-accent + 90% white", "usage": "활성 nav 배경, 뱃지 배경"})
        color_tokens.append({"token": "color-accent-hover", "value": _mix(accent, "#000000", 0.12),
                             "mode": "shared", "origin": "inference",
                             "source": "derived: color-accent darken 12%", "usage": "버튼 hover"})
        # semantic: 입력 있으면 human, 없으면 표준 제안(inference) + open_question
        for key, std, usage in SEMANTIC_DEFAULTS:
            if brand.get(key):
                color_tokens.append({"token": f"color-{key}", "value": brand[key], "mode": "shared",
                                     "origin": "human", "source": f"brand_tokens.{key}", "usage": usage})
            else:
                color_tokens.append({"token": f"color-{key}", "value": std, "mode": "shared",
                                     "origin": "inference", "source": "derived: 표준 의미색 제안(검증 필요)", "usage": usage})
                open_questions.append(f"의미색 '{key}' 미제공: 표준값 {std} 제안, 브랜드 확인 필요")
        # 중립 라이트: baseline
        for token, value, usage in LIGHT_NEUTRALS:
            color_tokens.append({"token": token, "value": value, "mode": "light", "origin": "baseline",
                                 "source": "baseline: SaaS 라이트 중립 팔레트(WCAG AA)", "usage": usage})
        # 중립 다크: 라이트의 다크 변환(파생, inference)
        for token, value, usage in DARK_NEUTRALS:
            color_tokens.append({"token": token, "value": value, "mode": "dark", "origin": "inference",
                                 "source": "derived: 라이트 중립의 다크 모드 변환", "usage": usage})

        # 컴포넌트 명세: 정의된 토큰만 참조
        component_specs = [
            {"component": "button",
             "spec": {"height": "34px", "padding": "7px 14px", "font_size": "13px", "font_weight": 500,
                      "primary_bg": "color-accent", "primary_text": "#FFFFFF", "hover_bg": "color-accent-hover"},
             "uses_tokens": ["color-accent", "color-accent-hover", "r-md", "sp-2"]},
            {"component": "input",
             "spec": {"height": "34px", "padding": "0 10px", "border": "0.5px solid color-border",
                      "focus_border": "color-accent", "focus_ring": "focus-ring"},
             "uses_tokens": ["color-border", "color-accent", "r-md"]},
            {"component": "badge",
             "spec": {"padding": "2px 8px", "font_size": "11px", "font_weight": 500,
                      "bg": "color-accent-tint", "text": "color-accent"},
             "uses_tokens": ["color-accent-tint", "color-accent", "r-sm"]},
            {"component": "table",
             "spec": {"header_bg": "color-bg-subtle", "header_text": "color-text-muted",
                      "row_text": "color-text-primary", "row_border": "color-border", "hover_bg": "color-bg-subtle"},
             "uses_tokens": ["color-bg-subtle", "color-text-muted", "color-text-primary", "color-border", "sp-3"]},
            {"component": "card",
             "spec": {"bg": "color-surface", "border": "0.5px solid color-border", "padding": "sp-6",
                      "title_text": "color-text-primary", "sub_text": "color-text-secondary"},
             "uses_tokens": ["color-surface", "color-border", "color-text-primary", "color-text-secondary", "r-lg", "sp-6"]},
            {"component": "nav",
             "spec": {"item_text": "color-text-secondary", "active_bg": "color-accent-tint",
                      "active_text": "color-accent", "hover_bg": "color-bg-subtle"},
             "uses_tokens": ["color-text-secondary", "color-accent-tint", "color-accent", "color-bg-subtle", "r-md", "sp-3"]},
        ]

    # typography
    font_family = brand.get("font_family")
    if font_family:
        ff = {"value": font_family, "origin": "human", "source": "brand_tokens.font_family"}
    else:
        ff = {"value": SYSTEM_FONT, "origin": "baseline", "source": "baseline: 시스템 sans-serif"}
        open_questions.append("브랜드 폰트 미제공: 시스템 sans-serif 사용")
    typography = {
        "font_family": ff,
        "scale": [
            {"role": "페이지 제목", "size": "22px", "weight": 500, "color_token": "color-text-primary"},
            {"role": "카드 주 텍스트", "size": "14px", "weight": 500, "color_token": "color-text-primary"},
            {"role": "본문/테이블", "size": "13px", "weight": 400, "color_token": "color-text-secondary"},
            {"role": "컬럼 헤더", "size": "12px", "weight": 400, "color_token": "color-text-muted"},
            {"role": "뱃지 레이블", "size": "11px", "weight": 500, "color_token": "color-accent"},
        ],
        "principles": ["weight는 400/500/600/700만 사용", "줄간격 본문 1.6 / 제목 1.2", "uppercase 레이블 자간 0.06em"],
    }

    spacing = [{"token": t, "value": v, "usage": u} for t, v, u in SPACING]
    radius = [{"token": t, "value": v, "usage": u} for t, v, u in RADIUS]
    elevation = [{"token": t, "value": v, "usage": u} for t, v, u in ELEVATION]
    icon = {"library": "Tabler Icons (outline 전용)",
            "sizes": {"web_inline": "16px", "web_decorative": "20px", "mobile_nav": "20px", "mobile_card": "13-16px"},
            "origin": "baseline", "source": "baseline: Tabler outline 아이콘 세트"}
    accessibility = {"min_touch_target": "44x44px", "min_input_height": "34px",
                     "min_text_size": "11px", "contrast": "WCAG AA 4.5:1"}

    # CSS 변수 템플릿: 정의된 토큰에서 생성(derived)
    light_lines = [f"  --{c['token']}: {c['value']};" for c in color_tokens if c["mode"] in ("shared", "light")]
    dark_lines = [f"    --{c['token']}: {c['value']};" for c in color_tokens if c["mode"] == "dark"]
    sp_lines = [f"  --{s['token']}: {s['value']};" for s in spacing]
    r_lines = [f"  --{r['token']}: {r['value']};" for r in radius]
    css_parts = [":root {"] + light_lines + sp_lines + r_lines + ["}"]
    if dark_lines:
        css_parts += ["@media (prefers-color-scheme: dark) {", "  :root {"] + dark_lines + ["  }", "}"]
    css_variables_template = "\n".join(css_parts)

    body = {
        "color_tokens": color_tokens,
        "typography": typography,
        "spacing": spacing,
        "radius": radius,
        "elevation": elevation,
        "component_specs": component_specs,
        "icon": icon,
        "accessibility": accessibility,
        "css_variables_template": css_variables_template,
        "open_questions": open_questions,
        "provenance": {
            "color_tokens": "per_token",
            "typography": "per_field",
            "spacing": "baseline",
            "radius": "baseline",
            "elevation": "baseline",
            "component_specs": "inference",
            "icon": "baseline",
            "accessibility": "baseline",
            "css_variables_template": "derived",
        },
    }
    return json.dumps(body, ensure_ascii=False)


def produce(inputs: dict, llm=offline_llm) -> dict:
    intake = inputs["intake"]
    ux = inputs.get("ux", {})
    strategy = inputs.get("strategy", {})
    raw = llm(SYSTEM_PROMPT, build_user_prompt(intake, ux, strategy))
    raw = raw.replace("```json", "").replace("```", "").strip()
    body = json.loads(raw)
    return validate(body)


def make_producer(llm=offline_llm):
    """orchestrator에 등록할 producer(inputs)->body 클로저. llm 주입은 클로저로 처리(구조 변경 없음)."""
    def producer(inputs):
        return produce(inputs, llm=llm)
    return producer
