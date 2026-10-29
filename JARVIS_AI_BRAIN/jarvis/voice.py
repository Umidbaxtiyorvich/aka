"""Voice Engine.

Dvigatellar (siz tanlaysiz):
* browser — brauzerning Web Speech API (Chrome/Edge). uz-UZ ni qo'llaydi, lekin ovoz Google/Microsoft
  serverlariga yuboriladi: internet kerak, maxfiylik — ularning siyosati. TTS ovozi brauzer/OS'ga bog'liq:
  Windows'da o'zbekcha TTS ovozi odatda YO'Q — bunda matn ko'rsatiladi yoki boshqa til ovozi ishlatiladi.
* TTS (server tomonida, mahalliy): espeak-ng — o'zbek ovozi (`uz`) bor, bepul, ~5 MB. Windows: espeak-ng MSI
  (github.com/espeak-ng/espeak-ng/releases). Ovoz sun'iy (robotga o'xshash), lekin o'zbekcha to'g'ri o'qiydi.
  Muqobil: Windows SAPI (o'zbekcha ovoz odatda yo'q — faqat `allow_other_language=True` bilan).
* whisper — mahalliy faster-whisper (internet kerak emas). Ixtiyoriy: `pip install faster-whisper`,
  model hajmi: tiny ≈75 MB, base ≈145 MB, small ≈480 MB, medium ≈1.5 GB. O'zbek tili sifati: tiny/base past,
  small o'rtacha, medium yaxshiroq (8 GB RAMda sekin). Model faqat siz ruxsat berganda yuklanadi.
Mikrofon faqat dashboarddagi tugma bilan yoqiladi va holati doimo ko'rinadi. Yashirin tinglash yo'q.
Ovoz yozuvlari faqat `save_voice_recordings` yoqilganda saqlanadi.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

WHISPER_MODELS = {"tiny": 75, "base": 145, "small": 480, "medium": 1530}


class VoiceError(Exception):
    pass


class Voice:
    def __init__(self, core):
        self.core = core
        self._model = None
        self._model_name = None

    def tts_engines(self) -> dict:
        espeak = shutil.which("espeak-ng") or shutil.which("espeak")
        return {"espeak-ng": {"installed": bool(espeak), "uzbek": bool(espeak), "offline": True},
                "windows_sapi": {"installed": os.name == "nt", "uzbek": "odatda yo'q", "offline": True}}

    def synthesize(self, text: str, out_path: str | None = None, *, speed: int = 150, allow_other_language: bool = False) -> dict:
        """Matnni WAV faylga aylantiradi. Matn buyruq qatoriga emas, fayl orqali beriladi (injection yo'q)."""
        text = (text or "").strip()
        if not text:
            raise VoiceError("Matn bo'sh")
        if len(text) > 5000:
            raise VoiceError("Matn 5000 belgidan uzun")
        out = Path(out_path) if out_path else Path(self.core.settings.allowed_write_dirs[0]) / "exports" / f"ovoz_{datetime.now():%Y%m%d_%H%M%S_%f}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="jarvis_tts_")) / "matn.txt"
        tmp.write_text(text, encoding="utf-8")
        try:
            espeak = shutil.which("espeak-ng") or shutil.which("espeak")
            if espeak:
                p = subprocess.run([espeak, "-v", "uz", "-s", str(max(80, min(speed, 300))), "-f", str(tmp), "-w", str(out)],
                                   capture_output=True, text=True, timeout=120)
                if p.returncode != 0 or not out.exists():
                    raise VoiceError(f"espeak-ng xatosi: {p.stderr.strip()[-300:]}")
                engine = "espeak-ng (uz)"
            elif os.name == "nt":
                if not allow_other_language:
                    raise VoiceError("O'zbekcha TTS dvigateli topilmadi. espeak-ng o'rnating yoki boshqa til ovoziga ruxsat bering.")
                q = lambda x: str(x).replace("'", "''")  # noqa: E731 — PowerShell qator ekranlash
                ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                      f"$s.SetOutputToWaveFile('{q(out)}'); $s.Speak([IO.File]::ReadAllText('{q(tmp)}')); $s.Dispose()")
                p = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120)
                if p.returncode != 0 or not out.exists():
                    raise VoiceError(f"Windows TTS xatosi: {p.stderr.strip()[-300:]}")
                engine = "windows_sapi (o'zbekcha emas)"
            else:
                raise VoiceError("TTS dvigateli topilmadi: espeak-ng o'rnating")
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)
        self.core.audit.log("voice_agent", f"TTS: {len(text)} belgi", target=out.name, risk="B", result=engine)
        return {"output": str(out), "engine": engine, "chars": len(text)}

    def status(self) -> dict:
        has_fw = importlib.util.find_spec("faster_whisper") is not None
        return {"tts": self.tts_engines(),
            "engines": [
                {"id": "browser", "stt": True, "tts": True, "offline": False, "uzbek": "STT: ha (uz-UZ); TTS: OS ovoziga bog'liq",
                 "privacy": "Ovoz brauzer provayderiga yuboriladi"},
                {"id": "whisper", "stt": True, "tts": False, "offline": True, "installed": has_fw,
                 "models_mb": WHISPER_MODELS, "uzbek": "small/medium modelda o'rtacha-yaxshi",
                 "loaded_model": self._model_name},
            ],
            "save_recordings": self.core.settings.save_voice_recordings,
            "recordings_dir": str(self.recordings_dir),
        }

    @property
    def recordings_dir(self) -> Path:
        return Path(self.core.settings.allowed_write_dirs[0]) / "voice"

    def save_recording(self, data: bytes, ext: str = "webm") -> str:
        if not self.core.settings.save_voice_recordings:
            raise VoiceError("Ovoz yozuvlarini saqlash o'chirilgan (Sozlamalar)")
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        p = self.recordings_dir / f"yozuv_{datetime.now():%Y%m%d_%H%M%S}.{ext}"
        p.write_bytes(data)
        self.core.audit.log("voice_agent", "Ovoz yozuvi saqlandi", target=p.name, risk="B")
        return str(p)

    def load_whisper(self, model: str = "small") -> dict:
        if model not in WHISPER_MODELS:
            raise VoiceError(f"Model: {list(WHISPER_MODELS)}")
        if importlib.util.find_spec("faster_whisper") is None:
            raise VoiceError("faster-whisper o'rnatilmagan: pip install faster-whisper "
                             f"(so'ng '{model}' modeli ≈{WHISPER_MODELS[model]} MB yuklanadi)")
        from faster_whisper import WhisperModel
        self._model = WhisperModel(model, device="auto", compute_type="int8")
        self._model_name = model
        self.core.audit.log("voice_agent", f"Whisper modeli yuklandi: {model}", target="local", risk="C",
                            approval_status="user_action")
        return self.status()

    def transcribe(self, audio_path: str, language: str = "uz") -> dict:
        if self._model is None:
            raise VoiceError("Mahalliy STT modeli yuklanmagan. Voice bo'limida Whisper modelini yuklang (hajmi oldindan ko'rsatiladi).")
        segments, info = self._model.transcribe(audio_path, language=language, vad_filter=True)
        segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments if s.text.strip()]
        return {"text": " ".join(x["text"] for x in segs), "segments": segs, "language": info.language,
                "probability": round(info.language_probability, 2), "model": self._model_name}
