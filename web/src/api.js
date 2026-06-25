// 기존 FastAPI(프록시 경유)를 호출만 한다. 외부 식별자는 public_key만 사용(내부 PK 미사용).
async function j(method, url, body) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opt.body = JSON.stringify(body);
  const res = await fetch(url, opt);
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new Error((data && data.detail) || `${res.status} ${res.statusText}`);
  return data;
}

function qs(params) {
  const p = Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return p.length ? "?" + p.map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&") : "";
}

const enc = encodeURIComponent;
export const api = {
  listProjects: (params) => j("GET", "/projects" + qs(params)),
  createProject: (payload) => j("POST", "/projects", payload),
  run: (pk) => j("POST", `/projects/${enc(pk)}/run`),
  status: (pk) => j("GET", `/projects/${enc(pk)}/status`),
  records: (pk) => j("GET", `/projects/${enc(pk)}/records`),
  approve: (pk) => j("POST", `/projects/${enc(pk)}/approve`),
  complete: (pk) => j("POST", `/projects/${enc(pk)}/complete`),
  reopen: (pk) => j("POST", `/projects/${enc(pk)}/reopen`),
  remove: (pk) => j("DELETE", `/projects/${enc(pk)}`),
};
