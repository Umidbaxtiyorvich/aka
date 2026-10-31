"""Tool Registry — JARVIS vositalarining yagona katalogi.

Har bir tool: id, nom, tavsif, input/output sxemasi, xavf darajasi (A–E), qaysi agentlar chaqira oladi, timeout,
qayta urinish siyosati (faqat idempotent — o'qiydigan tool'lar), handler va audit.

Xavfsizlik qoidalari:
* Default deny: ro'yxatda yo'q tool chaqirilmaydi; tool faqat `agents` ro'yxatidagi agent (yoki foydalanuvchi) nomidan.
* Agentning ruxsat chegarasidan yuqori darajali tool rad etiladi; ruxsat boshqa agentga o'tmaydi.
* Registry o'zi faqat A/B (o'qish, tahlil, mahalliy qoralama) tool'larini bevosita bajaradi. Tashqi ta'sirli amallar
  (`approval=True`) faqat TASDIQ SO'ROVINI yaratadi — bajarish odatdagi Approval Engine orqali, foydalanuvchi qarori bilan.
* Avtonomlik Level 0 da faqat A darajali (o'qish) tool'lar ishlaydi.
* Har chaqiruv `tool_calls` jadvaliga (argumentlar maskalangan holda) yoziladi; daqiqalik limit bor.
"""
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutTimeout
from dataclasses import dataclass, field
from typing import Callable

