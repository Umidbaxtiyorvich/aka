// Ulanish yo'riqnomalari: har bir bo'lim tepasida "Qanday ulanadi?" bloki.
// Maxfiy kalitlar shu yerning o'zida kiritiladi (Windows Credential Manager'ga yoziladi, ekranga hech qachon qaytarilmaydi).
const SETTINGS_FILE = "JARVIS papkasi\\data\\settings.json";

const GUIDES = {
  chat: {
    title: "AI qanday ulanadi?",
    steps: [
      "JARVIS mahalliy AI uchun <b>Ollama</b> dasturidan foydalanadi. O'rnatuvchi uni o'rnatgan va modellarni sozlagan.",
      "Ollama ishlayotganini tekshiring: ekranning pastki o'ng burchagida lama belgisi bo'lishi kerak. Bo'lmasa, Start → <b>Ollama</b> ni oching.",
      "<a href=\"#router\">AI Router</a> bo'limida qaysi model ishlatilishini va holatini ko'rasiz.",
      "Javob kelmasa yoki \"offline\" deb yozsa: <a href=\"#settings\">Sozlamalar</a> → Provider: <b>ollama</b> → Saqlash.",
    ],
    note: "8 GB RAM'da birinchi javob 10–30 soniya olishi mumkin — model xotiraga yuklanadi. Keyingilari tezroq.",
  },
  router: {
    title: "Qo'shimcha (pullik) AI ulash",
    steps: [
      "Standart holatda faqat mahalliy, bepul modellar ishlaydi.",
      "Pullik provayder (OpenAI, Anthropic va h.k.) qo'shsangiz, uning kalitini pastdagi maydonga kiriting. Nomi: <code>ai_key_&lt;provayder id&gt;</code>.",
      "Pullik AI faqat \"Pullik AI'ga ruxsat\" yoqilsa va kunlik/oylik limit ichida ishlaydi. Shaxsiy ma'lumotli savollar baribir faqat mahalliy modelga yuboriladi.",
    ],
    secrets: "ai_key_",
  },
  telegram: {
    title: "Telegram botni qanday ulash mumkin?",
    steps: [
      "Telegram'da <b>@BotFather</b> ga yozing → <code>/newbot</code> → botga nom bering. U sizga <b>token</b> beradi (masalan <code>123456:ABC...</code>).",
      "Tokenni pastdagi <b>telegram_bot_token</b> maydoniga qo'ying va <b>Saqlash</b> ni bosing.",
      "O'z Telegram ID'ingizni bilish uchun <b>@userinfobot</b> ga yozing — u raqam qaytaradi.",
      `Xavfsizlik uchun botga kim yoza olishini faqat siz qo'lda belgilaysiz: Bloknot (Notepad) bilan <code>${SETTINGS_FILE}</code> faylini oching va <code>"telegram_allowed_ids": [123456789]</code> qatoriga ID'ingizni yozing, saqlang.`,
      "JARVIS'ni yoping va ish stolidagi <b>JARVIS</b> belgisi bilan qayta oching → shu bo'limda <b>Ishga tushirish</b> → <b>Test xabar</b>.",
    ],
    note: "Bot orqali tasdiqlash so'rovlari ko'rinadi, lekin tasdiqlash faqat shu dashboard'da qilinadi.",
    secrets: ["telegram_bot_token"],
  },
  instagram: {
    title: "Instagram'ni qanday ulash mumkin?",
    steps: [
      "Instagram akkauntingiz <b>Professional</b> (Business yoki Creator) bo'lishi va Facebook sahifaga ulangan bo'lishi kerak: Instagram → Sozlamalar → Akkaunt turi.",
      "<a href=\"https://developers.facebook.com/apps\" target=\"_blank\" rel=\"noopener\">developers.facebook.com</a> da ilova (App) yarating va <b>Instagram Graph API</b> ni qo'shing.",
      "Graph API Explorer'da ruxsatlarni tanlang: <code>instagram_basic</code>, <code>instagram_content_publish</code>, <code>instagram_manage_comments</code>, <code>instagram_manage_insights</code> → <b>Generate Access Token</b>, so'ng uni <b>long-lived</b> (60 kunlik) tokenga almashtiring.",
      "Akkaunt ID'sini toping (Explorer'da <code>me/accounts?fields=instagram_business_account</code>) va pastda akkaunt qo'shing.",
      "Tokenni <b>instagram_token_&lt;nom&gt;</b> maydoniga qo'ying va saqlang.",
    ],
    note: "Har bir post, izohga javob va Direct xabar alohida tasdiq bilan yuboriladi. Token muddati tugashidan oldin bildirishnoma keladi.",
    secrets: "instagram_token_",
    form: "instagram",
  },
  pos: {
    title: "YesPOS (va boshqa POS) qanday ulanadi?",
    steps: [
      "<b>YesPOS sozlamasi</b> tugmasini bosing — manzil va hisobot sahifasi o'zi to'ldiriladi.",
      "<b>POS'ga kirish</b> ni bosing: alohida brauzer oynasi ochiladi, login va parolni <b>o'zingiz</b> kiritasiz (JARVIS ularni ko'rmaydi va saqlamaydi). Kirib bo'lgach oynani yoping.",
      "Hisobot manbalarini yoqing va oraliqni tanlang — JARVIS hisobotlarni faqat <b>o'qiydi</b> va BI bo'limiga yuklaydi.",
      "Sessiya tugasa, \"qayta kiring\" degan bildirishnoma keladi — 2-qadamni takrorlaysiz.",
      "Muqobil: YesPOS'dan Excel hisobotini yuklab olib, <a href=\"#bi\">Business Intelligence</a> bo'limiga tashlang.",
    ],
    note: "POS'ga kirim, chiqim, to'lov yoki savdo yozish faqat sizning alohida tasdig'ingiz bilan. REST API bo'lsa, tokenni pastga kiriting.",
    secrets: ["pos_api_token"],
  },
  research: {
    title: "Internet tadqiqotini yoqish",
    steps: ["Standart holatda internet o'chiq.", "<a href=\"#settings\">Sozlamalar</a> → <b>Internet tadqiqotiga ruxsat</b> → Saqlash.",
      "Topilgan sahifalar ishonchsiz ma'lumot sifatida belgilanadi — ulardagi buyruqlar bajarilmaydi."],
  },
  browser: {
    title: "Brauzer agenti",
    steps: ["Brauzer agenti uchun Chromium o'rnatuvchi tomonidan o'rnatiladi (so'ralganda \"ha\" deyilgan bo'lsa).",
      "Agent faqat <a href=\"#settings\">Sozlamalar</a>dagi ruxsat berilgan domenlarga kiradi va faqat o'qiydi.",
      "O'rnatilmagan bo'lsa: o'rnatuvchini qayta ishga tushirib, brauzer agenti savoliga \"ha\" deng."],
  },
  studio: {
    title: "Rasm va video uchun nima kerak?",
    steps: ["Video tahriri va subtitr uchun <b>FFmpeg</b> kerak — o'rnatuvchi so'raydi.",
      "Rasm yaratish uchun <b>Stable Diffusion WebUI</b> ni <code>--api</code> bilan ishga tushiring va <a href=\"#settings\">Sozlamalar</a>da manzilini yozing (odatda <code>http://127.0.0.1:7860</code>).",
      "Rasm mazmunini tushunish uchun Ollama'da <b>moondream</b> modeli bo'lishi kerak."],
  },
  voice: {
    title: "Ovoz bilan ishlash",
    steps: ["Mikrofon tugmasini bosganda brauzer ruxsat so'raydi — <b>Разрешить</b> ni bosing.",
      "O'zbekcha ovozli javob uchun <b>espeak-ng</b>, ovozni matnga aylantirish uchun <b>faster-whisper</b> kerak — o'rnatuvchi so'raydi.",
      "Mikrofon yonganida ekranda belgi ko'rinadi; yozuvlar standart holatda saqlanmaydi."],
  },
  notifications: {
    title: "Telefon qo'ng'irog'i (Twilio) — ixtiyoriy, pullik",
    steps: ["<a href=\"https://www.twilio.com\" target=\"_blank\" rel=\"noopener\">twilio.com</a> da ro'yxatdan o'ting va telefon raqam oling.",
      "Pastda Account SID, raqamingiz va bir daqiqa narxini yozing, <b>twilio_auth_token</b> ni kiriting.",
      "Qo'ng'iroq hech qachon avtomatik qilinmaydi — har biri tasdiq bilan."],
    secrets: ["twilio_auth_token"],
    form: "twilio",
  },
  settings: {
    title: "Asosiy sozlamalar",
    steps: ["Bu yerda AI provayderi, internet, POS manzili va boshqalarni o'zgartirasiz. Har bir o'zgarish audit jurnaliga yoziladi.",
      `Xavfsizlik sozlamalari (Telegram ID'lari, ruxsat berilgan papkalar, faqat-o'qish rejimi) ataylab faqat <code>${SETTINGS_FILE}</code> faylida Bloknot bilan o'zgartiriladi — JARVIS ularni o'zi o'zgartira olmaydi.`],
  },
};

