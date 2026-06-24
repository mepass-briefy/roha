import { useState } from "react";
import { api } from "./api";

const NODE_LABELS = {
  intake: "입력", discovery: "Discovery", strategy: "전략", ux: "UX",
  security: "보안", design_system: "디자인 시스템", features: "기능",
  wireframe: "와이어프레임", backend: "백엔드", frontend: "프론트엔드",
};

function GateChip({ run }) {
  if (!run || !run.gate) return null;
  const g = run.gate;
  return (
    <span className="muted">
      게이트: <span className={`gate g-${g.test}`}>test {g.test}</span>
      <span className={`gate g-${g.review}`}>review {g.review}</span>
    </span>
  );
}

function OriginBadge({ origin }) {
  const map = { explicit: "b-explicit", "context-inferred": "b-context", fact: "b-fact" };
  const label = { explicit: "고객 명시", "context-inferred": "맥락 추론", fact: "사실" };
  return <span className={`badge ${map[origin] || "b-inference"}`}>{label[origin] || origin || "추론"}</span>;
}

function DiscoveryView({ body }) {
  const gi = body.goal_interpretation || {};
  return (
    <div className="card">
      <h2>Discovery 검토 <span className="badge b-inference">전부 추론·미확정</span></h2>
      <div className="notice">아래는 AI가 고객 말을 해석한 결과입니다. 확정 전까지 가설입니다.</div>

      <h3>목표 해석 (차원)</h3>
      {(gi.inferred_dimensions || []).map((d, i) => (
        <div className="item" key={i}>{d.dimension}<div className="meta">근거: {d.basis}</div></div>
      ))}
      <h3>후보 지표</h3>
      {(gi.candidate_metrics || []).map((m, i) => (
        <div className="item" key={i}>{m.metric} <span className="badge b-inference">confidence: {m.confidence}</span>
          <div className="meta">{m.rationale}</div></div>
      ))}
      <h3>요구 정규화</h3>
      {(body.requirement_normalization || []).map((r) => (
        <div className="item" key={r.id}><b>{r.id}</b> {r.statement} <OriginBadge origin={r.origin} /></div>
      ))}
      <h3>확인 필요 (Open Questions)</h3>
      <ul className="oq">{(body.open_questions || []).map((q, i) => <li key={i}>{q}</li>)}</ul>
      <div className="meta">target_platform: <b>{body.target_platform}</b> (입력값)</div>
    </div>
  );
}

