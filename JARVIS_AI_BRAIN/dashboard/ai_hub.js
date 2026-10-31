// AI Provider Center, Smart AI Router, Model Catalog va Memory Import Center.
// API kalitlari faqat backend orqali Credential Manager'ga yoziladi; bu yerda hech qachon ko'rsatilmaydi va saqlanmaydi.
"use strict";

const HUB = { cat: null, add: null };
const HST = { connected: "ok", partially_supported: "warn", unchecked: "warn", not_configured: "warn", rate_limited: "warn" };
const hubPill = (st, label) => `<span class="pill ${HST[st] || "bad"}">${esc(label || st)}</span>`;
const money = (x, cur) => `${(+x || 0).toFixed(4)} ${esc(cur || "USD")}`;

async function hubCatalog() { HUB.cat = HUB.cat || await api("/api/ai/hub/catalog"); return HUB.cat; }

function hubSteps(v) {
  if (!v) return "";
  const ic = (ok) => (ok === true ? "✅" : ok === false ? "❌" : "➖");
  return `<div class="small" style="margin-top:6px">${hubPill(v.status, v.label)} ${esc(v.note || "")}
    <ol style="margin:6px 0 0 18px;padding:0">${(v.steps || []).map((s) => `<li>${ic(s.ok)} <b>${esc(s.step)}</b>: ${esc(s.detail)}</li>`).join("")}</ol></div>`;
}

async function renderProviderCenter(v) {
  const [cat, list, ov] = await Promise.all([hubCatalog(), api("/api/ai/hub/providers"), api("/api/ai/hub/overview")]);
  const st = cat.statuses;
  v.innerHTML = `<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(160px,1fr))">
      ${[["Provayderlar", ov.providers], ["Ulangan", ov.connected], ["Ishlamayapti", ov.offline], ["Modellar", ov.models], ["Bugungi so'rovlar", ov.today.requests],
         ["Bugungi xarajat", money(ov.today.cost, ov.currency)], ["Oylik xarajat", money(ov.month.cost, ov.currency)], ["Fallback (bugun)", ov.fallbacks_today],
         ["Lokal AI", st[ov.local_ai] || ov.local_ai]].map(([k, x]) => `<div class="card"><div class="muted small">${k}</div><b style="font-size:20px">${esc(x)}</b></div>`).join("")}</div>
    <div class="card"><p class="small muted">⚠ API kaliti borligi xizmat bepul yoki cheksiz degani emas. Pullik so'rovlar faqat Sozlamalarda "Pullik AI" yoqilgan va
      kunlik/oylik limit belgilangan bo'lsa yuboriladi (${ov.paid_ai_allowed ? "hozir: yoqilgan" : "hozir: o'chiq"}). Tekshiruvda bepul qadamlar (ulanish, modellar ro'yxati) har doim bajariladi.</p></div>
    <h3>Ulangan provayderlar</h3>
    <div class="grid" id="hplist" style="grid-template-columns:repeat(auto-fill,minmax(330px,1fr))">${list.length ? list.map(hubCard).join("") : '<div class="card muted">Hali ulanmagan — pastdan tanlang.</div>'}</div>
    <h3>Provayder qo'shish</h3>
    <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(210px,1fr))">${Object.entries(cat.providers).map(([k, p]) => `<div class="card" style="cursor:pointer" data-addp="${k}">
      <b>${esc(p.logo)} ${esc(p.title)}</b><div class="small muted">${esc(p.local ? "mahalliy" : p.gateway ? "gateway" : p.kind === "media" ? "rasm/video" : "bulut API")}${p.free_note ? " · " + esc(p.free_note) : ""}</div></div>`).join("")}</div>
    <div id="hpadd"></div>`;
  v.querySelectorAll("[data-addp]").forEach((el) => { el.onclick = () => hubAddForm($("#hpadd"), el.dataset.addp, v); });
  $("#hplist").onclick = async (e) => {
    const b = e.target.closest("button[data-h]"); if (!b) return;
    const pid = b.dataset.id, a = b.dataset.h, box = $(`#hpm_${pid}`);
    if (a === "del" && !confirm(`${pid} o'chirilsinmi? (kalit ham Credential Manager'dan o'chiriladi)`)) return;
    b.disabled = true; box.innerHTML = '<span class="muted">bajarilmoqda…</span>';
    try {
      if (a === "verify" || a === "test") { box.innerHTML = hubSteps(await post(`/api/ai/hub/providers/${pid}/verify?test_model=${a === "test"}`)); b.disabled = false; return; }
      if (a === "default") await post(`/api/ai/hub/providers/${pid}/default?task=chat`);
      if (a === "toggle") await post(`/api/ai/hub/providers/${pid}`, { enabled: b.dataset.en !== "1" });
      if (a === "del") await api(`/api/ai/hub/providers/${pid}`, { method: "DELETE" });
      if (a === "edit") { hubEditForm(box, pid, v); b.disabled = false; return; }
      renderProviderCenter(v);
    } catch (er) { fail(box, er); b.disabled = false; }
  };
}

