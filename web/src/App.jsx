import React, { useEffect, useState } from "react";
import { api } from "./api";

// 단색 라인 아이콘(Tabler 풍). 컬러 이모지 금지 — currentColor 상속.
const IconFolder = () => (
  <svg className="ico" viewBox="0 0 24 24"><path d="M4 6a2 2 0 0 1 2-2h3l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6z" /></svg>
);
const IconPlus = () => (
  <svg className="ico" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>
);
const IconTrash = () => (
  <svg className="ico" viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" /></svg>
);
const IconCheck = () => (
  <svg className="ico" viewBox="0 0 24 24"><path d="M5 12l5 5L20 6" /></svg>
);

// 디바이스(복수 선택). 웹=PC 브라우저, 모바일웹=모바일 브라우저, 모바일=모바일 앱.
const DEVICES = [
  { key: "웹", desc: "PC 브라우저" },
  { key: "모바일웹", desc: "모바일 브라우저" },
  { key: "모바일", desc: "모바일 앱" },
];
// 디바이스 선택 -> discovery 호환 target_platform(web|mobile|both|미정) 파생.
function devicesToPlatform(devices) {
  const web = devices.includes("웹") || devices.includes("모바일웹");
  const app = devices.includes("모바일");
  return web && app ? "both" : app ? "mobile" : web ? "web" : "미정";
}

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
  devices: "디바이스", target_platform: "플랫폼(파생)",
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
const qText = (it) => (typeof it === "string" ? it : (it.question || ""));
const qAns = (it) => (typeof it === "string" ? "" : (it.answer || ""));

