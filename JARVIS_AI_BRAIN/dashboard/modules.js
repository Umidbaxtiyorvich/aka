// JARVIS dashboard — integratsiya bo'limlari. Umumiy yordamchilar ($, esc, api, table) app.js da.
const post = (path, body) => api(path, { method: "POST", body: body || {} });
const put = (path, body) => api(path, { method: "PUT", body });
// Element yo'q bo'lsa (foydalanuvchi so'rov tugashidan oldin boshqa bo'limga o'tgan) — jim o'tkazib yuboriladi
const out = (el, data) => { if (!el || !el.isConnected) return; el.hidden = false; el.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2); };
const fail = (el, e) => { if (!el || !el.isConnected) return; el.hidden = false; el.innerHTML = `<span class="bad">${esc(e.message)}</span>`; };
const fileLink = (p) => p ? `<a href="/api/studio/file?path=${encodeURIComponent(p)}" target="_blank">${esc(p.split(/[\\/]/).pop())}</a>` : "";

// ---------------- Voice ----------------
let recog = null, mediaRec = null, chunks = [];
async function renderVoice(v) {
  const st = await api("/api/voice/status");
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const uzVoice = (speechSynthesis.getVoices() || []).find((x) => x.lang && x.lang.toLowerCase().startsWith("uz"));
  v.innerHTML = `<div class="grid" style="grid-template-columns:1fr 1fr">
    <div class="card"><h3>Ovozli muloqot</h3>
      <div class="row"><button id="mic">🎙 Mikrofonni yoqish</button><span id="micst" class="pill">Mikrofon o'chiq</span></div>
      <div class="row"><label><input type="checkbox" id="speak" checked style="width:auto"> Javobni ovozda aytish</label></div>
      <div class="row"><label><input type="checkbox" id="rec" style="width:auto" ${st.save_recordings ? "" : "disabled"}> Ovozni yozib saqlash
        ${st.save_recordings ? "" : '<span class="muted">(Sozlamalarda yoqilmagan)</span>'}</label></div>
      <div id="heard" class="muted">Gapirganingiz shu yerda ko'rinadi.</div><div id="reply" style="margin-top:8px"></div>
      <p class="muted" style="margin-top:12px">${SR ? "Brauzer STT: uz-UZ. Ovoz brauzer provayderiga (Google/Microsoft) yuboriladi — internet kerak." : '<span class="warn">Bu brauzer Web Speech API ni qo\'llamaydi. Chrome yoki Edge ishlating.</span>'}<br>
      TTS: ${uzVoice ? "o'zbekcha ovoz topildi: " + esc(uzVoice.name) : '<span class="warn">o\'zbekcha TTS ovozi topilmadi — javob matn bilan ko\'rsatiladi (yoki boshqa til ovozi)</span>'}</p></div>
    <div class="card"><h3>Dvigatellar</h3>${table(st.engines.map((e) => ({ ...e, models_mb: e.models_mb ? Object.entries(e.models_mb).map(([k, x]) => k + ":" + x + "MB").join(" ") : "" })), ["id", "offline", "uzbek", "installed", "loaded_model", "models_mb"])}
      <div class="row" style="margin-top:8px"><select id="wm" style="width:140px"><option>tiny</option><option>base</option><option selected>small</option><option>medium</option></select>
      <button class="ghost" id="wl">Whisper modelini yuklash</button></div><pre id="wo" hidden></pre></div></div>`;
  $("#wl").onclick = async () => { try { out($("#wo"), await post("/api/voice/whisper/load", { text: $("#wm").value })); } catch (e) { fail($("#wo"), e); } };
  const setMic = (on) => { $("#micst").textContent = on ? "🔴 MIKROFON YOQILGAN — tinglayapman" : "Mikrofon o'chiq"; $("#micst").className = "pill " + (on ? "bad" : ""); $("#mic").textContent = on ? "⏹ To'xtatish" : "🎙 Mikrofonni yoqish"; };
  $("#mic").onclick = async () => {
    if (recog) { recog.stop(); return; }
    if (!SR) return alert("Brauzer ovozni tanishni qo'llamaydi");
    recog = new SR(); recog.lang = "uz-UZ"; recog.interimResults = true; recog.continuous = false;
    if ($("#rec").checked) {
      try { const stream = await navigator.mediaDevices.getUserMedia({ audio: true }); chunks = []; mediaRec = new MediaRecorder(stream);
        mediaRec.ondataavailable = (e) => chunks.push(e.data);
        mediaRec.onstop = async () => { stream.getTracks().forEach((t) => t.stop()); await fetch("/api/voice/recordings", { method: "POST", body: new Blob(chunks) }); };
        mediaRec.start(); } catch (e) { alert("Mikrofon ruxsati berilmadi: " + e.message); }
    }
    recog.onresult = (e) => { $("#heard").textContent = [...e.results].map((r) => r[0].transcript).join(" "); };
    recog.onerror = (e) => { $("#heard").innerHTML = `<span class="bad">Xato: ${esc(e.error)}</span>`; };
    recog.onend = async () => {
      setMic(false); recog = null; if (mediaRec && mediaRec.state !== "inactive") mediaRec.stop();
      const t = $("#heard").textContent.trim(); if (!t || t.startsWith("Gapirganingiz")) return;
      const r = await post("/api/chat", { text: t }); $("#reply").textContent = r.text;
      if ($("#speak").checked && "speechSynthesis" in window) { const u = new SpeechSynthesisUtterance(r.text); u.lang = uzVoice ? uzVoice.lang : "uz-UZ"; if (uzVoice) u.voice = uzVoice; speechSynthesis.speak(u); }
    };
    recog.start(); setMic(true);
  };
}

