// JARVIS dashboard — v0.3 boshqaruv bo'limlari (router, xarajat, siyosat, bilim, qarorlar, graflar, kengaytmalar, sandbox, zaxira, diagnostika).
const STATUS_CLS = { ok: "ok", healthy: "ok", done: "ok", reused: "ok", enabled: "ok", warning: "warn", degraded: "warn", partial: "warn",
  waiting_approval: "warn", paused: "warn", unknown: "warn", running: "", error: "bad", down: "bad", failed: "bad", blocked: "bad",
  untrusted: "bad", invalid: "bad", cancelled: "muted", not_configured: "muted", disabled: "muted", pending: "muted" };
const pill = (s, text) => `<span class="pill ${STATUS_CLS[s] || ""}">${esc(text || s)}</span>`;
const memLabel = (m) => m.info_type === "fact" ? (m.verified && m.reference ? "Tasdiqlangan fakt" : "Tekshirilmagan fakt")
  : ({ assumption: "Taxmin", model_inference: "Model xulosasi", user_given: "Foydalanuvchi ma'lumoti" }[m.info_type] || m.info_type || "");

// ---------------- Diagnostika ----------------
async function renderDiagnostics(v) {
  v.innerHTML = `<div class="row"><label><input type="checkbox" id="ext" style="width:auto" checked> Tashqi xizmatlarni ham tekshirish</label>
    <button id="go">Tekshirish</button><a id="exp" href="/api/diagnostics/export" download><button class="ghost">Hisobotni eksport (JSON)</button></a></div><div id="r" class="muted">Tekshirilmoqda…</div>`;
  const run = async () => {
    const ext = $("#ext").checked; $("#exp").href = `/api/diagnostics/export?external=${ext}`;
    const d = await api(`/api/diagnostics?external=${ext}`);
    $("#r").innerHTML = `<div class="card"><h3>Umumiy holat</h3><div class="big">${pill(d.overall, { healthy: "sog'lom", degraded: "qisman muammo", down: "ishlamayapti" }[d.overall])}</div>
      <div class="muted">${Object.entries(d.counts).map(([k, n]) => `${k}: ${n}`).join(" · ")} — ${esc(d.note)}</div></div>
      <div class="card" style="margin-top:12px"><h3>Komponentlar</h3><table><tr><th>komponent</th><th>holat</th><th>tafsilot</th><th>ms</th><th>tekshirildi</th></tr>
      ${d.components.map((c) => `<tr><td>${esc(c.name)}</td><td>${pill(c.status)}</td><td>${esc(c.detail)}${c.last_success ? `<div class="muted">oxirgi muvaffaqiyatli ish: ${esc(c.last_success)}</div>` : ""}</td><td>${c.latency_ms ?? ""}</td><td class="muted">${esc(c.checked_at)}</td></tr>`).join("")}</table></div>
      <div class="grid" style="grid-template-columns:1fr 1fr;margin-top:12px"><div class="card"><h3>Xatolar toifalari</h3>${table(d.errors.by_category, ["label", "count", "latest", "latest_ts"])}</div>
      <div class="card"><h3>Resurslar (o'lchangan)</h3>${table([d.resources], Object.keys(d.resources))}</div></div>
      <div class="card" style="margin-top:12px"><h3>API javob vaqtlari</h3>${table(d.responses.slice(0, 25), ["route", "count", "p50_ms", "p95_ms", "max_ms", "errors_4xx", "errors_5xx"])}</div>`;
  };
  $("#go").onclick = run; run();
}

