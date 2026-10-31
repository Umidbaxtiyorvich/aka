// Topshiriqlar → ulangan saytlar yoki JARVIS agentlari ("rasm yarat", "video yarat", "tarjima qil" ...).
// Saytda bajarish sizning hisobingizdan bo'ladi — har safar aniq tasdiq (D). Tasdiqsiz hech narsa yuborilmaydi.
"use strict";

const fileUrl = (p) => `/api/studio/file?path=${encodeURIComponent(p)}`;

function taskResultHtml(r) {
  const media = (r.outputs || []).map((p) => /\.(png|jpe?g|gif|webp)$/i.test(p) ? `<a href="${fileUrl(p)}" target="_blank"><img src="${fileUrl(p)}" class="tres-img" alt="natija"></a>`
    : /\.(mp4|webm)$/i.test(p) ? `<video src="${fileUrl(p)}" controls class="tres-img"></video>` : /\.(mp3|wav|ogg)$/i.test(p) ? `<audio src="${fileUrl(p)}" controls></audio>`
      : `<a href="${fileUrl(p)}" target="_blank">${esc(p.split(/[\\/]/).pop())}</a>`).join("");
  return `${r.status === "ok" ? statusPill(true, "Bajarildi") : `<span class="pill warn">${esc(r.status)}</span>`} <span class="small muted">${esc(r.site || "")}</span>
    ${r.error ? `<p class="bad small">${esc(r.error)}</p>` : ""}
    ${media ? `<div class="tres">${media}</div>` : ""}${r.text ? `<pre style="white-space:pre-wrap">${esc(r.text)}</pre>` : ""}
    ${(r.outputs || []).length ? `<p class="small muted">Saqlandi: ${esc(r.outputs.join(", "))}</p>` : ""}
    ${r.screenshot ? `<details><summary class="small">Sayt skrinshoti (isbot)</summary><img src="${fileUrl(r.screenshot)}" class="tres-img" alt="skrinshot"></details>` : ""}`;
}

