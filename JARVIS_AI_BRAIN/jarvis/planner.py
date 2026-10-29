"""Planner: maqsadni bosqichlarga ajratadi, har birini mos agentga beradi va ketma-ket bajaradi.
Bosqich tasdiq kutsa, reja to'xtaydi ('waiting_approval') — tasdiqsiz davom etmaydi."""
from __future__ import annotations

import json
import re

from . import intent as intent_mod

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT, goal TEXT NOT NULL, steps TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned', created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""
SPLIT = re.compile(r"\n+|;\s*|\s+(?:va\s+)?keyin\s+|\s+so'ng\s+|\s+undan keyin\s+|\s*\d+[.)]\s+", re.I)


class PlannerError(Exception):
    pass


def split_goal(goal: str) -> list[str]:
    parts = [p.strip(" .,") for p in SPLIT.split(goal) if p and p.strip(" .,")]
    return parts or [goal.strip()]


def step_for(text: str) -> dict:
    it, _ = intent_mod.detect(text)
    m = re.search(r"`([^`]+)`", text)
    if it == "command" and m:
        return {"agent": "computer", "payload": {"command": m.group(1), "reason": text}}
    if it == "run_tests":
        return {"agent": "qa", "payload": {}}
    if it == "file_read":
        return {"agent": "file_analysis", "payload": {"op": "list"}}
    if it == "research":
        q = re.sub(r"(?i)\b(internetdan|internetda|qidir\w*|izla\w*|topib ber|ma'lumot)\b", "", text).strip(" :")
        return {"agent": "research", "payload": {"query": q or text}}
    if it == "bi_report":
        return {"agent": "bi", "payload": {"op": "report"}}
    return {"agent": "manager", "payload": {"text": text}}


class Planner:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)

    def create(self, goal: str) -> dict:
        if not goal.strip():
            raise PlannerError("Maqsad bo'sh")
        steps = [{"n": i + 1, "text": t, **step_for(t), "status": "planned", "task_id": None}
                 for i, t in enumerate(split_goal(goal))]
        cur = self.core.db.execute("INSERT INTO plans(goal, steps) VALUES (?,?)", (goal, json.dumps(steps, ensure_ascii=False)))
        self.core.audit.log("planner", f"Reja tuzildi: {goal[:80]} ({len(steps)} bosqich)", target=f"plan#{cur.lastrowid}", risk="B")
        return self.get(cur.lastrowid)

    def get(self, pid: int) -> dict:
        r = self.core.db.one("SELECT * FROM plans WHERE id=?", (pid,))
        if not r:
            raise PlannerError("Reja topilmadi")
        r["steps"] = json.loads(r["steps"])
        return r

    def list(self) -> list[dict]:
        return [self.get(r["id"]) for r in self.core.db.query("SELECT id FROM plans ORDER BY id DESC LIMIT 50")]

    def _save(self, plan: dict, status: str):
        self.core.db.execute("UPDATE plans SET steps=?, status=? WHERE id=?",
                             (json.dumps(plan["steps"], ensure_ascii=False), status, plan["id"]))

    def run(self, pid: int) -> dict:
        plan = self.get(pid)
        status = "done"
        for s in plan["steps"]:
            if s["status"] == "done":
                continue
            agent = self.core.agents.agents.get(s["agent"])
            if agent is None or agent.handler is None:
                s["status"], status = "skipped", "partial"
                continue
            t = self.core.agents.submit(s["agent"], f"Reja #{pid}, {s['n']}-bosqich", s["payload"], run_now=True)
            s["task_id"], s["status"] = t["id"], t["status"]
            if t["status"] == "failed":
                status = "failed"
                break
            if t["status"] == "waiting_approval":
                status = "waiting_approval"
                break
        self._save(plan, status)
        return self.get(pid)
