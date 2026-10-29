# JARVIS AI BRAIN

O'zbek tilida ishlaydigan, doimiy xotirali, agentli va **har bir muhim amalni faqat sizning tasdig'ingizdan keyin bajaradigan** shaxsiy AI yordamchi.

> JARVIS ongga ega emas. U — AI modeli (ixtiyoriy), SQLite xotira, qoidalar va ruxsat berilgan vositalardan iborat dastur.

## Holat (0.1.0 — 1-bosqich)

| Holat | Funksiya |
|---|---|
| ✅ Ishlaydi | FastAPI backend, o'zbekcha dashboard (dark/neon-blue), matnli chat (lotin/kirill, xatoga chidamli buyruqlar) |
| ✅ Ishlaydi | Doimiy xotira: qo'shish, FTS qidiruv, tahrirlash, eksport, o'chirish; manba/sana/ishonch; zid ma'lumotni belgilash |
| ✅ Ishlaydi | Audit jurnali (maxfiy ma'lumotlar avtomatik yashiriladi), xatolar jurnali |
| ✅ Ishlaydi | Approval Engine: A–E darajalar, tasdiq payload'ning SHA-256 xeshiga bog'langan, o'zgarsa bekor bo'ladi, takroriy/noma'lum natija himoyasi |
| ✅ Ishlaydi | 6 ta haqiqiy agent: Manager, Developer (Python tahlili), File Analysis, Computer (tasdiq bilan), Security, QA; ketma-ket navbat |
| ✅ Ishlaydi | Fayllarni o'qish (txt/csv/xlsx/pdf) faqat ruxsat berilgan papkada; `.env`, kalit fayllari bloklangan |
| ✅ Ishlaydi | Diagnostika (RAM/CPU/disk/GPU), model katalogi, self-check va pytest dashboarddan |
| ⚠️ Qisman | AI suhbat: Ollama ulansa ishlaydi (adapter tayyor, real Ollama bilan hali sinalmagan); aks holda offline rejim |
| ⏳ Hali yo'q | Ovoz, internet tadqiqoti, brauzer agenti, rasm/video, Instagram, Telegram, POS/BI, telefon qo'ng'irog'i — [docs/ROADMAP.md](docs/ROADMAP.md) |

Rejadagi 9 ta agent dashboardda xira ko'rinadi va vazifa qabul qilmaydi — ishlayotgandek ko'rsatilmaydi.

## Uch ish rejimi

1. **Cloud Development** — Claude Code bulut muhitida kod yoziladi, testlar bajariladi, GitHub'ga yuboriladi. GitHub faqat kodni saqlaydi: u server ham, JARVIS xotirasi ham emas.
2. **Local AI Runtime** — Windows 11 kompyuteringizda ishga tushirasiz. Xotira (`jarvis.db`) faqat sizning kompyuteringizda bo'ladi.
3. **Optional Cloud Deployment** — kelajakda, faqat sizning qaroringiz bilan (narx, maxfiylik, autentifikatsiya oldindan muhokama qilinadi). Hozir server faqat `127.0.0.1` da tinglaydi.

## Windows 11'da ishga tushirish

```powershell
git clone https://github.com/Umidbaxtiyorvich/aka.git
cd aka\JARVIS_AI_BRAIN
powershell -ExecutionPolicy Bypass -File scripts\check_system.ps1   # GPU/RAM/disk diagnostikasi (faqat o'qiydi)
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1  # .venv + kutubxonalar (~40 MB) + testlar
powershell -ExecutionPolicy Bypass -File scripts\start_windows.ps1  # http://127.0.0.1:8765
```

Ma'lumotlar standart holatda `JARVIS_AI_BRAIN\data\` ichida. Boshqa diskda saqlash ixtiyoriy: `setx JARVIS_HOME D:\JARVIS_DATA`.

Fayl tahlili uchun fayllarni `data\workspace\` ichiga joylang (faqat shu papka ruxsat etilgan). Boshqa papkalarni `data\settings.json` dagi `allowed_read_dirs` ga o'zingiz qo'shasiz.

### Mahalliy AI (Ollama) — ixtiyoriy

Model avtomatik yuklanmaydi. 8 GB RAM uchun boshlang'ich tavsiya — `qwen2.5:1.5b` (~1 GB disk, ~2 GB RAM).

1. https://ollama.com dan Ollama'ni o'rnating.
2. `ollama pull qwen2.5:1.5b`
3. Dashboard → Sozlamalar → Provider: `ollama` → Saqlash. Holat darhol tekshiriladi.

GPU (VRAM 6 GB+) bo'lsa, kattaroq modellar Sozlamalar → Model katalogida ko'rsatilgan.

## Ishlab chiqish (Linux/bulut)

```bash
cd JARVIS_AI_BRAIN
pip install -r requirements.txt httpx
python -m pytest -q
./scripts/start.sh            # http://127.0.0.1:8765
```

## Chat buyruqlari namunasi

- `yordam` — nima ishlaydi va nima hali yo'q
- `eslab qol: hisobotlar har dushanba` · `xotira: hisobot`
- `vazifa: POS manzilini topish`
- `holat` · `fayllar` · `test`
- ``bajar `dir` `` — buyruq taklif qilinadi, tasdiqlashlar bo'limida tasdiqlanadi

## Hujjatlar

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — arxitektura va modullar
- [docs/SECURITY.md](docs/SECURITY.md) — xavfsizlik, tasdiqlash, maxfiy kalitlar
- [docs/ROADMAP.md](docs/ROADMAP.md) — keyingi bosqichlar
