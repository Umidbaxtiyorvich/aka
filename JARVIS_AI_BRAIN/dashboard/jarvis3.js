// JARVIS 3.0 sahifalari: Digital Twin, Guardian & Proactive (avtonomlik darajasi), Asset Manager, Simulation Lab,
// Knowledge Researcher, Business Command Center, Creative Factory, Skills Factory, Everywhere (qurilmalar). Hammasi real backend API.
"use strict";

const LVL = ["0 — faqat maslahat", "1 — reja va tasdiq", "2 — xavfsiz amallarni o'zi bajaradi (Safe, tavsiya)", "3 — agentlarni boshqaradi", "4 — to'liq sikl (o'zi davom ettiradi)"];
const GST = { ok: "ok", warn: "warn", bad: "bad" };
const fmtSize = (b) => (b > 2 ** 30 ? `${(b / 2 ** 30).toFixed(1)} GB` : b > 2 ** 20 ? `${(b / 2 ** 20).toFixed(1)} MB` : `${Math.round((b || 0) / 1024)} KB`);

async function renderTwin(v) {
  const d = await api("/api/twin");
  const secs = d.profile.sections;
  v.innerHTML = `<div class="card"><h3>🪞 Raqamli egizak</h3><p class="small muted">${esc(d.profile.note)} JARVIS bu profil asosida faqat TAKLIF beradi — sizning nomingizdan qaror qabul qilmaydi
      va profil tashqi AI'ga avtomatik yuborilmaydi.</p>
    <h3>Takliflar</h3>${d.suggestions.length ? d.suggestions.map((s) => `<div class="kv"><span>${esc(s.text)}</span>${s.link ? `<a href="${s.link}">ochish</a>` : ""}</div>`).join("") : '<p class="muted">Hozircha taklif yo\'q.</p>'}</div>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(340px,1fr))">${Object.entries(secs).map(([k, s]) => `<div class="card"><h3>${esc(s.title)} (${s.items.length})</h3>
      ${s.items.length ? s.items.map((i) => `<div class="kv"><span><span contenteditable="true" data-tw="${i.id}">${esc(i.content)}</span>
        <div class="small muted">${esc(i.source)} · ${esc(i.date || "")}</div></span><button class="ghost" data-twd="${i.id}" title="O'chirish">🗑</button></div>`).join("")
      : '<p class="muted small">Ma\'lumot yo\'q</p>'}</div>`).join("")}</div><div id="twmsg"></div>`;
  v.querySelectorAll("[data-tw]").forEach((el) => { el.onblur = async () => { try { await post(`/api/twin/${el.dataset.tw}`, { content: el.textContent.trim() }); } catch (e) { fail($("#twmsg"), e); } }; });
  v.querySelectorAll("[data-twd]").forEach((b) => { b.onclick = async () => { if (!confirm("Bu ma'lumot xotiradan o'chirilsinmi?")) return;
    try { await api(`/api/twin/${b.dataset.twd}`, { method: "DELETE" }); renderTwin(v); } catch (e) { fail($("#twmsg"), e); } }; });
}