function FeaturesView({ body }) {
  const catClass = { Explicit: "b-explicit", Derived: "b-inference", Operational: "b-inference", Competitive: "b-fact" };
  return (
    <div className="card">
      <h2>기능 (features)</h2>
      {(body.features || []).map((f, i) => (
        <div className="item" key={i}>{f.feature}
          <span className={`badge ${catClass[f.category] || "b-inference"}`}>{f.category}</span>
          <div className="meta">source: {f.source}</div></div>
      ))}
      {(body.open_questions || []).length > 0 && <>
        <h3>확인 필요</h3>
        <ul className="oq">{body.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
      </>}
    </div>
  );
}

function RecordView({ rec }) {
  if (rec.type === "discovery") return <DiscoveryView body={rec.body} />;
  if (rec.type === "features") return <FeaturesView body={rec.body} />;
  return (
    <div className="card">
      <h2>{NODE_LABELS[rec.type] || rec.type} <span className="muted">({rec.status} v{rec.version})</span></h2>
      <pre className="body">{JSON.stringify(rec.body, null, 2)}</pre>
    </div>
  );
}

export default function App() {
  const [view, setView] = useState("input");
  const [pk, setPk] = useState(null);
  const [statusData, setStatusData] = useState(null);
  const [records, setRecords] = useState([]);
  const [lastRun, setLastRun] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const [goal, setGoal] = useState("동네 풋살 모임을 활성화하고 싶다");
  const [context, setContext] = useState("기존 풋살장 운영 업체. 주말은 차는데 평일이 빔.");
  const [reqs, setReqs] = useState("예약되면 좋겠고\n평일에 사람 모으고 싶다");
  const [platform, setPlatform] = useState("both");

  async function refresh(pkv) {
    const [s, r] = await Promise.all([api.status(pkv), api.records(pkv)]);
    setStatusData(s);
    setRecords(r.records || []);
  }

  async function withBusy(fn) {
    setError(null); setBusy(true);
    try { await fn(); } catch (e) { setError(String(e.message || e)); } finally { setBusy(false); }
  }

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
    await refresh(res.public_key);
    setView("workbench");
  });

  const runStep = () => withBusy(async () => {
    const res = await api.run(pk);
    setLastRun(res);
    await refresh(pk);
  });

  const approve = () => withBusy(async () => {
    await api.approve(pk);
    setLastRun(null);
    await refresh(pk);
  });

  const awaiting = statusData?.awaiting_approval || [];

  return (
    <div className="app">
      <div className="topbar">
        <h1>ROHA Workbench</h1>
        {pk && <span className="pk">project: {pk}</span>}
      </div>

      {view === "input" && (
        <div className="card">
          <h2>새 프로젝트</h2>
          <label>목표 <span className="req">*</span></label>
          <textarea value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="고객 언어 그대로의 목표" />
          <label>맥락 Context <span className="muted">(선택·권장)</span></label>
          <textarea value={context} onChange={(e) => setContext(e.target.value)} placeholder="고객이 누구인지·기존 상황" />
          <label>요구사항 <span className="muted">(선택, 줄마다 하나)</span></label>
          <textarea value={reqs} onChange={(e) => setReqs(e.target.value)} />
          <label>Target Platform</label>
          <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
            <option value="web">web</option>
            <option value="mobile">mobile</option>
            <option value="both">both</option>
            <option value="미정">미정</option>
          </select>
          <div className="row">
            <button className="btn-primary" disabled={busy || !goal.trim()} onClick={create}>
              {busy ? "생성 중…" : "프로젝트 생성"}
            </button>
          </div>
          {error && <div className="err">{error}</div>}
        </div>
      )}

      {view === "workbench" && (
        <>
          <div className="steps">
            {(statusData?.nodes || []).map((n) => (
              <span key={n.node} className={`step ${n.status || ""}`}>
                {NODE_LABELS[n.node] || n.node}{n.status ? `: ${n.status}` : ""}
              </span>
            ))}
          </div>

          <div className="card">
            <div className="row" style={{ marginTop: 0 }}>
              {awaiting.length > 0 ? (
                <button className="btn-primary" disabled={busy} onClick={approve}>
                  {busy ? "처리 중…" : `확정 (게이트 통과: ${awaiting.map((a) => NODE_LABELS[a] || a).join(", ")})`}
                </button>
              ) : (
                <button className="btn-primary" disabled={busy} onClick={runStep}>
                  {busy ? "실행 중…" : "다음 단계 실행"}
                </button>
              )}
              <button className="btn-text" disabled={busy} onClick={() => withBusy(() => refresh(pk))}>새로고침</button>
              {lastRun && lastRun.ran && <span className="muted">방금 실행: {NODE_LABELS[lastRun.ran] || lastRun.ran} </span>}
              <GateChip run={lastRun} />
            </div>
            {awaiting.length > 0 && <div className="notice" style={{ marginTop: 12 }}>사람 검토 대기: 위 산출을 확인하고 확정하세요.</div>}
            {error && <div className="err">{error}</div>}
          </div>

          {[...records].sort((a, b) => (statusData?.nodes || []).findIndex((n) => n.node === a.type) - (statusData?.nodes || []).findIndex((n) => n.node === b.type))
            .filter((r) => r.type !== "intake")
            .map((rec) => <RecordView key={rec.type} rec={rec} />)}
        </>
      )}
    </div>
  );
}
