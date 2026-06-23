# 하네스 오케스트레이터 정책 v1.1

v1을 대체한다. 추가 검토 결과를 반영해 MVP 기준 안정화 버전으로 확정한다. 스키마 v2(3층, 버전 핀) 위에서 도는 실행 정책이며 DDL의 근거가 된다.

## 0. v1.1 변경 요약

| 번호 | 변경 | 근거 |
|---|---|---|
| 1 | stale을 confirmed 집합에서 제외되는 별도 상태로 명시 | DONE이 stale 입력을 숨기는 사각지대 제거 |
| 2 | gate와 on_upstream_change를 독립 축으로 분리 | 최초 승인 정책과 재생성 정책의 충돌 제거 |
| 3 | gate=auto는 결정적 노드에만 허용 | 자동 연쇄의 무분별 확산 차단 |
| 4 | stale 전파 트리거를 confirmed 전이 + version 증가 동시 충족으로 한정 | 미승인 중간 작업이 하위를 흔드는 것 차단 |
| 5 | 동일 내용 재승인은 version 증가·전파 없음 | 무의미한 캐스케이드 차단 |
| 6 | version 증가 조건과 책임 계층 명시 | 데이터 동일한데 버전만 오르거나 그 반대 방지 |
| 7 | Run 성공 시 canonical 비교 기반 갱신 규칙 명시 | 불필요한 stale 전파·연쇄 재실행 방지 |
| 8 | 재실행 성공 시 derived_from 재핀과 stale 해제는 version 증가와 무관하게 항상 수행 | stuck stale 버그 방지 |

## 1. Workflow 정의 상태 전이 규칙

Workflow 정의는 템플릿이며 불변이다. 수정은 새 버전을 만든다.

| 상태 | 의미 |
|---|---|
| draft | 편집 중. 실행 불가 |
| active | 현재 버전. 신규 바인딩이 사용 |
| deprecated | 상위 버전 게시로 밀려남. 과거 핀 참조용 영구 보존 |

| 전이 | 트리거 | 조건 |
|---|---|---|
| draft → active | 사람(게시) | key당 active 1개. 기존 active는 deprecated |
| active → deprecated | 시스템 | 같은 key 새 버전이 active가 될 때 |

규칙

1. active·deprecated 정의는 수정·삭제 금지. 모든 버전 영구 보존.
2. Run은 workflow_version을 핀한다. 과거 Run의 DAG 정의를 항상 복원한다.
3. 프로젝트는 시작 시 workflow_key + version에 바인딩된다. 진행 중 자동 전환 없음. 마이그레이션만 명시적.

## 2. 오케스트레이터 결정 알고리즘

### 2.1 읽는 입력

1. 프로젝트 바인딩 Workflow 정의
2. 프로젝트의 모든 Spec Record(type, status, version, derived_from)
3. 프로젝트의 모든 Run(node_id, run_status, input_refs)

전제: Append-Only 미도입. (프로젝트, type)당 Spec Record는 1행이며 mutate된다.

### 2.2 Spec Record 상태 모델

| 상태 | 의미 | confirmed 집합 포함 |
|---|---|---|
| draft | 검토 전 | 아니오 |
| in_review | 사람 게이트 대기 | 아니오 |
| confirmed | 승인됨. 하위 진행 가능 | 예 |
| rejected | 반려됨 | 아니오 |
| stale | 입력이 낡음 | 아니오 |

핵심: stale은 confirmed에서 이탈한 별도 상태다. confirmed 집합에 포함하지 않는다. 따라서 의존성 평가에서 dep가 stale이면 confirmed 아님으로 처리된다.

상태 전이표

| 전이 | 트리거 | 조건 |
|---|---|---|
| (없음) → draft | 시스템 | 노드 첫 실행 준비 |
| draft → in_review | Run 성공 | gate=human |
| draft → confirmed | Run 성공 | gate=auto |
| in_review → confirmed | 사람 | 승인 |
| in_review → rejected | 사람 | 반려 |
| rejected → in_review | 사람 | 수정 입력 후 재실행 |
| confirmed → stale | 시스템(영향도 전파) | 상위 confirmed + version 증가 |
| in_review → stale | 시스템(영향도 전파) | 사람 판단 전 상위 변경 |
| stale → in_review | Run 성공 | 재실행, gate=human, 산출 변경됨 |
| stale → confirmed | Run 성공 | 재실행, gate=auto. 또는 gate=human이며 산출 동일(4.5 참조) |

### 2.3 노드 파생 상태

각 노드 N에 대해 저장하지 않고 파생한다.

