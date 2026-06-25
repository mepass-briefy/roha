"""
Design System Agent producer (재정의: Material 3 tonal + Reference Contract).

orchestrator 계약: producer(inputs: dict) -> body: dict (canonical 비교 유지).
모델 호출은 llm(system, user) -> str. offline은 결정적(reference token 즉시 적용, image/url은 open_questions, baseline fallback).

seed -> Material 3 tonal palette(Light/Dark mirror, surface container 톤 5단계, 의미색 tonal, WCAG AA).
derive_seed(strategy, intake, references)가 seed·폰트·아이콘·origin 단일 진입점.
모든 토큰은 token_key/value/origin(+source_reference_id) 단위 traceability를 갖는다.
본 에이전트는 body만 반환한다. 버전/derived_from/status는 orchestrator 책임.
"""

import json
import os
import re
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

AGENT_NAME = "agent.design_system"
REAL_MODEL_DEFAULT = "claude-sonnet-4-6"
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# real 모드 지시: brand seed(색)만 결정. 토큰 계산(_tone/surface/의미색/WCAG)은 결정적 엔진이 수행.
SEED_INSTRUCTION = (
    "\n\n## real 모드 지시(brand seed 결정만 — 토큰 계산은 엔진이 한다)\n"
    "너의 임무는 '어떤 brand 색이 맞는가'를 정하는 것뿐이다. 색조·명도 단계·surface·의미색·WCAG 대비 계산은 결정적 엔진이 수행하므로 너는 seed만 정한다.\n"
    "입력의 strategy(positioning·톤), discovery(goal_interpretation·목표 성격), references를 보고 제품 성격에 맞는 brand primary 색(hex)을 정한다.\n"
    "1. references에 image/url이 있으면 그 메타(파일명·url·설명)와 제품 맥락에서 brand 색을 추론한다(source는 \"reference-image\" 또는 \"reference-url\", source_reference_id는 해당 reference_id).\n"
    "2. 쓸만한 reference가 없으면 strategy·discovery 성격에서 적절한 색을 추론한다(예: 신뢰·금융 성격이면 차분한 블루/인디고, 활기·소셜이면 따뜻한 색). source는 \"inference\".\n"
    "3. 출력은 JSON 하나만: {\"primary\":\"#RRGGBB\", \"secondary\":\"#RRGGBB 또는 null\", \"font_family\":\"... 또는 null\", "
    "\"source\":\"reference-image|reference-url|inference\", \"source_reference_id\":\"... 또는 null\", \"rationale\":\"왜 이 색인가\"}. "
    "primary는 반드시 #RRGGBB 6자리 hex. 설명 텍스트·코드펜스 금지."
)
SYSTEM_PROMPT = Path(__file__).with_name("agent_design_system.md").read_text(encoding="utf-8")

# B6: baseline 고정 세트(추론이 아니라 정해진 fallback)
BASELINE_SEED = "#6750A4"      # Material 3 baseline primary
BASELINE_SECONDARY = "#625B71"
BASELINE_FONT = "Pretendard"
BASELINE_ICONS = "Tabler"
NEUTRAL_SEED = "#787579"       # 토대 중립(브랜드 무관, 항상 baseline)

SEM_SEEDS = {"success": "#16A34A", "warning": "#D97706", "danger": "#DC2626", "info": "#2563EB"}
# 의미색 4-토큰 패밀리(name/on-name/name-container/on-name-container) 생성 대상.
# hue는 의미에 고정(SEM_SEEDS, 초록/앰버/빨강) — brand seed와 무관하게 항상 동일(success는 어떤 brand든 초록).
# 명도·container 톤은 primary와 동일한 _tone() 패턴 재사용(새 알고리즘 없음). info는 패밀리 제외(base만 state_mapping에서 유지).
SEMANTIC_FAMILY = ("success", "warning", "danger")
# ROHA 디자인 명세 13종 컴포넌트(DESIGN_SYSTEM_SPEC.md §5).
PRIMITIVES = ("sidebar", "select", "tab", "checkbox", "radio_card", "toggle",
              "button", "badge", "input", "table", "profile", "card", "search")
INTERACTIVE = {"sidebar", "select", "tab", "checkbox", "radio_card", "toggle", "button", "input", "search"}
WCAG_AA = 4.5

