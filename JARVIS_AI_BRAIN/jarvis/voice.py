"""Voice Engine.

Dvigatellar (siz tanlaysiz):
* browser — brauzerning Web Speech API (Chrome/Edge). uz-UZ ni qo'llaydi, lekin ovoz Google/Microsoft
  serverlariga yuboriladi: internet kerak, maxfiylik — ularning siyosati. TTS ovozi brauzer/OS'ga bog'liq:
  Windows'da o'zbekcha TTS ovozi odatda YO'Q — bunda matn ko'rsatiladi yoki boshqa til ovozi ishlatiladi.
* whisper — mahalliy faster-whisper (internet kerak emas). Ixtiyoriy: `pip install faster-whisper`,
  model hajmi: tiny ≈75 MB, base ≈145 MB, small ≈480 MB, medium ≈1.5 GB. O'zbek tili sifati: tiny/base past,
  small o'rtacha, medium yaxshiroq (8 GB RAMda sekin). Model faqat siz ruxsat berganda yuklanadi.
Mikrofon faqat dashboarddagi tugma bilan yoqiladi va holati doimo ko'rinadi. Yashirin tinglash yo'q.
Ovoz yozuvlari faqat `save_voice_recordings` yoqilganda saqlanadi.
"""
from __future__ import annotations

import importlib.util
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

    def status(self) -> dict:
        has_fw = importlib.util.find_spec("faster_whisper") is not None
        return {
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

    def transcribe(self, audio_path: str) -> dict:
        if self._model is None:
            raise VoiceError("Mahalliy STT modeli yuklanmagan. Sozlamalar → Voice → Whisper modelini yuklash.")
        segments, info = self._model.transcribe(audio_path, language="uz", vad_filter=True)
        text = " ".join(s.text.strip() for s in segments)
        return {"text": text, "language": info.language, "probability": round(info.language_probability, 2)}