function guideHtml(id) {
  const g = GUIDES[id];
  if (!g) return "";
  return `<details class="guide" data-guide="${id}"><summary>${g.title}</summary>
    <ol>${g.steps.map((s) => `<li>${s}</li>`).join("")}</ol>${g.note ? `<div class="note">${g.note}</div>` : ""}
    ${g.form ? `<div class="gform" style="margin-top:12px"></div>` : ""}
    ${g.secrets ? `<div class="gsec" style="margin-top:12px"></div>` : ""}</details>`;
}

async function fillGuide(box, id) {
  const g = GUIDES[id];
  const sec = box.querySelector(".gsec"), form = box.querySelector(".gform");
  const s = form ? await api("/api/settings").catch(() => null) : null;
  if (form && s && g.form === "instagram") {
    form.innerHTML = `<b>Akkauntlar</b>: ${s.instagram_accounts.length ? s.instagram_accounts.map((a) => `<code>${esc(a.name)}</code> (${esc(a.ig_user_id)})`).join(", ") : '<span class="muted">yo\'q</span>'}
      <div class="row" style="margin-top:6px"><input class="ga-n" placeholder="nom, masalan: shop"><input class="ga-i" placeholder="ig_user_id (raqam)"><button class="ga-b">Qo'shish</button></div><div class="ga-m"></div>`;
    form.querySelector(".ga-b").onclick = async () => {
      const accs = s.instagram_accounts.concat([{ name: form.querySelector(".ga-n").value.trim().toLowerCase(), ig_user_id: form.querySelector(".ga-i").value.trim() }]);
      try { await api("/api/settings", { method: "POST", body: { instagram_accounts: accs } }); show(); } catch (e) { form.querySelector(".ga-m").innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
    };
  }
  if (form && s && g.form === "twilio") {
    form.innerHTML = `<div class="row"><input class="gt-s" placeholder="Account SID (AC...)" value="${esc(s.telephony_account_sid || "")}"><input class="gt-f" placeholder="Raqam (+1...)" value="${esc(s.telephony_from || "")}">
      <input class="gt-c" type="number" step="0.01" placeholder="1 daqiqa narxi" value="${esc(s.telephony_cost_per_min || "")}"><button class="gt-b">Saqlash</button></div><div class="gt-m"></div>`;
    form.querySelector(".gt-b").onclick = async () => {
      try { await api("/api/settings", { method: "POST", body: { telephony_provider: "twilio", telephony_account_sid: form.querySelector(".gt-s").value.trim(),
        telephony_from: form.querySelector(".gt-f").value.trim(), telephony_cost_per_min: Number(form.querySelector(".gt-c").value || 0) } });
        form.querySelector(".gt-m").innerHTML = '<span class="ok">Saqlandi</span>'; } catch (e) { form.querySelector(".gt-m").innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
    };
  }
  if (!sec) return;
  const all = await api("/api/secrets").catch(() => []);
  const names = Array.isArray(g.secrets) ? g.secrets : all.map((x) => x.name).filter((n) => n.startsWith(g.secrets));
  const isSet = Object.fromEntries(all.map((x) => [x.name, x.set]));
  sec.innerHTML = `<b>Maxfiy kalitlar</b> <span class="muted">— Windows Credential Manager'da saqlanadi, ekranda qayta ko'rsatilmaydi</span>
    ${names.length ? names.map((n) => `<div class="row" style="margin-top:6px"><code style="min-width:190px">${esc(n)}</code>
      ${isSet[n] ? '<span class="pill ok">kiritilgan</span>' : '<span class="pill warn">kiritilmagan</span>'}
      <input type="password" autocomplete="off" data-sn="${esc(n)}" placeholder="${isSet[n] ? "yangi qiymat (almashtirish)" : "qiymatni qo'ying"}">
      <button data-ss="${esc(n)}">Saqlash</button>${isSet[n] ? `<button class="ghost" data-sd="${esc(n)}">O'chirish</button>` : ""}</div>`).join("")
    : `<div class="muted" style="margin-top:6px">Avval ${g.form === "instagram" ? "akkaunt" : "provayder"} qo'shing — kalit maydoni shundan keyin chiqadi.</div>`}<div class="gs-m"></div>`;
  sec.onclick = async (e) => {
    const d = e.target.dataset, m = sec.querySelector(".gs-m");
    try {
      if (d.ss) { const inp = sec.querySelector(`input[data-sn="${d.ss}"]`); await api("/api/secrets", { method: "POST", body: { name: d.ss, value: inp.value } }); inp.value = ""; m.innerHTML = '<span class="ok">Saqlandi. Kerak bo\'lsa JARVIS\'ni qayta oching.</span>'; fillGuide(box, id); }
      if (d.sd && confirm(`${d.sd} o'chirilsinmi?`)) { await api("/api/secrets/delete", { method: "POST", body: { name: d.sd } }); fillGuide(box, id); }
    } catch (er) { m.innerHTML = `<span class="bad">${esc(er.message)}</span>`; }
  };
}

function attachGuide(view, id) {
  if (!GUIDES[id]) return;
  view.insertAdjacentHTML("afterbegin", guideHtml(id));
  const box = view.querySelector(".guide");
  box.addEventListener("toggle", () => { if (box.open && !box.dataset.filled) { box.dataset.filled = "1"; fillGuide(box, id); } });
  if (localStorage.getItem("guide_seen_" + id) !== "1") { box.open = true; try { localStorage.setItem("guide_seen_" + id, "1"); } catch (e) { /* ixtiyoriy */ } }
}