1. dep 해소: N.depends_on의 각 노드 산출 타입의 현재 레코드.
2. dep 유효: 모든 dep가 confirmed(stale·in_review·rejected 아님).
3. 입력 시그니처: dep 레코드들의 {pk, version} 집합(dep 유효일 때만).

| 파생 상태 | 조건 |
|---|---|
| BLOCKED | dep 중 confirmed 아님 존재(stale 포함) |
| RUNNING | N에 진행 중(queued/running) Run 존재 |
| NEEDS_REVIEW | N 산출 레코드가 in_review |
| STALE | N 산출 레코드가 stale |
| REJECTED | N 산출 레코드가 rejected |
| DONE | N 산출 confirmed 이고, derived_from == 현재 입력 시그니처 이며, 입력 레코드 중 stale 없음 |
| READY | dep 모두 confirmed, 유효 산출 없음, 진행 중 Run 없음 |

DONE 강화: 시그니처 일치만으로 DONE을 주지 않는다. 입력이 모두 confirmed이고 stale이 없어야 DONE이다.

### 2.4 결정 루프(매 tick)

1. 모든 노드 파생 상태 계산.
2. READY 노드에 Run 생성(3절). input_refs = 입력 시그니처, workflow_version 핀.
3. RUNNING·NEEDS_REVIEW·BLOCKED는 생성 없음.
4. STALE 노드는 영향도 전파 규칙(4절)에 따라 처리.
5. REJECTED는 자동 재실행 금지. 사람 수정 입력 대기.

### 2.5 결정성·동시성

1. 멱등: 동일 상태에서 동일 결정.
2. 중복 Run 방지: (project_pk, node_id, input_signature_hash) 유니크 + 트랜잭션.
3. 단일 진입: 콘텐츠 상태 전이와 Run 생성은 정의된 경로로만.

## 3. Run 생성·종료 규칙

### 3.1 생성 전제

1. 노드가 READY 이거나, STALE 이며 재실행 정책이 재생성을 지시.
2. 진행 중 Run 없음.
3. 입력 시그니처가 confirmed 레코드로 해소됨.

### 3.2 생성 값

1. run_status=queued, attempt=1(재시도면 직전+1).
2. input_refs=입력 시그니처(버전 핀), workflow_version=바인딩 버전 핀.
3. output_record_pk=null.
4. 멱등 키=(project_pk, node_id, input_signature_hash).

### 3.3 종료 전이

| 전이 | 결과 |
|---|---|
| queued → running | 워커 집음 |
| running → succeeded | 3.6 갱신 규칙 적용 |
| running → failed | error 기록. attempt<max면 새 Run 행으로 재시도. max 도달 시 종료 |
| running → cancelled | 입력 무효화 또는 수동 취소 |

### 3.4 재시도·감사

1. 각 시도는 별도 Run 행. 실패 이력 보존.
2. max_attempts는 Workflow 또는 노드 설정.

### 3.5 입력 무효화

1. 진행 중 Run의 input_refs가 현재 confirmed 시그니처와 불일치하면 cancelled(reason=input_superseded).
2. in_review 산출은 상위 변경 시 stale로 전이(낡은 산출 검토 방지).
3. 이후 4절 재실행 정책에 따라 새 Run 생성.

### 3.6 Run 성공 시 Record 갱신 규칙

저장 계층이 canonical serialization 기반으로 판정한다. 오케스트레이터의 책임이 아니다.

1. canonical body 비교: 새 산출 body와 현재 Record body를 정규화 직렬화로 비교.
2. 변경된 경우: version+1, body 갱신, derived_from=input_refs, status는 gate에 따라(human→in_review, auto→confirmed). changed=true 반환.
3. 동일한 경우: version 유지, body 유지, derived_from=input_refs로 재핀, stale 해제. changed=false 반환.
4. 비교 대상은 body만. pk·version·status·updated_at·origin·derived_from·provenance·public_key는 비교에서 제외.

핵심(stuck stale 방지): 동일하여 version을 안 올려도 derived_from 재핀과 stale 해제는 항상 수행한다. version 증가는 하위 전파 트리거만 담당하고, 핀 갱신·stale 해제는 재실행 성공의 기본 동작이다.

### 3.7 version 증가 조건

1. 의미 있는 변경(semantic change) 시에만 version+1.
2. 단순 승인, 메타데이터 수정, 재저장은 version 유지.
3. version 증가 판정과 적용은 Record 저장 계층의 책임이며 canonical body 비교로 결정한다.

## 4. 변경 영향도 전파 규칙 (Impact Propagation Rule)

