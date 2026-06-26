"""
Agentic Runtime glue 공통부 (에이전트 무관 메커니즘).

backend_runtime·frontend_runtime·mobile_runtime이 동일하게 쓰던 메커니즘을 한 곳에 모은다.
순수 추출 — 새 동작·새 파라미터 의미 0. 에이전트 고유(produce 호출·_indexes()·프롬프트)는 per-agent glue에 남는다.

  inject_directive(base_llm, directive)        repair_directive를 LLM 프롬프트(user)에 주입.
  make_generate(produce_fn, base_llm, dir)     Runtime generate(inputs, prior, repair_directive) 빌더. produce_fn만 per-agent.
  make_runtime_producer(record_type, gen, ...) generate를 Runtime 루프에 묶어 확정본 반환.
  jsonl_history_sink(path)                     iteration append-only JSONL 저장.
"""
import json
from pathlib import Path

import agentic_runtime as rt
import gate_review


def inject_directive(base_llm, directive):
    """base_llm(prompt_messages)->str 를 감싸 보강 지시를 user 메시지에 덧붙인다.
    에이전트의 produce/execute/build_prompt 무수정. real 실패 시 execute의 offline 폴백 그대로."""
    def llm(prompt):
        if directive:
            prompt = [dict(m) for m in prompt]
            for m in prompt:
                if m.get("role") == "user":
                    m["content"] = m["content"] + "\n\n## 직전 Gate 사유(보강 지시 — 입력 근거 내에서만)\n" + directive
        return base_llm(prompt)
    return llm


def make_generate(produce_fn, base_llm, artifact_dir):
    """Runtime generate(inputs, prior, repair_directive) -> body. produce_fn(에이전트 produce)만 per-agent.
    재산출에도 produce_fn이 _indexes()로 권위 인덱스를 입력에서 채우므로 멤버십·발명 가드 유지."""
    def generate(inputs, prior=None, repair_directive=None):
        llm = inject_directive(base_llm, repair_directive)
        return produce_fn(inputs, llm=llm, artifact_dir=artifact_dir)
    return generate


def make_runtime_producer(record_type, generate, max_iter=rt.DEFAULT_MAX_ITER,
                          max_calls=None, history_sink=None):
    """orchestrator producer(inputs)->body. Runtime 루프 후 확정본(final_body)만 반환.
    gate/repair/converge는 Runtime 기본 구현(에이전트 지식 없음). 단발 경로와 동일하게 body dict 반환."""
    gate = rt.default_gate(gate_review.run_review_gate)

    def producer(inputs):
        result = rt.run_loop(
            record_type, inputs, generate, gate, rt.default_repair,
            converge=rt.default_converge, max_iter=max_iter,
            max_calls=max_calls, history_sink=history_sink,
        )
        return result["final_body"]
    return producer


def jsonl_history_sink(path):
    """iteration 레코드를 append-only JSONL로 저장(ROHA append-only). 확정본은 record, 중간본은 내부 이력."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def sink(rec):
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return sink
