# Persana Design System

> B2B SaaS 기반 디자인 시스템. 웹(Light Mode)과 모바일(Dark Mode) 두 컨텍스트를 포함한다.  
> 이력서 디자인, 웹페이지 구현, 컴포넌트 개발 시 이 토큰과 규칙을 참조할 것.

---

## 1. 색상 토큰 (Color Tokens)

### 1-1. 공유 Accent (Web + Mobile 동일)

| Token              | Hex       | 용도                          |
|--------------------|-----------|-------------------------------|
| `color-accent`     | `#2563EB` | CTA 버튼, 활성 탭, 링크, 체크박스 |
| `color-success`    | `#22C55E` | 성공 상태, Active 뱃지          |
| `color-warning`    | `#D97706` | 경고, Delayed 뱃지              |
| `color-danger`     | `#DC2626` | 위험, Critical 뱃지             |

### 1-2. Web (Light Mode)

| Token                  | Hex       | 용도                     |
|------------------------|-----------|--------------------------|
| `color-bg-base`        | `#FFFFFF` | 페이지 기본 배경          |
| `color-bg-subtle`      | `#F8FAFC` | 테이블 헤더, 사이드바 배경 |
| `color-surface`        | `#FFFFFF` | 카드, 인풋 배경           |
| `color-border`         | `#E2E8F0` | 기본 보더                 |
| `color-text-primary`   | `#1E293B` | 본문, 카드 제목           |
| `color-text-secondary` | `#64748B` | 서브 텍스트, 설명         |
| `color-text-muted`     | `#94A3B8` | 컬럼 헤더, 플레이스홀더   |
| `color-accent-tint`    | `#EFF6FF` | 활성 nav 배경, 뱃지 배경  |

### 1-3. Mobile (Dark Mode)

| Token                  | Hex       | 용도                     |
|------------------------|-----------|--------------------------|
| `color-bg-base`        | `#111116` | 앱 기본 배경              |
| `color-surface`        | `#1C1C28` | 카드, 세그먼트 탭 컨테이너 |
| `color-border`         | `#2E2E3E` | 카드 테두리, 구분선        |
| `color-text-primary`   | `#FFFFFF` | 제목, 주요 수치           |
| `color-text-secondary` | `#A0A0C0` | 서브 텍스트               |
| `color-text-muted`     | `#6E6E8A` | 타임스탬프, 레이블        |

### 1-4. Semantic Overlay (Mobile 인라인 알림용)

```css
/* 컬러 + 투명도 조합으로 어두운 배경에서도 읽히는 알림 */
--alert-critical-bg:  rgba(220, 38,  38,  0.12);
--alert-critical-border: rgba(220, 38,  38,  0.25);
--alert-critical-text: #FCA5A5;

--alert-warning-bg:   rgba(217, 119,  6,  0.12);
--alert-warning-border: rgba(217, 119,  6,  0.25);
--alert-warning-text: #FCD34D;

--alert-info-bg:      rgba(37,  99,  235,  0.12);
--alert-info-border:  rgba(37,  99,  235,  0.25);
--alert-info-text:    #93C5FD;
```

---

## 2. 타이포그래피 (Typography)

### 2-1. Web

| 역할           | Size  | Weight | Color              | 비고                  |
|----------------|-------|--------|--------------------|----------------------|
| 페이지 제목     | 22px  | 500    | `color-text-primary`| e.g. "AI Generate Email" |
| 카드 주 텍스트  | 14px  | 500    | `color-text-primary`| 이름, 회사명          |
| 테이블 본문     | 13px  | 400    | `color-text-secondary`| URL, 이메일         |
| 컬럼 헤더      | 12px  | 400    | `#94A3B8` / uppercase / letter-spacing 0.06em | |
| 뱃지 레이블     | 11px  | 500    | 컬러 ramp 내 텍스트 | |

### 2-2. Mobile

| 역할           | Size    | Weight | Color              | 비고              |
|----------------|---------|--------|--------------------|------------------|
| Hero 수치       | 28–32px | 700    | `#FFFFFF`          | 대시보드 핵심 지표 |
| 페이지 제목     | 20px    | 700    | `#FFFFFF`          |                  |
| 카드 ID / 제목  | 15px    | 600    | `#FFFFFF`          | TRK-892, SHP-8473 |
| 카드 서브       | 13px    | 400    | `#A0A0C0`          | 이름, 위치        |
| 타임스탬프·메타 | 11px    | 400    | `#6E6E8A`          | "2 hours ago"    |

