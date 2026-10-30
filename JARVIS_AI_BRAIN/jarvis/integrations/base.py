"""Universal Connector interfeysi. Har bir adapter shu shartnomaga amal qiladi:

    connect() / authenticate() / health_check() / discover() / describe_schema() / fetch_data() / sync() / disconnect()

Holatlar: connected, disconnected, auth_expired, auth_failed, permission_denied, rate_limited, user_action_required,
not_supported, error, syncing. Adapter qila olmaydigan narsani "bajarildi" demaydi — NotSupported xatosini beradi.
"""
from __future__ import annotations

from urllib.parse import urlparse

STATUSES = {"new", "connected", "disconnected", "auth_expired", "auth_failed", "permission_denied", "rate_limited",
            "user_action_required", "not_supported", "error", "syncing"}
MODES = {"read_only": "Faqat o'qish", "assistant": "Yordamchi (o'zgartirish takliflari)",
         "authorized": "Ruxsatli avtomatlashtirish (har amal tasdiq bilan)"}


class ConnectorError(Exception):
    def __init__(self, message: str, status: str = "error", retry_after: float | None = None):
        super().__init__(message)
        self.status = status if status in STATUSES else "error"
        self.retry_after = retry_after


class NotSupported(ConnectorError):
    def __init__(self, message: str):
        super().__init__(message, "not_supported")


def check_url(url: str, field: str = "URL") -> str:
    """Faqat https:// yoki shu kompyuter (127.0.0.1 / localhost) — parollar shifrlanmagan kanalda yuborilmaydi."""
    url = (url or "").strip()
    u = urlparse(url)
    if u.scheme == "https" and u.hostname:
        return url.rstrip("/")
    if u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost"):
        return url.rstrip("/")
    raise ConnectorError(f"{field} https:// bo'lishi kerak (yoki shu kompyuterdagi http://127.0.0.1)", "error")


def field(key, label, type_="text", *, secret=False, required=False, help_="", options=None, default=None) -> dict:
    return {"key": key, "label": label, "type": type_, "secret": secret, "required": required, "help": help_,
            "options": options or [], "default": default}


class BaseConnector:
    kind = "base"
    title = "Base"
    protocols: list[str] = []
    FIELDS: list[dict] = []
    can_write = False

    def __init__(self, conn: dict, secret, core):
        self.conn, self.cfg, self.secret, self.core = conn, conn.get("config") or {}, secret, core
        self.cid = conn.get("id")

    # --- umumiy shartnoma ---
    def connect(self) -> dict:
        return self.health_check()

    def authenticate(self) -> dict:
        return {"status": "connected", "note": "Autentifikatsiya talab qilinmaydi"}

    def health_check(self) -> dict:
        raise NotSupported(f"{self.title}: holatni tekshirish qo'llab-quvvatlanmaydi")

    def discover(self) -> dict:
        raise NotSupported(f"{self.title}: avtomatik aniqlash qo'llab-quvvatlanmaydi")

    def describe_schema(self) -> dict:
        d = self.discover()
        return {"entities": d.get("entities", [])}

    def fetch_data(self, entity: str, *, since=None, cursor=None, limit: int = 500) -> dict:
        raise NotSupported(f"{self.title}: ma'lumot olish qo'llab-quvvatlanmaydi")

    def write(self, entity: str, operation: str, payload: dict) -> dict:
        raise NotSupported(f"{self.title}: tashqi tizimga yozish bu adapterda yo'q")

    def disconnect(self) -> dict:
        return {"status": "disconnected"}
