"""
ROHA Agentic Runtime 검증.
[7] 가드(결정적, LLM 없음): no_progress / max_iter / error_cleared / warn best-effort.
[6] 실측(RUNTIME_REAL=on일 때만): backend 루프(인플루언서/풋살) — generate->gate->repair->retry->converge.
[8] 분리성: Runtime 본체엔 backend 지식 없음(별도 grep로 점검).

orchestrator·backend.py·gate_review.py 무수정. 판정은 Gate 유일.
"""
import os, sys, json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))

import agentic_runtime as rt

PASS = "PASS"

# ---------- [7] 결정적 가드 (Gate 결과를 body가 들고 다니는 합성 케이스) ----------
def fake_gate(record_type, body):
    return {"errors": list(body.get("_errors", [])), "warnings": list(body.get("_warnings", [])),
            "status": "FAIL" if body.get("_errors") else ("WARN" if body.get("_warnings") else "PASS")}


print("=== [7] no_progress 가드: 동일 body + 동일 ERROR 반복 -> 무한루프 없이 종료 ===")
def gen_stuck(inputs, prior=None, repair_directive=None):
    return {"x": 1, "_errors": ["[빈 산출] entities=[] — 채울 수 없음"]}
r = rt.run_loop("backend", {}, gen_stuck, fake_gate, rt.default_repair, max_iter=5)
print(f"  reason={r['reason']} iters={len(r['iterations'])} converged={r['converged']}")
assert r["reason"] == "no_progress" and not r["converged"], "no_progress 종료 실패"
assert len(r["iterations"]) == 2, "변화 없으면 2 iter에서 멈춰야 함"
print(" ", PASS)

print("\n=== [7] max_iter 가드: 매번 다른 body지만 ERROR 안 사라짐 -> max_iter서 종료 ===")
def make_gen_changing():
    n = {"i": 0}
    def gen(inputs, prior=None, repair_directive=None):
        n["i"] += 1
        return {"x": n["i"], "_errors": ["[발명] endpoint_ref 'ep-x'가 입력에 없음"]}
    return gen
r = rt.run_loop("backend", {}, make_gen_changing(), fake_gate, rt.default_repair, max_iter=3)
print(f"  reason={r['reason']} iters={len(r['iterations'])} converged={r['converged']}")
assert r["reason"] == "max_iter" and not r["converged"] and len(r["iterations"]) == 3
print(" ", PASS)

print("\n=== [7] error_cleared: v1 ERROR -> repair 후 v2/v3 ERROR 0 도달(통과) ===")
def make_gen_heal():
    n = {"i": 0}
    def gen(inputs, prior=None, repair_directive=None):
        n["i"] += 1
        if n["i"] == 1:
            return {"x": 1, "_errors": ["[빈 산출] endpoints=[]"], "_warnings": ["[품질] acceptance_criteria 약함"]}
        if n["i"] == 2:
            return {"x": 2, "_warnings": ["[품질] acceptance_criteria 약함"]}  # ERROR 해소, WARN 남음
        return {"x": 3}  # WARN까지 해소
    return gen
r = rt.run_loop("backend", {}, make_gen_heal(), fake_gate, rt.default_repair, max_iter=4)
errs_per = [len(it["gate_result"]["errors"]) for it in r["iterations"]]
print(f"  iter별 ERROR 수={errs_per} reason={r['reason']} converged={r['converged']}")
assert errs_per[0] == 1 and errs_per[-1] == 0, "ERROR 감소 추적 실패"
assert r["converged"] and r["reason"] == "error_cleared"
# repair가 ERROR 사유를 담았는지(게이트 기반)
assert r["iterations"][0]["repair"] and "[빈 산출]" in r["iterations"][0]["repair"]
print(" ", PASS)