// ---------------- AI Router va xarajat ----------------
async function renderRouter(v) {
  const [r, g, s, q] = await Promise.all([api("/api/ai/router"), api("/api/guard"), api("/api/settings"), api("/api/ai/quality")]);
  const money = (x) => `${x} ${esc(g.limits.currency)}`;
  v.innerHTML = `<div class="grid">
    <div class="card"><h3>Bugun</h3><div class="big">${g.today.requests}</div><div class="muted">so'rov · xato ${g.today.failed} · ${money(g.today.cost)}</div></div>
    <div class="card"><h3>Shu oy</h3><div class="big">${money(g.month.cost)}</div><div class="muted">${g.month.requests} so'rov${g.month.cost_estimated_part ? ` · shundan taxminiy ${money(g.month.cost_estimated_part)}` : ""}</div></div>
    <div class="card"><h3>Tokenlar (bugun)</h3><div>o'lchangan: <b>${g.today.tokens_measured}</b></div><div>taxminiy: <b>${g.today.tokens_estimated}</b></div></div>
    <div class="card"><h3>Pullik AI</h3>${g.limits.paid_ai_allowed ? '<span class="warn">yoqilgan</span>' : '<span class="ok">o\'chiq</span>'}<div class="muted">kun ${money(g.limits.daily_cost_limit)} · oy ${money(g.limits.monthly_cost_limit)}</div></div></div>
    <div class="card" style="margin-top:12px"><h3>Provayderlar</h3>${table(r.providers.map((p) => ({ ...p, holat: p.available ? "mavjud" : "yo'q" })), ["id", "kind", "model", "tier", "local", "paid", "holat", "note", "price_in_per_1k", "price_out_per_1k"])}
      <div class="row" style="margin-top:10px;flex-wrap:wrap"><input id="pid" placeholder="id" style="width:110px"><select id="pkind" style="width:170px"><option>ollama</option><option>openai_compatible</option><option>anthropic</option></select>
      <input id="pmodel" placeholder="model" style="width:160px"><input id="purl" placeholder="base_url (tashqi uchun https://)" style="width:240px"><select id="ptier" style="width:100px"><option>light</option><option>strong</option></select>
      <input id="pin" type="number" step="0.0001" placeholder="narx kirish/1k" style="width:130px"><input id="pout" type="number" step="0.0001" placeholder="narx chiqish/1k" style="width:130px"><button id="padd">Qo'shish</button></div>
      <div class="muted">Tashqi kalit: yuqoridagi yo'riqnomadagi <code>ai_key_&lt;id&gt;</code> maydoniga kiriting. Narxlarni o'zingiz kiritasiz — xarajat shu narx bo'yicha hisoblanadi.</div><div id="pm"></div></div>
    <div class="grid" style="grid-template-columns:1fr 1fr;margin-top:12px"><div class="card"><h3>Model sifati (fikr + testlar)</h3>
      ${table(r.providers.filter((p) => p.kind !== "offline").map((p) => { const x = q[p.id] || {}; return { id: p.id, model: p.model, "👍": x.user_up || 0, "👎": x.user_down || 0,
        "test ✓": x.eval_pass || 0, "test ✗": x.eval_fail || 0, baho: x.votes ? `${Math.round(x.score * 100)}%${x.enough ? "" : " (kam)"}` : "—" }; }), ["id", "model", "👍", "👎", "test ✓", "test ✗", "baho"])}
      <div class="row" style="margin-top:8px">${r.providers.filter((p) => p.kind !== "offline" && p.available).map((p) => `<button class="ghost" data-ev="${esc(p.id)}">${esc(p.id)}: sinash</button>`).join("") || '<span class="muted">Sinash uchun mavjud model yo\'q</span>'}</div>
      <div class="muted">Chatdagi har javob ostida 👍/👎 bor. Kamida 5 ta baho to'plangach, bir xil darajadagi modellardan yaxshirog'i birinchi tanlanadi. Pullik model sinovi Cost Guard limitidan o'tadi.</div><pre id="evo" hidden></pre></div>
      <div class="card"><h3>Qayta urinishlar va xatolar (bugun)</h3>${table(g.reliability.ai, ["provider", "n", "failed", "retries", "fallbacks"])}
        <div style="margin-top:8px">Vazifalar: ${g.reliability.tasks_today.total} ta, xato ${g.reliability.tasks_today.failed}</div>
        ${g.reliability.errors_by_module.length ? table(g.reliability.errors_by_module, ["module", "n"]) : '<div class="muted">Bugun xato yo\'q</div>'}<div class="muted">${esc(g.reliability.note)}</div></div></div>
    <div class="grid" style="grid-template-columns:1fr 1fr;margin-top:12px"><div class="card"><h3>Xarajat limitlari</h3>
      <label><input type="checkbox" id="paid" style="width:auto" ${s.paid_ai_allowed ? "checked" : ""}> Pullik AI'ga ruxsat (limit doirasida)</label>
      <label>Kunlik limit</label><input id="dl" type="number" step="0.01" value="${s.daily_cost_limit}"><label>Oylik limit</label><input id="ml" type="number" step="0.01" value="${s.monthly_cost_limit}">
      <label>Kunlik so'rovlar limiti</label><input id="rl" type="number" value="${s.daily_request_limit}"><label>Ogohlantirish (%)</label><input id="wp" type="number" value="${s.cost_warn_percent}">
      <label>Valyuta</label><input id="cur" value="${esc(s.currency)}"><div class="row" style="margin-top:8px"><button id="lsave">Saqlash</button></div><div id="lm"></div></div>
      <div class="card"><h3>Routing sinovi</h3><textarea id="rt" placeholder="Matn kiriting — qaysi modelga ketishini ko'rasiz (so'rov yuborilmaydi)"></textarea><div class="row" style="margin-top:8px"><button class="ghost" id="rp">Ko'rish</button></div><pre id="ro" hidden></pre>
      <h3 style="margin-top:12px">Oxirgi marshrut</h3><pre>${esc(r.last_route ? JSON.stringify(r.last_route, null, 1) : "hali yo'q")}</pre></div></div>
    <div class="grid" style="grid-template-columns:1fr 1fr;margin-top:12px"><div class="card"><h3>Model ko'rsatkichlari</h3>${table(r.metrics, ["provider", "model", "n", "success_pct", "avg_ms", "cost", "fallbacks_in"])}</div>
      <div class="card"><h3>Resurslar</h3>${table([g.process], Object.keys(g.process))}<div style="margin-top:8px">Mahalliy model: ${g.local_model.measured ? table(g.local_model.models, ["name", "size_mb", "vram_mb"]) : `<span class="muted">${esc(g.local_model.note)}</span>`}</div>
      <h3 style="margin-top:12px">Vazifa vaqtlari</h3>${table(g.task_durations, ["agent", "n", "avg_ms", "failed"])}<div class="muted">${g.notes.map(esc).join("<br>")}</div></div></div>`;
  $("#padd").onclick = async () => {
    const p = { id: $("#pid").value.trim(), kind: $("#pkind").value, model: $("#pmodel").value.trim(), tier: $("#ptier").value, enabled: true,
      price_in_per_1k: Number($("#pin").value || 0), price_out_per_1k: Number($("#pout").value || 0) };
    if ($("#purl").value.trim()) p.base_url = $("#purl").value.trim();
    const list = (s.ai_providers || []).filter((x) => x.id !== p.id).concat([p]);
    try { await post("/api/settings", { ai_providers: list }); show(); } catch (e) { fail($("#pm"), e); }
  };
  $("#lsave").onclick = async () => { try { await post("/api/settings", { paid_ai_allowed: $("#paid").checked, daily_cost_limit: Number($("#dl").value), monthly_cost_limit: Number($("#ml").value),
    daily_request_limit: Number($("#rl").value), cost_warn_percent: Number($("#wp").value), currency: $("#cur").value }); $("#lm").innerHTML = '<span class="ok">Saqlandi</span>'; } catch (e) { fail($("#lm"), e); } };
  $("#rp").onclick = async () => out($("#ro"), await post("/api/ai/route-preview", { text: $("#rt").value }));
  v.addEventListener("click", async (e) => { const id = e.target.dataset.ev; if (!id) return;
    out($("#evo"), "Sinalmoqda…"); try { out($("#evo"), await post(`/api/ai/evaluate/${encodeURIComponent(id)}`)); later(show, 1500); } catch (er) { fail($("#evo"), er); } });
}

