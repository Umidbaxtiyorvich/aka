# JARVIS ULTIMATE ALL-IN-ONE (Safe Autonomous) — Phase 1 audit va Phase 2 arxitektura

Holat: **v1.0.0** (`ccr-f1c0e6d1-uu59k9`, commit e101a98). Bu hujjat faqat audit va taklif — kod o'zgartirilmadi.
Tanlov: yo'nalish — **hammasi (All-in-One)**, avtonomlik siyosati — **Safe**. Keyingi bosqichlar foydalanuvchi tasdig'idan keyin.

---

## 1. Mavjud arxitektura xaritasi

```
Windows 11 runtime (JARVIS.exe → python -m jarvis.api → 127.0.0.1:8765)        Bulut (Claude Code) — faqat ishlab chiqish/testlar
│
├─ Dashboard (vanilla JS, 9 fayl, ~45 bo'lim)  ── HTTP + SSE (/api/events/stream)
│
├─ FastAPI (api.py, ~260 endpoint) ── PIN auth, Host/Origin tekshiruvi, USER_ERRORS → 400
│
├─ JarvisCore (core.py) — barcha modullarni bitta jarayonda ulaydi
│   ├─ Miya:       mission.py (Mission Engine) · brain_core.py (biznes trace) · planner.py · dag.py · intent.py
│   ├─ Agentlar:   agents.py (20 agent, navbat) · permissions.py (agent profillari)
│   ├─ AI:         router.py (Smart Router) · ai_hub.py (31 provayder) · ai_engine.py · resource_guard.py (xarajat)
│   ├─ Xotira:     memory.py (FTS5) · memory_connect.py · kgraph.py · memory_import.py · decisions.py · brain.py (3D holat)
│   ├─ Xavfsizlik: policy.py · approval.py (A–E, xesh) · auth.py · secrets.py · security.py · sandbox.py · backup.py
│   ├─ Integratsiya: integrations/ (REST, OData, GraphQL, MCP, sayt, DB, fayl, desktop, vault) · pos.py · pos_sync.py · bi.py
│   ├─ Kanallar:   telegram_bot.py · instagram.py · instagram_mcp.py · telephony.py · notify.py · events.py
│   ├─ Ish vositalari: files.py · computer.py · browser.py · research.py · studio.py · imagegen.py · voice.py · voice_pro.py
│   └─ Sog'liq:    diagnostics.py · selfcheck.py · selfheal.py · improve.py · plugins.py · system_info.py
│
└─ SQLite (data/jarvis.db, WAL) · secrets → Windows Credential Manager · vault/*.bin (Fernet) · data/ Git'ga kirmaydi
```

Hajm: ~17 900 qator (Python + JS), 56 backend modul, 56 jadval, 33 test fayli (232 test), CI: Ubuntu + Windows + brauzer + Windows installer.
Texnologiyalar: Python 3.11+, FastAPI, Uvicorn, SQLite, Playwright (ixtiyoriy), FFmpeg, Ollama, keyring, cryptography, Pillow, openpyxl, pypdf, Three.js (vendored).

---

## 2. Existing features report — so'ralgan 23 menyu bo'yicha

