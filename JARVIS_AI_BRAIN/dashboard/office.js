// 🏢 Jonli ofis — xodimlar (agentlar), ish jadvali, jonli lenta; 🧬 O'zini rivojlantirish (Self-Dev).
"use strict";

const OST = { working: ["ishlayapti", "ok"], waiting: ["tasdiq kutmoqda", "warn"], idle: ["bo'sh", ""] };

async function renderOfficeLive(v) {
  let last = 0;
  v.innerHTML = `<div class="row" style="justify-content:space-between"><h2 style="margin:0">🏢 Ofis — JARVIS boshqaruvida <a class="small" href="#officerooms">xonalar tarixi →</a></h2><div id="ofbar" class="small"></div></div>
    <div class="office-floor" id="ofdesks"></div>
    <div class="grid" style="grid-template-columns:minmax(320px,1.2fr) minmax(300px,1fr);margin-top:12px">
      <div class="card"><h3>📡 Jonli lenta</h3><div id="offeed" class="offeed"></div></div>
      <div class="card"><h3>🗣 Xodimga topshiriq</h3><select id="ofrole"></select><textarea id="oftext" rows="3" placeholder="Masalan: kechagi savdoni tahlil qilib, eng ko'p sotilgan 5 ta tovarni ayt"></textarea>
        <div class="row"><button id="ofask">Topshirish</button></div><div id="ofans"></div></div></div>
    <div class="card"><h3>🗓 Ish jadvali (o'zi bajaradigan ishlar)</h3><p class="small muted">Hammasi o'qish yoki loyiha tayyorlash. Nashr, xabar, kirim — har doim sizning tasdig'ingiz bilan.
      Format: <code>every:60</code> (har 60 daqiqa) yoki <code>daily:09:00</code>.</p><div id="ofrt"></div>
      <details><summary><b>+ Yangi ish qo'shish</b></summary><div class="row"><select id="nrrole"></select><input id="nrtitle" placeholder="Nomi"><input id="nrsch" placeholder="daily:10:00" style="width:120px"></div>
        <textarea id="nrprompt" rows="2" placeholder="Xodim nima qilsin (AI agent bajaradi)"></textarea><div class="row"><button id="nrsave">Qo'shish</button></div><div id="nrmsg"></div></details></div>`;
  const draw = async () => {
    const o = await api("/api/office/live");
    $("#ofbar").innerHTML = `${o.paused ? '<span class="pill bad">⏸ to\'xtatilgan</span>' : '<span class="pill ok">ishlayapti</span>'} · avtonomlik Level ${o.autonomy}
      · AI: ${o.ai ? '<span class="ok">ulangan</span>' : '<span class="warn">ulanmagan (oddiy rejim)</span>'} · <a href="#approvals">tasdiq kutmoqda: ${o.pending_approvals}</a>`;
    $("#ofdesks").innerHTML = o.staff.map((s) => `<div class="desk ${s.status}" data-role="${s.key}"><div class="desk-av">${s.emoji}</div>
      <div><b>${esc(s.name)}</b> <span class="pill ${OST[s.status][1]}">${OST[s.status][0]}${s.waiting ? ` (${s.waiting})` : ""}</span>
      <div class="small muted">${esc(s.role)}</div>
      <div class="small">${s.current ? `⚙ ${esc(s.current)}` : s.last ? `<span class="muted">${esc(String(s.last.ts).slice(11, 16))}</span> ${esc(s.last.text.slice(0, 90))}` : '<span class="muted">hali ish yo\'q</span>'}</div>
      <div class="small muted">bugun: ${s.today} ta ish</div></div></div>`).join("");
    if (!$("#ofrole").options.length) {
      const opts = o.staff.map((s) => `<option value="${s.key}">${s.emoji} ${esc(s.name)}</option>`).join("");
      $("#ofrole").innerHTML = opts; $("#nrrole").innerHTML = opts;
    }
    const nm = Object.fromEntries(o.staff.map((s) => [s.key, s]));
    $("#offeed").innerHTML = o.feed.map((f) => `<div class="fi ${f.kind}"><span class="muted">${esc(String(f.ts).slice(11, 16))}</span> ${nm[f.role] ? nm[f.role].emoji : "•"} <b>${esc(nm[f.role] ? nm[f.role].name : f.role)}</b>: ${esc(f.text)}</div>`).join("")
      || '<span class="muted">Hali faollik yo\'q — ish jadvali har daqiqa tekshiriladi.</span>';
    last = o.feed.length ? o.feed[0].id : last;
    $("#ofrt").innerHTML = `<table><tr><th>Xodim</th><th>Ish</th><th>Jadval</th><th>Oxirgi</th><th>Natija</th><th></th></tr>${o.routines.map((r) => `<tr>
      <td>${nm[r.role] ? nm[r.role].emoji : ""} ${esc(nm[r.role] ? nm[r.role].name : r.role)}</td><td>${esc(r.title)}</td>
      <td><input data-sch="${r.id}" value="${esc(r.schedule)}" style="width:110px"></td><td class="small">${esc((r.last_run || "—").replace("T", " ").slice(0, 16))}</td>
      <td class="small">${r.last_status ? `<span class="pill ${r.last_status === "ok" ? "ok" : r.last_status === "error" ? "bad" : ""}">${esc(r.last_status)}</span> ` : ""}${esc((r.last_result || "").slice(0, 80))}</td>
      <td><label class="small"><input type="checkbox" data-en="${r.id}" ${r.enabled ? "checked" : ""}> yoqilgan</label> <button class="ghost" data-rrun="${r.id}">▶ hozir</button>
      ${r.builtin ? "" : `<button class="ghost" data-rdel="${r.id}">✕</button>`}</td></tr>`).join("")}</table>`;
    v._routines = o.routines;
  };
  await draw();
  timer = setInterval(() => { if (!v.contains(document.activeElement) || document.activeElement === document.body) draw(); }, 4000);
  v.onclick = async (e) => {
    if (await agentApprovalClick(e)) return;
    const b = e.target.closest("button"); if (!b) return;
    try {
      if (b.id === "ofask") {
        const t = $("#oftext").value.trim(); if (!t) return;
        b.disabled = true; $("#ofans").innerHTML = '<p class="muted">⏳ Xodim ishlayapti…</p>';
        const r = await post("/api/office/ask", { role: $("#ofrole").value, text: t });
        $("#ofans").innerHTML = `<div class="msg assistant" style="white-space:pre-wrap">${esc(r.text || "")}</div>${r.note ? `<p class="small muted">${esc(r.note)}</p>` : ""}${agentExtrasHtml(r)}`;
        b.disabled = false; draw();
      }
      if (b.dataset.rrun) { b.disabled = true; await post(`/api/office/routines/${b.dataset.rrun}/run`); draw(); }
      if (b.dataset.rdel && confirm("Ish o'chirilsinmi?")) { await api(`/api/office/routines/${b.dataset.rdel}`, { method: "DELETE" }); draw(); }
      if (b.id === "nrsave") { await post("/api/office/routines", { role: $("#nrrole").value, title: $("#nrtitle").value, prompt: $("#nrprompt").value, schedule: $("#nrsch").value.trim() }); draw(); }
    } catch (er) { fail($("#nrmsg"), er); alert(er.message); b.disabled = false; }
  };
  v.onchange = async (e) => {
    const d = e.target.dataset, id = d.sch || d.en; if (!id) return;
    const r = v._routines.find((x) => x.id === +id);
    try { await post("/api/office/routines", { rid: r.id, role: r.role, title: r.title, prompt: r.prompt || "", schedule: d.sch ? e.target.value.trim() : r.schedule, enabled: d.en ? e.target.checked : !!r.enabled }); }
    catch (er) { alert(er.message); }
    draw();
  };
}

