# TODO (현재 구조 내 처리 가능)

## Strategy Agent

1. T1. offline 모드는 web 없음. real 모드(web_search 가능 Claude 서브에이전트)로 llm 교체 시 competitors.axes(기능/수익모델/온보딩/불편지점)와 market_gaps를 실데이터로 채운다. 교체 지점: strategy.make_producer(llm=real_llm).
2. T2. offline market_gaps는 추론 placeholder(provenance=inference로 정직 표기됨). real 모드에서 fact 근거로 대체.
3. T3. unique_angles는 intake가 제공해야 wow_points 생성. intake 단계에서 사람 각도 입력을 받는 경로 정비.
