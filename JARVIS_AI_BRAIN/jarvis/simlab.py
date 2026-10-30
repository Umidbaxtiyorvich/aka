"""Simulation Lab — o'zgarishni production'ga tatbiq etishdan OLDIN sinov nusxasida tekshirish.

* SQL: JARVIS bazasi yoki ulangan SQLite bazasining vaqtinchalik NUSXASIda bajariladi → oldin/keyin qatorlar, jadval bo'yicha
  farq, xatolar. Nusxa so'ng o'chiriladi — production'ga tegilmaydi ("rollback" = nusxani tashlab yuborish).
* POS/ERP yozuvi: sinxronlangan yozuv ustida "oldin → keyin" ko'rinishi va kerakli tasdiq darajasi (tashqi tizimga hech narsa yuborilmaydi).
* Missiya: reja + har bosqich xavfi + qaysi tasdiqlar kerak bo'lishi — hech narsa bajarilmaydi.
* Kod: mavjud Sandbox (cheklangan jarayon) orqali.
Simulyatsiya muvaffaqiyatli bo'lsa ham production uchun ruxsat alohida, odatdagi tasdiq bilan olinadi.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

from .security import is_within

SCHEMA = """
CREATE TABLE IF NOT EXISTS sim_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, target TEXT, input TEXT, report TEXT, status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""
FORBIDDEN_SQL = re.compile(r"(?i)\b(attach|detach|vacuum\s+into|load_extension|writable_schema)\b")
ROW_DIFF_LIMIT = 5000


class SimError(Exception):
    pass


def _counts(conn) -> dict:
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'")]
    return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}


def _rows(conn, table: str) -> dict:
    cur = conn.execute(f'SELECT rowid, * FROM "{table}"')
    cols = [d[0] for d in cur.description]
    return {r[0]: dict(zip(cols[1:], r[1:])) for r in cur.fetchall()}


