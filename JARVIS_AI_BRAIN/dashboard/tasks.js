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
    <div class="card"><h3>Oxirgi bajarilganlar</h3>${d.runs.length ? d.runs.map((r) => `<div class="kv small"><span>#${r.id} ${esc(r.capability)} · ${esc((r.prompt || "").slice(0, 60))}</span>
      <span>${r.status === "ok" ? '<span class="pill ok">ok</span>' : `<span class="pill warn">${esc(r.status)}</span>`} ${r.outputs.filter((p) => /\.(png|jpe?g|webp|gif)$/i.test(p)).slice(0, 3)
        .map((p) => `<a href="${fileUrl(p)}" target="_blank"><img src="${fileUrl(p)}" style="height:34px;vertical-align:middle;border-radius:4px"></a>`).join(" ")}</span></div>`).join("") : '<span class="muted">Hali yo\'q</span>'}</div>`;
  const go = async () => { const t = $("#tktext").value.trim(); if (!t) return;
    try { openTaskModal(await post("/api/do/plan", { text: t })); } catch (e) { alert(e.message); } };
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
