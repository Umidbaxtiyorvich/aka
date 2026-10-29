# Arxitektura

```
dashboard/ (HTML/CSS/JS)  ──HTTP──>  jarvis/api.py (FastAPI, 127.0.0.1)
                                          │
                                   jarvis/core.py  (JARVIS Core: chat routing)
     ┌──────────────┬──────────────┬──────┴───────┬───────────────┬──────────────┐
 intent.py     ai_engine.py     memory.py     agents.py       approval.py     files.py
 (o'zbekcha    (Offline/Ollama  (SQLite+FTS5) (Agent Manager, (A–E, xesh,     (File
  NLU)          adapterlari)                   navbat)         idempotency)    Intelligence)
                                                  │                 │
                                             computer.py ───────────┘
                    security.py (redact, injection, buyruq xavfi, yo'l doirasi)
                    audit.py (audit_log, errors)   db.py (SQLite adapteri)
                    secrets.py (Windows Credential Manager / keyring)
                    selfcheck.py (health + pytest)   system_info.py (diagnostika)
```

## Modullar va holati

| # | Modul | Fayl | Holat |
|---|---|---|---|
| 1 | JARVIS Core | core.py | ✅ |
| 2 | AI Engine | ai_engine.py | ✅ offline, ⚠️ Ollama adapteri |
| 3 | Memory Engine | memory.py, db.py | ✅ |
| 4 | Planner | core.py (vazifa xotirasi) + agents.py (navbat) | ⚠️ oddiy |
| 5 | Agent Manager | agents.py | ✅ |
| 6 | Computer Agent | computer.py | ✅ (faqat o'qish rejimi) |
| 7 | Browser Agent | — | ⏳ |
| 8 | File Intelligence | files.py | ✅ |
| 9 | Voice Engine | — | ⏳ |
| 10 | Image & Video Studio | — | ⏳ |
| 11 | Instagram Manager | — | ⏳ |
| 12 | Telegram Assistant | — | ⏳ |
| 13 | Business Intelligence | — | ⏳ |
| 14 | POS Connector | — (approval.py tayyor) | ⏳ |
| 15 | Approval Engine | approval.py | ✅ |
| 16 | Security Engine | security.py, secrets.py | ✅ |
| 17 | Audit Engine | audit.py | ✅ |
| 18 | Self-Improvement | selfcheck.py | ⚠️ tekshiradi, patch yaratmaydi |
| 19 | Dashboard | dashboard/ | ✅ |
| 20 | Monitoring & Notifications | dashboard (ichki) | ⚠️ Telegram bilan kengayadi |

## Ma'lumotlar bazasi (SQLite)

`memories` (+FTS5 indeks), `conversations`, `audit_log`, `approvals`, `tasks`, `errors`.
Boshqa BD'ga o'tish uchun `db.Database` interfeysi (`execute`, `query`, `one`) almashtiriladi.

## Agentlar navbati

Bitta fon ishchi oqimi vazifalarni ketma-ket bajaradi — 8 GB RAMda bir nechta model bir vaqtda yuklanmaydi.
Har bir vazifa `tasks` jadvalida: `queued → running → done | failed | waiting_approval`.

## Kengaytirish

Yangi agent: `agents.py` dagi `_register()` ga handler qo'shiladi. Tashqi tizimga yozadigan har qanday agent
`approvals.request(level="D", ...)` → foydalanuvchi qarori → `authorize_execution(payload)` → bajarish →
`mark_result("executed" | "unknown")` oqimidan o'tishi shart.
