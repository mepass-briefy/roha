# TODO (현재 구조 내 처리 가능)

## 실행 환경

1. T0. [완료] Windows 기본 코덱(cp949) 환경에서 텍스트 I/O(인코딩 미지정)가 UTF-8 한국어 파일에서 UnicodeDecodeError를 냈다. 수정(사용자 승인, 버그 수정): orchestrator.py의 read_text·write_text·events open("a")에 encoding="utf-8" 추가, agents/strategy.py의 agent_strategy.md read_text에 encoding="utf-8" 추가(agents/ux.py는 처음부터 utf-8). 검증: PYTHONUTF8 없이 demo.py·demo_ux.py 둘 다 exit 0 실측 확인.

## Strategy Agent

1. T1. offline 모드는 web 없음. real 모드(web_search 가능 Claude 서브에이전트)로 llm 교체 시 competitors.axes(기능/수익모델/온보딩/불편지점)와 market_gaps를 실데이터로 채운다. 교체 지점: strategy.make_producer(llm=real_llm).
2. T2. offline market_gaps는 추론 placeholder(provenance=inference로 정직 표기됨). real 모드에서 fact 근거로 대체.
3. T3. unique_angles는 intake가 제공해야 wow_points 생성. intake 단계에서 사람 각도 입력을 받는 경로 정비.


## Discovery 사람 수정(human edit) — 알려진 한계
- 서버 PUT /projects/{pk}/records/discovery는 사람 수정본을 새 append-only 버전으로 저장(provenance.human_edited). orchestrator·에이전트 무수정.
- 한계: 확정(confirmed) 상태의 Discovery를 수정하면 새 버전은 기록되나 하위 노드 stale 전파(캐스케이드)는 일어나지 않음(전파는 orchestrator 책임, 본 경로는 우회). 검토(in_review) 단계 편집을 가정. confirmed 편집 후 재생성/전파가 필요하면 orchestrator 경유 설계 필요 -> BACKLOG 후보.
