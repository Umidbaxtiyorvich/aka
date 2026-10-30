"""Monitoring va bildirishnomalar: dashboard (har doim) + Telegram (egasi ulangan va hodisa turi yoqilgan bo'lsa)."""
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
        self.telephony = None    # qo'ng'iroq qoidalari (faqat reja + tasdiq)
        db.conn.executescript(SCHEMA)

    def notify(self, title: str, body: str = "", *, severity: str = "info", category: str = "system") -> dict:
        if severity not in SEVERITIES:
            severity = "info"
        title, body = redact(title)[:200], redact(body)[:2000]
        delivered = "dashboard"
        if self.telegram and self.telegram.event(category, title, body, severity):
            delivered = "dashboard+telegram(1)"
        cur = self.db.execute("INSERT INTO notifications(severity, category, title, body, delivered) VALUES (?,?,?,?,?)",
                              (severity, category, title, body, delivered))
        row = self.db.one("SELECT * FROM notifications WHERE id=?", (cur.lastrowid,))
        if self.telephony and severity == "critical" and category != "telephony":
            appr = self.telephony.on_notification(row)
            if appr:
                self.db.execute("INSERT INTO notifications(severity, category, title, body) VALUES (?,?,?,?)",
                                ("warning", "telephony", "Qo'ng'iroq rejasi tasdiq kutmoqda", f"Tasdiq #{appr['id']}: {appr['summary'][:200]}"))
        return row

    def list(self, unread_only: bool = False, limit: int = 100) -> list[dict]:
        return self.db.query("SELECT * FROM notifications" + (" WHERE read=0" if unread_only else "") +
                             " ORDER BY id DESC LIMIT ?", (limit,))

    def mark_read(self, nid: int | None = None) -> None:
        if nid is None:
            self.db.execute("UPDATE notifications SET read=1")
        else:
            self.db.execute("UPDATE notifications SET read=1 WHERE id=?", (nid,))
