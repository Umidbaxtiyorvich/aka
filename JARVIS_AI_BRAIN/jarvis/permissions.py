"""Permission Manager — har bir agent va amal uchun yagona, foydalanuvchiga ko'rinadigan ruxsat jadvali.

Bu yangi "ikkinchi" tasdiqlash tizimi EMAS: haqiqiy bajarish baribir Policy Engine + Approval Engine orqali o'tadi
(chetlab o'tib bo'lmaydi). Permission Manager reja tuzish bosqichida xavfni oldindan baholaydi, agentning ruxsat
chegarasini tekshiradi va foydalanuvchiga tushunarli darajani (LOW / MEDIUM / HIGH / CRITICAL) ko'rsatadi.

Darajalar: A, B → LOW · C → MEDIUM · D → HIGH · E → CRITICAL. HIGH va CRITICAL hech qachon tasdiqsiz bajarilmaydi,
CRITICAL uchun har safar alohida aniq tasdiq (dashboard). Agentlar bir-birining ruxsatini meros qilib olmaydi.
"""
from __future__ import annotations

RISK = {"A": "LOW", "B": "LOW", "C": "MEDIUM", "D": "HIGH", "E": "CRITICAL"}
ORDER = "ABCDE"

# agent → (asosiy amal turi policy.ACTIONS dan, router vazifa turi, xotiraga kirish, natijani tekshirish qoidasi)
PROFILES = {
    "manager": ("analysis", "reasoning", "read", "text"),
    "developer": ("analysis", "code", "none", "no_error"),
    "file_analysis": ("read", "document", "none", "no_error"),
    "computer": ("shell_command", "agents", "none", "approval"),
    "security": ("analysis", "chat", "none", "no_error"),
    "qa": ("analysis", "code", "none", "tests"),
    "research": ("read", "research", "read", "sources"),
    "browser": ("read", "research", "none", "no_error"),
    "voice": ("analysis", "voice", "none", "no_error"),
    "image": ("local_draft", "vision", "none", "no_error"),
    "video": ("local_draft", "chat", "none", "no_error"),
    "instagram": ("instagram_publish", "chat", "none", "approval"),
    "telegram": ("read", "chat", "none", "no_error"),
    "bi": ("analysis", "pos", "none", "no_error"),
    "pos": ("pos_kirim", "pos", "none", "approval"),
    "pos_expert": ("read", "pos", "read", "no_error"),
    "business_analyst": ("analysis", "pos", "read", "no_error"),
    "database_expert": ("read", "pos", "none", "no_error"),
    "integration": ("read", "agents", "none", "no_error"),
    "memory_agent": ("analysis", "chat", "write_approved", "no_error"),
    "swarm": ("analysis", "agents", "none", "supervisor"),
}
VERIFY_RULES = {"text": "Javob bo'sh emas", "no_error": "Natijada xato yo'q", "tests": "Testlar o'tdi", "sources": "Manbalar ko'rsatilgan",
                "approval": "Tasdiq so'rovi yaratildi (amal tasdiqdan keyin bajariladi)",
                "supervisor": "Supervisor tasdig'i (holat, bo'sh natija, xato, tool qoidasi)"}


class PermissionManager:
    def __init__(self, core):
        self.core = core

    def assess(self, agent_key: str, payload: dict | None = None) -> dict:
        agent = self.core.agents.agents.get(agent_key)
        if agent is None:
            return {"agent": agent_key, "allowed": False, "risk": "CRITICAL", "level": "E", "reason": "Noma'lum agent"}
        action = (PROFILES.get(agent_key) or ("analysis",))[0]
        if agent_key == "computer" and payload and payload.get("command"):
            from .computer import classify_command
            action = "shell_read" if classify_command(payload["command"]) == "A" else "shell_command"
            d = self.core.policy.evaluate(action, command=payload["command"])
        else:
            d = self.core.policy.evaluate(action)
        if d.risk == "forbidden":
            return {"agent": agent_key, "action": action, "allowed": False, "risk": "CRITICAL", "level": "E", "reason": d.reason or "Taqiqlangan amal"}
        lvl = d.level
        ceiling = agent.permission or "A"
        if ORDER.index(lvl) > ORDER.index(ceiling):
            return {"agent": agent_key, "action": action, "allowed": False, "risk": RISK[lvl], "level": lvl,
                    "reason": f"Agent ruxsat chegarasi {ceiling} — {lvl} darajali amalni bajara olmaydi"}
        return {"agent": agent_key, "action": action, "allowed": True, "risk": RISK[lvl], "level": lvl,
                "needs_approval": lvl not in ("A", "B"), "reversible": d.reversible, "impact": d.impact}

    def profiles(self) -> list[dict]:
        out = []
        for k, a in self.core.agents.agents.items():
            action, task, mem, rule = PROFILES.get(k, ("analysis", "chat", "none", "no_error"))
            out.append({"key": k, "title": a.title, "role": a.role, "tools": a.tools, "max_level": a.permission, "max_risk": RISK.get(a.permission, "?"),
                        "action": action, "router_task": task, "memory_access": mem, "verify": VERIFY_RULES[rule], "status": a.status,
                        "implemented": a.handler is not None})
        return out