function openTaskModal(plan) {
  let m = document.getElementById("cmodal");
  if (m) m.remove();
  m = document.createElement("div");
  m.id = "cmodal";
  const opts = plan.options || [];
  m.innerHTML = `<div class="card cm-box"><div class="row" style="justify-content:space-between;margin:0"><h3 style="margin:0">${esc(plan.icon || "🧩")} ${esc(plan.label || "Topshiriq")}</h3>
      <button class="ghost" id="cmx" title="Yopish">✕</button></div><div id="tkbody"></div></div>`;
  document.body.appendChild(m);
  const body = m.querySelector("#tkbody"), close = () => m.remove();
  m.querySelector("#cmx").onclick = close;
  m.addEventListener("click", (e) => { if (e.target === m) close(); });
  if (!plan.capability) { body.innerHTML = `<p>${esc(plan.text)}</p>`; return; }
  body.innerHTML = `<label>So'rov (saytga / agentga yuboriladigan matn)</label><textarea id="tkp" rows="3">${esc(plan.prompt || "")}</textarea>
    <label>Kim bajaradi?</label>
    <div id="tkopts">${opts.map((o, i) => `<label class="tkopt ${o.available ? "" : "muted"}"><input type="radio" name="tko" value="${i}" ${i === plan.choice ? "checked" : ""} ${o.available ? "" : "disabled"}>
      ${o.kind === "site" ? "🌐" : "🤖"} <b>${esc(o.name)}</b> ${o.kind === "site" ? (o.verified ? '<span class="pill ok">sinalgan</span>' : '<span class="pill warn">hali sinalmagan</span>') : ""}
      ${o.named ? '<span class="pill">siz aytgan sayt</span>' : ""}<div class="small muted">${esc(o.note || (o.approval ? "sizning hisobingizdan, tasdiq bilan" : ""))}</div></label>`).join("")
      || '<p class="muted">Variant yo\'q</p>'}</div>
    ${plan.choice === null ? `<p class="warn small">${esc(plan.text)}</p><a href="#connections">→ Sayt ulash</a>` : ""}
    <div class="row"><button id="tkgo" ${plan.choice === null ? "disabled" : ""}>Bajarish</button></div><div id="tkout"></div>`;
  const out = body.querySelector("#tkout");
  body.querySelector("#tkgo").onclick = async () => {
    const sel = body.querySelector("input[name=tko]:checked"); if (!sel) return;
    const o = opts[+sel.value], prompt = body.querySelector("#tkp").value.trim();
    if (!prompt) return fail(out, new Error("So'rov bo'sh"));
    body.querySelector("#tkgo").disabled = true;
    try {
      if (o.kind === "agent") {
        out.innerHTML = '<p class="muted">JARVIS agenti bajarmoqda…</p>';
        out.innerHTML = taskResultHtml(await post("/api/do/run", { capability: plan.capability, agent: o.agent, prompt }));
        return;
      }
      const r = await post("/api/do/run", { skill_id: o.skill_id, prompt }), a = r.approval;
      out.innerHTML = `<div class="cm-step">🛡 <b>Tasdiq kerak (D):</b> ${esc(a.summary)}<div class="small muted">Amal sizning hisobingizdan bajariladi; sayt kredit/limit sarflashi mumkin.
        JARVIS hech narsa sotib olmaydi, CAPTCHA/SMS'ni chetlab o'tmaydi.</div></div>
        <div class="row"><button id="tkok">✅ Tasdiqlash va bajarish</button><button class="ghost" id="tkno">Rad etish</button></div><div id="tkres"></div>`;
      out.querySelector("#tkno").onclick = async () => { await post(`/api/approvals/${a.id}/decide`, { approve: false, confirm_hash: a.payload_hash }); out.innerHTML = '<p class="muted">Rad etildi — hech narsa yuborilmadi.</p>'; };
      out.querySelector("#tkok").onclick = async () => {
        const res = out.querySelector("#tkres");
        out.querySelector("#tkok").disabled = out.querySelector("#tkno").disabled = true;
        try {
          await post(`/api/approvals/${a.id}/decide`, { approve: true, confirm_hash: a.payload_hash });
          res.innerHTML = '<p class="muted">⏳ Saytga kirilmoqda, so\'rov yuborilmoqda va natija kutilmoqda (1–3 daqiqa)…</p>';
          res.innerHTML = taskResultHtml(await post(`/api/site-skills/execute/${a.id}`));
        } catch (e) { fail(res, e); }
      };
    } catch (e) { fail(out, e); body.querySelector("#tkgo").disabled = false; }
  };
}