function hubCard(p) {
  const u = p.usage, btn = (a, t, extra = "") => `<button class="ghost" data-h="${a}" data-id="${esc(p.id)}" ${extra}>${t}</button>`;
  return `<div class="card"><div class="row" style="justify-content:space-between;margin:0"><b>${esc(p.logo)} ${esc(p.title)} <span class="muted small">(${esc(p.id)})</span></b>
      ${hubPill(p.status, (HUB.cat.statuses[p.status] || p.status))}</div>
    <div class="kv"><span>Base URL</span><b class="small">${esc(p.base_url)}</b></div>
    <div class="kv"><span>Model</span><b>${esc(p.model)}</b></div><div class="kv"><span>Modellar (topilgan)</span><b>${p.models_count}</b></div>
    <div class="kv"><span>API kalit</span><b>${p.needs_key ? (p.key_set ? "🔒 kiritilgan" : "kiritilmagan") : "kerak emas"}</b></div>
    <div class="kv"><span>Turi</span><b>${p.local ? "mahalliy (bepul)" : "bulut (pullik bo'lishi mumkin)"}${p.enabled ? "" : " · o'chirilgan"}</b></div>
    <div class="kv"><span>Narx (1K token)</span><b>${p.local ? "—" : `${p.price_in_per_1k} / ${p.price_out_per_1k}`}</b></div>
    <div class="kv"><span>So'rov · xato · token</span><b>${u.requests} · ${u.errors} · ${u.tokens}</b></div>
    <div class="kv"><span>Xarajat (taxminiy)</span><b>${money(u.cost)}</b></div><div class="kv"><span>Oxirgi ishlatilgan</span><b>${esc(u.last_used || "—")}</b></div>
    <div class="small">Imkoniyatlar <span class="muted">(${p.caps_source === "name_guess" ? "taxmin" : esc(p.caps_source)})</span>: ${p.capabilities.map((c) => `<span class="pill">${esc(HUB.cat.capabilities[c] || c)}</span>`).join(" ")}</div>
    ${p.default_for.length ? `<div class="small">Standart: ${esc(p.default_for.join(", "))}</div>` : ""}
    ${p.blocked ? `<p class="small warn">Router vaqtincha ishlatmaydi: ${esc(p.blocked)}</p>` : ""}
    ${(u.recent_errors || []).length ? `<details class="small"><summary>Xatolar tarixi</summary>${u.recent_errors.map((e) => `<div>${esc(e.ts)} — ${esc(e.error)}</div>`).join("")}</details>` : ""}
    ${p.note ? `<p class="small muted">${esc(p.note)}</p>` : ""}
    <div class="row" style="margin-top:8px">${btn("verify", "API tekshirish")}${btn("test", "Modelni sinash")}${btn("default", "Standart qilish")}${btn("edit", "Tahrirlash")}
      ${btn("toggle", p.enabled ? "O'chirish" : "Yoqish", `data-en="${p.enabled ? 1 : 0}"`)}${btn("del", "Olib tashlash")}</div>
    <div id="hpm_${esc(p.id)}">${p.last_check ? `<details class="small"><summary>Oxirgi tekshiruv: ${esc(p.last_check.ts)}</summary>${hubSteps({ status: p.last_check.status, label: HUB.cat.statuses[p.last_check.status], note: p.last_check.note, steps: p.last_check.steps })}</details>` : ""}</div></div>`;
}