# 역할 토큰(명세 §2,§3): brand별 checked/tab/neutral 고정값. 미지정 seed는 결정적 파생.
THEME_ROLES = {
    "#3F51B5": {  # 인디고
        "checked": {"light": "#51C0FF", "dark": "#51C0FF"},
        "tab-bg": {"light": "#EDF9FF", "dark": "#0D1F35"},
        "tab-fg": {"light": "#1056BD", "dark": "#5BA3D4"},
        "neutral": {"light": "#292929", "dark": "#E6E5E6"},
        "on-neutral": {"light": "#FFFFFF", "dark": "#1A191A"},
    },
    "#FF5E5E": {  # 코랄
        "checked": {"light": "#FF5E5E", "dark": "#FF5E5E"},
        "tab-bg": {"light": "#FFEFEF", "dark": "#2D1515"},
        "tab-fg": {"light": "#FF5E5E", "dark": "#FF5E5E"},
        "neutral": {"light": "#292F45", "dark": "#E6E5E6"},
        "on-neutral": {"light": "#FFFFFF", "dark": "#1A191A"},
    },
}
# brand 무관 고정 역할(명세 §3): active(접속, success와 구분), menu-sel(활성메뉴), danger-soft.
ROLE_FIXED = {
    "active": {"light": "#10A957", "dark": "#3DD17F"},
    "menu-sel": {"light": "#EEEEEE", "dark": "#2C2B2C"},
    "danger-soft-bg": {"light": "#FFF0F0", "dark": "#3A1515"},
    "danger-soft-fg": {"light": "#AB0909", "dark": "#F1A7A7"},
}

# 컴포넌트별 states·uses_tokens(역할 토큰 참조). 명세 §5. 토큰 키만 참조(하드코딩 색 금지).
COMPONENT_SPECS = {
    "sidebar": {
        "states": {"enabled": {"bg": "color.light.surface", "border": "color.light.outline"},
                   "nav-hover": {"bg": "color.light.surface-container-base"},
                   "nav-active": {"bg": "color.light.menu-sel", "fg": "color.light.on-surface"}},
        "uses_tokens": ["color.light.surface", "color.light.menu-sel", "color.light.outline", "radius.r-md", "spacing.sp-2"]},
    "select": {
        "states": {"enabled": {"bg": "color.light.surface", "border": "color.light.outline", "fg": "color.light.on-surface"},
                   "focus": {"border": "color.light.primary"}, "disabled": {"bg": "ui_intent.disabled"}},
        "uses_tokens": ["color.light.surface", "color.light.outline", "radius.r-md", "spacing.sp-3"]},
    "tab": {
        "states": {"enabled": {"bg": "color.light.surface", "fg": "color.light.on-surface"},
                   "active": {"bg": "color.light.tab-bg", "fg": "color.light.tab-fg"}},
        "uses_tokens": ["color.light.tab-bg", "color.light.tab-fg", "color.light.outline", "radius.r-lg"]},
    "checkbox": {
        "states": {"enabled": {"border": "color.light.outline"},
                   "checked": {"bg": "color.light.checked", "fg": "color.light.on-primary"}},
        "uses_tokens": ["color.light.checked", "radius.r-sm"]},
    "radio_card": {
        "states": {"enabled": {"border": "color.light.outline"},
                   "selected": {"border": "color.light.tab-fg", "bg": "color.light.tab-bg"}},
        "uses_tokens": ["color.light.tab-bg", "color.light.tab-fg", "radius.r-lg"]},
    "toggle": {
        "states": {"off": {"bg": "color.light.surface-container-highest", "knob": "color.light.surface-container-lowest"},
                   "on": {"bg": "color.light.checked", "knob": "color.light.surface-container-lowest"}},
        "uses_tokens": ["color.light.checked", "radius.r-xl"]},
    "button": {  # 명세 5종: primary/neutral/outline/danger/danger-soft
        "states": {"primary": {"bg": "color.light.primary", "fg": "color.light.on-primary"},
                   "neutral": {"bg": "color.light.neutral", "fg": "color.light.on-neutral"},
                   "outline": {"bg": "transparent", "border": "color.light.outline", "fg": "color.light.on-surface"},
                   "danger": {"bg": "transparent", "fg": "color.light.danger-soft-fg"},
                   "danger-soft": {"bg": "color.light.danger-soft-bg", "fg": "color.light.danger-soft-fg"},
                   "disabled": {"bg": "ui_intent.disabled"}},
        "uses_tokens": ["color.light.primary", "color.light.neutral", "color.light.on-neutral",
                        "color.light.danger-soft-bg", "color.light.danger-soft-fg", "color.light.outline", "radius.r-md"]},
    "badge": {  # pill, 의미색·active·muted
        "states": {"prim": {"bg": "color.light.primary-container", "fg": "color.light.on-primary-container"},
                   "success": {"bg": "color.light.success", "fg": "color.light.on-success"},
                   "warning": {"bg": "color.light.warning", "fg": "color.light.on-warning"},
                   "danger": {"bg": "color.light.danger", "fg": "color.light.on-danger"},
                   "active": {"bg": "color.light.surface-container-low", "fg": "color.light.active"},
                   "muted": {"bg": "color.light.surface-container-base", "fg": "color.light.outline"}},
        "uses_tokens": ["color.light.primary-container", "color.light.success", "color.light.warning",
                        "color.light.danger", "color.light.active", "radius.r-xl"]},
    "input": {
        "states": {"enabled": {"bg": "color.light.surface", "border": "color.light.outline", "fg": "color.light.on-surface"},
                   "focus": {"border": "color.light.primary"}, "disabled": {"bg": "ui_intent.disabled"}},
        "uses_tokens": ["color.light.surface", "color.light.outline", "color.light.primary", "radius.r-md"]},
    "table": {
        "states": {"header": {"fg": "color.light.outline", "border": "color.light.outline"},
                   "row": {"fg": "color.light.on-surface", "border": "color.light.outline"},
                   "hover": {"bg": "color.light.surface-container-base"}},
        "uses_tokens": ["color.light.on-surface", "color.light.outline", "spacing.sp-3"]},
    "profile": {
        "states": {"enabled": {"bg": "color.light.surface-container-base", "fg": "color.light.on-surface"},
                   "active": {"dot": "color.light.active"}},
        "uses_tokens": ["color.light.active", "color.light.surface-container-base"]},
    "card": {
        "states": {"enabled": {"bg": "color.light.surface", "border": "color.light.outline"}},
        "uses_tokens": ["color.light.surface", "color.light.outline", "radius.r-lg", "spacing.sp-6"]},
    "search": {
        "states": {"enabled": {"bg": "color.light.surface", "border": "color.light.outline", "fg": "color.light.outline"},
                   "focus": {"border": "color.light.primary"}},
        "uses_tokens": ["color.light.surface", "color.light.outline", "radius.r-md"]},
}

