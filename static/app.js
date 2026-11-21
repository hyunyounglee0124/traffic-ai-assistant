// 내 데이터를 아는 AI 비서 — 화면 스크립트 (프레임워크 없이 순수 JavaScript)
// 서버 응답을 화면에 넣을 때는 모두 escapeHtml / textContent를 거쳐 XSS를 막는다.

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const WD = ["월", "화", "수", "목", "금", "토", "일"];
let UNIT = "", charts = {};

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
// 안전한 간이 마크다운: 먼저 HTML을 이스케이프한 뒤 **굵게**만 변환
function mdLite(s) { return escapeHtml(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>"); }
const fmt = (n) => (n === null || n === undefined ? "–" : Number(n).toLocaleString("ko-KR", { maximumFractionDigits: 0 }));
const pct = (n) => (n === null || n === undefined ? "–" : `${n > 0 ? "+" : ""}${n.toFixed(2)}%`);
const wd = (d) => WD[(new Date(d + "T00:00:00").getDay() + 6) % 7];

function toast(msg, err = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
  clearTimeout(t._h); t._h = setTimeout(() => (t.className = "toast"), 2600);
}

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
  let data = null;
  try { data = await res.json(); } catch { /* CSV 등 */ }
  if (!res.ok) {
    let msg = `요청 실패 (${res.status})`;
    if (data?.detail) msg = Array.isArray(data.detail) ? data.detail.map((d) => d.msg.replace(/^Value error, /, "")).join(", ") : data.detail;
    throw new Error(msg);
  }
  return data;
}

// ── 탭 ─────────────────────────────────────────────
$$(".tab").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
function showTab(name) {
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  if (name === "dashboard") loadDashboard();
  if (name === "records") loadRecords();
  if (name === "history") loadHistory();
  if (name === "chat") loadSummary();
}

// ── 상태 / 요약 ─────────────────────────────────────
async function loadHealth() {
  const h = await api("/api/health");
  UNIT = h.unit;
  $("#dataLabel").textContent = `${h.data_label} · 기록 ${fmt(h.records)}건`;
  const pill = $("#llmStatus");
  if (h.llm_configured) { pill.textContent = `AI 키 설정됨 · ${h.api_style} · ${h.model}`; pill.className = "status-pill ok"; }
  else { pill.textContent = "AI 키 미설정 · 데이터 요약 모드"; pill.className = "status-pill warn"; }
}
async function loadSummary() {
  const s = await api("/api/analysis/latest");
  $("#summaryText").textContent = s ? s.summary_text : "분석 결과가 없습니다.";
  $("#snapInfo").textContent = s ? `분석 #${s.id} · ${s.created_at.replace("T", " ")} · 계기: ${s.trigger} · 기록 ${fmt(s.record_count)}건` : "";
}

// ── ① AI 채팅 ──────────────────────────────────────
const SUGGEST = ["최근 30일 흐름을 요약해 줘", "2018년 4월 폭설 때 교통량은 얼마나 줄었어?", "어느 요일이 가장 붐벼?",
  "공휴일에는 교통량이 평소보다 얼마나 적어?", "2017년 12월은 다른 달과 비교해서 어땠어?", "이상치로 잡힌 날들은 왜 그런 것 같아?"];
SUGGEST.forEach((q) => {
  const c = document.createElement("button"); c.type = "button"; c.className = "chip"; c.textContent = q;
  c.onclick = () => { $("#question").value = q; updateCount(); sendQuestion(); };
  $("#suggest").appendChild(c);
});
const updateCount = () => ($("#qCount").textContent = `${$("#question").value.length} / 500`);
$("#question").addEventListener("input", updateCount);
$("#question").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendQuestion(); }
});
$("#chatForm").addEventListener("submit", (e) => { e.preventDefault(); sendQuestion(); });

function addMsg(role, html, cls = "") {
  const m = document.createElement("div"); m.className = `msg ${role} ${cls}`;
  m.innerHTML = `<div class="bubble">${html}</div>`;
  $("#messages").appendChild(m); $("#messages").scrollTop = $("#messages").scrollHeight;
  return m;
}
function renderAnswer(el, r) {
  el.className = `msg assistant ${r.mode === "fallback" ? "fallback" : ""}`;
  el.innerHTML = `<div class="bubble">${mdLite(r.answer)}</div>
    <div class="meta"><span class="badge ${r.mode === "fallback" ? "fallback" : ""}">${r.mode === "ai" ? "AI 답변" : "데이터 요약 답변"}</span>
      ${r.model ? `<span>${escapeHtml(r.model)}</span>` : ""}${r.latency_ms ? `<span>${(r.latency_ms / 1000).toFixed(1)}초</span>` : ""}
      <span>${escapeHtml(r.created_at.replace("T", " "))}</span></div>
    <details class="ctx"><summary>근거 보기 — AI에게 보낸 데이터</summary><pre>${escapeHtml(r.context)}</pre></details>`;
  $("#messages").scrollTop = $("#messages").scrollHeight;
}