async function renderSiteSkills(v) {
  const [d, conns] = await Promise.all([api("/api/site-skills"), api("/api/integrations")]);
  const sites = conns.filter((c) => c.adapter === "website");
  const capOpts = (sel) => Object.entries(d.catalog).map(([k, c]) => `<option value="${k}" ${k === sel ? "selected" : ""}>${c.icon} ${esc(c.uz)}</option>`).join("");
  v.innerHTML = `<div class="card"><h3>🧩 Topshiriq bering</h3><p class="small muted">Masalan: "rasm yarat: tog'dagi qal'a", "video yarat: dengiz", "tarjima qil: ...".
      JARVIS mos ulangan saytni topadi (siz nomini aytgan sayt — birinchi); bo'lmasa o'z agentlari bilan bajaradi yoki nima ulash kerakligini aytadi.</p>
      <div class="row"><input id="tktext" placeholder="Nima qilay?" style="flex:1"><button id="tkplan">Davom</button></div></div>
    <div class="card"><h3>Saytlar nima qila oladi</h3>
      ${sites.length ? "" : '<p class="muted">Hali sayt ulanmagan. <a href="#connections">Ulanishlar</a> → havolani tashlang.</p>'}
      ${d.skills.length ? `<table><tr><th>Sayt</th><th>Imkoniyat</th><th>Sahifa</th><th>Manba</th><th>Holat</th><th></th></tr>${d.skills.map((s) => `<tr>
        <td>${esc(s.conn_name)}</td><td>${esc(d.catalog[s.capability]?.icon || "")} ${esc(s.label)}</td><td class="small" style="word-break:break-all">${esc(s.url)}</td>
        <td class="small">${{ detected: "sahifadan aniqlandi", preset: "ma'lum sayt", user: "siz sozlagansiz" }[s.source] || esc(s.source)}</td>
        <td>${s.verified ? '<span class="pill ok">sinalgan</span>' : '<span class="pill warn">sinalmagan</span>'} <span class="small muted">${s.runs} marta</span></td>
        <td><button class="ghost" data-ed="${s.id}">Tuzatish</button><button class="ghost" data-del="${s.id}">O'chirish</button></td></tr>`).join("")}</table>`
        : sites.length ? '<p class="muted small">Ko\'nikma aniqlanmadi. Ulanishlar\'da "O\'rganish"ni bosing yoki pastda qo\'lda qo\'shing.</p>' : ""}
      ${sites.length ? `<details id="skform"><summary><b>+ Ko'nikma qo'shish / tuzatish</b></summary>
        <input type="hidden" id="skid"><div class="row"><div style="flex:1"><label>Sayt</label><select id="skconn">${sites.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select></div>
        <div style="flex:1"><label>Imkoniyat</label><select id="skcap">${capOpts()}</select></div></div>
        <label>Sahifa manzili (shu sayt ichida)</label><input id="skurl" placeholder="https://.../create">
        <details><summary class="small">Qo'shimcha (selektorlar — bo'sh qolsa JARVIS o'zi topadi)</summary>
          <label>So'rov maydoni</label><input id="skp" placeholder="textarea#prompt"><label>Tugma</label><input id="sks" placeholder="button.generate">
          <label>Natija (matn uchun)</label><input id="skr" placeholder=".result"></details>
        <div class="row"><button id="sksave">Saqlash</button></div><div id="skmsg"></div></details>` : ""}</div>
    <div id="teach"></div>
    <div class="card"><h3>Oxirgi bajarilganlar</h3>${d.runs.length ? d.runs.map((r) => `<div class="kv small"><span>#${r.id} ${esc(r.capability)} · ${esc((r.prompt || "").slice(0, 60))}</span>
      <span>${r.status === "ok" ? '<span class="pill ok">ok</span>' : `<span class="pill warn">${esc(r.status)}</span>`} ${r.outputs.filter((p) => /\.(png|jpe?g|webp|gif)$/i.test(p)).slice(0, 3)
        .map((p) => `<a href="${fileUrl(p)}" target="_blank"><img src="${fileUrl(p)}" style="height:34px;vertical-align:middle;border-radius:4px"></a>`).join(" ")}</span></div>`).join("") : '<span class="muted">Hali yo\'q</span>'}</div>`;
  const go = async () => { const t = $("#tktext").value.trim(); if (!t) return;
    try { openTaskModal(await post("/api/do/plan", { text: t })); } catch (e) { alert(e.message); } };
  renderTeach($("#teach"));
  $("#tkplan").onclick = go;
  $("#tktext").addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  v.onclick = async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.del) { if (confirm("Ko'nikma o'chirilsinmi? (Saytga tegilmaydi)")) { await api(`/api/site-skills/${b.dataset.del}`, { method: "DELETE" }); renderSiteSkills(v); } return; }
    if (b.dataset.ed) {
      const s = d.skills.find((x) => x.id === +b.dataset.ed);
      $("#skform").open = true; $("#skid").value = s.id; $("#skconn").value = s.conn_id; $("#skcap").value = s.capability; $("#skurl").value = s.url;
      $("#skp").value = s.prompt_selector || ""; $("#sks").value = s.submit_selector || ""; $("#skr").value = s.result_selector || "";
      return;
    }
    if (b.id === "sksave") {
      try {
        await post("/api/site-skills", { conn_id: +$("#skconn").value, capability: $("#skcap").value, url: $("#skurl").value.trim(), prompt_selector: $("#skp").value.trim(),
          submit_selector: $("#sks").value.trim(), result_selector: $("#skr").value.trim(), skill_id: $("#skid").value ? +$("#skid").value : null });
        renderSiteSkills(v);
      } catch (er) { fail($("#skmsg"), er); }
    }
  };
}

