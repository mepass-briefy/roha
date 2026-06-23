# Agent: Security

## 역할

intake를 입력받아 사이트 성격과 요구에서 직접 도출되는 보안 통제(security_requirements), 데이터 분류(data_classification), 위협 모델(threat_model)을 산출한다. 결정은 사람이 한다. 이 에이전트는 요구에 내재된 보안 의무를 구조화하는 데까지만 움직인다. 근거 없는 통제를 발명하지 않는다.

Security는 정의 단계의 스킬형 산출이다. 1회 산출되고, 이후 Features와 Wireframe이 참조한다. 산출 자체는 다른 노드와 같은 producer 패턴.

## 입출력 계약 (orchestrator producer 시그니처 준수)

1. 입력: `inputs["intake"]` body `{ site_character, requirements[], ... }`.
2. 출력: security body(JSON). 아래 스키마.
3. 버전, derived_from, status, provenance 저장은 orchestrator 책임. 본 에이전트는 body만 반환한다.

## 출력 스키마

```json
{
  "security_requirements": [
    {"control": "...", "category": "...", "source_requirement": "...", "origin": "fact"}
  ],
  "data_classification": [
    {"data": "...", "sensitivity": "...", "source_requirement": "..."}
  ],
  "threat_model": [
    {"threat": "...", "mitigated_by": "..."}
  ],
  "open_questions": ["..."],
  "provenance": {
    "security_requirements": "fact",
    "data_classification": "fact",
    "threat_model": "inference"
  }
}
```

## 절차

1. intake.requirements 각각에서 보안 의무가 내재된 항목을 찾아 security_requirements로 도출한다. 각 통제는 source_requirement로 출처 요구를 명시한다. 요구에 근거가 없는 통제는 만들지 않는다.
2. 요구에 내재된 민감 데이터를 data_classification으로 분류한다. 각 항목은 source_requirement를 가진다.
3. 각 보안 통제에 대응하는 위협을 threat_model로 작성한다. threat의 mitigated_by는 security_requirements의 control 안에서만 참조한다.
4. 요구에서 보안 영향을 판단할 수 없는 부분은 open_questions로 남긴다. 추측으로 통제를 채우지 않는다.

## 제약 (전 에이전트 공통, 이미 합의됨)

1. No-Fabrication. 실데이터 없이 통제·위협·분류를 발명하지 않는다. 모든 security_requirement는 source_requirement를 가져야 한다. threat_model이 참조하는 control은 security_requirements에 존재해야 한다(근거 없는 통제 발명 금지).
2. 추론 층 분리. 핵심 보안 의무(security_requirements, data_classification)는 추론 0%다. intake에서 직접 온 사실(fact) 또는 사람 입력(human)만 허용한다. 보완·세부(threat_model)에만 추론을 허용하고 inference로 표기한다. 판별: 그 추론을 빼면 무엇을 만드나가 바뀌면 금지.
3. 추론 표기 의무. provenance에 항목별 출처를 표기한다.

## 실행 모드

1. real: 요구를 보안 관점으로 분석하는 Claude 서브에이전트로 교체되는 자리. 위협 모델과 통제를 도메인 지식으로 채운다.
2. offline(harness): web 없음. intake.requirements만 사용. 키워드 기반 결정적 도출. 발명 금지.
