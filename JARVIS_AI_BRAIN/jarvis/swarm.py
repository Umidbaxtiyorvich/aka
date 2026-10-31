"""Agent Swarm — agentlar bir-biriga Tool Registry orqali vazifa topshiradi, Supervisor natijani tekshiradi.

Qoidalar:
* Topshiriq QABUL QILUVCHI agentning ruxsatlari bilan bajariladi (Tool Registry `caller` = qabul qiluvchi): yuboruvchi o'z
  ruxsatini boshqa agentga o'tkaza olmaydi va o'zi qila olmaydigan ishni boshqasi orqali "chetlab" qildira olmaydi —
  yuboruvchining ruxsat chegarasi ham tekshiriladi (ikkalasidan pasti amal qiladi).
* Chuqurlik ≤ 3, bitta missiya/zanjir uchun ≤ 20 topshiriq, bir xil (agent, tool, argumentlar) takrori — sikl sifatida rad.
* Supervisor har natijani tekshiradi: holat, bo'sh natija, xato, tool turiga xos qoida (manba, tasdiq so'rovi yaratilganmi).
  Tekshiruvdan o'tmagan natija "bajarildi" deyilmaydi.
* Agentlar o'zaro erkin suhbatlashmaydi (token sarfi yo'q): faqat aniq tool chaqiruvlari.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA = """
CREATE TABLE IF NOT EXISTS delegations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), chain TEXT NOT NULL, depth INTEGER NOT NULL,
    from_agent TEXT NOT NULL, to_agent TEXT NOT NULL, tool TEXT NOT NULL, args_hash TEXT NOT NULL, status TEXT NOT NULL,
    verdict TEXT, note TEXT, mission_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_deleg_chain ON delegations(chain);
"""
ORDER = "ABCDE"
MAX_DEPTH = 3
MAX_PER_CHAIN = 20


class SwarmError(Exception):
    pass


class Supervisor:
    """Natija tekshiruvchisi: tool turiga qarab qoidalar. AI ishlatmaydi (tez, bepul, deterministik)."""

    def review(self, tool_id: str, res: dict) -> tuple[bool, str]:
        if res.get("status") == "approval_requested":
            appr = (res.get("result") or {}).get("approval") or {}
            if (res.get("result") or {}).get("status") in ("draft", "pending_approval") or appr.get("status") in ("pending", "approved"):
                return True, "tasdiq so'rovi yaratildi — amal foydalanuvchi qaroridan keyin bajariladi"
            return False, "tasdiq so'rovi yaratilmadi"
        if res.get("status") != "ok":
            return False, f"holat: {res.get('status')}"
        r = res.get("result")
        if r in (None, "", [], {}):
            return False, "natija bo'sh"
        if isinstance(r, dict):
            if r.get("error"):
                return False, f"xato: {str(r['error'])[:150]}"
            if tool_id == "research.web" and not r.get("sources"):
                return False, "manbasiz javob — tekshirilmagan"
            if tool_id == "analyst.ask" and r.get("handled") and not r.get("data"):
                return True, "ma'lumot yo'q (taxmin qilinmadi) — natija halol"
        return True, "tekshiruvdan o'tdi"


class Swarm:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        self.supervisor = Supervisor()

    def _ceiling(self, agent: str) -> str:
        if agent == "user":
            return "E"
        a = self.core.agents.agents.get(agent)
        if not a:
            raise SwarmError(f"Agent topilmadi: {agent}")
        return a.permission or "A"

    def delegate(self, from_agent: str, to_agent: str, tool_id: str, args: dict | None = None, *, chain: str = "", depth: int = 1,
                 mission_id: int | None = None) -> dict:
        args = args or {}
        t = self.core.tools.tools.get(tool_id)
        if not t:
            raise SwarmError(f"Tool topilmadi: {tool_id}")
        h = hashlib.sha256(f"{to_agent}|{tool_id}|{json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)}".encode()).hexdigest()[:16]
        chain = chain or hashlib.sha256(f"{from_agent}{h}{id(args)}".encode()).hexdigest()[:12]
        db = self.core.db
        log = lambda status, verdict=None, note="": db.execute(  # noqa: E731
            "INSERT INTO delegations(chain, depth, from_agent, to_agent, tool, args_hash, status, verdict, note, mission_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (chain, depth, from_agent, to_agent, tool_id, h, status, verdict, note[:300], mission_id))
        if depth > MAX_DEPTH:
            log("denied", note="chuqurlik limiti")
            raise SwarmError(f"Topshiriq zanjiri juda chuqur (>{MAX_DEPTH})")
        if db.one("SELECT COUNT(*) n FROM delegations WHERE chain=?", (chain,))["n"] >= MAX_PER_CHAIN:
            log("denied", note="zanjir limiti")
            raise SwarmError(f"Bitta zanjirda {MAX_PER_CHAIN} tadan ortiq topshiriq")
        if db.one("SELECT 1 FROM delegations WHERE chain=? AND args_hash=? AND status IN ('ok','running')", (chain, h)):
            log("denied", note="takroriy topshiriq (sikl)")
            raise SwarmError("Bir xil topshiriq takrorlandi — sikl sifatida to'xtatildi")
        # Yuboruvchi o'zi qila olmaydigan darajadagi ishni boshqa agent orqali qildira olmaydi
        if ORDER.index(t.level) > ORDER.index(self._ceiling(from_agent)):
            log("denied", note="yuboruvchining ruxsati yetarli emas")
            raise SwarmError(f"'{from_agent}' {t.level} darajali ishni topshira olmaydi (o'z chegarasi {self._ceiling(from_agent)})")
        from .tools import ToolError
        try:
            res = self.core.tools.invoke(tool_id, args, caller=to_agent)
        except ToolError as e:
            log("denied" if "chaqira olmaydi" in str(e) or "chegarasi" in str(e) else "error", note=str(e))
            raise SwarmError(str(e)) from None
        ok, note = self.supervisor.review(tool_id, res)
        log("ok" if ok else "rejected", "approved" if ok else "rejected", note)
        ev = getattr(self.core, "events", None)
        if ev:
            ev.publish("swarm", from_agent=from_agent, to_agent=to_agent, tool=tool_id, verdict="approved" if ok else "rejected")
        return {"chain": chain, "from": from_agent, "to": to_agent, "tool": tool_id, "result": res.get("result"), "status": res.get("status"),
                "supervisor": {"ok": ok, "note": note}}

    def history(self, limit: int = 100, mission_id: int | None = None) -> list[dict]:
        return self.core.db.query("SELECT * FROM delegations" + (" WHERE mission_id=?" if mission_id else "") + " ORDER BY id DESC LIMIT ?",
                                  (mission_id, limit) if mission_id else (limit,))

    def routes(self) -> dict:
        """Kim kimga qaysi tool bilan topshiriq bera oladi (Tool Registry'dan hisoblanadi)."""
        out = {}
        for t in self.core.tools.catalog():
            out[t["id"]] = [a for a in t["agents"] if a != "user"]
        return out
