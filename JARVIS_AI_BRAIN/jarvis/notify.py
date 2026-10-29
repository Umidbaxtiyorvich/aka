"""Monitoring va bildirishnomalar: dashboard (har doim) + Telegram (sozlangan bo'lsa, warning va undan yuqori)."""
from __future__ import annotations

from .db import Database
from .security import redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')),
    severity TEXT NOT NULL, category TEXT NOT NULL, title TEXT NOT NULL, body TEXT,
    read INTEGER NOT NULL DEFAULT 0, delivered TEXT NOT NULL DEFAULT 'dashboard'
);
"""
SEVERITIES = ("info", "warning", "critical")


class Notifier:
    def __init__(self, db: Database, settings):
        self.db, self.settings = db, settings
        self.telegram = None     # core.telegram ulanganda o'rnatiladi
        db.conn.executescript(SCHEMA)

    def notify(self, title: str, body: str = "", *, severity: str = "info", category: str = "system") -> dict:
        if severity not in SEVERITIES:
            severity = "info"
        title, body = redact(title)[:200], redact(body)[:2000]
        delivered = "dashboard"
        if self.telegram and self.settings.telegram_notify and severity != "info" and self.telegram.configured():
            sent = self.telegram.broadcast(f"{'🔴' if severity == 'critical' else '🟡'} {title}\n{body}")
            if sent:
                delivered = f"dashboard+telegram({sent})"
        cur = self.db.execute("INSERT INTO notifications(severity, category, title, body, delivered) VALUES (?,?,?,?,?)",
                              (severity, category, title, body, delivered))
        return self.db.one("SELECT * FROM notifications WHERE id=?", (cur.lastrowid,))

    def list(self, unread_only: bool = False, limit: int = 100) -> list[dict]:
        return self.db.query("SELECT * FROM notifications" + (" WHERE read=0" if unread_only else "") +
                             " ORDER BY id DESC LIMIT ?", (limit,))

    def mark_read(self, nid: int | None = None) -> None:
        if nid is None:
            self.db.execute("UPDATE notifications SET read=1")
        else:
            self.db.execute("UPDATE notifications SET read=1 WHERE id=?", (nid,))
