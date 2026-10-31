# JARVIS AI BRAIN

O'zbek tilida ishlaydigan, doimiy xotirali, agentli va **har bir muhim amalni faqat sizning tasdig'ingizdan keyin bajaradigan** shaxsiy AI yordamchi.

> JARVIS ongga ega emas. U — AI modeli (ixtiyoriy), SQLite xotira, qoidalar va ruxsat berilgan vositalardan iborat dastur.

## v0.3.0 — boshqaruv, nazorat va xavfsizlik qatlami

| Takomillashtirish | Holat | Qisqacha |
|---|---|---|
| Adaptive AI Router | ✅ | light/strong modellar, murakkablik va maxfiylik bo'yicha tanlash, ko'rinadigan fallback, OpenAI-compatible/Anthropic adapterlari |
| Resource & Cost Guard | ✅ | so'rov/token/xarajat (o'lchangan va taxminiy alohida), kunlik/oylik limit, ogohlantirish, pullik AI standart holatda o'chiq |
| Policy Engine | ✅ | low/medium/high/forbidden, buyruqlar allowlist'i, tasdiq oynasida ta'sir/maqsad/qaytarish |
| Knowledge Provenance | ✅ | fakt/taxmin/model xulosasi/foydalanuvchi ma'lumoti, manbasiz "tasdiqlangan" bo'lmaydi, eskirish, manbalarni solishtirish |
| Decision Journal | ✅ | o'zgarmas tarix, qayta ko'rib chiqish yangi qaror sifatida |
| Sandbox | ✅ (best-effort) | statik tekshiruv + audit-hook + limitlar; OS izolyatsiyasi emas — Docker ixtiyoriy |
| Backup & DR | ✅ | izchil nusxa, manifest + SHA-256, sinov-tiklash, retention, E-darajali tiklash |
| Task Dependency Graph | ✅ | bog'liqliklar, xavfsiz parallel, takrorni qayta ishlatish, xato tarqalishi, vizual |
| Knowledge Graph | ✅ | SQLite tugun/qirra, avtomatik bog'lanishlar, qidiruv, yo'l topish |
| Plugin arxitekturasi | ✅ | manifest, hash bo'yicha ishonch, minimal ruxsatlar, sandbox'da ishlash |
| Observability | ✅ | yagona diagnostika, "tekshirib bo'lmadi" holati, javob vaqtlari, eksport |
| Release Gate | ✅ | toifalangan testlar, frontend e2e, PASS/FAIL/INCOMPLETE, CI |

## v0.4.0 — qolib ketgan rejalar

