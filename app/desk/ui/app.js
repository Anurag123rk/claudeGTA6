"use strict";
// Vice Desk UI. Talks only to the local server (127.0.0.1). Nothing here blocks first paint:
// the page renders instantly and every network call is async with a timeout.
const T = window.DESK_TOKEN;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const AND = window.ViceAndroid || null; // bridge injected by the Android app
if (AND) document.body.classList.add("android");
const S = { tasks: [], status: null, jobs: [], selTask: null, watch: {}, prevStates: {}, net: [], findTab: "trends" };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function fmtBytes(n) { if (n == null || isNaN(n)) return "–"; const u = ["B", "KB", "MB", "GB"]; let i = 0; n = +n; while (n >= 1024 && i < 3) { n /= 1024; i++; } return (i ? n.toFixed(1) : n.toFixed(0)) + " " + u[i]; }
function fmtSpeed(n) { if (!n) return "0 KB/s"; return n >= 1048576 ? (n / 1048576).toFixed(2) + " MB/s" : (n / 1024).toFixed(0) + " KB/s"; }
function fmtDur(s) { if (s == null || !isFinite(s)) return "–"; s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}:${String(x).padStart(2, "0")}`; }
const fmtT = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const fileUrl = (p) => `/api/file?t=${encodeURIComponent(T)}&path=${encodeURIComponent(p)}`;

async function api(path, body, timeout = 15000) {
  const ctl = new AbortController(); const tm = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(path, { method: body ? "POST" : "GET", headers: { "X-Desk-Token": T, "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined, signal: ctl.signal });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
    return j;
  } finally { clearTimeout(tm); }
}
function toast(msg, ms = 4500) { const t = $("#toast"); t.innerHTML = msg; t.hidden = false; clearTimeout(toast.h); toast.h = setTimeout(() => (t.hidden = true), ms); }
const formData = (f) => Object.fromEntries(new FormData(f).entries());

// ---------------------------------------------------------------- navigation
function go(page) {
  $$("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.page === page));
  $$(".page").forEach((p) => p.classList.toggle("on", p.id === "page-" + page));
  if (page === "library") loadJobs();
  if (page === "settings") loadSettings();
  if (page === "monitor") renderMonitor();
  try { localStorage.setItem("vd-page", page); } catch (e) { /* storage may be blocked */ }
}
$$("#nav a").forEach((a) => a.addEventListener("click", () => go(a.dataset.page)));
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-goto]"); if (g) { e.preventDefault(); go(g.dataset.goto); }
  const ext = e.target.closest("a[data-ext]");
  if (ext) { e.preventDefault(); if (AND) AND.openUrl(ext.dataset.ext); else api("/api/open-url", { url: ext.dataset.ext }).catch((er) => toast(esc(er.message))); }
  const op = e.target.closest("[data-open]");
  if (op) { e.preventDefault(); if (AND) toast("Use Share or Save on a clip."); else api("/api/open", { path: op.dataset.open }).catch((er) => toast(esc(er.message))); }
  const sh = e.target.closest("[data-share]"); if (sh && AND) { e.preventDefault(); AND.shareFile(sh.dataset.share); }
  const sv = e.target.closest("[data-save]"); if (sv && AND) { e.preventDefault(); AND.saveToGallery(sv.dataset.save); }
  const pk = e.target.closest("[data-pick]"); if (pk && AND) { e.preventDefault(); S.pickTarget = pk.dataset.pick; AND.pickVideo(); }
  const pl = e.target.closest("[data-play]"); if (pl) { e.preventDefault(); play(pl.dataset.play, pl.dataset.name); }
});

window.onPickedVideo = (path) => {
  const f = $((S.pickTarget || "#pipeForm") + " [name=src]"); if (f) f.value = path;
  toast("Video ready: " + esc(path.split("/").pop()));
};
window.onAndroidMessage = (msg) => toast(esc(msg));
window.onSharedUrl = (url) => { go("pipeline"); $("#pipeForm [name=src]").value = url; toast("Link received. Tap <b>Run full pipeline</b>."); };
window.onAndroidBack = () => {
  const d = $("#player"); if (d.open) { $("#closePlayer").click(); return true; }
  if (!$("#page-dashboard").classList.contains("on")) { go("dashboard"); return true; }
  return false;
};

// ---------------------------------------------------------------- live monitor (SSE + polling fallback)
function connect() {
  const conn = $("#conn");
  let es;
  try { es = new EventSource(`/api/events?t=${encodeURIComponent(T)}`); } catch (e) { return poll(); }
  es.onopen = () => { conn.className = "conn ok"; conn.lastElementChild.textContent = "live"; };
  es.onmessage = (ev) => { try { onTasks(JSON.parse(ev.data).tasks); } catch (e) { /* ignore bad frame */ } };
  es.onerror = () => {
    conn.className = "conn bad"; conn.lastElementChild.textContent = "reconnecting…";
    if (es.readyState === 2) { setTimeout(connect, 2000); }
  };
}
async function poll() {
  try { onTasks((await api("/api/tasks")).tasks); $("#conn").className = "conn ok"; } catch (e) { $("#conn").className = "conn bad"; }
  setTimeout(poll, 1500);
}

function onTasks(tasks) {
  S.tasks = tasks;
  const running = tasks.filter((t) => t.state === "running" || t.state === "queued");
  $("#runCount").hidden = !running.length; $("#runCount").textContent = running.length;
  // network meter
  const sp = running.reduce((a, t) => a + ((t.download && t.download.speed) || 0), 0);
  S.net.push(sp); if (S.net.length > 80) S.net.shift();
  $("#netSpeed").textContent = sp ? fmtSpeed(sp) : "idle";
  spark($("#netSpark"), S.net, 160, 30);
  // finished-task hooks
  for (const t of tasks) {
    const prev = S.prevStates[t.id];
    if (prev && prev !== t.state && ["done", "failed", "cancelled"].includes(t.state)) onFinished(t);
    S.prevStates[t.id] = t.state;
  }
  renderDash(); renderWatched(); if ($("#page-monitor").classList.contains("on")) renderMonitor();
  document.title = running.length ? `(${Math.round((running[0].progress || 0) * 100)}%) Vice Desk` : "Vice Desk";
}

function spark(svg, data, w, h) {
  if (!svg) return;
  const max = Math.max(1, ...data);
  const pts = data.map((v, i) => `${(i / Math.max(1, data.length - 1)) * w},${h - (v / max) * (h - 3) - 1}`).join(" ");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.innerHTML = data.length > 1 ? `<polyline points="0,${h} ${pts} ${w},${h}" fill="#3ad1e622" stroke="none"/><polyline points="${pts}" fill="none" stroke="#3ad1e6" stroke-width="1.5"/>` : "";
}

function taskCard(t, opts = {}) {
  const pct = t.progress == null ? null : Math.round(t.progress * 100);
  const live = t.state === "running";
  const d = t.download;
  const showDl = d && (live ? (d.speed || d.bytes) : d.bytes);
  const stepTxt = t.step_n > 1 ? `Step ${Math.min(t.step_i + 1, t.step_n)}/${t.step_n} · ` : "";
  const stageTxt = t.stage ? `${t.stage_n ? `Stage ${t.stage_i}/${t.stage_n}: ` : ""}${t.stage}` : (live ? "Starting…" : "");
  let res = "";
  if (t.state === "done" && t.result) {
    const r = t.result, b = [];
    if (r.job) b.push(`<button class="sm" data-showjob="${esc(r.job)}">View candidates</button>`, `<button class="sm" data-open="${esc(r.job)}">Open folder</button>`);
    (r.clips || []).forEach((c) => b.push(`<button class="sm" data-play="${esc(c)}" data-name="${esc(c.split(/[\\/]/).pop())}">▶ ${esc(c.split(/[\\/]/).pop())}</button>`));
    (r.checks || []).forEach((c) => b.push(`<span class="badge ${c.pass ? "done" : "failed"}" title="${esc((c.lines || []).join("\n"))}">${c.pass ? "PASS" : "FAIL"} ${esc(c.clip.split(/[\\/]/).pop())}</span>`));
    if (r.file) b.push(`<button class="sm" data-showfind="${t.kind}">Show results</button>`);
    res = b.length ? `<div class="res">${b.join("")}</div>` : "";
  }
  return `<div class="task ${S.selTask === t.id ? "sel" : ""}" data-task="${t.id}">
    <div class="top"><span class="badge ${t.state}">${t.state}</span><span class="ttl" title="${esc(t.title)}">${esc(t.title)}</span>
      <span class="muted small">${fmtDur(t.elapsed)}</span>${live ? `<button class="sm danger" data-cancel="${t.id}">Stop</button>` : ""}</div>
    <div class="sub"><span>${esc(stepTxt + (t.step || ""))}</span><b>${pct == null ? (live ? "working…" : "") : pct + "%"}</b></div>
    <div class="bar ${pct == null && live ? "ind" : ""}"><i style="width:${pct == null ? (t.state === "done" ? 100 : 0) : pct}%"></i></div>
    ${stageTxt || t.detail ? `<div class="sub"><span>${esc(stageTxt)}</span><span>${esc(t.detail || "")}</span></div>` : ""}
    ${live && t.stage_frac != null && t.stage_n ? `<div class="bar thin"><i style="width:${Math.round(t.stage_frac * 100)}%"></i></div>` : ""}
    ${showDl ? `<div class="dl"><div><span>Speed</span><br><b>${fmtSpeed(live ? d.speed : 0)}</b></div>
      <div><span>Downloaded</span><br>${fmtBytes(d.bytes)}${d.total ? " / " + fmtBytes(d.total) : ""}</div>
      <div><span>ETA</span><br>${live && d.eta != null ? fmtDur(d.eta) : "–"}</div><div><span>Source</span><br>${esc(d.source || "")}</div>
      <svg data-spark="${t.id}"></svg></div>` : ""}
    ${t.error ? `<div class="err">${esc(t.error)}</div>` : ""}
    ${live && t.last && !opts.noLast ? `<div class="last">${esc(t.last)}</div>` : ""}
    ${res}</div>`;
}
function paintSparks(root) { $$("svg[data-spark]", root).forEach((s) => { const t = S.tasks.find((x) => x.id === s.dataset.spark); if (t) spark(s, t.speed_hist || [], 200, 26); }); }

document.addEventListener("click", async (e) => {
  const c = e.target.closest("[data-cancel]");
  if (c) { e.stopPropagation(); await api(`/api/tasks/${c.dataset.cancel}/cancel`, {}).catch((er) => toast(esc(er.message))); return; }
  const sj = e.target.closest("[data-showjob]");
  if (sj) { e.stopPropagation(); go("pipeline"); showJob(sj.dataset.showjob); return; }
  const sf = e.target.closest("[data-showfind]");
  if (sf) { e.stopPropagation(); go("find"); setFindTab(sf.dataset.showfind); loadFind(sf.dataset.showfind); return; }
  const tk = e.target.closest(".task[data-task]");
  if (tk && !e.target.closest("button")) { S.selTask = tk.dataset.task; go("monitor"); refreshLog(true); }
});

function renderDash() {
  const act = S.tasks.filter((t) => t.state === "running" || t.state === "queued");
  const recent = S.tasks.filter((t) => !act.includes(t)).slice(0, 3);
  const list = act.concat(recent).slice(0, 5);
  const el = $("#dashTasks");
  el.innerHTML = list.length ? list.map((t) => taskCard(t)).join("") : `<p class="muted">Nothing running. Start a pipeline above or find a video first.</p>`;
  paintSparks(el);
}
function watchTask(slot, id) { S.watch[slot] = id; renderWatched(); }
function renderWatched() {
  for (const [slot, id] of Object.entries(S.watch)) {
    const t = S.tasks.find((x) => x.id === id); const el = $("#" + slot);
    if (el) { el.innerHTML = t ? taskCard(t) : ""; paintSparks(el); }
  }
}
function renderMonitor() {
  const el = $("#allTasks");
  el.innerHTML = S.tasks.length ? S.tasks.map((t) => taskCard(t, { noLast: true })).join("") : `<p class="muted">No tasks yet.</p>`;
  paintSparks(el);
  if (S.selTask) refreshLog();
}
async function refreshLog(force) {
  if (!S.selTask) return;
  const now = Date.now(); if (!force && now - (refreshLog.t || 0) < 900) return; refreshLog.t = now;
  try {
    const t = await api(`/api/tasks/${S.selTask}`);
    $("#logTitle").textContent = t.title;
    const pre = $("#log"); pre.textContent = (t.log || []).join("\n") || "(no output yet)";
    if ($("#follow").checked) pre.scrollTop = pre.scrollHeight;
  } catch (e) { /* task may have been cleared */ }
}
$("#clearTasks").addEventListener("click", async () => { await api("/api/tasks/clear", {}); S.selTask = null; $("#log").textContent = "Select a task to see its live log."; });

function onFinished(t) {
  const msg = { done: "finished", failed: "failed", cancelled: "was stopped" }[t.state];
  toast(`<b>${esc(t.title)}</b> ${msg}${t.error ? "<br><span class='bad small'>" + esc(t.error) + "</span>" : ""}`);
  if (t.state === "done") {
    if (t.kind === "trends" || t.kind === "streams") loadFind(t.kind);
    if (t.result && t.result.job && ["moments", "pipeline", "cut"].includes(t.kind)) showJob(t.result.job);
    loadJobs(true);
  }
  if (t.kind === "install_ffmpeg") loadStatus();
  if (t.kind === "install_model") {
    $$("#modelCards button").forEach((b) => (b.disabled = false));
    if (t.state === "done") { $("#firstRun").hidden = true; toast(`Speech model <b>${esc(t.result.model)}</b> is ready. You're all set!`); go("dashboard"); }
    loadStatus();
  }
}