let busy = false;
async function sendQuestion() {
  const q = $("#question").value.trim();
  if (!q || busy) return;
  busy = true; $("#sendBtn").disabled = true; $("#question").disabled = true;
  addMsg("user", escapeHtml(q));
  $("#question").value = ""; updateCount();
  // 로딩 표시: 점 애니메이션 + 경과 시간
  const loading = addMsg("assistant", `<span class="dots"><span></span><span></span><span></span></span> <span>데이터를 살펴보고 답변을 만드는 중… <b class="elapsed">0</b>초</span>`, "loading");
  const t0 = Date.now();
  const timer = setInterval(() => { const e = loading.querySelector(".elapsed"); if (e) e.textContent = Math.floor((Date.now() - t0) / 1000); }, 500);
  $("#sendBtn").textContent = "답변 중…";
  try {
    const r = await api("/api/chat", { method: "POST", body: JSON.stringify({ question: q }) });
    renderAnswer(loading, r);
  } catch (e) {
    loading.className = "msg assistant fallback";
    loading.innerHTML = `<div class="bubble">⚠️ ${escapeHtml(e.message)}</div>`;
  } finally {
    clearInterval(timer); busy = false;
    $("#sendBtn").disabled = false; $("#question").disabled = false; $("#sendBtn").textContent = "보내기"; $("#question").focus();
  }
}

// ── ② 분석 대시보드 ────────────────────────────────
let range = { start: null, end: null };
$$("#rangeSeg button").forEach((b) => b.addEventListener("click", () => {
  $$("#rangeSeg button").forEach((x) => x.classList.toggle("active", x === b));
  range = b.dataset.range === "all" ? { start: null, end: null } : { days: Number(b.dataset.range) };
  $("#dStart").value = ""; $("#dEnd").value = "";
  loadDashboard();
}));
$("#applyRange").onclick = () => {
  $$("#rangeSeg button").forEach((x) => x.classList.remove("active"));
  range = { start: $("#dStart").value || null, end: $("#dEnd").value || null }; loadDashboard();
};
$("#refreshAnalysis").onclick = async () => {
  const s = await api("/api/analysis/refresh", { method: "POST" });
  toast(`분석을 다시 실행해 결과 #${s.id}를 저장했습니다`); loadDashboard();
};

function kpi(label, value, note = "", cls = "") {
  return `<div class="kpi"><div class="label">${label}</div><div class="value ${cls}">${value}</div><div class="note">${note}</div></div>`;
}
function makeChart(id, cfg) { if (charts[id]) charts[id].destroy(); charts[id] = new Chart($(id), cfg); }

