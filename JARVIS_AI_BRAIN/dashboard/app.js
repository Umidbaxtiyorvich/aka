// JARVIS dashboard — barcha ma'lumotlar /api orqali backenddan keladi.
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error(data.detail || data || res.statusText);
  return data;
}

const SECTIONS = [
  ["dashboard", "Dashboard", renderDashboard],
  ["chat", "AI Chat", renderChat],
  ["voice", "Voice", planned("Ovozli muloqot", "Mikrofon (faqat siz yoqqanda, holati ko'rinib turadi), STT va TTS. O'zbek tili uchun mahalliy variantlar (Whisper) va ularning sifati solishtiriladi.")],
  ["memory", "Memory", renderMemory],
  ["agents", "Agentlar", renderAgents],
  ["office", "Virtual AI Office", renderOffice],
  ["files", "Fayllar", renderFiles],
  ["computer", "Kompyuter boshqaruvi", renderComputer],
  ["research", "Internet tadqiqoti", planned("Internet tadqiqoti", "Qidiruv, manba va sana bilan javob. Sahifa matni 'ishonchsiz ma'lumot' sifatida belgilanadi — undagi ko'rsatmalar bajarilmaydi.")],
  ["studio", "Rasm va video", planned("Image & Video Studio", "FFmpeg orqali kesish, birlashtirish, 9:16 Reels, subtitr. Rasm generatsiyasi GPU yoki ixtiyoriy onlayn adapter talab qiladi.")],
  ["instagram", "Instagram", planned("Instagram Manager", "Faqat Meta rasmiy Graph API (Business/Creator akkaunt). Har bir nashr aniq matn va akkaunt bilan tasdiqlanadi.")],
  ["telegram", "Telegram", planned("Telegram Assistant", "Bot tokeni Credential Manager'da; faqat ruxsat berilgan user ID'lardan buyruq qabul qilinadi.")],
  ["bi", "Business Intelligence", planned("Business Intelligence", "CSV/Excel import, qoldiq, foyda, kam qolgan mahsulot, takroriy hujjat va noto'g'ri narx tahlili.")],
  ["pos", "POS ulanishi", planned("POS Connector", "Avval faqat o'qish. Hujjat loyihasi → aniq versiya tasdig'i → kiritish → qayta tekshirish → audit. POS manzili berilgach boshlanadi.")],
  ["docs", "Hujjatlar", planned("Hujjatlar", "Tayyorlangan hujjat loyihalari va ularning versiyalari (POS moduli bilan birga).")],
  ["approvals", "Tasdiqlashlar", renderApprovals],
  ["audit", "Audit jurnali", renderAudit],
  ["errors", "Xatolar", renderErrors],
  ["tests", "Testlar", renderTests],
  ["security", "Xavfsizlik", renderSecurity],
  ["settings", "Sozlamalar", renderSettings],
];
const PLANNED = new Set(["voice", "research", "studio", "instagram", "telegram", "bi", "pos", "docs"]);

function buildMenu() {
  $("#menu").innerHTML = SECTIONS.map(([id, name]) =>
    `<a data-id="${id}">${name}${PLANNED.has(id) ? '<span class="tag">tez orada</span>' : ""}</a>`).join("");
  $("#menu").onclick = (e) => { const a = e.target.closest("a"); if (a) location.hash = a.dataset.id; };
}

let timer = null;
async function show() {
  clearInterval(timer);
  const id = location.hash.slice(1) || "dashboard";
  const sec = SECTIONS.find((s) => s[0] === id) || SECTIONS[0];
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.id === sec[0]));
  $("#title").textContent = sec[1];
  try { await sec[2]($("#view")); } catch (e) { $("#view").innerHTML = `<div class="card bad">Xato: ${esc(e.message)}</div>`; }
}

function planned(title, text) {
  return (v) => { v.innerHTML = `<div class="card"><h3>${esc(title)}</h3><p>${esc(text)}</p>
    <p class="warn">Bu modul hali yaratilmagan. Ishlayotgandek ko'rsatilmaydi.</p></div>`; };
}

const statusPill = (ok, yes, no) => `<span class="pill ${ok ? "ok" : "warn"}">${ok ? yes : no}</span>`;

