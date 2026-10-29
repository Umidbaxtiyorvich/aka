"""Decision Journal — muhim qarorlar tarixi.

Tarixiy yozuvlar jimlik bilan o'zgartirilmaydi:
* Asosiy maydonlar (muammo, variantlar, tanlov, sabab, manbalar, xavflar, kutilgan natija) yaratilgandan keyin
  to'g'ridan-to'g'ri tahrirlanmaydi. O'zgartirish = yangi qaror, eskisi 'superseded' bo'ladi va ular bog'lanadi.
* Faqat "haqiqiy natija", "qayta ko'rib chiqish sanasi" va holat yangilanadi — har biri decision_events'ga
  eski va yangi qiymat bilan yoziladi.
"""
from __future__ import annotations

import json

from .security import contains_secret

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, problem TEXT NOT NULL, options TEXT NOT NULL, chosen TEXT NOT NULL,
    rationale TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]', risks TEXT, expected_outcome TEXT,
    actual_outcome TEXT, review_at TEXT, status TEXT NOT NULL DEFAULT 'active',  -- active | reviewed | superseded
    supersedes INTEGER, superseded_by INTEGER, project TEXT, files TEXT NOT NULL DEFAULT '[]',
    author TEXT NOT NULL DEFAULT 'user', created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS decision_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id INTEGER NOT NULL, ts TEXT NOT NULL DEFAULT (datetime('now')),
    field TEXT NOT NULL, old_value TEXT, new_value TEXT, note TEXT
);
"""
CORE_FIELDS = ("problem", "options", "chosen", "rationale", "sources", "risks", "expected_outcome", "files", "project")
MUTABLE = ("actual_outcome", "review_at", "status")


class DecisionError(Exception):
    pass


class DecisionJournal:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)

    def _dec(self, row: dict) -> dict:
        for k in ("options", "sources", "files"):
            row[k] = json.loads(row[k] or "[]")
        return row

    def get(self, did: int) -> dict:
        r = self.core.db.one("SELECT * FROM decisions WHERE id=?", (did,))
        if not r:
            raise DecisionError("Qaror topilmadi")
        d = self._dec(r)
        d["events"] = self.core.db.query("SELECT * FROM decision_events WHERE decision_id=? ORDER BY id", (did,))
        return d

    def create(self, *, problem: str, options: list[str], chosen: str, rationale: str, sources: list[str] | None = None,
               risks: str = "", expected_outcome: str = "", review_at: str = "", project: str = "", files: list[str] | None = None,
               author: str = "user", supersedes: int | None = None) -> dict:
        if not problem.strip() or not chosen.strip() or not rationale.strip():
            raise DecisionError("Muammo, tanlangan variant va sabab majburiy")
        if len(options) < 1 or chosen not in options:
            raise DecisionError("Tanlangan variant ko'rib chiqilgan variantlar ro'yxatida bo'lishi kerak")
        blob = json.dumps([problem, options, chosen, rationale, sources, risks, expected_outcome], ensure_ascii=False)
        if contains_secret(blob):
            raise DecisionError("Qaror matnida maxfiy ma'lumot bor — saqlanmadi")
        cur = self.core.db.execute(
            "INSERT INTO decisions(problem, options, chosen, rationale, sources, risks, expected_outcome, review_at, project,"
            " files, author, supersedes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (problem, json.dumps(options, ensure_ascii=False), chosen, rationale, json.dumps(sources or [], ensure_ascii=False),
             risks, expected_outcome, review_at or None, project or None, json.dumps(files or [], ensure_ascii=False),
             author, supersedes))
        did = cur.lastrowid
        self.core.db.execute("INSERT INTO decision_events(decision_id, field, new_value, note) VALUES (?,?,?,?)",
                             (did, "created", chosen, f"muallif: {author}"))
        self.core.audit.log(author, f"Qaror yozildi: {problem[:80]}", target=f"decision#{did}", risk="B")
        if hasattr(self.core, "kgraph"):
            self.core.kgraph.on_decision(self.get(did))
        return self.get(did)

    def update(self, did: int, *, note: str = "", **fields) -> dict:
        bad = [k for k in fields if k not in MUTABLE]
        if bad:
            raise DecisionError(f"{bad} tarixiy maydon — o'zgartirish uchun 'qayta ko'rib chiqish' (revise) ishlating")
        d = self.get(did)
        if d["status"] == "superseded" and fields:
            raise DecisionError(f"Bu qaror #{d['superseded_by']} bilan almashtirilgan — yangisini yangilang")
        if "status" in fields and fields["status"] not in ("active", "reviewed"):
            raise DecisionError("Holat: active yoki reviewed")
        for k, v in fields.items():
            if v == d[k]:
                continue
            self.core.db.execute(f"UPDATE decisions SET {k}=? WHERE id=?", (v, did))
            self.core.db.execute("INSERT INTO decision_events(decision_id, field, old_value, new_value, note) VALUES (?,?,?,?,?)",
                                 (did, k, d[k], v, note))
        return self.get(did)

    def revise(self, did: int, *, reason: str, **changes) -> dict:
        """Yangi ma'lumot asosida qayta ko'rib chiqish: yangi qaror yaratiladi, eskisi saqlanadi va bog'lanadi."""
        if not reason.strip():
            raise DecisionError("Qayta ko'rib chiqish sababi majburiy")
        old = self.get(did)
        if old["status"] == "superseded":
            raise DecisionError(f"Allaqachon #{old['superseded_by']} bilan almashtirilgan")
        base = {k: old[k] for k in CORE_FIELDS} | {"review_at": old["review_at"] or ""}
        base.update({k: v for k, v in changes.items() if k in CORE_FIELDS or k == "review_at"})
        base["rationale"] = base["rationale"] + f"\n[Qayta ko'rib chiqildi #{did}: {reason}]"
        new = self.create(**base, author=changes.get("author", "user"), supersedes=did)
        self.core.db.execute("UPDATE decisions SET status='superseded', superseded_by=? WHERE id=?", (new["id"], did))
        self.core.db.execute("INSERT INTO decision_events(decision_id, field, old_value, new_value, note) VALUES (?,?,?,?,?)",
                             (did, "status", old["status"], "superseded", f"→ #{new['id']}: {reason}"))
        return {"old": self.get(did), "new": self.get(new["id"])}

    def list(self, q: str = "", status: str = "") -> list[dict]:
        sql, params = "SELECT * FROM decisions WHERE 1=1", []
        if q:
            sql += " AND (problem LIKE ? OR chosen LIKE ? OR rationale LIKE ? OR options LIKE ?)"
            params += [f"%{q}%"] * 4
        if status:
            sql += " AND status=?"
            params.append(status)
        return [self._dec(r) for r in self.core.db.query(sql + " ORDER BY id DESC LIMIT 200", tuple(params))]

    def due_for_review(self) -> list[dict]:
        rows = self.core.db.query("SELECT * FROM decisions WHERE status='active' AND review_at IS NOT NULL"
                                  " AND date(review_at) <= date('now') ORDER BY review_at")
        return [self._dec(r) for r in rows]

    def compare(self, a: int, b: int) -> dict:
        da, db_ = self.get(a), self.get(b)
        diff = {k: {"a": da[k], "b": db_[k]} for k in CORE_FIELDS + ("actual_outcome", "status") if da[k] != db_[k]}
        return {"a": a, "b": b, "differences": diff}

    def history(self, did: int) -> list[dict]:
        """Qarorning butun zanjiri: avvalgilari va keyingilari."""
        chain, d = [], self.get(did)
        while d["supersedes"]:
            d = self.get(d["supersedes"])
        while True:
            chain.append({"id": d["id"], "chosen": d["chosen"], "status": d["status"], "created_at": d["created_at"]})
            if not d["superseded_by"]:
                break
            d = self.get(d["superseded_by"])
        return chain
