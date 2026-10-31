"""Credential Vault — ulanishlar uchun login, parol, token va brauzer sessiyalari.

* Qisqa maxfiy qiymatlar (parol, API kalit, token) — OS kalitlar omborida (Windows: Credential Manager, DPAPI bilan
  shifrlangan). Nomi: `conn<ID>.<maydon>`. Qiymat hech qachon API orqali qaytarilmaydi.
* Katta maxfiy ma'lumotlar (brauzer cookie / storage state) — `JARVIS_HOME/vault/*.bin` fayllarida Fernet (AES-128-CBC +
  HMAC) bilan shifrlangan; kalit OS kalitlar omborida saqlanadi. Fayllar Git'ga ham, zaxira nusxaga ham kirmaydi.
* O'qilgan har bir qiymat `security.register_secret` orqali loglar va xatolarda avtomatik yashiriladi.
* Qiymatlar AI provayderlariga (promptlarga) hech qachon qo'shilmaydi — ular faqat adapter ichida ishlatiladi.
"""
from __future__ import annotations

import re

from ..config import jarvis_home
from ..security import register_secret

SERVICE = "JARVIS_AI_BRAIN"
FIELDS = {"username", "password", "api_key", "token", "client_secret", "db_password", "mcp_token", "refresh_token", "webhook_secret"}


class VaultError(Exception):
    pass


def _kr():
    try:
        import keyring
        keyring.get_keyring()
        return keyring
    except Exception as e:
        raise VaultError(f"Kalitlar ombori (Credential Manager) mavjud emas: {type(e).__name__}") from None


class Vault:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript("""
        CREATE TABLE IF NOT EXISTS vault_index (conn_id INTEGER NOT NULL, field TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY(conn_id, field));
        """)

    @staticmethod
    def _name(cid: int, field: str) -> str:
        if field not in FIELDS and not re.fullmatch(r"f_[a-z0-9_]{1,30}", field):      # f_* — saytdan aniqlangan kirish maydonlari
            raise VaultError(f"Ruxsat etilmagan maxfiy maydon: {field}")
        return f"conn{int(cid)}.{field}"

    def set(self, cid: int, field: str, value: str) -> None:
        value = (value or "").strip("\n")
        if not value:
            raise VaultError("Bo'sh qiymat saqlanmaydi")
        if len(value) > 4096:
            raise VaultError("Qiymat juda uzun")
        _kr().set_password(SERVICE, self._name(cid, field), value)
        register_secret(value)
        self.core.db.execute("INSERT OR REPLACE INTO vault_index(conn_id, field, updated_at) VALUES (?,?,datetime('now'))", (cid, field))
        self.core.audit.log("vault", f"Maxfiy maydon saqlandi: ulanish #{cid}.{field}", target=f"conn#{cid}", risk="C",
                            approval_status="user_action")

    def get(self, cid: int, field: str) -> str | None:
        import os
        env = os.environ.get(f"JARVIS_CONN{int(cid)}_{field.upper()}")        # faqat testlar va CI uchun
        if env:
            register_secret(env)
            return env
        try:
            v = _kr().get_password(SERVICE, self._name(cid, field))
        except VaultError:
            return None
        register_secret(v)
        return v

    def has(self, cid: int, field: str) -> bool:
        return bool(self.get(cid, field))

    def fields(self, cid: int) -> list[dict]:
        return self.core.db.query("SELECT field, updated_at FROM vault_index WHERE conn_id=? ORDER BY field", (cid,))

    def delete(self, cid: int, field: str) -> None:
        try:
            _kr().delete_password(SERVICE, self._name(cid, field))
        except Exception:
            pass
        self.core.db.execute("DELETE FROM vault_index WHERE conn_id=? AND field=?", (cid, field))

    def delete_all(self, cid: int) -> None:
        for f in [r["field"] for r in self.fields(cid)]:
            self.delete(cid, f)
        p = self._blob_path(cid, "session")
        if p.exists():
            p.unlink()

    # --- shifrlangan katta ma'lumot (brauzer sessiyasi) ---
    def _fernet(self):
        from cryptography.fernet import Fernet
        kr = _kr()
        key = kr.get_password(SERVICE, "vault.master_key")
        if not key:
            key = Fernet.generate_key().decode()
            kr.set_password(SERVICE, "vault.master_key", key)
        return Fernet(key.encode())

    @staticmethod
    def _blob_path(cid: int, name: str):
        if not re.fullmatch(r"[a-z_]{1,30}", name):
            raise VaultError("Noto'g'ri blob nomi")
        d = jarvis_home() / "vault"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"conn{int(cid)}_{name}.bin"

    def put_blob(self, cid: int, name: str, data: bytes) -> None:
        self._blob_path(cid, name).write_bytes(self._fernet().encrypt(data))

    def get_blob(self, cid: int, name: str) -> bytes | None:
        p = self._blob_path(cid, name)
        if not p.exists():
            return None
        try:
            return self._fernet().decrypt(p.read_bytes())
        except Exception:
            return None                       # kalit almashgan yoki fayl buzilgan — sessiya yo'q deb hisoblanadi
