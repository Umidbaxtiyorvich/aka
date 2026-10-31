// v1.3 sahifalari: Agent Swarm, Semantik xotira, File Intelligence, Computer Control. Hammasi real backend API.
"use strict";

async function renderSwarm(v) {
  const [d, agents] = await Promise.all([api("/api/swarm"), api("/api/agents")]);
  v.innerHTML = `<div class="card"><h3>🐝 Agentlar jamoasi</h3><p class="small muted">Agentlar bir-biriga faqat vositalar ro'yxati orqali topshiriq beradi. Topshiriq QABUL QILUVCHI agentning
      ruxsati bilan bajariladi; yuboruvchi o'zi qila olmaydigan ishni boshqasiga topshira olmaydi. Nazoratchi har natijani tekshiradi.
      Missiyada: "xotiradan qidir: …", "fayl qidir: …", "prognoz", "biznes savol: …", "matnni tekshir: …", "dry-run: …".</p>
    <div class="row"><select id="sfrom">${agents.map((a) => `<option ${a.key === "manager" ? "selected" : ""}>${esc(a.key)}</option>`).join("")}</select> →
      <select id="sto">${agents.map((a) => `<option>${esc(a.key)}</option>`).join("")}</select>
      <select id="stool">${Object.keys(d.routes).map((t) => `<option>${esc(t)}</option>`).join("")}</select></div>
    <div class="row"><input id="sargs" value='{"query": "ombor"}'><button id="sgo">Topshirish</button></div><pre id="sout" hidden></pre></div>
    <div class="card"><h3>Kim qaysi tool'ni bajara oladi</h3>${Object.entries(d.routes).map(([t, a]) => `<div class="kv"><span><code>${esc(t)}</code></span><b class="small">${esc(a.join(", "))}</b></div>`).join("")}</div>
    <div class="card"><h3>Topshiriqlar tarixi</h3>${table(d.history, ["ts", "from_agent", "to_agent", "tool", "status", "verdict", "note"])}</div>`;
  $("#sto").value = "memory_agent";
  $("#sgo").onclick = async () => { try { out($("#sout"), await post("/api/swarm/delegate", { from_agent: $("#sfrom").value, to_agent: $("#sto").value, tool: $("#stool").value,
    args: JSON.parse($("#sargs").value || "{}") })); later(() => renderSwarm(v), 1500); } catch (e) { fail($("#sout"), e); } };
}

async function renderSemantic(v) {
  const s = await api("/api/semantic");
  v.innerHTML = `<div class="card"><h3>🧠 Semantik xotira (ma'no bo'yicha qidiruv)</h3>
      <div class="kv"><span>Rejim</span><b>${esc(s.mode)}</b></div><div class="kv"><span>Ollama</span>${statusPill(s.ollama, "ishlayapti", "javob bermadi")}</div>
      <div class="kv"><span>Model</span><b>${esc(s.model || "yoqilmagan")} ${s.installed ? '<span class="pill ok">o\'rnatilgan</span>' : ""}</b></div>
      <div class="kv"><span>Vektorlangan xotiralar</span><b>${s.indexed} / ${s.total}</b></div>
      ${s.state.error ? `<p class="small bad">${esc(s.state.error)}</p>` : ""}${s.state.pulling ? '<p class="small warn">Model yuklanmoqda…</p>' : ""}
      <p class="small muted">Vektorlar JARVIS bazasida saqlanadi (AI provayderdan mustaqil); matn faqat mahalliy Ollama'ga beriladi. Model yo'q bo'lsa — kalit so'z qidiruvi.</p>
      <div class="row">${!s.enabled && s.installed ? `<button id="sen">Yoqish (${esc(s.suggested_model)} allaqachon bor)</button>` : ""}
        ${!s.installed ? `<button id="sinst">${esc(s.suggested_model)} ni yuklash (~${s.size_mb} MB)</button>` : ""}${s.enabled ? '<button class="ghost" id="sidx">Qayta indekslash</button>' : ""}</div><div id="smsg"></div></div>
    <div class="card"><h3>Qidiruv</h3><div class="row"><input id="sq" placeholder="ma'no bo'yicha so'rang: masalan 'sklad qachon yopiq'"><button id="sgo2">Qidirish</button></div><div id="sres"></div></div>`;
  const m = $("#smsg");
  const inst = $("#sinst"); inst.onclick = async () => {
    const plan = await post("/api/semantic/install");
    if (!confirm(plan.note)) return;
    try { await post("/api/semantic/install?confirm=true"); m.innerHTML = '<span class="muted">yuklanmoqda (fonda)…</span>'; later(() => renderSemantic(v), 4000); } catch (e) { fail(m, e); } };
  const en = $("#sen"); en.onclick = async () => { try { await post(`/api/semantic/enable?model=${encodeURIComponent(s.suggested_model)}`); await post("/api/semantic/index"); renderSemantic(v); } catch (e) { fail(m, e); } };
  const ix = $("#sidx"); ix.onclick = async () => { try { out(m, await post("/api/semantic/index")); } catch (e) { fail(m, e); } };
  $("#sgo2").onclick = async () => { try { const r = await api(`/api/semantic/search?q=${encodeURIComponent($("#sq").value)}`);
    $("#sres").innerHTML = r.length ? r.map((x) => `<div class="kv"><span>${esc(x.content)}</span><b class="small">${esc(x.match)}${x.score ? ` · ${x.score}` : ""}</b></div>`).join("") : '<span class="muted">Topilmadi</span>';
  } catch (e) { fail($("#sres"), e); } };
}

