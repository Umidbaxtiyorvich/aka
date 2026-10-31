// Universal Connection Center (POS / ERP / CRM / sayt / API / MCP / baza / fayl / dastur) va Super Brain Control Center.
// Parollar va tokenlar faqat shu kompyuterdagi shifrlangan vault'ga yoziladi; backend ularni hech qachon qaytarmaydi (faqat maydon nomi).
"use strict";

const CC = { tab: "all", sel: null, catalog: null };
const CC_TABS = [["all", "Barcha ulanishlar"], ["add", "+ Yangi ulanish"], ["pos", "POS"], ["erp", "ERP"], ["crm", "CRM"], ["website", "Saytlar"],
  ["api", "API"], ["mcp", "MCP"], ["database", "Bazalar"], ["files", "Fayllar"], ["desktop", "Dasturlar"], ["history", "Sinxron tarixi"],
  ["proposals", "Yozish takliflari"], ["credentials", "Kirish ma'lumotlari"]];
const ST_LABEL = { new: "yangi", connected: "ulangan", disconnected: "uzilgan", auth_expired: "sessiya tugagan", auth_failed: "login xato",
  permission_denied: "ruxsat yo'q", rate_limited: "cheklov (kuting)", user_action_required: "siz kirishingiz kerak", not_supported: "qo'llanmaydi",
  error: "xato", syncing: "sinxronlanmoqda" };
const stPill = (s) => `<span class="pill ${s === "connected" ? "ok" : ["new", "syncing", "user_action_required", "rate_limited", "disconnected"].includes(s) ? "warn" : "bad"}">${esc(ST_LABEL[s] || s)}</span>`;

async function renderConnections(v) {
  CC.catalog = CC.catalog || await api("/api/integrations/catalog");
  const list = await api("/api/integrations");
  const count = (f) => list.filter(f).length;
  v.innerHTML = `<div class="card"><div class="row" style="justify-content:space-between">
      <div><b>${list.length}</b> ta ulanish · <span class="pill ok">${count((c) => c.status === "connected")} ulangan</span>
        <span class="pill warn">${count((c) => ["user_action_required", "auth_expired", "new"].includes(c.status))} e'tibor kerak</span>
        <span class="pill bad">${count((c) => ["error", "auth_failed", "permission_denied"].includes(c.status))} xato</span></div>
      <button id="ccquick">+ Sayt / POS ulash</button>
      <span class="muted small">🔒 Parollar shifrlangan vault'da. Ulanish faqat "Tekshirish" muvaffaqiyatli bo'lsa "ulangan" deb ko'rsatiladi.</span></div>
    <div class="tabs">${CC_TABS.map(([k, t]) => `<a data-t="${k}" class="${CC.tab === k ? "active" : ""}">${t}</a>`).join("")}</div></div>
    <div id="ccbody"></div><div id="ccdetail"></div>`;
  $("#ccquick").onclick = () => { const u = prompt("Sayt yoki POS havolasini kiriting (https://...)"); if (u && u.trim()) openConnectModal(u.trim(), () => renderConnections(v)); };
  $(".tabs", v).onclick = (e) => { const a = e.target.closest("a"); if (a) { CC.tab = a.dataset.t; CC.sel = null; renderConnections(v); } };
  const body = $("#ccbody");
  if (CC.tab === "add") return ccAdd(body, v);
  if (CC.tab === "history") { body.innerHTML = `<div class="card"><h3>Sinxronlash tarixi</h3>${table((await api("/api/integrations/sync-history")).map((r) => ({ ...r, natija: r.counts })), ["id", "name", "mode", "trigger", "status", "started_at", "finished_at", "natija", "error"])}</div>`; return; }
  if (CC.tab === "proposals") { body.innerHTML = `<div class="card"><h3>Tashqi tizimga yozish takliflari</h3><p class="muted small">Yozish hech qachon avtomatik bajarilmaydi: "assistant" rejimida faqat qoralama, "authorized" rejimida — Tasdiqlashlar bo'limida siz tasdiqlaganingizdan keyin.</p>${table(await api("/api/integrations/proposals"), ["id", "conn_id", "entity", "operation", "status", "approval_id", "created_at"])}<a href="#approvals">→ Tasdiqlashlar</a></div>`; return; }
  if (CC.tab === "credentials") return ccCreds(body, list, v);
  const rows = CC.tab === "all" ? list : list.filter((c) => c.system_type === CC.tab);
  body.innerHTML = (CC.tab === "desktop" ? '<div class="card"><div class="row"><button id="dscan">🖥 Kompyuterdagi dasturlarni ko\'rish (faqat o\'qish)</button></div><pre id="dout" hidden></pre></div>' : "") +
    (rows.length ? `<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(300px,1fr))">${rows.map(ccCard).join("")}</div>`
      : `<div class="card"><p class="muted">Bu turda ulanish yo'q.</p><button id="ccgo">+ Yangi ulanish qo'shish</button></div>`);
  const go = $("#ccgo"); go.onclick = () => { CC.tab = "add"; renderConnections(v); };
  const ds = $("#dscan"); ds.onclick = async () => { try { const d = await post("/api/integrations/desktop-scan"); out($("#dout"), { dasturlar: (d.entities || []).map((e) => e.name), modullar: d.modules, izoh: d.note }); } catch (e) { fail($("#dout"), e); } };
  body.onclick = async (e) => {
    const b = e.target.closest("button[data-a]"); if (!b) return;
    const id = +b.dataset.id, a = b.dataset.a, msg = $(`#ccm${id}`);
    if (a === "open") { CC.sel = id; return ccDetail($("#ccdetail"), id, v); }
    if (a === "delete" && !confirm("Ulanish va uning shifrlangan kirish ma'lumotlari o'chirilsinmi? (Tashqi tizimdagi ma'lumotlarga tegilmaydi)")) return;
    b.disabled = true; msg.innerHTML = '<span class="muted">bajarilmoqda…</span>';
    try {
      const path = { test: "test", discover: "discover", sync: "sync", disconnect: "disconnect", login: "login-window" }[a];
      const r = a === "delete" ? await api(`/api/integrations/${id}`, { method: "DELETE" }) : await post(`/api/integrations/${id}/${path}`);
      if (a === "login") { msg.innerHTML = `<span class="muted">${esc(r.note)}</span>`; b.disabled = false; return; }
      renderConnections(v);
    } catch (er) { fail(msg, er); b.disabled = false; }
  };
  if (CC.sel) ccDetail($("#ccdetail"), CC.sel, v);
}