function hubAddForm(box, key, v) {
  const c = HUB.cat.providers[key];
  box.innerHTML = `<div class="card"><h3>${esc(c.logo)} ${esc(c.title)} — ulash</h3>${c.note ? `<p class="small warn">${esc(c.note)}</p>` : ""}
    ${c.key_url ? `<p class="small">Kalitni olish: <a href="${esc(c.key_url)}" target="_blank" rel="noopener">${esc(c.key_url)}</a></p>` : ""}
    <div class="row"><div style="flex:1"><label>Provayder ID</label><input id="hpid" value="${esc(key)}"></div>
      <div style="flex:1"><label>API turi</label><select id="hptype">${["openai_compatible", "anthropic", "ollama", "azure_openai"].map((t) => `<option ${t === c.kind ? "selected" : ""}>${t}</option>`).join("")}</select></div></div>
    <label>API Base URL</label><input id="hpurl" value="${esc(c.base_url)}">
    ${c.auth !== "none" ? '<label>API Key / Token 🔒</label><input id="hpkey" type="password" autocomplete="off" placeholder="kalitni qo\'ying — saqlangach avtomatik tekshiriladi">' : '<p class="small muted">Kalit talab qilinmaydi (mahalliy server).</p>'}
    <label>Model ID</label><input id="hpmodel" value="${esc(String(c.model || "").includes("<") ? "" : c.model || "")}" placeholder="bo'sh qoldirsangiz — ro'yxatdan tanlaysiz">
    <div class="row"><div style="flex:1"><label>Narx: kirish (1K token, USD)</label><input id="hpin" type="number" step="0.0001" min="0" value="0"></div>
      <div style="flex:1"><label>Narx: chiqish (1K token, USD)</label><input id="hpout" type="number" step="0.0001" min="0" value="0"></div></div>
    <label>Maxsus parametrlar (JSON, ixtiyoriy)</label><textarea id="hpparams" rows="2">${esc(JSON.stringify(c.params || {}))}</textarea>
    <p class="small muted">Kalit chatga, Telegram'ga yoki kodga yozilmaydi — faqat shu forma orqali Windows Credential Manager'ga.</p>
    <div class="row"><button id="hpsave">Saqlash va tekshirish</button></div><div id="hpmsg"></div></div>`;
  box.scrollIntoView({ behavior: "smooth" });
  $("#hpsave").onclick = async () => {
    const m = $("#hpmsg"); m.innerHTML = '<span class="muted">tekshirilmoqda…</span>';
    try {
      let params = {}; try { params = JSON.parse($("#hpparams").value || "{}"); } catch (e) { throw new Error("Parametrlar JSON noto'g'ri"); }
      const r = await post("/api/ai/hub/providers", { catalog_id: key, pid: $("#hpid").value.trim(), base_url: $("#hpurl").value.trim(), api_type: $("#hptype").value,
        api_key: ($("#hpkey").value || "").trim(), model: $("#hpmodel").value.trim(), params, price_in: +$("#hpin").value || 0, price_out: +$("#hpout").value || 0 });
      const k = $("#hpkey"); if (k) k.value = "";
      m.innerHTML = hubSteps(r.verification) + '<div class="row"><button class="ghost" id="hpdone">Ro\'yxatga qaytish</button></div>';
      $("#hpdone").onclick = () => renderProviderCenter(v);
    } catch (e) { fail(m, e); }
  };
}

