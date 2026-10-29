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
