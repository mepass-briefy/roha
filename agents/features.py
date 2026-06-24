"""
Features Agent producer.

orchestrator 계약: producer(inputs: dict) -> body: dict
모델 호출은 llm(system, user) -> str 인터페이스로 분리한다.
  - real: Anthropic messages API(키는 .env의 ANTHROPIC_API_KEY). 실패 시 mock 폴백 없이 RuntimeError.
          FEATURES_SEARCH=on이면 strategy가 찾은 경쟁사의 "기능"을 web_search로 조사.
  - offline(mock): 결정적. ux/security/strategy 입력만 사용.

features는 외부 사실 검색이 아니라 '요구를 펼치는' 역할이다. 모든 확장 기능을 4분류로 태깅한다:
  Explicit(fact) / Derived(inference) / Operational(inference,operational) / Competitive(fact,URL).
  Business는 자동 채택 금지 -> open_questions로 전환(provenance=open_question).
본 에이전트는 body만 반환한다. 버전/derived_from/status는 orchestrator 책임.
"""

import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # dotenv 없으면 환경변수만 사용(real 모드에서만 키 필요)

AGENT_NAME = "agent.features"
SYSTEM_PROMPT = Path(__file__).with_name("agent_features.md").read_text(encoding="utf-8")

CORE_ORIGINS = ("fact", "human")
ALLOWED_ORIGINS = ("fact", "human", "inference")
# features에 들어갈 수 있는 4분류(Business는 features에 넣지 않고 open_questions로).
FEATURE_CATEGORIES = ("Explicit", "Derived", "Operational", "Competitive")

REAL_MODEL_DEFAULT = "claude-sonnet-4-6"
WEB_SEARCH_TOOL_TYPE = "web_search_20250305"
WEB_SEARCH_MAX_USES_DEFAULT = 5

REAL_MODE_INSTRUCTION = (
    "\n\n## real 모드 지시(features = 요구 펼치기)\n"
    "사용자 요구(intake)와 strategy/ux/security 산출을 실무 수준 기능으로 펼치되, 모든 기능을 category로 태깅한다:\n"
    "1. Explicit: 사용자가 직접 명시한 요구. origin=fact, source=\"requirement:<요구>\" 또는 \"ux:<태스크>\".\n"
    "2. Derived: 요구에서 직접 추론 가능한 기능. origin=inference, source=\"derived:<어느 요구에서>\".\n"
    "3. Operational: 일반 운영 관행 기반 추론. origin=inference, source=\"derived:operational:<근거>\".\n"
    "4. Business: 사업 판단이 필요한 것. features에 넣지 말고 open_questions에 \"[Business] ...\"로 기록한다(자동 채택 금지).\n"
    "경계 규칙: Derived/Operational/Business 판단이 애매하면 더 보수적인 쪽(Business=open_questions)으로. 발명보다 질문.\n"
    "Fabrication 금지: 어느 요구에서도 도출되지 않는 신규 기능은 출력하지 않는다.\n"
    "strategy가 이미 경쟁사를 분석했으므로 경쟁사를 다시 발굴하지 않는다.\n"
    "category 값은 정확히 다음 중 하나만 쓴다(풀네임·설명 텍스트 금지): \"Explicit\", \"Derived\", \"Operational\", \"Competitive\".\n"
    "provenance.features=\"per_item\". 각 기능에 category·origin·source를 표기한다. 출력은 features body JSON만(코드펜스/설명 금지)."
)

REAL_SEARCH_INSTRUCTION = (
    "\n\n## web_search 지시(ON)\n"
    "strategy가 찾은 경쟁사의 '기능'만 web_search로 조사한다(경쟁사 재발굴 금지).\n"
    "1. 발견한 경쟁사 기능은 category=Competitive, origin=fact, source=출처 URL(http...)로 기록한다.\n"
    "2. '경쟁사에 있으니 우리도'를 자동 채택하지 마라. 채택 여부는 Business이므로 open_questions에 \"[Business] 경쟁사 기능 ... 채택 검토\"로 남긴다.\n"
    "3. 검색 결과에 없는 경쟁사 기능을 지어내지 마라."
)