// ---------------- Policy ----------------
async function renderPolicy(v) {
  const [rows, s] = await Promise.all([api("/api/policy"), api("/api/settings")]);
  v.innerHTML = `<div class="card"><h3>Amallar siyosati</h3><p class="muted">low — avtomatik · medium — tasdiq (yoki siz belgilagan avtomatik) · high — har safar alohida tasdiq · forbidden — hech qachon.</p>
    <table><tr><th>amal</th><th>xavf</th><th>min. daraja</th><th>qaytariladimi</th><th>ta'sir</th><th>avtomatik</th></tr>${rows.map((r) => `<tr><td>${esc(r.action_type)}</td>
      <td>${pill({ low: "ok", medium: "warning", high: "error", forbidden: "error" }[r.risk], r.risk)}</td><td>${esc(r.min_level)}</td><td>${r.reversible ? "ha" : "yo'q"}</td><td>${esc(r.impact)}</td>
      <td>${r.risk === "medium" ? `<input type="checkbox" style="width:auto" data-auto="${esc(r.action_type)}" ${r.auto ? "checked" : ""}>` : (r.auto ? "ha" : "yo'q")}</td></tr>`).join("")}</table><div id="pm"></div></div>
    <div class="card" style="margin-top:12px"><h3>Buyruqlar allowlist'i (faqat settings.json orqali)</h3><div>${s.command_allowlist.map((c) => `<code>${esc(c)}</code>`).join(" ")}</div></div>
    <div class="card" style="margin-top:12px"><h3>Sinab ko'rish</h3><div class="row"><input id="at" placeholder="amal turi, masalan shell_command" style="width:240px"><input id="cmd" placeholder="buyruq (ixtiyoriy)"><button id="ev">Baholash</button></div><pre id="eo" hidden></pre></div>`;
  v.onchange = async (e) => { if (!e.target.dataset.auto) return;
    const list = [...document.querySelectorAll("[data-auto]")].filter((x) => x.checked).map((x) => x.dataset.auto);
    try { await post("/api/settings", { medium_auto_actions: list }); $("#pm").innerHTML = '<span class="ok">Siyosat saqlandi (audit jurnaliga yozildi)</span>'; } catch (er) { fail($("#pm"), er); } };
  $("#ev").onclick = async () => out($("#eo"), await post("/api/policy/evaluate", { op: $("#at").value.trim(), params: { command: $("#cmd").value || null } }));
}

// ---------------- Bilim manbalari (provenance) ----------------
async function renderKnowledge(v) {
  const stale = await api("/api/knowledge/stale");
  v.innerHTML = `<div class="card"><div class="row"><input id="q" placeholder="Mavzu — barcha manbalarni solishtirish"><button id="go">Solishtirish</button></div><div id="r"></div></div>
    <div class="card" style="margin-top:12px"><h3>Eskirgan ma'lumotlar</h3>${stale.length ? `<table>${stale.map((m) => `<tr><td>#${m.id}</td><td>${esc(m.content)}</td><td>${esc(m.label)}</td><td>${esc(m.observed_at || m.created_at)}</td><td>${esc(m.reference || m.source)}</td></tr>`).join("")}</table>` : '<span class="muted">Eskirgan yozuv yo\'q</span>'}</div>
    <div class="card" style="margin-top:12px"><h3>Yozuv manbasi</h3><div class="row"><input id="mid" type="number" placeholder="xotira #" style="width:140px"><button class="ghost" id="pv">Ko'rish</button></div><div id="po"></div></div>`;
  $("#go").onclick = async () => { const r = await api("/api/knowledge/compare?q=" + encodeURIComponent($("#q").value));
    $("#r").innerHTML = `<p><b>${esc(r.summary)}</b> · manbalar: ${r.sources.map(esc).join(", ") || "yo'q"}</p><table><tr><th>#</th><th>mazmun</th><th>turi</th><th>manba</th><th>sana</th><th>ishonch</th><th></th></tr>${r.items.map((i) => `<tr>
      <td>${i.id}</td><td>${esc(i.content)}${i.status === "conflict" ? ' <span class="warn">(zid)</span>' : ""}${i.stale ? ' <span class="warn">(eskirgan)</span>' : ""}</td><td>${esc(i.label)}</td><td>${esc(i.reference || i.source)}</td><td>${esc(i.date)}</td><td>${i.confidence}</td>
      <td>${i.label !== "Tasdiqlangan fakt" ? `<button class="ghost" data-ver="${i.id}">tekshirdim</button>` : ""}</td></tr>`).join("")}</table>`; };
  const showProv = async (id) => { const p = await api(`/api/memory/${id}/provenance`);
    $("#po").innerHTML = `<table>${[["Mazmun", p.memory.content], ["Turi", p.label], ["Manba", p.source], ["Havola", p.reference || "—"], ["Yozilgan", p.recorded_at], ["Manba sanasi", p.observed_at || "—"],
      ["Ishonch", p.confidence], ["Eskirganmi", p.stale ? "ha" : "yo'q"]].map(([k, x]) => `<tr><th>${k}</th><td>${esc(x)}</td></tr>`).join("")}</table>
      ${p.conflicts.length ? "<h3>Zid ma'lumotlar</h3>" + table(p.conflicts, ["id", "content", "label", "source", "reason"]) : ""}`; };
  $("#pv").onclick = () => showProv($("#mid").value).catch((e) => fail($("#po"), e));
  v.onclick = async (e) => { const id = e.target.dataset.ver; if (!id) return;
    const ref = prompt("Qaysi manba (havola yoki hujjat) bilan tekshirdingiz? Manbasiz tasdiqlanmaydi:"); if (!ref) return;
    try { await post(`/api/memory/${id}/verify`, { reference: ref }); $("#go").click(); } catch (er) { alert(er.message); } };
}

