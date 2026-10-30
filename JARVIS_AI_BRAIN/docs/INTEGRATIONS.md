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

## Telegram Control Center
Hammasi dashboard → **Telegram** sahifasida, terminal kerak emas.
1. @BotFather → `/newbot` → tokenni oling va `telegram_bot_token` maydoniga kiriting. Token Credential Manager'da saqlanadi.
2. Ixtiyoriy: **ruxsat berilgan telefon raqami**.
3. **Ulash kodini olish** → havolani oching yoki botga `/start KOD` yuboring. Kod 10 daqiqa amal qiladi va bir martalik; soatiga 5 ta noto'g'ri urinishdan keyin ulash yopiladi.
4. Raqam belgilangan bo'lsa, botdagi **📱 Raqamni tasdiqlash** tugmasini bosing. Faqat o'zingizning kontaktingiz qabul qilinadi (`contact.user_id` yuboruvchiga teng bo'lishi kerak).

Xavfsizlik:
- **Bitta ega.** Buyruqlar faqat shu `user_id` + `chat_id` dan, faqat shaxsiy chatdan qabul qilinadi. Guruh va kanallar e'tiborsiz qoldiriladi.
- **Begonalar.** Ularga javob berilmaydi va ma'lumot berilmaydi. Har urinish audit jurnaliga yoziladi, egasiga bir marta ogohlantirish yuboriladi.
- **Token almashsa**, egalik va barcha ochiq tugmalar bekor bo'ladi. "Ruxsatni bekor qilish" tugmasi istalgan vaqtda uzadi.

**Tasdiqlash tugmalari (✅/❌).**
- Har bir so'rov uchun tasodifiy kalit yaratiladi; muddati standart 30 daqiqa. Tugma bir martalik.
- Qaror aynan yuborilgan versiya xeshi bilan qabul qilinadi: amal o'zgarsa, eski tugma ishlamaydi.
- Begona bosgan tugma rad etiladi. Har qaror audit jurnaliga yoziladi.
- E-darajali amallar (zaxiradan tiklash, kodni asosiy versiyaga o'tkazish) faqat dashboardda tasdiqlanadi. Bu `telegram_approval_max_level` (qulflangan) bilan belgilanadi.

**Buyruqlar.** `/start /status /tasks /agents /approvals /approve ID /reject ID /report /voice /stop /help`. Oddiy matn JARVIS'ga topshiriq sifatida ketadi.

**Hodisalar.** Qaysi hodisalar Telegram'ga yuborilishini sahifada tanlaysiz. Mavjudlari: ishga tushish, xatolar, API/xizmat uzilishi, Instagram, Telegram uzilishi, vazifalar, tasdiqlar, resurslar (RAM ≥92%, disk <3 GB), zaxira, xavfsizlik, kod o'zgarishi, POS.

**Ovoz.**
- `/voice` va critical ogohlantirishlar o'zbekcha ovozli xabar sifatida keladi (espeak-ng, OGG uchun FFmpeg).
- Siz yuborgan ovozli xabar matnga aylantiriladi (Whisper yuklangan bo'lsa). Bajarishdan oldin "Tushundim: «…». Bajaraymi?" deb tasdiq so'raladi.

**Qo'ng'iroq.** Telegram Bot API bot nomidan qo'ng'iroq qilish imkonini bermaydi, shuning uchun bu funksiya Telegram orqali YO'Q. Haqiqiy qo'ng'iroq uchun alohida telefoniya xizmati kerak: Bildirishnomalar → Twilio. U pullik va har qo'ng'iroq tasdiq bilan.

**Telegram → Instagram.** «Instagram'ga Reels tayyorla: https://…/video.mp4 mavzu: chegirma» deb yozsangiz:
1. JARVIS loyiha tuzadi: caption (AI) va hashtaglar.
2. Media havolasini tekshiradi. Instagram API ommaviy https:// havolani talab qiladi.
3. Telegram'ga ✅/❌ tugmali so'rov yuboradi.
4. Tasdiqlasangiz, Graph API orqali joylaydi, natijani tekshiradi (Instagram ID) va yakuniy hisobot yuboradi.
5. Xato bo'lsa, sababi va yechimi yoziladi.

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

### Token muddati va ruxsatlari
**Meta App ID** (Instagram yo'riqnomasidagi maydon) va `meta_app_secret` ni kiriting. Shundan keyin "token muddati va ruxsatlari" tugmasi `debug_token` orqali quyidagilarni ko'rsatadi:
- token yaroqliligi;
- necha kun qolgani;
- yetishmayotgan ruxsatlar.

### Instagram MCP Connector (ixtiyoriy)
Agar sizda Instagram MCP serveri bo'lsa:
1. Instagram sahifasidagi MCP kartasiga uning manzilini kiriting: `https://…`, yoki shu kompyuterdagi `http://127.0.0.1:…`.
2. Kerak bo'lsa `instagram_mcp_token` ni kiriting.

Ishlash tartibi:
- JARVIS standart MCP protokoli bilan ulanadi (`initialize` → `tools/list`) va serverdagi vositalarni ro'yxatga oladi.
- `readOnlyHint` belgisi bor vositalar darhol chaqiriladi. Qolganlari (joylash, javob, xabar) tashqi ta'sirli hisoblanadi: ular faqat tasdiq bilan bajariladi, tasdiqni Telegram tugmasi orqali ham berish mumkin.
- Server qaytargan matn `<untrusted>` deb belgilanadi va hech qachon ko'rsatma sifatida bajarilmaydi.
- Ulanish jadval bo'yicha tekshiriladi. Uzilsa, bildirishnoma keladi.
- JARVIS faqat server bergan imkoniyatlarni ko'rsatadi, ortig'ini "bor" demaydi.

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

## YesPOS
Holat (2026-10-30):
- YesPOS'ning **ochiq API hujjati topilmadi**.
- Bulut ishlab chiqish muhitidan `app.yespos.uz` ga ulanib bo'lmadi. Shuning uchun saytning o'zi real holatda sinalmagan.

Bu holatda xavfsiz yo'l — **siz o'zingiz kirgan brauzer sessiyasi orqali faqat o'qish**:
1. `pip install playwright` va `python -m playwright install chromium` ni bajaring.
2. Dashboard → **POS ulanishi** → **"YesPOS sozlamasi"**. Sayt va brauzer ruxsati yoqiladi.
3. **"POS'ga kirish (o'zim kiraman)"** ni bosing:
   - brauzer oynasi ochiladi;
   - login va parolni **o'zingiz** kiritasiz, CAPTCHA yoki SMS kodni ham o'zingiz o'tasiz;
   - so'ng oynani yopasiz.

   JARVIS parolni ko'rmaydi va saqlamaydi. Sessiya cookie'lari `JARVIS_HOME\browser_profile` da qoladi. Ular Git'ga ham, zaxira nusxaga ham kirmaydi.
4. Hisobot sahifasini kiriting (masalan, `https://app.yespos.uz/reports`) va **"Jadvallarni olish"** ni bosing:
   - sahifadagi jadvallar CSV qilib saqlanadi;
   - **"BI'ga import"** bilan tahlilga o'tadi.
5. Kerak bo'lsa, **"Sessiyani unutish"** saqlangan cookie'larni o'chiradi.

Muqobil yo'l — eng ishonchli: YesPOS hisobotidagi **Excel'ga eksport** tugmasi bilan faylni yuklab oling va BI bo'limiga yuklang.

YesPOS'ga hujjat **kiritish** (yozish) qo'shilmagan. Buning uchun YesPOS'dan rasmiy API va token so'rash kerak. API berilsa, `pos_connector: "api"` va `pos_api` sozlamasi bilan ulanadi.

### YesPOS — avtomatik o'qish
1. **"YesPOS sozlamasi"** ni bosing, keyin **"POS'ga kirish"** orqali bir marta kiring.
2. **"Avtomatik o'qish"** bo'limida hisobot sahifalarini kiriting. Har qatorga bitta: `nom | manzil | tur`. Masalan: `savdo | https://app.yespos.uz/reports | auto`.
3. **"Hozir o'qish"** bilan sinab ko'ring. Natija to'g'ri bo'lsa, **"Avtomatik o'qishni yoqish"** ni belgilang (standart: har 6 soatda).

JARVIS ishlab turganda hisobotlar jadval bo'yicha o'qiladi va BI'ga qo'shiladi:
- har bir manbaning eski nusxasi almashtiriladi, savdo ikki marta hisoblanmaydi;
- kam qolgan mahsulot, narx xatosi, takroriy hujjat yoki katta tafovut bo'lsa, bildirishnoma keladi (Telegram sozlangan bo'lsa unga ham);
- sessiya tugasa, "qayta kiring" xabari keladi.

YesPOS'ga hech narsa yozilmaydi.

Real YesPOS bilan hali sinalmagan. Agar u jadvallarni `<table>` sifatida ko'rsatmasa yoki ustun nomlari tanilmasa, "Hozir o'qish" natijasini yuboring. Moslashtirib beraman.