// ---------------- Research ----------------
async function renderResearch(v) {
  const s = await api("/api/settings");
  v.innerHTML = `${s.internet_enabled ? "" : '<div class="warnbox">Internet tadqiqoti o\'chirilgan. <a href="#settings">Sozlamalarda yoqing</a>. Hozircha mahalliy xotira va fayllar ishlaydi.</div>'}
    <div class="card"><div class="row"><input id="q" placeholder="Savol yoki qidiruv so'zi"><button id="ans">Javob (manbalar bilan)</button><button class="ghost" id="srch">Faqat qidiruv</button></div>
    <div id="r"></div></div>`;
  const show = (r) => {
    const srcs = (r.sources || []).map((x) => `<tr><td>[${x.n}]</td><td><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title || x.url)}</a><div class="muted">${esc(x.url)}</div></td>
      <td>${esc(x.fetched_at)}</td><td>${x.reliability} <span class="muted">${esc(x.reliability_note)}</span></td><td>${x.injection_flags.length ? '<span class="warn">shubhali ko\'rsatma: ' + x.injection_flags.length + "</span>" : ""}</td>
      <td><button class="ghost" data-save="${x.n}">xotiraga</button></td></tr>`).join("");
    $("#r").innerHTML = `<pre>${esc(r.answer)}</pre>${srcs ? `<table><tr><th></th><th>manba</th><th>sana</th><th>ishonch</th><th></th><th></th></tr>${srcs}</table>` : ""}
      ${(r.errors || []).length ? `<div class="muted">O'qilmadi: ${r.errors.map(esc).join("; ")}</div>` : ""}`;
    $("#r").onclick = async (e) => {
      const n = e.target.dataset.save; if (!n) return; const src = r.sources[n - 1];
      const text = prompt("Xotiraga saqlanadigan bilim (tekshirib, tahrirlang):", `${r.query}: ${src.title}`);
      if (text) { await post("/api/memory", { content: text, kind: "knowledge", source: src.url, reference: src.url, info_type: "fact",
        observed_at: src.fetched_at, confidence: src.reliability }); e.target.textContent = "saqlandi ✓ (tekshirilmagan fakt)"; }
    };
  };
  $("#ans").onclick = async () => { $("#r").textContent = "Qidirilmoqda…"; try { show(await post("/api/research/answer", { text: $("#q").value })); } catch (e) { fail($("#r"), e); } };
  $("#srch").onclick = async () => { try { const rs = await post("/api/research/search", { text: $("#q").value });
    $("#r").innerHTML = table(rs.map((x) => ({ ...x, url: x.url })), ["title", "url", "snippet", "reliability"]); } catch (e) { fail($("#r"), e); } };
}

