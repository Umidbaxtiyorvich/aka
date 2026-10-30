# Takomillashtirishlar: mavjud kod tahlili va reja (v0.3)

| # | Talab | Avvaldan mavjud | Yetishmagani (qo'shiladi) |
|---|---|---|---|
| 1 | Adaptive AI Router | `ai_engine.py`: offline + bitta Ollama modeli | `router.py`: provayderlar ro'yxati (light/strong, lokal/pullik), murakkablik va maxfiylik bo'yicha tanlash, fallback, metrikalar, modelni foydalanuvchiga ko'rsatish |
| 2 | Knowledge Provenance | `memories`: source, confidence, created_at, conflict holati | Ma'lumot turi (fakt/taxmin/model xulosasi/foydalanuvchi), tekshirilgan holat, havola, manba sanasi, eskirish, manbalarni solishtirish |
| 3 | Sandbox | `improve.py` worktree + pytest; `computer.py` buyruq + tasdiq | `sandbox.py`: statik tekshiruv, cheklangan muhit, vaqt/xotira/qayta urinish limiti, natijalarni saqlash, buyruqlar allowlist'i; ixtiyoriy Docker; cheklovlar halol hujjatlashtiriladi |
| 4 | Resource & Cost Guard | `system_info.py` (RAM/CPU/disk lahzali) | `resource_guard.py`: so'rovlar, tokenlar (o'lchangan/taxminiy ajratilgan), xarajat, kunlik/oylik limit, ogohlantirish, pullikni to'xtatish |
| 5 | Backup & DR | `scripts/backup.py` (oddiy nusxa) | `backup.py`: manifest + SHA-256, integrity_check, sinov-tiklash, retention, tarix, avtomatik jadval, E-darajali tiklash |
| 6 | Task Dependency Graph | `planner.py` (ketma-ket) | `dag.py`: bog'liqliklar, sikl tekshiruvi, xavfsiz parallel, takrorni qayta ishlatish, xato tarqalishi, bekor qilish, vizual |
| 7 | Decision Journal | yo'q (audit faqat amallarni yozadi) | `decisions.py`: qarorlar + o'zgarmas tahrir tarixi + qayta ko'rib chiqish |
| 8 | Knowledge Graph | yo'q | `kgraph.py`: SQLite tugun/qirra jadvallari, avtomatik bog'lash, qidiruv, yo'l topish |
| 9 | Plugins | yo'q | `plugins.py` + `plugins/`: manifest, hash bo'yicha ishonch, minimal ruxsatlar, sandbox'da ishga tushirish |
| 10 | Policy Engine | `approval.py` A–E darajalar, `security.classify_command` | `policy.py`: markaziy low/medium/high/forbidden, minimal daraja majburiy, ta'sir/maqsad/qaytarish ko'rsatiladi |
| 11 | Observability | `selfcheck.health`, `/api/status` | `diagnostics.py`: javob vaqti middleware, xato toifalari, tashqi xizmat "tekshirib bo'lmadi" holati, eksport |
| 12 | Release Gate | CI: ruff + pytest | `scripts/release_gate.py`: toifalangan testlar, frontend e2e, PASS/FAIL/INCOMPLETE; CI'ga ulash |

Mavjud API va dashboard bo'limlari saqlanadi; yangi jadvallar mavjud bazaga migratsiya bilan qo'shiladi.

## Natija (v0.3.0)

Barcha 12 band amalga oshirildi. Fayllar: `router.py`, `resource_guard.py`, `policy.py`, `memory.py` (provenance), `decisions.py`,
`sandbox.py`, `backup.py`, `dag.py`, `kgraph.py`, `plugins.py` + `plugins/`, `diagnostics.py`, `scripts/release_gate.py`,
`dashboard/advanced.js`, `tests/frontend/`. Mavjud API va bo'limlar o'zgarmadi; yangi jadvallar migratsiya bilan qo'shildi.

Halol cheklovlar:
* Sandbox `process` backend — OS darajasidagi izolyatsiya emas (batafsil: docs/SECURITY.md → Sandbox).
* Xarajat = token × siz kiritgan narx; provayder hisob-fakturasi emas.
* Tashqi AI/Telegram/Instagram real xizmat bilan bulut muhitida sinalmagan (tarmoq yopiq) — mock testlar bor.


## v0.6 — "Final Advanced Upgrade" auditi
Promptdagi 12 band mavjud kod bilan solishtirildi. To'liq mavjud bo'lganlar qayta yaratilmadi:
- sandbox;
- backup va recovery;
- task dependency graph (DAG);
- qarorlar jurnali;
- kengaytmalar (plugins);
- Policy Engine;
- asosiy diagnostika.

Faqat yetishmagan qismlar qo'shildi:

| Band | Nima qo'shildi | Fayllar |
|---|---|---|
| 1. Router 2.0 | Foydalanuvchi fikri (chatda 👍/👎) va o'rnatilgan testlar (`evaluate`) asosida model sifati bahosi. Kamida 5 baho bo'lsa, bir xil darajadagi modellardan yaxshirog'i birinchi tanlanadi. Past baho javob izohida ko'rsatiladi. Pullik model testi Cost Guard limitidan o'tadi. | `router.py`, `resource_guard.py` (`model_feedback`), `app.js`, `advanced.js` |
| 2. Knowledge Graph 2.0 | Har tugunda manba, olingan vaqt va tekshirilganlik holati. Test natijalari tugunlari (`test_run`), `tested_by` va `covers` aloqalari. Tugundan tegishli dashboard bo'limiga o'tish. | `kgraph.py`, `improve.py`, `advanced.js` |
| 3. Self-healing | Diagnostika va xatolarni imzo bo'yicha guruhlash. Takrorlanuvchi xatolar (≥3) aniqlanadi. Testlar alohida git worktree'da ishga tushadi. AI tuzatish taklifi regressiya testi bilan beriladi; kvota: kuniga 3 ta, bitta xato imzosiga 24 soatda 1 ta. Git holati va qaytarish rejalari ko'rsatiladi. Taklif ichida test yo'q bo'lsa, merge tasdig'ida ogohlantirish chiqadi. Har 6 soatda yengil tekshiruv o'tkaziladi. Hech narsa avtomatik qo'llanmaydi. | `selfheal.py`, `improve.py`, `core.py`, `app.js` |
| 5. Resource Guard | Qayta urinishlar va xatolar statistikasi (bugun): AI provayderlari, fallbacklar, modul xatolari, vazifa xatolari. Ma'lumot "real vaqt emas" deb belgilangan. | `resource_guard.py` |
| 12. Release gate | `diff_review` tekshiruvi. Diffda maxfiy fayl (`.env`, `*.pem`, `data/settings.json`) yoki haqiqiy kalit naqshi (sk-, ghp_, AKIA, Telegram bot tokeni, private key va h.k.) bo'lsa — FAIL. Kod o'zgarib, testlar o'zgarmagan bo'lsa — ogohlantirish. CI diff uchun oldingi commitni ham yuklaydi. | `scripts/release_gate.py`, CI |