async function renderGuardian(v) {
  const [g, p, set] = await Promise.all([api("/api/guardian"), api("/api/proactive"), api("/api/settings")]);
  v.innerHTML = `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(360px,1fr))">
    <div class="card"><h3>🛡 Tizim qo'riqchisi <span class="pill ${GST[g.overall]}">${esc(g.overall)}</span></h3>
      ${g.checks.map((c) => `<div class="kv"><span>${esc(c.title)}${c.note ? `<div class="small muted">${esc(c.note)}</div>` : ""}</span><span>
        <span class="pill ${GST[c.status]}">${esc(c.value)}</span>${c.action ? ` <button class="ghost" data-ga="${c.action}">${esc(g.actions[c.action].split(" (")[0])}</button>` : ""}</span></div>`).join("")}
      <div class="row" style="margin-top:10px"><button class="bad" data-ga="emergency_stop">⛔ Favqulodda to'xtatish</button><button class="ghost" data-ga="backup_now">Zaxira yaratish</button>
        <button class="ghost" id="gupd">🔄 JARVIS'ni yangilash</button></div>
      <div id="gmsg"></div><details class="small"><summary>Qo'riqchi amallari tarixi</summary>${table(g.events, ["ts", "action", "auto", "result"])}</details></div>
    <div class="card"><h3>🎚 Avtonomlik darajasi</h3>
      ${LVL.map((t, i) => `<label class="small" style="display:block"><input type="radio" name="alvl" value="${i}" ${+set.autonomy_level === i ? "checked" : ""}> Level ${esc(t)}</label>`).join("")}
      <p class="small muted">Daraja barcha agent va ulanishlarga bir xil qo'llanadi. HIGH (tashqi xabar, POS yozuvi, pullik xizmat) va CRITICAL (to'lov, o'chirish)
        amallar istalgan darajada alohida tasdiq bilan. Tasdiqlar ${esc(String(set.approval_ttl_hours))} soatda eskiradi. JARVIS darajani o'zi o'zgartira olmaydi.</p>
      <div class="row"><button id="alsave">Saqlash</button></div><div id="almsg"></div></div>
    <div class="card"><h3>💡 Proaktiv kuzatuv (${p.items.length})</h3><p class="small muted">JARVIS faqat xabar beradi va taklif qiladi — tashqi amal bajarmaydi.</p>
      ${p.items.map((i) => `<div class="kv"><span><span class="pill ${i.severity === "warning" ? "warn" : ""}">${esc(i.severity)}</span> ${esc(i.title)}${i.body ? `<div class="small muted">${esc(i.body)}</div>` : ""}</span>
        ${i.link ? `<a href="${i.link}">ochish</a>` : ""}</div>`).join("") || '<p class="muted">E\'tibor talab qiladigan narsa yo\'q.</p>'}
      <div class="row" style="margin-top:8px"><button class="ghost" id="rday">Kunlik hisobot</button><button class="ghost" id="rweek">Haftalik hisobot</button></div><pre id="rout" hidden></pre>
      <details class="small"><summary>Oldingi hisobotlar (${p.reports.length})</summary>${p.reports.map((r) => `<div>${esc(r.period)} (${esc(r.kind)}): ${esc(JSON.stringify(r.report.missions))} · AI ${r.report.ai_requests}</div>`).join("")}</details></div></div>`;
  v.querySelectorAll("[data-ga]").forEach((b) => { b.onclick = async () => {
    if (b.dataset.ga === "emergency_stop" && !confirm("Barcha avtomatik jarayonlar va missiyalar to'xtatilsinmi?")) return;
    try { const r = await post(`/api/guardian/${b.dataset.ga}`); $("#gmsg").innerHTML = `<span class="pill ok">${esc(String(r.result).slice(0, 200))}</span>`; later(() => renderGuardian(v), 900); }
    catch (e) { fail($("#gmsg"), e); } }; });
  $("#gupd").onclick = async () => { if (!confirm("Yangilash oynasi ochiladi. JARVIS bir necha daqiqaga to'xtaydi. Davom etilsinmi?")) return;
    try { const r = await post("/api/system/update"); $("#gmsg").innerHTML = `<span class="pill ok">${esc(r.note)}</span>`; } catch (e) { fail($("#gmsg"), e); } };
  $("#alsave").onclick = async () => { const val = +(v.querySelector("[name=alvl]:checked") || {}).value;
    try { await post("/api/settings", { autonomy_level: val }); $("#almsg").innerHTML = `<span class="pill ok">Level ${val} saqlandi</span>`; } catch (e) { fail($("#almsg"), e); } };
  const rep = async (k) => { try { out($("#rout"), await post(`/api/proactive/report?kind=${k}`)); } catch (e) { fail($("#rout"), e); } };
  $("#rday").onclick = () => rep("daily"); $("#rweek").onclick = () => rep("weekly");
}

