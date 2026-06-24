import React, { useEffect, useState } from "react";
import { api } from "./api";

const NODE_LABELS = {
  intake: "입력", discovery: "Discovery", strategy: "전략", ux: "UX",
  security: "보안", design_system: "디자인 시스템", features: "기능",
  wireframe: "와이어프레임", backend: "백엔드", frontend: "프론트엔드", mobile: "모바일",
};

// 산출 body 키 한글 라벨(구조화 렌더용)
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
  feature: "기능", source: "출처",
  open_questions: "확인 필요", provenance: "근거 표기",
};
const lab = (k) => KEY_LABELS[k] || k;

function Val({ v }) {
  if (v === null || v === undefined || v === "") return <span className="muted">—</span>;
  if (Array.isArray(v)) {
    if (v.length === 0) return <span className="muted">—</span>;
    if (typeof v[0] === "object") return <>{v.map((x, i) => <div className="item" key={i}><Val v={x} /></div>)}</>;
    return <span>{v.join(", ")}</span>;
  }
  if (typeof v === "object") {
    return (
      <div className="kv">
        {Object.entries(v).map(([k, x]) => (
          <React.Fragment key={k}>
            <div className="k">{lab(k)}</div>
            <div><Val v={x} /></div>
          </React.Fragment>
        ))}
      </div>
    );
  }
  return <span>{String(v)}</span>;
}

function ProvBadges({ p }) {
  if (!p || typeof p !== "object") return null;
  return (
    <div style={{ marginTop: 12 }}>
      {Object.entries(p).map(([k, v]) => (
        <span key={k} className="badge b-inference">{lab(k)}: {String(v)}</span>
      ))}
    </div>
  );
}

// 범용 구조화 렌더(strategy·ux·security·design_system 등). JSON 대신 섹션·카드.
function StructuredView({ body }) {
  const entries = Object.entries(body).filter(([k]) => k !== "provenance");
  return (
    <>
      {entries.map(([k, v]) => (
        <div key={k}>
          <h3>{lab(k)}</h3>
          {Array.isArray(v) && v.length === 0 ? <div className="muted" style={{ fontSize: 13 }}>—</div>
            : Array.isArray(v) ? v.map((it, i) => <div className="item" key={i}><Val v={it} /></div>)
              : (v && typeof v === "object") ? <div className="item"><Val v={v} /></div>
                : <div className="item"><Val v={v} /></div>}
        </div>
      ))}
      <ProvBadges p={body.provenance} />
    </>
  );
}

// Discovery 전용(추론 강조)
function DiscoveryView({ body }) {
  const gi = body.goal_interpretation || {};
  return (
    <>
      <div className="notice">AI가 고객 말을 해석한 결과입니다(전부 추론·미확정). 확정 전까지 가설입니다.</div>
      <h3>목표 해석 — 차원</h3>
      {(gi.inferred_dimensions || []).map((d, i) => <div className="item" key={i}>{d.dimension}<div className="meta">근거: {d.basis}</div></div>)}
      <h3>후보 지표</h3>
      {(gi.candidate_metrics || []).map((m, i) => <div className="item" key={i}>{m.metric} <span className="badge b-inference">confidence: {m.confidence}</span><div className="meta">{m.rationale}</div></div>)}
      <h3>요구 정규화</h3>
      {(body.requirement_normalization || []).map((r) => (
        <div className="item" key={r.id}><b>{r.id}</b> {r.statement}
          <span className={`badge ${r.origin === "context-inferred" ? "b-context" : "b-explicit"}`}>{r.origin === "context-inferred" ? "맥락 추론" : "고객 명시"}</span></div>
      ))}
      <h3>확인 필요</h3>
      <ul className="oq">{(body.open_questions || []).map((q, i) => <li key={i}>{q}</li>)}</ul>
      <div className="meta">target_platform: <b>{body.target_platform}</b> (입력값)</div>
    </>
  );
}