async function renderDocIntel(v) {
  const f = await api("/api/docs/formats");
  v.innerHTML = `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(380px,1fr))">
    <div class="card"><h3>📄 Hujjatlar tahlili</h3><p class="small muted">Asl fayl HECH QACHON o'zgarmaydi — tahrir va yangi fayllar <code>workspace/exports</code> da.
        O'qiladi: ${esc(f.read.join(" "))}. OCR: ${f.ocr.available ? "tayyor" : esc(f.ocr.note)}</p>
      <p class="small warn">Qo'llab-quvvatlanmaydi: ${esc(f.not_supported.join(", "))}. ${esc(f.note)}</p>
      <div class="row"><input type="file" id="dfile"><button id="dup">Yuklash va o'qish</button></div>
      <div class="row"><input id="dpath" placeholder="yoki ruxsat berilgan papkadagi fayl yo'li"><button class="ghost" id="dread">O'qish</button></div><div id="dres"></div></div>
    <div class="card"><h3>Amallar</h3>
      <div class="row"><input id="dq" placeholder="hujjat ichidan qidirish"><button class="ghost" id="dfind">Qidirish</button></div>
      <div class="row"><button class="ghost" id="dsum">Xulosa</button><label class="small"><input type="checkbox" id="dai"> mahalliy AI bilan</label><button class="ghost" id="dexp">Matnga eksport (.md)</button></div>
      <div class="row"><input id="db" placeholder="solishtirish: ikkinchi fayl yo'li"><button class="ghost" id="dcmp">Solishtirish</button></div>
      <label class="small">Word nusxasida almashtirish (JSON: {"eski": "yangi"})</label><div class="row"><input id="drep" value='{"": ""}'><button class="ghost" id="drgo">Nusxa yaratish</button></div>
      <pre id="dout" hidden></pre></div>
    <div class="card"><h3>Yangi hujjat</h3><input id="ntitle" placeholder="sarlavha"><textarea id="ntext" rows="4" placeholder="# Bo'lim&#10;- band&#10;oddiy matn"></textarea>
      <div class="row"><button class="ghost" id="ndocx">Word (.docx)</button><button class="ghost" id="npptx">PowerPoint (.pptx, har "# " — slayd)</button></div><pre id="nout" hidden></pre></div></div>`;
  let cur = null;
  const show = (d) => { cur = d.path; $("#dpath").value = d.path;
    $("#dres").innerHTML = `<div class="kv"><span>Fayl</span><b>${esc(d.name)} (${esc(d.type)}, ${Math.round(d.size / 1024)} KB)</b></div>
      <div class="kv"><span>So'z / bo'lak</span><b>${d.words} / ${d.chunks}</b></div>${d.meta && d.meta.slides ? `<div class="kv"><span>Slaydlar</span><b>${d.meta.slides}</b></div>` : ""}
      ${d.tables.length ? `<div class="kv"><span>Jadvallar</span><b>${d.tables.length}</b></div>` : ""}${d.has_secret ? '<p class="small bad">Ichida maxfiy ma\'lumotga o\'xshash matn bor</p>' : ""}
      <div class="small muted">Qila olaman: ${esc(d.actions.join(", "))}</div><pre style="max-height:260px;overflow:auto;white-space:pre-wrap">${esc(d.text.slice(0, 4000))}</pre>`; };
  $("#dup").onclick = async () => { const fl = $("#dfile").files[0]; if (!fl) return;
    try { const fd = new FormData(); fd.append("file", fl); const res = await fetch("/api/docs-upload", { method: "POST", body: fd }); const d = await res.json();
      if (!res.ok) throw new Error(d.detail || res.statusText); show(d); } catch (e) { fail($("#dres"), e); } };
  $("#dread").onclick = async () => { try { show(await post("/api/docs/extract", { path: $("#dpath").value.trim() })); } catch (e) { fail($("#dres"), e); } };
  const op = async (name, body) => { try { out($("#dout"), await post(`/api/docs/${name}`, { path: cur || $("#dpath").value.trim(), ...body })); } catch (e) { fail($("#dout"), e); } };
  $("#dfind").onclick = () => op("find", { query: $("#dq").value });
  $("#dsum").onclick = () => op("summary", { ai: $("#dai").checked });
  $("#dexp").onclick = () => op("export", { fmt: "md" });
  $("#dcmp").onclick = () => op("compare", { b: $("#db").value.trim() });
  $("#drgo").onclick = () => { try { op("docx-replace", { replacements: JSON.parse($("#drep").value) }); } catch (e) { fail($("#dout"), e); } };
  $("#ndocx").onclick = async () => { try { out($("#nout"), await post("/api/docs/create-docx", { title: $("#ntitle").value, text: $("#ntext").value })); } catch (e) { fail($("#nout"), e); } };
  $("#npptx").onclick = async () => {
    const slides = []; $("#ntext").value.split("\n").forEach((l) => { if (l.startsWith("# ")) slides.push({ title: l.slice(2), bullets: [] }); else if (l.trim() && slides.length) slides[slides.length - 1].bullets.push(l.replace(/^[-*]\s*/, "")); });
    try { out($("#nout"), await post("/api/docs/create-pptx", { title: $("#ntitle").value, slides })); } catch (e) { fail($("#nout"), e); } };
}