### 2-3. 공통 원칙

- 폰트 패밀리: **시스템 sans-serif** (`-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`)
- 줄간격: 본문 `1.6` / 제목 `1.2`
- 자간: 기본 `0` / 작은 레이블(uppercase) `0.06–0.08em`
- **weight는 400 / 500 / 600 / 700만 사용.** 그 외는 없음.

---

## 3. 간격 (Spacing Scale)

| Token    | Value | 주요 용도                        |
|----------|-------|----------------------------------|
| `sp-1`   | 4px   | 아이콘-텍스트 gap, 배지 내부 패딩 |
| `sp-2`   | 8px   | 아바타-텍스트, 배지 horizontal padding |
| `sp-3`   | 12px  | nav 아이템 gap, 테이블 셀 h-pad  |
| `sp-4`   | 16px  | 섹션 패딩, 카드 내부              |
| `sp-6`   | 24px  | 카드 패딩 (Web), 사이드바 padding |
| `sp-10`  | 40px  | 페이지 헤더 offset               |

**모바일 전용:**

| 영역               | 값                                     |
|--------------------|----------------------------------------|
| 좌우 페이지 패딩    | `16px`                                 |
| 카드 패딩           | `14–16px`                              |
| 카드 사이 gap       | `10–12px`                              |
| 리스트 아이템 min-h | `64px`                                 |
| Safe area bottom   | `env(safe-area-inset-bottom)` (iOS)    |

---

## 4. 보더 & 그림자 (Border & Elevation)

### Border

```css
/* Web */
border: 0.5px solid #E2E8F0;     /* 기본 카드, 인풋 */
border: 0.5px solid #CBD5E1;     /* 강조 보더 */
border: 2px solid #2563EB;       /* Featured 카드 (유일한 2px 예외) */

/* Mobile */
border: 0.5px solid #2E2E3E;     /* 카드, 구분선 */
```

### 그림자

```css
/* Web: 최소화 원칙 — 주로 border로 계층 구분 */
box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);   /* Soft (hover/focus용) */
box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.10); /* Focus ring (인풋) */

/* Mobile: 그림자 없음 — 배경색 대비로만 계층 구분 */
```

---

## 5. Border Radius

| 용도                  | 값     |
|-----------------------|--------|
| 체크박스              | `3px`  |
| 뱃지, 태그            | `4–5px`|
| 버튼, 인풋, 선택 요소  | `6px`  |
| 카드 내부 요소         | `8px`  |
| 카드, 패널, 모달       | `10–12px` |
| 아바타, 원형 버튼      | `50%`  |
| 모바일 카드            | `12–16px` (Web보다 더 둥글게) |

---

## 6. 컴포넌트 명세

### 6-1. 버튼 (Button)

```css
/* Base */
height: 34px;
padding: 7px 14px;
border-radius: 6px;
font-size: 13px;
font-weight: 500;
display: inline-flex;
align-items: center;
gap: 6px;
cursor: pointer;
transition: all 0.15s;

/* Primary */
background: #2563EB;
color: #FFFFFF;
border: none;
/* hover: background: #1D4ED8 */

/* Secondary */
background: #FFFFFF;
color: #1E293B;
border: 0.5px solid #E2E8F0;

/* Ghost */
background: transparent;
color: #64748B;
border: 0.5px solid #E2E8F0;

/* Danger */
background: #FEF2F2;
color: #DC2626;
border: 0.5px solid #FECACA;

/* Small modifier */
height: 30px;
padding: 5px 10px;
font-size: 12px;
border-radius: 5px;
```

### 6-2. 인풋 (Input / Select)

```css
height: 34px;
padding: 0 10px;
border: 0.5px solid #E2E8F0;
border-radius: 6px;
font-size: 13px;
background: #FFFFFF;
color: #1E293B;
outline: none;

/* Focus */
border-color: #2563EB;
box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.10);
```

### 6-3. 뱃지 (Badge)