function ccCard(c) {
  const btn = (a, t, cls = "ghost") => `<button class="${cls}" data-a="${a}" data-id="${c.id}">${t}</button>`;
  return `<div class="card"><div class="row" style="justify-content:space-between;margin:0"><h3 style="margin:0">${esc(c.name)}</h3>${stPill(c.status)}</div>
    <div class="kv"><span>Turi / adapter</span><b>${esc(c.system_type)} · ${esc(c.adapter)}</b></div>
    ${c.store ? `<div class="kv"><span>Do'kon</span><b>${esc(c.store)}</b></div>` : ""}
    <div class="kv"><span>Rejim</span><b>${esc(CC.catalog.modes[c.mode] || c.mode)}</b></div>
    <div class="kv"><span>Oxirgi sinxron</span><b>${esc(c.last_sync || "—")}</b></div><div class="kv"><span>Yozuvlar</span><b>${c.records}</b></div>
    ${c.status_note ? `<p class="small muted">${esc(c.status_note)}</p>` : ""}
    <div class="row" style="margin-top:8px">${btn("test", "Tekshirish", "")}${btn("discover", "O'rganish")}${btn("sync", "Sinxronlash")}${btn("open", "Batafsil")}
      ${c.adapter === "website" ? btn("login", "Brauzerda kirish") : ""}${btn("disconnect", "Uzish")}${btn("delete", "O'chirish")}</div><div id="ccm${c.id}"></div></div>`;
}

function ccFields(adapter, values = {}, secretsSet = []) {
  return (CC.catalog.adapters[adapter]?.fields || []).map((f) => {
    const id = `f_${f.key}`, val = f.secret ? "" : (values[f.key] ?? f.default ?? "");
    const v = typeof val === "object" ? JSON.stringify(val, null, 1) : val;
    const lab = `<label>${esc(f.label)}${f.required ? " *" : ""}${f.secret ? ` 🔒${secretsSet.includes(f.key) ? ' <span class="pill ok">kiritilgan</span>' : ""}` : ""}</label>`;
    if (f.type === "select") return lab + `<select id="${id}" data-k="${f.key}" data-s="${f.secret ? 1 : 0}">${f.options.map((o) => `<option ${String(v) === String(o) ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
    if (f.type === "json") return lab + `<textarea id="${id}" data-k="${f.key}" data-s="0" data-json="1" rows="3" placeholder="{}">${esc(v)}</textarea>`;
    return lab + `<input id="${id}" data-k="${f.key}" data-s="${f.secret ? 1 : 0}" type="${f.secret || f.type === "password" ? "password" : "text"}" autocomplete="off"
      placeholder="${esc(f.secret && secretsSet.includes(f.key) ? "o'zgartirish uchun yangisini kiriting" : f.help || "")}" value="${esc(v)}">`;
  }).join("");
}

function ccCollect(root) {
  const config = {}, secrets = {};
  root.querySelectorAll("[data-k]").forEach((el) => {
    if (el.value === "") return;
    if (el.dataset.json) { try { config[el.dataset.k] = JSON.parse(el.value); } catch (e) { throw new Error(`${el.dataset.k}: JSON noto'g'ri`); } return; }
    (el.dataset.s === "1" ? secrets : config)[el.dataset.k] = el.value;
  });
  return { config, secrets };
}

