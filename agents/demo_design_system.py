"""
Design System Agent(재정의) 검증.
Material 3 tonal + Reference Contract + Traceability + Conflict/Whitelist/WCAG + 게이트.
오프라인 모드(결정적). orchestrator·다른 에이전트·게이트는 수정하지 않는다.
"""
import os, sys, json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agents"))

import design_system as ds
import gate_test
import gate_review

STRAT = {"positioning": "풋살 소셜매치 예약"}
UX = {"ux_principles": []}


def produce(references):
    intake = {"site_character": "풋살 소셜매치 예약", "requirements": ["개인 신청"], "references": references}
    return ds.produce({"intake": intake, "strategy": STRAT, "ux": UX})


def oq_has(body, sub):
    return any(sub in q for q in body["open_questions"])


print("=== 1. reference 없음 -> baseline 세트 ===")
b0 = produce([])
print("seed:", b0["seed"])
print("baseline(Material seed + Pretendard + Tabler):",
      b0["seed"]["source"] == "baseline" and b0["seed"]["font_family"] == "Pretendard" and b0["seed"]["icon_pack"] == "Tabler")
print("open_questions에 기본 세트 사용 기록:", oq_has(b0, "기본 세트 사용 중"))
assert b0["seed"]["source"] == "baseline"
assert oq_has(b0, "기본 세트 사용 중")

print("\n=== 2. token reference -> 표현층만 override, 토대 불변 ===")
bt = produce([{"reference_id": "REF-001", "type": "token",
               "value": {"color.primary": "#1E88E5", "font.family": "Roboto"},
               "source": "brand kit"}])
print("seed.primary origin:", bt["seed"]["source"], "| font:", bt["seed"]["font_family"])
prim = next(t for t in bt["tokens"] if t["token_key"] == "color.light.primary")
fontt = next(t for t in bt["tokens"] if t["token_key"] == "font.family")
print("color.light.primary origin:", prim["origin"], "source_reference_id:", prim["source_reference_id"])
print("font.family origin:", fontt["origin"], "source_reference_id:", fontt["source_reference_id"])
print("컴포넌트 6종 불변:", [c["component"] for c in bt["component"]] == [c["component"] for c in b0["component"]])
print("터치타겟 44px 불변:", bt["governance"]["accessibility"]["min_touch_target"] == "44x44px")
print("spacing 체계 불변:", [s["token"] for s in bt["foundation"]["spacing"]] == [s["token"] for s in b0["foundation"]["spacing"]])
assert prim["origin"] == "reference-token" and prim["source_reference_id"] == "REF-001"
assert [c["component"] for c in bt["component"]] == [c["component"] for c in b0["component"]]

print("\n=== 3. 화이트리스트 밖 토큰 변경 시도 -> 무시 + open_questions ===")
bw = produce([{"reference_id": "REF-002", "type": "token",
               "value": {"spacing.sp-4": "99px", "color.primary": "#1E88E5"}, "source": "x"}])
print("whitelist_violations:", bw["reference"]["whitelist_violations"])
print("open_questions에 'override 범위 밖':", oq_has(bw, "override 범위 밖"))
sp4 = next(t for t in bw["tokens"] if t["token_key"] == "spacing.sp-4")
print("spacing.sp-4 값 불변(99px 무시):", sp4["value"], "| origin:", sp4["origin"])
print("color.primary는 정상 적용:", next(t for t in bw["tokens"] if t["token_key"] == "color.light.primary")["origin"])
assert "spacing.sp-4" in bw["reference"]["whitelist_violations"]
assert sp4["value"] == "16px" and sp4["origin"] == "baseline"

print("\n=== 4. WCAG 미달 token -> 적용 + 경고 open_questions ===")
bwc = produce([{"reference_id": "REF-003", "type": "token", "value": {"color.primary": "#EEEEEE"}, "source": "x"}])
print("wcag_warnings:", bwc["reference"]["wcag_warnings"])
print("open_questions에 대비 미달 경고:", oq_has(bwc, "대비 미달"))
assert "color.primary" in bwc["reference"]["wcag_warnings"]

print("\n=== 5. image/url -> offline 분석 안 함 + open_questions ===")
bi = produce([{"reference_id": "REF-004", "type": "image", "value": {"artifact_ref": "a1", "filename": "brand.png", "mime_type": "image/png"}, "source": "upload"},
              {"reference_id": "REF-005", "type": "url", "value": {"url": "https://x"}, "source": "site"}])
