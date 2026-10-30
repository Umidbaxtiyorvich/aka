// JARVIS ovozli muloqot: uzluksiz suhbat (VAD — gap tugashini aniqlash), gapma-gap ovozli javob, gapirganda to'xtash (barge-in).
// Mikrofon faqat tugma bilan yoqiladi, holati doimo ko'rinadi. Ovozli "ha" xavfli amallarni TASDIQLAMAYDI — tasdiq faqat tugma bilan.
"use strict";

const VoiceUI = {
  stream: null, ctx: null, analyser: null, rec: null, chunks: [], state: "off", timer: null, audio: null, queue: [], speaking: false, stopReq: false,
};

async function renderVoice(v) {
  const [st, set, secs] = await Promise.all([api("/api/voice/pro"), api("/api/settings"), api("/api/secrets").catch(() => [])]);
  const old = await api("/api/voice/status");
  const keySet = (secs.find((x) => x.name === "azure_speech_key") || {}).set;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const pill = (ok, a, b) => `<span class="pill ${ok ? "ok" : "warn"}">${ok ? a : b}</span>`;
  v.innerHTML = `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(340px,1fr))">
    <div class="card"><h3>🗣 Suhbat rejimi</h3>
      <p class="muted small">Mikrofonni yoqing va oddiy gapiring. Gapingiz tugaganini JARVIS sukunatdan aniqlaydi, javobni gapma-gap aytadi.
        Siz gapira boshlasangiz — o'zi to'xtaydi va tinglaydi. Xavfli amallar ovoz bilan emas, faqat tugma bilan tasdiqlanadi.</p>
      <div class="row"><button id="conv">🎙 Suhbatni boshlash</button><span id="vst" class="pill">Mikrofon o'chiq</span></div>
      <div class="vu"><i id="vu"></i></div>
      <div id="vlog" class="chat" style="height:260px"></div>
      <div class="row"><input id="vtext" placeholder="Yoki yozing — javob ovozda aytiladi"><button class="ghost" id="vsend">Yuborish</button><button class="ghost" id="vstop">⏹ Ovozni to'xtatish</button></div></div>
    <div class="card"><h3>Ovoz sozlamalari</h3>
      <div class="kv"><span>Javob ovozi (hozir)</span><b>${esc(st.selected.tts)}</b></div><div class="kv"><span>Tanish (hozir)</span><b>${esc(st.selected.stt)}</b></div>
      <label>Javob ovozi dvigateli</label><select id="tts">${["auto", "azure", "espeak", "browser"].map((x) => `<option ${set.voice_tts_engine === x ? "selected" : ""}>${x}</option>`).join("")}</select>
      <label>Ovoz</label><select id="gen"><option value="female" ${set.voice_gender === "female" ? "selected" : ""}>Ayol — Madina (Azure)</option><option value="male" ${set.voice_gender === "male" ? "selected" : ""}>Erkak — Sardor (Azure)</option></select>
      <label>Tezlik: <b id="ratev">${set.voice_rate}</b>%</label><input id="rate" type="range" min="-50" max="50" value="${set.voice_rate}">
      <label>Balandlik: <b id="volv">${set.voice_volume}</b></label><input id="vol" type="range" min="0" max="100" value="${set.voice_volume}">
      <label>Nutqni tanish dvigateli</label><select id="stt">${["auto", "azure", "whisper", "browser"].map((x) => `<option ${set.voice_stt_engine === x ? "selected" : ""}>${x}</option>`).join("")}</select>
      <label>Til</label><select id="lang">${[["uz", "O'zbekcha"], ["auto", "Aralash (o'zbek/rus/ingliz)"], ["ru-RU", "Ruscha"], ["en-US", "Inglizcha"]].map(([k, t]) => `<option value="${k}" ${set.voice_stt_language === k ? "selected" : ""}>${t}</option>`).join("")}</select>
      <label>Mikrofon sezgirligi: <b id="sensv">${set.voice_mic_sensitivity}</b></label><input id="sens" type="range" min="0" max="100" value="${set.voice_mic_sensitivity}">
      <label>Gap tugadi deb hisoblash (sukunat, ms): <b id="silv">${set.voice_silence_ms}</b></label><input id="sil" type="range" min="300" max="3000" step="100" value="${set.voice_silence_ms}">
      <div class="row" style="margin-top:8px"><button id="vsave">Saqlash</button><button class="ghost" id="vtest">▶ Sinab eshitish</button></div><div id="vmsg"></div></div>
    <div class="card"><h3>Tabiiy o'zbekcha ovoz (Azure Neural)</h3>
      <p class="muted small">Microsoft Azure'da haqiqiy o'zbekcha neyron ovozlar bor: <b>Madina</b> (ayol) va <b>Sardor</b> (erkak). Tabiiy urg'u va pauzalar.
        Bu tashqi xizmat: matn va ovoz Microsoft'ga yuboriladi; bepul daraja bor (oyiga cheklangan belgilar). Kalitsiz — mahalliy espeak-ng (robotga o'xshash) ishlaydi.</p>
      <div class="kv"><span>Holat</span>${pill(st.tts.azure.ready, "tayyor", keySet ? "mintaqa kiritilmagan" : "kalit kiritilmagan")}</div>
      <ol class="small"><li><a href="https://portal.azure.com" target="_blank" rel="noopener">portal.azure.com</a> → <b>Speech service</b> yarating (Free F0).</li>
        <li><b>Keys and Endpoint</b> dan KEY 1 va <b>Location/Region</b> ni oling.</li><li>Pastga kiriting va saqlang.</li></ol>
      <label>Mintaqa (Region)</label><input id="region" placeholder="masalan: westeurope" value="${esc(set.azure_speech_region || "")}">
      <label>azure_speech_key ${keySet ? '<span class="pill ok">kiritilgan</span>' : ""}</label><input id="azkey" type="password" autocomplete="off" placeholder="${keySet ? "yangi kalit (almashtirish)" : "kalitni qo'ying"}">
      <div class="row" style="margin-top:8px"><button id="azsave">Saqlash</button></div><div id="azmsg"></div></div>
    <div class="card"><h3>Mahalliy dvigatellar</h3>
      <div class="kv"><span>espeak-ng (uz)</span>${pill(st.tts.espeak.ready, "bor", "yo'q")}</div>
      <div class="kv"><span>Whisper (mahalliy tanish)</span>${pill(st.stt.whisper.ready, "yuklangan: " + esc(st.stt.whisper.model || ""), "yuklanmagan")}</div>
      <div class="kv"><span>Brauzer tanishi (uz-UZ)</span>${pill(!!SR, "bor", "yo'q (Chrome/Edge kerak)")}</div>
      <div class="kv"><span>FFmpeg</span>${pill(st.ffmpeg, "bor", "yo'q")}</div>
      <p class="muted small">Whisper o'zbekchani <b>small</b> (≈480 MB) yoki <b>medium</b> (≈1.5 GB, 8 GB RAM'da sekin) modelda yaxshiroq taniydi. Mahsulot va do'kon nomlari lug'at sifatida beriladi.</p>
      <div class="row"><select id="wm" style="width:140px">${Object.entries(old.engines[1].models_mb || {}).map(([k, mb]) => `<option value="${k}" ${k === "small" ? "selected" : ""}>${k} (${mb} MB)</option>`).join("")}</select>
        <button class="ghost" id="wl" ${old.engines[1].installed ? "" : "disabled"}>Whisper modelini yuklash</button></div>
      ${old.engines[1].installed ? "" : '<div class="muted small">faster-whisper o\'rnatilmagan — o\'rnatuvchida "ovozni mahalliy tanish" ni tanlang.</div>'}<pre id="wo" hidden></pre></div></div>`;

  const log = (who, text, extra = "") => { const el = $("#vlog"); el.insertAdjacentHTML("beforeend", `<div class="msg ${who === "siz" ? "user" : "assistant"}">${esc(text)}${extra}</div>`); el.scrollTop = 1e9; };
  const status = (t, cls = "") => { $("#vst").textContent = t; $("#vst").className = "pill " + cls; };
  ["rate", "vol", "sens", "sil"].forEach((id) => { $("#" + id).oninput = (e) => { $("#" + id + "v").textContent = e.target.value; }; });
  const settingsBody = () => ({ voice_tts_engine: $("#tts").value, voice_gender: $("#gen").value, voice_rate: Number($("#rate").value), voice_volume: Number($("#vol").value),
    voice_stt_engine: $("#stt").value, voice_stt_language: $("#lang").value, voice_mic_sensitivity: Number($("#sens").value), voice_silence_ms: Number($("#sil").value) });
  $("#vsave").onclick = async () => { try { await post("/api/settings", settingsBody()); $("#vmsg").innerHTML = '<span class="ok">Saqlandi</span>'; } catch (e) { fail($("#vmsg"), e); } };
  $("#azsave").onclick = async () => { try { await post("/api/settings", { azure_speech_region: $("#region").value.trim() });
    if ($("#azkey").value) await post("/api/secrets", { name: "azure_speech_key", value: $("#azkey").value }); $("#azkey").value = ""; show(); } catch (e) { fail($("#azmsg"), e); } };
  $("#wl").onclick = async () => { out($("#wo"), "Yuklanmoqda (bir necha daqiqa)…"); try { out($("#wo"), await post("/api/voice/whisper/load", { text: $("#wm").value })); } catch (e) { fail($("#wo"), e); } };

  // --- gapma-gap ovozli javob ---
  const uzVoice = () => (speechSynthesis.getVoices() || []).find((x) => (x.lang || "").toLowerCase().startsWith("uz"));
  async function speak(text) {
    stopSpeaking(); VoiceUI.stopReq = false;
    let prep; try { prep = await post("/api/voice/prepare", { text }); } catch (e) { return; }
    VoiceUI.speaking = true; status("🔊 Gapiryapman… (gapirsangiz to'xtayman)", "ok");
    if (prep.engine === "browser") {
      const vv = uzVoice();
      if (!vv) { VoiceUI.speaking = false; log("JARVIS", "", '<div class="muted small">Ovozli javob uchun o\'zbekcha ovoz yo\'q (Azure kalitini kiriting yoki espeak-ng o\'rnating).</div>'); return; }
      for (const ch of prep.chunks) { if (VoiceUI.stopReq) break; await new Promise((ok) => { const u = new SpeechSynthesisUtterance(ch); u.voice = vv; u.lang = vv.lang; u.onend = ok; u.onerror = ok; speechSynthesis.speak(u); }); }
      VoiceUI.speaking = false; return;
    }
    const fetchChunk = (t) => fetch("/api/voice/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: t }) }).then((r) => (r.ok ? r.blob() : null));
    let next = prep.chunks.length ? fetchChunk(prep.chunks[0]) : null;
    for (let i = 0; i < prep.chunks.length && !VoiceUI.stopReq; i++) {
      const blob = await next; next = i + 1 < prep.chunks.length ? fetchChunk(prep.chunks[i + 1]) : null;     // keyingi gap oldindan tayyorlanadi
      if (!blob || VoiceUI.stopReq) break;
      await new Promise((ok) => { const a = VoiceUI.audio = new Audio(URL.createObjectURL(blob)); a.volume = Math.max(0, Math.min(1, Number($("#vol").value || 100) / 100)); a.onended = ok; a.onerror = ok; a.play().catch(ok); });
    }
    VoiceUI.speaking = false;
    if (VoiceUI.state !== "off") status("🎙 Tinglayapman…", "bad");
  }
  function stopSpeaking() { VoiceUI.stopReq = true; if (VoiceUI.audio) { VoiceUI.audio.pause(); VoiceUI.audio = null; } try { speechSynthesis.cancel(); } catch (e) { /* */ } VoiceUI.speaking = false; }
  $("#vstop").onclick = stopSpeaking;
  $("#vtest").onclick = () => speak("Salom! Men JARVIS. Bugungi savdo bir million ikki yuz ellik ming so'm.");

  async function ask(text) {
    if (!text.trim()) return; log("siz", text);
    try { const r = await post("/api/chat", { text }); log("JARVIS", r.text); speak(r.text.split("\nℹ️")[0]); } catch (e) { log("JARVIS", "Xato: " + e.message); }
  }
  $("#vsend").onclick = () => { const t = $("#vtext").value; $("#vtext").value = ""; ask(t); };
  $("#vtext").onkeydown = (e) => { if (e.key === "Enter") $("#vsend").click(); };

  // --- tinglash: VAD (ovoz energiyasi), sukunatda gap tugaydi; gapirganda JARVIS to'xtaydi ---
  async function startConv() {
    const sttEng = st.selected.stt;
    try { VoiceUI.stream = await navigator.mediaDevices.getUserMedia({ audio: { noiseSuppression: true, echoCancellation: true, autoGainControl: true } }); }
    catch (e) { status("Mikrofonga ruxsat berilmadi", "warn"); return; }
    VoiceUI.ctx = new (window.AudioContext || window.webkitAudioContext)(); const src = VoiceUI.ctx.createMediaStreamSource(VoiceUI.stream);
    VoiceUI.analyser = VoiceUI.ctx.createAnalyser(); VoiceUI.analyser.fftSize = 1024; src.connect(VoiceUI.analyser);
    const buf = new Float32Array(VoiceUI.analyser.fftSize), sens = Number($("#sens").value), silence = Number($("#sil").value);
    let floor = 0.01, samples = 0, speechMs = 0, quietMs = 0, capturing = false, t0 = performance.now();
    const base = 0.06 - (sens / 100) * 0.055;                       // sezgirlik: 0 → 0.06, 100 → 0.005
    VoiceUI.state = "listening"; status("🎙 Tinglayapman… (MIKROFON YOQILGAN)", "bad"); $("#conv").textContent = "⏹ Suhbatni to'xtatish";
    const begin = () => {
      capturing = true; stopSpeaking();
      if (sttEng === "browser" && SR) { const r = new SR(); r.lang = $("#lang").value === "ru-RU" ? "ru-RU" : $("#lang").value === "en-US" ? "en-US" : "uz-UZ"; r.interimResults = false;
        r.onresult = (e) => ask(e.results[0][0].transcript); r.onend = () => { capturing = false; }; r.onerror = () => { capturing = false; }; try { r.start(); } catch (e) { capturing = false; } VoiceUI.rec = r; return; }
      VoiceUI.chunks = []; VoiceUI.rec = new MediaRecorder(VoiceUI.stream); VoiceUI.rec.ondataavailable = (e) => VoiceUI.chunks.push(e.data);
      VoiceUI.rec.onstop = async () => { capturing = false; const blob = new Blob(VoiceUI.chunks, { type: "audio/webm" }); if (blob.size < 2000) return;
        status("⏳ Tanilmoqda…", "warn"); const fd = new FormData(); fd.append("file", blob, "gap.webm");
        try { const r = await fetch("/api/voice/transcribe", { method: "POST", body: fd }); const d = await r.json(); if (!r.ok) throw new Error(d.detail);
          if (d.corrections && d.corrections.length) log("JARVIS", "", `<div class="muted small">Tuzatildi: ${d.corrections.map((c) => esc(c.from) + "→" + esc(c.to)).join(", ")}</div>`);
          if (d.text) await ask(d.text); } catch (e) { log("JARVIS", "Tanib bo'lmadi: " + e.message); }
        if (VoiceUI.state !== "off" && !VoiceUI.speaking) status("🎙 Tinglayapman…", "bad"); };
      VoiceUI.rec.start(250); status("🔴 Yozilmoqda… (gapiring)", "bad");
    };
    VoiceUI.timer = setInterval(() => {
      VoiceUI.analyser.getFloatTimeDomainData(buf); let s = 0; for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i]; const rms = Math.sqrt(s / buf.length);
      if (performance.now() - t0 < 600) { floor = (floor * samples + rms) / (++samples); return; }   // dastlabki shovqin darajasi
      const thr = Math.max(base, floor * 2.8) * (VoiceUI.speaking ? 1.6 : 1); const vu = $("#vu"); if (vu.isConnected) vu.style.width = Math.min(100, rms / thr * 50) + "%";
      if (rms > thr) { speechMs += 50; quietMs = 0; if (!capturing && speechMs >= (VoiceUI.speaking ? 250 : 150)) begin(); }
      else { quietMs += 50; speechMs = Math.max(0, speechMs - 50);
        if (capturing && quietMs >= silence && VoiceUI.rec && VoiceUI.rec.state === "recording") VoiceUI.rec.stop(); }
      if (!$("#vlog").isConnected) stopConv();
    }, 50);
  }
  function stopConv() {
    VoiceUI.state = "off"; clearInterval(VoiceUI.timer);
    try { if (VoiceUI.rec && VoiceUI.rec.state === "recording") VoiceUI.rec.stop(); } catch (e) { /* */ }
    if (VoiceUI.stream) VoiceUI.stream.getTracks().forEach((t) => t.stop()); VoiceUI.stream = null;
    if (VoiceUI.ctx) VoiceUI.ctx.close().catch(() => {}); VoiceUI.ctx = null; stopSpeaking();
    if ($("#conv").isConnected) { $("#conv").textContent = "🎙 Suhbatni boshlash"; status("Mikrofon o'chiq"); }
  }
  $("#conv").onclick = () => (VoiceUI.state === "off" ? startConv() : stopConv());
  if (window.JARVIS_VIZ) window.JARVIS_VIZ.items.add({ dispose: stopConv });
}