```css
/* Base */
display: inline-flex;
align-items: center;
padding: 2px 8px;
border-radius: 4px;
font-size: 11px;
font-weight: 500;

/* Web (Light) variants */
/* blue  */ background: #EFF6FF; color: #1D4ED8;
/* green */ background: #F0FDF4; color: #15803D;
/* gray  */ background: #F8FAFC; color: #475569; border: 0.5px solid #E2E8F0;
/* red   */ background: #FEF2F2; color: #DC2626;

/* Mobile (Dark) variants — solid fill */
/* blue  */ background: #2563EB; color: #FFFFFF;
/* green */ background: #16A34A; color: #FFFFFF;
/* red   */ background: #DC2626; color: #FFFFFF;
/* amber */ background: #D97706; color: #FFFFFF;
```

### 6-4. 테이블 (Data Table) — Web

```css
/* Table */
width: 100%;
border-collapse: collapse;
font-size: 13px;

/* Header row */
background: #F8FAFC;
padding: 8px 12px;
color: #94A3B8;
font-size: 12px;
font-weight: 400;
text-transform: uppercase;
letter-spacing: 0.06em;
border-bottom: 0.5px solid #E2E8F0;

/* Data row */
padding: 10px 12px;
min-height: 48px;
border-bottom: 0.5px solid #F1F5F9;
color: #1E293B;

/* Hover */
background: #F8FAFC;
```

### 6-5. 아바타 (Avatar)

```css
width: 28px;        /* Web: 작은 사이즈 */
height: 28px;
border-radius: 50%;
background: #DBEAFE;
color: #1D4ED8;
font-size: 11px;
font-weight: 500;
display: flex;
align-items: center;
justify-content: center;

/* Mobile: 프로필 큰 사이즈 */
width: 72px;
height: 72px;
font-size: 22px;
```

### 6-6. 사이드바 Nav — Web

```css
/* Container */
width: 200px;
padding: 10px;

/* Nav item */
display: flex;
align-items: center;
gap: 10px;
padding: 8px 12px;
border-radius: 6px;
font-size: 13px;
color: #475569;
cursor: pointer;

/* Active */
background: #EFF6FF;
color: #2563EB;
font-weight: 500;

/* Hover */
background: #F8FAFC;

/* Icon */
font-size: 16px;  /* Tabler icon */
```

### 6-7. Bottom Navigation — Mobile

```css
/* Container */
height: 72px;
padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
background: #111116;
border-top: 0.5px solid #2E2E3E;
display: flex;
gap: 4px;

/* Nav item */
flex: 1;
display: flex;
flex-direction: column;
align-items: center;
gap: 3px;
padding: 6px 4px;
border-radius: 12px;
color: #6E6E8A;
font-size: 10px;

/* Active */
background: #2563EB;
color: #FFFFFF;

/* Icon */
font-size: 20px;  /* Tabler icon */
```

### 6-8. 세그먼트 탭 (Segmented Tab) — Mobile

```css
/* Container */
display: flex;
gap: 4px;
background: #1C1C28;
border-radius: 10px;
padding: 4px;

/* Tab item */
flex: 1;
padding: 6px 8px;
border-radius: 7px;
font-size: 12px;
text-align: center;
color: #6E6E8A;
height: 34px;

/* Active */
background: #2563EB;
color: #FFFFFF;
font-weight: 500;
```

### 6-9. 카드 (Card) — Mobile

```css
/* Shipment / Fleet card */
background: #1C1C28;
border-radius: 12–16px;
padding: 14–16px;
border: 0.5px solid #2E2E3E;
margin-bottom: 8–10px;

/* Card ID (primary label) */
font-size: 15px;
font-weight: 600;
color: #FFFFFF;

/* Sub label */
font-size: 12px;
color: #6E6E8A;
```

### 6-10. 인라인 알림 (Inline Alert) — Mobile

```css
/* 카드 내부 full-width row */
border-radius: 8px;
padding: 8px 12px;
font-size: 12px;
display: flex;
align-items: center;
gap: 8px;

/* Critical */
background: rgba(220, 38, 38, 0.12);
color: #FCA5A5;
border: 0.5px solid rgba(220, 38, 38, 0.25);

/* Warning */
background: rgba(217, 119, 6, 0.12);
color: #FCD34D;
border: 0.5px solid rgba(217, 119, 6, 0.25);
```

### 6-11. 대시보드 지표 카드 (Metric Card) — Mobile