print("image open_q:", oq_has(bi, "image): offline 분석 불가"))
print("url open_q:", oq_has(bi, "url): offline 분석 불가"))
print("seed는 baseline 유지(분석 안 함):", bi["seed"]["source"] == "baseline")
assert oq_has(bi, "offline 분석 불가") and bi["seed"]["source"] == "baseline"

print("\n=== 6. 토큰 traceability 실측 ===")
ok_trace = True
for t in bt["tokens"]:
    if not t.get("token_key") or "value" not in t or t.get("origin") not in ds.ALLOWED_ORIGINS:
        ok_trace = False
    if t["origin"].startswith("reference-") and not t.get("source_reference_id"):
        ok_trace = False
    if t["origin"] == "baseline" and t.get("source_reference_id"):
        ok_trace = False
n_ref = sum(1 for t in bt["tokens"] if t["origin"] == "reference-token")
n_base = sum(1 for t in bt["tokens"] if t["origin"] == "baseline")
print("모든 토큰 token_key/value/origin 보유 + 규칙 일치:", ok_trace)
print(f"reference-token 토큰: {n_ref}개 / baseline 토큰: {n_base}개 / 총 {len(bt['tokens'])}개")
assert ok_trace

print("\n=== 7. Conflict 우선순위(token>image>url>baseline) ===")
bc = produce([{"reference_id": "REF-006", "type": "token", "value": {"color.primary": "#1E88E5", "color.secondary": "#00897B"}, "source": "a"},
              {"reference_id": "REF-007", "type": "token", "value": {"color.primary": "#D81B60"}, "source": "b"}])
print("conflicts:", bc["reference"]["conflicts"])
print("color.primary 충돌 -> 임의선택 금지(baseline 유지):",
      next(t for t in bc["tokens"] if t["token_key"] == "color.light.primary")["origin"])
print("color.secondary는 충돌 없어 적용(token>baseline):",
      next(t for t in bc["tokens"] if t["token_key"] == "color.light.secondary")["origin"])
print("open_questions에 충돌 확인 요청:", oq_has(bc, "reference 충돌"))
assert "color.primary" in bc["reference"]["conflicts"]
assert next(t for t in bc["tokens"] if t["token_key"] == "color.light.primary")["origin"] == "baseline"
assert next(t for t in bc["tokens"] if t["token_key"] == "color.light.secondary")["origin"] == "reference-token"

print("\n=== 8. 게이트(Test/Review) 적용 ===")
for label, body in [("baseline", b0), ("token", bt)]:
    t = gate_test.run_test_gate("design_system", body)
    r = gate_review.run_review_gate("design_system", body)
    print(f"  {label}: TEST={t['status']} REVIEW={r['status']} (warns={len(t['warnings'])})")
    assert t["status"] in ("PASS", "WARN")
    assert r["status"] in ("PASS", "WARN")

print("\n=== Material 3 tonal 확인(Light 진한 / Dark 밝은, surface 5단계) ===")
print("light.primary:", b0["foundation"]["color"]["light"]["primary"], "| dark.primary:", b0["foundation"]["color"]["dark"]["primary"])
print("dark.surface(#121212 계열):", b0["foundation"]["color"]["dark"]["surface"])
print("surface container light 5단계:", list(b0["foundation"]["surface_tones"]["light"].keys()))
print("의미색 state_mapping:", [(s["state"], s["light"], s["dark"]) for s in b0["semantic"]["state_mapping"]])

print("\n=== 9. 의미색 4-토큰 패밀리 WCAG AA 보장(tone 조정 포함) 실측 ===")
SUBKEYS = lambda n: [n, f"on-{n}", f"{n}-container", f"on-{n}-container"]
fam_ok = True
aa_ok = True
for name in ds.SEMANTIC_FAMILY:
    sd = ds.SEM_SEEDS[name]
    for mode in ("light", "dark"):
        cm = b0["foundation"]["color"][mode]
        present = all(k in cm for k in SUBKEYS(name))
        fam_ok = fam_ok and present
        # 조정된 main tone 보고(40/80 -> 통과 tone)
        start = 40 if mode == "light" else 80
        step = -1 if mode == "light" else 1
        _, adj_t = ds._tone_meeting_contrast(sd, start, cm["surface"], step)
        # 4토큰 대비: main/surface, on-main/main, on-container/container
        c_main_surf = ds._contrast(cm[name], cm["surface"])
        c_on_main = ds._contrast(cm[f"on-{name}"], cm[name])
        c_on_cont = ds._contrast(cm[f"on-{name}-container"], cm[f"{name}-container"])
        passed = c_main_surf >= ds.WCAG_AA and c_on_main >= ds.WCAG_AA and c_on_cont >= ds.WCAG_AA
        aa_ok = aa_ok and passed
        print(f"  {mode}.{name}: main={cm[name]}(tone {start}->{adj_t}) on={cm[f'on-{name}']} cont={cm[f'{name}-container']} "
              f"| main/surf={c_main_surf:.2f} on/main={c_on_main:.2f} on/cont={c_on_cont:.2f} {'AA OK' if passed else 'AA FAIL'}")