class SimulationLab:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)

    def _save(self, kind: str, target: str, inp, report: dict, status: str) -> dict:
        rid = self.core.db.execute("INSERT INTO sim_runs(kind, target, input, report, status) VALUES (?,?,?,?,?)",
                                   (kind, target, json.dumps(inp, ensure_ascii=False, default=str)[:20000], json.dumps(report, ensure_ascii=False, default=str), status)).lastrowid
        self.core.audit.log("simlab", f"Simulyatsiya ({kind}): {status}", target=target, risk="A")
        return {"id": rid, "kind": kind, "target": target, "status": status, **report}

    def _source(self, target: str) -> Path:
        if target == "jarvis":
            return Path(self.core.db.path)
        if target.startswith("conn:"):
            c = self.core.integrations.get(int(target[5:]))
            if c["adapter"] != "database" or c["config"].get("engine", "sqlite") != "sqlite":
                raise SimError("Hozircha faqat SQLite bazalari nusxada sinaladi (PostgreSQL/MSSQL uchun test bazasi kerak)")
            p = Path(c["config"].get("path", ""))
            if not is_within(p, self.core.settings.allowed_read_dirs) or not p.exists():
                raise SimError("Baza fayli ruxsat berilgan papkada topilmadi")
            return p
        raise SimError("target: 'jarvis' yoki 'conn:<id>'")

    def sql(self, target: str, statements: list[str]) -> dict:
        stmts = [s.strip() for s in statements if s and s.strip()][:50]
        if not stmts:
            raise SimError("SQL buyruqlari kerak")
        for s in stmts:
            if FORBIDDEN_SQL.search(s):
                raise SimError(f"Sinovda ham taqiqlangan buyruq: {s[:60]}")
        src = self._source(target)
        tmp = Path(tempfile.mkdtemp(prefix="jarvis_sim_"))
        copy = tmp / "sim.db"
        try:
            with sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True) as s_conn, sqlite3.connect(copy) as d_conn:
                s_conn.backup(d_conn)                        # izchil nusxa (WAL bilan ham)
            conn = sqlite3.connect(copy)
            before = _counts(conn)
            small = [t for t, n in before.items() if n <= ROW_DIFF_LIMIT]
            snap = {t: _rows(conn, t) for t in small}
            results, ok = [], True
            for s in stmts:
                try:
                    cur = conn.execute(s)
                    results.append({"sql": s[:300], "ok": True, "rows_affected": cur.rowcount if cur.rowcount >= 0 else None,
                                    "preview": [list(r) for r in cur.fetchmany(5)] if cur.description else None})
                except sqlite3.Error as e:
                    ok = False
                    results.append({"sql": s[:300], "ok": False, "error": str(e)[:200]})
            conn.commit()
            after = _counts(conn)
            diff = []
            for t in sorted(set(before) | set(after)):
                b, a = before.get(t), after.get(t)
                d = {"table": t, "before": b, "after": a}
                if t in snap and a is not None:
                    new = _rows(conn, t)
                    d["inserted"] = len(set(new) - set(snap[t]))
                    d["deleted"] = len(set(snap[t]) - set(new))
                    d["updated"] = sum(1 for k in set(new) & set(snap[t]) if new[k] != snap[t][k])
                    d["examples"] = [{"rowid": k, "before": snap[t][k], "after": new[k]} for k in list(set(new) & set(snap[t])) if new[k] != snap[t][k]][:3]
                if b != a or d.get("updated") or d.get("inserted") or d.get("deleted"):
                    diff.append(d)
            conn.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        report = {"results": results, "diff": diff, "production_changed": False,
                  "rollback": "Sinov nusxasi o'chirildi — production bazasi o'zgarmagan. Tatbiq etish alohida tasdiq va oldindan zaxira bilan.",
                  "note": "Katta jadvallarda (5000+ qator) faqat qatorlar soni solishtirildi."}
        return self._save("sql", target, stmts, report, "ok" if ok else "errors")

    def write_preview(self, conn_id: int, entity: str, operation: str, payload: dict, record_id: str = "") -> dict:
        from .integrations import FINANCIAL
        c = self.core.integrations.get(conn_id)
        before = None
        if record_id:
            r = self.core.db.one("SELECT raw FROM ext_records WHERE conn_id=? AND (source_entity=? OR entity=?) AND source_id=? AND deleted=0",
                                 (conn_id, entity, entity, str(record_id)))
            before = json.loads(r["raw"]) if r else None
        after = {**(before or {}), **payload} if operation == "update" else payload
        changed = {k: {"before": (before or {}).get(k), "after": v} for k, v in after.items() if (before or {}).get(k) != v}
        financial = any(w in f"{entity} {operation} {json.dumps(payload, ensure_ascii=False)}".lower() for w in FINANCIAL)
        report = {"system": c["name"], "mode": c["mode"], "before": before, "after": after, "changed": changed,
                  "required_approval": "yo'q — rejim 'faqat o'qish', yozish mumkin emas" if c["mode"] == "read_only" else ("E (moliyaviy, faqat dashboard)" if financial else "D"),
                  "production_changed": False, "note": "Tashqi tizimga hech narsa yuborilmadi. Bu faqat mahalliy nusxa asosidagi ko'rinish."}
        return self._save("write", f"conn:{conn_id}", {"entity": entity, "operation": operation, "payload": payload}, report, "ok")

    def mission(self, goal: str) -> dict:
        nodes, note, source = self.core.missions._plan_nodes(goal, use_ai=False)
        steps = [{"key": n["key"], "title": n["title"], "agent": n["agent"], **self.core.permissions.assess(n["agent"], n["payload"])} for n in nodes]
        report = {"steps": steps, "would_auto_start": self.core.missions.may_auto_start(steps), "autonomy_level": self.core.settings.autonomy_level,
                  "approvals_needed": [s["key"] for s in steps if s.get("needs_approval")], "blocked": [s["key"] for s in steps if not s["allowed"]],
                  "plan_note": note, "production_changed": False}
        return self._save("mission", "mission", goal, report, "ok")

    def code(self, code: str) -> dict:
        r = self.core.sandbox.run_python(code)
        report = {"sandbox": {k: r.get(k) for k in ("status", "stdout", "stderr", "duration_ms", "findings", "approval")}, "production_changed": False}
        return self._save("code", "sandbox", code[:2000], report, r.get("status", "?"))

    def history(self, limit: int = 30) -> list[dict]:
        rows = self.core.db.query("SELECT * FROM sim_runs ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["report"] = json.loads(r["report"] or "{}")
            r["input"] = r["input"]
        return rows