from .security import contains_secret, redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), tool TEXT NOT NULL, caller TEXT NOT NULL,
    args TEXT, args_hash TEXT, status TEXT NOT NULL, duration_ms INTEGER, attempts INTEGER NOT NULL DEFAULT 1, error TEXT
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tool ON tool_calls(tool, ts);
"""
ORDER = "ABCDE"
TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tool")       # 8 GB RAM: bir vaqtda ko'pi bilan 2 ta tool


class ToolError(Exception):
    pass


@dataclass
class Tool:
    id: str
    name: str
    description: str
    level: str                                  # A..E (Policy darajasi)
    inputs: dict                                # {"query": {"type": "string", "required": True, "description": "..."}}
    output: str                                 # natija tavsifi
    handler: Callable
    agents: list[str] = field(default_factory=list)   # chaqirishga ruxsat berilgan agentlar ("user" — dashboard foydalanuvchisi)
    timeout: int = 60
    idempotent: bool = True                     # faqat shunda xatodan keyin 1 marta qayta urinadi
    approval: bool = False                      # True — tool faqat tasdiq so'rovini yaratadi (o'zi bajarmaydi)
    rate_per_min: int = 30

    def public(self) -> dict:
        from .permissions import RISK
        return {"id": self.id, "name": self.name, "description": self.description, "level": self.level, "risk": RISK[self.level],
                "inputs": self.inputs, "output": self.output, "agents": self.agents, "timeout": self.timeout,
                "retry": "1 marta (idempotent)" if self.idempotent else "yo'q (ikki marta bajarilmasligi uchun)",
                "approval": self.approval, "rate_per_min": self.rate_per_min}


def S(type_: str, required: bool = False, description: str = "", **kw) -> dict:
    return {"type": type_, "required": required, "description": description, **kw}


class ToolRegistry:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        self.tools: dict[str, Tool] = {}
        self._register_builtin()

    def register(self, t: Tool):
        if t.level not in ORDER:
            raise ToolError("Daraja A..E bo'lishi kerak")
        if t.level not in "AB" and not t.approval:
            raise ToolError(f"{t.id}: C–E darajali tool faqat tasdiq so'rovi orqali ishlaydi (approval=True)")
        self.tools[t.id] = t

    # ---------------- katalog ----------------
    def _register_builtin(self):
        c, R = self.core, self.register
        R(Tool("memory.search", "Xotiradan qidirish", "JARVIS xotirasidan (FTS) mos yozuvlarni topadi", "A",
               {"query": S("string", True, "qidiruv so'zlari"), "limit": S("integer", description="nechta (≤50)", default=10)},
               "yozuvlar ro'yxati (id, matn, manba, ishonch)", lambda a: c.memory.search(a["query"], min(int(a.get("limit", 10)), 50)),
               agents=["user", "manager", "memory_agent", "research", "business_analyst"]))
        R(Tool("memory.propose", "Xotiraga taklif", "Yangi bilimni xotiraga TAKLIF qiladi (foydalanuvchi tasdiqlaydi)", "B",
               {"content": S("string", True, "matn"), "kind": S("string", description="xotira turi", default="knowledge")},
               "taklif id", lambda a: self._propose_memory(a), agents=["user", "memory_agent", "research"], idempotent=False))
        R(Tool("files.list", "Papkani ko'rish", "Ruxsat berilgan papkadagi fayllar", "A", {"path": S("string", description="papka (bo'sh — asosiy)")},
               "fayllar ro'yxati", lambda a: c.files.list_dir(a.get("path") or None), agents=["user", "file_analysis", "manager"]))
        R(Tool("files.read", "Faylni o'qish", "Ruxsat berilgan papkadagi faylni o'qiydi (maxfiy fayllar o'qilmaydi)", "A", {"path": S("string", True, "fayl yo'li")},
               "matn va tahlil", lambda a: c.files.read(a["path"]), agents=["user", "file_analysis"]))
        R(Tool("assets.search", "Fayl qidirish", "Indekslangan fayllardan nom/matn bo'yicha qidiradi", "A",
               {"query": S("string", True, "so'zlar"), "category": S("string", description="document, image, ...")},
               "fayllar", lambda a: c.assets.search(a["query"], a.get("category", "")), agents=["user", "file_analysis", "manager"]))
        R(Tool("analyst.ask", "Biznes savoli", "Sinxronlangan POS/ERP ma'lumotidan savdo, foyda, qoldiq, qarz (manba bilan)", "A",
               {"question": S("string", True, "savol")}, "javob, manbalar, cheklovlar", lambda a: c.analyst.answer(a["question"]),
               agents=["user", "business_analyst", "pos_expert", "manager"]))
        R(Tool("business.forecast", "Savdo prognozi", "Kunlik savdo trendi va prognoz (taxmin)", "A", {"days": S("integer", description="1–30", default=7)},
               "prognoz", lambda a: c.business.forecast(max(1, min(int(a.get("days", 7)), 30))), agents=["user", "business_analyst"]))
        R(Tool("research.web", "Internet tadqiqoti", "Bir nechta manbani o'qib, manbali javob beradi (internet yoqilgan bo'lsa)", "A",
               {"query": S("string", True, "savol")}, "javob va manbalar", lambda a: c.research.answer(a["query"]),
               agents=["user", "research"], timeout=90, rate_per_min=6))
        R(Tool("simlab.mission", "Missiya dry-run", "Rejani bajarmasdan xavf va kerakli tasdiqlarni ko'rsatadi", "A", {"goal": S("string", True, "maqsad")},
               "bosqichlar va xavflar", lambda a: c.simlab.mission(a["goal"]), agents=["user", "manager"]))
        R(Tool("guardian.status", "Tizim holati", "CPU/RAM/disk, AI, xarajat, zaxira, xavfsizlik holati", "A", {}, "tekshiruvlar",
               lambda a: c.guardian.status(), agents=["user", "qa", "security", "manager"]))
        R(Tool("security.scan_text", "Matnni tekshirish", "Matnda maxfiy ma'lumot, injection belgisi va xavfli buyruq bor-yo'qligi", "A",
               {"text": S("string", True, "matn")}, "topilmalar", lambda a: c.agents.agents["security"].handler({"text": a["text"]}),
               agents=["user", "security", "manager"]))
        R(Tool("mission.create", "Missiya rejasi", "Maqsaddan reja tuzadi (boshlash — avtonomlik darajasi va xavfga ko'ra)", "B",
               {"goal": S("string", True, "maqsad")}, "missiya", lambda a: self._mission(a), agents=["user", "manager"], idempotent=False))
        R(Tool("computer.propose_command", "Kompyuter buyrug'i (taklif)", "Buyruqni tasdiqqa qo'yadi — bajarish faqat siz tasdiqlagandan keyin", "C",
               {"command": S("string", True, "buyruq"), "reason": S("string", description="nima uchun")}, "tasdiq so'rovi",
               lambda a: c.computer.propose(a["command"], a.get("reason", "")), agents=["user", "computer"], idempotent=False, approval=True, rate_per_min=10))
        R(Tool("integration.propose_write", "Tashqi tizimga yozish (taklif)", "POS/ERP/CRM'ga o'zgarish taklifi yoki tasdiq so'rovi (moliyaviy — E)", "D",
               {"conn_id": S("integer", True, "ulanish id"), "entity": S("string", True, "obyekt"), "operation": S("string", True, "create/update"),
                "payload": S("object", True, "ma'lumot")}, "taklif / tasdiq so'rovi",
               lambda a: c.integrations.request_write(int(a["conn_id"]), a["entity"], a["operation"], a["payload"]),
               agents=["user", "integration"], idempotent=False, approval=True, rate_per_min=5))

    def _propose_memory(self, a: dict) -> dict:
        from .memory import KINDS
        kind = a.get("kind", "knowledge")
        if kind not in KINDS or kind == "preference":
            raise ToolError("Xotira turi noto'g'ri (afzalliklarni faqat foydalanuvchi kiritadi)")
        if contains_secret(a["content"]):
            raise ToolError("Maxfiy ma'lumot xotiraga taklif qilinmaydi")
        return {"suggestion_id": self.core.db.execute(
            "INSERT INTO knowledge_findings(query, summary, sources, agreement) VALUES (?,?,?,?)",
            (f"[{kind}] taklif", a["content"][:4000], "[]", json.dumps({"note": "tool orqali taklif"}))).lastrowid,
            "note": "Taklif Knowledge Researcher → 'tasdiq kutayotgan xulosalar' da. Tasdiqlansa xotiraga yoziladi."}

    def _mission(self, a: dict) -> dict:
        m = self.core.missions.create(a["goal"], auto_start=True)
        return {"id": m["id"], "status": m["status"], "steps": len(m["graph"]["nodes"]), "questions": m["questions"]}

    # ---------------- ko'rish ----------------
    def catalog(self, agent: str | None = None) -> list[dict]:
        return [t.public() for t in self.tools.values() if agent is None or agent in t.agents]

    def calls(self, limit: int = 100, tool: str | None = None) -> list[dict]:
        return self.core.db.query("SELECT * FROM tool_calls" + (" WHERE tool=?" if tool else "") + " ORDER BY id DESC LIMIT ?",
                                  (tool, limit) if tool else (limit,))

    # ---------------- chaqirish ----------------
    def _validate(self, t: Tool, args: dict) -> dict:
        if not isinstance(args, dict):
            raise ToolError("Argumentlar obyekt bo'lishi kerak")
        unknown = set(args) - set(t.inputs)
        if unknown:
            raise ToolError(f"Noma'lum argument(lar): {sorted(unknown)}")
        out = {}
        for k, spec in t.inputs.items():
            if k not in args or args[k] in (None, ""):
                if spec.get("required"):
                    raise ToolError(f"'{k}' majburiy")
                if "default" in spec:
                    out[k] = spec["default"]
                continue
            v = args[k]
            typ = TYPES[spec["type"]]
            if spec["type"] == "integer" and isinstance(v, str) and v.strip().lstrip("-").isdigit():
                v = int(v)
            if not isinstance(v, typ) or (spec["type"] in ("integer", "number") and isinstance(v, bool)):
                raise ToolError(f"'{k}' turi {spec['type']} bo'lishi kerak")
            if isinstance(v, str) and len(v) > 20000:
                raise ToolError(f"'{k}' juda uzun")
            out[k] = v
        return out

    def _authorize(self, t: Tool, caller: str):
        if caller not in t.agents:
            raise ToolError(f"'{caller}' bu tool'ni chaqira olmaydi (ruxsat: {', '.join(t.agents)})")
        if caller != "user":
            agent = self.core.agents.agents.get(caller)
            if not agent or ORDER.index(t.level) > ORDER.index(agent.permission or "A"):
                raise ToolError(f"Agent ruxsat chegarasi ({agent.permission if agent else '?'}) {t.level} darajali tool uchun yetarli emas")
        if getattr(self.core, "automation_paused", False) and caller != "user" and t.level != "A":
            raise ToolError("Favqulodda to'xtatish yoqilgan — agentlar faqat o'qiy oladi")
        if int(self.core.settings.autonomy_level) <= 0 and t.level != "A":
            raise ToolError("Avtonomlik Level 0 (faqat maslahat): faqat o'qish tool'lari ishlaydi")
        recent = self.core.db.one("SELECT COUNT(*) n FROM tool_calls WHERE tool=? AND ts >= datetime('now','-1 minute')", (t.id,))["n"]
        if recent >= t.rate_per_min:
            raise ToolError(f"Daqiqalik limit ({t.rate_per_min}) tugadi — keyinroq urining")

    def invoke(self, tool_id: str, args: dict | None = None, caller: str = "user") -> dict:
        t = self.tools.get(tool_id)
        if not t:
            raise ToolError(f"Tool topilmadi: {tool_id}")
        safe_args = json.dumps(args or {}, ensure_ascii=False, default=str)
        h = hashlib.sha256(safe_args.encode()).hexdigest()[:16]
        log_args = redact(safe_args)[:1000]
        t0, attempts, status, err, result = time.monotonic(), 0, "error", None, None
        try:
            self._authorize(t, caller)
            a = self._validate(t, args or {})
            while True:
                attempts += 1
                fut = _POOL.submit(t.handler, a)
                try:
                    result = fut.result(timeout=t.timeout)
                    status = "approval_requested" if t.approval else "ok"
                    break
                except FutTimeout:
                    raise ToolError(f"Timeout ({t.timeout} s) — natija kutilmadi") from None
                except ToolError:
                    raise
                except Exception as e:
                    if t.idempotent and attempts < 2:
                        continue
                    raise ToolError(f"{type(e).__name__}: {e}") from None
        except ToolError as e:
            status, err = ("denied" if attempts == 0 else "error"), str(e)
            raise
        finally:
            ms = int((time.monotonic() - t0) * 1000)
            self.core.db.execute("INSERT INTO tool_calls(tool, caller, args, args_hash, status, duration_ms, attempts, error) VALUES (?,?,?,?,?,?,?,?)",
                                 (tool_id, caller, log_args, h, status, ms, max(attempts, 1), redact(err or "")[:300] or None))
            ev = getattr(self.core, "events", None)
            if ev:
                ev.publish("tool", tool=tool_id, caller=caller, status=status)
            if t.level not in "AB" or status != "ok":
                self.core.audit.log(caller, f"Tool: {tool_id} → {status}", target=tool_id, risk=t.level, result=status)
        return {"tool": tool_id, "status": status, "result": result, "attempts": attempts, "duration_ms": ms}