async function ccAdd(body, v) {
  const cat = CC.catalog;
  body.innerHTML = `<div class="card"><h3>🌐 Sayt yoki POS'ni ulash (tavsiya etiladi)</h3>
      <p class="small muted">1) Saytning havolasini kiriting → 2) JARVIS saytni ochib, kirish uchun nima kerakligini (login, parol, email, telefon, ID…) aniqlaydi →
        3) faqat shu ma'lumotlarni so'raydi. Ma'lumotlar shifrlangan holda faqat shu kompyuterda saqlanadi.</p>
      <div class="row"><input id="wurl" placeholder="https://app.yespos.uz yoki POS/ERP kabinet havolasi"><button id="wprobe">Saytni tekshirish</button></div>
      <div id="wres"></div></div>
    <details class="card"><summary><b>Boshqa ulanish turlari</b> <span class="small muted">— API, 1C (OData), ma'lumotlar bazasi, fayllar, MCP, kompyuter dasturlari</span></summary>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(360px,1fr));margin-top:10px">
    <div class="card"><h3>Yangi ulanish</h3>
      <label>Tizim (andoza)</label><select id="preset">${Object.entries(cat.presets).map(([k, p]) => `<option value="${k}">${esc(p.title)}</option>`).join("")}</select>
      <p id="pnote" class="small warn"></p>
      <label>Nomi</label><input id="cname" placeholder="masalan: Chilonzor do'koni — YesPOS">
      <div class="row"><div style="flex:1"><label>Tizim turi</label><select id="ctype">${Object.entries(cat.system_types).map(([k, t]) => `<option value="${k}">${esc(t)}</option>`).join("")}</select></div>
        <div style="flex:1"><label>Adapter</label><select id="cadapter">${Object.entries(cat.adapters).map(([k, a]) => `<option value="${k}">${esc(a.title)}</option>`).join("")}</select></div></div>
      <label>Do'kon / filial (bir nechta do'kon bo'lsa)</label><input id="cstore" placeholder="ixtiyoriy">
      <label>Ruxsat rejimi</label><select id="cmode">${Object.entries(cat.modes).map(([k, t]) => `<option value="${k}">${esc(t)}</option>`).join("")}</select>
      <div id="cfields"></div>
      <p class="small muted">🔒 Login/parol/token shu yerda kiritiladi va faqat shu kompyuterdagi shifrlangan vault'ga yoziladi. Ularni chatga, Telegram'ga yoki AI'ga yozmang.
        CAPTCHA yoki SMS-kod bo'lsa — "Brauzerda kirish" tugmasi bilan o'zingiz o'tasiz; JARVIS ularni chetlab o'tmaydi.</p>
      <div class="row"><button id="csave">Saqlash va tekshirish</button></div><div id="cmsg"></div></div>
    <div class="card"><h3>Tizimni avtomatik aniqlash</h3><p class="muted small">Manzilni kiriting — JARVIS bir nechta xavfsiz GET so'rov bilan REST/OpenAPI, GraphQL, OData yoki veb-panel ekanini aniqlaydi (login qilmaydi).</p>
      <div class="row"><input id="durl" placeholder="https://..."><button class="ghost" id="dgo">Aniqlash</button></div><div id="dres"></div>
      <h3 style="margin-top:16px">Qaysi usul qachon?</h3><ul class="small">
        <li><b>REST / OData / GraphQL</b> — tizimda rasmiy API bo'lsa (eng ishonchli). Token tizim kabinetidan olinadi.</li>
        <li><b>Veb-sayt</b> — API yo'q bo'lsa: login qilib, hisobot jadvallarini o'qiydi (sekinroq, sayt o'zgarsa buzilishi mumkin).</li>
        <li><b>Ma'lumotlar bazasi</b> — administrator bergan <u>read-only</u> foydalanuvchi bilan (faqat SELECT).</li>
        <li><b>Fayllar</b> — Excel/CSV eksport papkasi (eng oddiy va xavfsiz).</li><li><b>MCP</b> — MCP server manzili orqali vositalar.</li></ul></div></div></details>`;
  ccSiteWizard(v);
  const applyPreset = () => {
    const p = cat.presets[$("#preset").value];
    $("#pnote").textContent = p.note || ""; $("#ctype").value = p.system_type; $("#cadapter").value = p.adapter;
    if (!$("#cname").value || $("#cname").dataset.auto) { $("#cname").value = p.title; $("#cname").dataset.auto = 1; }
    $("#cfields").innerHTML = ccFields(p.adapter, p.config);
  };
  $("#preset").onchange = applyPreset; applyPreset();
  $("#cname").oninput = () => delete $("#cname").dataset.auto;
  $("#cadapter").onchange = () => { $("#cfields").innerHTML = ccFields($("#cadapter").value); };
  $("#dgo").onclick = async () => {
    try { const d = await post("/api/integrations/detect", { url: $("#durl").value.trim() });
      $("#dres").innerHTML = `<div class="kv"><span>Natija</span><b>${esc(d.recommended || "aniqlanmadi")}</b></div>${table(d.candidates || [], ["adapter", "confidence", "why"])}<p class="small muted">${esc(d.note || "")}</p>`;
      const best = (d.candidates || [])[0];
      if (best && cat.adapters[best.adapter]) { $("#cadapter").value = best.adapter; $("#cfields").innerHTML = ccFields(best.adapter, { base_url: best.base_url || $("#durl").value.trim(), ...(best.config || {}) }); }
    } catch (e) { fail($("#dres"), e); } };
  $("#csave").onclick = async () => {
    const m = $("#cmsg");
    try {
      const { config, secrets } = ccCollect($("#cfields"));
      const c = await post("/api/integrations", { name: $("#cname").value.trim(), preset: $("#preset").value, system_type: $("#ctype").value, adapter: $("#cadapter").value,
        store: $("#cstore").value.trim(), mode: $("#cmode").value, config, secrets });
      $("#cfields").querySelectorAll("[data-s='1']").forEach((el) => { el.value = ""; });
      m.innerHTML = '<span class="muted">Saqlandi. Tekshirilmoqda…</span>';
      let t; try { t = await post(`/api/integrations/${c.id}/test`); } catch (e) { t = { status: "error", status_note: e.message }; }
      m.innerHTML = `${stPill(t.status)} <span class="small">${esc(t.status_note || "")}</span>`;
      CC.tab = "all"; CC.sel = c.id; later(() => renderConnections(v), 1200);
    } catch (e) { fail(m, e); }
  };
}