async function renderAssets(v) {
  const [st, dup] = await Promise.all([api("/api/assets"), api("/api/assets/duplicates")]);
  v.innerHTML = `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(360px,1fr))">
    <div class="card"><h3>🗂 Fayllarni tartiblash</h3><p class="small muted">Faqat ruxsat berilgan papkalar: ${esc(st.roots.join(", "))}. Maxfiy fayllar (.env, kalitlar) o'tkaziladi.
      Hech narsa o'chirilmaydi yoki ko'chirilmaydi. Qidiruv hozircha nom va matn bo'yicha (semantik qidiruv — Memory Brain bosqichida).</p>
      <div class="kv"><span>Indekslangan fayllar</span><b>${st.total}</b></div>${st.categories.map((c) => `<div class="kv"><span>${esc(c.category)}</span><b>${c.n} · ${fmtSize(c.size)}</b></div>`).join("")}
      <div class="kv"><span>Oxirgi indeks</span><b class="small">${esc(st.state.last ? `${st.state.last.at} (+${st.state.last.new}, ~${st.state.last.updated}, -${st.state.last.removed})` : "hali yo'q")}</b></div>
      <div class="row"><button id="aidx">${st.state.running ? "Indekslanmoqda…" : "Indekslash"}</button></div><div id="amsg"></div></div>
    <div class="card"><h3>Qidiruv</h3><div class="row"><input id="aq" placeholder="fayl nomi yoki ichidagi so'z"><select id="acat"><option value="">hammasi</option>
      ${["document", "spreadsheet", "presentation", "image", "audio", "video", "code", "archive", "other"].map((c) => `<option>${c}</option>`).join("")}</select><button id="ago">Qidirish</button></div>
      <div id="ares" style="max-height:360px;overflow:auto"></div></div></div>
    <div class="card"><h3>Dublikatlar — ${dup.groups.length} guruh, ${fmtSize(dup.wasted_total)} ortiqcha joy</h3><p class="small muted">${esc(dup.note)}</p>
      ${dup.groups.slice(0, 30).map((g) => `<details class="small"><summary>${g.count} nusxa · ${fmtSize(g.size)}</summary>${g.files.map((f) => `<div>${esc(f)}</div>`).join("")}</details>`).join("")}</div>`;
  $("#aidx").onclick = async () => { try { await post("/api/assets/index?background=true"); $("#amsg").innerHTML = '<span class="muted">fonda indekslanmoqda — bir ozdan keyin sahifani yangilang</span>'; } catch (e) { fail($("#amsg"), e); } };
  const search = async () => { try { const rows = await api(`/api/assets/search?q=${encodeURIComponent($("#aq").value)}&category=${encodeURIComponent($("#acat").value)}`);
    $("#ares").innerHTML = rows.length ? rows.map((r) => `<div class="kv"><span>${esc(r.name)}<div class="small muted">${esc(r.path)} · ${fmtSize(r.size)}</div></span>
      <button class="ghost" data-ab="${esc(r.path)}">Zaxira nusxa</button></div>`).join("") : '<span class="muted">Topilmadi</span>';
    $("#ares").querySelectorAll("[data-ab]").forEach((b) => { b.onclick = async () => { try { const x = await post("/api/assets/backup", { text: b.dataset.ab }); b.outerHTML = `<span class="pill ok small">nusxa: ${esc(x.backup.split(/[\\/]/).pop())}</span>`; } catch (e) { alert(e.message); } }; });
  } catch (e) { fail($("#ares"), e); } };
  $("#ago").onclick = search; $("#aq").onkeydown = (e) => { if (e.key === "Enter") search(); };
}

