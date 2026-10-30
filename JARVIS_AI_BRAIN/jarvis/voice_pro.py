"""Uzbek Voice AI — tabiiy o'zbekcha ovoz va yaxshilangan nutqni tanish.

TTS (javob ovozi), tanlov tartibi "auto" da:
  1. Azure Neural TTS — uz-UZ-MadinaNeural (ayol) / uz-UZ-SardorNeural (erkak). Haqiqiy o'zbekcha neyron ovozlar,
     tabiiy urg'u va pauzalar. Kalit (azure_speech_key) va mintaqa kerak; bepul daraja bor, lekin bu TASHQI xizmat:
     matn Microsoft'ga yuboriladi. Kalit kiritilmaguncha ishlamaydi va "ishlayapti" deb ko'rsatilmaydi.
  2. espeak-ng (uz) — mahalliy, bepul, internetsiz; ovoz sun'iy (robotga o'xshash). Raqamlar o'zbekcha so'zga aylantiriladi.
  3. Brauzer ovozi — faqat brauzerda o'zbekcha ovoz bo'lsa (Windows'da odatda yo'q).
Uzun javob gaplarga bo'linadi va ketma-ket uzatiladi (gapma-gap) — ovoz uzilib qolmaydi, birinchi gap tez boshlanadi.

STT (nutqni tanish):
  * Azure STT (uz-UZ) — kalit bo'lsa; qisqa so'rovlar REST orqali (60 soniyagacha).
  * Whisper (mahalliy) — "auto" tilda o'zbek/rus/ingliz aralash gaplar; lug'at (mahsulot va do'kon nomlari) prompt sifatida;
    beam search; natijadagi so'zlar lug'at bo'yicha ehtiyotkor tuzatiladi (o'xshashlik ≥ 0.86, ro'yxat ko'rsatiladi).
  * Brauzer (Web Speech, uz-UZ) — dashboard ichida.
Ovozli tasdiq xavfli amallar uchun YAGONA omil emas: tasdiqlar faqat tugma (dashboard/Telegram) bilan.
"""
from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from . import net
from .secrets import get_secret

VOICES = {"female": "uz-UZ-MadinaNeural", "male": "uz-UZ-SardorNeural"}
ONES = ["", "bir", "ikki", "uch", "to'rt", "besh", "olti", "yetti", "sakkiz", "to'qqiz"]
TENS = ["", "o'n", "yigirma", "o'ttiz", "qirq", "ellik", "oltmish", "yetmish", "sakson", "to'qson"]
SCALES = [(10**9, "milliard"), (10**6, "million"), (1000, "ming")]


class VoiceProError(Exception):
    pass


