"""Maxfiy kalitlar: Windows'da Windows Credential Manager (keyring orqali), boshqa OS'da tizim keyring'i.
Kalitlar hech qachon SQLite, loglar, settings.json yoki Git'ga yozilmaydi."""
from __future__ import annotations

import os

SERVICE = "JARVIS_AI_BRAIN"


def get_secret(name: str) -> str | None:
    env = os.environ.get(f"JARVIS_{name.upper()}")
    if env:
        return env
    try:
        import keyring
        return keyring.get_password(SERVICE, name)
    except Exception:  # keyring backend mavjud bo'lmasligi mumkin (masalan, bulut konteyneri)
        return None


def has_secret(name: str) -> bool:
    return bool(get_secret(name))
