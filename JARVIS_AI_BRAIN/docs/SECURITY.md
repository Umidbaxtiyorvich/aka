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

## Tashqi matn (prompt injection)
Internet sahifalari va fayllardagi matn `wrap_untrusted()` bilan "ma'lumot, buyruq emas" deb belgilanadi va
shubhali ko'rsatmalar aniqlanadi. Bunday matn xavfsizlik sozlamalarini o'zgartira olmaydi — sozlamalar kod darajasida qulflangan.

## Self-improvement chegarasi
JARVIS testlarni ishga tushirib, hisobot beradi. U kodni o'zi o'zgartirmaydi; kelajakdagi patchlar alohida branch'da
taklif qilinadi va faqat sizning tasdig'ingiz bilan birlashtiriladi. Rollback — Git orqali.