```css
background: #1C1C28;
border-radius: 12px;
padding: 14px;
border: 0.5px solid #2E2E3E;

/* Label */
font-size: 10px;
color: #6E6E8A;
margin-bottom: 6px;

/* Value */
font-size: 22–28px;
font-weight: 700;
color: #FFFFFF;

/* Trend up */
font-size: 11px;
color: #22C55E;

/* Trend down */
font-size: 11px;
color: #EF4444;
```

---

## 7. 아이콘 (Icons)

- 라이브러리: **Tabler Icons** (outline 전용, filled 사용 금지)
- Web 인라인: `16px`
- Web 장식용: `20px`
- Mobile 네비게이션: `20px`
- Mobile 카드 내: `13–16px`
- 색상: 부모 컨텍스트 상속 (`currentColor`)

```html
<!-- 사용 예시 -->
<i class="ti ti-package"></i>
<i class="ti ti-truck"></i>
<i class="ti ti-search"></i>
<i class="ti ti-bell"></i>
<i class="ti ti-user"></i>
<i class="ti ti-sparkles"></i>
<i class="ti ti-alert-triangle"></i>
<i class="ti ti-chart-bar"></i>
```

---

## 8. Web ↔ Mobile 토큰 대조

| 속성              | Web (Light)                    | Mobile (Dark)                   |
|-------------------|--------------------------------|---------------------------------|
| BG Base           | `#FFFFFF`                      | `#111116`                       |
| Surface           | `#F8FAFC`                      | `#1C1C28`                       |
| Border            | `0.5px #E2E8F0`                | `0.5px #2E2E3E`                 |
| Text Primary      | `#1E293B`                      | `#FFFFFF`                       |
| Text Secondary    | `#64748B`                      | `#6E6E8A`                       |
| Accent            | `#2563EB` ← **공유**            | `#2563EB` ← **공유**             |
| Card Radius       | `10–12px`                      | `12–16px`                       |
| Page H-Padding    | `20–24px`                      | `16–20px`                       |
| Base Font Size    | `13–14px`                      | `14–15px`                       |
| Nav Pattern       | Left sidebar, 200px            | Bottom tab bar, 72px            |
| Active Nav Style  | `bg #EFF6FF` + blue text       | `bg #2563EB` pill + white text  |
| Inline Alert      | Badge only                     | Full-width colored row          |
| Elevation         | Border + soft shadow           | Border + bg contrast만 사용      |

---

## 9. 접근성 & 터치 타겟 규칙

```
최소 터치 타겟    : 44 × 44px  (버튼, 탭 아이템, 체크박스)
인풋 최소 높이    : 34px
텍스트 최소 크기  : 11px
명도 대비         : 배경 대비 텍스트 최소 4.5:1 (WCAG AA)
Safe area (iOS)  : padding-bottom: env(safe-area-inset-bottom)
Status bar 높이  : ~48px (예약)
Bottom nav 높이  : 72px + safe area
```

---

## 10. 빠른 참조 — CSS 변수 선언 템플릿

```css
:root {
  /* Accent (공유) */
  --color-accent: #2563EB;
  --color-accent-tint: #EFF6FF;
  --color-success: #22C55E;
  --color-warning: #D97706;
  --color-danger: #DC2626;

  /* Web Light */
  --color-bg: #FFFFFF;
  --color-surface: #F8FAFC;
  --color-border: #E2E8F0;
  --color-text-1: #1E293B;
  --color-text-2: #64748B;
  --color-text-3: #94A3B8;

  /* Spacing */
  --sp-1: 4px;
  --sp-2: 8px;
  --sp-3: 12px;
  --sp-4: 16px;
  --sp-6: 24px;

  /* Radius */
  --r-sm: 4px;
  --r-md: 6px;
  --r-lg: 10px;
  --r-xl: 16px;
}

/* Mobile Dark override */
@media (prefers-color-scheme: dark) {
  :root {
    --color-bg: #111116;
    --color-surface: #1C1C28;
    --color-border: #2E2E3E;
    --color-text-1: #FFFFFF;
    --color-text-2: #A0A0C0;
    --color-text-3: #6E6E8A;
  }
}
```

---

*마지막 업데이트: 2026-05 · Persana(Persana AI) 화면 분석 기반*
