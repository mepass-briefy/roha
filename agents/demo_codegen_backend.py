"""
codegen_backend 검증.
[5] 명세 충실성: 생성 엔티티·엔드포인트가 명세와 1:1, 발명 0. 식별자 3종·public_key 규칙 코드 반영.
[7] 분리성: 아키텍처 층(build_architecture)에 언어 전용 로직 0. 언어 투영 층에만 Python.
작동([6])은 별도 스모크(README 참조). 여기서는 결정적 검증만(LLM 무관).
"""
import sys, json, re, inspect, tempfile
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(BASE / "agents"))
import codegen_backend as cg

SPEC = json.load(open(BASE / "workspaces" / "futsal-socialmatch" / "backend_spec.json", encoding="utf-8"))

print("=== [5] 명세 충실성(발명 0) ===")
arch = cg.build_architecture(SPEC)
spec_entities = [e["name"] for e in SPEC["entities"]]
spec_eps = [(e["method"], e["path"]) for e in SPEC["api_spec"]["endpoints"]]
gen_entities = [e["name"] for e in arch["entities"]]
gen_routes = [(r["method"], r["path"]) for r in arch["routes"]]
print(" 엔티티 명세==생성:", spec_entities == gen_entities, gen_entities)
print(" 엔드포인트 명세==생성:", spec_eps == gen_routes, len(gen_routes), "개")
assert spec_entities == gen_entities, "엔티티 발명/누락"
assert spec_eps == gen_routes, "엔드포인트 발명/누락"
# 식별자 3종이 모든 엔티티 컬럼에 존재 + pk 내부역할
for e in arch["entities"]:
    roles = {c["role"] for c in e["columns"]}
    assert {"internal_pk", "business_key", "public_key"} <= roles, f"{e['name']} 식별자 3종 누락"
# 명세에 없는 도메인 필드 0(엔티티별 fields 그대로)
for se, ge in zip(SPEC["entities"], arch["entities"]):
    spec_fields = {f["name"] for f in se.get("fields", [])} - {"pk", "business_key", "public_key"}
    gen_domain = {c["name"] for c in ge["columns"] if c["role"] == "domain"}
    assert gen_domain == spec_fields, f"{se['name']} 도메인 필드 불일치(발명/누락): {gen_domain ^ spec_fields}"
print(" 식별자 3종 전 엔티티 존재 + 도메인 필드 명세 1:1(발명 0): PASS")

print("\n=== [7] 분리성: 아키텍처 층에 언어 전용 로직 0 ===")
arch_src = inspect.getsource(cg.build_architecture) + inspect.getsource(cg._match_entity_table) + inspect.getsource(cg._logical_type)
# 프레임워크 전용 토큰만(대소문자 구분). IR의 'column'/'table' 키는 언어무관 데이터모델 어휘라 제외.
lang_tokens = re.findall(r"fastapi|sqlalchemy|pydantic|uvicorn|FastAPI|Column\(|BigInteger|JSONResponse|from sqlalchemy|import models", arch_src)
print(" 아키텍처 층 프레임워크 토큰:", lang_tokens or "없음")
assert not lang_tokens, "아키텍처 층에 Python/프레임워크 로직 누출"
# 투영은 LANG_PROJECTORS로 교체 가능(언어=변수)
print(" 지원 언어 투영:", list(cg.LANG_PROJECTORS))
assert "python" in cg.LANG_PROJECTORS
# 외부 경로 규칙: item/update/delete 라우트는 public_key 파라미터만(내부 pk 경로 0)
for r in arch["routes"]:
    if "{" in r["path"]:
        params = re.findall(r"\{([^}]+)\}", r["path"])
        assert params == ["public_key"], f"외부 경로에 public_key 외 식별자: {r['path']}"
print(" 외부 경로는 public_key만(내부 pk 노출 0): PASS")

print("\n=== 생성 산출(임시 디렉터리) ===")
out = tempfile.mkdtemp()
res = cg.generate(SPEC, out)
print(" 언어:", res["language"], "| 파일:", [Path(f).name for f in res["files"]])
# models.py에 pk 내부·public_key 외부 규칙 코드 존재
models_src = (Path(out) / "models.py").read_text(encoding="utf-8")
assert "primary_key=True" in models_src and "외부 미노출" in models_src
assert "public_key" in models_src and "외부 노출" in models_src
print(" models.py 식별자 3종 규칙 반영: PASS")

print("\nDONE")
