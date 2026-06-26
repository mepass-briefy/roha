"""
ROHA Agentic Runtime (에이전트 비의존).

Generate -> Gate -> (Converge ? stop : Repair -> 다음 Generate) 루프를 제어한다.
이 모듈에는 어떤 에이전트(backend/frontend/...) 지식도 없다. 네 개를 주입받는다:
  generate(inputs, prior=None, repair_directive=None) -> body(dict)
  gate(record_type, body) -> {"errors":[...], "warnings":[...], "status":...}
  repair(body, gate_result) -> repair_directive(str|None)
  converge(gate_result, iter, max_iter, prev_gate=None, changed=True) -> {"stop":bool, "reason":str}

판정은 Gate가 유일하다(Self-Critique 없음). Runtime 본체 = 루프 제어 + iteration 저장 + diff + max_iter + 비용 가드.
"""
import json
import time

DEFAULT_MAX_ITER = 4


def _canon(body) -> str:
    """body 동일성 비교용 canonical 직렬화(no_progress 판정)."""
    return json.dumps(body, ensure_ascii=False, sort_keys=True)


def diff_bodies(prev, cur) -> dict:
    """제네릭 구조 diff(에이전트 무관). top-level 키별 변화 + 리스트 길이 델타.
    body 내부 스키마를 모른 채 수렴 과정을 추적할 수 있게 한다."""
    out = {}
    prev = prev or {}
    cur = cur or {}
    for k in sorted(set(prev) | set(cur)):
        a = prev.get(k)
        b = cur.get(k)
        if a == b:
            continue
        if isinstance(a, list) or isinstance(b, list):
            out[k] = {"len_before": len(a or []), "len_after": len(b or [])}
        elif isinstance(a, dict) or isinstance(b, dict):
            out[k] = {"keys_before": len(a or {}), "keys_after": len(b or {})}
        else:
            out[k] = {"changed": True}
    return out


def default_gate(run_review_gate):
    """run_review_gate(record_type, body)->{status,reasons,warnings} 를 Runtime gate 형태로 어댑트.
    reasons=계약 ERROR(차단), warnings=품질 WARN. 에이전트 무관(record_type만 전달)."""
    def gate(record_type, body):
        r = run_review_gate(record_type, body)
        return {"errors": list(r["reasons"]), "warnings": list(r["warnings"]), "status": r["status"]}
    return gate


def default_repair(body, gate_result):
    """Gate 사유만으로 보강 지시를 만든다(게이트 밖 기준·self-critique 금지).
    발명 금지: 입력 근거 안에서만 보강하라는 지시. 에이전트별 입력 키는 명시하지 않는다(주입된 generate가 컨텍스트를 안다)."""
    errs = gate_result.get("errors") or []
    warns = gate_result.get("warnings") or []
    if not errs and not warns:
        return None
    lines = [
        "직전 산출이 아래 Gate 지적을 받았다. 같은 입력만 근거로 보강하라.",
        "새 항목(엔티티·엔드포인트·화면·토큰 등)이나 근거 없는 값을 발명하지 마라. 입력에 없는 것은 open_questions로 남겨라.",
    ]
    if errs:
        lines.append("[ERROR — 반드시 해소]")
        lines += [f"  - {e}" for e in errs]
    if warns:
        lines.append("[WARN — 가능하면 보강(불가하면 open_questions)]")
        lines += [f"  - {w}" for w in warns]
    return "\n".join(lines)


def default_converge(gate_result, it, max_iter, prev_gate=None, changed=True):
    """수렴 정책(확정안):
      1차 목표 ERROR 0(필수). errors 비면 계약 통과.
      ERROR 0 후 WARN은 max_iter 한도 내 best-effort. 못 줄여도 종료(통과).
    종료 사유: error_cleared | warn_exhausted | max_iter | no_progress."""
    errs = gate_result.get("errors") or []
    warns = gate_result.get("warnings") or []
    # no_progress: 직전 대비 body·gate 변화 없음 -> 무의미 반복 차단.
    if prev_gate is not None and not changed:
        return {"stop": True, "reason": "warn_exhausted" if not errs else "no_progress"}
    if not errs and not warns:
        return {"stop": True, "reason": "error_cleared"}
    if not errs:
        # ERROR 0, WARN 남음 -> 한도 내 best-effort, 한도 도달 시 통과 종료.
        if it >= max_iter:
            return {"stop": True, "reason": "warn_exhausted"}
        return {"stop": False, "reason": "warn_best_effort"}
    # ERROR 남음 -> repair 계속, 한도 도달 시 종료(미수렴).
    if it >= max_iter:
        return {"stop": True, "reason": "max_iter"}
    return {"stop": False, "reason": "repairing"}


def _gate_counts(gr):
    g = gr or {}
    return len(g.get("errors") or []), len(g.get("warnings") or [])


