# Xavfsizlik

## Asosiy qoidalar
- Server faqat `127.0.0.1` da (tarmoqqa ochilmaydi). Autentifikatsiya hali yo'q — shuning uchun serverga tashqaridan kirish berilmasin.
- **Faqat o'qish rejimi** standart holatda yoqilgan: A darajadan yuqori buyruqlar tasdiqlansa ham bajarilmaydi.
- Yozish va o'qish faqat `allowed_read_dirs` / `allowed_write_dirs` ichida (standart: `data/workspace`).
- `read_only_mode`, `require_approval`, `allowed_*_dirs` — **qulflangan**: API, dashboard yoki JARVIS ularni o'zgartira olmaydi. Faqat siz `data/settings.json` ni qo'lda tahrirlaysiz.

## Tasdiqlash darajalari
| Daraja | Amal | Tasdiq |
|---|---|---|
| A | O'qish, tahlil | avtomatik |
| B | Mahalliy draft | avtomatik, natija ko'rsatiladi |
| C | Fayl/sozlama o'zgarishi, noma'lum buyruq | aniq tasdiq |
| D | Tashqi tizimga kiritish, xabar, post, moliyaviy amal | har bir amal uchun alohida |
| E | O'chirish, qaytarib bo'lmaydigan | ogohlantirish + aniq tasdiq |

Tasdiq umumiy "ha" emas: dashboard payload'ning SHA-256 xeshini yuboradi. Xesh amal turi, tizim/sayt, akkaunt va
butun payload (hujjat versiyasi, mahsulotlar, miqdorlar, narx, summa) dan hisoblanadi. Bajarishdan oldin payload
qayta xeshlanadi — farq bo'lsa tasdiq `invalidated`. `executed` holatdagi amal qayta bajarilmaydi;
`unknown` holatda avval tashqi tizim tekshirilishi kerak. `idempotency_key` takroriy so'rovni oldini oladi.

Zanjirlangan buyruqlar (`;`, `&`, `|`, `$(...)`) eng xavfli qismi bo'yicha baholanadi va kamida C bo'ladi.

## Maxfiy ma'lumotlar
- Parol, token, API kalit chatga yozilsa — saqlanmaydi, yashiriladi, foydalanuvchi ogohlantiriladi.
- Xotira va tasdiq payload'iga maxfiy ma'lumot qo'yib bo'lmaydi; audit va xatolar jurnalida avtomatik `[MAXFIY-YASHIRILDI]`.
- Kalitlarni kiritish: `python scripts/set_secret.py telegram_bot_token` → Windows Credential Manager. Kodda, `.env`, SQLite yoki Git'da saqlanmaydi.
- `.gitignore`: `data/`, `logs/`, `.env`, `config/settings.json`.
- POS logini/paroli chat orqali **so'ralmaydi**. Ulanish usullari (xavfsizlik tartibida): rasmiy API + cheklangan token → Credential Manager → siz o'zingiz kirgan brauzer sessiyasi.

## Integratsiyalar xavfsizligi
- **Telegram**: faqat `telegram_allowed_ids` (qulflangan, faqat settings.json) dan buyruq; begonalarga javob yo'q, urinish audit + ogohlantirish. Tasdiqlash Telegram orqali emas — faqat dashboardda.
- **Instagram**: faqat rasmiy Graph API; har bir post/javob — D daraja, aniq akkaunt va matn bilan. Login/parol yoki himoyani chetlab o'tish yo'q.
- **POS**: faqat o'qish rejimida tashqi konnektorlar (api/browser) yozolmaydi; `file_export` faqat lokal faylga yozadi. Natija noma'lum bo'lsa — qayta yuborilmaydi, avval tekshiriladi.
- **Internet**: standart holatda o'chiq; lokal/ichki tarmoq manzillari bloklanadi (SSRF); sahifa matni ishonchsiz.
- **Brauzer**: faqat ruxsat berilgan domenlar, faqat o'qish; parol kiritmaydi, CAPTCHA/2FA chetlab o'tilmaydi.
- **Ovoz**: mikrofon faqat tugma bilan, holati qizil belgi bilan ko'rinadi; yozuv saqlash alohida sozlama.
- **Telefon**: provayder sozlanmaguncha o'chiq; har bir qo'ng'iroq raqam, matn va taxminiy narx bilan D-darajali tasdiq.
- **Self-improvement**: `protected_paths` (security.py, approval.py, config.py, secrets.py, improve.py), `.github/` va testlarni o'chirish taqiqlangan; patch faqat alohida branch'ga.

