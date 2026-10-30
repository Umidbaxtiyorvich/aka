"""Memory Connection Engine — yangi ma'lumotni mavjud xotira bilan bog'lash.

Yangi ma'lumot kelganda:
  1. turini aniqlaydi (texnik / loyiha / afzallik / epizod / semantik / qisqa muddatli ...);
  2. o'xshash xotiralarni topadi (FTS5 + so'zlar va raqamlar o'xshashligi, Jaccard);
  3. tegishli loyihalarni aniqlaydi (mavjud loyiha nomlari matnda bo'lsa);
  4. takrorni aniqlaydi (o'xshashlik ≥ 0.9 va bir xil tur — yangi yozuv yaratilmaydi, mavjudi qaytariladi);
  5. aloqalarni: o'xshashlik ≥ 0.6 — avtomatik "bog'liq" aloqa; 0.3–0.6 — foydalanuvchi tasdig'i uchun taklif;
  6. manba va vaqtni xotiraning o'zida saqlaydi (memory.add), grafga tugun va aloqalarni qo'shadi.
Zid ma'lumotlar birlashtirilmaydi — memory.find_conflicts ularni "conflict" deb belgilaydi va ko'rsatadi.
"""
from __future__ import annotations

import re

from .memory import _numbers, _words

DUPLICATE = 0.9
AUTO_LINK = 0.6
SUGGEST = 0.3

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_link_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, src INTEGER NOT NULL, dst INTEGER NOT NULL, score REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(src, dst)
);
"""
TYPE_RULES = [
    ("technical", r"(?i)\b(python|api|sql|json|http|server|kod|funksiya|xato|error|bug|git|docker|config|port|endpoint|\.py|\.js)\b"),
    ("preference", r"(?i)\b(yoqtiraman|afzal|men uchun|doim|har doim|xohlayman|istayman|prefer|menga yoqadi|sevaman)\b"),
    ("episodic", r"(?i)\b(bugun|kecha|ertaga|o'tgan hafta|soat \d|uchrashuv|bo'ldi|qildim|bordim|keldi|\d{1,2}[./]\d{1,2}[./]\d{2,4})\b"),
    ("short_term", r"(?i)\b(hozir|vaqtincha|shu kun|keyinroq eslat|bir soatdan)\b"),
]


def similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    j = len(wa & wb) / len(wa | wb)
    na, nb = _numbers(a), _numbers(b)
    if na and nb and na != nb:
        j *= 0.85                              # raqamlari farq qiladi — "bir xil" emas (zid bo'lishi mumkin)
    return round(j, 3)


class MemoryConnector:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)

    def guess_kind(self, text: str, project: str | None = None) -> str:
        if project or self._projects_in(text):
            return "project"
        for kind, rx in TYPE_RULES:
            if re.search(rx, text):
                return kind
        return "semantic" if len(_words(text)) >= 4 else "long_term"

    def _projects_in(self, text: str) -> list[str]:
        names = [r["project"] for r in self.core.db.query("SELECT DISTINCT project FROM memories WHERE project IS NOT NULL AND project<>''")]
        low = text.lower()
        return [p for p in names if p and re.search(rf"(?<!\w){re.escape(p.lower())}(?!\w)", low)]

    def similar(self, text: str, exclude: int | None = None, limit: int = 10) -> list[dict]:
        words = sorted(_words(text))[:10]
        if not words:
            return []
        cands = self.core.memory.search(" OR ".join(words), limit=40)
        out = []
        for m in cands:
            if m["id"] == exclude:
                continue
            s = similarity(text, m["content"])
            if s >= SUGGEST:
                out.append({"id": m["id"], "kind": m["kind"], "content": m["content"][:200], "score": s, "status": m["status"]})
        return sorted(out, key=lambda x: -x["score"])[:limit]

    def analyze(self, text: str, project: str | None = None) -> dict:
        """Saqlashdan OLDIN ko'rish: nima bo'ladi (hech narsa yozilmaydi)."""
        kind = self.guess_kind(text, project)
        sims = self.similar(text)
        dup = next((s for s in sims if s["score"] >= DUPLICATE), None)
        return {"kind": kind, "projects": ([project] if project else []) + self._projects_in(text), "similar": sims,
                "duplicate_of": dup["id"] if dup else None,
                "auto_links": [s["id"] for s in sims if AUTO_LINK <= s["score"] < DUPLICATE],
                "suggested_links": [s["id"] for s in sims if SUGGEST <= s["score"] < AUTO_LINK],
                "conflicts": [c["id"] for c in self.core.memory.find_conflicts(text)]}

    def ingest(self, text: str, *, kind: str | None = None, project: str | None = None, source: str = "user",
               allow_duplicate: bool = False, **kw) -> dict:
        a = self.analyze(text, project)
        if a["duplicate_of"] and not allow_duplicate:
            existing = self.core.memory.get(a["duplicate_of"])
            return {"memory": existing, "duplicate": True, "analysis": a,
                    "note": f"Bu ma'lumot xotirada allaqachon bor (#{existing['id']}) — takror yozilmadi."}
        proj = project or (a["projects"][0] if a["projects"] else None)
        m = self.core.memory.add(text, kind or a["kind"], project=proj, source=source, **kw)
        kg = self.core.kgraph
        for dst in a["auto_links"]:
            kg.link(("memory", m["id"], None), "related_to", ("memory", dst, None))
            self.core.db.execute("INSERT OR IGNORE INTO memory_link_suggestions(src, dst, score, status) VALUES (?,?,?,'auto')",
                                 (m["id"], dst, next(s["score"] for s in a["similar"] if s["id"] == dst)))
        for dst in a["suggested_links"]:
            self.core.db.execute("INSERT OR IGNORE INTO memory_link_suggestions(src, dst, score) VALUES (?,?,?)",
                                 (m["id"], dst, next(s["score"] for s in a["similar"] if s["id"] == dst)))
        return {"memory": m, "duplicate": False, "analysis": a}

    # --- takliflar (foydalanuvchi tasdig'i) ---
    def suggestions(self, status: str = "pending") -> list[dict]:
        return self.core.db.query(
            "SELECT s.*, a.content AS src_content, b.content AS dst_content FROM memory_link_suggestions s"
            " JOIN memories a ON a.id=s.src JOIN memories b ON b.id=s.dst WHERE s.status=? ORDER BY s.score DESC LIMIT 200", (status,))

    def decide(self, sid: int, accept: bool) -> dict:
        s = self.core.db.one("SELECT * FROM memory_link_suggestions WHERE id=?", (sid,))
        if not s or s["status"] != "pending":
            raise ValueError("Taklif topilmadi yoki allaqachon hal qilingan")
        if accept:
            self.core.kgraph.link(("memory", s["src"], None), "related_to", ("memory", s["dst"], None))
        self.core.db.execute("UPDATE memory_link_suggestions SET status=? WHERE id=?", ("accepted" if accept else "rejected", sid))
        self.core.audit.log("user", f"Xotira aloqasi {'qabul qilindi' if accept else 'rad etildi'}: #{s['src']}↔#{s['dst']}",
                            target="memory", risk="A", approval_status="user_action")
        return self.core.db.one("SELECT * FROM memory_link_suggestions WHERE id=?", (sid,))

    def related(self, mid: int) -> list[dict]:
        """Bog'langan xotiralar: grafdagi aloqalar + yuqori o'xshashlik."""
        kg = self.core.kgraph
        out = {}
        try:
            n = kg.find("memory", mid)
            for x in kg.neighbors(n["id"])["nodes"]:
                if x["type"] == "memory" and str(x["ref"]) != str(mid):
                    out[int(x["ref"])] = {"id": int(x["ref"]), "label": x["label"], "via": "graf"}
        except Exception:
            pass
        m = self.core.memory.get(mid)
        for s in self.similar(m["content"], exclude=mid, limit=5):
            out.setdefault(s["id"], {"id": s["id"], "label": s["content"][:80], "via": f"o'xshash {s['score']:.0%}"})
        return list(out.values())

    def duplicates(self, limit: int = 500) -> list[dict]:
        """Mavjud xotiralar orasidagi takrorlar (o'xshashlik ≥ 0.9) — o'chirish faqat foydalanuvchi qaroriga ko'ra."""
        rows = self.core.memory.list(limit=limit)
        seen, out = set(), []
        for m in rows:
            if m["id"] in seen:
                continue
            for s in self.similar(m["content"], exclude=m["id"]):
                if s["score"] >= DUPLICATE and s["id"] not in seen:
                    out.append({"keep": min(m["id"], s["id"]), "duplicate": max(m["id"], s["id"]), "score": s["score"],
                                "content": m["content"][:160]})
                    seen.add(max(m["id"], s["id"]))
        return out