def num_to_uz(n: int) -> str:
    """Butun sonni o'zbekcha so'zga: 1250000 → "bir million ikki yuz ellik ming"."""
    if n == 0:
        return "nol"
    if n < 0:
        return "minus " + num_to_uz(-n)
    out = []
    for val, word in SCALES:
        if n >= val:
            out.append(f"{num_to_uz(n // val)} {word}" if not (val == 1000 and n // val == 1) else f"bir {word}")
            n %= val
    if n >= 100:
        out.append(f"{ONES[n // 100]} yuz".strip())
        n %= 100
    if n >= 10:
        out.append(TENS[n // 10])
        n %= 10
    if n:
        out.append(ONES[n])
    return " ".join(w for w in out if w)


def normalize_for_speech(text: str, numbers_to_words: bool = True) -> str:
    t = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    t = re.sub(r"[*_#>`|]+", " ", t)
    t = re.sub(r"https?://\S+", " havola ", t)
    t = re.sub(r"[\U0001F000-\U0001FFFF☀-➿]", " ", t)          # emoji o'qilmaydi
    t = t.replace("•", ",").replace("→", ",").replace("—", ",")
    if numbers_to_words:
        t = re.sub(r"(\d)[\s ](?=\d{3}\b)", r"\1", t)                   # "1 250 000" → "1250000"
        t = re.sub(r"(\d+)[.,](\d+)", lambda m: f"{num_to_uz(int(m[1]))} butun {num_to_uz(int(m[2]))}", t)
        t = re.sub(r"\d{1,12}", lambda m: num_to_uz(int(m[0])), t)
        t = t.replace("%", " foiz")
    return re.sub(r"\s+", " ", t).strip()


def split_sentences(text: str, max_len: int = 220) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+|\n+", text or "")
    out = []
    for p in (x.strip() for x in parts):
        while len(p) > max_len:                                               # juda uzun gap — vergul yoki bo'sh joyda bo'linadi
            cut = max(p.rfind(",", 0, max_len), p.rfind(" ", 0, max_len))
            cut = cut if cut > 40 else max_len
            out.append(p[:cut + 1].strip())
            p = p[cut + 1:].strip()
        if p:
            out.append(p)
    return out


class VoicePro:
    def __init__(self, core):
        self.core = core

    @property
    def s(self):
        return self.core.settings

    # --- holat ---
    def azure_ready(self) -> bool:
        return bool(get_secret("azure_speech_key") and self.s.azure_speech_region)

    def status(self) -> dict:
        espeak = bool(shutil.which("espeak-ng") or shutil.which("espeak"))
        return {"tts": {"azure": {"ready": self.azure_ready(), "voices": VOICES, "online": True,
                                  "note": "Tabiiy o'zbekcha neyron ovoz (Microsoft). Kalit va mintaqa kerak; matn Microsoft'ga yuboriladi."},
                        "espeak": {"ready": espeak, "online": False, "note": "Mahalliy, bepul; ovoz sun'iy."}},
                "stt": {"azure": {"ready": self.azure_ready(), "language": "uz-UZ"},
                        "whisper": {"ready": getattr(self.core.voice, "_model", None) is not None, "model": getattr(self.core.voice, "_model_name", None)},
                        "browser": {"ready": True, "note": "Chrome/Edge Web Speech (uz-UZ) — ovoz Google/Microsoft'ga yuboriladi"}},
                "selected": {"tts": self.tts_engine(), "stt": self.stt_engine()},
                "settings": {k: getattr(self.s, k) for k in ("voice_tts_engine", "voice_stt_engine", "voice_gender", "voice_rate", "voice_volume",
                                                              "voice_stt_language", "voice_silence_ms", "voice_mic_sensitivity", "azure_speech_region")},
                "ffmpeg": bool(shutil.which("ffmpeg"))}

    def tts_engine(self) -> str:
        e = self.s.voice_tts_engine
        if e == "auto":
            if self.azure_ready():
                return "azure"
            return "espeak" if (shutil.which("espeak-ng") or shutil.which("espeak")) else "browser"
        return e

    def stt_engine(self) -> str:
        e = self.s.voice_stt_engine
        if e == "auto":
            if self.azure_ready():
                return "azure"
            return "whisper" if getattr(self.core.voice, "_model", None) is not None else "browser"
        return e

    # --- TTS ---
    def prepare(self, text: str) -> dict:
        eng = self.tts_engine()
        clean = normalize_for_speech(text, numbers_to_words=(eng != "azure"))
        return {"engine": eng, "chunks": split_sentences(clean)[:60]}

    def synth(self, text: str) -> tuple[bytes, str, str]:
        text = (text or "").strip()[:1500]
        if not text:
            raise VoiceProError("Matn bo'sh")
        eng = self.tts_engine()
        if eng == "azure":
            try:
                return self._azure_tts(text), "audio/mpeg", "azure:" + VOICES.get(self.s.voice_gender, VOICES["female"])
            except VoiceProError as e:
                self.core.audit.error("voice_agent", f"Azure TTS: {e}")
                if not (shutil.which("espeak-ng") or shutil.which("espeak")):
                    raise
                text = normalize_for_speech(text)                      # zaxira: mahalliy ovoz
        if eng in ("azure", "espeak"):
            speed = max(80, min(300, int(150 * (1 + self.s.voice_rate / 100))))
            r = self.core.voice.synthesize(text, speed=speed)
            data = Path(r["output"]).read_bytes()
            Path(r["output"]).unlink(missing_ok=True)
            return data, "audio/wav", "espeak-ng (uz)"
        raise VoiceProError("Server ovozi yo'q — brauzer ovozi ishlatiladi (Sozlamalar → ovoz)")

    def _azure_tts(self, text: str) -> bytes:
        key, region = get_secret("azure_speech_key"), self.s.azure_speech_region
        if not (key and region and re.fullmatch(r"[a-z0-9]{3,30}", region)):
            raise VoiceProError("Azure Speech kaliti yoki mintaqasi yo'q")
        voice = VOICES.get(self.s.voice_gender, VOICES["female"])
        rate, vol = f"{int(self.s.voice_rate):+d}%", f"{int(self.s.voice_volume) - 100:+d}%"
        ssml = (f"<speak version='1.0' xml:lang='uz-UZ'><voice name='{voice}'><prosody rate='{rate}' volume='{vol}'>"
                f"{escape(text)}</prosody></voice></speak>")
        st, body, _ = net.post_raw(f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1", ssml.encode("utf-8"),
                                   {"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
                                    "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3"}, timeout=30)
        if st == 401:
            raise VoiceProError("Azure kaliti noto'g'ri yoki muddati tugagan")
        if st == 429:
            raise VoiceProError("Azure so'rovlar chegarasi")
        if st >= 400 or not body:
            raise VoiceProError(f"Azure TTS xatosi: HTTP {st}")
        return body

    # --- STT ---
    def vocabulary(self) -> list[str]:
        words = {"JARVIS", "savdo", "foyda", "qoldiq", "ombor", "chek", "kassa", "qarz", "mahsulot", "do'kon", "bugun", "kecha", "hafta", "oy"}
        db = self.core.db
        if db.one("SELECT 1 FROM sqlite_master WHERE name='ext_records'"):
            for r in db.query("SELECT data FROM ext_records WHERE entity='product' AND deleted=0 LIMIT 400"):
                n = json.loads(r["data"]).get("name")
                if n:
                    words.add(str(n)[:40])
            for r in db.query("SELECT name, store FROM integrations"):
                words.update(x for x in (r["name"], r["store"]) if x)
        return sorted(words)

    def correct(self, text: str, vocab: list[str] | None = None) -> tuple[str, list[dict]]:
        vocab = vocab or self.vocabulary()
        single = {w.lower(): w for v in vocab for w in v.split() if len(w) >= 4}
        fixes, out = [], []
        for tok in re.findall(r"\S+", text):
            core_tok = re.sub(r"[^\w'’-]", "", tok)
            low = core_tok.lower()
            if len(low) >= 4 and low not in single:
                m = difflib.get_close_matches(low, list(single), n=1, cutoff=0.86)
                if m:
                    fixes.append({"from": core_tok, "to": single[m[0]]})
                    tok = tok.replace(core_tok, single[m[0]])
            out.append(tok)
        return " ".join(out), fixes

    def _to_wav16k(self, src: str) -> str:
        ff = shutil.which("ffmpeg")
        if not ff:
            raise VoiceProError("FFmpeg kerak (audio formatini o'zgartirish uchun)")
        dst = str(Path(tempfile.mkdtemp(prefix="jarvis_stt_")) / "a.wav")
        p = subprocess.run([ff, "-y", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", "16000", "-af", "highpass=f=80,lowpass=f=7600", dst],
                           capture_output=True, timeout=120)
        if p.returncode != 0:
            raise VoiceProError("Audio o'zgartirilmadi")
        return dst

    def transcribe(self, audio_path: str) -> dict:
        eng = self.stt_engine()
        if eng == "azure":
            wav = self._to_wav16k(audio_path)
            try:
                key, region = get_secret("azure_speech_key"), self.s.azure_speech_region
                lang = "uz-UZ" if self.s.voice_stt_language in ("uz", "auto") else self.s.voice_stt_language
                st, body, _ = net.post_raw(f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
                                           f"?language={lang}&format=detailed", Path(wav).read_bytes(),
                                           {"Ocp-Apim-Subscription-Key": key, "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000"}, timeout=60)
            finally:
                shutil.rmtree(Path(wav).parent, ignore_errors=True)
            if st >= 400:
                raise VoiceProError(f"Azure STT xatosi: HTTP {st}")
            d = json.loads(body or b"{}")
            if d.get("RecognitionStatus") != "Success":
                return {"text": "", "engine": "azure", "status": d.get("RecognitionStatus"), "corrections": []}
            text = d.get("DisplayText") or ((d.get("NBest") or [{}])[0].get("Display", ""))
            conf = (d.get("NBest") or [{}])[0].get("Confidence")
            fixed, fixes = self.correct(text)
            return {"text": fixed, "raw": text, "engine": "azure", "confidence": conf, "corrections": fixes}
        if eng == "whisper":
            m = getattr(self.core.voice, "_model", None)
            if m is None:
                raise VoiceProError("Whisper modeli yuklanmagan (Voice bo'limida yuklang)")
            lang = None if self.s.voice_stt_language == "auto" else self.s.voice_stt_language
            prompt = "O'zbekcha suhbat. " + ", ".join(self.vocabulary()[:80])
            segs, info = m.transcribe(audio_path, language=lang, vad_filter=True, beam_size=5, initial_prompt=prompt,
                                      condition_on_previous_text=False)
            text = " ".join(s.text.strip() for s in segs if s.text.strip())
            fixed, fixes = self.correct(text)
            return {"text": fixed, "raw": text, "engine": f"whisper:{getattr(self.core.voice, '_model_name', '')}", "language": info.language,
                    "confidence": round(info.language_probability, 2), "corrections": fixes}
        raise VoiceProError("Server STT tanlanmagan — brauzer (Web Speech) ishlatiladi")