## Tashqi matn (prompt injection)
Internet sahifalari va fayllardagi matn `wrap_untrusted()` bilan "ma'lumot, buyruq emas" deb belgilanadi va
shubhali ko'rsatmalar aniqlanadi. Bunday matn xavfsizlik sozlamalarini o'zgartira olmaydi — sozlamalar kod darajasida qulflangan.

## Self-improvement chegarasi
JARVIS testlarni ishga tushirib, hisobot beradi. U kodni o'zi o'zgartirmaydi; kelajakdagi patchlar alohida branch'da
taklif qilinadi va faqat sizning tasdig'ingiz bilan birlashtiriladi. Rollback — Git orqali.

## Policy Engine (v0.3)
- Har bir tasdiq so'rovi `policy.py` orqali o'tadi. Kod past daraja so'rasa ham, siyosatdagi minimal daraja qo'llanadi.
- **forbidden** amallar tasdiq bilan ham bajarilmaydi:
  - CAPTCHA yoki login chetlab o'tish;
  - kalitni tashqariga yuborish;
  - tasdiqni o'chirish;
  - xavfli tizim buyruqlari: `format`, `diskpart`, `bcdedit`, `reg delete HKLM` va boshqalar;
  - `command_allowlist` da yo'q buyruq. Zanjirdagi har bir qism alohida tekshiriladi.
- **medium** amallarni avtomatik qilishni faqat siz yoqasiz (`medium_auto_actions`). **high** amallar hech qachon avtomatik emas.
- `command_allowlist` va `forbidden_actions` qulflangan: ularni faqat `settings.json` orqali o'zgartirish mumkin.

## Sandbox — halol cheklov
- `process` backend (standart) quyidagilarni qiladi:
  - statik AST tekshiruvi;
  - alohida vaqtinchalik papka;
  - token va kalitlarsiz muhit (`python -I`);
  - audit-hook: papkadan tashqariga yozish, subprocess, ctypes va ruxsatsiz tarmoqni bloklaydi;
  - vaqt va xotira limiti.
- Bu **OS darajasidagi izolyatsiya emas**. Maxsus yozilgan zararli kod (C-kengaytma, interpreter zaifligi) uni chetlab o'tishi mumkin.
- Windows'da CPU vaqti limiti yo'q, xotira esa monitoring orqali nazorat qilinadi.
- Shell buyruqlarida tarmoqni bloklab bo'lmaydi.
- Ishonchsiz kod uchun `sandbox_backend: "docker"` ishlating:
  - `--network none`, read-only konteyner, memory va pids limiti.
  - Docker o'rnatilgan bo'lishi kerak. Muqobili — Windows Sandbox yoki VM.
- Claude Code bulut muhiti JARVIS uchun izolyatsiya **emas**. U faqat ishlab chiqish muhiti.

## AI Router va xarajat
- Maxfiy ma'lumot (parol, karta, pasport, telefon) faqat mahalliy modelga yuboriladi. Mahalliy model bo'lmasa, tashqi modelga yuborilmaydi.
- Pullik AI standart holatda o'chiq. U faqat siz yoqqanda va kunlik/oylik limit belgilanganda ishlaydi.
- Limit tugasa, pullik so'rovlar to'xtaydi.
- Model almashtirilsa, bu javobda ko'rsatiladi.

## Kengaytmalar
- Kengaytma faqat aniq versiya, fayl xeshi va ruxsatlar bilan tasdiqlangandan keyin yoqiladi.
- Fayl o'zgarsa, kengaytma `untrusted` holatiga o'tadi.
- Kod sandbox'da ishlaydi va faqat berilgan ruxsatlar doirasidagi amallarni bajara oladi.

## Zaxira nusxalar
- Maxfiy kalitlar nusxaga kirmaydi.
- Tiklash E darajali tasdiq talab qiladi va undan oldin xavfsizlik nusxasi olinadi. Batafsil: docs/BACKUP.md.