function FeaturesView({ body }) {
  const cls = { Explicit: "b-explicit", Competitive: "b-fact" };
  return (
    <>
      {(body.features || []).map((f, i) => (
        <div className="item" key={i}>{f.feature}
          <span className={`badge ${cls[f.category] || "b-inference"}`}>{f.category}</span>
          <div className="meta">출처: {f.source}</div></div>
      ))}
      {(body.open_questions || []).length > 0 && <>
        <h3>확인 필요</h3>
        <ul className="oq">{body.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul></>}
    </>
  );
}

function RecordBody({ rec }) {
  if (rec.type === "discovery") return <DiscoveryView body={rec.body} />;
  if (rec.type === "features") return <FeaturesView body={rec.body} />;
  return <StructuredView body={rec.body} />;
}

export default function App() {
  const [projects, setProjects] = useState([]);
  const [pk, setPk] = useState(null);
  const [statusData, setStatusData] = useState(null);
  const [records, setRecords] = useState([]);
  const [view, setView] = useState("new");       // "new" | "node"
  const [node, setNode] = useState(null);          // 선택된 노드(produces)
  const [lastRun, setLastRun] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const [goal, setGoal] = useState("동네 풋살 모임을 활성화하고 싶다");
  const [context, setContext] = useState("기존 풋살장 운영 업체. 주말은 차는데 평일이 빔.");
  const [reqs, setReqs] = useState("예약되면 좋겠고\n평일에 사람 모으고 싶다");
  const [platform, setPlatform] = useState("both");

  async function loadProjects() {
    try { const r = await api.listProjects(); setProjects(r.projects || []); } catch (e) { /* 무시 */ }
  }
  useEffect(() => { loadProjects(); }, []);

  async function withBusy(fn) {
    setError(null); setBusy(true);
    try { await fn(); } catch (e) { setError(String(e.message || e)); } finally { setBusy(false); }
  }
  async function refresh(pkv) {
    const [s, r] = await Promise.all([api.status(pkv), api.records(pkv)]);
    setStatusData(s); setRecords(r.records || []);
    return { s, r };
  }

  const openProject = (pkv) => withBusy(async () => {
    setPk(pkv);
    const { s } = await refresh(pkv);
    const awaiting = s.awaiting_approval || [];
    const done = (s.nodes || []).filter((n) => n.status);
    setNode(awaiting[0] || (done.length ? done[done.length - 1].node : "intake"));
    setView("node");
  });

  const create = () => withBusy(async () => {
    const payload = {
      site_character: goal.slice(0, 40),
      requirements: reqs.split("\n").map((x) => x.trim()).filter(Boolean),
      goal: { statement: goal, details: {} },
      context: context.trim() || null,
      target_platform: platform,
    };
    const res = await api.createProject(payload);
    setPk(res.public_key);
    await loadProjects();
    await refresh(res.public_key);
    setNode("intake"); setView("node");
  });

  const runStep = () => withBusy(async () => {
    const res = await api.run(pk); setLastRun(res);
    await refresh(pk);
    if (res.ran) setNode(res.ran);
  });
  const approve = () => withBusy(async () => { await api.approve(pk); setLastRun(null); await refresh(pk); });

  const awaiting = statusData?.awaiting_approval || [];
  const recByType = Object.fromEntries(records.map((r) => [r.type, r]));
  const nodes = statusData?.nodes || [];
  const selectedRec = node ? recByType[node] : null;

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">ROHA</div>
        <button className="btn-tonal" style={{ width: "100%" }} onClick={() => { setView("new"); setPk(null); setNode(null); }}>+ 새 프로젝트</button>

        <div className="sec-label">프로젝트</div>
        {projects.length === 0 && <div className="muted" style={{ fontSize: 13 }}>아직 없음</div>}
        {projects.map((p) => (
          <button key={p.public_key} className={`nav-btn proj-item ${p.public_key === pk ? "active" : ""}`} onClick={() => openProject(p.public_key)}>
            <span>{p.title}</span>
            <small>{p.public_key}</small>
          </button>
        ))}

        {pk && (
          <>
            <div className="sec-label">단계</div>
            {nodes.map((n, i) => (
              <button key={n.node} className={`nav-btn ${node === n.node ? "active" : ""}`} onClick={() => { setNode(n.node); setView("node"); }}>
                <span className="num">{i + 1}</span>
                <span className={`dot ${n.status || ""}`} />
                <span>{NODE_LABELS[n.node] || n.node}</span>
              </button>
            ))}
          </>
        )}
      </aside>

      <main className="main">
        {view === "new" && (
          <div className="card">
            <h2>새 프로젝트</h2>
            <div className="sub">고객 언어 그대로 입력하세요. AI가 해석(Discovery)한 뒤 사람이 확정합니다.</div>
            <label>목표 <span className="req">*</span></label>
            <textarea value={goal} onChange={(e) => setGoal(e.target.value)} />
            <label>맥락 Context <span className="opt">(선택·권장 — 고객이 누구인지·기존 상황)</span></label>
            <textarea value={context} onChange={(e) => setContext(e.target.value)} />
            <label>요구사항 <span className="opt">(선택, 줄마다 하나)</span></label>
            <textarea value={reqs} onChange={(e) => setReqs(e.target.value)} />
            <label>Target Platform</label>
            <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
              <option value="web">web</option><option value="mobile">mobile</option>
              <option value="both">both</option><option value="미정">미정</option>
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
              {lastRun?.ran && <span className="muted">방금: {NODE_LABELS[lastRun.ran] || lastRun.ran}</span>}
              {lastRun?.gate && <span className="muted">게이트 <span className={`gate g-${lastRun.gate.test}`}>test {lastRun.gate.test}</span><span className={`gate g-${lastRun.gate.review}`}>review {lastRun.gate.review}</span></span>}
            </div>
            {awaiting.length > 0 && <div className="card"><div className="notice">사람 검토 대기: 아래 산출을 확인하고 "확정"하세요.</div></div>}
            {error && <div className="card"><div className="err">{error}</div></div>}

            <div className="card">
              <h2>{NODE_LABELS[node] || node} {selectedRec && <span className="muted">({selectedRec.status} v{selectedRec.version})</span>}</h2>
              {selectedRec
                ? (node === "intake" ? <Val v={selectedRec.body} /> : <RecordBody rec={selectedRec} />)
                : <div className="empty">아직 실행 전입니다. 좌측 순서대로 "다음 단계 실행"을 누르세요.</div>}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
