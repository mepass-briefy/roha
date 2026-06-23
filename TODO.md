# TODO (현재 구조 내 처리 가능)

## 실행 환경

1. T0. Windows 기본 코덱(cp949) 환경에서 `Path.read_text()`(인코딩 미지정)가 UTF-8 한국어 파일에서 UnicodeDecodeError를 낸다. 해당 지점: orchestrator.py(보호 파일, 저장 파일 읽기), agents/strategy.py(agent_strategy.md 읽기), agents/demo_strategy.py·demo.py(워크플로 JSON 읽기). 현재 회피: `PYTHONUTF8=1` 환경변수로 실행(소스 미수정). 검증 완료: 이 모드에서 demo.py·demo_ux.py exit 0. 근본 수정(read_text(encoding="utf-8"))은 orchestrator.py 버그 수정 범위지만 보호 파일이라 사용자 승인 후 진행.

## Strategy Agent

1. T1. offline 모드는 web 없음. real 모드(web_search 가능 Claude 서브에이전트)로 llm 교체 시 competitors.axes(기능/수익모델/온보딩/불편지점)와 market_gaps를 실데이터로 채운다. 교체 지점: strategy.make_producer(llm=real_llm).
2. T2. offline market_gaps는 추론 placeholder(provenance=inference로 정직 표기됨). real 모드에서 fact 근거로 대체.
3. T3. unique_angles는 intake가 제공해야 wow_points 생성. intake 단계에서 사람 각도 입력을 받는 경로 정비.