| Funksiya | Holat |
|---|---|
| Instagram Reels: konteyner qayta ishlanishini kutish, noma'lum natijani qayta yubormaslik | ✅ (mock API bilan testlangan) |
| Instagram Direct: suhbatlar, javob loyihasi, 24 soat qoidasi, har xabarga tasdiq | ✅ (mock) |
| Rejalashtirilgan Instagram postlari → vaqtida tasdiq so'rovi (avtomatik nashr yo'q) | ✅ |
| Dashboard PIN (PBKDF2), sessiya, urinishlarni bloklash, Host/Origin himoyasi | ✅ |
| Dasturni tasdiq bilan ochish (app_allowlist) | ✅ |
| Avtomatik subtitr (mahalliy Whisper) | ✅ (Whisper o'rnatilsa) |
| O'zbekcha TTS (espeak-ng) — chat javobi va videoga ovoz | ✅ (real espeak-ng bilan testlangan) |
| AI bilan reja tuzish, xatodan AI patch taklifi | ✅ (AI ulansa) |
| Mahalliy rasm generatsiyasi (Stable Diffusion WebUI) va vision tahlil (Ollama) | ✅ (o'rnatilsa) |
| POS REST API konnektori (Idempotency-Key, noma'lum natija himoyasi) | ✅ (POS API bo'lsa) |
| Twilio qo'ng'irog'i + qoidalar (faqat reja va tasdiq; qo'ng'iroq tasdiqdan keyin) | ✅ (pullik, sozlansa) |
| BI hisobotini Excel'ga eksport | ✅ |
| Windows'ga kirganda avtomatik ishga tushirish (`scripts\install_autostart.ps1`) | ✅ (Windows'da sinalmagan) |

Tafsilotlar: [docs/IMPROVEMENTS_PLAN.md](docs/IMPROVEMENTS_PLAN.md), [docs/RELEASE.md](docs/RELEASE.md), [docs/BACKUP.md](docs/BACKUP.md).

## Holat (0.2.0 modullari)

**✅ Ishlaydi va testlangan** (47 ta avtomatik test + brauzerda end-to-end tekshiruv):

| Modul | Nima qiladi |
|---|---|
| Core + Chat | O'zbekcha chat (lotin/kirill, xato yozilgan so'zlar), parol yozilsa bloklaydi |
| Memory | Qo'shish, FTS qidiruv, tahrir, eksport, o'chirish; manba/sana/ishonch; zid ma'lumotni belgilaydi |
| Planner | Maqsad → bosqichlar → agentlar; tasdiq kerak bo'lsa to'xtaydi |
| 15 ta agent | Manager, Developer, File, Computer, Security, QA, Research, Browser, Voice, Image, Video, Instagram, Telegram, BI, POS — hammasining haqiqiy handleri bor, navbat bilan ishlaydi |
| Approval + Audit | A–E darajalar, tasdiq aniq versiya xeshiga bog'langan, o'zgarsa bekor; takroriy va noma'lum natijadan himoya |
| Business Intelligence | CSV/Excel import (uz/ru/en ustunlar, cp1251), qoldiq, kam qolgan, noto'g'ri narx, takroriy hujjat, tafovut, foyda, qarzdorlik, kunlik savdo |
| POS Connector | Loyiha → tasdiq → kiritish → tekshirish. Hozir `file_export` (lokal outbox fayllari) |
| Video studiya | FFmpeg: kesish, birlashtirish, 9:16, format, subtitr, ovoz, rasmlardan video, sifat tekshiruvi |
| Rasm studiya | Pillow: tahlil, Instagram/Story presetlari, matn qo'shish, logo/avatar, generator uchun prompt |
| Browser agent | Playwright: ruxsat berilgan saytni faqat o'qish, sayt tuzilishini hujjatlashtirish, skrinshot |
| Telegram Control Center | Bitta ega (kod + telefon tasdig'i), ✅/❌ tugmali muddatli bir martalik tasdiqlar, hodisa xabarlari, ovozli xabar va ovozli buyruq (tasdiq bilan), /status /tasks /approve ... |
| Instagram MCP + Graph API | MCP serverga ulanish, vositalarni aniqlash (o'qish darhol, qolgani tasdiq bilan, natija ishonchsiz deb belgilanadi); token muddati/ruxsatlari |
| 🧠 3D Brain + 🌐 Graph Explorer | Protsedura yo'li bilan yaratilgan 3D miya (Three.js, oflayn), 8 hudud — haqiqiy modullar holati; jonli hodisalar (SSE) bilan impulslar; minglab tugunli 3D bilimlar grafi (15 kategoriya, filtrlar, yo'l, PNG/SVG); Memory Explorer va Connection Engine (takrorlar, aloqa takliflari). Batafsil: [docs/BRAIN_AND_GRAPH.md](docs/BRAIN_AND_GRAPH.md) |
| ⚡ Super Brain + 🔌 Universal Connection Center | Brain Core (fikrlash quvuri, trace), Model Router (Claude/Groq/Gemini/Ollama vazifa bo'yicha), POS/ERP/CRM/sayt/API/MCP/baza/fayl/dastur ulanishlari, shifrlangan vault, discovery + mapping, sinxronlash, POS tahlilchisi, tabiiy o'zbekcha ovoz (Azure Neural). Real POS ulanishlari sinalmagan — batafsil: [docs/SUPER_BRAIN.md](docs/SUPER_BRAIN.md) |
| 🤖 AI Provider Center + 🚦 Smart Router + 📥 Memory Import | 31 ta AI provayder katalogi (kengaytiriladi), API kalit tekshiruvi, modellar va imkoniyatlar katalogi, vazifaga qarab model tanlash, byudjet va fallback, ChatGPT eksportidan xotira (tasdiq bilan). Batafsil: [docs/AI_ECOSYSTEM.md](docs/AI_ECOSYSTEM.md) |
| 🎯 Mission Control + 🤝 Agent Command (JARVIS 2.0) | Markaziy avtonom sikl: maqsad → reja → ruxsat bahosi → bajarish → tekshirish → hisobot → refleksiya. Checkpoint, qayta urinish, dead-letter, pauza, vaqt/xarajat limiti, restartdan tiklash. Chatda `missiya: ...`. Audit va reja: [docs/JARVIS2_ARCHITECTURE.md](docs/JARVIS2_ARCHITECTURE.md) |
| 🛡 JARVIS 3.0 (Safe Autonomous) | Avtonomlik darajalari 0–4 (standart 2), Guardian va favqulodda to'xtatish, Proaktiv takliflar va hisobotlar, Digital Twin, Virtual Office xonalari, Simulation Lab (nusxada sinash), Knowledge Researcher, Asset Manager, Business prognoz/anomaliya, Creative Factory holati, Skills Factory (test, versiya, rollback), qurilmalar. Batafsil: [docs/JARVIS3_AUDIT_AND_ARCHITECTURE.md](docs/JARVIS3_AUDIT_AND_ARCHITECTURE.md) |
| 🧰 Tool Registry + ⌨ Command Center | Barcha vositalar yagona katalogda (sxema, xavf, ruxsat, timeout, limit, audit); har bo'limda buyruq satri va global qidiruv (Ctrl+K), `/holat`, `/to'xtat`, `/missiya` |
| 🐝 Swarm + 🧠 Semantik xotira + 📄 File Intelligence + 🖱 Computer Control | Agentlararo topshiriq (Supervisor bilan), ma'no bo'yicha qidiruv (mahalliy model, tasdiq bilan yuklanadi), Word/PowerPoint/ODF/RTF/PDF/OCR, nusxada tahrir va yaratish, sichqoncha/klaviatura — har ketma-ketlik tasdiq bilan |
| 🔗 Havola orqali ulanish | Sayt/POS havolasini tashlang — JARVIS kirish sahifasi va kerakli maydonlarni (login, parol, ID, email, telefon) o'zi aniqlaydi, faqat shularni so'raydi, shifrlab saqlaydi, kirib ko'radi va ulansa ma'lumotni o'zi oladi |
| Router 2.0 / Self-healing | Model sifati bahosi (👍/👎 + testlar), takrorlanuvchi xatolarni guruhlash, alohida nusxada testlar, kvotali tuzatish takliflari (regressiya testi bilan), release gate'da diff ko'rigi |
| Self-improvement | Yaxshilash takliflari; "Yangi funksiya so'rash" (o'zbekcha → AI patch); patch → alohida worktree'da test → tasdiq → branch → alohida E-tasdiq bilan qayta testlanib asosiy versiyaga; orqaga qaytarish (git revert) |
| Bildirishnomalar | Dashboard (+ Telegram sozlangan bo'lsa) |

**⚠️ Kod tayyor, lekin real xizmat bilan sinalmagan** (bulut muhitida bu xizmatlarga tarmoq yopiq; testlar soxta HTTP bilan):

- **Ollama** — o'rnatsangiz ishlaydi; offline rejim har doim bor.
- **Telegram bot** — token va o'z ID'ingiz kerak.
- **Instagram** — Business/Creator akkaunt, Meta App va token kerak. Nashr uchun media ommaviy URL'da bo'lishi shart.
- **Internet tadqiqoti** — standart holatda o'chiq, Sozlamalarda yoqiladi.
- **Ovoz** — brauzer STT/TTS (Chrome/Edge, internet bilan). O'zbekcha TTS ovozi Windows'da odatda yo'q. Mahalliy Whisper ixtiyoriy.

**⏳ Hali yo'q:**

- POSga API yoki brauzer orqali to'g'ridan-to'g'ri yozish — POS manzili kerak.
- AI bilan rasm generatsiyasi — GPU yoki onlayn adapter kerak.
- Haqiqiy telefon qo'ng'irog'i — SIP provayder kerak; hozir faqat reja va tasdiq.
- Dashboard autentifikatsiyasi — shuning uchun server faqat `127.0.0.1` da ishlaydi.

Sozlash bo'yicha qo'llanmalar: [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md).

## Uch ish rejimi

1. **Cloud Development** — Claude Code bulut muhitida kod yoziladi, testlar bajariladi, GitHub'ga yuboriladi. GitHub faqat kodni saqlaydi: u server ham, JARVIS xotirasi ham emas.
2. **Local AI Runtime** — Windows 11 kompyuteringizda ishga tushirasiz. Xotira (`jarvis.db`) faqat sizning kompyuteringizda bo'ladi.
3. **Optional Cloud Deployment** — kelajakda, faqat sizning qaroringiz bilan (narx, maxfiylik, autentifikatsiya oldindan muhokama qilinadi). Hozir server faqat `127.0.0.1` da tinglaydi.

## Windows 11'ga o'rnatish — bitta buyruq

PowerShell'ni oching (Start → "PowerShell") va qo'ying:

```powershell
irm https://raw.githubusercontent.com/Umidbaxtiyorvich/aka/ccr-f1c0e6d1-uu59k9/JARVIS_AI_BRAIN/install.ps1 | iex
```

O'rnatuvchi Python, JARVIS, brauzer agenti, FFmpeg, o'zbekcha ovoz va Ollama + AI modellarini o'rnatadi (har biridan oldin so'raydi),
ish stolida **JARVIS** belgisini (`JARVIS.exe`) yaratadi va dasturni ochadi. Keyin terminal kerak emas: belgini bossangiz, JARVIS (va Ollama) o'zi yonadi va alohida oynada ochiladi. Qayta ishga tushirsangiz — yangilanadi, xotira saqlanadi.

## Windows 11'da qo'lda ishga tushirish

> Sizning kompyuteringiz (MSI GF63 Thin, 8 GB RAM) uchun tayyor qo'llanma: [docs/MENING_KOMPYUTERIM.md](docs/MENING_KOMPYUTERIM.md)

```powershell
git clone https://github.com/Umidbaxtiyorvich/aka.git
cd aka\JARVIS_AI_BRAIN
powershell -ExecutionPolicy Bypass -File scripts\check_system.ps1   # GPU/RAM/disk diagnostikasi (faqat o'qiydi)
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1  # .venv + kutubxonalar (~60 MB) + testlar
powershell -ExecutionPolicy Bypass -File scripts\start_windows.ps1  # http://127.0.0.1:8765 — birinchi kirishda PIN o'rnatasiz
powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1   # (ixtiyoriy) Windows'ga kirganda avtomatik ishga tushirish
```

Ma'lumotlar standart holatda `JARVIS_AI_BRAIN\data\` ichida. Boshqa diskda saqlash ixtiyoriy: `setx JARVIS_HOME D:\JARVIS_DATA`.

Fayl tahlili uchun fayllarni `data\workspace\` ichiga joylang (faqat shu papka ruxsat etilgan). Boshqa papkalarni `data\settings.json` dagi `allowed_read_dirs` ga o'zingiz qo'shasiz.

### Mahalliy AI (Ollama) — ixtiyoriy

Model avtomatik yuklanmaydi. 8 GB RAM uchun boshlang'ich tavsiya — `qwen2.5:1.5b` (~1 GB disk, ~2 GB RAM).

1. https://ollama.com dan Ollama'ni o'rnating.
2. `ollama pull qwen2.5:1.5b`
3. Dashboard → Sozlamalar → Provider: `ollama` → Saqlash. Holat darhol tekshiriladi.

GPU (VRAM 6 GB+) bo'lsa, kattaroq modellar Sozlamalar → Model katalogida ko'rsatilgan.

## Ishlab chiqish (Linux/bulut)

```bash
cd JARVIS_AI_BRAIN
pip install -r requirements.txt httpx
python -m pytest -q
python scripts/release_gate.py   # PASS / FAIL / INCOMPLETE
./scripts/start.sh            # http://127.0.0.1:8765
```

## Chat buyruqlari namunasi

- `yordam` — nima ishlaydi va nima hali yo'q
- `eslab qol: hisobotlar har dushanba` · `xotira: hisobot`
- `vazifa: POS manzilini topish`
- `holat` · `fayllar` · `test` · `savdo hisoboti`
- `reja tuz: testlarni tekshir keyin savdo hisoboti`
- `internetdan qidir: ffmpeg subtitr` (internet yoqilgan bo'lsa)
- ``bajar `dir` `` — buyruq taklif qilinadi, tasdiqlashlar bo'limida tasdiqlanadi

## Hujjatlar

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — arxitektura va modullar
- [docs/SECURITY.md](docs/SECURITY.md) — xavfsizlik, tasdiqlash, maxfiy kalitlar
- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) — Ollama, Telegram, Instagram, POS, ovoz, FFmpeg, Playwright sozlash
- [docs/ROADMAP.md](docs/ROADMAP.md) — keyingi bosqichlar
