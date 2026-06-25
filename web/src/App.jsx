import React, { useEffect, useState } from "react";
import { api } from "./api";

const NODE_LABELS = {
  intake: "입력", discovery: "Discovery", strategy: "전략", ux: "UX",
  security: "보안", design_system: "디자인 시스템", features: "기능",
  wireframe: "와이어프레임", backend: "백엔드", frontend: "프론트엔드", mobile: "모바일",
};
const KEY_LABELS = {
  competitors: "경쟁사", market_gaps: "시장 갭", unique_angles: "고유 강점", wow_points: "와우포인트",
  options: "전략 옵션", chosen: "선택(사람)", rationale: "근거", tradeoffs: "트레이드오프", label: "옵션",
  name: "이름", source_url: "출처", axes: "비교 축",
  primary_tasks: "핵심 태스크", user_flows: "사용자 플로우", information_architecture: "정보구조",
  ux_principles: "UX 원칙", task: "태스크", steps: "단계", screen: "화면", purpose: "목적", tasks: "태스크",
  security_requirements: "보안 통제", data_classification: "데이터 분류", threat_model: "위협 모델",
  control: "통제", category: "분류", source_requirement: "출처 요구", origin: "출처", data: "데이터",
  sensitivity: "민감도", threat: "위협", mitigated_by: "완화 수단",
  features: "기능", priority: "우선순위", acceptance_criteria: "수용 기준", security_controls: "보안 통제",
  feature: "기능", source: "출처", open_questions: "확인 필요", provenance: "근거 표기",
};
const lab = (k) => KEY_LABELS[k] || k;
const fmtDate = (s) => (s ? s.slice(0, 16).replace("T", " ") : "");

