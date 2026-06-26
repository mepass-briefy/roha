# Forge Design System v1.0

테마 4종(Blue, Indigo, Orange, Green)과 라이트/다크 모드를 지원하는 토큰 기반 디자인 시스템. 폰트는 Pretendard 단일 패밀리, 간격은 4px 그리드(컴포넌트 내부, Slack 규칙)와 Notion 여백 규칙(레이아웃)을 영역별로 분리해 적용한다.

## 1. 기본 원칙

1. 테마는 50부터 950까지 11단계 스케일로 구성하고, Primary는 라이트 600 / 다크 500을 사용한다.
2. 컴포넌트 내부 간격은 Slack식 4px 그리드로 촘촘하게, 페이지/레이아웃 여백은 Notion식으로 넉넉하게 적용한다.
3. 다크모드는 사이드바를 테마 정체성(테마 최암색보다 한 단계 어두운 톤)으로, 콘텐츠 영역을 채도 낮춘 중립 다크로 통일해 대비를 만든다.
4. 모든 컴포넌트는 활성 테마 토큰을 참조하며, 내부 패딩은 4의 배수만 사용한다.

## 2. 색상

### 2.1 테마 스케일 (11단계)

| Step | Blue | Indigo | Orange | Green |
|---|---|---|---|---|
| 50 | #EDF9FF | #F7F3FF | #FFF7ED | #EFFEF5 |
| 100 | #D8F0FF | #EFE9FE | #FFEDD4 | #DBFDEA |
| 200 | #B9E6FF | #E2D6FE | #FFD7A9 | #B9F9D5 |
| 300 | #89D7FF | #CBB5FD | #FFBA72 | #82F3B5 |
| 400 | #51C0FF | #AD8BFA | #FE9239 | #44E48C |
| 500 | #29A1FF | #8B5CF6 | #FD7212 | #1DD772 |
| 600 | #1886FE | #713AED | #ED5709 | #10A957 |
| 700 | #0B6AEA | #5E28D9 | #C54009 | #118446 |
| 800 | #1056BD | #4E21B6 | #9C3310 | #13683B |
| 900 | #144A94 | #421D95 | #7E2C10 | #115632 |
| 950 | #112E5A | #230A5E | #441306 | #03301A |

### 2.2 중립 / 표면 (Light)

| 토큰 | 역할 | Hex |
|---|---|---|
| bg | 페이지 배경 | #FFFFFF |
| sidebar | 중립 표면 | #F7F8FA |
| surface | 카드·인풋 표면 | #F6F7F9 |
| elevated | 부상 표면 | #FFFFFF |
| border | 구분선·테두리 | #E6E8EC |
| hover | 호버 배경 | #F0F1F4 |
| text | 본문 텍스트 | #16191F |
| dim | 보조 텍스트 | #5B616E |
| faint | 흐린 텍스트 | #9AA0AC |
| sidebar-text | 사이드바 텍스트 | #16191F |
| sidebar-dim | 사이드바 보조 | #6B7280 |

### 2.3 중립 / 표면 (Dark)

