// JARVIS dashboard — barcha ma'lumotlar /api orqali backenddan keladi.
// Bo'lim almashgandan keyin tugagan async handlerlar yo'q elementga yozib xato bermasligi uchun — "bo'sh" element
const DETACHED = () => document.createElement("div");
const $ = (s, el = document) => el.querySelector(s) || DETACHED();
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (res.status === 401 && data.detail === "auth_required") {
    showLogin(data.pin_set);
    throw new Error("Kirish talab qilinadi");
  }
  if (!res.ok) throw new Error(data.detail || data || res.statusText);
  return data;
}

// ---------------- Kirish (PIN) ----------------
function showLogin(pinSet) {
  if (document.getElementById("login")) return;
  const el = document.createElement("div");
  el.id = "login";
  el.innerHTML = `<div class="card" style="max-width:380px;width:100%">
    <div class="brand" style="padding:0 0 10px">J.A.R.V.I.S<small>AI BRAIN</small></div>
    <h3>${pinSet ? "Kirish" : "Birinchi kirish: PIN o'rnating"}</h3>
    ${pinSet ? "" : '<p class="muted">PIN shu kompyuterda xeshlangan holda saqlanadi. Kamida 6 belgi; oson PIN qabul qilinmaydi.</p>'}
    <input id="pin1" type="password" placeholder="PIN" autocomplete="${pinSet ? "current-password" : "new-password"}" autofocus>
    ${pinSet ? "" : '<input id="pin2" type="password" placeholder="PIN (qayta)" autocomplete="new-password" style="margin-top:8px">'}
    <div class="row" style="margin-top:10px"><button id="pinok">${pinSet ? "Kirish" : "O'rnatish va kirish"}</button></div>
    <div id="pinmsg"></div><p class="muted">PIN unutilsa: kompyuterda <code>python scripts/reset_pin.py</code></p></div>`;
  document.body.appendChild(el);
  const go = async () => {
    const p1 = document.getElementById("pin1").value;
    if (!pinSet && p1 !== document.getElementById("pin2").value) { document.getElementById("pinmsg").innerHTML = '<span class="bad">PINlar mos emas</span>'; return; }
    const res = await fetch(pinSet ? "/api/auth/login" : "/api/auth/setup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pin: p1 }) });
    if (res.ok) { location.reload(); return; }
    const d = await res.json().catch(() => ({}));
    document.getElementById("pinmsg").innerHTML = `<span class="bad">${esc(d.detail || res.statusText)}</span>`;
  };
  document.getElementById("pinok").onclick = go;
  el.addEventListener("keydown", (e) => e.key === "Enter" && go());
}

async function logout() {
  await fetch("/api/auth/logout", { method: "POST" });
  location.reload();
}

const SECTIONS = [
  ["dashboard", "Brain Dashboard", renderDashboard],
  ["brain", "🧠 3D Brain Mode", (v) => renderBrainHub(v, "brain")],
  ["graph", "🌐 Graph Explorer Mode", (v) => renderBrainHub(v, "graph")],
  ["memx", "Memory Explorer", renderMemoryExplorer],
  ["neural", "Neural Activity", renderNeural],
  ["agentmap", "Agent Connections", (v) => renderBrainHub(v, "graph", ["agents", "tasks", "skills", "apis"])],
  ["projmap", "Projects Map", (v) => renderBrainHub(v, "graph", ["projects", "memories", "files", "decisions", "tasks"])],
  ["mission", "🎯 Mission Control", renderMissionControl],
  ["agentcmd", "🤝 Agent Command", renderAgentCommand],
  ["superbrain", "⚡ Super Brain Control", renderSuperBrain],
  ["aihub", "🤖 AI Provider Center", renderProviderCenter],
  ["smartrouter", "🚦 Smart AI Router", renderSmartRouter],
  ["models", "📚 Model Catalog", renderModelCatalog],
  ["memimport", "📥 Memory Import Center", renderMemoryImport],
  ["connections", "🔌 Universal Connection Center", renderConnections],
  ["chat", "AI Chat", renderChat],
  ["voice", "Voice", renderVoice],
  ["memory", "Memory", renderMemory],
  ["knowledge", "Bilim manbalari", renderKnowledge],
  ["decisions", "Qarorlar jurnali", renderDecisions],
  ["kg", "Knowledge Graph", renderKG],
  ["agents", "Agentlar", renderAgents],
  ["office", "Virtual AI Office", renderOffice],
  ["dag", "Vazifalar grafi", renderDag],
  ["router", "AI Router va xarajat", renderRouter],
  ["files", "Fayllar", renderFiles],
  ["computer", "Kompyuter boshqaruvi", renderComputer],
  ["research", "Internet tadqiqoti", renderResearch],
  ["browser", "Brauzer agenti", renderBrowser],
  ["studio", "Rasm va video", renderStudio],
  ["instagram", "Instagram", renderInstagram],
  ["telegram", "Telegram", renderTelegram],
  ["bi", "Business Intelligence", renderBI],
  ["pos", "POS ulanishi", renderPOS],
  ["docs", "Hujjatlar", renderDocs],
  ["approvals", "Tasdiqlashlar", renderApprovals],
  ["notifications", "Bildirishnomalar", renderNotifications],
  ["audit", "Audit jurnali", renderAudit],
  ["errors", "Xatolar", renderErrors],
  ["tests", "Testlar va yaxshilash", renderTests],
  ["diagnostics", "System Health (Diagnostika)", renderDiagnostics],
  ["sandbox", "Sandbox", renderSandbox],
  ["plugins", "Kengaytmalar", renderPlugins],
  ["backups", "Zaxira nusxalar", renderBackups],
  ["security", "Xavfsizlik", renderSecurity],
  ["policy", "Siyosat (Policy)", renderPolicy],
  ["settings", "Sozlamalar", renderSettings],
];
const PLANNED = new Set();

function buildMenu() {
  $("#menu").innerHTML = SECTIONS.map(([id, name]) =>
    `<a data-id="${id}">${name}${PLANNED.has(id) ? '<span class="tag">tez orada</span>' : ""}</a>`).join("");
  $("#menu").onclick = (e) => { const a = e.target.closest("a"); if (a && a.dataset.id) location.hash = a.dataset.id; };
  const theme = () => { try { return localStorage.getItem("theme") || "light"; } catch (er) { return "light"; } };
  const paint = () => { document.documentElement.dataset.theme = theme(); const t = document.getElementById("themetg"); if (t) t.textContent = theme() === "dark" ? "☀️ Och mavzu" : "🌙 Futuristik (qorong'i) mavzu"; };
  $("#menu").insertAdjacentHTML("beforeend", '<a id="themetg" style="margin-top:12px"></a>');
  document.getElementById("themetg").onclick = (e) => { e.stopPropagation(); try { localStorage.setItem("theme", theme() === "dark" ? "light" : "dark"); } catch (er) { /* */ } paint(); };
  paint();
  fetch("/api/auth/status").then((r) => r.json()).then((st) => {
    if (st.enabled && st.authenticated) $("#menu").insertAdjacentHTML("beforeend", '<a id="logout" style="margin-top:12px">⏻ Chiqish</a>');
    const lo = document.getElementById("logout"); if (lo) lo.onclick = (e) => { e.stopPropagation(); logout(); };
  }).catch(() => {});
}

let timer = null;
async function show() {
  clearInterval(timer);
  if (window.JARVIS_VIZ) window.JARVIS_VIZ.cleanup();      // 3D sahnalar va oqim tinglovchilarini bo'shatish
  const id = location.hash.slice(1) || "dashboard";
  const sec = SECTIONS.find((s) => s[0] === id) || SECTIONS[0];
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.id === sec[0]));
  $("#title").textContent = sec[1];
  try { await sec[2]($("#view")); attachGuide($("#view"), sec[0]); } catch (e) { $("#view").innerHTML = `<div class="card bad">Xato: ${esc(e.message)}</div>`; }
}