// ---------- Agent rejimi: chatdagi qadamlar va tasdiq tugmalari ----------
function agentExtrasHtml(r) {
  const steps = (r.steps || []).length ? `<details class="small"><summary>🧠 Qanday o'yladim (${r.steps.length} qadam)</summary>${r.steps.map((s, i) =>
    `<div class="kv small"><span>${i + 1}. <b>${esc(s.tool)}</b> ${esc(s.why || "")}</span><span class="${s.status === "error" ? "bad" : "muted"}">${esc(s.status)}</span></div>`).join("")}</details>` : "";
  const ap = (r.approvals || []).map((a) => `<div class="cm-step" data-apbox="${a.id}">🛡 <b>Tasdiq kerak (${esc(a.level)})</b>: ${esc(a.summary)}
    ${a.level === "E" ? '<div class="small warn">Moliyaviy amal — diqqat bilan tekshiring.</div>' : ""}
    <div class="row"><button data-apok="${a.id}" data-h="${esc(a.payload_hash)}">✅ Tasdiqlash va bajarish</button><button class="ghost" data-apno="${a.id}" data-h="${esc(a.payload_hash)}">Rad etish</button></div>
    <div data-apres="${a.id}"></div></div>`).join("");
  return steps + ap;
}

async function agentApprovalClick(e) {
  const d = e.target.dataset, id = d.apok || d.apno; if (!id) return false;
  const box = document.querySelector(`[data-apres="${id}"]`);
  e.target.closest(".row").querySelectorAll("button").forEach((b) => { b.disabled = true; });
  try {
    await post(`/api/approvals/${id}/decide`, { approve: !!d.apok, confirm_hash: d.h });
    if (!d.apok) { box.innerHTML = '<span class="muted">Rad etildi — hech narsa bajarilmadi.</span>'; return true; }
    box.innerHTML = '<span class="muted">⏳ Bajarilmoqda…</span>';
    const r = await post(`/api/approvals/${id}/run`);
    box.innerHTML = r.outputs || r.text !== undefined ? taskResultHtml(r) : `${r.status === "ok" || r.status === "executed" ? statusPill(true, "Bajarildi") : `<span class="pill warn">${esc(r.status)}</span>`}
      ${r.error ? `<p class="bad small">${esc(r.error)}</p>` : ""}${r.note ? `<p class="small muted">${esc(r.note)}</p>` : ""}
      ${r.screenshot ? `<details><summary class="small">Skrinshot (isbot)</summary><img src="${fileUrl(r.screenshot)}" class="tres-img"></details>` : ""}`;
  } catch (er) { fail(box, er); }
  return true;
}

