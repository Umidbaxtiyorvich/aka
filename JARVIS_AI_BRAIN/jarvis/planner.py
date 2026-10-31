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


# Agent Swarm: Main Brain (manager) aniq tool orqali mutaxassis agentga topshiradi, Supervisor tekshiradi
SWARM_RULES = [
    (re.compile(r"(?i)^\s*(xotiradan qidir|eslab ko'?r|xotirada)\s*:?\s*(.+)"), "memory_agent", "memory.search", "query"),
    (re.compile(r"(?i)^\s*(fayl qidir|faylni top)\s*:?\s*(.+)"), "file_analysis", "assets.search", "query"),
    (re.compile(r"(?i)^\s*(savdo prognozi|prognoz)\b\s*:?\s*(.*)"), "business_analyst", "business.forecast", None),
    (re.compile(r"(?i)^\s*(biznes savol|biznes tahlil)\s*:?\s*(.+)"), "business_analyst", "analyst.ask", "question"),
    (re.compile(r"(?i)^\s*(matnni tekshir|xavfsizlik tekshiruvi)\s*:?\s*(.+)"), "security", "security.scan_text", "text"),
    (re.compile(r"(?i)^\s*(dry-?run|sinab ko'?r)\s*:?\s*(.+)"), "manager", "simlab.mission", "goal"),
]


def step_for(text: str) -> dict:
    for rx, agent, tool, arg in SWARM_RULES:
        m = rx.match(text)
        if m:
            return {"agent": "swarm", "payload": {"to": agent, "tool": tool, "args": {arg: m.group(2).strip()} if arg else {}}}
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


AI_PROMPT = ("Foydalanuvchi maqsadini 1–8 ta qisqa, aniq bosqichga ajrat. Har bosqich bitta amal bo'lsin "
             "(masalan: 'savdo hisobotini ko'rsat', 'fayllarni ko'rsat', 'internetdan qidir: ...', 'test'). "
             "Faqat JSON ro'yxat qaytar, boshqa matn yozma: [\"1-bosqich\", \"2-bosqich\"]. Maqsad: <untrusted>{goal}</untrusted>")


def parse_ai_steps(text: str) -> list[str] | None:
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or not (1 <= len(data) <= 12):
        return None
    steps = [str(x).strip()[:300] for x in data if isinstance(x, (str, int, float)) and str(x).strip()]
    return steps or None


class Planner:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        core.db.ensure_columns("plans", {"source": "TEXT NOT NULL DEFAULT 'rules'", "note": "TEXT"})

    def _ai_split(self, goal: str) -> tuple[list[str] | None, str]:
        if not getattr(self.core.settings, "planner_use_ai", False) or self.core.ai.name == "offline":
            return None, "AI mavjud emas — qoidalar bo'yicha ajratildi"
        try:
            r = self.core.ai.route([{"role": "user", "content": AI_PROMPT.format(goal=goal)}], purpose="analysis")
        except Exception as e:
            return None, f"AI javob bermadi ({str(e)[:80]}) — qoidalar bo'yicha ajratildi"
        steps = parse_ai_steps(r["text"])
        if not steps:
            return None, "AI javobi tushunarsiz — qoidalar bo'yicha ajratildi"
        return steps, f"AI ({r['route']['provider']}) bosqichlarga ajratdi; agentlar qoidalar bo'yicha tanlandi"

    def create(self, goal: str, use_ai: bool | None = None) -> dict:
        if not goal.strip():
            raise PlannerError("Maqsad bo'sh")
        parts, note, source = None, "qoidalar bo'yicha ajratildi", "rules"
        if use_ai is not False:
            parts, note = self._ai_split(goal)
            source = "ai" if parts else "rules"
        parts = parts or split_goal(goal)
        # AI faqat matnni ajratadi; agent va payload har doim qoidalar bilan, xavfli amallar baribir tasdiqdan o'tadi
        steps = [{"n": i + 1, "text": t, **step_for(t), "status": "planned", "task_id": None} for i, t in enumerate(parts)]
        cur = self.core.db.execute("INSERT INTO plans(goal, steps, source, note) VALUES (?,?,?,?)",
                                   (goal, json.dumps(steps, ensure_ascii=False), source, note))
        self.core.audit.log("planner", f"Reja tuzildi: {goal[:80]} ({len(steps)} bosqich, {source})", target=f"plan#{cur.lastrowid}", risk="B")
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