// ---------------- Browser ----------------
async function renderBrowser(v) {
  const st = await api("/api/browser/status");
  v.innerHTML = `<div class="warnbox">Faqat o'qish rejimi: sahifa ochiladi, matn/havolalar/formalar o'qiladi. Hech narsa kiritilmaydi va yuborilmaydi. CAPTCHA va loginlar chetlab o'tilmaydi.</div>
    <div class="card"><div>Playwright: ${st.playwright ? '<span class="ok">o\'rnatilgan</span>' : '<span class="warn">o\'rnatilmagan (pip install playwright && python -m playwright install chromium)</span>'}
    · Ruxsat berilgan domenlar: ${st.allowed_domains.length ? st.allowed_domains.map(esc).join(", ") : '<span class="warn">yo\'q — Sozlamalarda qo\'shing</span>'}</div>
    <div class="row" style="margin-top:10px"><input id="u" placeholder="https://..."><button id="i">Sahifani o'qish</button><button class="ghost" id="m">Sayt tuzilishi</button></div><div id="r"></div></div>`;
  const run = async (path) => { $("#r").textContent = "Ochilmoqda…"; try { const r = await post(path, { url: $("#u").value });
    $("#r").innerHTML = `<h3>${esc(r.title)} ${r.status ? "· HTTP " + r.status : ""}</h3>${(r.notes || []).map((n) => `<div class="warn">${esc(n)}</div>`).join("")}
      ${r.screenshot ? `<div>Skrinshot: ${fileLink(r.screenshot)}</div>` : ""}
      ${r.sections ? "<h3>Bo'limlar</h3>" + table(r.sections, ["text", "href"]) : ""}
      ${r.forms && r.forms.length ? "<h3>Formalar</h3>" + table(r.forms.map((f) => ({ ...f, fields: (f.fields || []).map((x) => x.name || x).join(", ") })), ["action", "method", "fields"]) : ""}
      ${r.tables ? "<h3>Jadval sarlavhalari</h3><pre>" + esc(JSON.stringify(r.tables)) + "</pre>" : ""}
      ${r.text ? `<h3>Matn (ishonchsiz ma'lumot)</h3><pre>${esc(r.text)}</pre>` : ""}`; } catch (e) { fail($("#r"), e); } };
  $("#i").onclick = () => run("/api/browser/inspect"); $("#m").onclick = () => run("/api/browser/site-map");
}

// ---------------- Studio ----------------
async function renderStudio(v) {
  const [tools, exps] = await Promise.all([api("/api/studio/tools"), api("/api/studio/exports")]);
  const ws = (await api("/api/settings")).allowed_read_dirs[0];
  v.innerHTML = `<div class="card"><div>FFmpeg: ${tools.ffmpeg ? '<span class="ok">bor</span>' : '<span class="warn">yo\'q (winget install Gyan.FFmpeg)</span>'} · Pillow: ${tools.pillow ? '<span class="ok">' + esc(tools.pillow) + "</span>" : '<span class="warn">yo\'q</span>'}
    · AI rasm generatsiyasi: <span class="muted">${esc(tools.image_generation)}</span></div><div class="muted">Kirish fayllari: ${esc(ws)} · natijalar har doim yangi fayl (asl fayl o'zgarmaydi)</div></div>
    <div class="grid" style="grid-template-columns:1fr 1fr;margin-top:12px">
    <div class="card"><h3>Video</h3><select id="vop">${["probe:Ma'lumot", "quality:Sifat tekshiruvi (Reels)", "trim:Kesish", "vertical:9:16 Reels formati", "convert:Format o'zgartirish", "concat:Birlashtirish", "subtitles:Subtitr", "audio:Ovoz qo'shish", "slideshow:Rasmlardan video"].map((x) => `<option value="${x.split(":")[0]}">${x.split(":")[1]}</option>`).join("")}</select>
      <textarea id="vp" style="margin-top:8px"></textarea><div class="row" style="margin-top:8px"><button id="vgo">Bajarish</button></div><pre id="vo" hidden></pre></div>
    <div class="card"><h3>Rasm</h3><select id="iop">${["analyze:Tahlil", "resize:O'lcham (preset)", "text:Matn qo'shish", "logo:Logo/avatar", "prompt:Generator uchun prompt"].map((x) => `<option value="${x.split(":")[0]}">${x.split(":")[1]}</option>`).join("")}</select>
      <textarea id="ip" style="margin-top:8px"></textarea><div class="row" style="margin-top:8px"><button id="igo">Bajarish</button></div><pre id="io" hidden></pre></div></div>
    <div class="card" style="margin-top:12px"><h3>Natijalar (exports)</h3>${exps.length ? `<table>${exps.slice(0, 40).map((f) => `<tr><td>${fileLink(f.path)}</td><td class="muted">${(f.size / 1024).toFixed(0)} KB</td><td class="muted">${esc(f.path)}</td></tr>`).join("")}</table>` : '<span class="muted">Hali yo\'q</span>'}</div>`;
  const p = (f) => `${ws}/${f}`;
  const VEX = { probe: { path: p("video.mp4") }, quality: { path: p("video.mp4"), target: "reels" }, trim: { path: p("video.mp4"), start: 0, end: 10 },
    vertical: { path: p("video.mp4"), mode: "pad" }, convert: { path: p("video.mp4"), format: "mp3" }, concat: { paths: [p("a.mp4"), p("b.mp4")] },
    subtitles: { path: p("video.mp4"), lines: [{ start: 0, end: 2.5, text: "Assalomu alaykum!" }], burn: true }, audio: { path: p("video.mp4"), audio: p("musiqa.mp3"), mix: false },
    slideshow: { images: [p("1.jpg"), p("2.jpg")], seconds: 3 } };
  const IEX = { analyze: { path: p("rasm.jpg") }, resize: { path: p("rasm.jpg"), preset: "instagram_post", mode: "crop" }, text: { path: p("rasm.jpg"), text: "Chegirma 20%", position: "bottom" },
    logo: { text: "Mening Do'konim", shape: "circle" }, prompt: { subject: "yangi uzilgan non, issiq, do'kon peshtaxtasida", purpose: "instagram_post", style: "realistik, iliq ranglar" } };
  const sync = () => { $("#vp").value = JSON.stringify(VEX[$("#vop").value], null, 1); $("#ip").value = JSON.stringify(IEX[$("#iop").value], null, 1); };
  $("#vop").onchange = sync; $("#iop").onchange = sync; sync();
  const run = async (kind, op, txt, o) => { o.hidden = false; o.textContent = "Bajarilmoqda…";
    try { const r = await post(`/api/studio/${kind}`, { op, params: JSON.parse(txt) }); o.innerHTML = esc(JSON.stringify(r, null, 2)) + (r.output ? "\n\n" + fileLink(r.output) : ""); } catch (e) { fail(o, e); } };
  $("#vgo").onclick = () => run("video", $("#vop").value, $("#vp").value, $("#vo"));
  $("#igo").onclick = () => run("image", $("#iop").value, $("#ip").value, $("#io"));
}

// ---------------- Instagram ----------------
async function renderInstagram(v) {
  const [accs, posts] = await Promise.all([api("/api/instagram/accounts"), api("/api/instagram/posts")]);
  v.innerHTML = `<div class="warnbox">Faqat Meta rasmiy Graph API (Business/Creator akkaunt + Facebook sahifa + Meta App). Nashr uchun media ommaviy https:// URL bo'lishi kerak.
    Direct xabarlar alohida Messaging API ruxsatini talab qiladi — hozircha faqat izohlarga javob loyihasi. Har bir nashr aniq akkaunt va matn bilan alohida tasdiqlanadi.</div>
    <div class="card"><h3>Akkauntlar</h3>${accs.length ? table(accs, ["name", "connected", "username", "followers_count", "media_count", "note"]) :
      '<span class="muted">Akkaunt yo\'q. data/settings.json → instagram_accounts: [{"name":"shop","ig_user_id":"..."}], token: python scripts/set_secret.py instagram_token_shop</span>'}</div>
    <div class="grid" style="grid-template-columns:1fr 1fr;margin-top:12px"><div class="card"><h3>Yangi post loyihasi</h3>
      <div class="row"><select id="acc">${accs.map((a) => `<option>${esc(a.name)}</option>`).join("")}</select><select id="kind"><option value="post">Post</option><option value="reel">Reels</option><option value="story">Stories</option></select></div>
      <textarea id="cap" placeholder="Caption"></textarea><div class="row" style="margin-top:6px"><button class="ghost" id="tags">Hashtag taklifi</button><span id="tg" class="muted"></span></div>
      <input id="media" placeholder="Media URL (https://...)"><input id="when" type="datetime-local" style="margin-top:6px">
      <div class="row" style="margin-top:8px"><button id="save">Loyihani saqlash</button></div><div id="m"></div></div>
      <div class="card"><h3>Kontent kalendari</h3>${posts.length ? `<table><tr><th>#</th><th>sana</th><th>akk.</th><th>tur</th><th>caption</th><th>holat</th><th></th></tr>${posts.map((x) => `<tr><td>${x.id}</td><td>${esc(x.scheduled_at || x.created_at)}</td><td>${esc(x.account)}</td><td>${esc(x.kind)}</td><td>${esc(x.caption.slice(0, 90))}</td><td>${esc(x.status)}</td>
        <td>${x.status === "draft" ? `<button class="ghost" data-pv="${x.id}">preview</button> <button data-req="${x.id}">tasdiqqa</button>` : ""}${x.status === "pending_approval" ? `<button data-pub="${x.id}">nashr (tasdiqdan keyin)</button>` : ""}</td></tr>`).join("")}</table>` : '<span class="muted">Loyiha yo\'q</span>'}<pre id="po" hidden></pre></div></div>`;
  $("#tags").onclick = async () => { const r = await post("/api/instagram/hashtags", { text: $("#cap").value }); $("#tg").textContent = r.hashtags.join(" "); };
  $("#save").onclick = async () => { try { const tags = $("#tg").textContent.trim(); await post("/api/instagram/posts", { account: $("#acc").value, kind: $("#kind").value, caption: $("#cap").value, media_url: $("#media").value, scheduled_at: $("#when").value, hashtags: tags ? tags.split(" ") : null }); show(); } catch (e) { fail($("#m"), e); } };
  v.onclick = async (e) => { const d = e.target.dataset; try {
    if (d.pv) out($("#po"), await api(`/api/instagram/posts/${d.pv}/preview`));
    if (d.req) { await post(`/api/instagram/posts/${d.req}/request-publish`); location.hash = "approvals"; }
    if (d.pub) { out($("#po"), await post(`/api/instagram/posts/${d.pub}/publish`)); }
  } catch (er) { fail($("#po"), er); } };
}

// ---------------- Telegram ----------------
async function renderTelegram(v) {
  const st = await api("/api/telegram/status");
  v.innerHTML = `<div class="grid" style="grid-template-columns:1fr 1fr"><div class="card"><h3>Holat</h3>
    <div>Token: ${st.token_set ? '<span class="ok">kiritilgan</span>' : '<span class="warn">yo\'q</span>'}</div><div>Ruxsat berilgan IDlar: ${st.allowed_ids}</div>
    <div>Bot: ${st.running ? '<span class="ok">ishlayapti</span>' : "to'xtagan"}</div>${st.last_error ? `<div class="bad">${esc(st.last_error)}</div>` : ""}
    <div class="row" style="margin-top:10px"><button id="start" ${st.configured ? "" : "disabled"}>Ishga tushirish</button><button class="ghost" id="stop">To'xtatish</button><button class="ghost" id="test" ${st.configured ? "" : "disabled"}>Test xabar</button></div><pre id="o" hidden></pre></div>
    <div class="card"><h3>Sozlash (bir marta)</h3><ol>
      <li>Telegram'da @BotFather → /newbot → token oling.</li><li>Terminalda: <code>python scripts/set_secret.py telegram_bot_token</code> (token ko'rinmaydi, Git'ga tushmaydi).</li>
      <li>O'z ID'ingizni @userinfobot dan oling va <code>data/settings.json</code> → <code>"telegram_allowed_ids": [123456789]</code> ga yozing (xavfsizlik uchun faqat qo'lda).</li>
      <li>JARVIS'ni qayta ishga tushiring va "Ishga tushirish"ni bosing.</li></ol>
      <p class="muted">Buyruqlar: /holat /agentlar /vazifalar /tasdiqlar /xatolar /xotira. Tasdiqlash faqat dashboardda. Telegram xabari telefon qo'ng'irog'i emas.</p></div></div>`;
  const act = async (path) => { try { out($("#o"), await post(path)); } catch (e) { fail($("#o"), e); } };
  $("#start").onclick = () => act("/api/telegram/start"); $("#stop").onclick = () => act("/api/telegram/stop"); $("#test").onclick = () => act("/api/telegram/test");
}

// ---------------- Business Intelligence ----------------
async function renderBI(v) {
  const r = await api("/api/bi/report");
  const money = (x) => x == null ? "—" : Number(x).toLocaleString("uz-UZ");
  const p = r.profit;
  v.innerHTML = `<div class="card"><h3>Import (asl fayl o'zgartirilmaydi)</h3><div class="row">
    <select id="kind" style="width:200px"><option value="products">Mahsulotlar/qoldiq</option><option value="movements">Kirim/chiqim/sotuv</option><option value="payments">To'lovlar</option></select>
    <input type="file" id="f" accept=".csv,.xlsx"><button id="up">Yuklash</button></div>
    <div class="muted">Ustunlar avtomatik taniladi (o'zbek/rus/ingliz): kod, nomi, shtrix-kod, birlik, tannarx, sotish narxi, qoldiq, minimal; hujjat raqami, turi (kirim/chiqim/sotuv/qaytarish), sana, kontragent, miqdor, narx, summa.</div><pre id="o" hidden></pre></div>
    ${r.has_data ? `<div class="grid" style="margin-top:12px">
      <div class="card"><h3>Savdo summasi</h3><div class="big">${money(p.revenue)}</div></div>
      <div class="card"><h3>Tannarx</h3><div class="big">${money(p.cost_of_goods)}</div></div>
      <div class="card"><h3>Yalpi foyda</h3><div class="big ${p.gross_profit < 0 ? "bad" : "ok"}">${p.gross_profit == null ? money(p.gross_profit_known_only) + "*" : money(p.gross_profit)}</div>${p.skus_without_cost.length ? `<div class="muted">*tannarxi noma'lum: ${p.skus_without_cost.map(esc).join(", ")}</div>` : ""}</div>
      <div class="card"><h3>Kam qolgan</h3><div class="big ${r.low_stock.length ? "warn" : ""}">${r.low_stock.length}</div></div></div>
      <div class="grid" style="grid-template-columns:1fr 1fr;margin-top:12px">
      <div class="card"><h3>Kam qolgan mahsulotlar</h3>${table(r.low_stock, ["sku", "name", "current", "limit", "unit"])}</div>
      <div class="card"><h3>Noto'g'ri narx / miqdor</h3>${table(r.price_issues, ["sku", "issue", "value"])}</div>
      <div class="card"><h3>Takroriy hujjatlar</h3>${table(r.duplicates, ["type", "doc_no", "date", "party", "sku", "n", "imports"])}</div>
      <div class="card"><h3>Qoldiq tafovutlari</h3>${table(r.discrepancies, ["sku", "name", "reported_stock", "computed_from_movements", "difference", "note"])}</div>
      <div class="card"><h3>Qarzdorlik</h3>${table(r.debts, ["party", "purchases", "paid_out", "we_owe", "sales", "paid_in", "they_owe"])}</div>
      <div class="card"><h3>Kunlik savdo</h3>${table(r.sales_by_day, ["date", "checks", "qty", "total"])}</div>
      <div class="card"><h3>Mahsulot bo'yicha foyda</h3>${table(p.by_product, ["sku", "qty", "revenue", "cost", "profit"])}</div>
      <div class="card"><h3>Importlar</h3>${table(r.imports, ["id", "file_name", "kind", "rows_ok", "rows_bad", "created_at"])}</div></div>`
      : '<div class="card muted" style="margin-top:12px">Ma\'lumot yo\'q. POS\'dan eksport qilingan CSV/Excel faylni yuklang — natijalar to\'qib chiqarilmaydi.</div>'}`;
  $("#up").onclick = async () => {
    const f = $("#f").files[0]; if (!f) return alert("Fayl tanlang");
    const fd = new FormData(); fd.append("file", f);
    const res = await fetch(`/api/bi/upload?kind=${$("#kind").value}`, { method: "POST", body: fd }); const data = await res.json();
    if (!res.ok) return fail($("#o"), new Error(data.detail)); out($("#o"), data); setTimeout(show, 1500);
  };
}

// ---------------- POS ----------------
async function renderPOS(v) {
  const [st, docs] = await Promise.all([api("/api/pos/status"), api("/api/pos/documents")]);
  v.innerHTML = `<div class="card"><h3>Ulanish</h3><div>POS sayti: ${st.site ? esc(st.site) : '<span class="warn">berilmagan</span>'} · konnektor: <b>${esc(st.connector)}</b> ${st.connected ? '<span class="ok">tayyor</span>' : '<span class="warn">sozlanmagan</span>'}</div>
    <div class="muted">${esc(st.note)}</div><p class="muted">Oqim: loyiha → aniq versiyani tasdiqlash → kiritish → qayta tekshirish → audit. Loyiha o'zgarsa, tasdiq bekor bo'ladi. Natija noma'lum bo'lsa, avtomatik qayta yuborilmaydi.
    POS login/paroli chatda so'ralmaydi.</p></div>
    <div class="card" style="margin-top:12px"><h3>Yangi hujjat loyihasi</h3><div class="row"><select id="dt" style="width:160px">${["kirim", "chiqim", "sotuv", "qaytarish", "tolov"].map((x) => `<option>${x}</option>`).join("")}</select>
      <input id="party" placeholder="Yetkazib beruvchi / qabul qiluvchi"><input id="acc" placeholder="Akkaunt/filial (ixtiyoriy)" style="width:200px"></div>
      <textarea id="items">[{"sku": "A1", "name": "Non", "qty": 10, "price": 3000}]</textarea><div class="row" style="margin-top:8px"><button id="mk">Loyiha yaratish</button></div><pre id="o" hidden></pre></div>
    <div class="card" style="margin-top:12px"><h3>Hujjatlar</h3>${docs.length ? `<table><tr><th>#</th><th>tur</th><th>kontragent</th><th>mahsulotlar</th><th>jami</th><th>v</th><th>holat</th><th></th></tr>${docs.map((d) => `<tr><td>${d.id}</td><td>${esc(d.doc_type)}</td><td>${esc(d.party)}</td>
      <td>${d.items.map((i) => `${esc(i.sku)} ${i.qty}×${i.price}`).join("<br>")}</td><td>${d.total}</td><td>${d.version}</td><td>${esc(d.status)}${d.last_error ? `<div class="bad">${esc(d.last_error)}</div>` : ""}</td><td>
      ${d.status === "draft" ? `<button class="ghost" data-ed="${d.id}">tahrir</button> <button data-req="${d.id}">tasdiqqa</button>` : ""}
      ${d.status === "pending_approval" ? `<button class="ghost" data-ed="${d.id}">tahrir</button> <button data-sub="${d.id}">POSga kiritish</button>` : ""}
      ${d.status === "unknown" ? `<button data-chk="${d.id}">POSda tekshirish</button>` : ""}</td></tr>`).join("")}</table>` : '<span class="muted">Hujjat yo\'q</span>'}</div>`;
  $("#mk").onclick = async () => { try { await post("/api/pos/documents", { doc_type: $("#dt").value, party: $("#party").value, account: $("#acc").value, items: JSON.parse($("#items").value) }); show(); } catch (e) { fail($("#o"), e); } };
  v.onclick = async (e) => { const d = e.target.dataset; try {
    if (d.ed) { const doc = docs.find((x) => x.id == d.ed); const t = prompt("Mahsulotlar (JSON). O'zgartirsangiz, eski tasdiq bekor bo'ladi:", JSON.stringify(doc.items)); if (t) { await put(`/api/pos/documents/${d.ed}`, { items: JSON.parse(t) }); show(); } }
    if (d.req) { await post(`/api/pos/documents/${d.req}/request-approval`); location.hash = "approvals"; }
    if (d.sub) { out($("#o"), await post(`/api/pos/documents/${d.sub}/submit`)); setTimeout(show, 1200); }
    if (d.chk) { out($("#o"), await post(`/api/pos/documents/${d.chk}/check`)); setTimeout(show, 1200); }
  } catch (er) { fail($("#o"), er); } };
}

async function renderDocs(v) {
  const [docs, plans] = await Promise.all([api("/api/pos/documents"), api("/api/plans")]);
  v.innerHTML = `<div class="card"><h3>POS hujjatlari va versiyalari</h3>${table(docs.map((d) => ({ ...d, items: d.items.length + " qator" })), ["id", "doc_type", "party", "items", "total", "version", "status", "external_id", "updated_at"])}</div>
    <div class="card" style="margin-top:12px"><h3>Rejalar</h3>${table(plans.map((p) => ({ ...p, steps: p.steps.map((s) => `${s.n}.${s.agent}:${s.status}`).join(" ") })), ["id", "goal", "steps", "status", "created_at"])}</div>`;
}

// ---------------- Notifications ----------------
async function renderNotifications(v) {
  const rows = await api("/api/notifications");
  v.innerHTML = `<div class="card"><div class="row"><button class="ghost" id="rd">Hammasini o'qilgan deb belgilash</button></div>
    ${rows.length ? `<table><tr><th>vaqt</th><th>daraja</th><th>tur</th><th>xabar</th><th>yetkazildi</th></tr>${rows.map((n) => `<tr style="${n.read ? "opacity:.6" : ""}"><td>${esc(n.ts)}</td>
      <td class="${n.severity === "critical" ? "bad" : n.severity === "warning" ? "warn" : ""}">${esc(n.severity)}</td><td>${esc(n.category)}</td><td><b>${esc(n.title)}</b><div class="muted">${esc(n.body)}</div></td><td>${esc(n.delivered)}</td></tr>`).join("")}</table>` : '<span class="muted">Bildirishnoma yo\'q</span>'}</div>
    <div class="card" style="margin-top:12px"><h3>Telefon qo'ng'irog'i</h3><div id="tel"></div></div>`;
  $("#rd").onclick = async () => { await post("/api/notifications/read"); show(); };
  const t = await api("/api/telephony/status"); $("#tel").innerHTML = `<div>${t.configured ? '<span class="ok">sozlangan</span>' : '<span class="muted">o\'chirilgan</span>'} — ${esc(t.note)}</div>`;
}

// ---------------- Self-improvement ----------------
async function renderImprove(el) {
  const [sug, props] = await Promise.all([api("/api/improve/suggestions"), api("/api/improve/proposals")]);
  el.innerHTML = `<div class="card" style="margin-top:12px"><h3>Yaxshilash takliflari (avtomatik tahlil)</h3>${table(sug, ["source", "text"])}</div>
    <div class="card" style="margin-top:12px"><h3>Kod patch taklifi</h3><p class="muted">Patch alohida git worktree'da testdan o'tkaziladi. Tasdiqdan keyin faqat alohida branch'ga commit qilinadi — asosiy versiyaga birlashtirishni o'zingiz qilasiz. Xavfsizlik fayllarini o'zgartiruvchi patch rad etiladi.</p>
      <input id="pt" placeholder="Sarlavha"><textarea id="pd" placeholder="Unified diff (git diff natijasi)" style="margin-top:6px;min-height:120px"></textarea><div class="row" style="margin-top:8px"><button id="pc">Taklif yaratish</button></div><pre id="po" hidden></pre>
      ${props.length ? `<table><tr><th>#</th><th>sarlavha</th><th>holat</th><th>branch</th><th></th></tr>${props.map((p) => `<tr><td>${p.id}</td><td>${esc(p.title)}</td><td>${esc(p.status)}</td><td>${esc(p.branch || "")}</td><td>
        ${["proposed", "tested_fail"].includes(p.status) ? `<button class="ghost" data-t="${p.id}">test</button>` : ""}${p.status === "tested_pass" && !p.approval_id ? `<button data-r="${p.id}">tasdiqqa</button>` : ""}
        ${p.status === "tested_pass" && p.approval_id ? `<button data-a="${p.id}">branch yaratish</button>` : ""}${p.status === "applied" ? `<button class="danger" data-rb="${p.id}">bekor qilish</button>` : ""}
        ${p.test_output ? `<details><summary class="muted">test natijasi</summary><pre>${esc(p.test_output)}</pre></details>` : ""}</td></tr>`).join("")}</table>` : ""}</div>`;
  $("#pc").onclick = async () => { try { await post("/api/improve/proposals", { title: $("#pt").value, diff: $("#pd").value }); show(); } catch (e) { fail($("#po"), e); } };
  el.onclick = async (e) => { const d = e.target.dataset; try {
    if (d.t) { out($("#po"), "Test qilinmoqda…"); out($("#po"), await post(`/api/improve/proposals/${d.t}/test`)); setTimeout(show, 800); }
    if (d.r) { await post(`/api/improve/proposals/${d.r}/request-apply`); location.hash = "approvals"; }
    if (d.a) { out($("#po"), await post(`/api/improve/proposals/${d.a}/apply`)); }
    if (d.rb && confirm("Branch o'chiriladi. Davom etasizmi?")) { out($("#po"), await post(`/api/improve/proposals/${d.rb}/rollback`)); }
  } catch (er) { fail($("#po"), er); } };
}