// ---------- Amalni o'rgatish (bir marta ko'rsatish → keyin buyruq bilan) ----------
async function renderTeach(el) {
  const [d, conns] = await Promise.all([api("/api/site-tasks"), api("/api/integrations")]);
  const sites = conns.filter((c) => c.adapter === "website");
  el.innerHTML = `<div class="card"><h3>🎓 Saytda amalni o'rgatish</h3>
    <p class="small muted">Masalan YesPOS'da "kirim": brauzer oynasi ochiladi, siz bir marta kirim qilib ko'rsatasiz va pastdagi yashil
    "✅ JARVIS: o'rgatishni tugatdim" tugmasini bosasiz. Keyin qaysi qiymatlar o'zgarishini belgilaysiz (kontragent, tovar, miqdor, narx).
    So'ng chatda: <i>"Vali savdoga 12 ta Fanta 9500 dan kirim qil"</i> — JARVIS tayyorlaydi va tasdiqingizdan keyin kiritadi. Parol maydonlari yozib olinmaydi.</p>
    ${sites.length ? `<div class="row"><select id="tcconn">${sites.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select>
      <input id="tcname" placeholder="Amal nomi (masalan: kirim)"><input id="tcurl" placeholder="Boshlang'ich sahifa (ixtiyoriy)" style="flex:1"><button id="tcgo">Brauzerni ochib o'rgatish</button></div>`
      : '<p class="muted">Avval saytni ulang (Ulanishlar → havola).</p>'}<div id="tcmsg"></div></div>
    ${d.tasks.map((t) => `<div class="card" data-task="${t.id}"><div class="row" style="justify-content:space-between;margin:0"><b>${esc(t.name)} — ${esc(t.conn_name)}</b>
      <span>${{ ready: '<span class="pill ok">tayyor</span>', recording: '<span class="pill warn">yozib olinmoqda…</span>', recorded: '<span class="pill warn">parametrlarni belgilang</span>' }[t.status] || `<span class="pill">${esc(t.status)}</span>`}
      ${t.financial ? '<span class="pill warn">moliyaviy (E)</span>' : ""} ${t.verified ? '<span class="pill ok">sinalgan</span>' : ""}
      <button class="ghost" data-tdel="${t.id}">O'chirish</button></span></div>
      ${t.status === "recorded" ? `<p class="small muted">${t.steps.length} qadam yozib olindi. O'zgaruvchi qiymatlarga nom bering (bo'sh — doim bir xil):</p>
        <table><tr><th>#</th><th>Amal</th><th>Maydon / tugma</th><th>Namuna</th><th>Parametr nomi</th></tr>${t.steps.map((s, i) => `<tr><td>${i + 1}</td><td>${esc(s.op)}</td>
          <td class="small">${esc(s.label || s.text || s.selector || s.url || "")}</td><td class="small">${esc(s.value ?? "")}</td>
          <td>${["fill", "select"].includes(s.op) ? `<input data-pi="${i}" value="${esc(s.suggest || "")}" placeholder="masalan: miqdor" style="width:130px">` : ""}</td></tr>`).join("")}</table>
        <label>Tavsif</label><input id="tdesc${t.id}" placeholder="POS'ga tovar kirimi"><label>Muvaffaqiyat belgisi (sahifada chiqadigan matn, ixtiyoriy)</label><input id="tsucc${t.id}" placeholder="Saqlandi">
        <div class="row"><button data-tfin="${t.id}">Saqlash</button></div><div id="tfmsg${t.id}"></div>`
        : t.status === "ready" ? `<p class="small muted">${esc(t.description || "")} · parametrlar: ${t.params.map((p) => esc(p.name)).join(", ") || "yo'q"} · ${t.runs} marta bajarilgan</p>
        <div class="row">${t.params.map((p) => `<input data-tp="${t.id}" data-n="${esc(p.name)}" placeholder="${esc(p.label)} (${esc(p.example || "")})">`).join("")}<button data-trun="${t.id}">Bajarish (tasdiq bilan)</button></div><div id="trmsg${t.id}"></div>`
        : t.status === "recording" ? '<p class="small muted">Brauzer oynasida ko\'rsating va yashil tugmani bosing…</p>' : `<p class="small muted">${esc(t.note || "")}</p>`}</div>`).join("")}`;
  if (d.tasks.some((t) => t.status === "recording")) later(() => renderTeach(el), 3000);
  el.onclick = async (e) => {
    if (await agentApprovalClick(e)) return;
    const b = e.target.closest("button"); if (!b) return;
    try {
      if (b.id === "tcgo") { await post("/api/site-tasks/record", { conn_id: +$("#tcconn").value, name: $("#tcname").value.trim(), start_url: $("#tcurl").value.trim() }); return renderTeach(el); }
      if (b.dataset.tdel) { if (confirm("Amal o'chirilsinmi?")) { await api(`/api/site-tasks/${b.dataset.tdel}`, { method: "DELETE" }); renderTeach(el); } return; }
      if (b.dataset.tfin) {
        const id = +b.dataset.tfin, t = d.tasks.find((x) => x.id === id), box = el.querySelector(`[data-task="${id}"]`);
        const steps = t.steps.map((s, i) => { const inp = box.querySelector(`[data-pi="${i}"]`); return { ...s, param: inp && inp.value.trim() ? inp.value.trim() : null }; });
        await post(`/api/site-tasks/${id}/finalize`, { name: t.name, description: $(`#tdesc${id}`).value, steps, success_text: $(`#tsucc${id}`).value });
        return renderTeach(el);
      }
      if (b.dataset.trun) {
        const id = b.dataset.trun, params = {};
        el.querySelectorAll(`[data-tp="${id}"]`).forEach((i) => { params[i.dataset.n] = i.value; });
        const r = await post(`/api/site-tasks/${id}/propose`, { params });
        $(`#trmsg${id}`).innerHTML = agentExtrasHtml({ approvals: [r.approval] });
      }
    } catch (er) { fail($("#tcmsg"), er); alert(er.message); }
  };
}
