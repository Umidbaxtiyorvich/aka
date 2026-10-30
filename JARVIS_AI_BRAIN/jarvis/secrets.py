"""Maxfiy kalitlar: Windows'da Windows Credential Manager (keyring orqali), boshqa OS'da tizim keyring'i.
Kalitlar hech qachon SQLite, loglar, settings.json yoki Git'ga yozilmaydi."""
from __future__ import annotations

import os
import re

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


# Dashboard orqali kiritish mumkin bo'lgan kalit nomlari (faqat shular). Qiymat hech qachon qaytarilmaydi.
ALLOWED = re.compile(r"^(telegram_bot_token|pos_api_token|twilio_auth_token|instagram_token_[a-z0-9_]{1,40}|ai_key_[a-z0-9_-]{1,40})$")


class SecretError(ValueError):
    pass


def _check(name: str) -> str:
    name = (name or "").strip()
    if not ALLOWED.match(name):
        raise SecretError(f"Bu nomdagi kalitni dashboard orqali kiritib bo'lmaydi: {name!r}")
    return name


def set_secret(name: str, value: str) -> None:
    name = _check(name)
    value = (value or "").strip()
    if not value or len(value) > 4096:
        raise SecretError("Qiymat bo'sh yoki juda uzun")
    try:
        import keyring
        keyring.set_password(SERVICE, name, value)
    except Exception as e:  # keyring backend yo'q
        raise SecretError(f"Kalitlar ombori (Credential Manager) mavjud emas: {type(e).__name__}") from None


def delete_secret(name: str) -> None:
    name = _check(name)
    try:
        import keyring
        keyring.delete_password(SERVICE, name)
    except Exception:
        pass
