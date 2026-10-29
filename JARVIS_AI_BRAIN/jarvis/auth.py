"""Dashboard himoyasi: PIN, sessiya, urinishlarni cheklash.

* PIN ochiq saqlanmaydi: PBKDF2-HMAC-SHA256 (200 000 iteratsiya) + tasodifiy salt → JARVIS_HOME/auth.json.
* Birinchi kirishda PIN o'rnatiladi (faqat PIN hali yo'q bo'lsa va so'rov shu kompyuterdan kelsa).
* Sessiya: tasodifiy token, HttpOnly + SameSite=Strict cookie, `session_hours` dan keyin tugaydi.
* 5 ta noto'g'ri urinish → bloklash (5 daqiqa, har safar ikki baravar, maksimum 1 soat).
* PIN almashtirilsa, barcha sessiyalar bekor qilinadi. PIN unutilsa: `python scripts/reset_pin.py` (kompyuterda).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime, timezone

from .config import jarvis_home

ITERATIONS = 200_000
WEAK = {"123456", "1234567", "12345678", "654321", "000000", "111111", "123123", "password", "parol123", "qwerty"}


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


def _hash(pin: str, salt: bytes, iterations: int = ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations).hex()


def validate_pin(pin: str) -> None:
    if not isinstance(pin, str) or not (6 <= len(pin) <= 64):
        raise AuthError("PIN 6–64 belgidan iborat bo'lishi kerak", 400)
    if pin.lower() in WEAK or len(set(pin)) == 1:
        raise AuthError("Bu PIN juda oson — boshqasini tanlang", 400)
    if pin.isdigit() and (pin in "01234567890123456789" or pin in "98765432109876543210"):
        raise AuthError("Ketma-ket raqamlardan iborat PIN mumkin emas", 400)


class AuthManager:
    def __init__(self, core):
        self.core = core
        self._sessions: dict[str, float] = {}
        self._fails: dict[str, dict] = {}
        self._lock = threading.Lock()

    @property
    def path(self):
        return jarvis_home() / "auth.json"

    def has_pin(self) -> bool:
        return self.path.exists()

    def _load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _store(self, pin: str):
        salt = secrets.token_bytes(16)
        data = {"salt": salt.hex(), "hash": _hash(pin, salt), "iterations": ITERATIONS,
                "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def _verify(self, pin: str) -> bool:
        d = self._load()
        return hmac.compare_digest(_hash(pin, bytes.fromhex(d["salt"]), d["iterations"]), d["hash"])

    # --- urinishlarni cheklash ---
    def _check_lock(self, client: str):
        f = self._fails.get(client)
        if f and f["locked_until"] > time.time():
            raise AuthError(f"Juda ko'p noto'g'ri urinish. {int(f['locked_until'] - time.time()) + 1} soniyadan keyin qayta urinib ko'ring", 429)

    def _register_fail(self, client: str):
        f = self._fails.setdefault(client, {"count": 0, "locked_until": 0, "lock_s": 300})
        f["count"] += 1
        if f["count"] >= 5:
            f["locked_until"] = time.time() + f["lock_s"]
            f["lock_s"] = min(f["lock_s"] * 2, 3600)
            f["count"] = 0
            self.core.notifier.notify("Dashboard: ko'p noto'g'ri PIN urinishi", f"Manba: {client}. Kirish vaqtincha bloklandi.",
                                      severity="warning", category="security")

    # --- amallar ---
    def setup(self, pin: str, client: str) -> str:
        with self._lock:
            if self.has_pin():
                raise AuthError("PIN allaqachon o'rnatilgan", 409)
            if client not in ("127.0.0.1", "::1", "localhost", "testclient"):
                raise AuthError("PIN faqat shu kompyuterning o'zidan o'rnatiladi", 403)
            validate_pin(pin)
            self._store(pin)
        self.core.audit.log("auth", "Dashboard PIN o'rnatildi", target="dashboard", risk="C", approval_status="user_action")
        return self._new_session()

    def login(self, pin: str, client: str) -> str:
        with self._lock:
            self._check_lock(client)
            if not self.has_pin():
                raise AuthError("PIN hali o'rnatilmagan", 409)
            if not self._verify(pin or ""):
                self._register_fail(client)
                self.core.audit.log("auth", "Noto'g'ri PIN", target=f"client:{client}", risk="A", approval_status="denied")
                raise AuthError("PIN noto'g'ri")
            self._fails.pop(client, None)
        self.core.audit.log("auth", "Dashboardga kirildi", target=f"client:{client}", risk="A")
        return self._new_session()

    def change(self, current: str, new: str, client: str) -> str:
        with self._lock:
            self._check_lock(client)
            if not self._verify(current or ""):
                self._register_fail(client)
                raise AuthError("Joriy PIN noto'g'ri")
            validate_pin(new)
            self._store(new)
            self._sessions.clear()
        self.core.audit.log("auth", "Dashboard PIN almashtirildi, barcha sessiyalar bekor qilindi", target="dashboard", risk="C",
                            approval_status="user_action")
        return self._new_session()

    def _new_session(self) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = time.time() + self.core.settings.session_hours * 3600
        return token

    def check(self, token: str | None) -> bool:
        if not token:
            return False
        exp = self._sessions.get(token)
        if exp is None:
            return False
        if exp < time.time():
            self._sessions.pop(token, None)
            return False
        return True

    def logout(self, token: str | None):
        self._sessions.pop(token or "", None)

    def status(self, token: str | None) -> dict:
        return {"enabled": self.core.settings.auth_enabled, "pin_set": self.has_pin(), "authenticated": self.check(token)}