async function run(kind, params, slot) {
  try {
    const r = await api("/api/run", { kind, params });
    if (slot) watchTask(slot, r.id);
    toast(`Started: <b>${esc(kind)}</b>. Progress is shown live.`, 2500);
    return r.id;
  } catch (e) { toast(`<span class="bad">${esc(e.message)}</span>`, 7000); }
}

// ---------------------------------------------------------------- dashboard & setup
async function loadStatus() {
  try {
    const s = await api("/api/status", null, 8000); S.status = s;
    document.body.classList.toggle("android", !!s.android);
    $$("form").forEach((f) => { if (f.elements.layout) syncCam(f); });
    $("#ver").textContent = `v${s.version} · local`;
    $("#about").innerHTML = `Vice Desk ${esc(s.version)}. Runs the claudeGTA6 pipeline locally, with no login and no cloud backend. Tools folder: <span class="mono">${esc(s.bin)}</span>. You approve every post; nothing is uploaded.`;
    $("#wsLink").textContent = s.workspace; $("#wsLink").dataset.open = s.workspace;
    const names = { ffmpeg: "ffmpeg (video engine)", ffprobe: "ffprobe", "yt-dlp": "yt-dlp (downloader)", "faster-whisper": "faster-whisper (captions)", quickjs: "QuickJS (YouTube JS runtime)" };
    $("#toolList").innerHTML = Object.entries(s.tools).map(([k, v]) => `<li><span>${names[k] || k}<br><span class="muted small mono">${esc(v.path || "missing")}</span></span><span class="st ${v.ok ? "ok" : "bad"}">${v.ok ? "✓ ready" : "✗ missing"}</span></li>`).join("");
    renderModelCards(s); fillModelSelect(s);
    const modelBusy = S.tasks.some((x) => x.kind === "install_model" && x.state === "running");
    if (s.first_run || modelBusy) $("#firstRun").hidden = false;
    const b = $("#setupBanner");
    if (!s.tools.ffmpeg.ok || !s.tools.ffprobe.ok) {
      b.hidden = false;
      const why = esc((s.tools.ffmpeg.ok ? s.tools.ffprobe.path : s.tools.ffmpeg.path) || "");
      b.innerHTML = s.android
        ? `<span><b>The video engine can't start on this phone.</b> Please send a screenshot of the Setup card below to the developer.<br><span class="small mono">${why}</span></span>`
        : s.platform === "win32"
        ? `<span><b>ffmpeg is needed</b> to cut clips. One click downloads it (about 100 MB); you'll see the download speed live.</span><button class="primary" id="instFF">Install ffmpeg</button>`
        : `<span><b>ffmpeg is missing.</b> Install it with your package manager (<code>sudo apt install ffmpeg</code> / <code>brew install ffmpeg</code>), then restart.</span>`;
      const btn = $("#instFF"); if (btn) btn.onclick = () => run("install_ffmpeg", {});
    } else if (!s.android && !(s.installed_models || []).length) {
      b.hidden = false;
      b.innerHTML = `<span><b>No speech model yet.</b> Clips are cut without captions until you download one.</span><button class="primary" id="pickModel">Choose model</button>`;
      $("#pickModel").onclick = () => { $("#firstRun").hidden = false; };
    } else b.hidden = true;
  } catch (e) {
    $("#toolList").innerHTML = `<li class="bad">Could not reach the local engine: ${esc(e.message)}. <button class="sm" onclick="loadStatus()">Retry</button></li>`;
  }
}
function renderModelCards(st) {
  const inst = st.installed_models || [];
  $("#modelCards").innerHTML = st.models.map((m) => `<div class="model ${m.name === "small" ? "rec" : ""}">
    <b>${esc(m.name)}</b><span class="sz">${esc(m.size)} · ${esc(m.speed)}</span><p>${esc(m.quality)}</p>
    <button class="${m.name === "small" ? "primary" : ""}" data-model="${m.name}">${inst.includes(m.name) ? "Use (installed)" : "Download"}</button></div>`).join("");
}
function fillModelSelect(st) {
  const sel = $("#setForm [name=whisper_model]"); const inst = st.installed_models || [];
  sel.innerHTML = st.models.map((m) => `<option value="${m.name}">${m.name} · ${m.size} · ${inst.includes(m.name) ? "installed" : "not downloaded"}</option>`).join("");
  sel.value = st.settings.whisper_model;
}
async function chooseModel(name, slot) {
  const st = S.status || {};
  if ((st.installed_models || []).includes(name)) {
    await api("/api/settings", { whisper_model: name, model_choice_done: "1" });
    $("#firstRun").hidden = true; toast(`Using the <b>${esc(name)}</b> model.`); loadStatus(); return;
  }
  $$("#modelCards button").forEach((b) => (b.disabled = true));
  const id = await run("install_model", { model: name }, slot);
  if (!id) $$("#modelCards button").forEach((b) => (b.disabled = false));
}
document.addEventListener("click", (e) => { const b = e.target.closest("[data-model]"); if (b) chooseModel(b.dataset.model, "modelTask"); });
$("#skipModel").addEventListener("click", async (e) => { e.preventDefault(); await api("/api/settings", { model_choice_done: "1" }); $("#firstRun").hidden = true; loadStatus(); });
$("#dlModel").addEventListener("click", () => chooseModel($("#setForm [name=whisper_model]").value, "setModelTask"));

