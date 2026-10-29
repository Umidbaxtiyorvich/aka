"""Sozlamalar. Hech qanday lokal disk yo'li (masalan D:\\) majburiy emas.

Ma'lumotlar papkasi JARVIS_HOME muhit o'zgaruvchisi orqali belgilanadi;
berilmasa, loyiha ichidagi ``data/`` ishlatiladi (u .gitignore'da).
Maxfiy kalitlar bu yerda SAQLANMAYDI — ular secrets.py orqali olinadi.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Foydalanuvchi o'zgartira olmaydigan (va JARVIS o'zi o'zgartira olmaydigan) kalitlar.
LOCKED_KEYS = {"read_only_mode", "require_approval", "allowed_read_dirs", "allowed_write_dirs"}


def jarvis_home() -> Path:
    home = Path(os.environ.get("JARVIS_HOME", PROJECT_ROOT / "data")).resolve()
    home.mkdir(parents=True, exist_ok=True)
    return home


@dataclass
class Settings:
    ai_provider: str = "offline"          # offline | ollama
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:1.5b"    # 8 GB RAM uchun yengil boshlang'ich tanlov
    ai_timeout_sec: int = 60
    language: str = "uz"
    read_only_mode: bool = True           # boshida faqat o'qish/demo
    require_approval: bool = True
    allowed_read_dirs: list[str] = field(default_factory=list)
    allowed_write_dirs: list[str] = field(default_factory=list)

    @classmethod
    def path(cls) -> Path:
        return jarvis_home() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        p = cls.path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        if not s.allowed_read_dirs:
            s.allowed_read_dirs = [str(jarvis_home() / "workspace")]
        if not s.allowed_write_dirs:
            s.allowed_write_dirs = [str(jarvis_home() / "workspace")]
        for d in s.allowed_write_dirs:
            Path(d).mkdir(parents=True, exist_ok=True)
        return s

    def save(self) -> None:
        self.path().write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    def public(self) -> dict:
        return asdict(self)