function planned(title, text) {
  return (v) => { v.innerHTML = `<div class="card"><h3>${esc(title)}</h3><p>${esc(text)}</p>
    <p class="warn">Bu modul hali yaratilmagan. Ishlayotgandek ko'rsatilmaydi.</p></div>`; };
}

const statusPill = (ok, yes, no) => `<span class="pill ${ok ? "ok" : "warn"}">${ok ? yes : no}</span>`;

async function renderDashboard(root) {
  root.innerHTML = '<div id="dashbrain"></div><div id="dashmain"></div>';
  const v = $("#dashmain");
  brainCompact($("#dashbrain"));
  let tick = 0;
  const draw = async () => {
    if (++tick % 3 === 0) brainCompact($("#dashbrain"));
    const s = await api("/api/status");
    const sys = s.system, active = s.agents.filter((a) => a.implemented);
    $("#mode").innerHTML = (s.unread_notifications ? `<a href="#notifications" class="pill warn" style="margin-right:6px">🔔 ${s.unread_notifications}</a>` : "") + (s.settings.read_only_mode ? statusPill(true, "Faqat o'qish rejimi") : statusPill(false, "", "O'zgartirish rejimi"));
    v.innerHTML = `<div class="grid">
      <div class="card"><h3>AI holati</h3><div class="big">${esc(s.ai.provider)}</div>${statusPill(s.ai.available, "ishlayapti", "mavjud emas")}<div class="muted">${esc(s.ai.note)}</div></div>
      <div class="card"><h3>Faol model</h3><div class="big">${esc(s.ai.model || "—")}</div></div>
      <div class="card"><h3>RAM</h3><div class="big">${sys.ram_used_percent}%</div><div class="muted">jami ${sys.ram_total_gb} GB · CPU ${sys.cpu_percent}%</div></div>
      <div class="card"><h3>Bo'sh disk</h3><div class="big">${sys.disk_free_gb} GB</div><div class="muted">${esc(sys.os)}</div></div>
      <div class="card"><h3>Agentlar</h3><div class="big">${active.length} / ${s.agents.length}</div><div class="muted">ishlaydigan / jami (qolgani rejada)</div></div>
      <div class="card"><h3>Kutilayotgan tasdiqlar</h3><div class="big ${s.pending_approvals ? "warn" : ""}">${s.pending_approvals}</div><a href="#approvals">ko'rish →</a></div>
      <div class="card"><h3>Joriy vazifalar</h3>${s.current_tasks.length ? s.current_tasks.map((t) => `<div>#${t.id} ${esc(t.title)}</div>`).join("") : '<span class="muted">yo\'q</span>'}</div>
      <div class="card"><h3>Ulanishlar</h3>${Object.entries(s.integrations).map(([k, val]) => `<div>${k}: <span class="muted">${esc(val)}</span></div>`).join("")}
        <div>vositalar: ${Object.entries(sys.tools).map(([k, ok]) => `<span class="${ok ? "ok" : "muted"}">${k}</span>`).join(" · ")}</div></div>
    </div>
    <div class="grid" style="margin-top:14px;grid-template-columns:1fr 1fr">
      <div class="card"><h3>Oxirgi amallar</h3>${table(s.recent_actions, ["ts", "agent", "action", "risk"])}</div>
      <div class="card"><h3>Oxirgi xatolar</h3>${s.recent_errors.length ? table(s.recent_errors, ["ts", "module", "message"]) : '<span class="ok">Xato yo\'q</span>'}</div>
    </div>`;
  };
  await draw();
  timer = setInterval(draw, 5000);
}

function table(rows, cols) {
  if (!rows.length) return '<span class="muted">Bo\'sh</span>';
  return `<table><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr>${rows.map((r) =>
    `<tr>${cols.map((c) => `<td>${esc(cell(r[c]))}</td>`).join("")}</tr>`).join("")}</table>`;
}

function cell(v) {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.map((x) => (typeof x === "object" ? JSON.stringify(x) : x)).join(", ");
  if (typeof v === "boolean") return v ? "ha" : "yo'q";
  return typeof v === "object" ? JSON.stringify(v) : v;
}

async function renderChat(v) {
  v.innerHTML = `<div class="chat" id="log"></div>
    <div class="row"><input id="msg" placeholder="Yozing… (masalan: yordam, eslab qol: ..., xotira: ..., holat)" autofocus><button id="send">Yuborish</button></div>`;
  const log = $("#log");
  const add = (role, text, usage) => { log.insertAdjacentHTML("beforeend", `<div class="msg ${role}">${esc(text)}${usage ? `<div class="fb" style="margin-top:6px">
      <button class="ghost" data-fb="${usage}" data-g="1" title="Yaxshi javob">👍</button> <button class="ghost" data-fb="${usage}" data-g="0" title="Yomon javob">👎</button></div>` : ""}</div>`); log.scrollTop = 1e9; };
  log.onclick = async (e) => { const d = e.target.dataset;
    if (d.paid) {      // foydalanuvchi shu savol uchun pullik modelni tugma bilan tasdiqladi
      e.target.disabled = true;
      try { const r = await api("/api/chat", { method: "POST", body: { text: d.paid, allow_paid: true } }); add("assistant", r.text, r.route && r.route.usage_id); }
      catch (er) { add("assistant", "Xato: " + er.message); }
      return;
    }
    if (!d.fb) return;
    try { await post("/api/ai/feedback", { usage_id: Number(d.fb), good: d.g === "1" }); e.target.parentElement.innerHTML = '<span class="muted">Rahmat — baho saqlandi</span>'; } catch (er) { alert(er.message); } };
  (await api("/api/chat/history?limit=40")).forEach((m) => add(m.role, m.content));
  const send = async () => {
    const t = $("#msg").value.trim(); if (!t) return;
    $("#msg").value = ""; add("user", t);
    try { const r = await api("/api/chat", { method: "POST", body: { text: t } }); add("assistant", r.text, r.route && r.route.usage_id);
      if (r.paid_confirm_needed) log.insertAdjacentHTML("beforeend", `<div class="msg assistant"><button data-paid="${esc(t)}">💳 Pullik (kuchliroq) model bilan qayta so'rash</button>
        <span class="small muted">Xarajat kunlik/oylik limit ichida hisoblanadi.</span></div>`); }
    catch (e) { add("assistant", "Xato: " + e.message); }
  };
  $("#send").onclick = send;
  $("#msg").onkeydown = (e) => { if (e.key === "Enter") send(); };   // false qaytarmaslik kerak — aks holda yozib bo'lmaydi
}

async function renderMemory(v) {
  v.innerHTML = `<div class="card"><div class="row">
      <input id="q" placeholder="Xotiradan qidirish"><select id="kind" style="width:180px"><option value="">barcha turlar</option>
      ${["long_term", "short_term", "project", "knowledge", "task", "preference", "decision"].map((k) => `<option>${k}</option>`).join("")}</select>
      <button id="find">Qidirish</button><a href="/api/memory/export" download="jarvis_memory.json"><button class="ghost">Eksport</button></a></div>
    <div class="row"><input id="new" placeholder="Yangi xotira (parol/token yozmang)"><input id="proj" placeholder="loyiha (ixtiyoriy)" style="width:180px"><button id="add">Qo'shish</button></div></div>
    <div class="card" id="list" style="margin-top:12px"></div>`;
  const load = async () => {
    const q = $("#q").value.trim(), kind = $("#kind").value;
    const rows = await api(q ? `/api/memory?q=${encodeURIComponent(q)}` : `/api/memory${kind ? "?kind=" + kind : ""}`);
    $("#list").innerHTML = rows.length ? `<table><tr><th>#</th><th>tur</th><th>mazmun</th><th>ma'lumot turi</th><th>manba</th><th>ishonch</th><th>holat</th><th></th></tr>${rows.map((r) =>
      `<tr><td>${r.id}</td><td>${esc(r.kind)}</td><td>${esc(r.content)}</td><td>${esc(memLabel(r))}</td><td>${esc(r.reference || r.source)}<br><span class="muted">${esc(r.observed_at || r.created_at)}</span></td><td>${r.confidence}</td>
      <td class="${r.status === "conflict" ? "warn" : ""}">${esc(r.status)}</td>
      <td><button class="ghost" data-edit="${r.id}">tahrir</button> <button class="danger" data-del="${r.id}">o'chir</button></td></tr>`).join("")}</table>` : '<span class="muted">Xotira bo\'sh</span>';
  };
  $("#find").onclick = load; $("#kind").onchange = load;
  $("#add").onclick = async () => {
    try { await api("/api/memory", { method: "POST", body: { content: $("#new").value, kind: $("#kind").value || "long_term", project: $("#proj").value || null } }); $("#new").value = ""; load(); }
    catch (e) { alert(e.message); }
  };
  $("#list").onclick = async (e) => {
    const d = e.target.dataset;
    if (d.del && confirm(`#${d.del} xotirani butunlay o'chirasizmi? Qaytarib bo'lmaydi.`)) { await api(`/api/memory/${d.del}`, { method: "DELETE" }); load(); }
    if (d.edit) { const t = prompt("Yangi matn:"); if (t) { try { await api(`/api/memory/${d.edit}`, { method: "PUT", body: { content: t } }); load(); } catch (er) { alert(er.message); } } }
  };
  load();
}

