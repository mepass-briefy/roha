# ROHA Workbench (로컬 UI)

조회·실행 범위의 Workbench UI. React + Vite. 기존 FastAPI(server/app.py)를 호출만 한다(편집 화면은 Working Layer 결정 후 2단계).

## 사전 준비

1. Python 의존: `pip install -r requirements.txt` (루트)
2. `.env`(루트)에 `DATABASE_URL`(Neon), `ANTHROPIC_API_KEY`(real 모드 시). 커밋 금지.
3. DB 스키마: `python db/setup_db.py`

## 로컬 실행 (API + UI 동시, 같은 컴퓨터)

터미널 1 — API 서버(8000):
```
# mock(기본) 또는 real 스위치(환경변수)
#   STRATEGY_MODE=real FEATURES_MODE=real DISCOVERY_MODE=real
STORE=db python -m uvicorn server.app:app --port 8000
```

터미널 2 — UI(5173):
```
cd web
npm install
npm run dev
```

브라우저에서 http://localhost:5173 열기. UI는 Vite dev 프록시로 `/projects*`를 8000으로 보내므로 CORS 설정이 필요 없다(API 무수정).

## 흐름

입력(목표 + 맥락 Context + 요구사항 + target_platform) → 프로젝트 생성(POST /projects) → "다음 단계 실행"(POST /run) → Discovery 산출 검토(GET /records) → "확정"(POST /approve, 첫 게이트) → 다음 단계 실행(strategy …) → 산출물 보기.

- 게이트 대기 시 "확정" 버튼, 아니면 "다음 단계 실행" 버튼.
- 외부 식별자는 public_key만 사용(내부 PK 비노출).
- 편집(기능 채택·추가)은 이번 범위 제외.