async function loadDashboard() {
  if (typeof Chart === "undefined") { toast("차트 라이브러리를 불러오지 못했습니다 (인터넷 연결 확인)", true); }
  const snap = await api("/api/analysis/latest");
  const sm = snap.summary;
  const ser = (await api("/api/series")).items;
  let items = ser;
  if (range.days) {
    const last = new Date(sm.end + "T00:00:00"); last.setDate(last.getDate() - range.days + 1);
    const from = last.toISOString().slice(0, 10); items = ser.filter((r) => r.date >= from);
  } else if (range.start || range.end) {
    items = ser.filter((r) => (!range.start || r.date >= range.start) && (!range.end || r.date <= range.end));
  }
  const vals = items.map((r) => r.value);
  const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  const ch = sm.change_30d_pct, t = sm.trend_90d;
  $("#kpis").innerHTML =
    kpi("기록 수 · 기간", `${fmt(sm.count)}건`, `${sm.start} ~ ${sm.end}`) +
    kpi("선택 기간 평균", `${fmt(avg)}${UNIT}`, `${items.length}건 · ${items[0]?.date ?? "-"} ~ ${items.at(-1)?.date ?? "-"}`) +
    kpi("최근 30일 평균", `${fmt(sm.last30_avg)}${UNIT}`, `직전 30일 대비 <b class="${ch > 0 ? "up" : "down"}">${pct(ch)}</b>`) +
    kpi("최근 90일 추세", t ? t.direction : "–", t ? `한 달 환산 ${pct(t.per_month_pct)}` : "") +
    kpi("최고 / 최저", `${fmt(sm.max.value)} / ${fmt(sm.min.value)}`, `${sm.max.date} / ${sm.min.date}`);

  if (typeof Chart !== "undefined") {
    const memoPts = items.map((r) => (r.memo ? r.value : null));
    makeChart("#lineChart", { type: "line",
      data: { labels: items.map((r) => r.date), datasets: [
        { label: "일별 값", data: vals, borderColor: "#c9cdd3", borderWidth: 1, pointRadius: 0, tension: 0 },
        { label: "7일 이동평균", data: items.map((r) => r.ma7), borderColor: "#2a78d6", borderWidth: 1.8, pointRadius: 0 },
        { label: "30일 이동평균", data: items.map((r) => r.ma30), borderColor: "#eb6834", borderWidth: 2.4, pointRadius: 0 },
        { label: "메모 있는 날", data: memoPts, showLine: false, pointRadius: 4, pointBackgroundColor: "#1baf7a", borderColor: "#1baf7a" }] },
      options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, spanGaps: false,
        plugins: { tooltip: { callbacks: { afterBody: (ctx) => { const r = items[ctx[0].dataIndex]; return r.memo ? `메모: ${r.memo}` : ""; } } } },
        scales: { x: { ticks: { maxTicksLimit: 12 } }, y: { ticks: { callback: (v) => fmt(v) } } } } });
    makeChart("#monthChart", { type: "bar",
      data: { labels: sm.monthly.map((m) => m.month), datasets: [{ label: "월평균", data: sm.monthly.map((m) => m.avg), backgroundColor: "#2a78d6", borderRadius: 4 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { callback: (v) => fmt(v) } } } } });
    const wk = Object.entries(sm.weekday_avg);
    makeChart("#weekChart", { type: "bar",
      data: { labels: wk.map((w) => w[0]), datasets: [{ label: "요일 평균", data: wk.map((w) => w[1]),
        backgroundColor: wk.map((w) => (w[0] === sm.weekday_high ? "#eb6834" : w[0] === sm.weekday_low ? "#8a8f98" : "#2a78d6")), borderRadius: 4 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { callback: (v) => fmt(v) } } } } });
  }
  $("#anomalyBody").innerHTML = sm.anomalies.length ? sm.anomalies.map((a) =>
    `<tr><td>${a.date} (${wd(a.date)})</td><td class="num">${fmt(a.value)}</td><td class="num">${a.z.toFixed(1)}</td><td>${escapeHtml(a.memo)}</td></tr>`).join("")
    : `<tr><td colspan="4" class="empty">이상치 없음</td></tr>`;
  const hist = (await api("/api/analysis/history?limit=8")).items;
  $("#snapBody").innerHTML = hist.map((h) => `<tr><td>${h.id}</td><td>${h.created_at.replace("T", " ")}</td><td>${escapeHtml(h.trigger)}</td><td class="num">${fmt(h.record_count)}</td></tr>`).join("");
}