async function renderAgents(v) {
  const [agents, tasks] = await Promise.all([api("/api/agents"), api("/api/tasks?limit=30")]);
  v.innerHTML = `<div class="card"><h3>Agentga vazifa berish</h3>
    <div class="row"><select id="ag" style="width:220px">${agents.filter((a) => a.implemented).map((a) => `<option value="${a.key}">${esc(a.title)}</option>`).join("")}</select>
    <input id="tt" placeholder="Vazifa nomi"></div>
    <textarea id="pl" placeholder='Payload (JSON). Misollar: developer → {"code":"def f(:"}  · security → {"text":"..."} · file_analysis → {"op":"list"} · qa → {"run_tests":false}'>{}</textarea>
    <div class="row" style="margin-top:8px"><button id="go">Navbatga qo'yish</button></div></div>
    <div class="card" style="margin-top:12px"><h3>Planner: maqsad → bosqichlar</h3><div class="row"><input id="goal" placeholder="Masalan: testlarni tekshir keyin savdo hisobotini ko'rsat"><button id="mkplan">Reja tuzish</button></div><div id="plans"></div></div>
    <div class="card" style="margin-top:12px"><h3>Agentlar</h3>${table(agents, ["title", "role", "status", "permission", "tools", "last_error"])}</div>
    <div class="card" style="margin-top:12px"><h3>Vazifalar</h3>${table(tasks, ["id", "agent", "title", "status", "result", "error"])}</div>`;
  const drawPlans = async () => { const ps = await api("/api/plans");
    $("#plans").innerHTML = ps.slice(0, 8).map((p) => `<div style="margin-top:8px"><b>#${p.id}</b> ${esc(p.goal)} <span class="pill">${esc(p.status)}</span>
      ${["planned", "partial", "waiting_approval"].includes(p.status) ? `<button class="ghost" data-run="${p.id}">Bajarish</button>` : ""}
      <div class="muted">${p.steps.map((s) => `${s.n}. ${esc(s.text)} → ${s.agent} [${s.status}]`).join(" · ")}</div>${p.note ? `<div class="muted">ⓘ ${esc(p.note)}</div>` : ""}</div>`).join(""); };
  drawPlans();
  $("#mkplan").onclick = async () => { try { await api("/api/plans", { method: "POST", body: { text: $("#goal").value } }); drawPlans(); } catch (e) { alert(e.message); } };
  $("#plans").onclick = async (e) => { const id = e.target.dataset.run; if (id) { await api(`/api/plans/${id}/run`, { method: "POST" }); drawPlans(); } };
  $("#go").onclick = async () => {
    try { await api("/api/tasks", { method: "POST", body: { agent: $("#ag").value, title: $("#tt").value || "Vazifa", payload: JSON.parse($("#pl").value || "{}") } }); setTimeout(show, 400); }
    catch (e) { alert(e.message); }
  };
}