function Val({ v }) {
  if (v === null || v === undefined || v === "") return <span className="muted">—</span>;
  if (Array.isArray(v)) {
    if (v.length === 0) return <span className="muted">—</span>;
    if (typeof v[0] === "object") return <>{v.map((x, i) => <div className="item" key={i}><Val v={x} /></div>)}</>;
    return <span>{v.join(", ")}</span>;
  }
  if (typeof v === "object") {
    return <div className="kv">{Object.entries(v).map(([k, x]) => (
      <React.Fragment key={k}><div className="k">{lab(k)}</div><div><Val v={x} /></div></React.Fragment>))}</div>;
  }
  return <span>{String(v)}</span>;
}
function ProvBadges({ p }) {
  if (!p || typeof p !== "object") return null;
  return <div style={{ marginTop: 12 }}>{Object.entries(p).map(([k, v]) => <span key={k} className="badge b-inference">{lab(k)}: {String(v)}</span>)}</div>;
}
function StructuredView({ body }) {
  return <>{Object.entries(body).filter(([k]) => k !== "provenance").map(([k, v]) => (
    <div key={k}><h3>{lab(k)}</h3>
      {Array.isArray(v) ? (v.length ? v.map((it, i) => <div className="item" key={i}><Val v={it} /></div>) : <div className="muted" style={{ fontSize: 13 }}>—</div>)
        : <div className="item"><Val v={v} /></div>}
    </div>))}<ProvBadges p={body.provenance} /></>;
}
function DiscoveryView({ body }) {
  const gi = body.goal_interpretation || {};
  return (<>
    <div className="notice">AI가 고객 말을 해석한 결과입니다(전부 추론·미확정).</div>
    <h3>목표 해석 — 차원</h3>{(gi.inferred_dimensions || []).map((d, i) => <div className="item" key={i}>{d.dimension}<div className="meta">근거: {d.basis}</div></div>)}
    <h3>후보 지표</h3>{(gi.candidate_metrics || []).map((m, i) => <div className="item" key={i}>{m.metric} <span className="badge b-inference">conf: {m.confidence}</span><div className="meta">{m.rationale}</div></div>)}
    <h3>요구 정규화 — 고객이 말한 것</h3>{(body.requirement_normalization || []).map((r) => <div className="item" key={r.id}><b>{r.id}</b> {r.statement}<span className={`badge ${r.origin === "context-inferred" ? "b-context" : "b-explicit"}`}>{r.origin === "context-inferred" ? "맥락 추론" : "고객 명시"}</span></div>)}
    {(body.proposed_requirements || []).length > 0 && <>
      <h3>제안 요구 — 상용 준비 (검토 필요)</h3>
      <div className="notice" style={{ marginBottom: 8 }}>고객이 말하지 않았지만 상용에 필요한 항목입니다. 채택 여부는 사람이 정합니다.</div>
      {body.proposed_requirements.map((p) => <div className="item" key={p.id}><b>{p.id}</b> {p.statement}<span className="badge b-proposed">제안</span>{p.category && <span className="badge b-inference">{p.category}</span>}<div className="meta">근거: {p.basis}</div><div className="meta">이유: {p.rationale}</div></div>)}
    </>}
    <h3>확인 필요</h3><ul className="oq">{(body.open_questions || []).map((q, i) => <li key={i}>{q}</li>)}</ul>
    <div className="meta">target_platform: <b>{body.target_platform}</b></div>
  </>);
}
function FeaturesView({ body }) {
  const cls = { Explicit: "b-explicit", Competitive: "b-fact" };
  return (<>{(body.features || []).map((f, i) => <div className="item" key={i}>{f.feature}<span className={`badge ${cls[f.category] || "b-inference"}`}>{f.category}</span><div className="meta">출처: {f.source}</div></div>)}
    {(body.open_questions || []).length > 0 && <><h3>확인 필요</h3><ul className="oq">{body.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul></>}</>);
}
function RecordBody({ rec }) {
  if (rec.type === "discovery") return <DiscoveryView body={rec.body} />;
  if (rec.type === "features") return <FeaturesView body={rec.body} />;
  return <StructuredView body={rec.body} />;
}

function ProjectList({ onOpen }) {
  const [tab, setTab] = useState("active");
  const [sort, setSort] = useState("recent");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ projects: [], total: 0, page: 1, page_size: 20 });
  const [busy, setBusy] = useState(false);

  async function load() {
    setBusy(true);
    try {
      const d = await api.listProjects({ tab, sort, page, date_from: from || undefined, date_to: to || undefined });
      setData(d);
    } finally { setBusy(false); }
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [tab, sort, from, to, page]);
  useEffect(() => { setPage(1); /* eslint-disable-next-line */ }, [tab, sort, from, to]);

  const act = async (fn) => { await fn(); await load(); };
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <div className="card">
      <h2>프로젝트</h2>
      <div className="tabs">
        <button className={`tab ${tab === "active" ? "active" : ""}`} onClick={() => setTab("active")}>진행 중</button>
        <button className={`tab ${tab === "done" ? "active" : ""}`} onClick={() => setTab("done")}>완료</button>
      </div>
      <div className="toolbar">
        <label>정렬</label>
        <select value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="recent">최근순</option>
          <option value="incomplete">미완성순</option>
        </select>
        <label>기간</label>
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <span className="muted">~</span>
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        {(from || to) && <button className="btn-text" onClick={() => { setFrom(""); setTo(""); }}>기간 해제</button>}
        <span className="muted" style={{ marginLeft: "auto" }}>총 {data.total}건</span>
      </div>
      {data.projects.length === 0
        ? <div className="empty">{busy ? "불러오는 중…" : "프로젝트가 없습니다."}</div>
        : (
          <table className="ptable">
            <thead><tr><th>제목</th><th>진행도</th><th>생성</th><th style={{ width: 220 }}>액션</th></tr></thead>
            <tbody>
              {data.projects.map((p) => {
                const pct = Math.round((p.progress.confirmed / p.progress.total) * 100);
                return (
                  <tr key={p.public_key}>
                    <td>{p.title}{p.status === "done" && <span className="chip-done" style={{ marginLeft: 8 }}>완료</span>}<div className="muted" style={{ fontSize: 11 }}>{p.business_key}</div></td>
                    <td><span className="bar"><span className="bar-fill" style={{ width: pct + "%" }} /></span> <span className="muted">{p.progress.confirmed}/{p.progress.total}</span></td>
                    <td className="muted">{fmtDate(p.created_at)}</td>
                    <td>
                      <button className="btn-tonal rowbtn" onClick={() => onOpen(p.public_key)}>열기</button>
                      {p.status === "done"
                        ? <button className="btn-text rowbtn" onClick={() => act(() => api.reopen(p.public_key))}>재개</button>
                        : <button className="btn-text rowbtn" onClick={() => act(() => api.complete(p.public_key))}>완료</button>}
                      <button className="rowbtn del" onClick={() => { if (confirm("이 프로젝트를 삭제(숨김)할까요?")) act(() => api.remove(p.public_key)); }}>삭제</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      <div className="pager">
        <button className="btn-text" disabled={page <= 1} onClick={() => setPage(page - 1)}>← 이전</button>
        <span className="muted">{page} / {pages}</span>
        <button className="btn-text" disabled={page >= pages} onClick={() => setPage(page + 1)}>다음 →</button>
      </div>
    </div>
  );
}

export default function App() {
  const [view, setView] = useState("list");   // list | new | node
  const [pk, setPk] = useState(null);
  const [statusData, setStatusData] = useState(null);
  const [records, setRecords] = useState([]);
  const [node, setNode] = useState(null);
  const [lastRun, setLastRun] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const [goal, setGoal] = useState("동네 풋살 모임을 활성화하고 싶다");
  const [context, setContext] = useState("기존 풋살장 운영 업체. 주말은 차는데 평일이 빔.");
  const [reqs, setReqs] = useState("예약되면 좋겠고\n평일에 사람 모으고 싶다");
  const [platform, setPlatform] = useState("both");

  // 테마: index.html이 초기 data-theme를 이미 설정함. 여기선 그 값을 읽어 토글/저장만.
  const [theme, setTheme] = useState(() =>
    (typeof document !== "undefined" && document.documentElement.getAttribute("data-theme")) || "light");
  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("roha-theme", next); } catch { /* noop */ }
    setTheme(next);
  };

  async function withBusy(fn) { setError(null); setBusy(true); try { await fn(); } catch (e) { setError(String(e.message || e)); } finally { setBusy(false); } }
  async function refresh(pkv) { const [s, r] = await Promise.all([api.status(pkv), api.records(pkv)]); setStatusData(s); setRecords(r.records || []); return { s, r }; }

  const openProject = (pkv) => withBusy(async () => {
    setPk(pkv); const { s } = await refresh(pkv);
    const aw = s.awaiting_approval || []; const done = (s.nodes || []).filter((n) => n.status);
    setNode(aw[0] || (done.length ? done[done.length - 1].node : "intake")); setView("node");
  });
  const create = () => withBusy(async () => {
    const payload = { site_character: goal.slice(0, 40), requirements: reqs.split("\n").map((x) => x.trim()).filter(Boolean),
      goal: { statement: goal, details: {} }, context: context.trim() || null, target_platform: platform };
    const res = await api.createProject(payload); setPk(res.public_key); await refresh(res.public_key); setNode("intake"); setView("node");
  });
  const runStep = () => withBusy(async () => { const res = await api.run(pk); setLastRun(res); await refresh(pk); if (res.ran) setNode(res.ran); });
  const approve = () => withBusy(async () => { await api.approve(pk); setLastRun(null); await refresh(pk); });

  const awaiting = statusData?.awaiting_approval || [];
  const recByType = Object.fromEntries(records.map((r) => [r.type, r]));
  const nodes = statusData?.nodes || [];
  const selectedRec = node ? recByType[node] : null;

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">ROHA</div>
        <button className={`nav-btn ${view === "list" ? "active" : ""}`} onClick={() => setView("list")}>📁 프로젝트</button>
        <button className={`nav-btn ${view === "new" ? "active" : ""}`} onClick={() => { setView("new"); setPk(null); setNode(null); }}>＋ 새 프로젝트</button>
        {pk && view === "node" && (
          <>
            <div className="sec-label">단계 — {statusData?.business_key || ""}</div>
            {nodes.map((n, i) => (
              <button key={n.node} className={`nav-btn ${node === n.node ? "active" : ""}`} onClick={() => setNode(n.node)}>
                <span className="num">{i + 1}</span><span className={`dot ${n.status || ""}`} /><span>{NODE_LABELS[n.node] || n.node}</span>
              </button>
            ))}
          </>
        )}
        <button className="theme-toggle" onClick={toggleTheme}>
          {theme === "dark" ? "☀️ 라이트 모드" : "🌙 다크 모드"}
        </button>
      </aside>

      <main className="main">
        {view === "list" && <ProjectList onOpen={openProject} />}

        {view === "new" && (
          <div className="card">
            <h2>새 프로젝트</h2>
            <div className="sub">고객 언어 그대로 입력하세요. AI가 해석(Discovery)한 뒤 사람이 확정합니다.</div>
            <label>목표 <span className="req">*</span></label>
            <textarea value={goal} onChange={(e) => setGoal(e.target.value)} />
            <label>맥락 Context <span className="opt">(선택·권장)</span></label>
            <textarea value={context} onChange={(e) => setContext(e.target.value)} />
            <label>요구사항 <span className="opt">(선택, 줄마다 하나)</span></label>
            <textarea value={reqs} onChange={(e) => setReqs(e.target.value)} />
            <label>Target Platform</label>
            <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
              <option value="web">web</option><option value="mobile">mobile</option><option value="both">both</option><option value="미정">미정</option>
            </select>
            <div className="row" style={{ marginTop: 16 }}>
              <button className="btn-primary" disabled={busy || !goal.trim()} onClick={create}>{busy ? "생성 중…" : "프로젝트 생성"}</button>
            </div>
            {error && <div className="err">{error}</div>}
          </div>
        )}

        {view === "node" && (
          <>
            <div className="actionbar">
              {awaiting.length > 0
                ? <button className="btn-primary" disabled={busy} onClick={approve}>{busy ? "처리 중…" : `확정 (${awaiting.map((a) => NODE_LABELS[a] || a).join(", ")})`}</button>
                : <button className="btn-primary" disabled={busy} onClick={runStep}>{busy ? "실행 중…" : "다음 단계 실행"}</button>}
              <button className="btn-text" disabled={busy} onClick={() => withBusy(() => refresh(pk))}>새로고침</button>
              <button className="btn-text" onClick={() => setView("list")}>← 목록</button>
              {lastRun?.gate && <span className="muted">게이트 <span className={`gate g-${lastRun.gate.test}`}>test {lastRun.gate.test}</span><span className={`gate g-${lastRun.gate.review}`}>review {lastRun.gate.review}</span></span>}
            </div>
            {awaiting.length > 0 && <div className="card"><div className="notice">사람 검토 대기: 아래 산출을 확인하고 "확정"하세요.</div></div>}
            {error && <div className="card"><div className="err">{error}</div></div>}
            <div className="card">
              <h2>{NODE_LABELS[node] || node} {selectedRec && <span className="muted">({selectedRec.status} v{selectedRec.version})</span>}</h2>
              {selectedRec ? (node === "intake" ? <Val v={selectedRec.body} /> : <RecordBody rec={selectedRec} />)
                : <div className="empty">아직 실행 전입니다. 좌측 순서대로 "다음 단계 실행"을 누르세요.</div>}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
