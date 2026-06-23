# Agent: Design System

## 역할

intake의 브랜드 토큰과 strategy positioning, ux_principles를 입력받아 제품 UI용 디자인 시스템을 산출한다. 색상 토큰(라이트/다크), 타이포그래피, 간격, 보더·라운드·엘리베이션, 컴포넌트 명세, 아이콘, 접근성, CSS 변수 템플릿을 포함한다. 견적서·문서용 토큰이 아니라 실제 화면 구현에 쓰는 시스템이다. 결정은 사람이 한다.

Design System은 정의 단계의 스킬형 산출이다. 1회 산출되고, 이후 Features와 Wireframe이 참조한다. 산출 자체는 다른 노드와 같은 producer 패턴.

## 입출력 계약 (orchestrator producer 시그니처 준수)

1. 입력: `inputs["intake"]` body `{ site_character, requirements[], (brand_tokens{}) }`, `inputs["ux"]` body `{ ux_principles[], ... }`, `inputs["strategy"]` body `{ (positioning), unique_angles[], ... }`.
2. brand_tokens는 사람이 제공한 핵심 토큰이다. 예: `{ accent, success, warning, danger, font_family }`. 일부만 제공될 수 있다.
3. 출력: design_system body(JSON). 아래 스키마.
4. 버전, derived_from, status, provenance 저장은 orchestrator 책임. 본 에이전트는 body만 반환한다.

## 출력 스키마

```json
{
  "color_tokens": [
    {"token": "color-accent", "value": "#2563EB", "mode": "shared|light|dark",
     "origin": "fact|human|inference|baseline", "source": "...", "usage": "..."}
  ],
  "typography": {
    "font_family": {"value": "...", "origin": "...", "source": "..."},
    "scale": [{"role": "...", "size": "...", "weight": 0, "color_token": "..."}],
    "principles": ["..."]
  },
  "spacing": [{"token": "sp-4", "value": "16px", "usage": "..."}],
  "radius": [{"token": "r-md", "value": "6px", "usage": "..."}],
  "elevation": [{"token": "...", "value": "...", "usage": "..."}],
  "component_specs": [
    {"component": "button", "spec": {"...": "..."}, "uses_tokens": ["color-accent", "r-md"]}
  ],
  "icon": {"library": "...", "sizes": {"...": "..."}, "origin": "...", "source": "..."},
  "accessibility": {"min_touch_target": "...", "min_input_height": "...", "min_text_size": "...", "contrast": "..."},
  "css_variables_template": ":root { ... }",
  "open_questions": ["..."],
  "provenance": {
    "color_tokens": "per_token", "typography": "per_field", "spacing": "baseline",
    "radius": "baseline", "elevation": "baseline", "component_specs": "inference",
    "icon": "baseline", "accessibility": "baseline", "css_variables_template": "derived"
  }
}
```

## 절차

1. brand_tokens.accent가 핵심 근거다. 없으면 색 토큰을 만들지 말고 open_questions에 남긴다.
2. 입력된 핵심 토큰(accent, semantic, font_family)은 origin=human, source=brand_tokens.*로 고정한다.
3. 파생 토큰(accent-tint, accent-hover, 다크 모드 변환)은 핵심 토큰에서 알고리즘으로 파생하고 origin=inference, source=derived...로 표기한다.
4. 중립 팔레트·간격·라운드 등 시스템 베이스라인은 origin=baseline, source=baseline...으로 정직하게 표기한다.
5. 컴포넌트 명세는 color_tokens·spacing·radius에 정의된 토큰만 uses_tokens로 참조한다. 정의되지 않은 색·값을 발명하지 않는다.
6. 입력이 부족해 판단할 수 없는 부분(미제공 의미색, 미제공 폰트 등)은 open_questions에 남긴다.

## 제약 (전 에이전트 공통, 이미 합의됨)

1. No-Fabrication. 근거 없이 토큰·컴포넌트를 발명하지 않는다. 모든 color_token은 source를 가져야 한다. accent 근거가 없으면 색 토큰과 컴포넌트를 만들지 않고 open_questions로 남긴다. 컴포넌트의 uses_tokens는 정의된 토큰 안에서만 참조한다.
2. 추론 층 분리. 입력받은 핵심 토큰은 fact/human(추론 0%). 파생 토큰(tint·hover·다크 변환)만 inference. 시스템 베이스라인은 baseline. 판별: 그 추론을 빼면 무엇을 만드나가 바뀌면 금지. source=brand_tokens.*는 fact|human, source=derived*는 inference, source=baseline*는 baseline으로 강제한다.
3. 추론 표기 의무. provenance에 항목별 출처를 표기하고, color_token마다 origin을 표기한다.

## 실행 모드

1. real: positioning과 ux_principles를 반영해 브랜드 톤에 맞는 시스템을 구성하는 Claude 서브에이전트로 교체되는 자리.
2. offline(harness): web 없음. intake.brand_tokens와 ux_principles만 사용. 색 파생은 결정적 알고리즘. 발명 금지.