### 4.1 노드 정책 축 (독립 2축)

| 축 | 의미 |
|---|---|
| gate | 산출 승인 정책. 최초·재생성 모두 동일 적용. human 또는 auto |
| on_upstream_change | 재생성 트리거 정책. auto_rerun / manual_rerun / hold |

두 축은 독립이다. 조합표

| on_upstream_change | gate | 결과 |
|---|---|---|
| auto_rerun | auto | 재실행 후 confirmed |
| auto_rerun | human | 재실행 후 in_review(산출 변경 시). 동일 시 4.5 |
| manual_rerun | 무관 | stale 유지, 사람 트리거 대기 |
| hold | 무관 | stale 유지, 명시적 결정 |

제약: gate=auto는 사람 판단이 불필요한 결정적 노드에만 부여한다. strategy처럼 사람 가치가 들어가는 노드는 gate=human을 강제한다. gate=auto + auto_rerun 구간은 사람 개입 없이 confirmed가 되어 자동 연쇄가 발생하므로, 이 조합은 의도된 결정적 노드에만 허용한다.

### 4.2 전파 트리거 (엄격)

전파는 다음 두 조건이 동시에 충족될 때만 발생한다.

1. 상위 레코드가 confirmed로 전이.
2. 그 전이로 confirmed version 번호가 실제 상승.

version 증가 없는 단순 재승인, draft·in_review의 미승인 중간 수정은 전파를 발생시키지 않는다.

### 4.3 전파 알고리즘

상위 U가 4.2를 충족하면

1. U의 직접 하위(U를 depends_on에 둔 노드 산출 레코드)를 찾는다.
2. 각 하위 D의 derived_from이 핀한 U 버전이 새 버전보다 작으면 D를 stale로 전이(confirmed·in_review 모두 대상).
3. D의 on_upstream_change에 따라 처리(auto_rerun / manual_rerun / hold).

### 4.4 캐스케이드

1. 한 번에 한 홉만 전파. U 변경은 직접 하위만 stale.
2. 하위 D의 하위 E는 즉시 stale 아님. D가 재실행되어 새 버전으로 re-confirmed될 때 비로소 stale.
3. 변경은 홉마다 승인 게이트(또는 gate=auto의 자동 승인)를 통과하며 흐른다.

### 4.5 동일 산출 재실행 처리

gate=human 노드를 auto_rerun으로 재실행했는데 산출이 동일한 경우.

1. 채택 정책: 재검토 생략. stale → confirmed로 자동 정리. version 미증가. 하위 전파 없음.
2. 근거: 그 내용은 사람이 이미 승인했고, 입력 변화가 결과에 영향이 없다.
3. 이 결정은 되돌릴 수 있다. 항상 재검토를 원하면 동일 시에도 in_review로 보내도록 변경한다.

### 4.6 블라스트 반경

1. 저장되는 stale 전이는 버전 불일치가 확정된 직접 하위에만.
2. 전이적 하위 전체는 그래프에서 파생 계산해 사람에게 미리보기로 제공(영향도 분석).

### 4.7 예시: strategy 재확정 v2 → v3

| 단계 | 처리 |
|---|---|
| 1 | strategy 직접 하위 탐색. policy가 strategy를 depends_on |
| 2 | policy.derived_from은 strategy@v2 핀. v2<v3 불일치 |
| 3 | policy: confirmed → stale(영향도 전파, 시스템) |
| 4 | policy on_upstream_change 적용. auto_rerun이면 재실행, 입력 strategy@v3 |
| 5a | 산출 변경 시 policy → in_review(gate=human). 사람 승인 시 confirmed, version+1 |
| 5b | 산출 동일 시 재검토 생략. policy → confirmed, version 유지, derived_from은 v3로 재핀 |
| 6 | 5a로 version 상승한 경우에만 features(policy 이전 버전 핀)가 stale로 전이. 5b면 전파 없음 |

세 갈래 답

1. policy는 stale로 전이되는가: 그렇다. 항상.
2. 자동 재생성되는가: on_upstream_change=auto_rerun일 때만. 산출은 gate에 따름.
3. 사람 승인 대기로 들어가는가: gate=human이고 산출이 변경된 경우. 동일하면 4.5로 생략.

요지: 세 가지는 택일이 아니라 stale → (재실행) → (gate) → confirmed 순서의 단계다. 사람 게이트는 결정적 노드(gate=auto)를 제외하고 우회되지 않는다.

## 5. 다음 단계

DDL 설계(records, runs, workflows, dependencies, 유니크·인덱스 제약). 본 정책의 각 규칙을 제약으로 강제한다.
