"""3D Brain hududlari → JARVIS dasturiy modullari.

Bu biologik miya simulyatsiyasi EMAS: har bir hudud — JARVIS modullarining vizual guruhi. Holat, faol vazifalar,
agentlar, model va oxirgi ishlar haqiqiy jadvallardan (tasks, ai_usage, audit_log, approvals...) olinadi.
"""
from __future__ import annotations

REGIONS = [
    {"id": "memory", "name": "Memory Center", "uz": "Xotira markazi", "color": "#22d3ee",
     "modules": ["memory", "kgraph", "decisions"], "agents": ["file_analysis"], "actors": ["memory", "kgraph", "user"]},
    {"id": "reasoning", "name": "Reasoning Center", "uz": "Mantiqiy tahlil", "color": "#3b82f6",
     "modules": ["ai_router", "resource_guard"], "agents": ["manager", "developer"], "actors": ["ai_router", "manager", "developer"]},
    {"id": "planning", "name": "Planning Center", "uz": "Rejalashtirish", "color": "#a855f7",
     "modules": ["planner", "dag"], "agents": ["qa"], "actors": ["planner", "dag", "qa", "selfheal", "self_improve"]},
    {"id": "language", "name": "Language Center", "uz": "Til va muloqot", "color": "#06b6d4",
     "modules": ["chat", "voice", "telegram"], "agents": ["voice", "telegram"], "actors": ["voice_agent", "telegram_agent"]},
    {"id": "vision", "name": "Vision Center", "uz": "Tasvir tahlili", "color": "#f59e0b",
     "modules": ["imagegen", "studio"], "agents": ["image", "browser"], "actors": ["imagegen", "studio", "browser"]},
    {"id": "creative", "name": "Creative Center", "uz": "Ijodiy vazifalar", "color": "#ec4899",
     "modules": ["studio", "instagram"], "agents": ["video", "instagram"], "actors": ["instagram_agent", "instagram_mcp", "studio"]},
    {"id": "agents", "name": "Agent Control Center", "uz": "Agentlar boshqaruvi", "color": "#8b5cf6",
     "modules": ["agents"], "agents": ["research", "bi", "pos"], "actors": ["research", "bi", "pos", "pos_sync"]},
    {"id": "security", "name": "Security Center", "uz": "Xavfsizlik", "color": "#eab308",
     "modules": ["security", "policy", "approvals", "auth"], "agents": ["security", "computer"], "actors": ["security", "secrets", "computer"]},
]
AGENT_REGION = {a: r["id"] for r in REGIONS for a in r["agents"]}


class Brain:
    def __init__(self, core):
        self.core = core

    def region_state(self, rid: str) -> dict:
        r = next((x for x in REGIONS if x["id"] == rid), None)
        if not r:
            raise ValueError("Bunday hudud yo'q")
        c, db = self.core, self.core.db
        marks = ",".join("?" * len(r["agents"]))
        agents = [{"key": a.key, "title": a.title, "status": a.status, "last_error": a.last_error}
                  for k, a in c.agents.agents.items() if k in r["agents"]]
        active = db.query(f"SELECT id, title, agent, status, started_at FROM tasks WHERE agent IN ({marks}) AND status='running'"
                          " ORDER BY id DESC LIMIT 10", tuple(r["agents"])) if r["agents"] else []
        recent_tasks = db.query(f"SELECT id, title, agent, status, finished_at FROM tasks WHERE agent IN ({marks})"
                                " ORDER BY id DESC LIMIT 5", tuple(r["agents"])) if r["agents"] else []
        am = ",".join("?" * len(r["actors"]))
        recent = db.query(f"SELECT ts, agent AS actor, action, risk FROM audit_log WHERE agent IN ({am}) ORDER BY id DESC LIMIT 6", tuple(r["actors"]))
        errors = db.one(f"SELECT COUNT(*) n FROM errors WHERE ts >= datetime('now','-1 day') AND module IN ({am})", tuple(r["actors"]))["n"]
        model = None
        if rid in ("reasoning", "language"):
            lr = c.ai.last_route or {}
            model = f"{lr.get('provider')} ({lr.get('model')})" if lr else getattr(c.ai, "model", None)
        elif rid == "vision":
            model = c.settings.vision_model or "sozlanmagan"
        extra = {}
        if rid == "memory":
            extra = {"memories": db.one("SELECT COUNT(*) n FROM memories")["n"],
                     "conflicts": db.one("SELECT COUNT(*) n FROM memories WHERE status='conflict'")["n"],
                     "graph_nodes": db.one("SELECT COUNT(*) n FROM kg_nodes")["n"]}
        elif rid == "security":
            extra = {"pending_approvals": db.one("SELECT COUNT(*) n FROM approvals WHERE status='pending'")["n"],
                     "read_only": c.settings.read_only_mode}
        elif rid == "planning":
            extra = {"dag_running": db.one("SELECT COUNT(*) n FROM dag_runs WHERE status IN ('running','waiting_approval')")["n"]
                     if db.one("SELECT 1 FROM sqlite_master WHERE name='dag_runs'") else 0}
        status = ("error" if any(a["status"] == "error" for a in agents) or errors >= 3 else
                  "active" if active or any(a["status"] == "running" for a in agents) else "idle")
        return {k: r[k] for k in ("id", "name", "uz", "color", "modules")} | {
            "status": status, "agents": agents, "active_tasks": active, "recent_tasks": recent_tasks, "recent_actions": recent,
            "errors_24h": errors, "model": model, **extra}

    def state(self) -> dict:
        return {"regions": [self.region_state(r["id"]) for r in REGIONS], "events": self.core.events.snapshot(),
                "agent_region": AGENT_REGION,
                "note": "Hududlar — JARVIS dasturiy modullarining vizual ifodasi, biologik miya simulyatsiyasi emas."}