def build_user_prompt(intake: dict, ux: dict, security: dict, strategy: dict) -> str:
    return json.dumps({"intake": intake, "ux": ux, "security": security, "strategy": strategy},
                      ensure_ascii=False)


def _extract_json(text: str) -> str:
    text = text.replace("```json", "").replace("```", "").strip()
    i, j = text.find("{"), text.rfind("}")
    return text[i:j + 1] if i != -1 and j != -1 and j > i else text


def validate(body: dict) -> dict:
    """합의된 제약 + 4분류 태깅을 코드로 강제한다. 위반 시 raise."""
    required = {"features", "open_questions", "provenance"}
    missing = required - set(body)
    if missing:
        raise ValueError(f"features body 필드 누락: {missing}")

    prov = body["provenance"]
    names = set()
    has_acceptance = False

    for f in body["features"]:
        name = f.get("feature")
        if not name:
            raise ValueError("feature 이름 누락")
        if not f.get("source"):
            raise ValueError(f"No-Fabrication 위반: source 없는 기능 '{name}'")
        origin = f.get("origin")
        if origin not in ALLOWED_ORIGINS:
            raise ValueError(f"허용되지 않은 origin '{origin}' (기능 '{name}')")
        # 4분류 태깅 필수(Business는 features 금지 -> open_questions로)
        cat = f.get("category")
        if cat not in FEATURE_CATEGORIES:
            raise ValueError(
                f"4분류 태깅 누락/위반: 기능 '{name}' category='{cat}' "
                f"(Explicit/Derived/Operational/Competitive 중 하나여야 하며 Business는 open_questions로)")
        src = f["source"]
        # category별 origin·source 정합(추론 층 분리)
        if cat == "Explicit":
            if origin != "fact" or not (src.startswith("ux:") or src.startswith("requirement:")):
                raise ValueError(f"Explicit '{name}'은 origin=fact + source ux:/requirement: 여야 함(현재 origin={origin}, src='{src}')")
        elif cat in ("Derived", "Operational"):
            if origin != "inference" or not src.startswith("derived:"):
                raise ValueError(f"{cat} '{name}'은 origin=inference + source derived: 여야 함(현재 origin={origin}, src='{src}')")
        elif cat == "Competitive":
            if origin != "fact" or not (src.startswith("http://") or src.startswith("https://")):
                raise ValueError(f"Competitive '{name}'은 origin=fact + source 출처 URL(http) 여야 함(현재 origin={origin}, src='{src}')")
        if f.get("acceptance_criteria"):
            has_acceptance = True
        if name in names:
            raise ValueError(f"중복 기능명: '{name}'")
        names.add(name)

    if body["features"] and prov.get("features") != "per_item":
        raise ValueError("provenance.features는 per_item이어야 함(기능별 origin 표기)")
    if has_acceptance and prov.get("acceptance_criteria") != "inference":
        raise ValueError("provenance.acceptance_criteria는 inference여야 함")
    if any(f.get("security_controls") for f in body["features"]) and prov.get("security_controls") != "fact":
        raise ValueError("provenance.security_controls는 fact여야 함(security 통제 참조)")

    return body


