"""
Design System Agent(재정의) 검증.
Material 3 tonal + Reference Contract + Traceability + Conflict/Whitelist/WCAG + 게이트.
오프라인 모드(결정적). orchestrator·다른 에이전트·게이트는 수정하지 않는다.
"""
import sys, json
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
print("\nDONE")
