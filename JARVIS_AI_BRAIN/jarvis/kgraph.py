"""Knowledge Graph — loyiha, vazifa, fayl, agent, qaror, xato, manba va bilimlar orasidagi aloqalar.

Alohida grafik BD shart emas: SQLite'da ikki jadval (tugun, qirra) + indekslar yetarli.
Aloqalar avtomatik yoziladi (vazifa → agent, loyiha → xotira, manba → bilim, qaror → fayl, taklif → fayl,
xato → tuzatish) va qo'lda ham qo'shiladi.
"""
from __future__ import annotations

import json
import re
from collections import deque

SCHEMA = """
CREATE TABLE IF NOT EXISTS kg_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, ref TEXT NOT NULL, label TEXT NOT NULL,
    props TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(type, ref)
);
CREATE TABLE IF NOT EXISTS kg_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT, src INTEGER NOT NULL, rel TEXT NOT NULL, dst INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(src, rel, dst)
);
CREATE INDEX IF NOT EXISTS kg_edges_src ON kg_edges(src);
CREATE INDEX IF NOT EXISTS kg_edges_dst ON kg_edges(dst);
CREATE INDEX IF NOT EXISTS kg_nodes_label ON kg_nodes(label);
"""
RELATIONS = {"performed_by": "bajargan agent", "has_task": "vazifasi", "has_memory": "xotirasi", "supports": "qo'llab-quvvatlaydi",
             "affects": "ta'sir qiladi", "based_on": "asoslangan", "supersedes": "o'rnini bosadi", "changes": "o'zgartiradi",
             "resolved_by": "tuzatilgan", "has_decision": "qarori", "has_goal": "maqsadi", "related_to": "bog'liq",
             "tested_by": "sinalgan", "covers": "tekshiradi"}
# Tugun turi → dashboard bo'limi (tugundan tegishli joyga o'tish uchun)
SECTIONS = {"task": "agents", "agent": "agents", "decision": "decisions", "error": "errors", "proposal": "tests", "test_run": "tests",
            "file": "files", "memory": "memory", "source": "knowledge", "project": "memory", "module": "diagnostics"}
NodeSpec = tuple  # (type, ref, label|None)


class KGError(Exception):
    pass


