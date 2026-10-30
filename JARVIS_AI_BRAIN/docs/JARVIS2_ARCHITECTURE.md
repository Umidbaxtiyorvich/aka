# JARVIS 2.0 — Ultimate Autonomous: audit, arxitektura va bosqichma-bosqich reja

Tanlov: **Ultimate** daraja, birinchi ustuvor yo'nalish — **Autonomous** (o'zi rejalashtirib, vazifani oxirigacha yetkazish).
Asosiy tamoyil: JARVIS xavfsiz (LOW) ishlarni mustaqil bajaradi; o'zgartiruvchi, tashqi, pullik yoki qaytarib bo'lmaydigan amallar faqat tasdiq bilan.

## 1. Audit (v0.9 holati, kod bo'yicha)
Hajm: ~17 900 qator Python/JS, 56 backend modul, 250+ API endpoint, 33 test fayli. Backend — FastAPI + SQLite (WAL, FTS5), frontend — vanilla JS (build bosqichisiz).

### Ishlayotgan modullar
| Soha | Modul | Holat |
|---|---|---|
| Xavfsizlik yadrosi | `policy.py`, `approval.py` (A–E, payload xeshi), `auth.py` (PIN), `secrets.py` (Credential Manager), `security.py` (redaksiya), `sandbox.py`, `backup.py` | ishlaydi, testlangan |
| Rejalashtirish | `planner.py` (AI faqat matnni ajratadi), `dag.py` (bog'liqlik, parallel, takrorni qayta ishlatish, tasdiq kutish) | ishlaydi |
| Agentlar | `agents.py` — 20 agent, navbat, `tasks` jadvali | ishlaydi |
| AI | `router.py` + `ai_hub.py` (31 provayder, imkoniyatlar, strategiya, byudjet, fallback) | ishlaydi (mock bilan testlangan) |
| Xotira | `memory.py` (manba/ishonch/qarama-qarshilik), `memory_connect.py`, `kgraph.py`, `memory_import.py` (ChatGPT) | ishlaydi; **vektor qidiruv yo'q** |
| Integratsiyalar | `integrations/` (REST/OData/GraphQL/MCP/sayt/DB/fayl/desktop), POS, Telegram, Instagram | ishlaydi (real POS sinalmagan) |
| Diagnostika | `diagnostics.py`, `selfheal.py` (faqat taklif), `selfcheck.py`, `release_gate.py` | ishlaydi |
| Ovoz | `voice_pro.py` (Azure uz-UZ / espeak / Whisper), VAD | ishlaydi |
| Kengaytmalar | `plugins.py` (manifest, xesh, ruxsatlar, sandbox, tasdiq bilan yoqish) | ishlaydi — Skills Factory asosi |

### Tugallanmagan / yo'q (v0.9 gacha)
| Kerak | Holat |
|---|---|
| Markaziy avtonom sikl (maqsad → … → xotira) | Brain Core faqat biznes savollari uchun edi → **v1.0 da Mission Engine** |
| Vazifa holati: pauza, qayta urinish, checkpoint, restartdan tiklash, dead-letter, limitlar | yo'q edi → **v1.0** |
| Natijani tekshirish (Verification) | yo'q edi → **v1.0** |
| Refleksiya va tajribadan o'rganish | yo'q edi → **v1.0** (tasdiq bilan Procedural Memory) |
| Markaziy Permission Manager (ko'rinadigan ruxsat jadvali) | policy bor edi, agentlar kesimida ko'rinish yo'q → **v1.0** |
| Computer Use (sichqoncha/klaviatura, skrinshot tahlili, UI Automation) | faqat buyruq (tasdiq bilan) va ruxsat berilgan dasturni ochish; brauzer — faqat o'qish | **keyingi bosqich** |
| Workflow Studio (Trigger → Condition → Agent → Action) | yo'q | keyingi |
| Vektor qidiruv | yo'q | keyingi |
| File Intelligence: DOCX/PPTX/OCR/arxiv/tahrirlash | qisman | keyingi |
| Multi-device | PIN bilan LAN orqali brauzerdan kirish bor; HTTPS yo'q | keyingi |

### Takroriy modullar (texnik qarz)
- `planner.py` (plans jadvali) va `dag.py` — ikkalasi reja tuzadi. Mission Engine **DAG'ni** ishlatadi; `plans` eski API uchun qoldirildi (o'chirish — ruxsatsiz katta refaktor bo'lardi).
- `voice.py` va `voice_pro.py` — eski STT/TTS yordamchilari hali ayrim joylarda ishlatiladi.
- `brain_core.py` (biznes trace) va `mission.py` — birinchisi bitta javob, ikkinchisi ko'p bosqichli missiya. Keyinchalik Brain Core Mission'ning "tez yo'li" sifatida birlashtiriladi.

### Xavfsizlik holati
- Yaxshi: kalitlar Credential Manager'da, redaksiya, tasdiq xeshi, qulflangan sozlamalar (`LOCKED_KEYS`), `read_only_mode` standart yoqiq, sandbox, maxfiy ma'lumot faqat mahalliy modelga.
- Diqqat: LAN rejimida HTTPS yo'q (faqat ishonchli tarmoq); plaginlar uchun sandbox OS darajasidagi izolyatsiya emas (process + limitlar — `docs/SECURITY.md` da ochiq yozilgan); fayl yuklashda antivirus skaneri yo'q.

### Runtime
GitHub — faqat kod. Doimiy ishlash Windows 11 kompyuterda: `JARVIS.exe` → lokal server (127.0.0.1:8765), ma'lumotlar `data/` (Git'ga kirmaydi). Bulut (Claude Code) — faqat ishlab chiqish va testlar.

## 2. Yakuniy arxitektura
```
                 ┌────────────── JARVIS CENTRAL BRAIN (Mission Engine) ──────────────┐
 INPUT ─▶ Tushunish ─▶ Reja (Planner+DAG) ─▶ Ruxsat (Permission Mgr) ─▶ Bajarish (Agentlar)
          (savollar)    AI faqat matnni     LOW avtomatik;            checkpoint, retry,
                         ajratadi           MEDIUM+ — tasdiq           pauza, limitlar
                                                                         │
 MEMORY ◀─ Refleksiya ◀─ Hisobot ◀─ Tekshirish (Verification, agent qoidasi bo'yicha) ◀┘
 (tasdiq bilan)
     Smart AI Router (har agent faqat shu orqali) · Tool/Integration Registry · Audit · Events (3D Brain)
```

## 3. v1.0 da bajarilgan bosqichlar (Phase 3–7, 10–12)
- **Phase 3 — Task state:** `missions`, `mission_log`, `mission_lessons`; `dag_nodes` ga `attempts`, `max_attempts`, `verified`, `verify_note`, `dead_letter`; `dag_runs.stop_reason`.
  Statuslar: Pending, Planning, Needs input, Waiting Approval, Running, Paused, Retrying, Verifying, Completed, Failed, Cancelled.
- **Phase 4 — Central Brain (`mission.py`):** tushunish (noaniq maqsad, ulanmagan Telegram/Instagram → savol), reja, ruxsat bahosi, bajarish, tekshirish, hisobot, refleksiya.
- **Phase 5 — Planner:** mavjud Planner + DAG; "keyin" — ketma-ket, "hamda" — parallel; javob berilsa — qayta rejalash.
- **Phase 6 — Orchestrator:** DAG parallel bajarish (RAM bo'yicha cheklangan, og'ir agentlar bittadan) — mavjud; agent profillari.
- **Phase 7 — Permission Manager (`permissions.py`):** LOW/MEDIUM/HIGH/CRITICAL, agent ruxsat chegarasi, taqiqlangan buyruq → bosqich faqat maslahatga tushiriladi. Haqiqiy bajarish baribir Approval Engine orqali.
- **Phase 10–11 — Execution + persistent queue:** holat bazada, har tugagan bosqich — checkpoint; restartdan keyin idempotent bosqichlar qaytadan, tashqi ta'sirlilari **dead-letter** (ikki marta bajarilmaydi); vaqt va xarajat limiti → pauza; qo'lda qayta urinish.
- **Phase 12 — Verification:** bo'sh natija, agent xatosi, test muvaffaqiyatsizligi, manbasiz tadqiqot — "bajarildi" deb belgilanmaydi; idempotent agentda qayta urinish.
- **Refleksiya:** urinishlar, xatolar, maxsus agenti yo'q bosqichlar, model xatolari → xulosalar; tasdiqlansa **Procedural Memory**.
- **UI:** Mission Control, Agent Command. Chatda: `missiya: …`.

## 4. Keyingi bosqichlar (tartib bo'yicha)
| # | Bosqich | Nima | Asosiy xavf/cheklov |
|---|---|---|---|
| 13 | Memory Brain | mahalliy embedding (Ollama `nomic-embed-text`, ~270 MB, ixtiyoriy) + SQLite vektor jadvali; xotira konsolidatsiyasi; eksport | 8 GB RAM — embedding faqat navbat bilan |
| 14 | Computer Use | Windows UI Automation (`pywinauto`), skrinshot + vision model, sichqoncha/klaviatura (`pyautogui`), yozib olish/qayta ijro; har amal log, HIGH/CRITICAL — tasdiq | bulutda sinab bo'lmaydi — Windows'da real test kerak; CAPTCHA/MFA chetlab o'tilmaydi |
| 15 | Integratsiyalar | WebSocket, OAuth2 authorization code, Connector Wizard monitoringi | — |
| 16 | File Intelligence | DOCX/PPTX/ODT o'qish-tahrirlash (nusxada), OCR (Tesseract), arxivlar, solishtirish | OCR uchun Tesseract o'rnatish |
| 17 | Workflow Studio | Trigger → Condition → Agent → Action → Verification; jadval, webhook, tasdiq tugunlari, tarix, eksport | Mission Engine ustida |
| 18 | Self Diagnostics | Watchdog (servis to'xtasa qayta ishga tushirish), xavfsiz tiklash ro'yxati, regressiya | faqat oldindan ruxsat berilgan tiklashlar |
| 19 | Voice | ovozdan missiya boshlash/to'xtatish/holat | ovoz xavfli amalni tasdiqlamaydi |
| 20 | Command Center | global buyruq satri, faol missiyalar, xarajat, RAM | — |
| 21 | Xavfsizlik | fayl yuklash skaneri (Windows Defender CLI), prompt-injection izolyatsiyasi kengaytmasi, rate limit | — |
| 22 | Windows optimizatsiya | modelni avtomatik tushirish (Ollama keep_alive), og'ir servislarni lazy | — |

Har bosqich: audit → reja → kod → migratsiya (`CREATE IF NOT EXISTS` / `ensure_columns`) → testlar → hujjat.
Git: barcha ish `ccr-f1c0e6d1-uu59k9` branch'ida (bu sessiya uchun belgilangan); asosiy branch'ga birlashtirish — sizning qaroringiz (PR orqali).