// ---------------- Qarorlar jurnali ----------------
async function renderDecisions(v) {
  const [list, due] = await Promise.all([api("/api/decisions"), api("/api/decisions/due")]);
  v.innerHTML = `${due.length ? `<div class="warnbox">Qayta ko'rib chiqish vaqti kelgan qarorlar: ${due.map((d) => "#" + d.id).join(", ")}</div>` : ""}
    <div class="grid" style="grid-template-columns:1fr 1fr"><div class="card"><h3>Yangi qaror</h3><input id="pr" placeholder="Muammo"><textarea id="op" placeholder="Variantlar (har qatorda bittadan)" style="min-height:60px;margin-top:6px"></textarea>
      <input id="ch" placeholder="Tanlangan variant (ro'yxatdagidek)" style="margin-top:6px"><textarea id="ra" placeholder="Sabab" style="min-height:50px;margin-top:6px"></textarea>
      <input id="src" placeholder="Manbalar (vergul bilan)" style="margin-top:6px"><input id="rk" placeholder="Xavf va cheklovlar" style="margin-top:6px"><input id="ex" placeholder="Kutilgan natija" style="margin-top:6px">
      <input id="fl" placeholder="Ta'sir qiladigan fayllar (vergul bilan)" style="margin-top:6px"><input id="pj" placeholder="Loyiha" style="margin-top:6px"><input id="rv" type="date" style="margin-top:6px">
      <div class="row" style="margin-top:8px"><button id="mk">Saqlash</button></div><div id="mm"></div></div>
      <div class="card"><h3>Qarorlar</h3><div class="row"><input id="q" placeholder="qidirish"><button class="ghost" id="qs">Qidirish</button></div><div id="lst"></div><div id="det"></div></div></div>`;
  const csv = (x) => x.split(",").map((s) => s.trim()).filter(Boolean);
  const draw = (rows) => { $("#lst").innerHTML = `<table>${rows.map((d) => `<tr><td>#${d.id}</td><td>${esc(d.problem)}</td><td>${esc(d.chosen)}</td><td>${pill(d.status === "superseded" ? "cancelled" : d.status === "reviewed" ? "ok" : "running", d.status)}</td>
    <td><button class="ghost" data-d="${d.id}">ochish</button></td></tr>`).join("")}</table>`; };
  draw(list);
  $("#qs").onclick = async () => draw(await api("/api/decisions?q=" + encodeURIComponent($("#q").value)));
  $("#mk").onclick = async () => { try { await post("/api/decisions", { problem: $("#pr").value, options: $("#op").value.split("\n").map((s) => s.trim()).filter(Boolean), chosen: $("#ch").value.trim(),
    rationale: $("#ra").value, sources: csv($("#src").value), risks: $("#rk").value, expected_outcome: $("#ex").value, files: csv($("#fl").value), project: $("#pj").value, review_at: $("#rv").value }); show(); } catch (e) { fail($("#mm"), e); } };
  v.onclick = async (e) => { const d = e.target.dataset; try {
    if (d.d) { const x = await api(`/api/decisions/${d.d}`);
      $("#det").innerHTML = `<h3 style="margin-top:12px">#${x.id} ${esc(x.problem)}</h3><table>${[["Variantlar", x.options.join(" | ")], ["Tanlangan", x.chosen], ["Sabab", x.rationale], ["Manbalar", x.sources.join(", ")], ["Xavflar", x.risks], ["Kutilgan natija", x.expected_outcome],
        ["Haqiqiy natija", x.actual_outcome || "—"], ["Qayta ko'rish", x.review_at || "—"], ["Fayllar", x.files.join(", ")], ["Zanjir", x.chain.map((c) => `#${c.id}:${c.chosen}(${c.status})`).join(" → ")]].map(([k, val]) => `<tr><th>${k}</th><td style="white-space:pre-wrap">${esc(val)}</td></tr>`).join("")}</table>
        <h3>O'zgarishlar tarixi</h3>${table(x.events, ["ts", "field", "old_value", "new_value", "note"])}
        ${x.status !== "superseded" ? `<div class="row" style="margin-top:8px"><button class="ghost" data-res="${x.id}">Haqiqiy natijani yozish</button><button data-rev="${x.id}">Qayta ko'rib chiqish</button></div>` : '<div class="muted">Almashtirilgan qaror — tarix saqlanadi.</div>'}`; }
    if (d.res) { const t = prompt("Haqiqiy natija:"); if (t) { await post(`/api/decisions/${d.res}/update`, { actual_outcome: t, note: "dashboard" }); $(`[data-d="${d.res}"]`).click(); } }
    if (d.rev) { const reason = prompt("Qayta ko'rib chiqish sababi (yangi ma'lumot):"); if (!reason) return; const ch = prompt("Yangi tanlov (variantlardan biri):"); if (!ch) return;
      const x = await api(`/api/decisions/${d.rev}`); const r = await post(`/api/decisions/${d.rev}/revise`, { reason, changes: { chosen: ch, options: x.options.includes(ch) ? x.options : x.options.concat([ch]) } });
      alert(`Yangi qaror #${r.new.id} yaratildi; #${r.old.id} tarixda saqlandi.`); show(); }
  } catch (er) { alert(er.message); } };
}