def run_loop(record_type, inputs, generate, gate, repair,
             converge=default_converge, max_iter=DEFAULT_MAX_ITER,
             max_calls=None, history_sink=None, clock=None):
    """Generate->Gate->Converge?->Repair 루프. 에이전트 지식 없음.
    ERROR monotonic 강화: ERROR를 늘리는 재산출(회귀)은 다음 repair의 기반(prior)으로 채택하지 않는다.
      기각본도 history엔 전량 저장(append-only 불변, rejected=True). 다음 repair는 직전 채택본(ERROR 더 적은)에서 재시도.
    종료 시 best-so-far(ERROR 최소 -> WARN 최소 -> 최신) 반환. ERROR 잔존이면 final_status=FAIL(숨기지 않음).
    Converge 정책(ERROR 0 필수 + WARN best-effort)은 불변 — 채택된 현재 상태(base_gate)로 판정한다.
    반환: {final_body, converged, reason, iterations, calls, best_iter, final_status, final_errors}.
    iteration 레코드: {iter, body, gate_result, diff, applied_directive, rejected, converged, stop, reason, repair, ts}."""
    clock = clock or time.time
    cap = max_calls if max_calls is not None else max_iter
    history = []
    base_body = None       # 채택된 기반: 다음 generate의 prior, 다음 repair의 대상
    base_gate = None
    best = None            # {"body","gate","iter"} — ERROR 최소 -> WARN 최소 -> 최신
    prev_raw_body = None   # no_progress 판정(직전 raw 산출 대비 변화)
    prev_raw_gate = None
    directive = None       # 다음 generate에 주입할 보강 지시(채택본 repair 결과)
    reason = "max_iter"
    calls = 0

    def _is_better(gr, it, cur):
        if cur is None:
            return True
        e, w = _gate_counts(gr)
        ce, cw = _gate_counts(cur["gate"])
        if e != ce:
            return e < ce
        if w != cw:
            return w < cw
        return it >= cur["iter"]  # 동률이면 최신

    for it in range(1, max_iter + 1):
        if calls >= cap:
            reason = "max_calls"
            break
        applied = directive
        # generate 실패(파싱·스키마 등 생산자 구조 계약 위반)는 crash가 아니라 수리 대상 iteration으로 다룬다.
        # 판정 자체는 Gate가 유일하지만, Gate에 도달조차 못한 구조 실패는 그 사유를 repair로 환류한다(self-critique 아님).
        try:
            body = generate(inputs, prior=base_body, repair_directive=applied)
            calls += 1
            gr = gate(record_type, body)
        except Exception as e:
            calls += 1
            body = base_body
            gr = {"errors": [f"[생성 실패] {type(e).__name__}: {e}"], "warnings": [], "status": "FAIL"}

        n_err = _gate_counts(gr)[0]
        base_err = _gate_counts(base_gate)[0] if base_gate is not None else None
        # ERROR 회귀 기각: 직전 채택본보다 ERROR가 늘면 기각(다음 prior/repair 대상에서 제외). history엔 남긴다.
        rejected = base_gate is not None and n_err > base_err

        prev_base_gate = base_gate
        if not rejected:
            base_body, base_gate = body, gr

        # best-so-far 갱신(기각본 포함 비교 — ERROR 최소 기준이라 회귀본은 선택되지 않는다).
        if _is_better(gr, it, best):
            best = {"body": body, "gate": gr, "iter": it}

        # no_progress: 직전 raw 산출 대비 변화 여부(반복된 동일 회귀/정체 차단).
        raw_changed = not (prev_raw_body is not None
                           and _canon(body) == _canon(prev_raw_body) and gr == prev_raw_gate)
        # Converge는 '채택된 현재 상태'(base_gate)로 판정 — 회귀를 기각했으면 ERROR 0 상태 유지로 본다(정책 불변).
        decision = converge(base_gate, it, max_iter, prev_gate=prev_base_gate, changed=raw_changed)

        rec = {
            "iter": it, "body": body, "gate_result": gr,
            "diff": diff_bodies(prev_raw_body, body), "applied_directive": applied,
            "rejected": rejected,
            "converged": decision["stop"] and not (base_gate.get("errors") or []),
            "stop": decision["stop"], "reason": decision["reason"], "repair": None,
            "ts": clock(),
        }
        if not decision["stop"]:
            directive = repair(base_body, base_gate)  # 채택본 기반 repair(회귀본 아님)
            rec["repair"] = directive
        history.append(rec)
        if history_sink:
            history_sink(rec)
        prev_raw_body, prev_raw_gate = body, gr
        if decision["stop"]:
            reason = decision["reason"]
            break

    best_body = best["body"] if best else None
    best_gate = best["gate"] if best else {"errors": [], "warnings": []}
    n_err, n_warn = _gate_counts(best_gate)
    final_status = "FAIL" if n_err else ("WARN" if n_warn else "PASS")
    return {"final_body": best_body, "converged": (n_err == 0), "reason": reason,
            "iterations": history, "calls": calls,
            "best_iter": (best["iter"] if best else None),
            "final_status": final_status, "final_errors": n_err}
