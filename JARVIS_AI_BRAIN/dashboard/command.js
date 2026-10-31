// Global buyruq satri (har bo'limda): "/" bilan qisqa buyruqlar, oddiy matn — JARVIS'ga topshiriq, yozish paytida — global qidiruv.
// Hamma narsa backend orqali (/api/command, /api/search) — bir xil ruxsat va tasdiq qoidalari.
"use strict";

(function () {
  const inp = document.getElementById("gcmd"), box = document.getElementById("gres");
  if (!inp || !box) return;
  let t = null, seq = 0;
  const hide = () => { box.hidden = true; };
  const showHtml = (h) => { box.innerHTML = h; box.hidden = false; };
  const renderSearch = (r) => r.groups.length ? r.groups.map((g) => `<div class="small muted" style="margin-top:6px"><b>${esc(g.title)}</b></div>
      ${g.items.map((i) => `<a class="gi small" href="${g.link}">${esc(i.text)} <span class="muted">${esc(i.meta || "")}</span></a>`).join("")}`).join("")
    : '<span class="muted small">Hech narsa topilmadi</span>';
  inp.addEventListener("input", () => {
    clearTimeout(t);
    const q = inp.value.trim();
    if (!q) return hide();
    if (q.startsWith("/")) return showHtml('<span class="small muted">Enter — buyruqni bajarish. <b>/yordam</b> — ro\'yxat.</span>');
    t = setTimeout(async () => { const my = ++seq;
      try { const r = await api(`/api/search?q=${encodeURIComponent(q)}`); if (my === seq && inp.value.trim() === q) showHtml(renderSearch(r) + '<div class="small muted" style="margin-top:8px">Enter — JARVIS\'ga topshiriq sifatida yuborish</div>'); } catch (e) { /* jim */ } }, 250);
  });
  inp.addEventListener("keydown", async (e) => {
    if (e.key === "Escape") { hide(); inp.blur(); return; }
    if (e.key !== "Enter") return;
    const text = inp.value.trim(); if (!text) return;
    if (/^https?:\/\/\S+$/i.test(text)) { inp.value = ""; hide(); openConnectModal(text); return; }   // havola — sayt/POS ulash oynasi
    showHtml('<span class="muted small">bajarilmoqda…</span>');
    try {
      const r = await api("/api/command", { method: "POST", body: { text } });
      if (r.kind === "search") showHtml(renderSearch(r));
      else showHtml(`<div class="small" style="white-space:pre-wrap">${esc(r.text)}</div>${r.link ? `<a class="small" href="${r.link}">→ ochish</a>` : ""}`);
      inp.value = "";
    } catch (er) { showHtml(`<span class="bad small">${esc(er.message)}</span>`); }
  });
  inp.addEventListener("paste", () => setTimeout(() => { const t = inp.value.trim(); if (/^https?:\/\/\S+$/i.test(t)) { inp.value = ""; hide(); openConnectModal(t); } }, 50));
  document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); inp.focus(); } });
  document.addEventListener("click", (e) => { if (!document.getElementById("cmdbar").contains(e.target)) hide(); });
  window.addEventListener("hashchange", hide);
})();

async function renderTools(v) {
  const [tools, calls] = await Promise.all([api("/api/tools"), api("/api/tools/calls?limit=40")]);
  const RC = { LOW: "ok", MEDIUM: "warn", HIGH: "bad", CRITICAL: "bad" };
  v.innerHTML = `<div class="card"><h3>🧰 Vositalar ro'yxati</h3><p class="small muted">JARVIS va agentlar ishlatadigan barcha vositalar: kirish sxemasi, xavf darajasi, kim chaqira oladi,
      timeout va qayta urinish. Ro'yxatda yo'q vosita chaqirilmaydi. Tashqi ta'sirli vositalar faqat tasdiq so'rovini yaratadi.</p>
    ${tools.map((t) => `<details class="card" style="margin:8px 0"><summary><b>${esc(t.name)}</b> <code class="small">${esc(t.id)}</code> <span class="pill ${RC[t.risk]}">${esc(t.risk)} (${esc(t.level)})</span>
      ${t.approval ? '<span class="pill warn">tasdiq orqali</span>' : ""}</summary>
      <p class="small">${esc(t.description)}</p><div class="kv"><span>Natija</span><b class="small">${esc(t.output)}</b></div>
      <div class="kv"><span>Kim chaqira oladi</span><b class="small">${esc(t.agents.join(", "))}</b></div>
      <div class="kv"><span>Timeout / qayta urinish / limit</span><b class="small">${t.timeout} s · ${esc(t.retry)} · ${t.rate_per_min}/daq</b></div>
      ${Object.entries(t.inputs).map(([k, s]) => `<label class="small">${esc(k)}${s.required ? " *" : ""} <span class="muted">(${esc(s.type)}) ${esc(s.description || "")}</span></label>
        <input data-ti="${esc(t.id)}" data-k="${esc(k)}" data-type="${esc(s.type)}" placeholder="${esc(s.default ?? "")}">`).join("")}
      <div class="row" style="margin-top:6px"><button class="ghost" data-tr="${esc(t.id)}">Ishga tushirish</button></div><pre id="to_${esc(t.id).replace(/\./g, "_")}" hidden></pre></details>`).join("")}</div>
    <div class="card"><h3>Oxirgi chaqiruvlar</h3>${table(calls, ["ts", "tool", "caller", "status", "duration_ms", "attempts", "error"])}</div>`;
  v.querySelectorAll("[data-tr]").forEach((b) => { b.onclick = async () => {
    const id = b.dataset.tr, box = $(`#to_${id.replace(/\./g, "_")}`), args = {};
    try {
      v.querySelectorAll(`[data-ti="${id}"]`).forEach((i) => { if (i.value === "") return;
        args[i.dataset.k] = i.dataset.type === "integer" ? parseInt(i.value, 10) : i.dataset.type === "number" ? Number(i.value) : i.dataset.type === "object" ? JSON.parse(i.value) : i.value; });
      out(box, await post(`/api/tools/${id}/invoke`, { args }));
    } catch (e) { fail(box, e); } }; });
}
