# Integratsiyalarni sozlash

Hech qaysi integratsiya majburiy emas. Maxfiy kalitlar faqat Windows Credential Manager'ga kiritiladi:

```powershell
.\.venv\Scripts\python.exe scripts\set_secret.py <kalit_nomi>
```

Qiymat ekranda ko'rinmaydi va Git, SQLite yoki loglarga tushmaydi. Xavfsizlik bilan bog'liq sozlamalar faqat `data\settings.json` faylini qo'lda tahrirlab o'zgartiriladi. Bular: `telegram_allowed_ids`, papkalar ro'yxati va `read_only_mode`.

## Mahalliy AI — Ollama
1. Avval `scripts\check_system.ps1` ni ishga tushiring. GPU va VRAM shu yerda aniqlanadi.
2. https://ollama.com dan Ollama'ni o'rnating.
3. 8 GB RAM uchun boshlang'ich model: `ollama pull qwen2.5:1.5b` (~1 GB disk).
4. Dashboard → Sozlamalar → Provider: `ollama` → Saqlash. Holat darhol tekshiriladi.
- VRAM 6 GB va undan ko'p bo'lsa: `qwen2.5:7b`, ~4.7 GB. RAM'ni ko'p band qiladi.

## Telegram
1. @BotFather → `/newbot` → tokenni oling.
2. Tokenni kiriting: `python scripts\set_secret.py telegram_bot_token`
3. O'z ID'ingizni @userinfobot orqali bilib oling.
4. `data\settings.json` ga yozing: `"telegram_allowed_ids": [123456789]`
5. JARVIS'ni qayta ishga tushiring → Telegram bo'limi → "Ishga tushirish" → "Test xabar".
- Muhim xatolar va ogohlantirishlar Telegram'ga avtomatik keladi. Buni Sozlamalarda o'chirish mumkin.

## Instagram (Meta rasmiy API)
Talablar:
- Professional akkaunt (Business yoki Creator), Facebook sahifaga ulangan.
- developers.facebook.com da yaratilgan Meta App.
- Ruxsatlar: `instagram_basic`, `instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_insights`.

Sozlash:
1. Long-lived access token oling.
2. `data\settings.json` ga yozing: `"instagram_accounts": [{"name": "shop", "ig_user_id": "1784..."}]`
3. Tokenni kiriting: `python scripts\set_secret.py instagram_token_shop`

Cheklovlar:
- Nashr uchun rasm yoki video ommaviy `https://` URL'da bo'lishi kerak.
- Direct xabarlar uchun Instagram Messaging API va App Review kerak. Hozircha JARVIS faqat izohlarga javob loyihasini tayyorlaydi.
- Token muddati tugasa, bildirishnoma keladi.

## POS
- **Hozir:** CSV yoki Excel eksport → Business Intelligence. POS hujjatlari tasdiqlangach `data\pos_outbox\` ga JSON va CSV qilib yoziladi. Ularni POS'ga qo'lda import qilasiz.
- **Keyingi bosqich:** POS manzilini Sozlamalar → POS sayti ga yozing va domenni brauzer ro'yxatiga qo'shing.
  - Brauzer agenti → "Sayt tuzilishi" saytni faqat o'qiydi.
  - Shu asosida ulanish rejasi tuziladi: rasmiy API bo'lsa — API, bo'lmasa — siz o'zingiz kirgan brauzer sessiyasi.
  - Parol chatda so'ralmaydi.

## Ovoz
- **Brauzer (standart):** Chrome yoki Edge kerak, `uz-UZ` tanib olish. Internet kerak, ovoz brauzer provayderiga yuboriladi.
- **Mahalliy Whisper:**
  - O'rnatish: `pip install faster-whisper`.
  - Dashboard → Voice → modelni tanlab yuklang. Hajmi: small ≈480 MB, medium ≈1.5 GB.
  - Internet talab qilmaydi.
- **TTS:** Windows'da o'zbekcha ovoz odatda yo'q. Bunda javob matn bilan ko'rsatiladi.
  - Sifatli o'zbekcha ovoz uchun tashqi pullik xizmat kerak bo'ladi. U faqat sizning roziligingiz bilan ulanadi.

## Video / rasm
- FFmpeg o'rnatish: `winget install Gyan.FFmpeg`.
- Pillow `requirements.txt` ichida bor.
- AI bilan rasm generatsiyasi:
  - Mahalliy Stable Diffusion: kamida 4–6 GB VRAM kerak.
  - Onlayn generator: odatda pullik.
  - Hozircha JARVIS generator uchun prompt tayyorlaydi.

## Brauzer agenti
```powershell
pip install playwright
python -m playwright install chromium   # ~150 MB
```
Keyin Sozlamalar → Brauzer domenlari ga kerakli saytlarni qo'shing.

## Telefon qo'ng'irog'i
Haqiqiy qo'ng'iroq uchun SIP yoki telephony provayder kerak. Bu pullik: daqiqa uchun to'lov va raqam ijarasi.
- Hozir faqat rejalashtirish va tasdiq so'rovi tayyor.
- Provayder adapteri siz tanlaganingizdan va narxini ko'rib chiqqaningizdan keyin yoziladi.
