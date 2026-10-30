# Universal AI Ecosystem (v0.9) — audit, bosqichlar va halol holat

## Phase 1 — mavjud loyiha auditi (v0.8 holati)
| Modul | Holat | Izoh |
|---|---|---|
| AI Router (`router.py`) | **bor, ishlaydi** | murakkablik bo'yicha tanlov, maxfiylik → mahalliy, fallback, sifat bahosi, `ai_usage` jurnali |
| Cost Guard (`resource_guard.py`) | **bor** | kunlik/oylik limit, pullik AI standart o'chiq |
| Provayderlar | **qisman** | faqat 4 tur (Ollama, OpenAI-mos, Anthropic, offline), tekshiruv faqat "kalit bormi" |
| Model katalogi / imkoniyatlar | **yo'q** | → v0.9 da qo'shildi |
| Fayl tahlili (`files.py`) | **qisman** | TXT/MD/kod, CSV, XLSX, PDF matni (2 MB gacha). DOCX/PPTX/OCR/arxiv/tahrirlash yo'q |
| Rasm/video (`studio.py`, `imagegen.py`) | **qisman** | FFmpeg montaj (kesish, birlashtirish, 9:16, subtitr, ovoz), mahalliy Stable Diffusion WebUI (ixtiyoriy), Ollama vision. Bulut rasm/video API yo'q |
| Xotira (`memory.py`, `kgraph.py`) | **bor** | SQLite + FTS5, manba/sana/ishonch, takror va qarama-qarshilik, Knowledge Graph. Vektor (semantik) qidiruv **yo'q** |
| ChatGPT importi | **yo'q** | → v0.9 da qo'shildi |
| Agentlar (`agents.py`) | **bor** | chat/reja/kod agentlari `core.ai.route` orqali (markaziy router) |
| Ovoz (`voice_pro.py`) | **bor** | Azure uz-UZ / espeak / Whisper / brauzer, VAD |

## v0.9 da bajarilgan bosqichlar
- **Phase 2 — DB sxema:** `ai_models` (model, imkoniyatlar, manba, narx, kontekst), `ai_provider_checks` (tekshiruv tarixi), `memory_imports`, `memory_import_items`. `CREATE TABLE IF NOT EXISTS` — mavjud bazalar buzilmaydi.
- **Phase 3 — Provider registry (`ai_hub.py`):** 31 ta provayder katalogi; `ai_custom_catalog` sozlamasi bilan yangilari kod o'zgartirmasdan qo'shiladi.
- **Phase 4 — Kalitlar:** faqat Credential Manager (`ai_key_<id>`), API qaytarmaydi, audit va loglarda maskalanadi; kalit almashtirish (rotation) avtomatik qayta tekshiruv bilan.
- **Phase 5 — Tekshiruv:** ulanish → kalit → modellar → kichik test so'rovi → imkoniyatlar → limit/kvota → narx. Holatlar: Connected, Invalid API Key, Connection Failed, Rate Limited, Quota Exceeded, Billing Required, Model Unavailable, Partially Supported. `/models` yo'qligi "ishlamaydi" demaydi — Model ID qo'lda.
  Test so'rovi **pullik** provayderda faqat "Pullik AI" yoqilgan va limit bo'lsa yuboriladi; aks holda bu aniq yoziladi.
- **Phase 6 — Model va imkoniyatlar katalogi:** 18 imkoniyat. Manba ko'rsatiladi: `provider` (masalan OpenRouter modalliklari va narxlari), `name_guess` (model nomidan **taxmin**), `user`, `test`.
- **Phase 7 — LiteLLM:** og'ir kutubxona avtomatik o'rnatilmaydi. LiteLLM **Proxy** (OpenAI-mos gateway) sifatida ulanadi; AWS Bedrock va Vertex AI shu orqali. Azure OpenAI uchun alohida adapter.
- **Phase 8 — Smart Router:** vazifa → imkoniyat (kod, fikrlash, rasm, uzun hujjat, qidiruv, tool calling), provayder ichidan mos modelni tanlash, strategiyalar (muvozanat / eng arzon / sifat / tezlik / faqat bepul), ruxsat berilgan provayderlar, pullikdan oldin tasdiq (chatda tugma), fallback: tanlangan → boshqa mos → mahalliy → JARVIS ichki funksiyalari. Ishlatish paytida 401/402/429 → provayder vaqtincha chetlatiladi (kvota — 1 soat, rate limit — 2 daqiqa).
- **Phase 9 — Xarajat:** bir so'rov uchun maksimal xarajat qo'shildi; jurnal: provayder, model, vazifa, token (o'lchangan/taxminiy), xarajat, vaqt, fallback, natija. Jonli "hozir ishlayotgan model".
- **Phase 10 — Ollama:** katalogda, `/api/tags` orqali modellar, bepul/mahalliy, internet yo'q bo'lsa fallback.
- **Phase 13 — ChatGPT ZIP importi:** xavfsiz ZIP (yo'l, symlink, zip-bomba, hajm cheklovlari, diskka ochilmaydi), `conversations.json` va `chat.html` (jsonData), asosiy suhbat tarmog'i, 12 kategoriya, takror birlashtirish, qarama-qarshiliklar (masalan RAM 8 GB → 16 GB), tugallanmagan suhbatlar, maxfiy jumlalar o'tkaziladi, faqat foydalanuvchi xabarlaridan fakt, tahlil **mahalliy**, import faqat tasdiq bilan, o'chirish (xotiradan ham).

## Hali qilinmagan (keyingi bosqichlar)
- **Phase 11** — DOCX/PPTX/ODT o'qish va tahrirlash, OCR, arxivlar, fayllarni solishtirish/konvertatsiya, katta fayllarni bo'lib o'qish.
- **Phase 12** — bulut rasm/video API (OpenAI Images, Replicate, Gemini Imagen/Veo va h.k.) Media AI Studio'ga ulash.
- **Phase 14** — vektor (semantik) qidiruv: mahalliy embedding modeli (Ollama `nomic-embed-text`) + SQLite; PostgreSQL/pgvector — ixtiyoriy.
- **Phase 15** — qolgan ixtisoslashgan agentlar (Excel/Word/PDF/Video/...) va agentlararo topshiriq.
- **Phase 16** — ovozdan model/agent tanlash buyruqlari.

## Sinov holati
Barcha provayder testlari **sun'iy (mock) serverlar** bilan. Hech bir real API kaliti bulutda ishlatilmagan — real ulanish sizning kompyuteringizda "API tekshirish" orqali tasdiqlanadi.
Provayderlarning base URL va model nomlari o'zgarishi mumkin — kartada tahrirlanadi.
