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

## Dashboard PIN
- Birinchi kirishda PIN o'rnatasiz. U faqat shu kompyuterdan o'rnatiladi va xeshlangan holda saqlanadi.
- PIN'ni unutsangiz: `python scripts\reset_pin.py`.
- Tarmoqdan kirish kerak bo'lsa (tavsiya etilmaydi):
  1. `--host 0.0.0.0` bilan ishga tushiring.
  2. `data\settings.json` → `allowed_hosts` ga kompyuter IP manzilini qo'shing.
  3. Bunda HTTPS yo'qligini yodda tuting.

## O'zbekcha ovoz (TTS)
- espeak-ng'ni o'rnating (bepul, ~5 MB): https://github.com/espeak-ng/espeak-ng/releases → `espeak-ng.msi`.
- O'rnatilgach, Voice bo'limi brauzerda o'zbekcha ovoz bo'lmasa espeak-ng (`uz`) ni ishlatadi.
- Video studiyada "O'zbekcha ovoz qo'shish" ishlaydi.

## Avtomatik subtitr
1. `pip install faster-whisper` ni bajaring.
2. Voice → modelni yuklang (small ≈480 MB).
3. Studiya → "Avtomatik subtitr" ni tanlang.

Natijani nashrdan oldin tekshiring.

## Mahalliy rasm generatsiyasi
- Talab: NVIDIA GPU, kamida 4 GB VRAM (SD 1.5) yoki 6–8 GB (SDXL).
- Sozlash:
  1. Stable Diffusion WebUI (AUTOMATIC1111 yoki Forge) ni `--api` bilan ishga tushiring.
  2. Sozlamalar → "Rasm generatori" ga `http://127.0.0.1:7860` ni yozing.
- Model fayllarini (2–7 GB) o'zingiz yuklaysiz.

## Rasm mazmunini tahlil qilish (vision)
1. `ollama pull moondream` (≈1.7 GB) yoki `llava:7b` (≈4.7 GB).
2. Sozlamalar → "Vision modeli": `moondream`.

Rasm tashqariga yuborilmaydi.

## POS REST API
POS rasmiy API bersa:
1. Sozlamalar → POS konnektori: `api`.
2. "POS REST API sozlamasi" ga yozing:
   ```json
   {"base_url": "https://pos.example.uz/api", "create_path": "/documents",
    "find_path": "/documents?external_key={key}", "auth_header": "Authorization", "auth_scheme": "Bearer"}
   ```
3. Tokenni kiriting: `python scripts\set_secret.py pos_api_token`. Faqat kerakli huquqlarga ega token tavsiya etiladi.

Har bir hujjat `Idempotency-Key` bilan yuboriladi. Javob kelmasa, qayta yuborilmaydi.

## Telefon qo'ng'irog'i (Twilio, pullik)
1. `data\settings.json` ga yozing:
   ```json
   "telephony_provider": "twilio", "telephony_account_sid": "AC...", "telephony_from": "+1...",
   "telephony_cost_per_min": 0.3, "telephony_rules": [{"category": "pos", "severity": "critical", "phone": "+998..."}]
   ```
2. Tokenni kiriting: `python scripts\set_secret.py twilio_auth_token`.

Ishlash tartibi:
- Kritik bildirishnoma qoidaga mos kelsa, faqat qo'ng'iroq **rejasi** va tasdiq so'rovi yaratiladi.
- Qo'ng'iroq faqat siz "Qo'ng'iroq qilish" tugmasini bosganingizda amalga oshadi.
- Twilio o'zbek tilida o'qimaydi: xabar `telephony_voice_language` (standart `ru-RU`) tilida o'qiladi.
- Narxlar uchun Twilio saytini tekshiring.

## Avtomatik ishga tushirish (Windows)
- O'rnatish: `powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1`
- O'chirish: `... -Uninstall`

Faqat sizning foydalanuvchingiz uchun ishlaydi, administrator huquqi kerak emas. Server xato bilan to'xtasa, 3 martagacha qayta ishga tushadi.
