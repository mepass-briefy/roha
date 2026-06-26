# futsal-socialmatch backend (생성 코드)

ROHA codegen 에이전트(`agents/codegen_backend.py`)가 검증된 backend 명세
(`../backend_spec.json`)를 충실 번역한 Python 백엔드. 손으로 편집하지 말 것 — 명세에서 재생성된다.

## 스택 (언어 투영 = Python)
1. FastAPI + SQLAlchemy + SQLite(프로토타입). 운영 DB는 `DATABASE_URL` 환경변수로 교체.
2. 식별자 3종: `pk`(내부 bigint, 외부 비노출) · `business_key`(운영 ROHA 순번) · `public_key`(외부 노출, URL/응답).
3. 외부 경로는 `public_key`만. FK 참조는 요청에서 `<x>_public_key`로 받아 내부 `<x>_pk`로 변환.

## 재생성
```
python agents/codegen_backend.py workspaces/futsal-socialmatch/backend_spec.json workspaces/futsal-socialmatch/backend
```

## 실행
```
cd workspaces/futsal-socialmatch/backend
pip install -r requirements.txt
uvicorn main:app --port 8011
```
기동 시 SQLite 스키마 자동 생성(application·reservation·settlement). 외부 응답은
`{"success":true,"data":...}` / `{"success":false,"error":{code,message}}` 고정.

## 작동 확인(실측됨)
1. `POST /api/v1/applications` → 201, `business_key=ROHA0001` + `public_key` 발급, `pk` 외부 비노출.
2. `GET /api/v1/applications/{public_key}` → 200.
3. `POST /api/v1/reservations` (`application_public_key` 전달) → 201, 내부 `application_pk`로 변환·datetime 강제 변환.
4. 잘못된 FK/필수 누락 → 422 검증 거부.

## 충실 번역 / 발명 0
엔티티 3종·엔드포인트 9개는 명세와 1:1. 명세에 없는 엔티티·엔드포인트·필드는 생성하지 않음.
규칙수준 기본값만 코드 관용으로 채움(타입 매핑, SQLite 방언 pk variant, public_key→pk 변환).

## 알려진 한계(명세/codegen BACKLOG)
1. 인증 방식: 명세는 `security_ref`(통제명)만 제공 → 핸들러에 인증 미들웨어 자리 없음(미구현). 명세 보강 필요.
2. enum 값 목록: 명세는 type=enum만, 허용값 목록 없음 → `String`으로 매핑(CHECK 제약 미생성).
3. 업데이트(PATCH) 본문 반영·페이지네이션 커서 의미는 단순 구현(프로토타입 수준).