| # | Menyu | Holat | Mavjud asos |
|---|---|---|---|
| 1 | Main Dashboard | ✅ bor | Brain Dashboard |
| 2 | Mission Control | ✅ bor (v1.0) | mission.py: reja, risk, checkpoint, retry, dead-letter, pauza, limit, tiklash, tekshiruv, refleksiya |
| 3 | AI Brain | ✅ bor | Super Brain Control, Brain Core trace |
| 4 | Agent Command Center | 🟡 qisman | 20 agent + ruxsat jadvali; **agentlararo topshiriq va Supervisor yo'q** |
| 5 | AI Provider Hub | ✅ bor | 31 provayder, tekshiruv, modellar, imkoniyatlar (mock bilan testlangan) |
| 6 | Smart AI Router | ✅ bor | strategiya, byudjet, fallback, jonli model |
| 7 | Memory Brain | 🟡 qisman | FTS5 qidiruv, manba/ishonch, takror/qarama-qarshilik, ChatGPT import, procedural; **vektor qidiruv va konsolidatsiya yo'q** |
| 8 | 3D Brain | ✅ bor | jonli hodisalar bilan |
| 9 | Graph Explorer | ✅ bor | 15 kategoriya, filtrlar, yo'l |
| 10 | Virtual AI Office | 🟡 qisman | `office` bo'limi — agent holatlari ko'rinishi; **xonalar, umumiy kontekst, agent suhbati yo'q** |
| 11 | Computer Control | 🟡 qisman | buyruq (tasdiq bilan), ruxsat berilgan dasturni ochish, desktop o'qish; **sichqoncha/klaviatura, UI Automation, skrinshot tahlili yo'q** |
| 12 | Browser Automation | 🟡 qisman | Playwright: o'qish, sayt xaritasi, login (CAPTCHA/MFA'da to'xtaydi); **forma to'ldirish, yozib olish/ijro yo'q** |
| 13 | File Intelligence | 🟡 qisman | TXT/kod/CSV/XLSX/PDF (2 MB); **DOCX/PPTX/OCR/arxiv/tahrirlash/solishtirish yo'q** |
| 14 | Creative Factory | 🟡 qisman | FFmpeg (kesish, birlashtirish, 9:16, subtitr, ovoz), Pillow, mahalliy SD WebUI; **bulut rasm/video adapterlari yo'q** |
| 15 | Business Command Center | 🟡 qisman | BI, POS tahlilchisi (multi-do'kon); **prognoz va anomaliya yo'q** |
| 16 | Universal Integrations | ✅ bor | Connection Center; **WebSocket va OAuth2 authorization code yo'q** |
| 17 | Workflow Studio | ❌ yo'q | (DAG va scheduler asos bo'la oladi) |
| 18 | Simulation Lab | 🟡 qisman | sandbox (kod), selfheal worktree'da test, integratsiya yozuvlari faqat taklif; **DB test nusxasi, dry-run, before/after yo'q** |
| 19 | Digital Twin | ❌ yo'q | (preference/decision xotirasi asos) |
| 20 | Skills Factory | 🟡 qisman | plugins.py: manifest, xesh, ruxsatlar, sandbox, tasdiq bilan yoqish; **versiya/rollback, testlar, AI yaratishi yo'q** |
| 21 | Guardian & Security | 🟡 qisman | health_watch (RAM, disk, Ollama, ulanishlar), diagnostika, selfheal, audit, backup; **API xarajat anomaliyasi, avtomatik xavfsiz tiklash ro'yxati yo'q** |
| 22 | Usage & Costs | ✅ bor | AI Router va xarajat, so'rovlar jurnali |
| 23 | Settings | ✅ bor | qulflangan xavfsizlik kalitlari bilan |

Qo'shimcha mavjud: Telegram Control Center, Instagram, ovoz (Azure uz-UZ / Whisper / VAD), tasdiqlar, bildirishnomalar, xatolar, testlar, zaxira, policy.

---

## 3. Missing features report

