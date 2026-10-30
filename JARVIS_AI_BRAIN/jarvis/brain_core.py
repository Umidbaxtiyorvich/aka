"""JARVIS Brain Core — markaziy fikrlash quvuri (orkestratsiya qatlami).

Bu yangi neyron model EMAS: JARVIS'ning mavjud modullarini (Router, xotira, Knowledge Graph, POS tahlilchisi, ulanishlar,
tasdiqlash) bitta tartibli jarayonga bog'laydi va har qadamni iz (trace) sifatida yozadi:

  1. Tushunish — niyat va davr (intent.py + POS savol tahlili).
  2. Xotira — tegishli xotiralarni topish (FTS + Connection Engine).
  3. Vosita tanlash — POS tahlilchisi / ulanishlar holati / AI model (Router: vazifa turi bo'yicha).
  4. Ruxsat — vositalar faqat o'qiydi; yozish kerak bo'lsa — tasdiq so'rovi (bu yerda bajarilmaydi).
  5. Bajarish.
  6. Tekshirish — raqamlar hisoblangan ma'lumotdan bo'lsa "tekshirilgan", model matni bo'lsa "model javobi (tekshirilmagan)".
  7. Javob — o'zbekcha, manba va cheklovlar bilan.
"""
from __future__ import annotations

import time


class BrainCore:
    def __init__(self, core):
        self.core = core

    def think(self, text: str) -> dict | None:
        """POS/biznes va ulanishlar savollarini Brain Core hal qiladi; boshqalari uchun None (oddiy chat oqimi)."""
        t0, trace = time.monotonic(), []
        step = lambda name, **kw: trace.append({"step": name, **kw})  # noqa: E731
        from .integrations.analyst import parse_question
        q = parse_question(text)
        step("tushunish", intent=q["intent"], period=q["period"])
        if not q["intent"]:
            return None
        mem = self.core.memory.search(text, limit=3)
        step("xotira", found=[m["id"] for m in mem])
        tool = "integrations" if q["intent"] == "connections" else "pos_analyst"
        step("vosita", tool=tool, agent="business_analyst" if tool == "pos_analyst" else "integration")
        step("ruxsat", level="A", note="faqat o'qish — tasdiq shart emas")
        res = self.core.analyst.answer(text)
        step("bajarish", handled=res.get("handled"), sources=res.get("sources"))
        if not res.get("data") and q["intent"] != "connections":
            db = self.core.db
            has_bi = db.one("SELECT 1 FROM sqlite_master WHERE name='bi_products'") and (
                db.one("SELECT COUNT(*) n FROM bi_products")["n"] or db.one("SELECT COUNT(*) n FROM bi_movements")["n"])
            if has_bi:
                return None          # ulanishlarda ma'lumot yo'q, lekin fayl importidan BI bor — mavjud BI hisoboti javob beradi
        verified = bool(res.get("data")) and not res.get("limitations")
        step("tekshirish", verified=verified, note="raqamlar sinxronlangan ma'lumotdan hisoblandi" if res.get("data") else "ma'lumot yo'q — taxmin qilinmadi")
        parts = [res["text"]]
        if res.get("sources"):
            parts.append("Manba: " + ", ".join(res["sources"]) + (f" · davr: {res['period'][0]} — {res['period'][1]}" if res.get("period") else ""))
        if res.get("method") and res["method"] != "—":
            parts.append(f"Hisoblash: {res['method']}")
        for lim in res.get("limitations") or []:
            parts.append(f"⚠ {lim}")
        if mem:
            parts.append("Bog'liq xotira: " + "; ".join(f"#{m['id']} {m['content'][:60]}" for m in mem))
        ms = int((time.monotonic() - t0) * 1000)
        step("javob", ms=ms)
        self.core.audit.log("brain_core", f"Brain Core: {q['intent']} ({q['period']})", target="analyst", risk="A",
                            result="verified" if verified else "partial")
        return {"text": "\n".join(parts), "brain": {"intent": q["intent"], "period": q["period"], "trace": trace, "verified": verified,
                                                    "data": res.get("data"), "sources": res.get("sources", [])}}

    def status(self) -> dict:
        c = self.core
        from .router import TASK_TYPES
        profs = c.ai.status()
        return {"architecture": ["Brain Core", "Reasoning (Router + model)", "Planning (Planner, DAG)", "Memory (SQLite + FTS5)",
                                 "Knowledge (Knowledge Graph)", "Tool Calling (POS tahlilchisi, ulanishlar, fayllar, internet)",
                                 "Model Router", "Agent Orchestrator", "Learning (Connection Engine, Discovery)", "Verification (manba + hisob)"],
                "models": [{"id": p["id"], "kind": p["kind"], "model": p["model"], "tier": p["tier"], "local": p["local"], "paid": p["paid"],
                            "available": p["available"], "note": p["note"]} for p in profs],
                "task_routes": c.settings.ai_task_routes, "task_types": TASK_TYPES, "last_route": c.ai.last_route,
                "agents": [{"key": a.key, "title": a.title, "status": a.status, "permission": a.permission} for a in c.agents.agents.values()],
                "integrations": c.integrations.health(),
                "memory": {"items": c.db.one("SELECT COUNT(*) n FROM memories")["n"], "graph_nodes": c.db.one("SELECT COUNT(*) n FROM kg_nodes")["n"]},
                "note": "JARVIS o'z AI Engine'iga ega: modellar sozlanadi va almashtiriladi. Claude Code (ishlab chiqish muhiti) JARVIS ichida ishlamaydi."}
