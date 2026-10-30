"""Memory Engine: tuzilgan doimiy xotira (SQLite + FTS5 qidiruv) + Knowledge Provenance.

Har bir yozuv: manba, sana, ma'lumot turi (fakt / taxmin / model xulosasi / foydalanuvchi ma'lumoti),
ishonch, tekshirilgan holati, havola, manba sanasi va eskirish muddati. Manbasiz yozuv "tasdiqlangan fakt"
bo'la olmaydi. Zid ma'lumotlar birlashtirilmaydi — belgilanadi va ko'rsatiladi.
"""
from __future__ import annotations

import json
import re

from .audit import Audit
from .db import Database
from .security import contains_secret

KINDS = {"short_term", "long_term", "working", "episodic", "semantic", "project", "technical", "knowledge", "task",
         "preference", "decision", "conversation"}
# Memory Explorer toifalari (preference = foydalanuvchi o'zi kiritgan/tasdiqlagan afzalliklar)
CATEGORY_LABELS = {"short_term": "Short-term Memory", "long_term": "Long-term Memory", "working": "Working Memory",
                   "episodic": "Episodic Memory", "semantic": "Semantic Memory", "project": "Project Memory",
                   "technical": "Technical Memory", "preference": "User-approved Preferences", "knowledge": "Knowledge",
                   "task": "Task Memory", "decision": "Decision Memory", "conversation": "Conversation Memory"}
INFO_TYPES = {"fact": "Fakt", "assumption": "Taxmin", "model_inference": "Model xulosasi", "user_given": "Foydalanuvchi ma'lumoti"}
STALE_DAYS = {"fact": 365, "model_inference": 90, "assumption": 30}
PROVENANCE_COLUMNS = {"info_type": "TEXT NOT NULL DEFAULT 'user_given'", "verified": "INTEGER NOT NULL DEFAULT 0",
                      "reference": "TEXT", "observed_at": "TEXT", "verified_at": "TEXT", "verified_note": "TEXT",
                      "stale_after_days": "INTEGER", "title": "TEXT"}
NEGATIONS = ("emas", "yo'q", "yoq", "not", "never", "hech qachon")