$("#quickForm").addEventListener("submit", (e) => { e.preventDefault(); run("pipeline", formData(e.target)); });
$("#openWs").addEventListener("click", () => api("/api/open", {}).catch((er) => toast(esc(er.message))));

// ---------------------------------------------------------------- find
function setFindTab(tab) {
  S.findTab = tab;
  $$("#findTabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  $$("#findForm [data-only]").forEach((el) => (el.hidden = el.dataset.only !== tab));
}
$$("#findTabs button").forEach((b) => b.addEventListener("click", () => { setFindTab(b.dataset.tab); loadFind(b.dataset.tab); }));
$("#findForm").addEventListener("submit", (e) => {
  e.preventDefault(); const d = formData(e.target); d.deep = e.target.elements.deep.checked ? "1" : ""; run(S.findTab, d, "findTask");
});

function parseMd(md) {
  const sections = []; let cur = { title: "", rows: [], head: null, notes: [] };
  for (const line of md.split(/\r?\n/)) {
    if (/^#{1,3} /.test(line)) { if (cur.head || cur.notes.length || cur.title) sections.push(cur); cur = { title: line.replace(/^#+ /, ""), rows: [], head: null, notes: [] }; continue; }
    if (line.startsWith("|")) {
      const cells = line.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      if (cells.every((c) => /^-+$/.test(c))) continue;
      if (!cur.head) cur.head = cells; else cur.rows.push(cells);
    } else if (line.trim()) cur.notes.push(line.trim());
  }
  sections.push(cur); return sections;
}
function cellHtml(c) {
  const m = c.match(/^\[(.*)\]\((https?:[^)]+)\)$/);
  if (m) return `<a data-ext="${esc(m[2])}" href="#">${esc(m[1])}</a>`;
  if (/^https?:\/\//.test(c)) return `<a data-ext="${esc(c)}" href="#">${esc(c.replace(/^https?:\/\/(www\.)?/, ""))}</a>`;
  return esc(c);
}
async function loadFind(kind) {
  const name = kind === "streams" ? "streams.md" : "trends.md";
  const box = $("#findResults");
  try {
    const r = await api(`/api/text?name=${name}`);
    if (!r.text) { box.innerHTML = `<p class="muted">No ${kind} results yet. Run a search.</p>`; return; }
    const secs = parseMd(r.text);
    box.innerHTML = `<p class="muted small">Last run: ${new Date(r.mtime * 1000).toLocaleString()}</p>` + secs.map((s) => {
      if (!s.head) return s.title || s.notes.length ? `<h2>${esc(s.title)}</h2>${s.notes.map((n) => `<p class="muted">${esc(n)}</p>`).join("")}` : "";
      const urlCol = (row) => { for (const c of row) { const m = c.match(/\((https?:[^)]+)\)$/) || c.match(/^(https?:\/\/\S+)$/); if (m) return m[1]; } return ""; };
      return `<h2>${esc(s.title)}</h2>${s.notes.map((n) => `<p class="muted small">${esc(n)}</p>`).join("")}<div style="overflow:auto"><table><thead><tr>${s.head.map((h) => `<th>${esc(h)}</th>`).join("")}<th></th></tr></thead><tbody>${s.rows.map((row) => {
        const u = urlCol(row);
        const btns = u ? (kind === "streams"
          ? `<button class="sm primary" data-live="${esc(u)}">Record live</button>`
          : `<button class="sm primary" data-clip="${esc(u)}" data-title="${esc(row.find((c) => /\]\(https?:/.test(c)) || "")}">Clip it</button>`) : "";
        return `<tr>${row.map((c) => `<td class="${/^[\d,.]+$/.test(c) ? "num" : ""}">${cellHtml(c)}</td>`).join("")}<td class="acts">${btns}</td></tr>`;
      }).join("")}</tbody></table></div>`;
    }).join("");
  } catch (e) { box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
}
document.addEventListener("click", (e) => {
  const c = e.target.closest("[data-clip]"); if (c) openClipDialog(c.dataset.clip, c.dataset.title);
  const l = e.target.closest("[data-live]"); if (l) { go("live"); $("#liveForm [name=url]").value = l.dataset.live; }
});

// ---------------------------------------------------------------- layout / platform / webcam options
function syncCam(form) {
  const lay = form.elements.layout ? form.elements.layout.value : "blur";
  const vertical = !form.elements.platform || form.elements.platform.value === "vertical";
  const camLabel = form.querySelector(".cam-only");
  if (camLabel) camLabel.hidden = !(["facecam", "react"].includes(lay) && vertical);
  const cam = form.elements.cam;  // phones cannot auto-detect the webcam (no OpenCV): default to a corner
  if (cam && (AND || (S.status && S.status.android)) && cam.value === "auto") cam.value = "top-right";
}
$$("form").forEach((f) => { if (f.elements.layout) { f.addEventListener("change", () => syncCam(f)); syncCam(f); } });

const CLIP_KEYS = ["clips", "layout", "platform", "cam", "captions", "punch", "clean_audio", "fps60"];
function openClipDialog(url, titleCell) {
  const f = $("#clipForm"); f.reset();
  let saved = {}; try { saved = JSON.parse(localStorage.getItem("vd-clipopts") || "{}"); } catch (e) { /* storage blocked */ }
  for (const k of CLIP_KEYS) {
    const el = f.elements[k]; if (!el || saved[k] === undefined) continue;
    if (el.type === "checkbox") el.checked = !!saved[k]; else el.value = saved[k];
  }
  f.elements.src.value = url;
  const m = (titleCell || "").match(/^\[(.*)\]\(/); $("#clipTitle").textContent = m ? m[1] : url;
  syncCam(f); $("#clipDialog").showModal();
}
$("#clipForm").addEventListener("submit", (e) => {
  e.preventDefault(); const f = e.target; const d = formData(f);
  const keep = {}; for (const k of CLIP_KEYS) { const el = f.elements[k]; if (el) keep[k] = el.type === "checkbox" ? el.checked : el.value; }
  try { localStorage.setItem("vd-clipopts", JSON.stringify(keep)); } catch (er) { /* storage blocked */ }
  $("#clipDialog").close(); go("pipeline"); run("pipeline", d, "pipeTask");
});
$("#clipClose").addEventListener("click", () => $("#clipDialog").close());
$("#clipMore").addEventListener("click", () => {  // hand over to the full Pipeline form (moments, lengths, caption check)
  const f = $("#clipForm"), p = $("#pipeForm");
  for (const k of ["src", "layout", "platform", "cam", "captions", "hook", "clips"]) if (p.elements[k] && f.elements[k]) p.elements[k].value = f.elements[k].value;
  for (const k of ["punch", "clean_audio", "fps60"]) if (p.elements[k] && f.elements[k]) p.elements[k].checked = f.elements[k].checked;
  syncCam(p); $("#clipDialog").close(); go("pipeline"); p.elements.src.focus();
});

// ---------------------------------------------------------------- pipeline
$("#pipeForm").addEventListener("submit", (e) => { e.preventDefault(); run("pipeline", formData(e.target), "pipeTask"); });
$("#momentsOnly").addEventListener("click", () => { const f = $("#pipeForm"); if (!f.reportValidity()) return; run("moments", formData(f), "pipeTask"); });

function candRow(job, c) {
  return `<div class="cand"><div class="n">${c.n}</div>
    <div><b>${fmtT(c.start)}–${fmtT(c.end)}</b><br><span class="muted small">${Math.round(c.end - c.start)}s · score ${c.score}</span></div>
    <div>${(c.why || []).map((w) => `<span class="tag">${esc(w)}</span>`).join("")}${c.text ? `<q>${esc(c.text)}</q>` : ""}</div>
    <div class="acts"><select class="sm" data-layout="${c.n}"><option value="blur">blur</option><option value="fill">fill</option><option value="facecam">facecam</option><option value="react">react</option></select>
      <button class="sm primary" data-cut="${c.n}" data-job="${esc(job)}">Cut</button></div></div>`;
}
async function showJob(dir) {
  const jobs = await loadJobs(true); const j = jobs.find((x) => x.dir === dir);
  const box = $("#pipeJob");
  if (!j) { box.innerHTML = `<p class="muted">Job not found: ${esc(dir)}</p>`; return; }
  box.innerHTML = `<div class="card-h"><h2>${esc(j.title)}</h2><button class="sm" data-open="${esc(j.dir)}">Open folder</button></div>
    ${j.candidates.length ? j.candidates.map((c) => candRow(j.dir, c)).join("") : `<p class="muted">No candidates.</p>`}
    ${j.clips.length ? `<h2 style="margin-top:14px">Clips</h2><div class="clipgrid">${j.clips.map(clipCard).join("")}</div>` : ""}`;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-cut]"); if (!b) return;
  const lay = b.parentElement.querySelector("select");
  const f = formData($("#pipeForm"));
  run("cut", { job: b.dataset.job, pick: b.dataset.cut, layout: lay ? lay.value : "blur", hook: f.hook, captions: f.captions, caption: f.caption,
    punch: f.punch, clean_audio: f.clean_audio, fps60: f.fps60, platform: f.platform, cam: f.cam }, "pipeTask");
});

// ---------------------------------------------------------------- live
$("#liveForm").addEventListener("submit", (e) => { e.preventDefault(); run("live", formData(e.target), "liveTask"); });

// ---------------------------------------------------------------- library
function clipCard(c) {
  return `<div class="clip"><video preload="metadata" muted src="${fileUrl(c.file)}#t=0.5" data-play="${esc(c.file)}" data-name="${esc(c.name)}"></video>
    <div class="ci"><b>${esc(c.name)}</b><span class="muted">${fmtBytes(c.size)}${c.layout ? " · " + esc(c.layout) : ""}</span>${c.hook ? `<br>${esc(c.hook)}` : ""}
    <div class="acts" style="margin-top:6px;flex-wrap:wrap"><button class="sm" data-check="${esc(c.file)}">Check</button>${AND
      ? `<button class="sm primary" data-share="${esc(c.file)}">Share</button><button class="sm" data-save="${esc(c.file)}">Save</button>`
      : `<button class="sm" data-open="${esc(c.file)}">Open</button>`}</div></div></div>`;
}
async function loadJobs(quiet) {
  try {
    const r = await api("/api/jobs"); S.jobs = r.jobs;
    const box = $("#jobs");
    box.innerHTML = r.jobs.length ? r.jobs.map((j, i) => `<details class="job" ${i === 0 ? "open" : ""}><summary><span class="jt">${esc(j.title)}</span>
        <span class="muted small">${j.candidates.length} moments · ${j.clips.length} clips${j.live.length ? " · " + j.live.length + " live spikes" : ""}</span>
        <span class="muted small">${new Date(j.mtime * 1000).toLocaleString()}</span></summary><div class="body">
        <div class="acts" style="margin-bottom:8px">${j.url ? `<a data-ext="${esc(j.url)}" href="#" class="small">${esc(j.url)}</a>` : ""} <button class="sm" data-open="${esc(j.dir)}">Open folder</button></div>
        ${j.candidates.map((c) => candRow(j.dir, c)).join("")}
        ${j.clips.length ? `<h2 style="margin-top:14px">Clips</h2><div class="clipgrid">${j.clips.map(clipCard).join("")}</div>` : ""}
        ${j.live.length ? `<h2 style="margin-top:14px">Live spikes</h2><div class="clipgrid">${j.live.map(clipCard).join("")}</div>` : ""}
        </div></details>`).join("") : `<p class="muted">No jobs yet. Run the pipeline on a video to fill your library.</p>`;
    const clips = r.jobs.flatMap((j) => j.clips).slice(0, 6);
    $("#dashClips").innerHTML = clips.length ? clips.map(clipCard).join("") : `<p class="muted">No clips yet.</p>`;
    return r.jobs;
  } catch (e) { if (!quiet) $("#jobs").innerHTML = `<p class="bad">${esc(e.message)}</p>`; return []; }
}
$("#refreshJobs").addEventListener("click", () => loadJobs());
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-check]"); if (!b) return;
  run("check", { clip: b.dataset.check, caption: $("#pipeForm [name=caption]").value }); go("monitor");
});
function play(file, name) {
  const d = $("#player"); $("#playerTitle").textContent = name || ""; const v = $("#video");
  v.src = fileUrl(file); d.showModal(); v.play().catch(() => {});
}
$("#closePlayer").addEventListener("click", () => { const v = $("#video"); v.pause(); v.removeAttribute("src"); v.load(); $("#player").close(); });

