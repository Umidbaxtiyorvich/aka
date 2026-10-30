# Sizning kompyuteringiz uchun sozlash

**Kompyuter:** MSI GF63 Thin 11SC · Intel i7-11800H (8 yadro / 16 oqim) · 8 GB RAM · Windows 11 Pro.

**Videokarta:** bu model odatda **NVIDIA GTX 1650 (4 GB VRAM)** bilan keladi. Uni tasdiqlash uchun:
- `dxdiag` → **"Преобразователь"** yorlig'i;
- yoki Task Manager → Performance → GPU 1.

VRAM boshqacha chiqsa, `setup_ai.py --vram <GB>` qilib ko'rsating.

## 1. JARVIS'ni o'rnatish

```powershell
git clone https://github.com/Umidbaxtiyorvich/aka.git
cd aka\JARVIS_AI_BRAIN
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
```

## 2. Mahalliy AI (Ollama)

1. https://ollama.com/download → Windows uchun o'rnating.
2. Tavsiyani ko'ring:
   ```powershell
   .\.venv\Scripts\python.exe scripts\setup_ai.py --vram 4
   ```
3. Qo'llang va yuklang. Hajm ~4.6 GB, oldin sizdan so'raladi:
   ```powershell
   .\.venv\Scripts\python.exe scripts\setup_ai.py --vram 4 --apply --pull
   ```

| Vazifa | Model | Hajm | Izoh |
|---|---|---|---|
| Oddiy savollar | `qwen2.5:1.5b` | ~1.0 GB | Tez |
| Kod, tahlil | `qwen2.5:3b` | ~1.9 GB | 4 GB VRAM'ga to'liq sig'adi |
| Rasm mazmuni | `moondream` | ~1.7 GB | |
| Ovoz → matn | Whisper `small` | ~480 MB | `pip install faster-whisper` |

**8 GB RAM uchun qoida:** 7B modellar (4.7 GB) tavsiya etilmaydi. Ular VRAM'ga sig'maydi va kompyuterni sekinlashtiradi.

## 3. O'zbekcha ovoz

espeak-ng'ni o'rnating: https://github.com/espeak-ng/espeak-ng/releases → `espeak-ng.msi`.

## 4. Rasm yaratish (ixtiyoriy)

GTX 1650 bilan faqat **Stable Diffusion 1.5** ishlaydi. Ishga tushirish parametrlari: `--api --medvram --precision full --no-half`. 512×512 rasm taxminan 30–60 soniyada tayyor bo'ladi. SDXL bu kartaga og'irlik qiladi.

## 5. YesPOS

Batafsil: [INTEGRATIONS.md → YesPOS](INTEGRATIONS.md#yespos).