async function renderSimLab(v) {
  const [hist, conns] = await Promise.all([api("/api/simlab/history"), api("/api/integrations")]);
  const dbs = conns.filter((c) => c.adapter === "database"), writable = conns.filter((c) => c.mode !== "read_only");
  v.innerHTML = `<div class="card"><h3>🧪 Sinov laboratoriyasi</h3><p class="small muted">O'zgarish avval NUSXADA sinaladi: production'ga hech narsa yozilmaydi.
      Natija yaxshi bo'lsa ham, haqiqiy tatbiq uchun odatdagi tasdiq (va oldindan zaxira) kerak.</p></div>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(380px,1fr))">
    <div class="card"><h3>Baza o'zgarishi (SQL, nusxada)</h3><select id="stgt"><option value="jarvis">JARVIS bazasi (nusxa)</option>${dbs.map((c) => `<option value="conn:${c.id}">${esc(c.name)}</option>`).join("")}</select>
      <textarea id="ssql" rows="4" placeholder="UPDATE products SET price = price*1.1;&#10;-- har qator alohida buyruq (;) bilan"></textarea>
      <div class="row"><button id="sgo">Simulyatsiya</button></div><div id="sres"></div></div>
    <div class="card"><h3>POS / ERP yozuvi (oldin → keyin)</h3>${writable.length ? `<select id="wconn">${writable.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select>
      <div class="row"><input id="went" placeholder="obyekt (products)"><input id="wid" placeholder="yozuv ID"></div><select id="wop"><option>update</option><option>create</option></select>
      <textarea id="wpay" rows="2">{"price": 3500}</textarea><div class="row"><button id="wgo">Ko'rish</button></div><div id="wres"></div>`
      : '<p class="muted small">Yozish rejimidagi ulanish yo\'q (hammasi "faqat o\'qish").</p>'}</div>
    <div class="card"><h3>Missiya quruq yurishi (dry-run)</h3><textarea id="mg" rows="2" placeholder="Maqsad"></textarea><div class="row"><button id="mgo2">Rejani sinash</button></div><div id="mres"></div></div>
    <div class="card"><h3>Kod (sandbox)</h3><textarea id="scode" rows="4">print(sum(range(10)))</textarea><div class="row"><button id="cgo">Ishga tushirish</button></div><pre id="cres" hidden></pre></div></div>
    <div class="card"><h3>Simulyatsiyalar tarixi</h3>${table(hist.map((h) => ({ id: h.id, turi: h.kind, nishon: h.target, holat: h.status, vaqt: h.created_at })), ["id", "turi", "nishon", "holat", "vaqt"])}</div>`;
  $("#sgo").onclick = async () => {
    try { const r = await post("/api/simlab/sql", { target: $("#stgt").value, statements: $("#ssql").value.split(/;\s*\n|;\s*$/).map((x) => x.trim()).filter(Boolean) });
      $("#sres").innerHTML = `${r.results.map((x) => `<div class="small">${x.ok ? "✅" : "❌"} ${esc(x.sql)}${x.error ? ` — <span class="bad">${esc(x.error)}</span>` : x.rows_affected != null ? ` (${x.rows_affected} qator)` : ""}</div>`).join("")}
        ${table(r.diff.map((d) => ({ jadval: d.table, oldin: d.before, keyin: d.after, qo_shildi: d.inserted ?? "", o_chdi: d.deleted ?? "", o_zgardi: d.updated ?? "" })), ["jadval", "oldin", "keyin", "qo_shildi", "o_chdi", "o_zgardi"])}
        <p class="small ok">${esc(r.rollback)}</p>`; } catch (e) { fail($("#sres"), e); } };
  const wg = $("#wgo"); wg.onclick = async () => {
    try { const r = await post("/api/simlab/write", { conn_id: +$("#wconn").value, entity: $("#went").value.trim(), record_id: $("#wid").value.trim(), operation: $("#wop").value, payload: JSON.parse($("#wpay").value || "{}") });
      $("#wres").innerHTML = `${table(Object.entries(r.changed).map(([k, x]) => ({ maydon: k, oldin: x.before, keyin: x.after })), ["maydon", "oldin", "keyin"])}
        <div class="kv"><span>Kerakli tasdiq</span><b>${esc(r.required_approval)}</b></div><p class="small muted">${esc(r.note)}</p>`; } catch (e) { fail($("#wres"), e); } };
  $("#mgo2").onclick = async () => {
    try { const r = await post("/api/simlab/mission", { text: $("#mg").value });
      $("#mres").innerHTML = `${table(r.steps.map((s) => ({ bosqich: `${s.key}: ${s.title}`, agent: s.agent, xavf: s.risk, tasdiq: s.needs_approval ? "kerak" : "", ruxsat: s.allowed ? "" : s.reason })), ["bosqich", "agent", "xavf", "tasdiq", "ruxsat"])}
        <p class="small">Level ${r.autonomy_level} da avtomatik boshlanadimi: <b>${r.would_auto_start ? "ha" : "yo'q"}</b></p>`; } catch (e) { fail($("#mres"), e); } };
  $("#cgo").onclick = async () => { try { const r = await post("/api/simlab/code", { text: $("#scode").value }); out($("#cres"), r.sandbox); } catch (e) { fail($("#cres"), e); } };
}

async function renderResearcher(v) {
  const fs = await api("/api/researcher/findings");
  v.innerHTML = `<div class="card"><h3>🔎 Manbalarni solishtirib o'rganish</h3><p class="small muted">Bir nechta manbani o'qiydi, solishtiradi (mustaqil domenlar, umumiy faktlar, xavfli matn belgilari),
      manba va sanani saqlaydi. Xulosa xotiraga faqat siz tasdiqlasangiz yoziladi. Internet Sozlamalarda yoqilgan bo'lishi kerak.</p>
    <div class="row"><input id="rq" placeholder="Savol"><button id="rgo">Tadqiq qilish</button></div><div id="rres"></div></div>
    <div class="card"><h3>Tasdiq kutayotgan xulosalar (${fs.length})</h3>${fs.map((f) => `<div class="kv"><span><b>${esc(f.query)}</b><div class="small">${esc(f.summary.slice(0, 300))}</div>
      <div class="small muted">${f.sources.length} manba · ishonch: ${esc(f.agreement.confidence || "?")}</div></span>
      <span><button class="ghost" data-rf="${f.id}" data-ok="1">✅ Xotiraga</button><button class="ghost" data-rf="${f.id}" data-ok="0">❌</button></span></div>`).join("") || '<p class="muted">Yo\'q</p>'}</div>`;
  $("#rgo").onclick = async () => {
    $("#rres").innerHTML = '<span class="muted">qidirilmoqda…</span>';
    try { const r = await post("/api/researcher/investigate", { text: $("#rq").value });
      const a = r.agreement;
      $("#rres").innerHTML = `<p style="white-space:pre-wrap">${esc(r.answer)}</p>
        <div class="kv"><span>Manbalar / mustaqil domenlar</span><b>${a.sources} / ${a.independent_domains}</b></div><div class="kv"><span>Ishonch</span><b>${esc(a.confidence)}</b></div>
        <div class="small">Umumiy atamalar: ${esc(a.shared_terms.join(", ") || "—")}</div>${a.flagged.length ? `<p class="small warn">Shubhali ko'rsatma matni bor: ${esc(a.flagged.join(", "))}</p>` : ""}
        ${table(r.sources.map((s) => ({ n: s.n, sarlavha: s.title, url: s.url, sana: s.fetched_at, ishonchlilik: s.reliability })), ["n", "sarlavha", "url", "sana", "ishonchlilik"])}
        <p class="small muted">${esc(a.note)}</p>`; later(() => renderResearcher(v), 100);
    } catch (e) { fail($("#rres"), e); } };
  v.querySelectorAll("[data-rf]").forEach((b) => { b.onclick = async () => { await post(`/api/researcher/findings/${b.dataset.rf}?accept=${b.dataset.ok === "1"}`); renderResearcher(v); }; });
}

async function renderBusiness(v) {
  const [ov, fc] = await Promise.all([api("/api/business/overview"), api("/api/business/forecast")]);
  const f = fc.forecast, an = fc.anomalies, series = fc.daily.series.slice(-30);
  const max = Math.max(1, ...series.map((x) => x.amount), ...f.forecast.map((x) => x.amount));
  v.innerHTML = `<div class="card"><h3>📊 Biznes markazi</h3><p class="small muted">${esc(ov.mode_note)}</p>
      <div class="kv"><span>Ulangan biznes manbalari</span><b>${ov.connections.length ? esc(ov.connections.map((c) => `${c.name} (${c.status})`).join(", ")) : "yo'q — Ulanishlar'da ulang"}</b></div></div>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr))">${Object.entries({ today: "Bugungi savdo", top: "Ko'p sotilgan", low_stock: "Qoldig'i kam", debts: "Qarzlar", stores: "Do'konlar" }).map(([k, t]) => {
      const a = ov.answers[k]; return `<div class="card"><h3>${t}</h3><p class="small" style="white-space:pre-wrap">${esc(a.text)}</p>${(a.sources || []).length ? `<div class="small muted">Manba: ${esc(a.sources.join(", "))}</div>` : ""}</div>`; }).join("")}</div>
    <div class="card"><h3>Savdo dinamikasi va prognoz</h3>${series.length ? `<div style="display:flex;align-items:flex-end;gap:2px;height:160px">
      ${series.map((x) => `<div title="${esc(x.date)}: ${x.amount}" style="flex:1;background:var(--acc);height:${(x.amount / max) * 100}%"></div>`).join("")}
      ${f.forecast.map((x) => `<div title="prognoz ${esc(x.date)}: ${x.amount}" style="flex:1;background:var(--acc);opacity:.35;height:${(x.amount / max) * 100}%"></div>`).join("")}</div>
      <p class="small muted">Och rang — prognoz. ${esc(f.method || "")}</p>` : ""}<p class="small warn">${esc(f.note)}</p>
      <h3>Anomaliyalar</h3>${an.anomalies.length ? table(an.anomalies, ["date", "amount", "expected", "z", "kind"]) : `<p class="muted small">${esc(an.note || "Aniqlanmadi")}</p>`}</div>`;
}

async function renderCreative(v) {
  const c = await api("/api/creative/capabilities");
  const S = { ready: ["ok", "tayyor"], missing: ["bad", "o'rnatilmagan"], not_configured: ["warn", "sozlanmagan"], not_connected: ["warn", "ulanmagan"],
    model_only: ["warn", "model bor, adapter yo'q"], browser_only: ["warn", "faqat brauzer"], not_implemented: ["bad", "hali yo'q"] };
  v.innerHTML = `<div class="card"><h3>🎨 Media imkoniyatlari — haqiqiy holat</h3><p class="small muted">Har bir xizmatning hozirgi real holati. Ulanmagan yoki adapteri yo'q xizmat ishlaydigandek ko'rsatilmaydi.</p>
    ${c.services.map((s) => `<div class="kv"><span>${esc(s.service)}${s.note ? `<div class="small muted">${esc(s.note)}</div>` : ""}</span><span><span class="pill ${S[s.status]?.[0] || ""}">${esc(S[s.status]?.[1] || s.status)}</span>
      ${s.where ? ` <a href="${s.where}">ochish</a>` : ""}</span></div>`).join("")}
    <h3 style="margin-top:12px">Media pipeline</h3><p class="small">${c.pipeline.map(esc).join(" → ")}</p></div>`;
}

async function renderSkills(v) {
  const list = await api("/api/plugins");
  v.innerHTML = `<div class="card"><h3>🧩 Ko'nikmalar fabrikasi</h3><p class="small muted">Yangi skill: JARVIS qoralama yozadi (AI yoki shablon) → xavfsizlik tekshiruvi → sandbox testlari → siz tasdiqlaysiz → yoqiladi.
      Har yoqilgan versiya saqlanadi va rollback qilish mumkin. Skill JARVIS xavfsizlik kodini o'zgartira olmaydi.</p>
    <div class="row"><input id="skn" placeholder="nomi (masalan: excel_yordamchi)"><input id="skd" placeholder="nima qiladi?"></div>
    <div class="row"><label class="small"><input type="checkbox" id="skai"> AI kod yozsin (AI Router orqali)</label><button id="skgo">Qoralama yaratish</button></div><div id="skmsg"></div></div>
    <div class="card"><h3>Skill'lar</h3>${list.map((p) => `<div class="kv"><span><b>${esc(p.name)}</b> v${esc(p.version)} <span class="pill">${esc(p.status)}</span> <span class="small muted">${esc(p.source)}</span>
      <div class="small muted">${esc(p.description || "")}</div></span><span><button class="ghost" data-skt="${esc(p.name)}">Sinash</button><button class="ghost" data-skv="${esc(p.name)}">Versiyalar</button></span></div>
      <div id="skx_${esc(p.name)}"></div>`).join("")}<p class="small"><a href="#plugins">→ Yoqish/o'chirish va sozlamalar (Kengaytmalar)</a></p></div>`;
  $("#skgo").onclick = async () => { try { const r = await post("/api/skills", { name: $("#skn").value.trim(), description: $("#skd").value.trim(), use_ai: $("#skai").checked });
    $("#skmsg").innerHTML = `<span class="pill ok">yaratildi: ${esc(r.name)} (${esc(r.created_by)})</span>${r.findings.length ? ` <span class="warn small">${r.findings.length} ta ogohlantirish</span>` : ""}`; later(() => renderSkills(v), 800); }
    catch (e) { fail($("#skmsg"), e); } };
  v.querySelectorAll("[data-skt]").forEach((b) => { b.onclick = async () => { const box = $(`#skx_${b.dataset.skt}`);
    try { const r = await post(`/api/skills/${b.dataset.skt}/test`); box.innerHTML = `<p class="small">${r.passed ? "✅ testlar o'tdi" : "❌ testlar o'tmadi"} · ${r.results.length} test · ${r.findings.length} ogohlantirish</p>
      ${r.results.map((x) => `<div class="small">${x.passed ? "✅" : "❌"} ${esc(JSON.stringify(x.input))} → ${esc(JSON.stringify(x.output || x.error).slice(0, 200))}</div>`).join("")}`; } catch (e) { fail(box, e); } }; });
  v.querySelectorAll("[data-skv]").forEach((b) => { b.onclick = async () => { const box = $(`#skx_${b.dataset.skv}`);
    try { const vs = await api(`/api/skills/${b.dataset.skv}/versions`);
      box.innerHTML = vs.length ? vs.map((x) => `<div class="kv small"><span>v${esc(x.version)} · ${esc(x.hash.slice(0, 10))} · ${esc(x.created_at)}${x.current ? " (joriy)" : ""}</span>
        ${x.current ? "" : `<button class="ghost" data-rb="${x.id}">Qaytarish</button>`}</div>`).join("") : '<p class="small muted">Hali tasdiqlangan versiya yo\'q</p>';
      box.querySelectorAll("[data-rb]").forEach((rb) => { rb.onclick = async () => { if (!confirm("Shu versiyaga qaytarilsinmi? Keyin qayta tasdiq bilan yoqiladi.")) return;
        try { await post(`/api/skills/${b.dataset.skv}/rollback/${rb.dataset.rb}`); renderSkills(v); } catch (e) { fail(box, e); } }; });
    } catch (e) { fail(box, e); } }; });
}

