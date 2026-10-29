# Release Gate

```bash
python scripts/release_gate.py                    # lokal
python scripts/release_gate.py --require-frontend # frontend e2e ham majburiy (CI frontend job)
```

## Tekshiruvlar

| Tekshiruv | Majburiy | Izoh |
|---|---|---|
| lint (ruff) | ha | E, F, W qoidalari |
| JS sintaksisi (`node --check`) | `--require-frontend` bilan | Node bo'lmasa — bajarilmadi |
| unit | ha | modul mantiqi |
| integration | ha | ffmpeg, git, sandbox, mock HTTP |
| api | ha | FastAPI TestClient |
| permissions | ha | tasdiq, siyosat, sandbox, kengaytma ruxsatlari |
| errors | ha | xato holatlari va noto'g'ri kirishlar |
| frontend | `--require-frontend` bilan | Playwright + Chromium, barcha bo'limlar va asosiy oqimlar |

To'liq test to'plami har safar ishlaydi. Bu mavjud funksiyalar buzilmaganini tekshiradi (regressiya).

## Natijalar

| Natija | Ma'nosi | Chiqish kodi |
|---|---|---|
| **PASS** | Barcha majburiy tekshiruvlar bajarildi va o'tdi | 0 |
| **FAIL** | Biror tekshiruv yoki test muvaffaqiyatsiz | 1 |
| **INCOMPLETE** | Majburiy tekshiruv bajarilmadi: vosita yo'q yoki toifadagi hamma test skip bo'ldi. Bu "tayyor" degani **emas**. | 2 |

Hisobot `JARVIS_HOME/release/last.json` ga yoziladi. U dashboardda ko'rinadi: Testlar va yaxshilash → Release gate.

## CI

`.github/workflows/jarvis-ci.yml` ikki job'dan iborat:
- **release gate:** Ubuntu va Windows'da ishlaydi. Frontend bu yerda majburiy emas.
- **frontend gate:** Ubuntu'da Playwright, Chromium va FFmpeg bilan ishlaydi, `--require-frontend` rejimida.

Hisobotlar artifact sifatida yuklanadi.