async function renderDashboard(v) {
  const draw = async () => {
    const s = await api("/api/status");
    const sys = s.system, active = s.agents.filter((a) => a.implemented);
    $("#mode").innerHTML = s.settings.read_only_mode ? statusPill(true, "Faqat o'qish rejimi") : statusPill(false, "", "O'zgartirish rejimi");
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
    `<tr>${cols.map((c) => `<td>${esc(typeof r[c] === "object" ? JSON.stringify(r[c]) : r[c])}</td>`).join("")}</tr>`).join("")}</table>`;
}

async function renderChat(v) {
  v.innerHTML = `<div class="chat" id="log"></div>
    <div class="row"><input id="msg" placeholder="Yozing… (masalan: yordam, eslab qol: ..., xotira: ..., holat)" autofocus><button id="send">Yuborish</button></div>`;
  const log = $("#log");
  const add = (role, text) => { log.insertAdjacentHTML("beforeend", `<div class="msg ${role}">${esc(text)}</div>`); log.scrollTop = 1e9; };
  (await api("/api/chat/history?limit=40")).forEach((m) => add(m.role, m.content));
  const send = async () => {
    const t = $("#msg").value.trim(); if (!t) return;
    $("#msg").value = ""; add("user", t);
    try { add("assistant", (await api("/api/chat", { method: "POST", body: { text: t } })).text); }
    catch (e) { add("assistant", "Xato: " + e.message); }
  };
  $("#send").onclick = send;
  $("#msg").onkeydown = (e) => e.key === "Enter" && send();
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
    $("#list").innerHTML = rows.length ? `<table><tr><th>#</th><th>tur</th><th>mazmun</th><th>manba</th><th>ishonch</th><th>holat</th><th></th></tr>${rows.map((r) =>
      `<tr><td>${r.id}</td><td>${esc(r.kind)}</td><td>${esc(r.content)}</td><td>${esc(r.source)}<br><span class="muted">${esc(r.created_at)}</span></td><td>${r.confidence}</td>
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
    <div class="card" style="margin-top:12px"><h3>Agentlar</h3>${table(agents, ["title", "role", "status", "permission", "tools", "last_error"])}</div>
    <div class="card" style="margin-top:12px"><h3>Vazifalar</h3>${table(tasks, ["id", "agent", "title", "status", "result", "error"])}</div>`;
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
    <div class="card"><div class="row"><input id="cmd" placeholder="Masalan: dir   yoki   git status"><button id="p">Taklif qilish</button></div><div id="r"></div></div>`;
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
    <div class="muted">Daraja ${a.level}: ${esc(a.level_info)} · tizim: ${esc(a.target)} · akkaunt: ${esc(a.account || "—")} · so'ragan: ${esc(a.requested_by)} · ${esc(a.created_at)}</div>
    <pre>${esc(JSON.stringify(a.payload, null, 2))}</pre><div class="muted">versiya xeshi: ${a.payload_hash}</div>
    <div class="row" style="margin-top:8px">${a.status === "pending" ? `<button data-ok="${a.id}" data-h="${a.payload_hash}">Aynan shu versiyani tasdiqlash</button><button class="danger" data-no="${a.id}" data-h="${a.payload_hash}">Rad etish</button>` : ""}
    ${a.status === "approved" && a.action_type === "shell_command" ? `<button data-run="${a.id}">Bajarish</button>` : ""}</div><pre id="o${a.id}" hidden></pre></div>`).join("")
    : '<div class="card muted">Tasdiq so\'rovlari yo\'q</div>';
  v.onclick = async (e) => {
    const d = e.target.dataset;
    try {
      if (d.ok || d.no) { await api(`/api/approvals/${d.ok || d.no}/decide`, { method: "POST", body: { approve: !!d.ok, confirm_hash: d.h } }); show(); }
      if (d.run) { const r = await api(`/api/approvals/${d.run}/execute`, { method: "POST" }); const o = $("#o" + d.run); o.hidden = false; o.textContent = `exit=${r.exit_code}\n${r.output}`; }
    } catch (er) { alert(er.message); }
  };
}

async function renderAudit(v) {
  v.innerHTML = `<div class="card">${table(await api("/api/audit?limit=200"), ["ts", "agent", "action", "target", "risk", "approval_status", "result", "error_code", "verified"])}</div>`;
}
async function renderErrors(v) {
  const rows = await api("/api/errors");
  v.innerHTML = `<div class="card">${rows.length ? table(rows, ["ts", "module", "message"]) : '<span class="ok">Xatolar yo\'q</span>'}</div>`;
}

async function renderTests(v) {
  v.innerHTML = `<div class="card"><div class="row"><button id="h">Modullarni tekshirish</button><button id="t" class="ghost">pytest testlarini ishga tushirish</button></div><div id="r" class="muted">Natija shu yerda chiqadi.</div></div>`;
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

async function renderSecurity(v) {
  const s = await api("/api/settings");
  v.innerHTML = `<div class="grid"><div class="card"><h3>Joriy siyosat</h3>
    <div>Faqat o'qish rejimi: <b class="${s.read_only_mode ? "ok" : "warn"}">${s.read_only_mode ? "yoqilgan" : "o'chirilgan"}</b></div>
    <div>Tasdiq talab qilinadi: <b class="ok">${s.require_approval ? "ha" : "yo'q"}</b></div>
    <div>O'qish ruxsati: ${s.allowed_read_dirs.map(esc).join(", ")}</div><div>Yozish ruxsati: ${s.allowed_write_dirs.map(esc).join(", ")}</div>
    <p class="muted">Bu kalitlar (${s.locked_keys.join(", ")}) dashboard yoki JARVIS tomonidan o'zgartirilmaydi — faqat siz settings.json faylini qo'lda tahrirlab.</p></div>
    <div class="card"><h3>Matnni tekshirish</h3><textarea id="t" placeholder="Matn yoki buyruq"></textarea><div class="row" style="margin-top:8px"><button id="c">Tekshirish</button></div><pre id="r" hidden></pre></div></div>`;
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
    <div class="card" style="margin-top:12px"><h3>Model katalogi (taxminiy talablar)</h3>${table(sys.model_catalog, ["name", "disk_gb", "ram_gb", "note"])}</div>`;
  $("#pv").value = s.ai_provider;
  $("#save").onclick = async () => {
    try { await api("/api/settings", { method: "POST", body: { ai_provider: $("#pv").value, ollama_url: $("#url").value, ollama_model: $("#model").value } });
      const st = await api("/api/status"); $("#msg").innerHTML = st.ai.available ? `<span class="ok">${esc(st.ai.note)}</span>` : `<span class="warn">${esc(st.ai.note)}</span>`;
    } catch (e) { $("#msg").innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
  };
}

buildMenu();
window.addEventListener("hashchange", show);
show();
