"""
backend용 Agentic Runtime 결합부 (backend 지식은 여기에만).

공통 메커니즘(inject_directive·make_runtime_producer·jsonl_history_sink)은 runtime_glue로 추출.
이 모듈은 backend 고유부(make_backend_generate = backend.produce 바인딩)만 가진다. backend.py 무수정.
"""
import runtime_glue
import backend as backend_agent

# import 호환 re-export(기존 호출부 시그니처 불변).
jsonl_history_sink = runtime_glue.jsonl_history_sink


def make_backend_generate(base_llm, artifact_dir):
    """Runtime generate(inputs, prior, repair_directive) -> body. backend.produce 재사용(_indexes 권위 인덱스 유지)."""
    return runtime_glue.make_generate(backend_agent.produce, base_llm, artifact_dir)


def make_runtime_producer(base_llm, artifact_dir, max_iter=runtime_glue.rt.DEFAULT_MAX_ITER,
                          max_calls=None, history_sink=None):
    """orchestrator producer(inputs)->body. Runtime 루프 후 확정본만 반환."""
    generate = make_backend_generate(base_llm, artifact_dir)
    return runtime_glue.make_runtime_producer("backend", generate, max_iter=max_iter,
                                              max_calls=max_calls, history_sink=history_sink)