# E: override 가능 키(표현층). color.* 와 font.family/font.weight 만 offline 허용.
def _in_whitelist(key):
    return key.startswith("color.") or key in ("font.family", "font.weight")

ALLOWED_ORIGINS = ("baseline", "reference-token", "reference-image", "reference-url")


# ---------------- 색 유틸 ----------------
def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(r, g, b):
    return "#{:02X}{:02X}{:02X}".format(max(0, min(255, round(r))), max(0, min(255, round(g))), max(0, min(255, round(b))))


def _rgb_to_hsl(r, g, b):
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2.0
    if mx == mn:
        return 0.0, 0.0, l
    d = mx - mn
    s = d / (2.0 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == r:
        h = (g - b) / d + (6 if g < b else 0)
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h / 6.0, s, l


def _hue(p, q, t):
    if t < 0:
        t += 1
    if t > 1:
        t -= 1
    if t < 1 / 6:
        return p + (q - p) * 6 * t
    if t < 1 / 2:
        return q
    if t < 2 / 3:
        return p + (q - p) * (2 / 3 - t) * 6
    return p


def _hsl_to_rgb(h, s, l):
    if s == 0:
        v = l * 255
        return v, v, v
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    return _hue(p, q, h + 1 / 3) * 255, _hue(p, q, h) * 255, _hue(p, q, h - 1 / 3) * 255


def _tone(seed_hex, tone, neutral=False):
    """seed의 tonal palette에서 주어진 tone(0~100)을 lightness로 매핑(Material 3 근사). neutral은 채도 억제."""
    r, g, b = _hex_to_rgb(seed_hex)
    h, s, _ = _rgb_to_hsl(r, g, b)
    if neutral:
        s = min(s, 0.06)
    rr, gg, bb = _hsl_to_rgb(h, s, tone / 100.0)
    return _rgb_to_hex(rr, gg, bb)


def _luminance(hexv):
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _hex_to_rgb(hexv)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(a, b):
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _best_on(color):
    return "#FFFFFF" if _contrast("#FFFFFF", color) >= _contrast("#000000", color) else "#000000"


def _tone_meeting_contrast(seed_hex, start_tone, bg_hex, step):
    """WCAG AA(4.5:1) 보장. start_tone에서 step(±1)으로 한 단계씩 이동하며 bg 대비 >= WCAG_AA가 되는 첫 tone을 찾는다.
    경계(0~100)에 닿으면 그 tone을 반환. _tone·_contrast만 사용(새 알고리즘 없음). (value, tone) 반환."""
    t = start_tone
    val = _tone(seed_hex, t)
    while _contrast(val, bg_hex) < WCAG_AA:
        nt = t + step
        if nt < 0 or nt > 100:
            break
        t = nt
        val = _tone(seed_hex, t)
    return val, t


# ---------------- B: seed 도출 ----------------
def _role_tokens(primary_hex):
    """역할 토큰(checked/tab-bg/tab-fg/neutral/on-neutral): 명세 테마(인디고/코랄)는 lookup, 미지정 seed는 결정적 파생.
    엔진 톤 함수(_tone 등) 무수정 — 여기서 emit용 값만 구성한다."""
    t = THEME_ROLES.get(str(primary_hex).upper())
    if t is not None:
        return t
    return {  # 범용 파생: checked=밝은 brand, tab-bg=옅은 tint, tab-fg=읽기색
        "checked": {"light": _tone(primary_hex, 70), "dark": _tone(primary_hex, 75)},
        "tab-bg": {"light": _tone(primary_hex, 95), "dark": _tone(primary_hex, 18)},
        "tab-fg": {"light": _tone(primary_hex, 40), "dark": _tone(primary_hex, 75)},
        "neutral": {"light": "#292929", "dark": "#E6E5E6"},
        "on-neutral": {"light": "#FFFFFF", "dark": "#1A191A"},
    }


def derive_seed(strategy, intake, references):
    """seed·폰트·아이콘·origin을 결정하는 단일 진입점. offline: token 즉시 적용, image/url은 보류."""
    references = references or []
    open_questions = []
    conflicts = []
    whitelist_violations = []
    wcag_warnings = []
    applied = {}  # key -> (value, reference_id)

    by_type = {"token": [], "image": [], "url": []}
    for ref in references:
        by_type.get(ref.get("type"), by_type.setdefault(ref.get("type"), [])).append(ref)

    # offline: image/url 분석 금지 -> open_questions (우선순위상 token 아래)
    for ref in by_type.get("image", []):
        open_questions.append(f"reference {ref.get('reference_id')}(image): offline 분석 불가 -> 보류(real 모드 필요)")
    for ref in by_type.get("url", []):
        open_questions.append(f"reference {ref.get('reference_id')}(url): offline 분석 불가 -> 보류(real 모드 필요)")

    # token type: 같은 key 충돌 검출(임의 선택 금지) + whitelist + WCAG
    keymap = {}
    for ref in by_type.get("token", []):
        for k, v in (ref.get("value") or {}).items():
            keymap.setdefault(k, []).append((v, ref.get("reference_id")))
    for k, vals in keymap.items():
        distinct = {v for v, _ in vals}
        if len(distinct) > 1:
            conflicts.append(k)
            open_questions.append(f"reference 충돌: '{k}' 값이 {sorted(distinct)}로 불일치 -> 사용자 확인 필요(임의 선택 금지)")
            continue
        if not _in_whitelist(k):
            whitelist_violations.append(k)
            open_questions.append(f"override 범위 밖 요청 무시: '{k}'(토대 토큰은 변경 불가)")
            continue
        val, rid = vals[0]
        if k.startswith("color."):
            # accent 색이 라이트 표면(흰색) 위에서 본문 대비 4.5:1을 못 넘으면 경고
            if _contrast(val, "#FFFFFF") < WCAG_AA:
                wcag_warnings.append(k)
                open_questions.append(f"제공된 색 '{k}'={val} 대비 미달(WCAG AA 4.5:1, 흰 배경 기준) -> 적용하되 확인 필요")
        applied[k] = (val, rid)

    has_ref_token = bool(applied)
    seed_primary = applied.get("color.primary", (BASELINE_SEED, None))[0]
    seed_secondary = applied.get("color.secondary", (BASELINE_SECONDARY, None))[0]
    font_family = applied.get("font.family", (BASELINE_FONT, None))[0]

    if not references:
        open_questions.append("브랜드 reference 미제공, 기본 세트 사용 중(Material 3 baseline seed + Pretendard + Tabler)")
    elif not has_ref_token:
        open_questions.append("적용 가능한 token reference 없음 -> baseline 세트 사용 중")

    return {
        "primary": seed_primary,
        "secondary": seed_secondary,
        "font_family": font_family,
        "icon_pack": BASELINE_ICONS,
        "source": "reference-token" if "color.primary" in applied else "baseline",
        "source_reference_id": applied.get("color.primary", (None, None))[1],
        "_applied": applied,
        "_open_questions": open_questions,
        "_conflicts": conflicts,
        "_whitelist_violations": whitelist_violations,
        "_wcag_warnings": wcag_warnings,
    }


def _origin_for(brand_key, applied):
    if brand_key and brand_key in applied:
        return "reference-token", applied[brand_key][1]
    return "baseline", None


def build_user_prompt(intake, strategy, ux, discovery=None):
    disc = {k: (discovery or {}).get(k) for k in
            ("goal_interpretation", "requirement_normalization", "proposed_requirements")}
    return json.dumps({"intake": intake, "strategy": strategy, "ux": ux, "discovery": disc}, ensure_ascii=False)


# ---------------- 산출 빌드 ----------------
def _build_body(intake, strategy, ux):
    references = intake.get("references", []) if isinstance(intake, dict) else []
    seed = derive_seed(strategy, intake, references)
    applied = seed["_applied"]
    open_questions = list(seed["_open_questions"])
    primary = seed["primary"]
    secondary = seed["secondary"]

    tokens = []  # F: 토큰 단위 traceability

    def push(token_key, value, brand_key=None):
        origin, rid = _origin_for(brand_key, applied)
        tokens.append({"token_key": token_key, "value": value,
                       "source_reference_id": rid, "origin": origin})
        return value

    # Foundation color: Light(진한 톤)/Dark(밝은 톤) mirror
    color = {"light": {}, "dark": {}}
    # primary family (brand_key=color.primary)
    color["light"]["primary"] = push("color.light.primary", _tone(primary, 40), "color.primary")
    color["light"]["on-primary"] = push("color.light.on-primary", _tone(primary, 100), "color.primary")
    color["light"]["primary-container"] = push("color.light.primary-container", _tone(primary, 90), "color.primary")
    color["light"]["on-primary-container"] = push("color.light.on-primary-container", _tone(primary, 10), "color.primary")
    color["dark"]["primary"] = push("color.dark.primary", _tone(primary, 80), "color.primary")
    color["dark"]["on-primary"] = push("color.dark.on-primary", _tone(primary, 20), "color.primary")
    color["dark"]["primary-container"] = push("color.dark.primary-container", _tone(primary, 30), "color.primary")
    color["dark"]["on-primary-container"] = push("color.dark.on-primary-container", _tone(primary, 90), "color.primary")
    # secondary
    color["light"]["secondary"] = push("color.light.secondary", _tone(secondary, 40), "color.secondary")
    color["dark"]["secondary"] = push("color.dark.secondary", _tone(secondary, 80), "color.secondary")
    # neutral / surface / outline (항상 baseline)
    color["light"]["surface"] = push("color.light.surface", _tone(NEUTRAL_SEED, 98, neutral=True))
    color["light"]["on-surface"] = push("color.light.on-surface", _tone(NEUTRAL_SEED, 10, neutral=True))
    color["light"]["outline"] = push("color.light.outline", _tone(NEUTRAL_SEED, 50, neutral=True))
    color["dark"]["surface"] = push("color.dark.surface", _tone(NEUTRAL_SEED, 6, neutral=True))
    color["dark"]["on-surface"] = push("color.dark.on-surface", _tone(NEUTRAL_SEED, 90, neutral=True))
    color["dark"]["outline"] = push("color.dark.outline", _tone(NEUTRAL_SEED, 60, neutral=True))

    # 의미색 4-토큰 패밀리(success/warning/danger). hue 고정(SEM_SEEDS, brand 무관).
    # 원칙은 'tone 고정'이 아니라 'WCAG AA(4.5:1) 보장'(design_system 재정의 명시). 따라서 main tone은 고정값이 아니라
    # surface 대비 AA를 넘을 때까지 한 단계씩 조정(light=40에서 낮춤, dark=80에서 높임; _tone·_contrast 재사용).
    # on-*은 _best_on으로 main/container 대비 보장. base 토큰 color.{mode}.{name}은 state_mapping이 동일 값으로 push(중복 방지).
    sem_tone = {}  # 보고용: 조정된 main tone
    for name in SEMANTIC_FAMILY:
        sd = SEM_SEEDS[name]
        l_main, l_t = _tone_meeting_contrast(sd, 40, color["light"]["surface"], -1)
        d_main, d_t = _tone_meeting_contrast(sd, 80, color["dark"]["surface"], +1)
        sem_tone[name] = {"light": l_t, "dark": d_t}
        # main: dict 노출만(토큰 push는 state_mapping이 동일 값으로 수행)
        color["light"][name] = l_main
        color["dark"][name] = d_main
        # container(light 90 / dark 30) + on-* 대비 보장(_best_on)
        l_cont, d_cont = _tone(sd, 90), _tone(sd, 30)
        color["light"][f"on-{name}"] = push(f"color.light.on-{name}", _best_on(l_main))
        color["light"][f"{name}-container"] = push(f"color.light.{name}-container", l_cont)
        color["light"][f"on-{name}-container"] = push(f"color.light.on-{name}-container", _best_on(l_cont))
        color["dark"][f"on-{name}"] = push(f"color.dark.on-{name}", _best_on(d_main))
        color["dark"][f"{name}-container"] = push(f"color.dark.{name}-container", d_cont)
        color["dark"][f"on-{name}-container"] = push(f"color.dark.on-{name}-container", _best_on(d_cont))
        # 잔여 미달만 open_questions(조정 후 정상이면 추가 없음 = 경고 해소)
        for mode in ("light", "dark"):
            if _contrast(color[mode][f"on-{name}"], color[mode][name]) < WCAG_AA:
                open_questions.append(f"의미색 대비 미달: {mode} on-{name}/{name} (WCAG AA 4.5:1 미달) -> 확인 필요")
            if _contrast(color[mode][name], color[mode]["surface"]) < WCAG_AA:
                open_questions.append(f"의미색 대비 미달: {mode} {name}/surface (WCAG AA 4.5:1 미달) -> 확인 필요")

    # A2: surface container 톤 5단계(lowest~highest). 다크 base #121212 계열.
    surface_tones = {
        "light": {n: push(f"color.light.surface-container-{n}", _tone(NEUTRAL_SEED, t, neutral=True))
                  for n, t in (("lowest", 100), ("low", 96), ("base", 94), ("high", 92), ("highest", 90))},
        "dark": {n: push(f"color.dark.surface-container-{n}", _tone(NEUTRAL_SEED, t, neutral=True))
                 for n, t in (("lowest", 4), ("low", 10), ("base", 12), ("high", 17), ("highest", 22))},
    }

    # 역할 토큰(명세 §2,§3): checked/tab/neutral은 brand-role(color.primary 출처 추적), active/menu-sel/danger-soft는 brand 무관(baseline).
    roles = _role_tokens(primary)
    for rk in ("checked", "tab-bg", "tab-fg", "neutral", "on-neutral"):
        color["light"][rk] = push(f"color.light.{rk}", roles[rk]["light"], "color.primary")
        color["dark"][rk] = push(f"color.dark.{rk}", roles[rk]["dark"], "color.primary")
    for rk, vals in ROLE_FIXED.items():
        color["light"][rk] = push(f"color.light.{rk}", vals["light"])
        color["dark"][rk] = push(f"color.dark.{rk}", vals["dark"])

    # Semantic: state mapping (각자 tonal, 다크는 밝은 톤)
    state_mapping = []
    for state, sseed in SEM_SEEDS.items():
        bk = f"color.{state}"
        sval = applied.get(bk, (sseed, None))[0]
        if bk in applied and _contrast(sval, "#FFFFFF") < WCAG_AA:
            open_questions.append(f"제공된 의미색 '{bk}'={sval} 대비 미달(WCAG AA, 흰 배경 기준) -> 적용하되 확인 필요")
        # WCAG AA 보장: foundation 의미색 패밀리와 동일하게 surface 대비 통과 tone으로 조정(없으면 그대로).
        light_v = push(f"color.light.{state}", _tone_meeting_contrast(sval, 40, color["light"]["surface"], -1)[0], bk)
        dark_v = push(f"color.dark.{state}", _tone_meeting_contrast(sval, 80, color["dark"]["surface"], +1)[0], bk)
        state_mapping.append({"state": state, "light": light_v, "dark": dark_v})

    # Semantic: ui_intent — 색 역할 분리(명세 §2). 각 컴포넌트가 올바른 역할 토큰을 참조.
    ui_intent = [
        {"intent": "primary", "light": color["light"]["primary"], "dark": color["dark"]["primary"]},          # 주요버튼·로고
        {"intent": "secondary", "light": color["light"]["secondary"], "dark": color["dark"]["secondary"]},
        {"intent": "checked", "light": color["light"]["checked"], "dark": color["dark"]["checked"]},            # 토글·체크
        {"intent": "tab", "light": color["light"]["tab-bg"], "dark": color["dark"]["tab-bg"]},                  # 탭·라디오 선택
        {"intent": "tab-fg", "light": color["light"]["tab-fg"], "dark": color["dark"]["tab-fg"]},
        {"intent": "active", "light": color["light"]["active"], "dark": color["dark"]["active"]},               # 접속/온라인(success와 구분)
        {"intent": "menu-sel", "light": color["light"]["menu-sel"], "dark": color["dark"]["menu-sel"]},         # 활성 메뉴
        {"intent": "neutral", "light": color["light"]["neutral"], "dark": color["dark"]["neutral"]},            # 코랄 주요액션 대비
        {"intent": "destructive", "light": next(s["light"] for s in state_mapping if s["state"] == "danger"),
         "dark": next(s["dark"] for s in state_mapping if s["state"] == "danger")},
        {"intent": "disabled", "light": _tone(NEUTRAL_SEED, 80, neutral=True), "dark": _tone(NEUTRAL_SEED, 40, neutral=True)},
    ]

    # Typography
    font_origin, font_rid = _origin_for("font.family", applied)
    tokens.append({"token_key": "font.family", "value": seed["font_family"],
                   "source_reference_id": font_rid, "origin": font_origin})
    typography = {
        "font_family": {"value": seed["font_family"], "origin": font_origin, "source_reference_id": font_rid},
        "scale": [
            {"role": "display", "size": "28px", "weight": 700},
            {"role": "title", "size": "20px", "weight": 600},
            {"role": "body", "size": "14px", "weight": 400},
            {"role": "label", "size": "12px", "weight": 500},
        ],
        "principles": ["weight 400/500/600/700만 사용", "줄간격 본문 1.6 / 제목 1.2"],
    }

    # spacing / radius (토대, baseline)
    spacing = []
    for t, v in (("sp-1", "4px"), ("sp-2", "8px"), ("sp-3", "12px"), ("sp-4", "16px"), ("sp-6", "24px"), ("sp-10", "40px")):
        push(f"spacing.{t}", v)
        spacing.append({"token": t, "value": v})
    radius = []
    for t, v in (("r-sm", "4px"), ("r-md", "8px"), ("r-lg", "12px"), ("r-xl", "16px")):
        push(f"radius.{t}", v)
        radius.append({"token": t, "value": v})

    # Component: 명세 13종, 컴포넌트별 states(역할 토큰 참조) + 터치타겟 + uses_tokens. 토큰 키만 참조(하드코딩 색 금지).
    component = []
    for name in PRIMITIVES:
        spec = COMPONENT_SPECS[name]
        component.append({
            "component": name,
            "states": spec["states"],
            "touch_target": "44x44px" if name in INTERACTIVE else "-",
            "elevation": "surface-container",
            "uses_tokens": spec["uses_tokens"],
        })

    governance = {
        "accessibility": {"min_touch_target": "44x44px", "contrast": "WCAG AA 4.5:1",
                          "min_input_height": "44px", "min_text_size": "11px"},
        "interaction": {"states": ["enabled", "hover", "focus", "disabled", "selected", "checked", "on", "off"]},
        "responsiveness": {"modes": ["light", "dark"], "dynamic_color": False},
    }
    # G20: 근거 없는 레이어는 open_questions
    open_questions.append("pattern 레이어: 근거(features 도메인 상태) 없음 -> 보류(자리만)")
    open_questions.append("motion 레이어: 근거 없음 -> 미정의")

    # 하류(wireframe·frontend) 소비 형상 정렬: 엔진 산출(tokens)을 키만 투영한다. 값·결정성 불변.
    # token은 component uses_tokens가 참조하는 full dotted key와 동일해야 멤버십이 성립한다.
    color_tokens = [{"token": t["token_key"]} for t in tokens if t["token_key"].startswith("color.")]
    spacing_tokens = [{"token": t["token_key"]} for t in tokens if t["token_key"].startswith("spacing.")]
    radius_tokens = [{"token": t["token_key"]} for t in tokens if t["token_key"].startswith("radius.")]

    body = {
        "seed": {"primary": seed["primary"], "secondary": seed["secondary"],
                 "font_family": seed["font_family"], "icon_pack": seed["icon_pack"],
                 "source": seed["source"], "source_reference_id": seed["source_reference_id"]},
        "foundation": {"color": color, "surface_tones": surface_tones,
                       "typography": typography, "spacing": spacing, "radius": radius},
        "semantic": {"state_mapping": state_mapping, "ui_intent": ui_intent},
        "component_specs": component,
        "color_tokens": color_tokens,
        "spacing": spacing_tokens,
        "radius": radius_tokens,
        "pattern": [],
        "governance": governance,
        "tokens": tokens,
        "reference": {
            "applied": [{"token_key": k, "value": v, "source_reference_id": rid} for k, (v, rid) in applied.items()],
            "conflicts": seed["_conflicts"],
            "whitelist_violations": seed["_whitelist_violations"],
            "wcag_warnings": seed["_wcag_warnings"],
        },
        "open_questions": open_questions,
        "provenance": {
            "seed": seed["source"],
            "foundation": "baseline",
            "semantic": "baseline",
            "component": "baseline",
            "governance": "baseline",
            "tokens": "per_token",
            "reference_analysis": "inference",
        },
    }
    return body


def validate(body: dict) -> dict:
    """재정의 계약을 코드로 강제한다. 위반 시 raise."""
    required = {"seed", "foundation", "semantic", "component_specs", "pattern",
                "governance", "tokens", "reference", "open_questions", "provenance"}
    missing = required - set(body)
    if missing:
        raise ValueError(f"design_system body 필드 누락: {missing}")

    # F: 토큰 단위 traceability
    if not body["tokens"]:
        raise ValueError("tokens 비어 있음(traceability 없음)")
    for t in body["tokens"]:
        if not t.get("token_key") or "value" not in t:
            raise ValueError(f"토큰 token_key/value 누락: {t}")
        origin = t.get("origin")
        if origin not in ALLOWED_ORIGINS:
            raise ValueError(f"traceability 위반: origin 없음/허용 안 됨 '{origin}' ({t.get('token_key')})")
        if origin.startswith("reference-") and not t.get("source_reference_id"):
            raise ValueError(f"traceability 위반: {origin} 인데 source_reference_id 없음 ({t['token_key']})")
        if origin == "baseline" and t.get("source_reference_id"):
            raise ValueError(f"traceability 위반: baseline 인데 source_reference_id 존재 ({t['token_key']})")
    if body["provenance"].get("tokens") != "per_token":
        raise ValueError("provenance.tokens는 per_token이어야 함")

    # E12: 컴포넌트 6종 구조 보존(발명 금지)
    comps = [c["component"] for c in body["component_specs"]]
    if set(comps) != set(PRIMITIVES):
        raise ValueError(f"컴포넌트 13종 불변 위반: {comps} (기대 {list(PRIMITIVES)})")

    # 접근성 토대(터치타겟 44px·WCAG) 불변
    acc = body["governance"].get("accessibility", {})
    if acc.get("min_touch_target") != "44x44px":
        raise ValueError("접근성 토대 위반: 터치타겟 44x44px 불변")
    if "WCAG AA" not in (acc.get("contrast") or ""):
        raise ValueError("접근성 토대 위반: WCAG AA 기준 불변")

    return body


def offline_llm(system: str, user: str) -> str:
    """결정적 오프라인 모드. reference token 즉시 적용, image/url은 open_questions, baseline fallback."""
    payload = json.loads(user)
    body = _build_body(payload.get("intake", {}) or {}, payload.get("strategy", {}) or {}, payload.get("ux", {}) or {})
    return json.dumps(body, ensure_ascii=False)


def _extract_json(text: str) -> str:
    text = text.replace("```json", "").replace("```", "").strip()
    i, j = text.find("{"), text.rfind("}")
    return text[i:j + 1] if i != -1 and j != -1 and j > i else text


def make_real_llm(model=REAL_MODEL_DEFAULT, max_tokens=1024):
    """real llm(system, user) -> str. Claude는 brand seed(색)만 결정하고, 토큰은 결정적 엔진(_build_body)이 생성한다.
    실패(SDK 미설치/키 없음/네트워크/API 에러/형식 오류)는 RuntimeError — produce에서 offline 폴백."""
    def real_llm(system: str, user: str) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError("real 모드 불가: anthropic SDK 미설치") from e
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("real 모드 불가: ANTHROPIC_API_KEY 없음")
        payload = json.loads(user)
        intake = dict(payload.get("intake", {}) or {})
        strategy = payload.get("strategy", {}) or {}
        ux = payload.get("ux", {}) or {}
        discovery = payload.get("discovery", {}) or {}
        # 1) Claude에게 seed만 묻는다(strategy·discovery·references 맥락).
        seed_user = json.dumps({"strategy": strategy, "discovery": discovery,
                                "references": intake.get("references", [])}, ensure_ascii=False)
        client = anthropic.Anthropic(api_key=api_key)
        try:
            resp = client.messages.create(model=model, max_tokens=max_tokens,
                                          system=system + SEED_INSTRUCTION,
                                          messages=[{"role": "user", "content": seed_user}])
        except Exception as e:
            raise RuntimeError(f"real 모드 Anthropic API 호출 실패: {type(e).__name__}: {e}") from e
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        try:
            seed = json.loads(_extract_json(text))
        except Exception as e:
            raise RuntimeError(f"real seed JSON 파싱 실패: {e}") from e
        primary = (seed.get("primary") or "").strip()
        if not _HEX_RE.match(primary):
            raise RuntimeError(f"real seed primary hex 형식 오류: '{primary}'")
        # 2) 결정적 엔진에 주입: seed를 합성 reference token으로 넣어 _build_body가 토큰을 WCAG 보장·결정적으로 생성.
        value = {"color.primary": primary}
        if seed.get("secondary") and _HEX_RE.match(str(seed["secondary"])):
            value["color.secondary"] = seed["secondary"]
        if seed.get("font_family"):
            value["font.family"] = seed["font_family"]
        ref_id = seed.get("source_reference_id") or f"real-seed:{seed.get('source', 'inference')}"
        refs = list(intake.get("references", []) or [])
        refs.append({"reference_id": ref_id, "type": "token", "value": value,
                     "source": f"real:{seed.get('source', 'inference')}"})
        intake["references"] = refs
        body = _build_body(intake, strategy, ux)
        # seed 결정 근거 표시(토큰 무변경; 표시용 필드만 덧붙임)
        if isinstance(body.get("seed"), dict):
            body["seed"]["rationale"] = seed.get("rationale")
            body["seed"]["decided_source"] = seed.get("source")
        return json.dumps(body, ensure_ascii=False)
    return real_llm


real_llm = make_real_llm()


def produce(inputs: dict, llm=offline_llm) -> dict:
    intake = inputs["intake"]
    strategy = inputs.get("strategy", {})
    ux = inputs.get("ux", {})
    discovery = inputs.get("discovery", {})  # v13: real seed 결정에 목표·전략 맥락 사용
    up = build_user_prompt(intake, strategy, ux, discovery)
    try:
        raw = llm(SYSTEM_PROMPT, up)
    except RuntimeError:
        raw = offline_llm(SYSTEM_PROMPT, up)  # real 실패 -> offline 폴백
    raw = raw.replace("```json", "").replace("```", "").strip()
    body = json.loads(raw)
    return validate(body)


def make_producer(llm=offline_llm):
    """orchestrator에 등록할 producer(inputs)->body 클로저. mock: make_producer(). real: make_producer(real_llm)."""
    def producer(inputs):
        return produce(inputs, llm=llm)
    return producer
