# Super Brain + Universal Connection Center (v0.8)

Bu hujjat nima **haqiqatan ishlaydi**, nima **faqat mock (sun'iy server) bilan sinalgan** va nima **sizdan kirish ma'lumotlarini kutadi** — shularni halol ko'rsatadi.

## Arxitektura
```
Foydalanuvchi (chat / ovoz / Telegram)
  → Brain Core (brain_core.py): tushunish → xotira → vosita → ruxsat → bajarish → tekshirish → javob (har qadam trace)
      ├─ Model Router (router.py): vazifa turi → model (Claude / Groq / Gemini / Ollama), maxfiy matn → faqat mahalliy
      ├─ POS tahlilchisi (integrations/analyst.py): savdo, top/kam sotilgan, foyda, qoldiq, qarz, do'konlar taqqosi
      ├─ Integration Hub (integrations/__init__.py): ulanishlar, discovery, mapping, sync, monitor
      ├─ Xotira (SQLite + FTS5) va Knowledge Graph — "o'rganish" shu yerda (model qayta o'qitilmaydi)
      └─ Approval Engine (A–E): tashqi tizimga yozish faqat tasdiq bilan; pul/narx/o'chirish → E (faqat dashboard)
```
Dashboard: **⚡ Super Brain Control** va **🔌 Universal Connection Center**.

## Ulanish adapterlari
| Adapter | Nima qiladi | Sinov holati |
|---|---|---|
| REST (OpenAPI) | auth: API key / Bearer / Basic / OAuth2 client credentials; OpenAPI'dan obyektlarni topish; sahifalash; incremental | mock server bilan sinalgan |
| OData (1C) | `$metadata` dan EntitySet'lar, `$top/$skip` | mock bilan |
| GraphQL | introspection, query | mock bilan |
| MCP | `tools/list`, o'qish vositalari | mock bilan |
| Veb-sayt (Playwright) | login, jadvallarni o'qish, sessiya shifrlangan; CAPTCHA/MFA → "siz kirishingiz kerak" (chetlab o'tmaydi) | lokal test sayti bilan |
| Ma'lumotlar bazasi | faqat SELECT; SQLite `mode=ro`; PostgreSQL/MySQL/MSSQL/Mongo — drayver o'rnatilsa | SQLite real, qolganlari drayversiz sinalmagan |
| Fayllar | CSV/XLSX/JSON/XML, faqat ruxsat berilgan papkadan | real |
| Kompyuter dasturlari | o'rnatilgan dasturlar, jarayonlar, portlar (faqat o'qish). UI Automation yo'q | real (Windows'da to'liq) |

## POS andozalari — halol holat
| Tizim | Usul | Real ulanish |
|---|---|---|
| YesPOS | veb-panel (ommaviy API topilmadi) yoki Excel eksport | **sinalmagan** — hisob kerak |
| BITO | veb-panel yoki REST (hujjat bo'lsa) | **sinalmagan** |
| 1C | OData (administrator e'lon qilishi kerak) | **sinalmagan** |
| Info-Enterprise | MS SQL read-only foydalanuvchi (pyodbc) | **sinalmagan** |
| CloudShop | REST + token | **sinalmagan** |

Hech bir POS'ga bulut muhitidan real ulanish qilinmagan — hisob va loginlar yo'q. Testlardagi "POS" — sun'iy serverlar. Real ulanish faqat sizning kompyuteringizda "Tekshirish" muvaffaqiyatli bo'lganda tasdiqlanadi.

## Kirish ma'lumotlari
- Vault: OS keyring (Windows Credential Manager) + Fernet bilan shifrlangan fayllar (`JARVIS_HOME/vault`). Qiymatlar API orqali qaytmaydi, loglarda maskalanadi, AI promptlariga qo'shilmaydi.
- Parollarni chat, Telegram yoki ovoz orqali yubormang — faqat dashboard formasi.

## Ruxsat rejimlari
`read_only` (standart) · `assistant` — faqat qoralama · `authorized` — har yozuv tasdiq so'rovi (D), moliyaviy/o'chirish — E. JARVIS rejimni o'zi o'zgartira olmaydi.

## AI modellar
Super Brain Control → **Model qo'shish** (Claude, Groq, Gemini) → API kalit. Bulut modellar pullik hisoblanadi va **Sozlamalar → Pullik AI'ga ruxsat** yoqilmaguncha ishlamaydi. "Vazifa → model" jadvali (`ai_task_routes`) har vazifaga model tanlaydi; maxfiy/shaxsiy matn baribir mahalliy modelga ketadi.

## O'zbekcha ovoz
- TTS: Azure Neural `uz-UZ-MadinaNeural` / `uz-UZ-SardorNeural` (kalit + mintaqa kerak, bepul F0 daraja bor) → bo'lmasa espeak-ng → brauzer.
- STT: Azure Speech (uz-UZ) → Whisper (POS mahsulot nomlari lug'at sifatida beriladi) → brauzer.
- Suhbat rejimi: VAD (sukunatdan gap tugashini aniqlash), gapma-gap javob, barge-in. Raqamlar o'zbekcha so'z bilan o'qiladi.
- Ovozli "ha" xavfli amalni tasdiqlamaydi — faqat tugma.
- Azure kaliti bilan real sinov bulutda qilinmagan (kalit yo'q); mantiq mock bilan sinalgan.