async function renderComputerUse(v) {
  const s = await api("/api/computer-use");
  v.innerHTML = `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(380px,1fr))">
    <div class="card"><h3>🖱 Sichqoncha va klaviatura</h3><div class="kv"><span>Holat</span>${statusPill(s.available, "tayyor", "ishlamaydi")}</div>
      ${s.available ? `<div class="kv"><span>Ekran</span><b>${esc(s.screen.join("×"))}</b></div><div class="kv"><span>Faol oyna</span><b class="small">${esc(s.active_window)}</b></div>` : `<p class="small warn">${esc(s.note)}</p>`}
      <div class="kv"><span>UI Automation (pywinauto)</span>${statusPill(s.ui_automation, "bor", "yo'q")}</div>
      <ul class="small">${s.rules.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      <div class="row"><button class="ghost" id="cwin" ${s.available ? "" : "disabled"}>Oynalar</button><button class="ghost" id="cshot" ${s.available ? "" : "disabled"}>Skrinshot</button>
        <label class="small"><input type="checkbox" id="cana"> tahlil (vision/OCR)</label></div><div id="cres"></div></div>
    <div class="card"><h3>Amallar ketma-ketligi (tasdiq bilan)</h3>
      <p class="small muted">Turlar: click, double_click, right_click, move (x, y) · type (text) · hotkey (keys) · scroll (amount) · focus_window (title) · wait (seconds)</p>
      <textarea id="cacts" rows="6">[{"type": "focus_window", "title": "Bloknot"}, {"type": "type", "text": "Salom JARVIS"}, {"type": "hotkey", "keys": ["ctrl", "s"]}]</textarea>
      <input id="creason" placeholder="nima uchun (tasdiqda ko'rinadi)">
      <div class="row"><button id="cprop">Tasdiqqa yuborish</button><input id="cmname" placeholder="makro nomi" style="max-width:160px"><button class="ghost" id="csave">Makro saqlash</button></div>
      <div id="cpmsg"></div></div></div>
    <div class="card"><h3>Makrolar</h3>${s.macros.length ? s.macros.map((m) => `<div class="kv"><span>${esc(m.name)} (${m.actions.length} amal)</span><button class="ghost" data-rp="${esc(m.name)}">Qayta ijro (tasdiq bilan)</button></div>`).join("") : '<p class="muted small">Yo\'q</p>'}</div>
    <div class="card"><h3>Amallar jurnali</h3>${table(s.log, ["ts", "approval_id", "idx", "type", "detail", "window", "status", "error"])}</div>`;
  const res = $("#cres"), pm = $("#cpmsg");
  const w = $("#cwin"); w.onclick = async () => { try { const ws = await api("/api/computer-use/windows");
    res.innerHTML = ws.map((x) => `<div class="small">${x.active ? "▶ " : ""}${esc(x.title)}${x.sensitive ? ' <span class="pill bad">maxfiy — ishlanmaydi</span>' : ""}</div>`).join(""); } catch (e) { fail(res, e); } };
  const sh = $("#cshot"); sh.onclick = async () => { try { out(res, await post(`/api/computer-use/screenshot?analyze=${$("#cana").checked}`)); } catch (e) { fail(res, e); } };
  const showAppr = (r) => { pm.innerHTML = `<p class="small">Tasdiq #${r.approval.id}: ${esc(r.approval.summary)} — <span class="pill warn">${esc(r.approval.status)}</span></p>
      <p class="small"><a href="#approvals">Tasdiqlashlar</a> bo'limida tasdiqlang, so'ng: <button class="ghost" data-ex="${r.approval.id}">Bajarish</button></p>`;
    pm.querySelector("[data-ex]").onclick = async (e) => { try { out(pm, await post(`/api/computer-use/execute/${e.target.dataset.ex}`)); } catch (er) { fail(pm, er); } }; };
  $("#cprop").onclick = async () => { try { showAppr(await post("/api/computer-use/propose", { actions: JSON.parse($("#cacts").value), reason: $("#creason").value })); } catch (e) { fail(pm, e); } };
  $("#csave").onclick = async () => { try { await post("/api/computer-use/macros", { name: $("#cmname").value, actions: JSON.parse($("#cacts").value) }); renderComputerUse(v); } catch (e) { fail(pm, e); } };
  v.querySelectorAll("[data-rp]").forEach((b) => { b.onclick = async () => { try { showAppr(await post(`/api/computer-use/macros/${encodeURIComponent(b.dataset.rp)}/replay`)); } catch (e) { fail(pm, e); } }; });
}
