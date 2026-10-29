# Zaxira nusxa va tiklash

## Nima saqlanadi

| Saqlanadi | Saqlanmaydi |
|---|---|
| `jarvis.db` — xotira, audit, tasdiqlar, BI, POS hujjatlari, qarorlar va boshqalar. SQLite online backup bilan olinadi, shuning uchun nusxa izchil bo'ladi. | Maxfiy kalitlar. Ular Windows Credential Manager'da turadi. Qayta o'rnatishda `scripts\set_secret.py` bilan qayta kiritiladi. |
| `settings.json`. Unda maxfiy kalitga o'xshash qiymat topilsa, nusxa olinmaydi. | Kod. Kod Git va GitHub'da turadi. GitHub esa ma'lumotlar bazasining nusxasi emas. |
| `workspace/` — ixtiyoriy (`backup_include_workspace`). 50 MB dan katta fayllar kirmaydi. | |
| `manifest.json` — har bir faylning SHA-256 xeshi, `integrity_check` natijasi va jadvallardagi qatorlar soni. | |

## Joylashuv va jadval

- Nusxalar: `JARVIS_HOME\backups\jarvis_<vaqt>.zip`. Tarixi: `history.json`.
- Server ishlab turganda nusxa har `backup_interval_hours` soatda (standart 24) avtomatik olinadi va darhol tekshiriladi.
- Eski nusxalar avtomatik o'chiriladi. Oxirgi `backup_keep` ta (standart 10) qoladi, umumiy hajm `backup_max_total_mb` dan oshmaydi.
- Nusxa olish yoki tekshirish muvaffaqiyatsiz bo'lsa: kritik bildirishnoma keladi, Telegram sozlangan bo'lsa unga ham.

**Muhim:** nusxalar shu kompyuterda turadi. Disk buzilishidan himoya uchun `backups` papkasini vaqti-vaqti bilan tashqi diskka yoki shifrlangan bulut saqlovchiga o'zingiz ko'chiring.

## Tekshirish

Dashboard → Testlar va yaxshilash → Zaxira nusxalar → **Tekshirish**. Yoki terminalda:

```powershell
.\.venv\Scripts\python.exe scripts\backup.py verify jarvis_20261029_120000_000000.zip
```

Quyidagilar tekshiriladi:
1. Zip CRC.
2. Manifestda yo'q qo'shimcha fayl yo'qligi.
3. Har bir faylning SHA-256 xeshi.
4. Vaqtinchalik papkaga sinov-tiklash: `integrity_check` va qatorlar soni manifest bilan mos kelishi.

## Tiklash

1. **Dashboard orqali:**
   - Nusxa → "Tiklash"ni bosing. E darajali tasdiq yaratiladi.
   - Tasdiqlashlar bo'limida aniq nusxani tasdiqlang.
   - Qaytib, "Tiklash"ni yana bosing.
2. **Terminal orqali:** `python scripts\backup.py restore <nom>`. Tasdiqlash uchun nusxa nomini qayta yozasiz.
3. Har ikki usulda ham tiklashdan oldin **joriy holatning xavfsizlik nusxasi** avtomatik olinadi. Tiklash noto'g'ri bo'lsa, shu nusxaga qaytasiz.
4. Tiklashdan keyin JARVIS'ni qayta ishga tushirish tavsiya etiladi. Telegram bot kabi fon jarayonlari yangi sozlamani shundan keyin oladi.

## Butunlay yangi kompyuterga ko'chirish

1. Repozitoriyni klonlang va `scripts\setup_windows.ps1` ni ishga tushiring.
2. Zip ichidagi `jarvis.db` va `settings.json` ni `data\` papkasiga oching. Yoki avval `backups` papkasini ko'chirib, `scripts\backup.py restore` ishlating.
3. Maxfiy kalitlarni `scripts\set_secret.py` bilan qayta kiriting.
4. `scripts\backup.py verify` va dashboarddagi diagnostika bilan holatni tekshiring.