function hubEditForm(box, pid, v) {
  box.innerHTML = `<label>Yangi API kalit (rotation) 🔒</label><input id="he_key" type="password" autocomplete="off" placeholder="bo'sh — o'zgarmaydi">
    <label>Model ID</label><input id="he_model"><label>Narx kirish / chiqish (1K token)</label><div class="row"><input id="he_in" type="number" step="0.0001" min="0"><input id="he_out" type="number" step="0.0001" min="0"></div>
    <div class="row"><button id="he_save">Saqlash</button></div><div id="he_msg"></div>`;
  $("#he_save").onclick = async () => {
    try { const body = {}; if ($("#he_key").value) body.api_key = $("#he_key").value; if ($("#he_model").value) body.model = $("#he_model").value;
      if ($("#he_in").value !== "") body.price_in_per_1k = +$("#he_in").value; if ($("#he_out").value !== "") body.price_out_per_1k = +$("#he_out").value;
      const r = await post(`/api/ai/hub/providers/${pid}`, body); $("#he_key").value = "";
      $("#he_msg").innerHTML = r.verification ? hubSteps(r.verification) : '<span class="pill ok">saqlandi</span>'; later(() => renderProviderCenter(v), r.verification ? 2500 : 600);
    } catch (e) { fail($("#he_msg"), e); } };
}