print("\n=== [7] warn_exhausted: ERROR 0인데 WARN 안 줄면 한도 내 종료(통과) ===")
def make_gen_warn():
    n = {"i": 0}
    def gen(inputs, prior=None, repair_directive=None):
        n["i"] += 1
        return {"x": n["i"], "_warnings": ["[커버리지] 미구현 화면 1건"]}  # ERROR 0, WARN 고정(body는 변함)
    return gen
r = rt.run_loop("backend", {}, make_gen_warn(), fake_gate, rt.default_repair, max_iter=3)
print(f"  reason={r['reason']} iters={len(r['iterations'])} converged={r['converged']}")
assert r["converged"] and r["reason"] == "warn_exhausted"  # ERROR 0이므로 converged True
print(" ", PASS)

print("\n=== [7] generate 실패 가드: produce 예외 -> crash 없이 [생성 실패] 환류 -> 다음 iter 복구 ===")
def make_gen_raise_then_ok():
    n = {"i": 0}
    def gen(inputs, prior=None, repair_directive=None):
        n["i"] += 1
        if n["i"] == 1:
            raise ValueError("ApiSpec endpoints.0.security_ref Input should be a valid string")  # real produce 스키마 실패 모사
        return {"x": 2}  # repair 환류 후 복구(clean)
    return gen
r = rt.run_loop("backend", {}, make_gen_raise_then_ok(), fake_gate, rt.default_repair, max_iter=3)
print(f"  v1 gate errors={r['iterations'][0]['gate_result']['errors']}")
print(f"  reason={r['reason']} converged={r['converged']}")
assert "[생성 실패]" in r["iterations"][0]["gate_result"]["errors"][0], "생성 실패 환류 안 됨"
assert r["converged"] and r["reason"] == "error_cleared", "복구 수렴 실패"
assert r["iterations"][0]["repair"] and "[생성 실패]" in r["iterations"][0]["repair"]
print(" ", PASS)

# diff·history 형태 점검
print("\n=== [4] iteration history/diff 형태 ===")
last = r["iterations"][-1]
print("  iteration 키:", sorted(last.keys()))
assert set(["iter", "body", "gate_result", "diff", "repair", "converged", "reason", "ts", "applied_directive", "stop"]) <= set(last.keys())
print("  diff(예):", r["iterations"][1]["diff"])
print(" ", PASS)