class MemoryError_(Exception):
    pass


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[^\W\d][\w'’]*", text.lower()) if len(w) > 3}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", text))


def label(m: dict) -> str:
    t = m.get("info_type") or "user_given"
    if t == "fact":
        return "Tasdiqlangan fakt" if m.get("verified") and m.get("reference") else "Tekshirilmagan fakt"
    return INFO_TYPES.get(t, t)


def default_info_type(source: str) -> str:
    s = (source or "").lower()
    if s.startswith(("http://", "https://")):
        return "fact"
    if s.startswith(("ai", "model", "router", "plugin:")):
        return "model_inference"
    return "user_given"


class Memory:
    def __init__(self, db: Database, audit: Audit):
        self.db, self.audit = db, audit
        db.ensure_columns("memories", PROVENANCE_COLUMNS)
        self.on_add = None      # Knowledge Graph ilgagi
        self.events = None      # hodisalar oqimi (3D Brain): qidiruv va qo'shish

    def add(self, content: str, kind: str = "long_term", *, project: str | None = None,
            source: str = "user", confidence: float = 1.0, info_type: str | None = None, reference: str = "",
            observed_at: str | None = None, verified: bool = False, stale_after_days: int | None = None,
            title: str | None = None) -> dict:
        if kind not in KINDS:
            raise MemoryError_(f"Noma'lum xotira turi: {kind}")
        if kind == "preference" and str(source).startswith(("ai", "model", "router", "plugin:", "http")):
            raise MemoryError_("Afzalliklar faqat foydalanuvchi tomonidan kiritiladi (User-approved Preferences).")
        if contains_secret(content):
            raise MemoryError_("Maxfiy ma'lumot (parol/token/kalit) oddiy xotirada saqlanmaydi.")
        info_type = info_type or default_info_type(source)
        if info_type not in INFO_TYPES:
            raise MemoryError_(f"Ma'lumot turi: {list(INFO_TYPES)}")
        if source.startswith(("http://", "https://")) and not reference:
            reference = source
        if verified and (info_type != "fact" or not reference.strip()):
            raise MemoryError_("Manbasiz (havolasiz) yoki fakt bo'lmagan ma'lumot 'tekshirilgan' deb belgilanmaydi.")
        conflicts = self.find_conflicts(content)
        status = "conflict" if conflicts else "active"
        cur = self.db.execute(
            "INSERT INTO memories(kind, project, content, source, confidence, status, info_type, reference, observed_at,"
            " verified, verified_at, stale_after_days, title) VALUES (?,?,?,?,?,?,?,?,?,?,CASE WHEN ? THEN datetime('now') END,?,?)",
            (kind, project, content.strip(), source, max(0.0, min(1.0, confidence)), status, info_type, reference or None,
             observed_at, int(verified), int(verified), stale_after_days, (title or "").strip()[:120] or None))
        self.audit.log("memory", f"Xotiraga qo'shildi ({kind})", target=f"memory#{cur.lastrowid}", risk="B")
        row = self.get(cur.lastrowid)
        if self.on_add:
            try:
                self.on_add(row)
            except Exception as e:  # graf xatosi xotirani buzmasin
                self.audit.error("kgraph", str(e))
        row["conflicts_with"] = [c["id"] for c in conflicts]
        if self.events:
            self.events.publish("memory.add", id=row["id"], kind=kind, conflict=bool(conflicts))
        return row

    def find_conflicts(self, content: str) -> list[dict]:
        """Oddiy evristika: so'zlarning ko'pi mos, lekin inkor belgisi farq qiladi.
        Avtomatik birlashtirilmaydi — foydalanuvchiga ko'rsatiladi."""
        new_w, new_neg = _words(content), any(n in content.lower() for n in NEGATIONS)
        if len(new_w) < 2:
            return []
        out, new_num = [], _numbers(content)
        for m in self.search(" OR ".join(sorted(new_w)[:8]), limit=20):
            w = _words(m["content"])
            overlap = len(new_w & w) / max(1, len(new_w | w))
            neg_differs = new_neg != any(n in m["content"].lower() for n in NEGATIONS)
            old_num = _numbers(m["content"])
            num_differs = bool(new_num and old_num and new_num != old_num)   # "narx 5000" vs "narx 6000"
            if (overlap >= 0.5 and neg_differs) or (overlap >= 0.6 and num_differs):
                out.append(m | {"conflict_reason": "inkor farqi" if neg_differs else "raqamlar farqi"})
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
        rows = self.db.query(
            "SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.rowid WHERE memories_fts MATCH ?"
            " ORDER BY rank LIMIT ?", (fts, limit))
        if self.events:
            self.events.publish("memory.search", hits=[r["id"] for r in rows[:20]], n=len(rows))
        return rows

    def update(self, mid: int, content: str, *, title: str | None = None, kind: str | None = None) -> dict:
        if contains_secret(content):
            raise MemoryError_("Maxfiy ma'lumot saqlanmaydi.")
        self.get(mid)
        if kind is not None:
            if kind not in KINDS:
                raise MemoryError_(f"Noma'lum xotira turi: {kind}")
            self.db.execute("UPDATE memories SET kind=? WHERE id=?", (kind, mid))
        if title is not None:
            self.db.execute("UPDATE memories SET title=? WHERE id=?", (title.strip()[:120] or None, mid))
        # Mazmun o'zgarsa, oldingi tekshiruv endi amal qilmaydi
        self.db.execute("UPDATE memories SET content=?, status='active', verified=0, verified_at=NULL,"
                        " updated_at=datetime('now') WHERE id=?", (content, mid))
        self.audit.log("memory", "Xotira tahrirlandi", target=f"memory#{mid}", risk="C", approval_status="user_action")
        return self.get(mid)

    def delete(self, mid: int) -> None:
        self.get(mid)
        self.db.execute("DELETE FROM memories WHERE id=?", (mid,))
        self.audit.log("memory", "Xotira o'chirildi", target=f"memory#{mid}", risk="E", approval_status="user_action")

    # ---------- Provenance ----------
    def verify(self, mid: int, reference: str, note: str = "") -> dict:
        m = self.get(mid)
        if not reference.strip():
            raise MemoryError_("Tekshirish uchun manba havolasi yoki hujjat ko'rsatilishi shart.")
        self.db.execute("UPDATE memories SET info_type='fact', verified=1, reference=?, verified_at=datetime('now'),"
                        " verified_note=? WHERE id=?", (reference.strip(), note, mid))
        self.audit.log("memory", f"Fakt tekshirildi: memory#{mid}", target=reference[:120], risk="B",
                       approval_status="user_action", verified="user")
        return self.get(m["id"])

    def set_type(self, mid: int, info_type: str) -> dict:
        if info_type not in INFO_TYPES:
            raise MemoryError_(f"Ma'lumot turi: {list(INFO_TYPES)}")
        self.get(mid)
        self.db.execute("UPDATE memories SET info_type=?, verified=CASE WHEN ?='fact' THEN verified ELSE 0 END WHERE id=?",
                        (info_type, info_type, mid))
        return self.get(mid)

    def is_stale(self, m: dict) -> bool:
        days = m.get("stale_after_days") or STALE_DAYS.get(m.get("info_type") or "", 0)
        if not days:
            return False
        row = self.db.one("SELECT julianday('now') - julianday(?) AS age", (m.get("observed_at") or m["created_at"],))
        return bool(row and row["age"] is not None and row["age"] > days)

    def provenance(self, mid: int) -> dict:
        m = self.get(mid)
        conflicts = [c for c in self.find_conflicts(m["content"]) if c["id"] != mid]
        return {"memory": m, "label": label(m), "type": INFO_TYPES.get(m["info_type"], m["info_type"]),
                "verified": bool(m["verified"]), "reference": m["reference"], "source": m["source"],
                "recorded_at": m["created_at"], "observed_at": m["observed_at"], "confidence": m["confidence"],
                "stale": self.is_stale(m), "conflicts": [{"id": c["id"], "content": c["content"], "source": c["source"],
                                                          "label": label(c), "reason": c["conflict_reason"]} for c in conflicts]}

    def compare(self, query: str) -> dict:
        """Mavzu bo'yicha barcha yozuvlar manbalari bilan — qaror qabul qilishdan oldin solishtirish uchun."""
        hits = self.search(query, limit=30)
        rows = [{"id": h["id"], "content": h["content"], "label": label(h), "source": h["source"], "reference": h["reference"],
                 "confidence": h["confidence"], "date": h["observed_at"] or h["created_at"], "stale": self.is_stale(h),
                 "status": h["status"]} for h in hits]
        verified = [r for r in rows if r["label"] == "Tasdiqlangan fakt"]
        return {"query": query, "items": rows, "sources": sorted({r["reference"] or r["source"] for r in rows}),
                "verified_count": len(verified), "conflicts": [r for r in rows if r["status"] == "conflict"],
                "stale": [r for r in rows if r["stale"]],
                "summary": ("Tasdiqlangan manba yo'q — qaror uchun ehtiyot bo'ling" if not verified else
                            f"{len(verified)} ta tasdiqlangan fakt, {len(rows) - len(verified)} ta boshqa yozuv")}

    def stale_items(self, limit: int = 100) -> list[dict]:
        return [m | {"label": label(m)} for m in self.list(limit=1000) if self.is_stale(m)][:limit]

    def export(self) -> str:
        return json.dumps(self.db.query("SELECT * FROM memories ORDER BY id"), ensure_ascii=False, indent=2)