print("  4종 × light/dark × 3색 모두 생성:", fam_ok)
print("  light·dark 전 의미색 4토큰 WCAG AA 통과:", aa_ok)
assert fam_ok, "의미색 4-토큰 패밀리 누락"
assert aa_ok, "의미색 WCAG AA 미달 잔존"
# open_questions의 WCAG 의미색 경고가 해소됐는지
sem_wcag_oq = [q for q in b0["open_questions"] if "의미색 대비 미달" in q]
print("  open_questions 잔존 '의미색 대비 미달' 경고:", sem_wcag_oq if sem_wcag_oq else "없음(해소)")
assert not sem_wcag_oq, f"WCAG 경고 미해소: {sem_wcag_oq}"

print("\n=== 10. 회귀: 기존 토큰 불변 + token_key 중복 없음 ===")
# 기존 토큰(primary/surface/outline/typography/spacing/state_mapping base)이 그대로 존재
for k in ("primary", "on-primary", "primary-container", "surface", "on-surface", "outline"):
    assert k in b0["foundation"]["color"]["light"], f"기존 토큰 누락: {k}"
keys = [t["token_key"] for t in b0["tokens"]]
dups = sorted({k for k in keys if keys.count(k) > 1})
print("  token_key 중복:", dups if dups else "없음")
assert not dups, f"token_key 중복 발생(추가만 위반): {dups}"
# state_mapping base 토큰(color.light.success 등)이 여전히 tokens에 존재(중복 없이)
for name in ds.SEMANTIC_FAMILY:
    assert f"color.light.{name}" in keys and f"color.dark.{name}" in keys, f"base 토큰 누락: {name}"
    # foundation.color base == state_mapping base (일관성)
    sm = next(s for s in b0["semantic"]["state_mapping"] if s["state"] == name)
    assert b0["foundation"]["color"]["light"][name] == sm["light"], f"{name} light base 불일치"
    assert b0["foundation"]["color"]["dark"][name] == sm["dark"], f"{name} dark base 불일치"
print("  기존 primary/surface/outline 토큰 불변 + base 일관성 OK")
print("  의미색 추가 토큰 수(success/warning/danger × 6 신규키):",
      sum(1 for k in keys if any(k.startswith(f"color.{m}.on-{n}") or k.startswith(f"color.{m}.{n}-container")
                                 for m in ("light", "dark") for n in ds.SEMANTIC_FAMILY)))
print("\nDONE")


# ── [real] real이 도출한 seed로 토큰 생성(엔진 결정적·WCAG 유지). DESIGN_SYSTEM_MODE=real일 때만 ──
if os.environ.get("DESIGN_SYSTEM_MODE") == "real":
    print("\n=== [real] strategy·discovery 맥락에서 brand seed 도출 -> 엔진 토큰 생성 ===")
    R_INTAKE = {"site_character": "인플루언서 캠페인 관리", "requirements": ["계약금", "정산", "검증"], "references": []}
    R_STRATEGY = {"positioning": "광고주·인플루언서 신뢰 기반 매칭·정산 플랫폼",
                  "options": [{"label": "신뢰·투명성 중심"}]}
    R_DISCOVERY = {"goal_interpretation": {"inferred_dimensions": [{"dimension": "정산 신뢰", "basis": "goal"}],
                                           "candidate_metrics": [], "assumptions": []},
                   "requirement_normalization": [{"id": "R-01", "statement": "국내외 정산", "origin": "explicit"}],
                   "proposed_requirements": []}
    rb = ds.produce({"intake": R_INTAKE, "strategy": R_STRATEGY, "ux": {}, "discovery": R_DISCOVERY},
                    llm=ds.real_llm)
    seed = rb["seed"]
    print("real 도출 seed.primary:", seed.get("primary"), "| decided_source:", seed.get("decided_source"))
    print("rationale:", seed.get("rationale"))
    print("baseline(#6750A4)과 다른가(real이 결정):", seed.get("primary") != ds.BASELINE_SEED)
    # 토큰 결정적·WCAG 유지: light 의미색 4토큰 AA 확인
    aa_ok = True
    for name in ds.SEMANTIC_FAMILY:
        for mode in ("light", "dark"):
            cm = rb["foundation"]["color"][mode]
            c1 = ds._contrast(cm[f"on-{name}"], cm[name])
            c2 = ds._contrast(cm[name], cm["surface"])
            aa_ok = aa_ok and c1 >= ds.WCAG_AA and c2 >= ds.WCAG_AA
    print("의미색 4토큰 WCAG AA(엔진 보장) 유지:", aa_ok)
    print("primary 토큰 생성됨:", rb["foundation"]["color"]["light"]["primary"],
          "| tokens 수:", len(rb["tokens"]))
    assert aa_ok, "real seed에서도 WCAG AA 유지돼야 함"
    print("[real] 검증 통과(엔진 결정적 토큰 + WCAG 유지)")