| Kerak | Nima yetishmaydi | Murakkablik |
|---|---|---|
| **Autonomy Levels (0–4)** | yagona sozlama yo'q; hozir faqat "LOW avtomatik" (≈ Level 2) | o'rta — markaziy |
| **Tool Registry** | agent handlerlari kodda; ID, schema, risk, timeout, retry yagona katalogda yo'q | o'rta |
| **Agentlararo topshiriq + Supervisor** | agent faqat bitta vazifani bajaradi | o'rta |
| **Token/vaqt limiti per agent** | missiya darajasida vaqt/xarajat bor; agent darajasida yo'q | past |
| **Expiring / per-project approvals** | Telegram TTL bor, dashboard tasdiqlari muddatsiz | past |
| **Global emergency stop missiyalarga** | `stop_automation` jadval va POS'ni to'xtatadi, **Mission Engine'ni to'xtatmaydi** | past (tuzatish kerak) |
| Vektor xotira | embedding + qidiruv | o'rta (RAM) |
| Computer Use | UI Automation, input, skrinshot | yuqori (faqat Windows'da test) |
| File Intelligence kengaytmasi | DOCX/PPTX/OCR/arxiv | o'rta |
| Workflow Studio | vizual tugunlar, triggerlar | yuqori |
| Simulation Lab | DB nusxa, dry-run, before/after | o'rta |
| Digital Twin | tasdiqlangan profil + takliflar | o'rta |
| Proactive Intelligence | tugallanmagan ish/muddat kuzatuvi, kunlik/haftalik hisobot | o'rta |
| Multi-device | HTTPS, qurilma ro'yxati, sessiyalar | o'rta |
| Projects entity | loyiha tushunchasi faqat xotira maydonida | o'rta |

---

## 4. Security report

| # | Topilma | Daraja | Tavsiya |
|---|---|---|---|
| S1 | `stop_automation` (favqulodda to'xtatish) ishlayotgan **missiyalarni to'xtatmaydi** | **Yuqori** | Mission/DAG `stop_check` global pauzani ham tekshirsin |
| S2 | Windows'da sandbox xotira/CPU limitlari (`resource`) qo'llanmaydi — faqat timeout va audit-hook | **Yuqori** (Windows) | Windows Job Object orqali limit; hujjatda ochiq yozilgan, UI'da ham ko'rsatish |
| S3 | LAN rejimida HTTPS yo'q (PIN bor) | O'rta | Multi-device bosqichida self-signed TLS yoki faqat localhost + tunnel |
| S4 | Dashboard tasdiqlari muddatsiz | O'rta | `expires_at`; eski tasdiq bajarilmasin |
| S5 | Yuklangan fayllar antivirusdan o'tmaydi | O'rta | Windows Defender `MpCmdRun -Scan` (mavjud bo'lsa), aks holda ogohlantirish |
| S6 | Integratsiya `check_url` LAN manzillariga ruxsat beradi (POS uchun kerak) — SSRF xavfi past, chunki URL'ni faqat foydalanuvchi kiritadi | Past | hujjatlashtirish; AI-yaratgan URL'lar uchun research.py dagi kabi private-IP filtri |
| S7 | Audit/usage jadvallari uchun retention yo'q (disk o'sadi) | Past | 180 kun siyosati, backup'dan keyin tozalash (tasdiq bilan) |
| S8 | Bitta SQLite ulanishi + global lock — xavfsiz, lekin uzoq yozuvlar UI'ni sekinlatishi mumkin | Past | og'ir importlar uchun alohida ulanish |

Kuchli tomonlar: kalitlar Credential Manager/Fernet'da va hech qachon qaytarilmaydi; redaksiya loglarda; tasdiq payload xeshiga bog'langan; xavfsizlik sozlamalari API orqali o'zgarmaydi (`LOCKED_KEYS`); `read_only_mode` standart; maxfiy matn faqat mahalliy modelga; Host/Origin himoyasi; PIN urinish cheklovi; ZIP import xavfsiz; prompt-injection: tashqi matn `<untrusted>` va "tarixiy ma'lumot" sifatida.

---

## 5. Database report

56 jadval, WAL rejimi, migratsiyalar — `CREATE TABLE IF NOT EXISTS` + `ensure_columns` (qo'shimcha ustunlar; o'chirish/o'zgartirish yo'q).

| So'ralgan entity | Mavjud jadval | Izoh |
|---|---|---|
| users | — (bitta egasi: PIN + `telegram_owner`) | Multi-device bosqichida `devices` kerak; ko'p foydalanuvchi shart emas |
| projects | — | **yangi** `projects` kerak (xotira/missiya/fayllarni bog'lash) |
| tasks / task_steps / task_checkpoints | `missions`, `dag_runs`, `dag_nodes` (checkpoint = tugagan node), `tasks`, `plans` | mavjud; `plans` eski — muzlatiladi |
| agents / agent_runs | kodda + `tasks` | `agent_runs` uchun `tasks` yetarli; token/vaqt ustunlari qo'shiladi |
| providers / models / provider_credentials | `settings.ai_providers`, `ai_models`, `ai_provider_checks`; kalitlar — Credential Manager | kalitlar bazada bo'lmasligi to'g'ri |
| tool_registry | — | **yangi** |
| connector_instances | `integrations`, `sync_runs`, `sync_state`, `ext_records`, `vault_index` | mavjud |
| permissions / approval_requests | `approvals` (+policy kodda) | `approval_grants` (muddatli, agent/loyiha doirasida) **yangi** |
| execution_logs / audit_events | `mission_log`, `audit_log`, `errors` | mavjud |
| memories / memory_sources | `memories` (+source, reference, confidence), `memories_fts`, `memory_import_items` | vektor uchun `memory_vectors` **yangi** |
| knowledge_nodes / edges | `kg_nodes`, `kg_edges` (indekslangan) | mavjud |
| files | — | **yangi** `file_index` (Asset Manager) |
| workflows / workflow_runs | — | **yangi** |
| skills | `plugins`, `plugin_logs` | versiya/rollback ustunlari |
| usage_records | `ai_usage`, `model_feedback` | mavjud |

Kamchiliklar: **foreign key'lar yo'q** (SQLite'da yoqilmagan), indekslar kam (5 ta), retention yo'q. Tavsiya: yangi jadvallarda FK + indeks; eski jadvallarga faqat indeks qo'shish (`missions(status)`, `dag_nodes(run_id,status)`, `ai_usage(ts)`, `audit_log(ts)`); `PRAGMA foreign_keys=ON` faqat yangi jadvallar uchun sinovdan keyin.

---

## 6. Architecture proposal — Safe Autonomous

**Tamoyil:** yangi tizim yozilmaydi — mavjud Mission Engine markaz bo'ladi, qolganlar unga "capability" sifatida ulanadi.

```
USER (chat / ovoz / Telegram / dashboard)
   │
CENTRAL BRAIN = Mission Engine
   Understanding → Planning → Risk analysis → Permission check → Execution → Verification → Result → Memory
   │            │                 │                    │
   │      Planner + DAG     Permission Manager    Tool Registry ──▶ capability'lar:
   │                        + Autonomy Level         AI Router · Files · Computer Use · Browser · Connectors · POS/BI ·
   │                        + Approval Engine        Creative · Research · Memory · Telegram/Instagram · Skills
   │
Guardian (health, xarajat, xavfsizlik, global stop)   ·   Proactive engine (kuzatish → taklif, hech qachon tashqi amal emas)
Memory Brain (provayderdan mustaqil) · Digital Twin (faqat tasdiqlangan ma'lumot) · Audit · Events → 3D Brain / Office
```

### 6.1 Autonomy Levels (markaziy, barcha agent va connectorlarga bir xil)
| Level | Xatti-harakat | A/B (LOW) | C (MEDIUM) | D (HIGH) | E (CRITICAL) |
|---|---|---|---|---|---|
| 0 | faqat maslahat | maslahat | — | — | — |
| 1 | reja + tasdiq | tasdiq | tasdiq | tasdiq | har safar aniq tasdiq |
| 2 | xavfsiz ishlarni o'zi | avtomatik | tasdiq | tasdiq | har safar aniq tasdiq |
| 3 | agentlarni boshqaradi | avtomatik | ruxsat berilgan papka/sandbox'da avtomatik | tasdiq | har safar aniq tasdiq |
| 4 | to'liq sikl + davom | avtomatik | sandbox'da avtomatik | **muddatli oldindan ruxsat** (masalan 1 soat, 1 agent, 1 loyiha) yoki tasdiq | har safar aniq tasdiq |

**Safe** siyosati = standart **Level 2**; Level 3–4 ni faqat foydalanuvchi dashboard'da yoqadi. JARVIS darajani o'zi ko'tara olmaydi. To'lov, o'chirish, pul o'tkazish, xavfsizlik sozlamasi — har qanday darajada har safar alohida tasdiq. Ruxsat boshqa agentga o'tmaydi va muddati tugaydi.

### 6.2 Tool Registry
Har tool: `id, name, description, input_schema, output_schema, risk(A–E), permissions, timeout, retry(idempotent?), handler, audit`. Mavjud agent handlerlari tool sifatida ro'yxatga olinadi (kod qayta yozilmaydi). Agent faqat o'z ro'yxatidagi tool'ni chaqiradi; har chaqiruv Permission Manager → Approval Engine orqali.

### 6.3 Agent Swarm
- Agent = profil (system prompt, router vazifa turi, tool ro'yxati, ruxsat chegarasi, xotira doirasi, limitlar: vaqt/token/xarajat/urinish, output schema, tekshiruv qoidasi).
- Agentlararo topshiriq = Mission'ga yangi sub-step qo'shish (DAG), to'g'ridan-to'g'ri cheksiz suhbat emas → token sarfi cheklangan.
- Supervisor = Verification Engine + ixtiyoriy AI tekshiruvi (faqat pullik byudjet doirasida).
- 40 ta so'ralgan agentning ko'pi **profil** (prompt + tool'lar) sifatida qo'shiladi; haqiqiy imkoniyati yo'qlari "faqat maslahat" deb belgilanadi.

### 6.4 Qolgan modullar qanday ulanadi
| Modul | Asos | Ulanishi |
|---|---|---|
| Proactive Intelligence | scheduler + missions + memory | kunlik/haftalik hisobot, tugallanmagan missiya/loyiha, xatolar → bildirishnoma (faqat ichki kanal; Telegram — mavjud egasi kanali) |
| Digital Twin | preference/decision/project xotira | faqat tasdiqlangan yozuvlardan profil; tahrirlash/o'chirish; takliflar Mission rejasi sifatida |
| Simulation Lab | sandbox + backup + integration proposals | SQLite nusxasida dry-run, before/after diff, rollback rejasi; production uchun ruxsat alohida |
| Asset Manager | files.py + memory | ruxsat berilgan papkalar indeksi, xesh bo'yicha dublikat, tasnif |
| Virtual AI Office | office bo'limi + mission_log | agent xonasi = agent profili + uning vazifalari + natijalari (3D ixtiyoriy) |
| Skills Factory | plugins.py | versiya, testlar, rollback; AI yaratgan skill → sandbox test → tasdiq → yoqish |
| Guardian | health_watch + diagnostics + guard | xarajat anomaliyasi, xavfsiz tiklash ro'yxati (masalan Ollama qayta ulanishi), global stop |
| Workflow Studio | DAG + scheduler + webhook | Trigger → Condition → Agent/Tool → Approval → Verification; saqlash, tarix |
| Multi-device | auth + PIN | qurilmalar ro'yxati, sessiyalar, TLS; telefon — brauzer orqali |

### 6.5 8 GB RAM qoidalari
Bitta jarayon; og'ir modullar lazy import (Playwright, Whisper, embedding); mahalliy model bittadan (`HEAVY` agentlar navbatda); Ollama `keep_alive` qisqa; DAG parallelligi RAM bo'yicha (mavjud); fayllar bo'laklab; vektorlash fon navbatida.

---

## 7. Implementation roadmap (taklif)

Prinsip: har bosqich — audit → reja → kod → migratsiya → test (unit + API + brauzer + failure) → hujjat → push → CI. Real tashqi tizimlar mock bilan testlanadi va hisobotda "real sinalmagan" deb yoziladi.

| Bosqich | Kontent | Bog'liqlik | Windows'da real test kerakmi |
|---|---|---|---|
| **A. Xavfsizlik tuzatishlari** | S1 global stop → missiyalar; S4 muddatli tasdiqlar; indekslar; retention siyosati (tasdiq bilan) | — | yo'q |
| **B. Autonomy Levels + Tool Registry** | level sozlamasi (Safe = 2), muddatli grantlar, tool katalogi, agent limitlari | A | yo'q |
| **C. Agent Swarm** | agent profillari (40 rol), agentlararo sub-step, Supervisor | B | yo'q |
| **D. Projects + Proactive + Digital Twin** | `projects`, kuzatuv, kunlik/haftalik hisobot, tasdiqlangan profil | C | yo'q |
| **E. Memory Brain** | mahalliy embedding (ixtiyoriy), vektor qidiruv, konsolidatsiya, eksport | D | qisman (RAM) |
| **F. File Intelligence + Asset Manager** | DOCX/PPTX/OCR/arxiv, nusxada tahrir, indeks, dublikat | E | qisman (OCR) |
| **G. Simulation Lab** | DB nusxa dry-run, before/after, rollback | B | yo'q |
| **H. Workflow Studio** | vizual builder, triggerlar | B, G | yo'q |
| **I. Computer Use** | UI Automation, input, skrinshot + vision, yozib olish/ijro | B | **ha** |
| **J. Creative Factory + Business** | bulut rasm/video adapterlari, prognoz/anomaliya | B | yo'q (kalitlar kerak) |
| **K. Skills Factory v2** | versiya, testlar, rollback, AI yaratgan skill | B, G | yo'q |
| **L. Guardian v2 + Multi-device** | xarajat anomaliyasi, xavfsiz tiklash, TLS, qurilmalar | A | **ha** |
| **M. Dashboard qayta tartib + dark neon** | 23 menyu tartibi, responsive | hammasi | yo'q |
| **N. Xavfsizlik auditi + Windows optimizatsiya** | penetration checklist, RAM profil | hammasi | **ha** |

Taklif etiladigan birinchi qadam: **A + B** (bitta reliz) — xavfsiz avtonomiyaning poydevori; keyin C.

### Sizdan kerakli qarorlar
1. Roadmap tartibini tasdiqlaysizmi (A+B'dan boshlash)?
2. Safe siyosati uchun standart daraja **Level 2** ma'qulmi?
3. Level 4 dagi "muddatli oldindan ruxsat" (HIGH amallar uchun) kerakmi yoki HIGH har doim tasdiq bo'lib qolsinmi?
4. Eski `plans` (Planner) API'sini muzlatib, faqat Mission Engine'ni rivojlantirishga rozimisiz?