// ---------------- Vazifalar grafi (DAG) ----------------
function dagSvg(g) {
  const levels = {}; g.nodes.forEach((n) => { (levels[n.level] = levels[n.level] || []).push(n); });
  const W = 190, H = 54, GX = 60, GY = 18, pos = {};
  const cols = Object.keys(levels).map(Number).sort((a, b) => a - b);
  const maxRows = Math.max(...cols.map((c) => levels[c].length));
  cols.forEach((c) => levels[c].forEach((n, i) => { pos[n.key] = { x: 10 + c * (W + GX), y: 10 + i * (H + GY) }; }));
  const color = (s) => ({ done: "#059669", reused: "#059669", running: "#4f46e5", failed: "#dc2626", blocked: "#dc2626", waiting_approval: "#d97706", cancelled: "#94a3b8" }[s] || "#94a3b8");
  const width = 20 + cols.length * (W + GX), height = 20 + maxRows * (H + GY);
  return `<svg viewBox="0 0 ${width} ${height}" style="width:100%;max-width:${width}px;height:auto" role="img" aria-label="vazifalar grafi">
    <defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#94a3b8"/></marker></defs>
    ${g.edges.map((e) => { const a = pos[e.from], b = pos[e.to]; return `<path d="M${a.x + W},${a.y + H / 2} C${a.x + W + GX / 2},${a.y + H / 2} ${b.x - GX / 2},${b.y + H / 2} ${b.x},${b.y + H / 2}" fill="none" stroke="#94a3b8" stroke-width="1.5" marker-end="url(#ar)"/>`; }).join("")}
    ${g.nodes.map((n) => { const p = pos[n.key]; return `<g><rect x="${p.x}" y="${p.y}" width="${W}" height="${H}" rx="9" fill="#ffffff" stroke="${color(n.status)}" stroke-width="2"/>
      <text x="${p.x + 10}" y="${p.y + 20}" fill="#0f172a" font-size="12">${esc(n.title.slice(0, 26))}</text>
      <text x="${p.x + 10}" y="${p.y + 40}" fill="${color(n.status)}" font-size="11">${esc(n.agent)} · ${esc(n.status)}</text><title>${esc(n.error || n.title)}</title></g>`; }).join("")}</svg>`;
}

async function renderDag(v) {
  const runs = await api("/api/dag");
  v.innerHTML = `<div class="card"><h3>Yangi graf</h3><div class="row"><input id="goal" placeholder="Masalan: xavfsizlikni tekshir hamda fayllarni ko'rsat keyin savdo hisoboti"><button id="mk">Yaratish</button></div>
    <div class="muted">"keyin" — ketma-ket bosqich; "hamda" yoki "&" — parallel vazifalar. Parallel faqat resurs yetarli bo'lsa va har agent bittadan.</div><div id="m"></div></div>
    ${runs.map((g) => `<div class="card" style="margin-top:12px"><div class="row" style="justify-content:space-between"><b>#${g.id} ${esc(g.goal)}</b><span>${pill(g.status)} ${g.max_parallel ? `<span class="muted">parallel: ${g.max_parallel}</span>` : ""}</span></div>
      <div style="overflow-x:auto">${dagSvg(g)}</div><div class="muted">${Object.entries(g.counts).map(([k, n]) => `${k}: ${n}`).join(" · ")}</div>
      <div class="row" style="margin-top:8px">${["pending", "waiting_approval", "running", "partial"].includes(g.status) ? `<button data-run="${g.id}">Bajarish / davom ettirish</button><button class="danger" data-cancel="${g.id}">Bekor qilish</button>` : ""}</div>
      ${g.nodes.some((n) => n.error) ? table(g.nodes.filter((n) => n.error), ["key", "status", "error"]) : ""}</div>`).join("")}`;
  $("#mk").onclick = async () => { try { await post("/api/dag", { goal: $("#goal").value }); show(); } catch (e) { fail($("#m"), e); } };
  v.onclick = async (e) => { const d = e.target.dataset; try {
    if (d.run) { e.target.textContent = "Bajarilmoqda…"; await post(`/api/dag/${d.run}/run`, {}); show(); }
    if (d.cancel && confirm("Grafni bekor qilasizmi? Yangi vazifalar boshlanmaydi.")) { await post(`/api/dag/${d.cancel}/cancel`); show(); }
  } catch (er) { alert(er.message); } };
}

