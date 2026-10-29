# Arxitektura

```
dashboard/ (index.html, modules.js, app.js)  ──HTTP──>  jarvis/api.py (FastAPI, 127.0.0.1)
                                                             │
                                                      jarvis/core.py (JARVIS Core)
  ┌───────────┬────────────┬────────────┬──────────────┬─────┴──────┬────────────┬────────────┐
intent.py  ai_engine.py  memory.py   planner.py     agents.py   approval.py   audit.py   notify.py
(o'zbekcha (Offline/     (SQLite +   (maqsad →      (15 agent,   (A–E, xesh,  (redaksiya) (dashboard +
 NLU)       Ollama)       FTS5)       bosqichlar)    navbat)      idempotency)              Telegram)
                                                        │
   ┌──────────┬──────────┬──────────┬───────────┬───────┴─────┬──────────┬────────────┬────────────┐
files.py  computer.py  bi.py     pos.py     research.py   browser.py  studio.py  instagram.py  telegram_bot.py
                                                                                   voice.py  telephony.py  improve.py
   security.py (redact, injection, buyruq xavfi, yo'l doirasi)   secrets.py (Credential Manager)
   net.py (HTTP, testlarda almashtiriladi)   db.py (SQLite adapteri)   system_info.py   selfcheck.py
```

## Modullar

| # | Modul | Fayl | Holat |
|---|---|---|---|
| 1 | JARVIS Core | core.py | ✅ |
| 2 | AI Engine | ai_engine.py | ✅ offline, ⚠️ Ollama (real sinalmagan) |
| 3 | Memory Engine | memory.py, db.py | ✅ |
| 4 | Planner | planner.py | ✅ qoidaga asoslangan bo'lish |
| 5 | Agent Manager | agents.py | ✅ 15 agent |
| 6 | Computer Agent | computer.py | ✅ |
| 7 | Browser Agent | browser.py | ✅ faqat o'qish |
| 8 | File Intelligence | files.py | ✅ |
| 9 | Voice Engine | voice.py + dashboard | ⚠️ brauzer STT/TTS, Whisper ixtiyoriy |
| 10 | Image & Video Studio | studio.py | ✅ (AI generatsiya yo'q) |
| 11 | Instagram Manager | instagram.py | ⚠️ Graph API (real sinalmagan) |
| 12 | Telegram Assistant | telegram_bot.py | ⚠️ Bot API (real sinalmagan) |
| 13 | Business Intelligence | bi.py | ✅ |
| 14 | POS Connector | pos.py | ✅ file_export; ⏳ api/browser |
| 15 | Approval Engine | approval.py | ✅ |
| 16 | Security Engine | security.py, secrets.py | ✅ |
| 17 | Audit Engine | audit.py | ✅ |
| 18 | Self-Improvement | improve.py, selfcheck.py | ✅ |
| 19 | Dashboard | dashboard/ | ✅ 23 bo'lim |
| 20 | Monitoring & Notifications | notify.py, telephony.py | ✅ dashboard/Telegram, ⏳ qo'ng'iroq |

## v0.3 boshqaruv qatlami

| Modul | Fayl | Vazifa |
|---|---|---|
| Policy Engine | policy.py | Har bir amal: low/medium/high/forbidden → tasdiq darajasi (ApprovalEngine ichida majburiy) |
| AI Router | router.py | Murakkablik/maxfiylik/narx/mavjudlik bo'yicha model tanlash, fallback; `core.ai` |
| Resource Guard | resource_guard.py | ai_usage jadvali, limitlar, ogohlantirishlar, resurs o'lchovlari |
| Provenance | memory.py | info_type, verified, reference, observed_at, eskirish, solishtirish |
| Decision Journal | decisions.py | decisions + decision_events (o'zgarmas tarix) |
| Sandbox | sandbox.py | Kod/buyruqni cheklangan muhitda ishga tushirish, sandbox_runs |
| Backup | backup.py | Zip + manifest, verify, restore, retention, avto-jadval |
| Task Graph | dag.py | dag_runs, dag_nodes; parallel va bog'liqliklar |
| Knowledge Graph | kgraph.py | kg_nodes, kg_edges; avtomatik ilgaklar |
| Plugins | plugins.py, plugins/ | Manifest, ishonch, ruxsatlar, sandbox'da ijro |
| Diagnostics | diagnostics.py | Komponentlar holati, so'rov vaqtlari middleware'i, eksport |
| Release Gate | scripts/release_gate.py | lint + JS + toifalangan pytest → PASS/FAIL/INCOMPLETE |

## Ma'lumotlar bazasi (SQLite, `JARVIS_HOME/jarvis.db`)

`memories`(+FTS5), `conversations`, `audit_log`, `errors`, `approvals`, `tasks`, `plans`, `notifications`,
`bi_imports`, `bi_products`, `bi_movements`, `bi_payments`, `pos_documents`, `ig_posts`, `ig_replies`, `proposals`,
`ai_usage`, `guard_alerts`, `decisions`, `decision_events`, `sandbox_runs`, `dag_runs`, `dag_nodes`, `kg_nodes`, `kg_edges`,
`plugins`, `plugin_logs`. Migratsiya: `Database.ensure_columns()` — mavjud ma'lumot yo'qolmaydi.

## Fayllar (`JARVIS_HOME/workspace/` — yagona ruxsat berilgan papka)

`imports/` (BI yuklamalari), `exports/` (studiya natijalari), `screenshots/`, `voice/` (faqat yoqilganda).
`JARVIS_HOME/pos_outbox/` — tasdiqlangan POS hujjatlari (JSON + CSV).

## Tashqi amal oqimi (POS, Instagram, kod o'zgarishi, qo'ng'iroq)

```
loyiha (B) → approvals.request(level D/C, payload, idempotency_key)
          → foydalanuvchi dashboardda payload_hash bilan tasdiqlaydi
          → authorize_execution(joriy payload)  — xesh mos kelmasa: invalidated
          → mavjudligini tekshirish (takroriy emasmi) → bajarish
          → mark_result(executed | unknown) → tekshirish → audit
```

## Ish rejimlari

- **Cloud Development** — shu repozitoriy, CI (Ubuntu + Windows).
- **Local Runtime** — Windows 11, `scripts/setup_windows.ps1`; xotira faqat lokal.
- **Cloud Deployment** — rejalashtirilmagan; avval autentifikatsiya, HTTPS, zaxira va narx muhokama qilinadi.