function ccSiteWizard(v) {
  const inp = $("#wurl");
  const go = () => { const u = inp.value.trim(); if (u) openConnectModal(u, () => renderConnections(v)); };
  $("#wprobe").onclick = go;
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  inp.addEventListener("paste", () => setTimeout(() => { if (/^https?:\/\//i.test(inp.value.trim())) go(); }, 50));   // havola tashlandi — oyna o'zi ochiladi
}

// Sayt / POS ulash oynasi: havola → JARVIS saytni ochib kirish usulini aniqlaydi → faqat kerakli maydonlar → kirib ko'radi →
// ulansa — o'zi o'rganadi (discover) va ma'lumotni oladi (sync). Parol va boshqa qiymatlar shifrlangan saqlanadi.
function openConnectModal(url, onDone) {
  let m = document.getElementById("cmodal");
  if (m) m.remove();
  m = document.createElement("div");
  m.id = "cmodal";
  m.innerHTML = `<div class="card cm-box"><div class="row" style="justify-content:space-between;margin:0"><h3 style="margin:0">🔌 Sayt / POS'ni ulash</h3>
      <button class="ghost" id="cmx" title="Yopish">✕</button></div><div class="small muted" style="word-break:break-all">${esc(url)}</div><div id="cmbody"></div></div>`;
  document.body.appendChild(m);
  const body = m.querySelector("#cmbody"), close = () => { m.remove(); if (onDone) onDone(); };
  m.querySelector("#cmx").onclick = close;
  m.addEventListener("click", (e) => { if (e.target === m) close(); });
  const step = (t) => `<div class="cm-step">${t}</div>`;
  body.innerHTML = step("⏳ Sayt ochilmoqda va kirish usuli aniqlanmoqda…");
  (async () => {
    let r;
    try { r = await post("/api/integrations/probe-login", { url }); } catch (e) { body.innerHTML = `<p class="bad">${esc(e.message)}</p><p class="small muted">Havolani tekshiring (https:// bilan boshlanishi kerak).</p>`; return; }
    if (r.service_link) {
      body.innerHTML = `<p class="warn">ℹ ${esc(r.notes[0])}</p><div class="row"><a href="${r.service_link}" id="cmsvc"><button>→ ${esc(r.service)} bo'limini ochish</button></a></div>`;
      m.querySelector("#cmsvc").onclick = () => m.remove();
      return;
    }
    const store = r.fields.filter((f) => f.store), cat = CC.catalog || (CC.catalog = await api("/api/integrations/catalog"));
    const needUser = r.captcha || r.otp || r.sso.length;
    body.innerHTML = `${step(`✅ Sayt ochildi: <b>${esc(r.domain)}</b>`)}
      ${step(`🔎 Kirish sahifasi: <span class="small">${esc(r.login_url)}</span>`)}
      ${step(`📝 Kirish uchun kerak: <b>${esc(store.map((f) => f.label).join(", ") || "—")}</b>${r.guessed ? ' <span class="pill warn">taxmin</span>' : ""}`)}
      ${r.notes.map((n) => `<p class="small warn">ℹ ${esc(n)}</p>`).join("")}
      <div class="row"><div style="flex:1"><label>Nomi</label><input id="cmname" value="${esc(r.preset ? cat.presets[r.preset].title : r.domain)}"></div>
        <div style="flex:1"><label>Turi</label><select id="cmtype"><option value="pos">POS</option><option value="erp">ERP</option><option value="crm">CRM</option>
        <option value="shop">Internet-do'kon</option><option value="website">Boshqa sayt</option></select></div></div>
      ${store.map((f) => `<label>${esc(f.label)} 🔒${f.hint ? ` <span class="muted small">(${esc(f.hint)})</span>` : ""}</label>
        <input data-cf="${esc(f.key)}" type="${f.kind === "password" ? "password" : "text"}" autocomplete="off" placeholder="${esc(f.label)}">`).join("")}
      <p class="small muted">🔒 Kiritgan ma'lumotlaringiz shifrlangan holda faqat shu kompyuterda saqlanadi, ekranda qayta ko'rsatilmaydi va hech qayerga yuborilmaydi (faqat shu saytga kirish uchun).</p>
      <div class="row"><button id="cmgo">Kirish va ulash</button></div><div id="cmprog"></div>`;
    $("#cmtype").value = r.preset && cat.presets[r.preset].system_type === "erp" ? "erp" : "pos";
    const first = body.querySelector("[data-cf]");
    if (first) first.focus();
    body.querySelectorAll("[data-cf]").forEach((i) => i.addEventListener("keydown", (e) => { if (e.key === "Enter") $("#cmgo").click(); }));
    $("#cmgo").onclick = async () => {
      const prog = $("#cmprog"), secrets = {}, missing = [];
      body.querySelectorAll("[data-cf]").forEach((i) => { if (i.value) secrets["f_" + i.dataset.cf] = i.value; else missing.push(i.placeholder); });
      if (missing.length && !r.sso.length) return fail(prog, new Error("To'ldiring: " + missing.join(", ")));
      $("#cmgo").disabled = true;
      const say = (t) => { prog.insertAdjacentHTML("beforeend", step(t)); };
      let c;
      try {
        c = await post("/api/integrations", { name: $("#cmname").value.trim() || r.domain, system_type: $("#cmtype").value, adapter: "website",
          config: { base_url: r.url, login_url: r.login_url, login_fields: r.fields }, secrets });
        body.querySelectorAll("[data-cf]").forEach((i) => { i.value = ""; });
        say("💾 Saqlandi (shifrlangan).");
        if (needUser) {
          await post(`/api/integrations/${c.id}/login-window`);
          say(`🧭 Brauzer oynasi ochildi — CAPTCHA / SMS kod / ${esc(r.sso.join(", ") || "tasdiq")} qadamini o'zingiz bajaring, so'ng oynani yoping va pastdagi tugmani bosing.`);
          prog.insertAdjacentHTML("beforeend", '<div class="row"><button id="cmchk">Kirdim — tekshirish</button></div>');
          $("#cmchk").onclick = () => finish(c.id);
          return;
        }
        await finish(c.id);
      } catch (e) { fail(prog, e); $("#cmgo").disabled = false; }
    };
    async function finish(cid) {
      const prog = $("#cmprog"), say = (t) => { prog.insertAdjacentHTML("beforeend", step(t)); };
      say("🔐 Saytga kirilmoqda…");
      let t;
      try { t = await post(`/api/integrations/${cid}/test`); } catch (e) { t = { status: "error", status_note: e.message }; }
      if (t.status !== "connected") {
        say(`${stPill(t.status)} ${esc(t.status_note || "")}`);
        say(t.status === "auth_failed" ? "Login yoki parol noto'g'ri bo'lishi mumkin — Ulanishlar → Batafsil'da qayta kiriting." : "Holatni Ulanishlar bo'limida ko'rishingiz mumkin.");
        return;
      }
      say(`${stPill("connected")} Ulandi!`);
      say("📚 JARVIS saytni o'rganmoqda (bo'limlar va jadvallar)…");
      try { const d = await post(`/api/integrations/${cid}/discover`); say(`✅ ${(d.entities || []).length} ta bo'lim/jadval topildi.`); } catch (e) { say(`<span class="warn">O'rganishda muammo: ${esc(e.message)}</span>`); }
      say("⬇ Ma'lumotlar olinmoqda…");
      try { const sy = await post(`/api/integrations/${cid}/sync`); say(`✅ Sinxronlash: ${esc(JSON.stringify(sy.counts || sy.result || sy).slice(0, 160))}`); } catch (e) { say(`<span class="warn">Sinxronlashda muammo: ${esc(e.message)}</span>`); }
      say('🎉 Tayyor. Endi chatda so\'rang: <i>"Bugungi savdo qancha?"</i>');
      CC.tab = "all"; CC.sel = cid;
    }
  })();
}

async function ccDetail(el, id, v) {
  const c = await api(`/api/integrations/${id}`);
  const ents = c.learning?.entities || c.entities.map((e) => ({ name: e.name, readable: e.readable }));
  const MODEL = ["", "product", "sale", "customer", "supplier", "payment", "movement", "expense"];
  el.innerHTML = `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(380px,1fr))">
    <div class="card"><h3>${esc(c.name)} — sozlamalar</h3>${stPill(c.status)} <span class="small muted">${esc(c.status_note || "")}</span>
      <div id="dfields">${ccFields(c.adapter, c.config, c.secrets)}</div>
      <label>Avtomatik sinxronlash (daqiqa, 0 — o'chiq)</label><input id="dint" type="number" min="0" value="${c.sync_interval_min || 0}">
      <label>Ruxsat rejimi (Permissions)</label><select id="dmode">${Object.entries(CC.catalog.modes).map(([k, t]) => `<option value="${k}" ${c.mode === k ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
      <p class="small muted">Rejimdan qat'i nazar: tashqi tizimga har bir yozuv tasdiqni talab qiladi, pul/narx/to'lov/o'chirish — eng yuqori (E) daraja, faqat dashboardda.</p>
      <div class="row"><button id="dsave">Saqlash</button><button class="ghost" id="dfull">To'liq sinxronlash</button></div><div id="dmsg"></div></div>
    <div class="card"><h3>Discovery — JARVIS nimani o'rgandi</h3>
      ${c.learning ? `<p class="small">Modullar: ${esc((c.learning.modules || []).join(", ") || "—")}</p>` : '<p class="muted">Hali o\'rganilmagan — "O\'rganish" tugmasini bosing.</p>'}
      ${ents.length ? `<table><tr><th>Obyekt</th><th>O'qiladi</th><th>JARVIS modeli</th><th>Ishonch</th><th>Holat</th><th></th></tr>${ents.map((e, i) => {
        const mp = c.mapping[e.name] || {};
        return `<tr><td>${esc(e.name)}</td><td>${e.readable ? "ha" : "yo'q"}</td><td><select data-me="${i}">${MODEL.map((m) => `<option value="${m}" ${(mp.entity || "") === m ? "selected" : ""}>${m || "— (ishlatilmaydi)"}</option>`).join("")}</select></td>
          <td>${Math.round((mp.confidence || 0) * 100)}%</td><td>${esc(mp.status || "—")}</td><td><button class="ghost" data-mc="${i}">Tasdiqlash</button></td></tr>
          ${Object.keys(mp.fields || {}).length || (mp.unmapped || []).length ? `<tr><td colspan="6" class="small muted">Maydonlar: ${esc(Object.entries(mp.fields || {}).map(([a, b]) => `${a}→${b}`).join(", "))}${(mp.unmapped || []).length ? ` · mos kelmadi: ${esc(mp.unmapped.join(", "))}` : ""}</td></tr>` : ""}`;
      }).join("")}</table><p class="small muted">Moslik taxminiy: tekshirib "Tasdiqlash"ni bosing. Tahlilda tasdiqlangan yoki ishonchi yuqori xaritalar ishlatiladi; noma'lum maydonlar to'ldirilmaydi.</p>` : ""}
      <div id="mmsg"></div></div>
    <div class="card"><h3>Ma'lumotlar (sinxronlangan nusxa)</h3>
      <div class="row"><select id="rent"><option value="">hammasi</option>${[...new Set(ents.map((e) => e.name))].map((n) => `<option>${esc(n)}</option>`).join("")}</select><button class="ghost" id="rgo">Ko'rish</button></div><div id="rres" style="max-height:340px;overflow:auto"></div>
      ${c.adapter === "database" ? `<h3 style="margin-top:14px">SQL so'rov (faqat SELECT)</h3><textarea id="sql" rows="3" placeholder="SELECT * FROM products LIMIT 20"></textarea><div class="row"><button class="ghost" id="sqlgo">Bajarish</button></div><div id="sqlres" style="max-height:300px;overflow:auto"></div>` : ""}</div>
    <div class="card"><h3>Tashqi tizimga yozish (taklif)</h3>
      ${CC.catalog.adapters[c.adapter]?.can_write ? `<p class="small muted">"Faqat o'qish" rejimida rad etiladi. Boshqa rejimlarda — qoralama yoki tasdiq so'rovi yaratiladi, darhol bajarilmaydi.</p>
        <label>Obyekt</label><input id="went" placeholder="products"><label>Amal</label><select id="wop"><option>create</option><option>update</option></select>
        <label>Ma'lumot (JSON)</label><textarea id="wpay" rows="3">{}</textarea><label>Qisqa izoh</label><input id="wsum">
        <div class="row"><button class="ghost" id="wgo">Taklif yaratish</button></div><div id="wres"></div>` : '<p class="muted">Bu adapter yozishni qo\'llamaydi (faqat o\'qish).</p>'}</div></div>`;
  $("#dsave").onclick = async () => {
    try { const { config, secrets } = ccCollect($("#dfields"));
      await post(`/api/integrations/${id}`, { config, secrets: Object.keys(secrets).length ? secrets : null, sync_interval_min: +$("#dint").value || 0 });
      if ($("#dmode").value !== c.mode) await api(`/api/integrations/${id}/mode?mode=${encodeURIComponent($("#dmode").value)}`, { method: "POST" });
      renderConnections(v);
    } catch (e) { fail($("#dmsg"), e); } };
  $("#dfull").onclick = async () => { try { const r = await api(`/api/integrations/${id}/sync?mode=full`, { method: "POST" }); out($("#dmsg"), r); } catch (e) { fail($("#dmsg"), e); } };
  el.querySelectorAll("[data-mc]").forEach((b) => { b.onclick = async () => {
    const e = ents[+b.dataset.mc], mp = c.mapping[e.name] || {}, ent = el.querySelector(`[data-me="${b.dataset.mc}"]`).value;
    try { await post(`/api/integrations/${id}/mapping`, { source_entity: e.name, entity: ent || null, fields: ent === mp.entity ? mp.fields || {} : {} }); ccDetail(el, id, v); } catch (er) { fail($("#mmsg"), er); } }; });
  $("#rgo").onclick = async () => {
    try { const rows = await api(`/api/integrations/${id}/records?entity=${encodeURIComponent($("#rent").value)}&limit=100`);
      const flat = rows.map((r) => ({ obyekt: r.source_entity, model: r.entity, ...r.data }));
      const cols = [...new Set(flat.flatMap((r) => Object.keys(r)))].slice(0, 12);
      $("#rres").innerHTML = table(flat, cols); } catch (e) { fail($("#rres"), e); } };
  const sq = $("#sqlgo"); sq.onclick = async () => { try { const r = await post(`/api/integrations/${id}/query`, { sql: $("#sql").value }); $("#sqlres").innerHTML = table(r.rows || [], r.columns || Object.keys((r.rows || [])[0] || {})); } catch (e) { fail($("#sqlres"), e); } };
  const wg = $("#wgo"); wg.onclick = async () => {
    try { const r = await post(`/api/integrations/${id}/write`, { entity: $("#went").value.trim(), operation: $("#wop").value, payload: JSON.parse($("#wpay").value || "{}"), summary: $("#wsum").value });
      out($("#wres"), r); } catch (e) { fail($("#wres"), e); } };
}

function ccCreds(body, list, v) {
  body.innerHTML = `<div class="card"><h3>Kirish ma'lumotlari (shifrlangan saqlash)</h3>
    <p class="small muted">Qiymatlar hech qachon ko'rsatilmaydi va GitHub'ga, loglarga yoki AI'ga yuborilmaydi: faqat qaysi maydon kiritilgani. Saqlash joyi — Windows Credential Manager
      (yoki JARVIS_HOME/vault ichidagi shifrlangan fayl). Almashtirish uchun ulanishning "Batafsil" sahifasidan yangi qiymat kiriting.</p>
    ${table(list.map((c) => ({ id: c.id, ulanish: c.name, adapter: c.adapter, maydonlar: c.secrets.join(", ") || "—", holat: ST_LABEL[c.status] || c.status })), ["id", "ulanish", "adapter", "maydonlar", "holat"])}
    <div class="row" style="margin-top:10px">${list.map((c) => `<button class="ghost" data-o="${c.id}">${esc(c.name)} — batafsil</button>`).join("")}</div>
    <p class="small"><a href="#audit">→ Audit jurnali</a> (har bir ulanish, tekshiruv va yozish urinishi qayd etiladi)</p></div>`;
  body.onclick = (e) => { const b = e.target.closest("[data-o]"); if (b) { CC.tab = "all"; CC.sel = +b.dataset.o; renderConnections(v); } };
}

// ---------------- Super Brain Control Center ----------------
async function renderSuperBrain(v) {
  const [st, pr, set, secs, voice] = await Promise.all([api("/api/brain-core/status"), api("/api/ai/presets"), api("/api/settings"),
    api("/api/secrets").catch(() => []), api("/api/voice/pro").catch(() => null)]);
  const has = (n) => (secs.find((x) => x.name === n) || {}).set;
  const ids = st.models.map((m) => m.id);
  const pos = st.integrations.filter((c) => ["pos", "erp", "crm"].includes(c.type));
  v.innerHTML = `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(360px,1fr))">
    <div class="card"><h3>🧠 Miya tuzilishi</h3><ol class="small">${st.architecture.map((a) => `<li>${esc(a)}</li>`).join("")}</ol>
      <p class="small muted">${esc(st.note)}</p>
      <div class="kv"><span>Xotira yozuvlari</span><b>${st.memory.items}</b></div><div class="kv"><span>Knowledge Graph tugunlari</span><b>${st.memory.graph_nodes}</b></div>
      <div class="kv"><span>Oxirgi marshrut</span><b>${esc(st.last_route ? `${st.last_route.provider || st.last_route.chosen || ""} ${st.last_route.reason || ""}` : "—")}</b></div>
      <p class="small muted">O'rganish: JARVIS modelni qayta o'qitmaydi — yangi bilim xotira, Knowledge Graph va ulanishlar xaritasiga yoziladi (RAG).</p></div>
    <div class="card"><h3>AI modellar</h3>${table(st.models.map((m) => ({ id: m.id, model: m.model, turi: m.local ? "mahalliy" : "bulut", pullik: m.paid, tayyor: m.available, izoh: m.note })), ["id", "model", "turi", "pullik", "tayyor", "izoh"])}
      <div class="kv"><span>Pullik AI ruxsati</span>${statusPill(set.paid_ai_allowed, "yoqilgan", "o'chiq (faqat siz yoqasiz — Sozlamalar)")}</div>
      <h3 style="margin-top:12px">Model qo'shish</h3><div class="row">${Object.entries(pr.presets).filter(([, p]) => !ids.includes(p.id)).map(([k, p]) => `<button class="ghost" data-pp="${k}">${esc(k)} (${esc(p.model)})</button>`).join("") || '<span class="muted small">Barcha andozalar qo\'shilgan</span>'}</div>
      <div id="ppform"></div><div id="ppmsg"></div></div>
    <div class="card"><h3>Vazifa → model</h3><p class="small muted">Har vazifa uchun afzal model. Maxfiy/shaxsiy ma'lumot bo'lsa baribir faqat mahalliy modelga ketadi.</p>
      ${Object.entries(pr.task_types).map(([k, t]) => `<div class="kv"><span>${esc(t)}</span><select data-tr="${k}" style="max-width:180px"><option value="">avtomatik</option>${ids.map((i) => `<option ${pr.routes[k] === i ? "selected" : ""}>${esc(i)}</option>`).join("")}</select></div>`).join("")}
      <div class="row" style="margin-top:8px"><button id="trsave">Saqlash</button></div><div id="trmsg"></div></div>
    <div class="card"><h3>POS / ERP ulanishlari</h3>${pos.length ? table(pos.map((c) => ({ nomi: c.name, "do'kon": c.store, holat: ST_LABEL[c.status] || c.status, sinxron: c.last_sync, yozuvlar: c.records })), ["nomi", "do'kon", "holat", "sinxron", "yozuvlar"]) : '<p class="muted">Hali POS ulanmagan.</p>'}
      <a href="#connections">→ Ulanishlar</a></div>
    <div class="card"><h3>Biznes tahlilchisi (POS savollari)</h3><p class="small muted">Masalan: "Bugungi savdo qancha?", "Qaysi mahsulot ko'p sotildi?", "Qaysi do'konda savdo pasaydi?", "Qarzdorlar". Javob faqat sinxronlangan ma'lumotdan, manba bilan.</p>
      <div class="row"><input id="aq" placeholder="Savol"><button id="ago">So'rash</button></div><div id="ares"></div></div>
    <div class="card"><h3>Ovoz</h3>${voice ? `<div class="kv"><span>Javob ovozi</span><b>${esc(voice.selected.tts)}</b></div><div class="kv"><span>Nutqni tanish</span><b>${esc(voice.selected.stt)}</b></div>
      <div class="kv"><span>Azure o'zbek neyron ovozi</span>${statusPill(has("azure_speech_key") && set.azure_speech_region, "sozlangan", "kalit/mintaqa yo'q")}</div>` : '<p class="muted">Holat olinmadi</p>'}<a href="#voice">→ Ovoz sozlamalari</a></div>
    <div class="card"><h3>Agentlar</h3>${table(st.agents.map((a) => ({ agent: a.title, holat: a.status, ruxsat: a.permission })), ["agent", "holat", "ruxsat"])}</div>
    <div class="card"><h3>Xavfsizlik</h3><ul class="small"><li>Xavfli amallar — faqat tugma bilan tasdiq (ovoz yagona omil emas).</li><li>Tashqi tizimga yozish, to'lov, o'chirish — avtomatik bajarilmaydi.</li>
      <li>JARVIS o'z xavfsizlik qoidalari va ruxsatlarini o'zi o'zgartira olmaydi.</li><li>Parollar faqat shifrlangan vault'da.</li></ul>
      <a href="#approvals">Tasdiqlashlar</a> · <a href="#audit">Audit</a> · <a href="#security">Xavfsizlik</a></div></div>`;
  v.querySelectorAll("[data-pp]").forEach((b) => { b.onclick = () => {
    const p = pr.presets[b.dataset.pp];
    $("#ppform").innerHTML = `<p class="small">${esc(p.note)}</p><label>Model nomi</label><input id="ppmodel" value="${esc(p.model)}">
      ${p.kind === "ollama" ? "" : `<label>API kalit 🔒 (ai_key_${esc(p.id)})</label><input id="ppkey" type="password" autocomplete="off" placeholder="kalitni qo'ying">`}
      <p class="small muted">${p.paid ? "Pullik xizmat: ishlashi uchun Sozlamalarda 'Pullik AI' ni o'zingiz yoqishingiz kerak. Maxfiy ma'lumotlar unga yuborilmaydi." : ""}</p>
      <div class="row"><button id="ppadd">Qo'shish</button></div>`;
    $("#ppadd").onclick = async () => {
      try { const prov = { ...p, model: $("#ppmodel").value.trim() || p.model }; delete prov.note;
        const key = $("#ppkey").value; await post("/api/settings", { ai_providers: [...(set.ai_providers || []), prov] });
        if (key) await post("/api/secrets", { name: `ai_key_${p.id}`, value: key });
        renderSuperBrain(v); } catch (e) { fail($("#ppmsg"), e); } };
  }; });
  $("#trsave").onclick = async () => {
    const routes = {}; v.querySelectorAll("[data-tr]").forEach((s) => { if (s.value) routes[s.dataset.tr] = s.value; });
    try { await post("/api/settings", { ai_task_routes: routes }); $("#trmsg").innerHTML = '<span class="pill ok">saqlandi</span>'; } catch (e) { fail($("#trmsg"), e); } };
  const ask = async () => {
    const q = $("#aq").value.trim(); if (!q) return;
    $("#ares").innerHTML = '<span class="muted">hisoblanmoqda…</span>';
    try { const r = await post("/api/analyst/ask", { question: q });
      if (!r.handled) { $("#ares").innerHTML = '<p class="muted">Bu savol POS tahlili emas — AI Chat bo\'limida so\'rang.</p>'; return; }
      $("#ares").innerHTML = `<p style="white-space:pre-wrap">${esc(r.text)}</p>${(r.sources || []).length ? `<p class="small">Manba: ${esc(r.sources.join(", "))}${r.period ? ` · ${esc(r.period[0])} — ${esc(r.period[1])}` : ""}</p>` : ""}
        ${r.method && r.method !== "—" ? `<p class="small muted">Hisoblash: ${esc(r.method)}</p>` : ""}${(r.limitations || []).map((l) => `<p class="small warn">⚠ ${esc(l)}</p>`).join("")}`;
    } catch (e) { fail($("#ares"), e); } };
  $("#ago").onclick = ask; $("#aq").onkeydown = (e) => { if (e.key === "Enter") ask(); };
}
