// Mission Control (avtonom missiyalar) va Agent Command (agentlar, ruxsatlar). Hammasi backend'dagi haqiqiy Mission Engine'ga ulangan.
"use strict";

const MC = { sel: null };
const MST = { completed: "ok", running: "ok", verifying: "ok", pending: "warn", paused: "warn", waiting_approval: "warn", needs_input: "warn", planning: "warn",
  retrying: "warn", failed: "bad", cancelled: "bad" };
const RISKC = { LOW: "ok", MEDIUM: "warn", HIGH: "bad", CRITICAL: "bad" };
const NST = { done: "ok", reused: "ok", running: "ok", pending: "warn", waiting_approval: "warn", failed: "bad", blocked: "bad", cancelled: "bad" };

async function renderMissionControl(v) {
  clearInterval(timer);                 // qayta chizishda eski kuzatuvchi taymer qolmasin
  const list = await api("/api/missions");
  v.innerHTML = `<div class="card"><h3>🎯 Yangi missiya</h3>
      <p class="small muted">Maqsadni yozing — JARVIS tushunadi, bosqichlarga ajratadi, har bosqich xavfini baholaydi. LOW bosqichlar avtomatik bajariladi;
        o'zgartiruvchi, tashqi yoki pullik amallar tasdiqsiz bajarilmaydi. "keyin" — ketma-ket, "hamda" — parallel.</p>
      <textarea id="mgoal" rows="2" placeholder="Masalan: fayllarni ko'rsat keyin savdo hisobotini ko'rsat hamda internetdan qidir: POS tizimlari"></textarea>
      <div class="row"><label class="small">Vaqt limiti (daq.)</label><input id="mmin" type="number" min="1" value="60" style="max-width:90px">
        <label class="small">Xarajat limiti</label><input id="mcost" type="number" min="0" step="0.01" value="0" style="max-width:90px">
        <label class="small">Urinishlar</label><input id="matt" type="number" min="1" max="5" value="2" style="max-width:70px">
        <label class="small"><input type="checkbox" id="mauto" checked> xavfsiz bo'lsa avtomatik boshlash</label><button id="mgo">Reja tuzish</button></div><div id="mmsg"></div></div>
    <div class="card"><h3>Missiyalar</h3>${list.length ? `<table><tr><th>#</th><th>Maqsad</th><th>Holat</th><th>Jarayon</th><th>Yaratilgan</th><th></th></tr>${list.map((m) => `<tr>
      <td>${m.id}</td><td>${esc(m.goal.slice(0, 90))}</td><td><span class="pill ${MST[m.status] || ""}">${esc(m.status_label)}</span></td>
      <td><div class="vu" style="width:120px"><i style="width:${m.progress}%"></i></div> ${m.progress}%</td><td class="small">${esc(m.created_at)}</td>
      <td><button class="ghost" data-mo="${m.id}">Ochish</button></td></tr>`).join("")}</table>` : '<p class="muted">Hali missiya yo\'q.</p>'}</div>
    <div id="mdet"></div><div id="mles"></div>`;
  $("#mgo").onclick = async () => {
    try { const m = await post("/api/missions", { goal: $("#mgoal").value, max_minutes: +$("#mmin").value || 60, max_cost: +$("#mcost").value || 0,
      max_attempts: +$("#matt").value || 2, auto_start: $("#mauto").checked });
    MC.sel = m.id; renderMissionControl(v); } catch (e) { fail($("#mmsg"), e); } };
  v.querySelectorAll("[data-mo]").forEach((b) => { b.onclick = () => { MC.sel = +b.dataset.mo; mcDetail($("#mdet"), v); }; });
  if (MC.sel) mcDetail($("#mdet"), v);
  mcLessons($("#mles"));
  timer = setInterval(() => { if (MC.sel && $("#mdet").isConnected) mcDetail($("#mdet"), v, true); }, 2500);
}

async function mcDetail(el, v, quiet) {
  const m = await api(`/api/missions/${MC.sel}`).catch(() => null);
  if (!m || !el.isConnected) return;
  if (quiet && el.dataset.sig === `${m.status}:${m.progress}:${m.log.length}`) return;
  el.dataset.sig = `${m.status}:${m.progress}:${m.log.length}`;
  const g = m.graph, rep = m.report, act = (a, t, cls = "ghost") => `<button class="${cls}" data-ma="${a}">${t}</button>`;
  const canStart = ["pending", "paused", "waiting_approval", "failed"].includes(m.status);
  el.innerHTML = `<div class="card"><div class="row" style="justify-content:space-between"><h3 style="margin:0">Missiya #${m.id}</h3>
      <span class="pill ${MST[m.status] || ""}">${esc(m.status_label)}</span></div>
    <p>${esc(m.goal)}</p>${m.stop_reason ? `<p class="small warn">${esc(m.stop_reason)}</p>` : ""}
    <div class="vu"><i style="width:${m.progress}%"></i></div>
    <div class="small muted">Reja: ${esc(m.plan_note || "")} · limitlar: ${m.max_minutes} daq., ${m.max_cost || "—"} xarajat, ${m.max_attempts} urinish</div>
    ${(m.questions || []).length && m.status === "needs_input" ? `<div class="card" style="margin-top:8px"><b>JARVIS savollari:</b><ul>${m.questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>
      <div class="row"><input id="mans" placeholder="Javob / aniqlashtirish"><button id="mansgo">Yuborish va qayta rejalash</button></div></div>` : ""}
    <div class="row" style="margin-top:8px">${canStart ? act("start", m.started_at ? "▶ Davom ettirish (checkpointdan)" : "▶ Boshlash", "") : ""}
      ${["running", "retrying"].includes(m.status) ? act("pause", "⏸ To'xtatish") : ""}${!["completed", "cancelled"].includes(m.status) ? act("cancel", "✖ Bekor qilish") : ""}
      ${m.status === "waiting_approval" ? '<a href="#approvals">→ Tasdiqlashlar</a>' : ""}</div><div id="mamsg"></div>
    <h3>Reja va bosqichlar</h3><table><tr><th>Bosqich</th><th>Agent</th><th>Xavf</th><th>Holat</th><th>Urinish</th><th>Tekshiruv</th><th></th></tr>
      ${g.nodes.map((n) => { const r = (m.risks || []).find((x) => x.key === n.key) || {};
        return `<tr><td>${esc(n.key)}: ${esc(n.title)}${n.depends_on.length ? `<div class="small muted">kutadi: ${esc(n.depends_on.join(", "))}</div>` : ""}</td>
        <td>${esc(n.agent)}${n.agent === "manager" ? '<div class="small muted">faqat AI maslahati</div>' : ""}</td>
        <td><span class="pill ${RISKC[r.risk] || ""}">${esc(r.risk || "?")}</span>${r.allowed === false ? `<div class="small bad">${esc(r.reason)}</div>` : ""}</td>
        <td><span class="pill ${NST[n.status] || ""}">${esc(n.status)}</span>${n.dead_letter ? ' <span class="pill bad">dead-letter</span>' : ""}${n.error ? `<div class="small">${esc(n.error.slice(0, 160))}</div>` : ""}</td>
        <td>${n.attempts || 0}/${n.max_attempts || 1}</td><td class="small">${n.verified === 1 ? "✅ " : n.verified === 0 ? "❌ " : ""}${esc(n.verify_note || "")}</td>
        <td>${["failed", "blocked"].includes(n.status) ? `<button class="ghost" data-mr="${esc(n.key)}">Qayta urinish</button>` : ""}</td></tr>`; }).join("")}</table>
    ${(m.risks || []).some((r) => r.key === "*") ? `<p class="small bad">⚠ ${esc(m.risks.find((r) => r.key === "*").title)} — har bir bunday amal alohida tasdiqlanadi.</p>` : ""}
    ${rep ? `<h3>Hisobot</h3><div class="kv"><span>Bajarildi</span><b>${rep.done}/${rep.total}${rep.advice_only ? ` (shundan ${rep.advice_only} tasi faqat maslahat)` : ""}</b></div>
      <div class="kv"><span>Bajarilmadi</span><b>${esc(rep.failed.join(", ") || "—")}</b></div><div class="kv"><span>Tasdiq kutmoqda</span><b>${esc(rep.waiting_approval.join(", ") || "—")}</b></div>
      <div class="kv"><span>AI modellari</span><b class="small">${esc(rep.models.map((x) => `${x.provider}/${x.model} ×${x.n}`).join(", ") || "ishlatilmadi")}</b></div>
      <div class="kv"><span>Xarajat (taxminiy)</span><b>${rep.cost}</b></div>` : ""}
    ${m.reflection ? `<h3>Refleksiya</h3><p class="small">Maqsadga erishildi: <b>${m.reflection.goal_reached ? "ha" : "yo'q"}</b></p><ul class="small">${m.reflection.lessons.map((l) => `<li>${esc(l)}</li>`).join("") || "<li>Alohida xulosa yo'q</li>"}</ul>` : ""}
    <details class="small"><summary>Jarayon jurnali (${m.log.length})</summary>${table(m.log, ["ts", "stage", "note"])}</details></div>`;
  el.querySelectorAll("[data-ma]").forEach((b) => { b.onclick = async () => {
    try { await post(`/api/missions/${m.id}/${b.dataset.ma}`); renderMissionControl(v); } catch (e) { fail($("#mamsg"), e); } }; });
  el.querySelectorAll("[data-mr]").forEach((b) => { b.onclick = async () => {
    try { await post(`/api/missions/${m.id}/retry?key=${encodeURIComponent(b.dataset.mr)}`); mcDetail(el, v); } catch (e) { fail($("#mamsg"), e); } }; });
  const ag = $("#mansgo"); ag.onclick = async () => { try { const n = await post(`/api/missions/${m.id}/answer`, { text: $("#mans").value }); MC.sel = n.id; renderMissionControl(v); } catch (e) { fail($("#mamsg"), e); } };
}

async function mcLessons(el) {
  const ls = await api("/api/missions/lessons");
  if (!ls.length || !el.isConnected) return;
  el.innerHTML = `<div class="card"><h3>🧠 O'rganilgan tajriba (tasdiq kutmoqda)</h3><p class="small muted">Tasdiqlangan xulosalar Procedural Memory'ga yoziladi. JARVIS o'z qoidalarini o'zi o'zgartirmaydi.</p>
    ${ls.map((l) => `<div class="kv"><span>#${l.mission_id}: ${esc(l.content)}</span><span><button class="ghost" data-la="${l.id}" data-ok="1">✅</button><button class="ghost" data-la="${l.id}" data-ok="0">❌</button></span></div>`).join("")}</div>`;
  el.querySelectorAll("[data-la]").forEach((b) => { b.onclick = async () => { await post(`/api/missions/lessons/${b.dataset.la}?accept=${b.dataset.ok === "1"}`); mcLessons(el); }; });
}

async function renderAgentCommand(v) {
  const profs = await api("/api/permissions/agents");
  v.innerHTML = `<div class="card"><h3>🤝 Agentlar va ruxsatlar (Permission Manager)</h3>
    <p class="small muted">Har agentning maksimal ruxsat darajasi, router orqali oladigan model turi, xotiraga kirishi va natijani tekshirish qoidasi.
      Agentlar bir-birining ruxsatini meros qilib ololmaydi; HIGH/CRITICAL amallar har doim tasdiq bilan.</p>
    ${table(profs.map((p) => ({ agent: p.title, kalit: p.key, holat: p.status, "maks. xavf": `${p.max_risk} (${p.max_level})`, amal: p.action, model: p.router_task,
      xotira: p.memory_access, tekshiruv: p.verify, vositalar: p.tools.join(", ") })), ["agent", "kalit", "holat", "maks. xavf", "amal", "model", "xotira", "tekshiruv", "vositalar"])}
    <p class="small">Darajalar: LOW (A/B) — avtomatik · MEDIUM (C) — tasdiq · HIGH (D) — har biri alohida tasdiq · CRITICAL (E) — faqat dashboard'da aniq tasdiq.</p></div>`;
}