콘텐츠 영역은 채도 낮은 중립 다크(#282828 계열)로 통일하고, 사이드바만 테마별 최암색으로 정체성을 유지한다.

| 토큰 | 역할 | Hex |
|---|---|---|
| bg | 콘텐츠 배경(틴티드 블랙) | #1A1A1C |
| surface | 카드·인풋 표면 | #222224 |
| elevated | 부상 표면 | #282828 |
| border | 구분선·테두리 | #343438 |
| hover | 호버 배경 | #282828 |
| text | 본문 텍스트 | #ECECEE |
| dim | 보조 텍스트 | #9B9BA2 |
| faint | 흐린 텍스트 | #6B6B72 |
| sidebar-text | 사이드바 텍스트 | #F2F2F4 |
| sidebar-dim | 사이드바 보조 | #AAAAB2 |

사이드바 색상(테마 950보다 한 단계 어두운 톤):

| 테마 | Sidebar Hex |
|---|---|
| Blue | #0A1C38 |
| Indigo | #15053A |
| Orange | #2A0B03 |
| Green | #021E0F |

### 2.4 시맨틱 토큰

`{ramp}`는 활성 테마 스케일을 의미한다.

| 토큰 | Light | Dark |
|---|---|---|
| accent | ramp 600 | ramp 500 |
| accent-hover | ramp 700 | ramp 400 |
| accent-soft | ramp 50 | rgba(ramp 500, 0.16) |
| accent-soft-text | ramp 700 | ramp 300 |
| on-accent | #FFFFFF | #FFFFFF |
| ring | rgba(ramp 500, 0.40) | rgba(ramp 400, 0.40) |
| success | #10A957 | #1DD772 |
| danger | #E5484D | #FF6166 |
| warning | #ED5709 | #FE9239 |
| info | accent | accent |

## 3. 타이포그래피

Pretendard 단일 패밀리. 본문 기본 14px, 여유 16px. 제목은 음수 자간으로 또렷하게 처리한다.

| 이름 | 크기 / 굵기 | 자간 | 행간 |
|---|---|---|---|
| Display | 40 / 800 | -0.03em | 1.1 |
| Heading 1 | 32 / 700 | -0.02em | 기본 |
| Heading 2 | 24 / 700 | -0.02em | 기본 |
| Heading 3 | 20 / 600 | -0.01em | 기본 |
| Body L | 16 / 400 | 기본 | 1.6 |
| Body | 14 / 400 | 기본 | 1.55 |
| Caption | 12 / 500 | 기본 | dim 색상 |

## 4. 간격 · 모서리

### 4.1 Spacing Scale (4px 그리드)

| 토큰 | px |
|---|---|
| space-1 | 4px |
| space-2 | 8px |
| space-3 | 12px |
| space-4 | 16px |
| space-5 | 20px |
| space-6 | 24px |
| space-8 | 32px |
| space-10 | 40px |
| space-12 | 48px |
| space-16 | 64px |

### 4.2 Radius

| 이름 | px |
|---|---|
| sm | 4px |
| md | 6px |
| lg | 8px |
| xl | 10px |
| 2xl | 14px |
| full | 9999px |

## 5. 다크모드 지침

1. 사이드바는 테마 최암색(950)보다 한 단계 어두운 톤으로 테마 정체성을 유지한다.
2. 콘텐츠 영역은 채도를 낮춘 중립 다크(#282828 계열)로 통일한다.
3. 컬러풀한 사이드바와 차분한 콘텐츠의 대비가 핵심이다.
4. 라이트 모드는 흰 배경에 중립 표면을 사용한다.

## 6. 컴포넌트 (13종)

모든 컴포넌트는 활성 테마 토큰을 사용하고 내부 패딩은 4px 그리드를 따른다.

### 6.1 버튼

1. 구성: variant × size × state.
2. variant: Primary, Secondary, Outline, Ghost, Soft, Danger.
3. size 높이: sm 28, md 36, lg 44 (4px 그리드).
4. state: Default, Hover, Focus, Disabled.
5. 패딩: 8 / 16.

### 6.2 입력 폼

1. 종류: input, textarea, select, checkbox, radio, toggle.
2. 인풋 높이 40, 내부 패딩 12.
3. 상태: 기본, 도움말, 포커스, 에러(필수 항목 표시), 비활성.

### 6.3 뱃지 · 태그 · 칩

1. 용도: 상태 표시, 분류 태그, 제거 가능한 칩.
2. 스타일: Solid, Soft, Outline, Neutral.
3. 상태 예시: OK(success), KO(danger), 검토 중(warning), 진행률.

### 6.4 카드 · 테이블

1. 카드 패딩 16~20.
2. 테이블 행 높이 약 52, 셀 패딩 16.
3. 테이블 구성: 헤더 액션(New, Export), 컬럼(USER, LICENSE, POSITION, REVENUE), 페이지네이션.

### 6.5 모달 · 토스트

1. 모달 패딩 24.
2. 토스트 패딩 12 / 16.
3. 토스트 유형: 성공, 실패, 정보, 진행.

### 6.6 소셜 로그인

1. 브랜드 컬러는 고정한다.
2. 테두리와 표면은 활성 테마를 따른다.
3. 대상: Facebook, Google, Apple, X.

## 7. 밀도 규칙 (Notion + Slack)

컴포넌트 내부는 Slack식 4px 그리드로 촘촘하게, 페이지/레이아웃 여백은 Notion식으로 넉넉하게. 두 규칙을 영역별로 분리해 적용한다.

### 7.1 Slack — 컴포넌트 내부 (촘촘, 기능 밀도 우선)

| 항목 | 값 |
|---|---|
| 버튼 패딩 | 8 / 16 |
| 인풋 패딩 | 10 / 12 |
| 테이블 셀 | 12 / 16 |
| 아이콘-라벨 갭 | 8 |
| 리스트 행 높이 | 44~52 |

### 7.2 Notion — 레이아웃 여백 (넉넉, 가독성·위계 우선)

| 항목 | 값 |
|---|---|
| 페이지 좌우 패딩 | 32 / 64 |
| 콘텐츠 최대폭 | 720~1080 |
| 섹션 간 간격 | 48 / 64 / 80 |
| 블록 간 간격 | 12 / 16 / 24 |
| 카드 내부 패딩 | 16 / 20 / 24 |