# ---------- [6] 실측: backend 루프(real) ----------
if os.environ.get("RUNTIME_REAL") == "on":
    import strategy as strategy_agent
    import ux as ux_agent
    import security as security_agent
    import features as features_agent
    import backend as backend_agent
    import backend_runtime
    import gate_review

    print("\n=== [6] 실측: backend Agentic Runtime (인플루언서/풋살, real) ===")
    intake = {
        "site_character": "풋살 소셜매치 예약",
        "requirements": ["개인 신청", "매치 예약", "정산 확인"],
        "goal": {"statement": "개인이 팀 없이도 동네 풋살 매치에 참여하고 정산까지 투명하게",
                 "details": {"target_users": "풋살 동호인", "constraints": "매니저 수동 배정"}},
        "context": "개인 참여·투명 정산 소셜 매치", "target_platform": "both",
        "seed_competitors": ["PLAB"], "unique_angles": ["매니저 배정 자동화", "정산 투명성"],
        "brand_tokens": {"accent": "#7C3AED"},
    }
    strat = strategy_agent.make_producer()({"intake": intake})
    ux_b = ux_agent.make_producer()({"intake": intake, "strategy": strat})
    sec_b = security_agent.make_producer()({"intake": intake})
    feat_b = features_agent.make_producer()({"intake": intake, "ux": ux_b, "security": sec_b, "strategy": strat})
    inputs = {"features": feat_b, "security": sec_b, "ux": ux_b, "discovery": {}}

    ART = BASE / "_run_runtime" / "artifacts"
    hist_path = ART / "backend_iterations.jsonl"
    if hist_path.exists():
        hist_path.unlink()
    generate = backend_runtime.make_backend_generate(backend_agent.real_llm, ART)
    gate = rt.default_gate(gate_review.run_review_gate)
    res = rt.run_loop("backend", inputs, generate, gate, rt.default_repair,
                      max_iter=3, history_sink=backend_runtime.jsonl_history_sink(hist_path))

    print(f"  수렴: converged={res['converged']} reason={res['reason']} calls={res['calls']} iters={len(res['iterations'])}")
    for it in res["iterations"]:
        gr = it["gate_result"]
        eps = len(it["body"].get("api_spec", {}).get("endpoints", []))
        ents = len(it["body"].get("entities", []))
        print(f"  v{it['iter']}: ERROR={len(gr['errors'])} WARN={len(gr['warnings'])} "
              f"endpoints={eps} entities={ents} stop={it['stop']} reason={it['reason']}")
        if gr["errors"]:
            print("      ERROR:", gr["errors"][:2])
        if it["diff"]:
            print("      diff:", it["diff"])
    # (a) ERROR 또는 WARN 받고 (e) 최종 발명 0(ERROR 0)
    fin = res["iterations"][-1]["gate_result"]
    invented = [e for e in fin["errors"] if "[발명]" in e]
    print(f"  최종 ERROR={len(fin['errors'])} (발명={len(invented)}) | history 저장:", hist_path.exists())
    assert res["converged"], "ERROR 0 수렴 실패"
    assert not invented, "발명 발생(입력 근거 위반)"
    # (d) history 전량 저장 확인
    lines = hist_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(res["iterations"]), "history 전량 저장 실패"
    print(" ", PASS, "(실측: 수렴·발명0·history 전량 저장)")

    # ----- frontend·mobile 실측 (계약 형상 일관 입력, 동형 Runtime) -----
    import frontend as frontend_agent
    import frontend_runtime
    import mobile as mobile_agent
    import mobile_runtime

    def _report(label, res, hist_path):
        print(f"\n  [{label}] converged={res['converged']} reason={res['reason']} calls={res['calls']} iters={len(res['iterations'])}")
        for it in res["iterations"]:
            gr = it["gate_result"]
            scr = len((it["body"] or {}).get("screens", []))
            print(f"    v{it['iter']}: ERROR={len(gr['errors'])} WARN={len(gr['warnings'])} screens={scr} stop={it['stop']} reason={it['reason']}")
            if gr["errors"]:
                print("        ERROR:", gr["errors"][:2])
            if it["diff"]:
                print("        diff:", it["diff"])
        fin = res["iterations"][-1]["gate_result"]
        invented = [e for e in fin["errors"] if "[발명]" in e]
        lines = hist_path.read_text(encoding="utf-8").strip().splitlines() if hist_path.exists() else []
        assert res["converged"], f"{label} 수렴 실패"
        assert not invented, f"{label} 발명 발생"
        assert len(lines) == len(res["iterations"]), f"{label} history 전량 저장 실패"
        print(f"    {PASS} ({label}: 수렴·발명0·history {len(lines)}건)")

    def _ep2(eid, method, path, feat, succ, err):
        return {"endpoint_id": eid, "method": method, "path": path, "feature_ref": feat, "security_ref": "ctrl",
                "success_cases": [{"code": succ, "http_status": 200, "description": "d"}],
                "error_cases": [{"code": err, "http_status": 400, "description": "d"}]}

    print("\n=== [6] 실측: frontend Agentic Runtime (real) ===")
    FE_WF = {"screens": [
        {"screen": "신청 목록", "sections": [{"section": "목록", "components": ["table", "card"], "feature_refs": ["개인 신청"]}]},
        {"screen": "정산 내역", "sections": [{"section": "내역", "components": ["table"], "feature_refs": ["정산 확인"]}]}],
        "design_component_palette": ["table", "card", "button", "input"], "navigation": {"pattern": "left-sidebar"}, "open_questions": []}
    FE_DS = {"component_specs": [
        {"component": "table", "uses_tokens": ["color-primary", "r-md"]},
        {"component": "card", "uses_tokens": ["color-surface", "sp-2"]},
        {"component": "button", "uses_tokens": ["color-primary"]},
        {"component": "input", "uses_tokens": ["color-outline", "r-sm"]}],
        "color_tokens": [{"token": "color-primary"}, {"token": "color-surface"}, {"token": "color-outline"}],
        "spacing": [{"token": "sp-2"}], "radius": [{"token": "r-md"}, {"token": "r-sm"}], "open_questions": []}
    FE_BK = {"api_spec": {"endpoints": [
        _ep2("ep-applications-list", "GET", "/api/v1/applications", "개인 신청", "OK", "VALIDATION_ERROR"),
        _ep2("ep-settlements-list", "GET", "/api/v1/settlements", "정산 확인", "OK", "FORBIDDEN")]}, "open_questions": []}
    fe_inputs = {"wireframe": FE_WF, "design_system": FE_DS, "backend": FE_BK, "ux": {}, "discovery": {}}
    fe_hist = ART / "frontend_iterations.jsonl"
    if fe_hist.exists():
        fe_hist.unlink()
    fe_gen = frontend_runtime.make_frontend_generate(frontend_agent.real_llm, ART)
    fe_res = rt.run_loop("frontend", fe_inputs, fe_gen, gate, rt.default_repair,
                         max_iter=2, history_sink=frontend_runtime.jsonl_history_sink(fe_hist))
    _report("frontend", fe_res, fe_hist)

    print("\n=== [6] 실측: mobile Agentic Runtime (real) ===")
    MB_WF = {"screens": [
        {"screen": "매치 피드", "sections": [{"section": "피드", "components": ["card", "button"], "feature_refs": ["매치 예약"]}]},
        {"screen": "인플루언서 프로필", "sections": [{"section": "프로필", "components": ["card", "table"], "feature_refs": ["개인 신청"]}]}],
        "design_component_palette": ["card", "table", "button", "input", "nav"], "navigation": {"pattern": "bottom-tab"}, "open_questions": []}
    MB_DS = {"component_specs": [
        {"component": "card", "uses_tokens": ["color-surface", "sp-2"]},
        {"component": "table", "uses_tokens": ["color-primary", "r-md"]},
        {"component": "button", "uses_tokens": ["color-primary"]},
        {"component": "nav", "uses_tokens": ["color-surface"]}],
        "color_tokens": [{"token": "color-primary"}, {"token": "color-surface"}, {"token": "color-surface-dark", "mode": "dark"}],
        "spacing": [{"token": "sp-2"}], "radius": [{"token": "r-md"}],
        "accessibility": {"min_touch_target": "44x44px"}, "open_questions": []}
    MB_BK = {"api_spec": {"endpoints": [
        _ep2("ep-matches-list", "GET", "/api/v1/matches", "매치 예약", "OK", "VALIDATION_ERROR"),
        _ep2("ep-applications-get", "GET", "/api/v1/applications/{public_key}", "개인 신청", "OK", "NOT_FOUND")]}, "open_questions": []}
    mb_inputs = {"wireframe": MB_WF, "design_system": MB_DS, "backend": MB_BK, "ux": {}, "discovery": {}}
    mb_hist = ART / "mobile_iterations.jsonl"
    if mb_hist.exists():
        mb_hist.unlink()
    mb_gen = mobile_runtime.make_mobile_generate(mobile_agent.real_llm, ART)
    mb_res = rt.run_loop("mobile", mb_inputs, mb_gen, gate, rt.default_repair,
                         max_iter=2, history_sink=mobile_runtime.jsonl_history_sink(mb_hist))
    _report("mobile", mb_res, mb_hist)
else:
    print("\n[6] 실측 스킵(RUNTIME_REAL=on 아님). [5/7] 가드만 실행.")

print("\nDONE")