# ── [6][8] 13종 컴포넌트 + 색역할 + 두 테마 + 결정성 ──
from orchestrator import canonical_hash
print("\n=== 13종 컴포넌트 + 색 역할 토큰 ===")
def make(seed):
    return ds.produce({"intake": {"references": [
        {"reference_id": "r", "type": "token", "value": {"color.primary": seed}, "source": "brand"}]},
        "strategy": {}, "ux": {}})

indigo = make("#3F51B5")
coral = make("#FF5E5E")
print("component 수:", len(indigo["component"]), "(13 기대):", [c["component"] for c in indigo["component"]])
assert len(indigo["component"]) == 13
cmap = {c["component"]: c for c in indigo["component"]}
print("toggle->checked:", cmap["toggle"]["states"]["on"]["bg"] == "color.light.checked")
print("checkbox->checked:", cmap["checkbox"]["states"]["checked"]["bg"] == "color.light.checked")
print("tab->tab-bg/fg:", cmap["tab"]["states"]["active"] == {"bg": "color.light.tab-bg", "fg": "color.light.tab-fg"})
print("sidebar nav-active->menu-sel:", cmap["sidebar"]["states"]["nav-active"]["bg"] == "color.light.menu-sel")
print("profile active->active:", cmap["profile"]["states"]["active"]["dot"] == "color.light.active")
print("button 5종:", sorted(set(cmap["button"]["states"]) & {"primary", "neutral", "outline", "danger", "danger-soft"}))

print("\n=== 두 테마 역할 토큰(명세 일치) ===")
for nm, b, exp in [("인디고", indigo, {"checked": "#51C0FF", "tab-bg": "#EDF9FF", "tab-fg": "#1056BD", "neutral": "#292929"}),
                   ("코랄", coral, {"checked": "#FF5E5E", "tab-bg": "#FFEFEF", "tab-fg": "#FF5E5E", "neutral": "#292F45"})]:
    cl = b["foundation"]["color"]["light"]
    got = {k: cl[k] for k in exp}
    print(f"  {nm}: {got} | active={cl['active']} menu-sel={cl['menu-sel']}")
    assert got == exp, f"{nm} 역할 토큰 불일치"
    assert cl["active"] == "#10A957", "active는 brand 무관 #10A957"

print("\n=== 두 테마 의미색 WCAG AA(엔진 보장) ===")
for nm, b in [("인디고", indigo), ("코랄", coral)]:
    ok = all(ds._contrast(b["foundation"]["color"][m][f"on-{s}"], b["foundation"]["color"][m][s]) >= ds.WCAG_AA
             and ds._contrast(b["foundation"]["color"][m][s], b["foundation"]["color"][m]["surface"]) >= ds.WCAG_AA
             for s in ds.SEMANTIC_FAMILY for m in ("light", "dark"))
    print(f"  {nm} 의미색 4토큰 AA:", ok)
    assert ok

print("\n=== [8] 토큰 엔진 결정성(같은 seed -> 같은 토큰) ===")
h1, h2 = canonical_hash(make("#3F51B5")), canonical_hash(make("#3F51B5"))
print("  동일 seed 재실행 canonical_hash 동일:", h1 == h2)
assert h1 == h2, "결정성 위반"
print("\n[6][8] 검증 통과")