const IDEA_ST = { new: ["yangi", ""], working: ["ishlanmoqda…", "warn"], ready: ["ko'rib chiqishga tayyor", "ok"], accepted: ["qabul qilindi — kuzatilmoqda", "ok"],
  done: ["barqaror ✅", "ok"], failed: ["bajarilmadi", "bad"], rejected: ["rad etildi", ""], reverted: ["orqaga qaytarildi", "warn"] };

async function renderSelfDev(v) {
  const d = await api("/api/selfdev"), st = d.status;
  v.innerHTML = `<div class="card"><h3>🧬 O'zini rivojlantirish</h3>
    <p class="small muted">JARVIS kamchiliklarini o'zi topadi (qila olmagan topshiriqlar, takroriy xatolar, past baholar), Dasturchi agent kod yozadi,
    alohida nusxada <b>to'liq testdan</b> o'tkazadi (o'tmasa — xatoni o'qib qayta yozadi). Tayyor bo'lgach sizga ko'rsatadi — <b>siz "Qabul qilish"ni bosgandagina</b>
    asosiy kodga qo'shiladi, JARVIS qayta ishga tushadi va 15 daqiqa kuzatadi: muammo bo'lsa o'zi orqaga qaytaradi. Xavfsizlik, tasdiq va maxfiylik fayllarini u o'zgartira olmaydi.</p>
    <div class="row">${st.ready ? '<span class="pill ok">tayyor</span>' : `<span class="pill warn">${esc(st.note)}</span>`} ${st.busy ? '<span class="pill warn">dasturchi ishlayapti…</span>' : ""}
      ${st.watch ? '<span class="pill warn">yangi versiya kuzatilmoqda</span>' : ""}</div>
    <label>Yangi imkoniyat so'rash</label><div class="row"><input id="sdq" placeholder="Masalan: Excel fayldan grafik chizib bera oladigan bo'l" style="flex:1"><button id="sdreq">Qo'shish</button>
      <button class="ghost" id="sdcol">🔎 Kamchiliklarni qidirish</button></div><div id="sdmsg"></div></div>
    ${d.ideas.length ? d.ideas.map((i) => `<div class="card"><div class="row" style="justify-content:space-between;margin:0"><b>#${i.id} ${esc(i.title)}</b>
      <span class="pill ${(IDEA_ST[i.status] || ["", ""])[1]}">${(IDEA_ST[i.status] || [i.status])[0]}</span></div>
      <div class="small muted">manba: ${esc({ user: "siz", chat: "chat", agent_unable: "qila olmagan topshiriq", errors: "takroriy xato", feedback: "past baho", office: "ofis" }[i.source] || i.source)}
        · ${esc(String(i.ts).slice(0, 16))}${i.attempts ? ` · ${i.attempts}-urinish` : ""}</div>${i.note ? `<p class="small">${esc(i.note)}</p>` : ""}
      ${i.proposal ? `<details><summary class="small">O'zgarish: ${i.proposal.files.map(esc).join(", ")} ${i.proposal.has_test ? "· test bor" : ""}</summary><pre class="diff">${esc(i.proposal.diff)}</pre>
        ${i.proposal.test_output ? `<div class="small muted">Testlar:</div><pre>${esc(i.proposal.test_output)}</pre>` : ""}</details>` : ""}
      <div class="row">${["new", "failed"].includes(i.status) ? `<button data-dev="${i.id}">👨‍💻 Ishlab chiqish</button>` : ""}
        ${i.status === "ready" ? `<button data-acc="${i.id}">✅ Qabul qilish</button><button class="ghost" data-rej="${i.id}">Rad etish</button>` : ""}
        ${["accepted", "done"].includes(i.status) ? `<button class="ghost" data-rb="${i.id}">↩ Orqaga qaytarish</button>` : ""}
        ${["new", "failed"].includes(i.status) ? `<button class="ghost" data-rej="${i.id}">Kerak emas</button>` : ""}</div></div>`).join("")
      : '<div class="card muted">Hali g\'oya yo\'q. JARVIS har kuni kechasi kamchiliklarni o\'zi qidiradi (Ofis → Dasturchi).</div>'}`;
  if (d.ideas.some((i) => i.status === "working")) later(() => renderSelfDev(v), 4000);
  v.onclick = async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    try {
      if (b.id === "sdreq") { await post("/api/selfdev/request", { description: $("#sdq").value }); return renderSelfDev(v); }
      if (b.id === "sdcol") { const r = await post("/api/selfdev/collect"); $("#sdmsg").innerHTML = `<span class="small">${r.added} ta yangi g'oya topildi</span>`; return later(() => renderSelfDev(v), 800); }
      if (b.dataset.dev) { b.disabled = true; await post(`/api/selfdev/${b.dataset.dev}/develop`); return renderSelfDev(v); }
      if (b.dataset.acc) {
        if (!confirm("O'zgarish asosiy kodga qo'shiladi (oldin yana testlanadi), JARVIS qayta ishga tushadi va 15 daqiqa kuzatiladi. Qabul qilasizmi?")) return;
        b.disabled = true;
        const r = await post(`/api/selfdev/${b.dataset.acc}/accept`, { confirm: true });
        $("#sdmsg").innerHTML = `<p class="ok">✅ Qabul qilindi. ${esc(r.restart.note || "")}</p>`;
        return later(() => renderSelfDev(v), r.restart.restarting ? 12000 : 500);
      }
      if (b.dataset.rej) { await post(`/api/selfdev/${b.dataset.rej}/reject`, {}); return renderSelfDev(v); }
      if (b.dataset.rb && confirm("Bu o'zgarish bekor qilinsinmi (git revert)?")) { await post(`/api/selfdev/${b.dataset.rb}/rollback`); return renderSelfDev(v); }
    } catch (er) { fail($("#sdmsg"), er); b.disabled = false; }
  };
}
