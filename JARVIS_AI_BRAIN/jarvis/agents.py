"""Agent Manager va agentlar. Har bir agent — haqiqiy handler funksiyasi.
Hali yaratilmagan agentlar 'planned' deb aniq belgilanadi va vazifa qabul qilmaydi.
Vazifalar bitta navbat orqali ketma-ket bajariladi (8 GB RAM uchun resurs tejash)."""
from __future__ import annotations

import ast
import json
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from .security import classify_command, contains_secret, injection_score


@dataclass
class Agent:
    key: str
    title: str
    role: str
    tools: list[str]
    permission: str                  # maksimal daraja: A..E
    handler: Callable | None = None
    status: str = "idle"             # idle | running | error | planned
    current_task: int | None = None
    last_result: str | None = None
    last_error: str | None = None
    history: list[int] = field(default_factory=list)

    def public(self) -> dict:
        return {k: getattr(self, k) for k in ("key", "title", "role", "tools", "permission", "status",
                                             "current_task", "last_result", "last_error")} | {
            "implemented": self.handler is not None, "recent_tasks": self.history[-10:]}


class AgentManager:
    def __init__(self, core):
        self.core = core
        self.agents: dict[str, Agent] = {}
        self.q: queue.Queue[int] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._register()

    # --- ro'yxat ---
    def _register(self):
        A = self._add
        A("manager", "Boshqaruvchi", "Xabarni tahlil qilib, tegishli agentga yo'naltiradi", ["intent", "planner"], "B", self._h_manager)
        A("developer", "Dasturchi", "Python kodini sintaksis va tuzilma bo'yicha tahlil qiladi", ["ast"], "B", self._h_developer)
        A("file_analysis", "Fayl tahlilchisi", "Ruxsat berilgan fayllarni o'qiydi va tahlil qiladi", ["files"], "A", self._h_files)
        A("computer", "Kompyuter agenti", "Buyruqni taklif qiladi; bajarish faqat tasdiqdan keyin", ["shell (tasdiq bilan)"], "E", self._h_computer)
        A("security", "Xavfsizlik agenti", "Matn/buyruqda maxfiy ma'lumot, injection va xavfni tekshiradi", ["security"], "A", self._h_security)
        A("qa", "Nazoratchi (QA)", "Modullar holatini tekshiradi va testlarni ishga tushiradi", ["selfcheck", "pytest"], "A", self._h_qa)
        for key, title, role in [
            ("research", "Tadqiqotchi", "Internetdan qidirish (keyingi bosqich)"),
            ("browser", "Brauzer agenti", "Playwright orqali saytlar (keyingi bosqich)"),
            ("voice", "Ovoz agenti", "STT/TTS (keyingi bosqich)"),
            ("image", "Rasm agenti", "Rasm yaratish/tahrirlash (keyingi bosqich)"),
            ("video", "Video agenti", "FFmpeg bilan video (keyingi bosqich)"),
            ("instagram", "Instagram agenti", "Meta rasmiy API (keyingi bosqich)"),
            ("telegram", "Telegram agenti", "Bot va bildirishnomalar (keyingi bosqich)"),
            ("bi", "Biznes tahlilchi", "Savdo va ombor tahlili (keyingi bosqich)"),
            ("pos", "POS agenti", "POS o'qish/kiritish (keyingi bosqich)"),
        ]:
            A(key, title, role, [], "A", None, status="planned")

    def _add(self, key, title, role, tools, perm, handler, status="idle"):
        self.agents[key] = Agent(key, title, role, tools, perm, handler, status=status)

    # --- navbat ---
    def submit(self, agent_key: str, title: str, payload: dict, run_now: bool = False) -> dict:
        agent = self.agents.get(agent_key)
        if not agent:
            raise KeyError(f"Agent topilmadi: {agent_key}")
        if agent.handler is None:
            raise ValueError(f"'{agent.title}' hali yaratilmagan (rejada).")
        cur = self.core.db.execute("INSERT INTO tasks(title, agent, payload) VALUES (?,?,?)",
                                   (title, agent_key, json.dumps(payload, ensure_ascii=False)))
        tid = cur.lastrowid
        agent.history.append(tid)
        if run_now:
            self._run(tid)
        else:
            self.q.put(tid)
            self._ensure_worker()
        return self.task(tid)

    def _ensure_worker(self):
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._loop, daemon=True)
            self._worker.start()

    def _loop(self):
        while True:
            tid = self.q.get()
            try:
                self._run(tid)
            finally:
                self.q.task_done()

    def _run(self, tid: int):
        t = self.task(tid)
        agent = self.agents[t["agent"]]
        agent.status, agent.current_task = "running", tid
        self.core.db.execute("UPDATE tasks SET status='running' WHERE id=?", (tid,))
        try:
            result = agent.handler(json.loads(t["payload"] or "{}"))
            text = json.dumps(result, ensure_ascii=False, default=str)
            status = "waiting_approval" if isinstance(result, dict) and result.get("needs_approval") else "done"
            self.core.db.execute("UPDATE tasks SET status=?, result=?, finished_at=? WHERE id=?",
                                 (status, text[:20000], datetime.now(timezone.utc).isoformat(), tid))
            agent.status, agent.last_result, agent.last_error = "idle", text[:300], None
            self.core.audit.log(agent.key, f"Vazifa bajarildi: {t['title']}", target=f"task#{tid}", risk="A",
                                result=status)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            self.core.db.execute("UPDATE tasks SET status='failed', error=?, finished_at=? WHERE id=?",
                                 (msg, datetime.now(timezone.utc).isoformat(), tid))
            agent.status, agent.last_error = "error", msg
            self.core.audit.log(agent.key, f"Vazifa xatosi: {t['title']}", target=f"task#{tid}", risk="A",
                                error_code=type(e).__name__, error_note=str(e))
            self.core.audit.error(agent.key, msg)
        finally:
            agent.current_task = None

    def task(self, tid: int) -> dict:
        return self.core.db.one("SELECT * FROM tasks WHERE id=?", (tid,))

    def tasks(self, limit: int = 50) -> list[dict]:
        return self.core.db.query("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,))

    # --- handlerlar ---
    def _h_manager(self, p):
        return self.core.route(p.get("text", ""))

    def _h_developer(self, p):
        code = p.get("code", "")
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {"ok": False, "error": f"Sintaksis xatosi {e.lineno}-qatorda: {e.msg}",
                    "hint": "Shu qatordagi qavslar, ikki nuqta va bo'shliqlarni tekshiring."}
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        bare = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.type is None)
        issues = []
        if bare:
            issues.append(f"{bare} ta 'except:' (turi ko'rsatilmagan) — xatolarni yashirishi mumkin")
        if contains_secret(code):
            issues.append("Kodda maxfiy kalit/parolga o'xshash qiymat bor — uni secret storage'ga o'tkazing")
        if "eval(" in code or "exec(" in code:
            issues.append("eval/exec ishlatilgan — xavfli")
        return {"ok": True, "functions": funcs, "classes": classes, "lines": code.count("\n") + 1, "issues": issues}

    def _h_files(self, p):
        fi = self.core.files
        if p.get("op") == "list":
            return {"items": fi.list_dir(p.get("path"))}
        if p.get("op") == "search":
            return {"matches": fi.search(p.get("pattern", ""))}
        r = fi.read(p["path"])
        r["text"] = r["text"][:5000]
        return r

    def _h_computer(self, p):
        res = self.core.computer.propose(p["command"], p.get("reason", ""))
        res["needs_approval"] = res["approval"]["status"] == "pending"
        return res

    def _h_security(self, p):
        text = p.get("text", "")
        return {"contains_secret": contains_secret(text), "injection_markers": injection_score(text),
                "command_risk": classify_command(text) if p.get("is_command") else None}

    def _h_qa(self, p):
        from . import selfcheck
        out = {"health": selfcheck.health(self.core)}
        if p.get("run_tests"):
            out["tests"] = selfcheck.run_tests()
        return out
