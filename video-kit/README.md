# Video kit: namuna reel'dagi vositalar va uslub

Manba: Instagram reel `DfMNORBAxFK` ("Claude zvuklarini to'g'irlaymiz — 3 ta bepul instrument").
Video fayli: `reference/namuna_reel.mp4` (720x1280, 9:16, 43 s). Har 2 soniyadagi kadrlar: `reference/sheet_0*.jpg`.

## 1. Videoda ko'rsatilgan 3 ta bepul vosita

| # | Vosita | Nima qiladi | Manba |
|---|---|---|---|
| 01 | **Earshot** | Claude "eshitishi" uchun: ovozni tahlil qiladi (`describe`, `timeline`, `critique`), kod orqali 252 ta tayyor SFX (whoosh, hit, riser, pop, ding...) render qiladi (`sfx`, `kit`), MCP server sifatida ham ishlaydi. MIT litsenziya. | https://github.com/Leonxlnx/earshot (skill'lar: `skills/earshot`, `skills/real-sound`) |
| 02 | **Real SFX** | Videodagi momentlarni topadi (`find_moments.py`, `look.py`) va har biriga haqiqiy yozilgan ovozni aynan kerakli kadrga qo'yadi, musiqa/ovozni saqlaydi. Natija: yangi MP4 + alohida SFX WAV + hisobot. 78 ta CC0 UI ovozi bilan keladi. | https://github.com/Clipwing/skills (`skills/real-sfx`) |
| 03 | **Openverse** | 5 000 000+ ochiq litsenziyali (CC) ovoz kutubxonasi — kerakli effektni qidirib yuklab olish. | API: https://api.openverse.org/v1/audio/?q=whoosh · MCP: https://github.com/pipeworx-io/mcp-openverse yoki https://github.com/Losera/soundfetch |

### O'rnatish (yangi sessiyada)

```bash
mkdir -p ~/tools && cd ~/tools
git clone --depth 1 https://github.com/Leonxlnx/earshot.git
git clone --depth 1 https://github.com/Clipwing/skills.git clipwing-skills

# Earshot: sfx/kit/measure modelsiz ishlaydi (torch shart emas)
pip install numpy scipy soundfile soxr librosa pyloudnorm scikit-learn pillow matplotlib
pip install --no-deps -e ~/tools/earshot
# to'liq tahlil (describe/match/timeline) uchun: pip install torch --index-url https://download.pytorch.org/whl/cpu transformers

# Skill'larni Claude Code'ga qo'shish
mkdir -p ~/.claude/skills
cp -R ~/tools/clipwing-skills/skills/real-sfx ~/.claude/skills/
cp -R ~/tools/earshot/skills/earshot ~/tools/earshot/skills/real-sound ~/.claude/skills/
cd ~/.claude/skills/real-sfx && python scripts/setup.py init --uisfx && python scripts/setup.py check
```

Eslatma: cloud muhitda `api.openverse.org` va `instagram.com` tarmoq sozlamalarida yopiq. Openverse uchun
environment → Network access → Allowed domains ga `api.openverse.org` qo'shing.

### Ish tartibi (ovoz qo'shish)

```bash
# 1) videoni ko'rish: kadrlar + ostidagi ovoz
python scripts/look.py FILM.mp4 --out work/look
# 2) momentlarni topish va cue ro'yxati
python scripts/find_moments.py FILM.mp4 --out work/moments
python scripts/suggest_cues.py work/moments/moments.json --out work/cues.json
# 3) ovozlarni joylash (avval --plan bilan tekshirish)
python scripts/mix.py work/cues.json --out result/film_sfx.mp4 --plan
python scripts/mix.py work/cues.json --out result/film_sfx.mp4
# 4) Earshot bilan tekshirish / yetishmagan effektni render qilish
earshot sfx list
earshot sfx render <ID> -o whoosh.wav --apex 0.3
earshot timeline result/film_sfx.mp4
```

Videodagi asosiy g'oya: "Oldin" — effektlar noto'g'ri joyda va juda baland (CLIPPING, -30 LUFS ...).
"Keyin" — **to'g'ri joy, to'g'ri balandlik** (ON BEAT, ~-14 LUFS).

## 2. Vizual uslub (namuna reel)

- **Format:** 9:16 vertikal, 1080x1920 (namuna 720x1280), 30 fps, 40-45 s.
- **Fon:** deyarli qora (#0A0A0A), tepa va pastda xira yashil nur (radial gradient, ~#3A4A00).
- **Asosiy rang:** neon laym-yashil **#C6F432** (glow bilan), oq matn, ogohlantirish uchun qizil **#E8344A**.
- **Sarlavha:** tepada, 2 qator, juda qalin (Inter/Manrope ExtraBold, UPPERCASE). 1-qator oq, 2-qator yashil
  glow bilan. Masalan: "CLAUDE ZVUKLARINI / TO'G'IRLAYMIZ", "3 TA BEPUL / INSTRUMENT", "KOMMENTGA / «SOUND»".
- **Markaz:** qorong'i UI kartalar (dumaloq burchak, ingichka chegara, `● ● ●` oyna tugmalari, monospace yozuvlar):
  timeline/waveform, ekvalayzer ustunlari, terminal (`> make a riser whoosh for my intro`), qulflangan ro'yxat
  `01 ? / 02 ? / 03 ?` → ochilganda `01 EARSHOT ✓`.
- **Maskot:** pastki o'ng burchakda naushnikli to'q sariq piksel-robot (har kadrda).
- **Subtitr:** ekran pastida bitta so'z, qora "pill" fonda oq qalin matn; muhim so'z yashil rangda
  ("bepul", "Earshot", "proyektingizga"). So'zlar ovozga mos ketma-ket almashadi.
- **Animatsiya:** tez kesishlar, motion blur bilan zoom/slayd o'tishlar, raqam hisoblagich (1 899 800 → 5 000 000+),
  "OLDIN" kabi qizil stiker.
- **Yakun (CTA):** "KOMMENTGA «SOUND»" — kommentga so'z yozish animatsiyasi, "Mana linklar, direktda · Ochish ↗".

## 3. Ssenariy tuzilmasi (namuna)

1. Hook (0-6 s): muammo — "Grafika zo'r, lekin eshitib ko'rsangiz..." (CLIPPING, BOING/WHOOSH/DING noto'g'ri joyda).
2. Va'da (6-9 s): "3 ta bepul instrument".
3. Oldin/Keyin (9-16 s): to'g'ri joy, to'g'ri balandlik.
4. Vosita 1, 2, 3 (16-36 s): har biri qulfdan ochiladi + nima qilishi ko'rsatiladi.
5. CTA (36-43 s): "Kommentga «SOUND» deb yozing — linklarni direktda beraman".

Oson Market POS videolari uchun ham shu tuzilma: hook (muammo) → va'da → oldin/keyin → yechim → CTA.
