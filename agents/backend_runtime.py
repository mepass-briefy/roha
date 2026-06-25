"""
backend용 Agentic Runtime 결합부 (backend 지식은 여기에만).

Runtime 본체(agentic_runtime)는 에이전트 무관. 이 모듈이 backend에 한정된 generate를 만든다:
  - generate = backend.produce 재사용 + repair_directive를 LLM 프롬프트에 주입(backend.py 무수정).
  - gate/repair/converge는 Runtime 기본 구현(agentic_runtime)을 그대로 쓴다(backend 지식 없음).

분리성: frontend/mobile 확장 시 make_*_generate 한 함수만 추가하면 된다. Runtime 본체는 불변.
"""
from pathlib import Path

import agentic_runtime as rt
import backend as backend_agent
import gate_review


def _inject_directive(base_llm, directive):
    """base_llm(prompt_messages)->str 를 감싸, 보강 지시를 user 메시지에 덧붙인다.
    backend.produce/execute/build_prompt 무수정. real 실패 시 execute의 offline 폴백 그대로(directive 없는 결정적 산출)."""
    def llm(prompt):
        if directive:
            prompt = [dict(m) for m in prompt]
            for m in prompt:
                if m.get("role") == "user":
                    m["content"] = m["content"] + "\n\n## 직전 Gate 사유(보강 지시 — 입력 근거 내에서만)\n" + directive
        return base_llm(prompt)
    return llm


def make_backend_generate(base_llm, artifact_dir):
    """Runtime generate(inputs, prior, repair_directive) -> body. backend.produce 재사용."""
    def generate(inputs, prior=None, repair_directive=None):
        llm = _inject_directive(base_llm, repair_directive)
        return backend_agent.produce(inputs, llm=llm, artifact_dir=artifact_dir)
    return generate


def make_runtime_producer(base_llm, artifact_dir, max_iter=rt.DEFAULT_MAX_ITER,
                          max_calls=None, history_sink=None):
    """orchestrator producer(inputs)->body. 내부에서 Runtime 루프를 돌리고 확정본(final_body)만 반환.
    iteration 이력은 history_sink로 흘린다(append-only). 단발 경로와 동일하게 body dict 반환."""
    generate = make_backend_generate(base_llm, artifact_dir)
    gate = rt.default_gate(gate_review.run_review_gate)

    def producer(inputs):
        result = rt.run_loop(
            "backend", inputs, generate, gate, rt.default_repair,
            converge=rt.default_converge, max_iter=max_iter,
            max_calls=max_calls, history_sink=history_sink,
        )
        return result["final_body"]
    return producer


def jsonl_history_sink(path):
    """iteration 레코드를 append-only JSONL로 저장(ROHA append-only 철학). 확정본은 별도 record, 중간본은 내부 이력."""
    import json
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def sink(rec):
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return sink