async function renderDevices(v) {
  const d = await api("/api/devices");
  v.innerHTML = `<div class="card"><h3>📱 Qurilmalar — telefon va boshqa kompyuterlardan kirish</h3><p class="small muted">${esc(d.note)}</p>
    <div class="kv"><span>PIN himoyasi</span>${statusPill(d.auth_enabled, "yoqilgan", "o'chirilgan")}</div><div class="kv"><span>Ruxsat berilgan manzillar</span><b class="small">${esc(d.hosts.join(", "))}</b></div>
    <h3>Faol sessiyalar</h3>${d.sessions.length ? d.sessions.map((s) => `<div class="kv"><span>${esc(s.client)} ${s.local ? "(shu kompyuter)" : "(tarmoqdan)"}${s.current ? " — <b>siz</b>" : ""}
      <div class="small muted">kirgan: ${new Date((s.created || 0) * 1000).toLocaleString()} · tugaydi: ${new Date(s.expires * 1000).toLocaleString()}</div></span>
      ${s.current ? "" : `<button class="ghost" data-dv="${s.id}">Chiqarib yuborish</button>`}</div>`).join("") : '<p class="muted small">PIN o\'chirilgan yoki sessiya yo\'q.</p>'}
    <p class="small warn">Internet orqali (uydan tashqarida) kirish hali xavfsiz emas — HTTPS va tunnel keyingi bosqichda.</p></div>`;
  v.querySelectorAll("[data-dv]").forEach((b) => { b.onclick = async () => { await post(`/api/devices/${b.dataset.dv}/revoke`); renderDevices(v); }; });
}