def offline_llm(system: str, user: str) -> str:
    """결정적 mock. ux/security/strategy 입력만 사용. 발명 금지. 4분류 태깅 포함."""
    payload = json.loads(user)
    ux = payload.get("ux", {}) or {}
    security = payload.get("security", {}) or {}
    strategy = payload.get("strategy", {}) or {}

    primary_tasks = [t["task"] for t in ux.get("primary_tasks", [])]
    flows_by_task = {f["task"]: f.get("steps", []) for f in ux.get("user_flows", [])}
    wow_points = strategy.get("wow_points", [])

    controls_by_req = {}
    for r in security.get("security_requirements", []):
        controls_by_req.setdefault(r.get("source_requirement"), []).append(r.get("control"))

    features = []
    open_questions = []

    if not primary_tasks:
        open_questions.append("ux.primary_tasks 없음: 핵심 기능 도출 불가")

    for i, task in enumerate(primary_tasks):
        steps = flows_by_task.get(task, [])
        acceptance = [f"{s} 가능" for s in steps] if steps else [f"{task} 완료 가능"]
        controls = controls_by_req.get(task, [])
        features.append({
            "feature": task, "category": "Explicit",          # 사용자 명시 요구를 ux가 태스크화
            "source": f"ux:{task}", "origin": "fact",
            "priority": "high" if i == 0 else "medium",
            "acceptance_criteria": acceptance, "security_controls": controls,
        })
        if not controls:
            open_questions.append(f"기능 '{task}'에 매핑된 보안 통제 없음: 검토 필요")

    # 보완 기능: 와우포인트 기반(Derived/inference)
    for w in wow_points:
        features.append({
            "feature": f"차별 기능: {w}", "category": "Derived",
            "source": "derived:strategy.wow_point", "origin": "inference",
            "priority": "low", "acceptance_criteria": [], "security_controls": [],
        })

    body = {
        "features": features,
        "open_questions": open_questions,
        "provenance": {
            "features": "per_item", "priority": "inference",
            "acceptance_criteria": "inference", "security_controls": "fact",
        },
    }
    return json.dumps(body, ensure_ascii=False)


def make_real_llm(model=REAL_MODEL_DEFAULT, max_tokens=8192, max_searches=WEB_SEARCH_MAX_USES_DEFAULT,
                  use_search=False):
    """real llm(system, user) -> str. Anthropic messages API(+선택적 web_search).
    실패는 mock 폴백 없이 RuntimeError. use_search=True면 경쟁사 기능 조사(Competitive Reference)."""
    def real_llm(system: str, user: str) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError("real 모드 불가: anthropic SDK 미설치 (pip install anthropic)") from e
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("real 모드 불가: ANTHROPIC_API_KEY 환경변수 없음 (mock으로 폴백하지 않음)")
        sys_prompt = system + REAL_MODE_INSTRUCTION + (REAL_SEARCH_INSTRUCTION if use_search else "")
        kwargs = {"model": model, "max_tokens": max_tokens, "system": sys_prompt,
                  "messages": [{"role": "user", "content": user}]}
        if use_search:
            kwargs["tools"] = [{"type": WEB_SEARCH_TOOL_TYPE, "name": "web_search", "max_uses": max_searches}]
        client = anthropic.Anthropic(api_key=api_key)
        try:
            resp = client.messages.create(**kwargs)
        except Exception as e:
            raise RuntimeError(f"real 모드 Anthropic API 호출 실패: {type(e).__name__}: {e}") from e
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if not text:
            raise RuntimeError("real 모드: Anthropic 응답에 텍스트 없음")
        return _extract_json(text)
    return real_llm


# 편의 인스턴스(검색 off 기본). 키/네트워크는 호출 시점에 검사.
real_llm = make_real_llm()


def produce(inputs: dict, llm=offline_llm) -> dict:
    intake = inputs["intake"]
    ux = inputs.get("ux", {})
    security = inputs.get("security", {})
    strategy = inputs.get("strategy", {})
    raw = llm(SYSTEM_PROMPT, build_user_prompt(intake, ux, security, strategy))
    raw = raw.replace("```json", "").replace("```", "").strip()
    body = json.loads(raw)
    return validate(body)


def make_producer(llm=offline_llm):
    """orchestrator에 등록할 producer(inputs)->body 클로저. mock: make_producer(). real: make_producer(make_real_llm(use_search=...))."""
    def producer(inputs):
        return produce(inputs, llm=llm)
    return producer