class KnowledgeGraph:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        # Provenance: manba, olingan vaqt va tekshirilgan holati har bir tugunda
        core.db.ensure_columns("kg_nodes", {"source": "TEXT", "observed_at": "TEXT", "verified": "INTEGER NOT NULL DEFAULT 0"})

    # --- yozish ---
    def node(self, type_: str, ref, label: str | None = None, props: dict | None = None, *, source: str | None = None,
             observed_at: str | None = None, verified: bool | None = None) -> int:
        ref = str(ref)
        row = self.core.db.one("SELECT id, label FROM kg_nodes WHERE type=? AND ref=?", (type_, ref))
        if row:
            if label and label != row["label"]:
                self.core.db.execute("UPDATE kg_nodes SET label=? WHERE id=?", (label[:200], row["id"]))
            if source is not None or observed_at is not None or verified is not None or props:
                self.core.db.execute("UPDATE kg_nodes SET source=COALESCE(?, source), observed_at=COALESCE(?, observed_at),"
                                     " verified=COALESCE(?, verified), props=CASE WHEN ? IS NULL THEN props ELSE ? END WHERE id=?",
                                     (source, observed_at, None if verified is None else int(verified),
                                      None if not props else 1, json.dumps(props or {}, ensure_ascii=False), row["id"]))
            return row["id"]
        cur = self.core.db.execute("INSERT INTO kg_nodes(type, ref, label, props, source, observed_at, verified) VALUES (?,?,?,?,?,"
                                   "COALESCE(?, datetime('now')),?)",
                                   (type_, ref, (label or f"{type_} {ref}")[:200], json.dumps(props or {}, ensure_ascii=False),
                                    source or "jarvis:auto", observed_at, int(bool(verified))))
        return cur.lastrowid

    def link(self, src: NodeSpec, rel: str, dst: NodeSpec) -> dict:
        if rel not in RELATIONS:
            raise KGError(f"Aloqa turi: {sorted(RELATIONS)}")
        a, b = self.node(*src), self.node(*dst)
        self.core.db.execute("INSERT OR IGNORE INTO kg_edges(src, rel, dst) VALUES (?,?,?)", (a, rel, b))
        return {"src": a, "rel": rel, "dst": b}

    # --- avtomatik ilgaklar ---
    def on_task(self, task: dict):
        self.link(("task", task["id"], task["title"]), "performed_by", ("agent", task["agent"], task["agent"]))

    def on_memory(self, m: dict):
        self.node("memory", m["id"], m["content"][:80], source=m.get("reference") or m.get("source") or "user",
                  observed_at=m.get("observed_at") or m.get("created_at"), verified=bool(m.get("verified")))
        node = ("memory", m["id"], m["content"][:80])
        if m.get("project"):
            self.link(("project", m["project"], m["project"]), "has_task" if m["kind"] == "task" else "has_memory", node)
        if m.get("reference"):
            self.link(("source", m["reference"], m["reference"][:120]), "supports", node)

    def on_decision(self, d: dict):
        node = ("decision", d["id"], d["problem"][:80])
        for f in d.get("files") or []:
            self.link(node, "affects", ("file", f, f))
        for s in d.get("sources") or []:
            self.link(node, "based_on", ("source", s, s[:120]))
        if d.get("project"):
            self.link(("project", d["project"], d["project"]), "has_decision", node)
        if d.get("supersedes"):
            self.link(node, "supersedes", ("decision", d["supersedes"], None))

    def on_proposal(self, p: dict, paths: set[str]):
        node = ("proposal", p["id"], p["title"][:80])
        for f in sorted(paths):
            self.link(node, "changes", ("file", f, f))
        for eid in re.findall(r"error#(\d+)", (p.get("description") or "") + " " + p["title"]):
            self.link(("error", eid, None), "resolved_by", node)

    def on_test_run(self, run_id: str, status: str, *, proposal: dict | None = None, files: set[str] | None = None,
                    summary: str = "", source: str = "pytest") -> int:
        """Test natijasi tugun sifatida: taklif → sinalgan → test; test → tekshiradi → fayllar."""
        nid = self.node("test_run", run_id, f"{status}: {summary[:60]}" if summary else status, {"status": status},
                        source=source, verified=status in ("passed", "tested_pass"))
        tn = ("test_run", run_id, None)
        if proposal:
            self.link(("proposal", proposal["id"], proposal["title"][:80]), "tested_by", tn)
        for f in sorted(files or []):
            self.link(tn, "covers", ("file", f, f))
        return nid

    def rebuild(self, limit: int = 5000) -> dict:
        """Mavjud jadvallardan grafni tiklash (takroriy chaqirish xavfsiz)."""
        db = self.core.db
        for t in db.query("SELECT id, title, agent FROM tasks ORDER BY id DESC LIMIT ?", (limit,)):
            self.on_task(t)
        for m in db.query("SELECT * FROM memories ORDER BY id DESC LIMIT ?", (limit,)):
            self.on_memory(m)
        if hasattr(self.core, "decisions"):
            for d in self.core.decisions.list():
                self.on_decision(d)
        for e in db.query("SELECT id, module, message FROM errors ORDER BY id DESC LIMIT ?", (limit,)):
            self.link(("error", e["id"], f"{e['module']}: {e['message'][:60]}"), "related_to", ("module", e["module"], e["module"]))
        return self.stats()

    # --- o'qish ---
    def stats(self) -> dict:
        return {"nodes": self.core.db.one("SELECT COUNT(*) n FROM kg_nodes")["n"],
                "edges": self.core.db.one("SELECT COUNT(*) n FROM kg_edges")["n"],
                "by_type": {r["type"]: r["n"] for r in self.core.db.query("SELECT type, COUNT(*) n FROM kg_nodes GROUP BY type")}}

    def search(self, q: str, type_: str = "", limit: int = 50) -> list[dict]:
        sql, params = "SELECT * FROM kg_nodes WHERE (label LIKE ? OR ref LIKE ?)", [f"%{q}%", f"%{q}%"]
        if type_:
            sql += " AND type=?"
            params.append(type_)
        return [n | {"section": SECTIONS.get(n["type"])} for n in self.core.db.query(sql + " ORDER BY id DESC LIMIT ?", (*params, limit))]

    @staticmethod
    def section_for(type_: str) -> str | None:
        return SECTIONS.get(type_)

    def find(self, type_: str, ref) -> dict:
        r = self.core.db.one("SELECT * FROM kg_nodes WHERE type=? AND ref=?", (type_, str(ref)))
        if not r:
            raise KGError("Tugun topilmadi")
        return r

    def neighbors(self, node_id: int, depth: int = 1, limit: int = 300) -> dict:
        depth = max(1, min(depth, 3))
        seen, frontier, edges = {node_id}, {node_id}, {}
        for _ in range(depth):
            if not frontier:
                break
            marks = ",".join("?" * len(frontier))
            rows = self.core.db.query(f"SELECT * FROM kg_edges WHERE src IN ({marks}) OR dst IN ({marks}) LIMIT ?",
                                      (*frontier, *frontier, limit))
            nxt = set()
            for e in rows:
                edges[e["id"]] = e
                for x in (e["src"], e["dst"]):
                    if x not in seen:
                        seen.add(x)
                        nxt.add(x)
            frontier = nxt
        marks = ",".join("?" * len(seen))
        nodes = self.core.db.query(f"SELECT * FROM kg_nodes WHERE id IN ({marks})", tuple(seen))
        nodes = [n | {"section": SECTIONS.get(n["type"])} for n in nodes]
        return {"center": node_id, "nodes": nodes,
                "edges": [e | {"rel_uz": RELATIONS.get(e["rel"], e["rel"])} for e in edges.values()]}

    def path(self, a: int, b: int, max_depth: int = 6) -> list[dict]:
        prev, q = {a: None}, deque([(a, 0)])
        while q:
            cur, d = q.popleft()
            if cur == b:
                break
            if d >= max_depth:
                continue
            for e in self.core.db.query("SELECT * FROM kg_edges WHERE src=? OR dst=?", (cur, cur)):
                nxt = e["dst"] if e["src"] == cur else e["src"]
                if nxt not in prev:
                    prev[nxt] = (cur, e)
                    q.append((nxt, d + 1))
        if b not in prev:
            return []
        steps, cur = [], b
        while prev[cur] is not None:
            p, e = prev[cur]
            steps.append(e)
            cur = p
        ids = {x for e in steps for x in (e["src"], e["dst"])}
        labels = {n["id"]: f"{n['type']}:{n['label']}" for n in self.core.db.query(
            f"SELECT * FROM kg_nodes WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))}
        return [{"from": labels[e["src"]], "rel": RELATIONS.get(e["rel"], e["rel"]), "to": labels[e["dst"]]} for e in reversed(steps)]