// ---------------- Knowledge Graph ----------------
function kgSvg(data) {
  const W = 760, H = 460, cx = W / 2, cy = H / 2, others = data.nodes.filter((n) => n.id !== data.center), pos = {};
  pos[data.center] = { x: cx, y: cy };
  others.forEach((n, i) => { const a = (2 * Math.PI * i) / Math.max(1, others.length), r = 170 + (i % 2) * 30; pos[n.id] = { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) }; });
  const col = { project: "#0ea5e9", task: "#4f46e5", agent: "#059669", memory: "#8b5cf6", decision: "#d97706", file: "#ea580c", source: "#64748b", error: "#dc2626", proposal: "#16a34a" };
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto" role="img" aria-label="bilimlar grafi">
    ${data.edges.filter((e) => pos[e.src] && pos[e.dst]).map((e) => { const a = pos[e.src], b = pos[e.dst]; return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="#cbd5e1"/><text x="${(a.x + b.x) / 2}" y="${(a.y + b.y) / 2}" fill="#64748b" font-size="10" text-anchor="middle">${esc(e.rel_uz)}</text>`; }).join("")}
    ${data.nodes.map((n) => { const p = pos[n.id]; if (!p) return ""; return `<g data-kg="${n.id}" style="cursor:pointer"><circle cx="${p.x}" cy="${p.y}" r="${n.id === data.center ? 11 : 7}" fill="${col[n.type] || "#475569"}"/>
      <text x="${p.x}" y="${p.y - 13}" fill="#0f172a" font-size="11" text-anchor="middle">${esc(n.type)}: ${esc(n.label.slice(0, 28))}</text></g>`; }).join("")}</svg>`;
}

async function renderKG(v) {
  const st = await api("/api/kg");
  v.innerHTML = `<div class="card"><div class="row"><input id="q" placeholder="Qidirish: loyiha, fayl, agent, qaror…"><select id="t" style="width:150px"><option value="">barcha turlar</option>${Object.keys(st.by_type).map((t) => `<option>${esc(t)}</option>`).join("")}</select>
    <button id="go">Qidirish</button><button class="ghost" id="rb">Mavjud ma'lumotlardan qayta qurish</button></div>
    <div class="muted">${st.nodes} tugun · ${st.edges} aloqa · ${Object.entries(st.by_type).map(([k, n]) => `${k}: ${n}`).join(", ")}</div><div id="res"></div></div>
    <div class="card" style="margin-top:12px"><div id="g" class="muted">Tugunni tanlang — bog'lanishlari ko'rinadi (tugunni bosib keyingisiga o'tasiz).</div><div id="e"></div></div>`;
  const open = async (id) => { const d = await api(`/api/kg/node/${id}?depth=1`);
    $("#g").innerHTML = kgSvg(d);
    const lab = Object.fromEntries(d.nodes.map((n) => [n.id, `${n.type}: ${n.label}`]));
    const c = d.nodes.find((n) => n.id === d.center) || {};
    $("#e").innerHTML = `<div class="row" style="margin-top:10px"><b>${esc(c.type)}: ${esc(c.label)}</b>
      <span class="pill">manba: ${esc(c.source || "—")}</span><span class="pill">olingan: ${esc(c.observed_at || c.created_at || "—")}</span>
      ${c.verified ? '<span class="pill ok">tekshirilgan</span>' : '<span class="pill warn">tekshirilmagan</span>'}
      ${c.section ? `<a href="#${esc(c.section)}"><button class="ghost">Tegishli bo'limga o'tish →</button></a>` : ""}</div>` + table(d.edges.map((x) => ({ dan: lab[x.src], aloqa: x.rel_uz, ga: lab[x.dst] })), ["dan", "aloqa", "ga"]); };
  $("#go").onclick = async () => { const r = await api(`/api/kg/search?q=${encodeURIComponent($("#q").value)}&type=${$("#t").value}`);
    $("#res").innerHTML = r.length ? r.map((n) => `<button class="ghost" style="margin:3px" data-kg="${n.id}">${esc(n.type)}: ${esc(n.label.slice(0, 40))}</button>`).join("") : '<span class="muted">Topilmadi</span>'; };
  $("#rb").onclick = async () => { await post("/api/kg/rebuild"); show(); };
  v.onclick = (e) => { const el = e.target.closest("[data-kg]"); if (el) open(el.dataset.kg); };
}

// ---------------- Kengaytmalar ----------------
async function renderPlugins(v) {
  const ps = await api("/api/plugins");
  v.innerHTML = `<div class="warnbox">Kengaytmalar ishonchsiz deb boshlanadi. Yoqish — aniq versiya, fayl xeshi va ruxsatlar bilan tasdiq. Fayllar o'zgarsa, qayta tasdiq kerak. Kod sandbox'da ishlaydi.</div>
    ${ps.map((p) => `<div class="card" style="margin-bottom:10px"><div class="row" style="justify-content:space-between"><b>${esc(p.name)} <span class="muted">v${esc(p.version)} · ${esc(p.source)}</span></b>${pill(p.status)}</div>
      <div>${esc(p.description)}</div><div class="muted">Ruxsatlar: ${p.permissions.length ? p.permissions.map((x) => `<code>${esc(x)}</code> — ${esc(p.permission_info[x])}`).join("; ") : "yo'q"}
      · Bog'liqliklar: ${p.dependencies.join(", ") || "yo'q"}${p.missing_dependencies.length ? ` <span class="bad">(o'rnatilmagan: ${p.missing_dependencies.join(", ")})</span>` : ""} · ishga tushgan: ${p.runs}, xato: ${p.errors}</div>
      ${p.last_error ? `<div class="bad">${esc(p.last_error)}</div>` : ""}
      ${Object.keys(p.config_schema).length ? `<div class="row" style="margin-top:6px;flex-wrap:wrap">${Object.entries(p.config_schema).map(([k, sc]) => `<label>${esc(k)} <input data-cfg="${esc(p.name)}" data-key="${esc(k)}" data-type="${sc.type}" value="${esc(p.config[k] ?? sc.default ?? "")}" style="width:110px" title="${esc(sc.description || "")}"></label>`).join("")}<button class="ghost" data-savecfg="${esc(p.name)}">Sozlamani saqlash</button></div>` : ""}
      <div class="row" style="margin-top:8px">${["disabled", "untrusted", "error"].includes(p.status) ? `<button data-req="${esc(p.name)}">Yoqishni so'rash</button>` : ""}
      ${p.status === "enabled" ? `<input data-in="${esc(p.name)}" placeholder='kirish JSON, masalan {"cost": 10000}'><button data-run="${esc(p.name)}">Ishga tushirish</button><button class="ghost" data-st="paused" data-n="${esc(p.name)}">To'xtatish</button>` : ""}
      ${p.status === "paused" ? `<button data-st="enabled" data-n="${esc(p.name)}">Davom ettirish</button>` : ""}${!["disabled", "invalid"].includes(p.status) ? `<button class="danger" data-st="disabled" data-n="${esc(p.name)}">O'chirish</button>` : ""}
      <button class="ghost" data-logs="${esc(p.name)}">jurnal</button></div><pre id="o_${esc(p.name)}" hidden></pre></div>`).join("") || '<div class="card muted">Kengaytma yo\'q</div>'}`;
  v.onclick = async (e) => { const d = e.target.dataset; const o = (n) => $(`#o_${n}`); try {
    if (d.req) { const a = await post(`/api/plugins/${d.req}/request-enable`);
      if (confirm(`Tasdiq #${a.id} yaratildi:\n${a.summary}\n\nTasdiqlashlar bo'limiga o'tasizmi? Tasdiqlagach, shu yerga qaytib «Yoqishni yakunlash»ni bosasiz.`)) location.hash = "approvals";
      o(d.req).hidden = false; o(d.req).innerHTML = `<button data-fin="${esc(d.req)}" data-aid="${a.id}">Yoqishni yakunlash (tasdiqdan keyin)</button>`; }
    if (d.fin) { out(o(d.fin), await post(`/api/plugins/${d.fin}/enable`, { approval_id: Number(d.aid) })); later(show, 800); }
    if (d.run) { const inp = $(`[data-in="${d.run}"]`).value.trim(); out(o(d.run), await post(`/api/plugins/${d.run}/run`, { input: inp ? JSON.parse(inp) : {} })); }
    if (d.st) { await post(`/api/plugins/${d.n}/status`, { status: d.st }); show(); }
    if (d.logs) out(o(d.logs), await api(`/api/plugins/${d.logs}/logs`));
    if (d.savecfg) { const cfg = {}; document.querySelectorAll(`[data-cfg="${d.savecfg}"]`).forEach((i) => { cfg[i.dataset.key] = i.dataset.type === "number" ? Number(i.value) : i.dataset.type === "boolean" ? i.value === "true" : i.value; });
      out(o(d.savecfg), await post(`/api/plugins/${d.savecfg}/config`, cfg)); }
  } catch (er) { const n = d.req || d.run || d.fin || d.n || d.savecfg || d.logs; if (n && o(n)) fail(o(n), er); else alert(er.message); } };
}

// ---------------- Sandbox ----------------
async function renderSandbox(v) {
  const d = await api("/api/sandbox");
  const iso = d.isolation;
  v.innerHTML = `<div class="grid" style="grid-template-columns:1fr 1fr"><div class="card"><h3>Izolyatsiya darajasi</h3><div><b>${esc(iso.level)}</b> · backend: ${esc(iso.backend)} · Docker: ${iso.docker_available ? "bor" : "yo'q"}</div>
      <div class="ok" style="margin-top:6px">${iso.guarantees.map((x) => "✓ " + esc(x)).join("<br>")}</div><div class="warn" style="margin-top:6px">${iso.not_guaranteed.map((x) => "✗ " + esc(x)).join("<br>")}</div>
      ${iso.recommendation ? `<p class="muted">${esc(iso.recommendation)}</p>` : ""}<div class="muted">Limitlar: ${iso.limits.timeout_sec} s, ${iso.limits.memory_mb} MB, qayta urinish ${iso.limits.max_retries}</div></div>
    <div class="card"><h3>Python kodini sinash</h3><textarea id="code" style="min-height:140px">print("Salom, sandbox!")</textarea>
      <label><input type="checkbox" id="netw" style="width:auto"> Tarmoqqa ruxsat (E-darajali tasdiq talab qiladi)</label>
      <div class="row" style="margin-top:8px"><button id="run">Ishga tushirish</button></div><pre id="o" hidden></pre></div></div>
    <div class="card" style="margin-top:12px"><h3>Natijalar tarixi</h3>${table(d.history.map((h) => ({ ...h, findings: h.findings.length + " ta topilma" })), ["id", "ts", "kind", "status", "exit_code", "duration_ms", "peak_mem_mb", "findings", "backend"])}</div>`;
  let pendingApproval = null;
  $("#run").onclick = async () => { try {
    const r = await post("/api/sandbox/python", { code: $("#code").value, allow_network: $("#netw").checked, approval_id: pendingApproval });
    if (!$("#o").isConnected) return;
    if (r.status === "needs_approval") { pendingApproval = r.approval.id;
      $("#o").hidden = false; $("#o").textContent = `Xavfli qismlar topildi — tasdiq #${r.approval.id} kerak (Tasdiqlashlar bo'limi). Tasdiqlagach, qayta "Ishga tushirish"ni bosing.\n\n` + r.findings.map((f) => `${f.severity} ${f.line}: ${f.msg}`).join("\n"); return; }
    pendingApproval = null; out($("#o"), `holat: ${r.status} · exit ${r.exit_code} · ${r.duration_ms} ms · xotira ${r.peak_mem_mb ?? "?"} MB\n--- stdout ---\n${r.stdout}\n--- stderr ---\n${r.stderr}`);
  } catch (e) { fail($("#o"), e); } };
}

// ---------------- Zaxira nusxalar ----------------
async function renderBackups(v) {
  const d = await api("/api/backups");
  const s = d.status;
  v.innerHTML = `<div class="grid"><div class="card"><h3>Oxirgi nusxa</h3><div class="big ${s.overdue ? "warn" : "ok"}">${s.age_hours == null ? "yo'q" : s.age_hours + " soat"}</div><div class="muted">jadval: har ${s.interval_hours} soat · avto: ${s.auto_running ? "ishlayapti" : "server ishga tushganda"}</div></div>
    <div class="card"><h3>Nusxalar</h3><div class="big">${s.count}</div><div class="muted">${s.total_mb} MB · ${esc(s.directory)}</div></div>
    <div class="card"><h3>Oxirgi xato</h3>${s.last_failure ? `<div class="bad">${esc(s.last_failure.action)}: ${esc(s.last_failure.error || s.last_failure.name || "")}</div><div class="muted">${esc(s.last_failure.ts)}</div>` : '<span class="ok">yo\'q</span>'}</div></div>
    <div class="card" style="margin-top:12px"><div class="row"><button id="mk">Hozir nusxa olish</button><label><input type="checkbox" id="ws" style="width:auto"> workspace fayllari bilan</label></div><pre id="o" hidden></pre>
      ${d.items.length ? `<table><tr><th>nom</th><th>sana</th><th>belgi</th><th>hajm</th><th>tekshiruv</th><th></th></tr>${d.items.map((i) => `<tr><td>${esc(i.name)}</td><td>${esc(i.created)}</td><td>${esc(i.label)}</td><td>${(i.size / 1024).toFixed(0)} KB</td>
        <td>${i.last_verify ? pill(i.last_verify.ok ? "ok" : "error", i.last_verify.ok ? "o'tdi" : "o'tmadi") : '<span class="muted">tekshirilmagan</span>'}</td>
        <td><button class="ghost" data-ver="${esc(i.name)}">tekshirish</button> <button class="danger" data-rr="${esc(i.name)}">tiklash</button></td></tr>`).join("")}</table>` : '<p class="muted">Hali nusxa yo\'q</p>'}</div>
    <div class="card" style="margin-top:12px"><h3>Tarix</h3>${table(d.history, ["ts", "action", "ok", "name", "label", "error"])}<p class="muted">Tiklash tartibi: docs/BACKUP.md. Maxfiy kalitlar nusxaga kirmaydi.</p></div>`;
  $("#mk").onclick = async () => { try { out($("#o"), await post("/api/backups", { label: "dashboard", include_workspace: $("#ws").checked })); later(show, 800); } catch (e) { fail($("#o"), e); } };
  v.onclick = async (e) => { const d2 = e.target.dataset; try {
    if (d2.ver) { const r = await post(`/api/backups/${encodeURIComponent(d2.ver)}/verify`); out($("#o"), r.checks.map((c) => `${c.ok ? "OK  " : "XATO"} ${c.check} ${c.note || ""}`).join("\n")); }
    if (d2.rr) { if (!confirm(`DIQQAT: ma'lumotlar ${d2.rr} holatiga qaytariladi. Davom etasizmi? (avval tasdiq so'raladi)`)) return;
      const a = await post(`/api/backups/${encodeURIComponent(d2.rr)}/request-restore`);
      $("#o").hidden = false; $("#o").innerHTML = `E-darajali tasdiq #${a.id} yaratildi. <a href="#approvals">Tasdiqlang</a>, keyin: <button data-fin="${esc(d2.rr)}" data-aid="${a.id}">Tiklashni bajarish</button>`; }
    if (d2.fin) { out($("#o"), await post(`/api/backups/${encodeURIComponent(d2.fin)}/restore`, { approval_id: Number(d2.aid) })); }
  } catch (er) { fail($("#o"), er); } };
}