async function renderOffice(v) {
  const draw = async () => {
    const agents = await api("/api/agents");
    v.innerHTML = `<p class="muted">Har bir xona — haqiqiy agent. Yashil: bo'sh, ko'k: ishlayapti, qizil: xato, xira: hali yaratilmagan.</p>
    <div class="office">${agents.map((a) => `<div class="room ${a.status}"><span class="dot"></span><b>${esc(a.title)}</b>
      <div class="muted">${esc(a.role)}</div><div>holat: ${esc(a.status)} · ruxsat: ${a.permission}</div>
      ${a.current_task ? `<div>vazifa #${a.current_task}</div>` : ""}${a.last_error ? `<div class="bad">${esc(a.last_error)}</div>` : ""}</div>`).join("")}</div>`;
  };
  await draw(); timer = setInterval(draw, 3000);
}

async function renderFiles(v) {
  const path = new URLSearchParams(location.search).get("p");
  const data = await api("/api/files" + (path ? "?path=" + encodeURIComponent(path) : ""));
  const root = path || data.root[0];
  v.innerHTML = `<div class="card"><div class="muted">Ruxsat berilgan papkalar: ${data.root.map(esc).join(", ")}</div>
    <h3 style="margin-top:10px">${esc(root)}</h3>${data.items.length ? `<table>${data.items.map((i) =>
      `<tr><td>${i.dir ? "📁" : "📄"} ${esc(i.name)}</td><td class="muted">${i.size ?? ""}</td><td>${i.dir ? "" : `<button class="ghost" data-f="${esc(root + "/" + i.name)}">o'qish</button>`}</td></tr>`).join("")}</table>` : '<span class="muted">Papka bo\'sh. Tahlil qilinadigan fayllarni shu papkaga joylang.</span>'}</div>
    <div class="card" style="margin-top:12px" id="out"></div>`;
  v.onclick = async (e) => {
    const f = e.target.dataset.f; if (!f) return;
    try { const r = await api("/api/files/read?path=" + encodeURIComponent(f));
      $("#out").innerHTML = `<h3>${esc(r.kind)} · ${esc(JSON.stringify(r.analysis))}</h3>${r.has_secret ? '<div class="warnbox">Faylda maxfiy ma\'lumotga o\'xshash qiymat bor.</div>' : ""}<pre>${esc(r.text)}</pre>`;
    } catch (er) { $("#out").innerHTML = `<span class="bad">${esc(er.message)}</span>`; }
  };
}

async function renderComputer(v) {
  v.innerHTML = `<div class="warnbox">Buyruq darhol bajarilmaydi: avval xavf darajasi va tushuntirish ko'rsatiladi, so'ng "Tasdiqlashlar" bo'limida tasdiqlaysiz. Faqat o'qish rejimida faqat A darajali buyruqlar bajariladi.</div>
    <div class="card"><div class="row"><input id="cmd" placeholder="Masalan: dir   yoki   git status"><button id="p">Taklif qilish</button></div><div id="r"></div></div>
    <div class="card" style="margin-top:12px"><h3>Dasturni ochish</h3><div id="apps" class="muted">yuklanmoqda…</div>
      <div class="row" style="margin-top:8px"><select id="app" style="width:200px"></select><input id="appfile" placeholder="ochiladigan fayl (ixtiyoriy, ruxsat berilgan papkadan)"><button id="appgo">Tasdiq so'rash</button></div><div id="appr"></div>
      <p class="muted">Ro'yxat (app_allowlist) faqat data/settings.json orqali o'zgartiriladi. Har bir ochish — alohida tasdiq.</p></div>`;
  const apps = await api("/api/apps");
  $("#apps").innerHTML = Object.keys(apps).length ? Object.entries(apps).map(([k, v]) => `<code>${esc(k)}</code> → ${esc(v)}`).join("<br>") : "Ruxsat berilgan dastur yo'q";
  $("#app").innerHTML = Object.keys(apps).map((k) => `<option>${esc(k)}</option>`).join("");
  $("#appgo").onclick = async () => { try { const r = await api("/api/apps/propose", { method: "POST", body: { name: $("#app").value, file: $("#appfile").value || null } });
    $("#appr").innerHTML = `Tasdiq #${r.approval.id} yaratildi. <a href="#approvals">Tasdiqlashlar →</a> (tasdiqlagach, o'sha yerda «Ochish»)`; } catch (e) { $("#appr").innerHTML = `<span class="bad">${esc(e.message)}</span>`; } };
  $("#p").onclick = async () => {
    try { const r = await api("/api/computer/propose", { method: "POST", body: { command: $("#cmd").value } });
      $("#r").innerHTML = `<p>Xavf darajasi: <b>${r.risk}</b> — ${esc(r.explanation)}</p><p>Tasdiq #${r.approval.id}: ${esc(r.approval.status)}. <a href="#approvals">Tasdiqlashlar →</a></p>`;
    } catch (e) { $("#r").innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
  };
}

async function renderApprovals(v) {
  const rows = await api("/api/approvals");
  v.innerHTML = rows.length ? rows.map((a) => `<div class="card" style="margin-bottom:10px">
    <div class="row" style="justify-content:space-between"><b>#${a.id} ${esc(a.summary)}</b><span class="pill ${a.status === "pending" ? "warn" : a.status === "executed" ? "ok" : ""}">${esc(a.status)}</span></div>
    ${a.level === "E" ? '<div class="warnbox bad">OGOHLANTIRISH: qaytarib bo\'lmaydigan yoki o\'chiruvchi amal bo\'lishi mumkin.</div>' : ""}
    ${a.risk ? `<div class="row" style="flex-wrap:wrap"><span class="pill ${a.risk === "high" ? "bad" : a.risk === "medium" ? "warn" : "ok"}">xavf: ${esc(a.risk)}</span>
      <span>Ta'sir: <b>${esc(a.impact)}</b></span><span>Maqsad: ${esc(a.purpose)}</span>
      <span>Qaytarish: ${a.reversible ? '<span class="ok">mumkin</span>' : '<span class="bad">mumkin emas</span>'}</span></div>` : ""}
    <div class="muted">Daraja ${a.level}: ${esc(a.level_info)} · tizim: ${esc(a.target)} · akkaunt: ${esc(a.account || "—")} · so'ragan: ${esc(a.requested_by)} · ${esc(a.created_at)}</div>
    <pre>${esc(JSON.stringify(a.payload, null, 2))}</pre><div class="muted">versiya xeshi: ${a.payload_hash}</div>
    <div class="row" style="margin-top:8px">${a.status === "pending" ? `<button data-ok="${a.id}" data-h="${a.payload_hash}">Aynan shu versiyani tasdiqlash</button><button class="danger" data-no="${a.id}" data-h="${a.payload_hash}">Rad etish</button>` : ""}
    ${a.status === "approved" && a.action_type.startsWith("shell_") ? `<button data-run="${a.id}">Bajarish</button>` : ""}
    ${a.status === "approved" && a.action_type.startsWith("pos_") ? '<a href="#pos">POS bo\'limida kiritish →</a>' : ""}
    ${a.status === "approved" && a.action_type.startsWith("instagram") ? '<a href="#instagram">Instagram bo\'limida nashr →</a>' : ""}
    ${a.status === "approved" && a.action_type === "code_change" ? '<a href="#tests">Branch yaratish →</a>' : ""}
    ${a.status === "approved" && a.action_type === "plugin_enable" ? '<a href="#plugins">Kengaytmani yoqish →</a>' : ""}
    ${a.status === "approved" && a.action_type === "backup_restore" ? '<a href="#backups">Tiklashni bajarish →</a>' : ""}
    ${a.status === "approved" && a.action_type === "sandbox_unsafe_run" ? '<a href="#sandbox">Sandbox\'da ishga tushirish →</a>' : ""}
    ${a.status === "approved" && a.action_type === "app_launch" ? `<button data-app="${a.id}">Ochish</button>` : ""}
    ${a.status === "approved" && a.action_type === "phone_call" ? `<button class="danger" data-call="${a.id}">Qo'ng'iroq qilish (pullik)</button>` : ""}
    ${a.status === "approved" && a.action_type === "instagram_dm" ? '<a href="#instagram">Direct javobni yuborish →</a>' : ""}</div><pre id="o${a.id}" hidden></pre></div>`).join("")
    : '<div class="card muted">Tasdiq so\'rovlari yo\'q</div>';
  v.onclick = async (e) => {
    const d = e.target.dataset;
    try {
      if (d.ok || d.no) { await api(`/api/approvals/${d.ok || d.no}/decide`, { method: "POST", body: { approve: !!d.ok, confirm_hash: d.h } }); show(); }
      if (d.run) { const r = await api(`/api/approvals/${d.run}/execute`, { method: "POST" }); const o = $("#o" + d.run); o.hidden = false; o.textContent = `exit=${r.exit_code}\n${r.output}`; }
      if (d.app) { const r = await api(`/api/apps/launch/${d.app}`, { method: "POST" }); const o = $("#o" + d.app); o.hidden = false; o.textContent = `Ochildi: ${r.app} (pid ${r.pid})`; }
      if (d.call && confirm("Pullik qo'ng'iroq amalga oshiriladi. Davom etasizmi?")) { const r = await api(`/api/telephony/call/${d.call}`, { method: "POST" }); const o = $("#o" + d.call); o.hidden = false; o.textContent = JSON.stringify(r); }
    } catch (er) { alert(er.message); }
  };
}

async function renderAudit(v) {
  v.innerHTML = `<div class="card">${table(await api("/api/audit?limit=200"), ["ts", "agent", "action", "target", "risk", "approval_status", "result", "error_code", "verified"])}</div>`;
}
async function renderErrors(v) {
  const rows = await api("/api/errors");
  v.innerHTML = `<div class="card">${rows.length ? `<table><tr><th>vaqt</th><th>modul</th><th>xabar</th><th></th></tr>${rows.map((e) => `<tr><td>${esc(e.ts)}</td><td>${esc(e.module)}</td><td>${esc(e.message)}</td>
    <td><button class="ghost" data-sug="${e.id}">AI tuzatish taklifi</button></td></tr>`).join("")}</table>` : '<span class="ok">Xatolar yo\'q</span>'}<pre id="so" hidden></pre>
    <p class="muted">AI taklifi faqat patch loyihasi: u "Testlar va yaxshilash" bo'limida test qilinadi va tasdiqlanmaguncha qo'llanmaydi.</p></div>`;
  v.onclick = async (e) => { const id = e.target.dataset.sug; if (!id) return; const o = $("#so"); o.hidden = false; o.textContent = "AI'dan so'ralmoqda…";
    try { const r = await api("/api/improve/suggest", { method: "POST", body: { error_id: Number(id) } }); o.textContent = `Taklif #${r.id}: ${r.title}\n${r.next}\n\n${r.diff}`; }
    catch (er) { o.textContent = er.message; } };
}

async function renderHeal(box) {
  box.innerHTML = `<div class="card" style="margin-top:12px"><h3>Self-healing — o'zini tekshirish</h3>
    <p class="muted">Diagnostika → takrorlanuvchi xatolarni guruhlash → (ixtiyoriy) testlar alohida nusxada → (ixtiyoriy) AI tuzatish taklifi regressiya testi bilan.
    Hech narsa o'zi qo'llanmaydi. Taklif kvotasi: kuniga 3 ta.</p>
    <div class="row"><button id="hl">Tekshirish</button><button class="ghost" id="ht">Tekshirish + testlar</button><button class="ghost" id="hp">+ tuzatish taklifi (AI)</button></div><div id="ho"></div></div>`;
  const run = async (q) => { $("#ho").innerHTML = '<span class="muted">Bajarilmoqda…</span>'; try { const r = await post(`/api/selfheal/run?${q}`);
    $("#ho").innerHTML = `<div style="margin:8px 0">Umumiy holat: <b>${esc(r.overall)}</b> · takrorlanuvchi xatolar: <b>${r.recurring.length}</b> · qolgan taklif kvotasi: ${r.quota_left}</div>
      ${r.problems.length ? table(r.problems, ["name", "status", "detail"]) : '<div class="ok">Diagnostikada muammo yo\'q</div>'}
      ${r.error_groups.length ? `<h4>Xatolar (7 kun, imzo bo'yicha)</h4>${table(r.error_groups, ["module", "count", "recurring", "last_seen", "sample"])}` : ""}
      ${r.tests ? `<h4>Testlar (alohida nusxa)</h4><div>${r.tests.ran ? (r.tests.passed ? '<span class="ok">o\'tdi</span>' : '<span class="bad">yiqildi</span>') + " — " + esc(r.tests.summary) : esc(r.tests.note)}</div>` : ""}
      ${r.proposal ? `<h4>Tuzatish taklifi</h4><div>${r.proposal.created ? `#${r.proposal.created} ${esc(r.proposal.title)} ${r.proposal.has_regression_test ? '<span class="pill ok">regressiya testi bor</span>' : '<span class="pill warn">regressiya testi yo\'q</span>'}` : ""} <span class="muted">${esc(r.proposal.note)}</span></div>` : ""}
      <h4>Git holati</h4><pre>${esc(r.git.ok ? `${r.git.branch} @ ${r.git.head}\n${r.git.diff_stat || "saqlanmagan o'zgarish yo'q"}` : r.git.note)}</pre>
      ${r.rollback_plans.length ? `<h4>Qaytarish rejalari</h4>${table(r.rollback_plans, ["proposal", "title", "plan"])}` : ""}`;
    if (q.includes("propose")) renderImprove($("#imp")); } catch (e) { fail($("#ho"), e); } };
  $("#hl").onclick = () => run(""); $("#ht").onclick = () => run("tests=true"); $("#hp").onclick = () => run("tests=true&propose=true");
}

async function renderTests(v) {
  v.innerHTML = `<div class="card"><div class="row"><button id="h">Modullarni tekshirish</button><button id="t" class="ghost">pytest testlarini ishga tushirish</button></div><div id="r" class="muted">Natija shu yerda chiqadi.</div></div><div id="heal"></div><div id="rel"></div><div id="imp"></div>`;
  renderHeal($("#heal"));
  renderRelease($("#rel"));
  renderImprove($("#imp"));
  const run = async (full) => {
    $("#r").textContent = "Bajarilmoqda…";
    const t = await api("/api/tasks", { method: "POST", body: { agent: "qa", title: full ? "pytest" : "Health check", payload: { run_tests: full } } });
    let r; for (let i = 0; i < 300; i++) { r = await api("/api/tasks/" + t.id); if (["done", "failed"].includes(r.status)) break; await new Promise((s) => setTimeout(s, 1000)); }
    if (r.status === "failed") { $("#r").innerHTML = `<span class="bad">${esc(r.error)}</span>`; return; }
    const res = JSON.parse(r.result);
    $("#r").innerHTML = table(res.health, ["check", "ok", "note"]) + (res.tests ? `<h3 style="margin-top:12px" class="${res.tests.passed ? "ok" : "bad"}">${res.tests.passed ? "Barcha testlar o'tdi" : "Testlar muvaffaqiyatsiz"}</h3><pre>${esc(res.tests.summary)}</pre>` : "");
  };
  $("#h").onclick = () => run(false); $("#t").onclick = () => run(true);
}

async function renderRelease(el) {
  const r = await api("/api/release/last");
  const cls = { PASS: "ok", FAIL: "bad", INCOMPLETE: "warn" }[r.verdict] || "muted";
  el.innerHTML = `<div class="card" style="margin-top:12px"><h3>Release gate</h3>
    ${r.verdict ? `<div class="big ${cls}">${esc(r.verdict)}</div><div class="muted">${esc(r.finished_at)} · commit ${esc((r.git || {}).commit || "?")}${(r.git || {}).uncommitted_changes ? " (commit qilinmagan o'zgarishlar bor)" : ""}</div>
      ${r.reasons.length ? `<div class="warnbox">${r.reasons.map(esc).join("<br>")}</div>` : ""}
      ${table(Object.entries(r.tests.categories).map(([k, c]) => ({ toifa: k, ...c })), ["toifa", "passed", "failed", "skipped"])}
      ${table(r.checks, ["name", "status", "detail"])}${r.tests.failures.length ? "<h3>Muvaffaqiyatsiz testlar</h3>" + table(r.tests.failures, ["test", "message"]) : ""}`
      : `<p class="muted">${esc(r.note)}</p>`}
    <div class="row" style="margin-top:8px"><button class="ghost" id="rgrun">Release gate'ni ishga tushirish (bir necha daqiqa)</button></div>
    <p class="muted">INCOMPLETE — majburiy tekshiruv bajarilmagan; bu "tayyor" degani emas.</p></div>`;
  $("#rgrun").onclick = async () => { $("#rgrun").textContent = "Ishlamoqda…"; const t = await api("/api/release/run", { method: "POST" });
    for (let i = 0; i < 600; i++) { const x = await api("/api/tasks/" + t.id); if (["done", "failed"].includes(x.status)) break; await new Promise((s) => setTimeout(s, 2000)); }
    renderRelease(el); };
}

async function renderSecurity(v) {
  const s = await api("/api/settings");
  v.innerHTML = `<div class="grid"><div class="card"><h3>Joriy siyosat</h3>
    <div>Faqat o'qish rejimi: <b class="${s.read_only_mode ? "ok" : "warn"}">${s.read_only_mode ? "yoqilgan" : "o'chirilgan"}</b></div>
    <div>Tasdiq talab qilinadi: <b class="ok">${s.require_approval ? "ha" : "yo'q"}</b></div>
    <div>O'qish ruxsati: ${s.allowed_read_dirs.map(esc).join(", ")}</div><div>Yozish ruxsati: ${s.allowed_write_dirs.map(esc).join(", ")}</div>
    <p class="muted">Bu kalitlar (${s.locked_keys.join(", ")}) dashboard yoki JARVIS tomonidan o'zgartirilmaydi — faqat siz settings.json faylini qo'lda tahrirlab.</p></div>
    <div class="card"><h3>Dashboard PIN'ini almashtirish</h3><input id="pc1" type="password" placeholder="Joriy PIN"><input id="pc2" type="password" placeholder="Yangi PIN" style="margin-top:6px">
      <div class="row" style="margin-top:8px"><button class="ghost" id="pcgo">Almashtirish</button></div><div id="pcm" class="muted">Almashtirilgach, boshqa barcha sessiyalar bekor bo'ladi.</div></div>
    <div class="card"><h3>Matnni tekshirish</h3><textarea id="t" placeholder="Matn yoki buyruq"></textarea><div class="row" style="margin-top:8px"><button id="c">Tekshirish</button></div><pre id="r" hidden></pre></div></div>`;
  $("#pcgo").onclick = async () => { try { await api("/api/auth/change", { method: "POST", body: { current: $("#pc1").value, new: $("#pc2").value } });
    $("#pcm").innerHTML = '<span class="ok">PIN almashtirildi</span>'; } catch (e) { $("#pcm").innerHTML = `<span class="bad">${esc(e.message)}</span>`; } };
  $("#c").onclick = async () => {
    const t = await api("/api/tasks", { method: "POST", body: { agent: "security", title: "Matn tekshiruvi", payload: { text: $("#t").value, is_command: true } } });
    await new Promise((s) => setTimeout(s, 500));
    const r = await api("/api/tasks/" + t.id); $("#r").hidden = false; $("#r").textContent = r.result || r.error || r.status;
  };
}

async function renderSettings(v) {
  const [s, sys] = await Promise.all([api("/api/settings"), api("/api/system")]);
  v.innerHTML = `<div class="grid" style="grid-template-columns:1fr 1fr"><div class="card"><h3>AI provider</h3>
    <label>Provider</label><select id="pv"><option value="offline">offline (modelsiz)</option><option value="ollama">ollama (mahalliy)</option></select>
    <label>Ollama URL</label><input id="url" value="${esc(s.ollama_url)}"><label>Model</label><input id="model" value="${esc(s.ollama_model)}">
    <div class="row" style="margin-top:10px"><button id="save">Saqlash</button></div><div id="msg"></div>
    <p class="muted">Model avtomatik yuklab olinmaydi. O'rnatish: <code>ollama pull ${esc(sys.recommended_model)}</code> (o'zingiz, hajmini ko'rib).</p></div>
    <div class="card"><h3>Diagnostika</h3><pre>${esc(JSON.stringify({ os: sys.os, cpu: sys.cpu, cores: sys.cpu_cores, ram_gb: sys.ram_total_gb, disk_free_gb: sys.disk_free_gb, gpu: sys.gpu, tools: sys.tools }, null, 2))}</pre>
    <div>Tavsiya etilgan model: <b>${esc(sys.recommended_model)}</b></div></div></div>
    <div class="card" style="margin-top:12px"><h3>Integratsiyalar (maxfiy kalitlarsiz)</h3>
      <label><input type="checkbox" id="inet" style="width:auto" ${s.internet_enabled ? "checked" : ""}> Internet tadqiqotiga ruxsat</label><br>
      <label><input type="checkbox" id="vrec" style="width:auto" ${s.save_voice_recordings ? "checked" : ""}> Ovoz yozuvlarini saqlash</label><br>
      <label><input type="checkbox" id="tgn" style="width:auto" ${s.telegram_notify ? "checked" : ""}> Muhim bildirishnomalarni Telegram'ga yuborish</label>
      <label>Brauzer agentiga ruxsat berilgan domenlar (vergul bilan)</label><input id="doms" value="${esc(s.browser_allowed_domains.join(", "))}">
      <label>POS sayti manzili</label><input id="pos" value="${esc(s.pos_site)}" placeholder="https://...">
      <label>POS konnektori</label><select id="posc"><option value="file_export">file_export (lokal fayl, tayyor)</option><option value="api">api (REST — pastda sozlang)</option><option value="browser">browser (sozlanmagan)</option></select>
      <label>Kam qolgan mahsulot chegarasi (min_stock bo'lmasa)</label><input id="low" type="number" value="${s.low_stock_threshold}">
      <label>POS REST API sozlamasi (JSON, tokensiz — token: POS ulanishi bo'limidagi yo'riqnomada kiritiladi)</label><textarea id="posapi" style="min-height:70px">${esc(JSON.stringify(s.pos_api || {}, null, 1))}</textarea>
      <label>Rasm generatori (Stable Diffusion WebUI --api)</label><input id="sdurl" value="${esc(s.image_gen_url || "")}" placeholder="http://127.0.0.1:7860">
      <label>Vision modeli (Ollama)</label><input id="vism" value="${esc(s.vision_model || "")}" placeholder="moondream">
      <label><input type="checkbox" id="pai" style="width:auto" ${s.planner_use_ai ? "checked" : ""}> Planner AI bilan bosqichlarga ajratsin (AI mavjud bo'lsa)</label>
      <label>Dashboard sessiyasi (soat)</label><input id="sess" type="number" value="${s.session_hours}">
      <div class="row" style="margin-top:10px"><button id="save2">Saqlash</button></div><div id="msg2"></div>
      <p class="muted">Telegram ID'lari, o'qish/yozish papkalari va faqat-o'qish rejimi xavfsizlik uchun faqat data/settings.json orqali o'zgartiriladi.</p></div>
    <div class="card" style="margin-top:12px"><h3>Model katalogi (taxminiy talablar)</h3>${table(sys.model_catalog, ["name", "disk_gb", "ram_gb", "note"])}</div>`;
  $("#pv").value = s.ai_provider; $("#posc").value = s.pos_connector;
  $("#save2").onclick = async () => {
    try { await api("/api/settings", { method: "POST", body: { internet_enabled: $("#inet").checked, save_voice_recordings: $("#vrec").checked, telegram_notify: $("#tgn").checked,
      browser_allowed_domains: $("#doms").value.split(",").map((x) => x.trim()).filter(Boolean), pos_site: $("#pos").value.trim(), pos_connector: $("#posc").value, low_stock_threshold: Number($("#low").value),
      pos_api: JSON.parse($("#posapi").value || "{}"), image_gen_url: $("#sdurl").value.trim(), vision_model: $("#vism").value.trim(),
      planner_use_ai: $("#pai").checked, session_hours: Number($("#sess").value) } });
      $("#msg2").innerHTML = '<span class="ok">Saqlandi (audit jurnaliga yozildi)</span>'; } catch (e) { $("#msg2").innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
  };
  $("#save").onclick = async () => {
    try { await api("/api/settings", { method: "POST", body: { ai_provider: $("#pv").value, ollama_url: $("#url").value, ollama_model: $("#model").value } });
      const st = await api("/api/status"); $("#msg").innerHTML = st.ai.available ? `<span class="ok">${esc(st.ai.note)}</span>` : `<span class="warn">${esc(st.ai.note)}</span>`;
    } catch (e) { $("#msg").innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
  };
}

buildMenu();
window.addEventListener("hashchange", show);
show();