function DiscoveryView({ body, pk, onSaved }) {
  const [edit, setEdit] = useState(false);
  const [draft, setDraft] = useState(body);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);
  useEffect(() => { setDraft(body); setEdit(false); setErr(null); }, [body]);

  const src = edit ? draft : body;
  const gi = src.goal_interpretation || {};
  const metrics = gi.candidate_metrics || [];
  const oqs = src.open_questions || [];

  const clone = () => JSON.parse(JSON.stringify(draft));
  const setMetric = (i, f, v) => { const d = clone(); d.goal_interpretation.candidate_metrics[i][f] = v; setDraft(d); };
  // 삭제는 단순 제거가 아니라 '틀림 신호' — body에 남겨 rejected+이유로 표기(재실행 시 AI 입력).
  const rejectMetric = (i) => { const d = clone(); const m = d.goal_interpretation.candidate_metrics[i]; m.rejected = true; if (m.reject_reason == null) m.reject_reason = ""; setDraft(d); };
  const restoreMetric = (i) => { const d = clone(); const m = d.goal_interpretation.candidate_metrics[i]; delete m.rejected; delete m.reject_reason; setDraft(d); };
  const setAnswer = (i, v) => { const d = clone(); d.open_questions[i] = { question: qText(d.open_questions[i]), answer: v }; setDraft(d); };

  // 편집 시작: 지표에 안정적 id(M-01..) 부여(편집·제외가 id로 참조되게).
  const startEdit = () => {
    const d = JSON.parse(JSON.stringify(body));
    ((d.goal_interpretation || {}).candidate_metrics || []).forEach((m, i) => { if (!m.id) m.id = `M-${String(i + 1).padStart(2, "0")}`; });
    setDraft(d); setEdit(true); setErr(null);
  };

  const save = async () => {
    setSaving(true); setErr(null);
    try { await api.editDiscovery(pk, draft); await onSaved(); setEdit(false); }
    catch (e) { setErr(String(e.message || e)); }
    finally { setSaving(false); }
  };
  const cancel = () => { setDraft(body); setEdit(false); setErr(null); };

  return (<>
    <div className="row" style={{ justifyContent: "flex-end", marginBottom: 8 }}>
      {!edit
        ? <button className="btn-tonal" onClick={startEdit}>지표·답변 수정</button>
        : <><button className="btn-text" onClick={cancel} disabled={saving}>취소</button>
            <button className="btn-primary" onClick={save} disabled={saving}>{saving ? "저장 중…" : "저장"}</button></>}
    </div>
    {err && <div className="err" style={{ marginBottom: 8 }}>{err}</div>}
    <div className="notice">AI가 고객 말을 해석한 결과입니다(전부 추론·미확정). 지표는 수정/제외(이유 기록), 확인 필요 항목은 답변을 넣어 다듬을 수 있습니다. 제외·답변은 재실행 시 반영됩니다.</div>

    <h3>목표 해석 — 차원</h3>
    {(gi.inferred_dimensions || []).map((d, i) => <div className="item" key={i}>{d.dimension}<div className="meta">근거: {d.basis}</div></div>)}

    <h3>후보 지표</h3>
    {metrics.length === 0 && <div className="muted" style={{ fontSize: 13 }}>지표 없음</div>}
    {/* 편집 모드: 모든 지표(제외 포함) 노출 — 수정/제외/되돌리기 */}
    {edit && metrics.map((m, i) => m.rejected
      ? <div className="item" key={i} style={{ opacity: 0.7 }}>
          {m.id && <b style={{ fontSize: 12 }}>{m.id} </b>}
          <span style={{ textDecoration: "line-through" }}>{m.metric}</span> <span className="badge b-inference">제외됨</span>
          <label style={{ marginTop: 8 }}>제외 이유(재실행 시 AI 입력)</label>
          <input type="text" value={m.reject_reason || ""} onChange={(e) => setMetric(i, "reject_reason", e.target.value)} placeholder="왜 틀렸는지 — 같은 지표를 다시 내지 않도록" />
          <div className="row" style={{ marginTop: 8, justifyContent: "flex-end" }}>
            <button className="btn-text" onClick={() => restoreMetric(i)}>되돌리기</button>
          </div>
        </div>
      : <div className="item" key={i}>
          {m.id && <b style={{ fontSize: 12 }}>{m.id}</b>}
          <label style={{ marginTop: m.id ? 4 : 0 }}>지표</label>
          <input type="text" value={m.metric || ""} onChange={(e) => setMetric(i, "metric", e.target.value)} />
          <label>근거(rationale)</label>
          <input type="text" value={m.rationale || ""} onChange={(e) => setMetric(i, "rationale", e.target.value)} />
          <div className="row" style={{ marginTop: 8, justifyContent: "space-between" }}>
            <select style={{ width: "auto" }} value={m.confidence || "low"} onChange={(e) => setMetric(i, "confidence", e.target.value)}>
              <option value="low">conf: low</option><option value="medium">conf: medium</option><option value="high">conf: high</option>
            </select>
            <button className="rowbtn del" onClick={() => rejectMetric(i)}>제외</button>
          </div>
        </div>
    )}
    {/* 조회 모드: 활성 지표만 */}
    {!edit && metrics.filter((m) => !m.rejected).map((m, i) => <div className="item" key={i}>{m.metric} <span className="badge b-inference">conf: {m.confidence}</span><div className="meta">{m.rationale}</div></div>)}
    {!edit && metrics.some((m) => m.rejected) && <>
      <h3>제외된 지표 — 재실행 시 반영</h3>
      {metrics.filter((m) => m.rejected).map((m, i) => <div className="item" key={i} style={{ opacity: 0.7 }}>{m.id && <b style={{ fontSize: 12 }}>{m.id} </b>}<span style={{ textDecoration: "line-through" }}>{m.metric}</span> <span className="badge b-inference">제외됨</span><div className="meta">이유: {m.reject_reason || "(미기재)"}</div></div>)}
    </>}

    <h3>요구 정규화 — 고객이 말한 것</h3>
    {(src.requirement_normalization || []).map((r) => <div className="item" key={r.id}><b>{r.id}</b> {r.statement}<span className={`badge ${r.origin === "context-inferred" ? "b-context" : "b-explicit"}`}>{r.origin === "context-inferred" ? "맥락 추론" : "고객 명시"}</span></div>)}

    {(src.proposed_requirements || []).length > 0 && <>
      <h3>제안 요구 — 상용 준비 (검토 필요)</h3>
      <div className="notice" style={{ marginBottom: 8 }}>고객이 말하지 않았지만 상용에 필요한 항목입니다. 채택 여부는 사람이 정합니다.</div>
      {src.proposed_requirements.map((p) => <div className="item" key={p.id}><b>{p.id}</b> {p.statement}<span className="badge b-proposed">제안</span>{p.category && <span className="badge b-inference">{p.category}</span>}<div className="meta">근거: {p.basis}</div><div className="meta">이유: {p.rationale}</div></div>)}
    </>}

    <h3>확인 필요 — 답변 입력</h3>
    {oqs.length === 0 && <div className="muted" style={{ fontSize: 13 }}>확인 필요 항목 없음</div>}
    {oqs.map((it, i) => <div className="item" key={i}>
      <div>{qText(it)}</div>
      {edit
        ? <><label style={{ marginTop: 8 }}>답변</label><textarea value={qAns(it)} onChange={(e) => setAnswer(i, e.target.value)} placeholder="이 질문에 대한 답변을 적어 정교하게 다듬으세요" style={{ minHeight: 56 }} /></>
        : <div className="meta" style={{ marginTop: 6 }}>{qAns(it) ? `답변: ${qAns(it)}` : "미답변"}</div>}
    </div>)}

    <div className="meta" style={{ marginTop: 12 }}>target_platform: <b>{src.target_platform}</b></div>
  </>);
}
function FeaturesView({ body }) {
  const cls = { Explicit: "b-explicit", Competitive: "b-fact" };
  return (<>{(body.features || []).map((f, i) => <div className="item" key={i}>{f.feature}<span className={`badge ${cls[f.category] || "b-inference"}`}>{f.category}</span><div className="meta">출처: {f.source}</div></div>)}
    {(body.open_questions || []).length > 0 && <><h3>확인 필요</h3><ul className="oq">{body.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul></>}</>);
}
// 컴포넌트명 -> 와이어프레임 박스 모양(회색 플레이스홀더). 미지정은 라벨 박스.
function WfComp({ name }) {
  const label = <span className="wf-comp-label">{name}</span>;
  if (name === "table") return (
    <div className="wf-comp wf-table">{label}
      <div className="wf-tr wf-th" /><div className="wf-tr" /><div className="wf-tr" /></div>);
  if (name === "button") return <div className="wf-comp wf-btn">{name}</div>;
  if (name === "badge") return <div className="wf-comp wf-badge">{name}</div>;
  if (name === "input" || name === "search") return <div className="wf-comp wf-input"><span className="wf-ph" />{label}</div>;
  if (name === "sidebar") return (
    <div className="wf-comp wf-sidebar">{label}<div className="wf-line" /><div className="wf-line" /><div className="wf-line" /></div>);
  if (name === "tab") return (
    <div className="wf-comp wf-tabs">{label}<div className="wf-tab wf-tab-on" /><div className="wf-tab" /><div className="wf-tab" /></div>);
  if (name === "profile") return (
    <div className="wf-comp wf-profile">{label}<div className="wf-av" /><div className="wf-lines"><div className="wf-line" /><div className="wf-line short" /></div></div>);
  if (name === "select") return <div className="wf-comp wf-select">{label}<span className="wf-caret">▾</span></div>;
  if (name === "checkbox" || name === "toggle" || name === "radio_card")
    return <div className="wf-comp wf-control"><span className={`wf-ctl wf-ctl-${name}`} />{name}</div>;
  if (name === "card") return (
    <div className="wf-comp wf-card">{label}<div className="wf-line" /><div className="wf-line short" /></div>);
  return <div className="wf-comp wf-box">{name}</div>;
}

function WireframeView({ body }) {
  const screens = body.screens || [];
  const nav = body.navigation || {};
  return (<>
    {nav.pattern && <div className="muted" style={{ fontSize: 13, marginBottom: 14 }}>네비게이션: {nav.pattern}</div>}
    {screens.length === 0 && <div className="muted">화면 없음</div>}
    {screens.map((sc, si) => (
      <div className="wf-frame" key={si}>
        <div className="wf-titlebar"><span className="wf-dot" /><span className="wf-dot" /><span className="wf-dot" />
          <span className="wf-screen-name">{sc.screen}</span></div>
        <div className="wf-viewport">
          {(sc.sections || []).map((se, sj) => (
            <div className="wf-section" key={sj}>
              <div className="wf-section-label">{se.section}</div>
              <div className="wf-comps">
                {(se.components || []).map((c, ck) => <WfComp name={c} key={ck} />)}
                {(!se.components || se.components.length === 0) && <div className="wf-empty">(컴포넌트 없음)</div>}
              </div>
              {(se.feature_refs || []).length > 0 && <div className="wf-featrefs">{se.feature_refs.join(" · ")}</div>}
            </div>
          ))}
          {(sc.sections || []).length === 0 && <div className="wf-empty">(영역 없음)</div>}
        </div>
      </div>
    ))}
    {(body.open_questions || []).length > 0 && <><h3>확인 필요</h3><ul className="oq">{body.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul></>}
  </>);
}

function RecordBody({ rec, pk, onSaved }) {
  if (rec.type === "discovery") return <DiscoveryView body={rec.body} pk={pk} onSaved={onSaved} />;
  if (rec.type === "features") return <FeaturesView body={rec.body} />;
  if (rec.type === "wireframe") return <WireframeView body={rec.body} />;
  return <StructuredView body={rec.body} />;
}

function ProjectList({ onOpen, tab, onNew }) {
  // tab(active|done)은 사이드바 2depth 메뉴가 제어. 와이어프레임: 표 아님, 2열 카드 그리드 + 검색 + 새 프로젝트.
  const [sort, setSort] = useState("recent");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [q, setQ] = useState("");
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
  const shown = data.projects.filter((p) => !q || (p.title + " " + p.business_key).toLowerCase().includes(q.toLowerCase()));

  return (
    <div className="proj-page">
      <div className="list-head">
        <div>
          <h2 className="list-title">{tab === "done" ? "완료" : "프로젝트"}</h2>
          <div className="list-sub">{tab === "done" ? "완료된 프로젝트 보관함입니다." : `총 ${data.total}개 워크스페이스 · 진행 중인 작업을 이어서 진행하세요`}</div>
        </div>
        <button className="btn-primary new-proj" onClick={onNew}><IconPlus />새 프로젝트</button>
      </div>

      <div className="search-row">
        <div className="search-box">
          <svg className="ico" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4-4" /></svg>
          <input type="search" placeholder="프로젝트·repo·에이전트 검색…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select className="seg-sel" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="recent">최근순</option>
          <option value="incomplete">미완성순</option>
        </select>
      </div>

      <div className="filter-row">
        <span className="muted">기간</span>
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <span className="muted">~</span>
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        {(from || to) && <button className="btn-text" onClick={() => { setFrom(""); setTo(""); }}>기간 해제</button>}
        <span className="muted" style={{ marginLeft: "auto" }}>총 {data.total}건</span>
      </div>

      {shown.length === 0
        ? <div className="empty">{busy ? "불러오는 중…" : "프로젝트가 없습니다."}</div>
        : (
          <div className="proj-grid">
            {shown.map((p) => {
              const pct = Math.round((p.progress.confirmed / p.progress.total) * 100);
              return (
                <div className="proj-card" key={p.public_key} onClick={() => onOpen(p.public_key)} role="button" tabIndex={0}>
                  <div className="pc-top">
                    <div className="pc-name">{p.title}</div>
                    <span className={`pc-badge ${p.status === "done" ? "is-done" : "is-active"}`}>{p.status === "done" ? "완료" : "진행중"}</span>
                  </div>
                  <div className="pc-key">{p.business_key}</div>
                  <div className="pc-bar"><span className="pc-bar-fill" style={{ width: pct + "%" }} /></div>
                  <div className="pc-foot">
                    <div className="pc-actions" onClick={(e) => e.stopPropagation()}>
                      {p.status === "done"
                        ? <button className="btn-text rowbtn" onClick={() => act(() => api.reopen(p.public_key))}>재개</button>
                        : <button className="btn-text rowbtn" onClick={() => act(() => api.complete(p.public_key))}>완료</button>}
                      <button className="rowbtn del" onClick={() => { if (confirm("이 프로젝트를 삭제(숨김)할까요?")) act(() => api.remove(p.public_key)); }}><IconTrash />삭제</button>
                    </div>
                    <div className="pc-pct">{p.progress.confirmed}/{p.progress.total} <b>{pct}%</b></div>
                  </div>
                </div>
              );
            })}
          </div>
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
  const [view, setView] = useState("new");   // 홈=새 프로젝트 고정. list | new | node
  const [listTab, setListTab] = useState("active");  // 프로젝트 2depth: active(진행 중) | done(완료/아카이브)
  const [pk, setPk] = useState(null);
  const [statusData, setStatusData] = useState(null);
  const [records, setRecords] = useState([]);
  const [node, setNode] = useState(null);
  const [lastRun, setLastRun] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const [goal, setGoal] = useState("");
  const [context, setContext] = useState("");
  const [reqs, setReqs] = useState("");
  const [devices, setDevices] = useState([]);
  const toggleDevice = (k) => setDevices((d) => (d.includes(k) ? d.filter((x) => x !== k) : [...d, k]));

  // 테마는 인디고 고정(index.html). 모드(light|dark)만 토글·저장.
  const [mode, setMode] = useState(() => (document.documentElement.getAttribute("data-mode") === "dark" ? "dark" : "light"));
  const applyMode = (m) => {
    if (m === "dark") document.documentElement.setAttribute("data-mode", "dark");
    else document.documentElement.removeAttribute("data-mode");
    try { localStorage.setItem("roha-mode", m); } catch { /* noop */ }
    setMode(m);
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
      goal: { statement: goal, details: {} }, context: context.trim() || null,
      devices, target_platform: devicesToPlatform(devices) };
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
        <div className="sb-top">
          <div className="brand"><div className="mark">R</div><div className="nm">ROHA</div></div>
          <div className="nav">
            {/* 1) 홈 = 새 프로젝트(최상위) */}
            <button className={`nav-btn ${view === "new" ? "active" : ""}`} onClick={() => { setView("new"); setPk(null); setNode(null); }}><IconPlus />새 프로젝트</button>
            {/* 2) 프로젝트 — 2depth(진행 중 / 완료). 탭 아님, 메뉴로 분리. 진행 중에 초점, 완료는 아카이브. */}
            <div className="nav-group">
              <div className="nav-group-label"><IconFolder />프로젝트</div>
              <button className={`nav-btn nav-sub ${view === "list" && listTab === "active" ? "active" : ""}`} onClick={() => { setListTab("active"); setView("list"); setPk(null); setNode(null); }}>진행 중</button>
              <button className={`nav-btn nav-sub ${view === "list" && listTab === "done" ? "active" : ""}`} onClick={() => { setListTab("done"); setView("list"); setPk(null); setNode(null); }}>완료</button>
            </div>
            {/* 3) 프로젝트 열람 시 단계 네비 */}
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
          </div>
        </div>
        <div className="sb-bottom">
          <div>
            <div className="seg-label">모드</div>
            <div className="seg">
              <button className={mode === "light" ? "on" : ""} onClick={() => applyMode("light")}>라이트</button>
              <button className={mode === "dark" ? "on" : ""} onClick={() => applyMode("dark")}>다크</button>
            </div>
          </div>
        </div>
      </aside>

      <main className="main">
        {view === "list" && <ProjectList onOpen={openProject} tab={listTab} onNew={() => { setView("new"); setPk(null); setNode(null); }} />}

        {view === "new" && (
          <div className="card">
            <h2>새 프로젝트</h2>
            <div className="sub">고객 언어 그대로 입력하세요. AI가 해석(Discovery)한 뒤 사람이 확정합니다.</div>
            <label>목표 <span className="req">*</span></label>
            <textarea value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="프로덕트의 구축 목표를 작성하세요" />
            <label>맥락 Context <span className="opt">(선택·권장)</span></label>
            <textarea value={context} onChange={(e) => setContext(e.target.value)} />
            <label>요구사항 <span className="opt">(선택, 줄마다 하나)</span></label>
            <textarea value={reqs} onChange={(e) => setReqs(e.target.value)} />
            <label>디바이스 <span className="opt">(선택, 복수 가능 · 나중에 확정 가능)</span></label>
            <div className="cb-list">
              {DEVICES.map((d) => (
                <div key={d.key} className={`cb-row ${devices.includes(d.key) ? "sel" : ""}`} onClick={() => toggleDevice(d.key)}>
                  <span className={`cb ${devices.includes(d.key) ? "on" : ""}`}>{devices.includes(d.key) && <IconCheck />}</span>
                  <span><span className="cb-name">{d.key}</span> <span className="cb-desc">{d.desc}</span></span>
                </div>
              ))}
            </div>
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
              <button className="btn-text" disabled={busy} onClick={() => withBusy(() => refresh(pk))} title="저장된 최신 상태로 화면을 다시 맞춥니다(재조회). 에이전트를 다시 돌리지 않습니다.">재정리</button>
              <button className="btn-text" onClick={() => setView("list")}>← 목록</button>
              {lastRun?.gate && <span className="muted">게이트 <span className={`gate g-${lastRun.gate.test}`}>test {lastRun.gate.test}</span><span className={`gate g-${lastRun.gate.review}`}>review {lastRun.gate.review}</span></span>}
            </div>
            {awaiting.length > 0 && <div className="card"><div className="notice">사람 검토 대기: 아래 산출을 확인하고 "확정"하세요.</div></div>}
            {error && <div className="card"><div className="err">{error}</div></div>}
            <div className="card">
              <h2>{NODE_LABELS[node] || node} {selectedRec && <span className="muted">({selectedRec.status} v{selectedRec.version})</span>}</h2>
              {selectedRec ? (node === "intake" ? <Val v={selectedRec.body} /> : <RecordBody rec={selectedRec} pk={pk} onSaved={() => refresh(pk)} />)
                : <div className="empty">아직 실행 전입니다. 좌측 순서대로 "다음 단계 실행"을 누르세요.</div>}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