async function renderSmartRouter(v) {
  const [live, set, pr, log, list] = await Promise.all([api("/api/ai/live"), api("/api/settings"), api("/api/ai/presets"), api("/api/ai/log?limit=60"), api("/api/ai/hub/providers")]);
  const ids = list.map((p) => p.id);
  v.innerHTML = `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(360px,1fr))">
    <div class="card"><h3>Hozir ishlayotgan model</h3><div id="srlive"></div></div>
    <div class="card"><h3>Tanlash qoidalari va byudjet</h3>
      <label>Strategiya</label><select id="srs">${Object.entries(live.strategies).map(([k, t]) => `<option value="${k}" ${set.ai_strategy === k ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
      <label><input type="checkbox" id="srpaid" ${set.paid_ai_allowed ? "checked" : ""}> Pullik AI'ga ruxsat</label>
      <label><input type="checkbox" id="srconf" ${set.ai_confirm_paid ? "checked" : ""}> Pullik modelga o'tishdan oldin tasdiq so'ralsin</label>
      <div class="row"><div style="flex:1"><label>Kunlik limit (${esc(set.currency)})</label><input id="srday" type="number" min="0" step="0.01" value="${set.daily_cost_limit}"></div>
        <div style="flex:1"><label>Oylik limit</label><input id="srmon" type="number" min="0" step="0.01" value="${set.monthly_cost_limit}"></div>
        <div style="flex:1"><label>Bir so'rov maks.</label><input id="srreq" type="number" min="0" step="0.001" value="${set.ai_max_request_cost}"></div></div>
      <label>Faqat shu provayderlar (bo'sh — hammasi; mahalliy modellar doim ruxsat)</label>
      <div class="row">${ids.map((i) => `<label class="small"><input type="checkbox" data-ap="${esc(i)}" ${(set.ai_allowed_providers || []).includes(i) ? "checked" : ""}> ${esc(i)}</label>`).join("") || '<span class="muted small">Provayder yo\'q</span>'}</div>
      <p class="small muted">Limit tugasa yoki pullik API ishlamasa — router keyingi ruxsat berilgan modelga, keyin mahalliy Ollama'ga, oxirida JARVIS ichki funksiyalariga o'tadi.
        Maxfiy/shaxsiy ma'lumotli so'rov faqat mahalliy modelga ketadi.</p>
      <div class="row"><button id="srsave">Saqlash</button></div><div id="srmsg"></div></div>
    <div class="card"><h3>Vazifa → model</h3>${Object.entries(pr.task_types).map(([k, t]) => `<div class="kv"><span>${esc(t)}</span><select data-sr="${k}" style="max-width:170px"><option value="">avtomatik</option>
      ${ids.map((i) => `<option ${pr.routes[k] === i ? "selected" : ""}>${esc(i)}</option>`).join("")}</select></div>`).join("")}
      <div class="row" style="margin-top:8px"><button id="srroutes">Saqlash</button></div><div id="srrmsg"></div></div></div>
    <div class="card"><h3>So'rovlar jurnali</h3>${table(log.map((r) => ({ vaqt: r.ts, provayder: r.provider, model: r.model, vazifa: r.purpose || "chat", token: `${r.tokens_in ?? "?"}/${r.tokens_out ?? "?"}${r.tokens_measured ? "" : " (taxmin)"}`,
      xarajat: r.cost, "ms": r.duration_ms, natija: r.ok ? "ok" : "xato", fallback: r.fallback_from || "", xato: r.error || "" })), ["vaqt", "provayder", "model", "vazifa", "token", "xarajat", "ms", "natija", "fallback", "xato"])}</div>`;
  const drawLive = async () => {
    const el = $("#srlive"); if (!el.isConnected) return;
    const l = await api("/api/ai/live").catch(() => null); if (!l) return;
    const c = l.current, last = l.last;
    el.innerHTML = c ? `<div class="kv"><span>Current model</span><b>${esc(c.model)}</b></div><div class="kv"><span>Provider</span><b>${esc(c.provider)}</b></div>
        <div class="kv"><span>Status</span><b><span class="pill ok">ishlamoqda · ${c.elapsed_ms} ms</span></b></div><div class="kv"><span>Task</span><b>${esc(c.task_label || c.task)}</b></div>
        <div class="kv"><span>Fallback</span><b>${c.fallback ? `ha (${c.attempt}-urinish)` : "yo'q"}</b></div>`
      : last ? `<p class="muted small">Hozir so'rov yo'q. Oxirgisi:</p><div class="kv"><span>Model</span><b>${esc(last.provider)} · ${esc(last.model)}</b></div>
        <div class="kv"><span>Vazifa</span><b>${esc(last.task || "chat")}${last.capability ? ` (${esc(last.capability)})` : ""}</b></div><div class="kv"><span>Sabab</span><b class="small">${esc(last.reason)}</b></div>
        <div class="kv"><span>Fallback</span><b>${last.fallbacks.length ? esc(last.fallbacks.map((f) => f.provider).join(" → ")) : "yo'q"}</b></div><div class="kv"><span>Vaqt</span><b>${last.duration_ms} ms</b></div>`
      : '<p class="muted">Hali AI so\'rovi bo\'lmagan.</p>';
  };
  drawLive(); clearInterval(timer); timer = setInterval(drawLive, 1500);
  $("#srsave").onclick = async () => {
    try { await post("/api/settings", { ai_strategy: $("#srs").value, paid_ai_allowed: $("#srpaid").checked, ai_confirm_paid: $("#srconf").checked,
      daily_cost_limit: +$("#srday").value || 0, monthly_cost_limit: +$("#srmon").value || 0, ai_max_request_cost: +$("#srreq").value || 0,
      ai_allowed_providers: [...v.querySelectorAll("[data-ap]")].filter((x) => x.checked).map((x) => x.dataset.ap) });
    $("#srmsg").innerHTML = '<span class="pill ok">saqlandi</span>'; } catch (e) { fail($("#srmsg"), e); } };
  $("#srroutes").onclick = async () => {
    const routes = {}; v.querySelectorAll("[data-sr]").forEach((s) => { if (s.value) routes[s.dataset.sr] = s.value; });
    try { await post("/api/settings", { ai_task_routes: routes }); $("#srrmsg").innerHTML = '<span class="pill ok">saqlandi</span>'; } catch (e) { fail($("#srrmsg"), e); } };
}

async function renderModelCatalog(v) {
  const [cat, models, capmap, list] = await Promise.all([hubCatalog(), api("/api/ai/hub/models"), api("/api/ai/hub/capabilities"), api("/api/ai/hub/providers")]);
  const caps = cat.capabilities;
  v.innerHTML = `<div class="card"><h3>Imkoniyat → model (router tanlovi)</h3><div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(250px,1fr))">
      ${Object.entries(caps).map(([k, t]) => `<div><b class="small">${esc(t)}</b><div class="small ${capmap[k]?.length ? "" : "muted"}">${capmap[k]?.length ? capmap[k].slice(0, 4).map((m) => `${esc(m.provider)}: ${esc(m.model)}${m.source === "name_guess" ? " (taxmin)" : ""}`).join("<br>") : "ulangan model yo'q"}</div></div>`).join("")}</div>
      <p class="small muted">"taxmin" — imkoniyat model nomidan aniqlangan (tekshirilmagan). Provayder bergan ma'lumot yoki siz tasdiqlagan imkoniyat ishonchliroq.
        Rasm/video yaratish uchun maxsus model kerak — oddiy chat API bilan video yaratib bo'lmaydi.</p></div>
    <div class="card"><h3>Model qo'shish (ro'yxat endpointi bo'lmagan provayderlar uchun)</h3><div class="row">
      <select id="mcp">${list.map((p) => `<option>${esc(p.id)}</option>`).join("")}</select><input id="mcid" placeholder="Model ID"><button class="ghost" id="mcadd">Qo'shish</button></div><div id="mcmsg"></div></div>
    <div class="card"><h3>Modellar (${models.length})</h3><div class="row"><input id="mcq" placeholder="qidirish"></div><div id="mctab" style="max-height:560px;overflow:auto"></div></div>`;
  const draw = () => {
    const q = $("#mcq").value.toLowerCase(), rows = models.filter((m) => !q || (m.provider_id + m.model_id).toLowerCase().includes(q)).slice(0, 400);
    $("#mctab").innerHTML = `<table><tr><th>Provayder</th><th>Model</th><th>Imkoniyatlar</th><th>Manba</th><th>Kontekst</th><th>Narx/1K</th><th></th></tr>${rows.map((m, i) => `<tr>
      <td>${esc(m.provider_id)}</td><td>${esc(m.model_id)}${m.free ? ' <span class="pill ok">bepul</span>' : ""}</td><td class="small">${m.caps.map((c) => esc(caps[c] || c)).join(", ")}</td>
      <td class="small">${esc(m.caps_source === "name_guess" ? "taxmin" : m.caps_source)}</td><td>${esc(m.context_len || "")}</td><td class="small">${m.price_in != null ? `${(+m.price_in).toFixed(4)} / ${(+m.price_out).toFixed(4)}` : "—"}</td>
      <td><button class="ghost" data-mi="${i}">Imkoniyatlarni tahrirlash</button></td></tr>`).join("")}</table>`;
    $("#mctab").querySelectorAll("[data-mi]").forEach((b) => { b.onclick = () => {
      const m = rows[+b.dataset.mi], tr = b.closest("tr");
      tr.insertAdjacentHTML("afterend", `<tr><td colspan="7"><div class="row">${Object.entries(caps).map(([k, t]) => `<label class="small"><input type="checkbox" data-cc="${k}" ${m.caps.includes(k) ? "checked" : ""}> ${esc(t)}</label>`).join("")}</div>
        <button id="ccsave">Saqlash</button> <span id="ccmsg"></span></td></tr>`);
      $("#ccsave").onclick = async () => {
        try { await post(`/api/ai/hub/providers/${encodeURIComponent(m.provider_id)}/caps`, { model_id: m.model_id, caps: [...v.querySelectorAll("[data-cc]")].filter((x) => x.checked).map((x) => x.dataset.cc) });
          renderModelCatalog(v); } catch (e) { fail($("#ccmsg"), e); } };
    }; });
  };
  $("#mcq").oninput = draw; draw();
  $("#mcadd").onclick = async () => { try { await post(`/api/ai/hub/providers/${encodeURIComponent($("#mcp").value)}/models`, { model_id: $("#mcid").value.trim() }); renderModelCatalog(v); } catch (e) { fail($("#mcmsg"), e); } };
}

// ---------------- Memory Import Center ----------------
const MI = { sel: null, cat: "" };

async function renderMemoryImport(v) {
  const d = await api("/api/memory-import");
  v.innerHTML = `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(360px,1fr))">
    <div class="card"><h3>📥 ChatGPT eksportini yuklash</h3>
      <ol class="small"><li>ChatGPT → Settings → Data controls → <b>Export data</b>.</li><li>Emailga kelgan havoladan ZIP faylni yuklab oling.</li><li>Shu yerga yuklang.</li></ol>
      <p class="small muted">Tahlil shu kompyuterda bajariladi — suhbatlaringiz hech qaysi tashqi AI'ga yuborilmaydi. ZIP tahlildan keyin o'chiriladi.
        Eski suhbatlardagi buyruqlar bajarilmaydi — ular faqat tarixiy ma'lumot. Hech narsa siz tasdiqlamaguncha xotiraga yozilmaydi.
        Eslatma: ChatGPT'ning ichki "Memory" bo'limi eksportga kirmaydi — xotira suhbatlardan tuziladi.</p>
      <div class="row"><input type="file" id="mif" accept=".zip"><button id="miup">Yuklash va tahlil</button></div><div id="mimsg"></div></div>
    <div class="card"><h3>Importlar</h3>${d.imports.length ? table(d.imports.map((i) => ({ id: i.id, fayl: i.filename, holat: i.status + (i.status === "analyzing" ? ` ${i.progress}%` : ""),
      suhbatlar: i.stats?.conversations ?? "", nomzodlar: Object.values(i.counts || {}).reduce((a, b) => a + b, 0), import_qilingan: i.counts?.imported || 0, xato: i.error || "" })),
      ["id", "fayl", "holat", "suhbatlar", "nomzodlar", "import_qilingan", "xato"]) + `<div class="row" style="margin-top:8px">${d.imports.map((i) => `<button class="ghost" data-mio="${i.id}">#${i.id} ochish</button>`).join("")}</div>` : '<p class="muted">Hali import yo\'q.</p>'}</div></div>
    <div id="midet"></div>`;
  $("#miup").onclick = async () => {
    const f = $("#mif").files[0]; if (!f) return; const m = $("#mimsg");
    m.innerHTML = '<span class="muted">yuklanmoqda…</span>';
    try { const fd = new FormData(); fd.append("file", f);
      const res = await fetch("/api/memory-import/upload", { method: "POST", body: fd }); const r = await res.json(); if (!res.ok) throw new Error(r.detail || res.statusText);
      MI.sel = r.id; m.innerHTML = '<span class="muted">tahlil qilinmoqda…</span>';
      const poll = async () => { const s = await api(`/api/memory-import/${r.id}`); if (!m.isConnected) return;
        if (s.status === "analyzing") { m.innerHTML = `<span class="muted">tahlil: ${s.progress}%</span>`; setTimeout(poll, 800); } else renderMemoryImport(v); };
      poll();
    } catch (e) { fail(m, e); } };
  v.querySelectorAll("[data-mio]").forEach((b) => { b.onclick = () => { MI.sel = +b.dataset.mio; MI.cat = ""; miDetail($("#midet"), d.categories, v); }; });
  if (MI.sel && d.imports.some((i) => i.id === MI.sel && i.status !== "analyzing")) miDetail($("#midet"), d.categories, v);
}

async function miDetail(el, cats, v) {
  const iid = MI.sel, imp = await api(`/api/memory-import/${iid}`), st = imp.stats;
  if (!st) { el.innerHTML = `<div class="card">${imp.status === "failed" ? `<span class="bad">Xato: ${esc(imp.error)}</span>` : "Tahlil natijasi yo'q"}</div>`; return; }
  const items = await api(`/api/memory-import/${iid}/items?limit=300&category=${encodeURIComponent(MI.cat)}`);
  el.innerHTML = `<div class="card"><h3>Import #${iid}: ${esc(imp.filename)}</h3>
      <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(160px,1fr))">${[["Format", st.format], ["Suhbatlar", st.conversations], ["Xabarlar", st.messages], ["Davr", st.period ? st.period.join(" — ") : "—"],
        ["Mavjud xotirada bor", st.duplicates_existing], ["Maxfiy jumla (o'tkazildi)", st.skipped_secret_sentences]].map(([k, x]) => `<div><div class="muted small">${k}</div><b>${esc(x)}</b></div>`).join("")}</div>
      <p class="small">Mavzular: ${esc((st.topics || []).slice(0, 12).join(", "))}</p><p class="small">Texnologiyalar: ${esc(Object.keys(st.technologies || {}).join(", "))}</p>
      ${Object.keys(st.conflicts || {}).length ? `<p class="small warn">Qarama-qarshi ma'lumotlar: ${esc(Object.entries(st.conflicts).map(([k, x]) => `${k}: ${x.join(" / ")}`).join("; "))}</p>` : ""}
      ${(st.warnings || []).length ? `<details class="small"><summary>Arxiv ogohlantirishlari (${st.warnings.length})</summary>${st.warnings.map((w) => `<div>${esc(w)}</div>`).join("")}</details>` : ""}
      <details class="small"><summary>Arxiv tarkibi (${st.files_in_zip} fayl)</summary>${table(st.listing || [], ["name", "size"])}</details>
      <p class="small muted">${esc(st.note)}</p>
      <div class="tabs"><a data-mc="" class="${MI.cat ? "" : "active"}">Hammasi</a>${Object.entries(cats).map(([k, t]) => `<a data-mc="${k}" class="${MI.cat === k ? "active" : ""}">${esc(t)} (${st.candidates[k] || 0})</a>`).join("")}</div>
      <div class="row" style="margin-top:10px"><button id="miall" ${MI.cat ? "" : "disabled"}>✅ Shu kategoriyani import qilish</button><button class="ghost" id="mirej" ${MI.cat ? "" : "disabled"}>Shu kategoriyani rad etish</button>
        <button class="ghost" id="misel">Belgilanganlarni import qilish</button><button class="ghost" id="midel">Importni o'chirish</button><label class="small"><input type="checkbox" id="mipurge"> import qilingan xotiralarni ham o'chirish</label></div>
      <div id="mimsg2"></div>
      <table><tr><th></th><th>Kategoriya</th><th>Ma'lumot</th><th>Sana</th><th>Ishonch</th><th>Belgilar</th><th>Holat</th></tr>${items.map((i) => `<tr>
        <td>${["pending", "duplicate"].includes(i.status) ? `<input type="checkbox" data-it="${i.id}">` : ""}</td><td class="small">${esc(i.category_label)}</td>
        <td><div contenteditable="${i.status === "pending"}" data-ed="${i.id}" style="min-width:260px">${esc(i.content)}</div><div class="small muted">${esc(i.conv_title || "")}${i.evidence > 1 ? ` · ${i.evidence} marta uchradi` : ""}</div>
          ${i.conflict_note ? `<div class="small warn">${esc(i.conflict_note)}</div>` : ""}</td>
        <td class="small">${esc(i.conv_date || "")}</td><td>${Math.round(i.confidence * 100)}%</td>
        <td class="small">${i.flags.map((f) => ({ historical_instruction: "tarixiy ko'rsatma", conflict: "qarama-qarshi", unfinished: "tugallanmagan" }[f] || f)).map(esc).join(", ")}${i.info_type === "assumption" ? " taxmin" : ""}</td>
        <td class="small">${esc({ pending: "kutmoqda", duplicate: "xotirada bor", imported: "import qilindi", rejected: "rad etildi" }[i.status] || i.status)}</td></tr>`).join("")}</table></div>`;
  el.querySelectorAll("[data-mc]").forEach((a) => { a.onclick = () => { MI.cat = a.dataset.mc; miDetail(el, cats, v); }; });
  el.querySelectorAll("[data-ed]").forEach((d) => { d.onblur = async () => { try { await post(`/api/memory-import/items/${d.dataset.ed}`, { content: d.textContent }); } catch (e) { fail($("#mimsg2"), e); } }; });
  const act = async (body) => { try { const r = await post(`/api/memory-import/${iid}/decide`, body); $("#mimsg2").innerHTML = `<span class="pill ok">${r.done} ta bajarildi</span>${r.errors.length ? ` <span class="bad small">${esc(r.errors.join("; "))}</span>` : ""}`;
    later(() => miDetail(el, cats, v), 700); } catch (e) { fail($("#mimsg2"), e); } };
  $("#miall").onclick = () => act({ action: "import", category: MI.cat });
  $("#mirej").onclick = () => act({ action: "reject", category: MI.cat });
  $("#misel").onclick = () => { const ids = [...el.querySelectorAll("[data-it]")].filter((x) => x.checked).map((x) => +x.dataset.it); if (ids.length) act({ action: "import", ids }); };
  $("#midel").onclick = async () => { if (!confirm("Import va undagi nomzodlar o'chirilsinmi?")) return;
    try { await api(`/api/memory-import/${iid}?purge=${$("#mipurge").checked}`, { method: "DELETE" }); MI.sel = null; renderMemoryImport(v); } catch (e) { fail($("#mimsg2"), e); } };
}
