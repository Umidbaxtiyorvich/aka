"""Audit Engine: har bir muhim amal jurnali. Matnlar yozishdan oldin redact() qilinadi."""
from __future__ import annotations

from .db import Database
from .security import redact


class Audit:
    def __init__(self, db: Database):
        self.db = db

    def log(self, agent: str, action: str, *, target: str = "", risk: str = "A",
            approval_status: str = "not_required", result: str = "", error_code: str = "",
            error_note: str = "", verified: str = "not_checked") -> int:
        cur = self.db.execute(
            "INSERT INTO audit_log(agent, action, target, risk, approval_status, result, error_code, error_note, verified)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (agent, redact(action), redact(target), risk, approval_status, redact(result)[:2000],
             error_code, redact(error_note)[:500], verified),
        )
        return cur.lastrowid

    def error(self, module: str, message: str) -> None:
        self.db.execute("INSERT INTO errors(module, message) VALUES (?,?)", (module, redact(message)[:1000]))

    def recent(self, limit: int = 50) -> list[dict]:
        return self.db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))

    def recent_errors(self, limit: int = 20) -> list[dict]:
        return self.db.query("SELECT * FROM errors ORDER BY id DESC LIMIT ?", (limit,))