// ── ③ 데이터 관리 (CRUD) ───────────────────────────
let page = 1, pages = 1, filter = {};
const recCache = new Map();   // 현재 페이지 기록 (수정·삭제 버튼용)
async function loadRecords() {
  const p = new URLSearchParams({ page, size: 20, ...Object.fromEntries(Object.entries(filter).filter(([, v]) => v)) });
  const r = await api(`/api/records?${p}`);
  pages = r.pages;
  $("#recordBody").innerHTML = r.items.length ? r.items.map((x) => `
    <tr data-id="${x.id}"><td>${x.date}</td><td>${wd(x.date)}</td><td class="num">${fmt(x.value)}</td><td>${escapeHtml(x.memo)}</td>
      <td><button class="btn sm" data-edit="${x.id}">수정</button> <button class="btn sm danger" data-del="${x.id}">삭제</button></td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">조건에 맞는 데이터가 없습니다</td></tr>`;
  $("#pageInfo").textContent = `${r.page} / ${r.pages} 페이지 · 총 ${fmt(r.total)}건`;
  $("#prevPage").disabled = page <= 1; $("#nextPage").disabled = page >= pages;
  recCache.clear(); r.items.forEach((x) => recCache.set(String(x.id), x));
}
$("#prevPage").onclick = () => { if (page > 1) { page--; loadRecords(); } };
$("#nextPage").onclick = () => { if (page < pages) { page++; loadRecords(); } };
$("#rSearch").onclick = () => { filter = { start: $("#rStart").value, end: $("#rEnd").value, q: $("#rQ").value.trim() }; page = 1; loadRecords(); };
$("#rReset").onclick = () => { $("#rStart").value = $("#rEnd").value = $("#rQ").value = ""; filter = {}; page = 1; loadRecords(); };

function setForm(rec) {
  $("#rid").value = rec?.id ?? ""; $("#fDate").value = rec?.date ?? ""; $("#fValue").value = rec?.value ?? ""; $("#fMemo").value = rec?.memo ?? "";
  $("#formTitle").textContent = rec ? `데이터 수정 — ${rec.date}` : "새 데이터 추가";
  $("#saveBtn").textContent = rec ? "수정 저장" : "추가"; $("#cancelEdit").hidden = !rec;
  $$("#recordBody tr").forEach((tr) => tr.classList.toggle("editing", rec && tr.dataset.id == rec.id));
  $("#formMsg").textContent = ""; $("#formMsg").className = "form-msg";
}
$("#cancelEdit").onclick = () => setForm(null);
$("#recordBody").addEventListener("click", async (e) => {
  const id = e.target.dataset.edit || e.target.dataset.del;
  if (!id) return;
  if (e.target.dataset.edit) { setForm(recCache.get(id)); $("#fValue").focus(); window.scrollTo({ top: 0, behavior: "smooth" }); return; }
  const rec = recCache.get(id);
  if (!confirm(`${rec.date} (${fmt(rec.value)}) 기록을 삭제할까요?`)) return;
  try {
    const r = await api(`/api/records/${id}`, { method: "DELETE" });
    toast(`삭제했습니다 · 분석 결과 #${r.snapshot_id} 저장`); loadRecords(); loadHealth(); loadSummary();
  } catch (err) { toast(err.message, true); }
});
$("#recordForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = $("#rid").value;
  const body = { date: $("#fDate").value, value: Number($("#fValue").value), memo: $("#fMemo").value.trim() };
  const msg = $("#formMsg");
  if (!body.date || $("#fValue").value === "" || Number.isNaN(body.value)) { msg.textContent = "날짜와 값을 모두 입력하세요"; msg.className = "form-msg err"; return; }
  try {
    const r = await api(id ? `/api/records/${id}` : "/api/records", { method: id ? "PUT" : "POST", body: JSON.stringify(body) });
    toast(`${id ? "수정" : "추가"}했습니다 · 분석 결과 #${r.snapshot_id} 저장`);
    setForm(null); msg.textContent = `✔ ${r.date} ${fmt(r.value)} 저장됨 (분석 자동 갱신)`; msg.className = "form-msg ok";
    loadRecords(); loadHealth(); loadSummary();
  } catch (err) { msg.textContent = "⚠ " + err.message; msg.className = "form-msg err"; }
});

// ── ④ 대화 기록 ────────────────────────────────────
async function loadHistory() {
  const r = await api("/api/chat/history?size=50");
  $("#histInfo").textContent = `저장된 대화 ${fmt(r.total)}건 (최근 50건 표시)`;
  $("#historyList").innerHTML = r.items.length ? r.items.map((h) => `
    <div class="hist"><div class="row"><div class="meta"><span class="badge ${h.mode === "fallback" ? "fallback" : ""}">${h.mode === "ai" ? "AI 답변" : "데이터 요약 답변"}</span>
      <span>${h.created_at.replace("T", " ")}</span>${h.model ? `<span>${escapeHtml(h.model)}</span>` : ""}${h.error ? `<span>오류: ${escapeHtml(h.error)}</span>` : ""}</div>
      <button class="btn sm danger" data-hdel="${h.id}">삭제</button></div>
      <div class="q">Q. ${escapeHtml(h.question)}</div><div class="a">${mdLite(h.answer)}</div></div>`).join("")
    : `<div class="empty">아직 대화가 없습니다. AI 채팅 탭에서 질문해 보세요.</div>`;
}
$("#historyList").addEventListener("click", async (e) => {
  const id = e.target.dataset.hdel; if (!id) return;
  await api(`/api/chat/history/${id}`, { method: "DELETE" }); toast("대화를 삭제했습니다"); loadHistory();
});
$("#clearHistory").onclick = async () => {
  if (!confirm("저장된 대화를 모두 삭제할까요?")) return;
  const r = await api("/api/chat/history", { method: "DELETE" }); toast(`${r.deleted}건 삭제했습니다`); loadHistory();
};

// ── 시작 ───────────────────────────────────────────
loadHealth().catch((e) => toast(e.message, true));
loadSummary().catch((e) => toast(e.message, true));
