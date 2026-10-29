"""Memory Engine: tuzilgan doimiy xotira (SQLite + FTS5 qidiruv)."""
from __future__ import annotations

import json
import re

from .audit import Audit
from .db import Database
from .security import contains_secret

KINDS = {"short_term", "long_term", "project", "knowledge", "task", "preference", "decision", "conversation"}
NEGATIONS = ("emas", "yo'q", "yoq", "not", "never", "hech qachon")


class MemoryError_(Exception):
    pass


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[\w'’]+", text.lower()) if len(w) > 3}


class Memory:
    def __init__(self, db: Database, audit: Audit):
        self.db, self.audit = db, audit

    def add(self, content: str, kind: str = "long_term", *, project: str | None = None,
            source: str = "user", confidence: float = 1.0) -> dict:
        if kind not in KINDS:
            raise MemoryError_(f"Noma'lum xotira turi: {kind}")
        if contains_secret(content):
            raise MemoryError_("Maxfiy ma'lumot (parol/token/kalit) oddiy xotirada saqlanmaydi.")
        conflicts = self.find_conflicts(content)
        status = "conflict" if conflicts else "active"
        cur = self.db.execute(
            "INSERT INTO memories(kind, project, content, source, confidence, status) VALUES (?,?,?,?,?,?)",
            (kind, project, content.strip(), source, max(0.0, min(1.0, confidence)), status))
        self.audit.log("memory", f"Xotiraga qo'shildi ({kind})", target=f"memory#{cur.lastrowid}", risk="B")
        row = self.get(cur.lastrowid)
        row["conflicts_with"] = [c["id"] for c in conflicts]
        return row

    def find_conflicts(self, content: str) -> list[dict]:
        """Oddiy evristika: so'zlarning ko'pi mos, lekin inkor belgisi farq qiladi.
        Avtomatik birlashtirilmaydi — foydalanuvchiga ko'rsatiladi."""
        new_w, new_neg = _words(content), any(n in content.lower() for n in NEGATIONS)
        if len(new_w) < 2:
            return []
        out = []
        for m in self.search(" OR ".join(sorted(new_w)[:8]), limit=20):
            w = _words(m["content"])
            overlap = len(new_w & w) / max(1, len(new_w | w))
            if overlap >= 0.5 and new_neg != any(n in m["content"].lower() for n in NEGATIONS):
                out.append(m)
        return out

    def get(self, mid: int) -> dict:
        row = self.db.one("SELECT * FROM memories WHERE id=?", (mid,))
        if not row:
            raise MemoryError_("Xotira topilmadi")
        return row

    def list(self, kind: str | None = None, project: str | None = None, limit: int = 100) -> list[dict]:
        sql, params = "SELECT * FROM memories WHERE 1=1", []
        if kind:
            sql += " AND kind=?"; params.append(kind)
        if project:
            sql += " AND project=?"; params.append(project)
        return self.db.query(sql + " ORDER BY id DESC LIMIT ?", (*params, limit))

    def search(self, query: str, limit: int = 20) -> list[dict]:
        q = query.strip()
        if not q:
            return []
        terms = [t for t in re.findall(r"[\w]+", q) if t.upper() not in {"OR", "AND", "NOT"}]
        if not terms:
            return []
        fts = " OR ".join(f'"{t}"*' for t in terms)
        return self.db.query(
            "SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.rowid WHERE memories_fts MATCH ?"
            " ORDER BY rank LIMIT ?", (fts, limit))

    def update(self, mid: int, content: str) -> dict:
        if contains_secret(content):
            raise MemoryError_("Maxfiy ma'lumot saqlanmaydi.")
        self.get(mid)
        self.db.execute("UPDATE memories SET content=?, status='active', updated_at=datetime('now') WHERE id=?",
                        (content, mid))
        self.audit.log("memory", "Xotira tahrirlandi", target=f"memory#{mid}", risk="C", approval_status="user_action")
        return self.get(mid)

    def delete(self, mid: int) -> None:
        self.get(mid)
        self.db.execute("DELETE FROM memories WHERE id=?", (mid,))
        self.audit.log("memory", "Xotira o'chirildi", target=f"memory#{mid}", risk="E", approval_status="user_action")

    def export(self) -> str:
        return json.dumps(self.db.query("SELECT * FROM memories ORDER BY id"), ensure_ascii=False, indent=2)