// ---------------------------------------------------------------- settings
async function loadSettings() {
  try {
    const s = await api("/api/status"); const f = $("#setForm");
    fillModelSelect(s);
    for (const [k, v] of Object.entries(s.settings)) if (f.elements[k] && k !== "twitch_token" && k !== "whisper_model") f.elements[k].value = v;
    f.elements.twitch_token.placeholder = s.settings.twitch_token ? "saved (leave empty to keep)" : "optional";
    const c = await api("/api/text?name=campaigns.md"); $("#campaigns").value = c.text;
  } catch (e) { toast(esc(e.message)); }
}
$("#setForm").addEventListener("submit", async (e) => {
  e.preventDefault(); const d = formData(e.target); if (!d.twitch_token) delete d.twitch_token;
  try { await api("/api/settings", d); toast("Settings saved."); loadStatus(); loadJobs(true); } catch (er) { toast(esc(er.message)); }
});
$("#saveCamp").addEventListener("click", async () => { await api("/api/campaigns", { text: $("#campaigns").value }); toast("Campaign rules saved."); });
$("#quitBtn").addEventListener("click", async () => { await api("/api/quit", {}).catch(() => {}); document.body.innerHTML = "<p style='padding:40px'>Vice Desk has stopped. You can close this window.</p>"; });

// ---------------------------------------------------------------- boot
setFindTab("trends");
connect(); loadStatus(); loadJobs(true); loadFind("trends");
setInterval(() => { if (S.selTask) refreshLog(); }, 1000);
try { const p = localStorage.getItem("vd-page"); if (p && $("#page-" + p)) go(p); } catch (e) { /* storage blocked */ }
