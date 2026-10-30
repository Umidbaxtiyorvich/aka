"""Mission Engine — JARVIS markaziy avtonom miyasi: maqsad → tushunish → reja → ruxsat → bajarish → tekshirish → hisobot → xotira.

Mavjud modullar ustiga quriladi (takror yaratilmaydi):
* Reja: Planner (AI faqat matnni bosqichlarga ajratadi, agent va payload qoidalar bilan tanlanadi) + Task Graph (DAG).
* Bajarish: AgentManager agentlari; har bir xavfli amal agent ichida Approval Engine orqali tasdiq so'raydi.
* Ruxsat: Permission Manager rejadagi har bir bosqichni oldindan baholaydi (LOW/MEDIUM/HIGH/CRITICAL).
* Ishonchlilik: holat bazada (checkpoint = har tugagan bosqich), qayta urinish faqat idempotent agentlarda, dead-letter,
  pauza/davom/bekor, vaqt va xarajat limiti, qayta ishga tushganda tiklash.
* Tekshirish: har bosqich natijasi agent profilidagi qoida bo'yicha tekshiriladi; tekshirilmagan natija "bajarildi" deyilmaydi.
* Refleksiya: missiyadan keyin xulosalar — foydalanuvchi tasdiqlasa Procedural Memory'ga yoziladi.

Halollik: JARVIS hamma narsani qila olmaydi. Maxsus agenti yo'q bosqich (masalan "sayt dizaynini yarat") Boshqaruvchi
agentga — AI maslahat/reja matniga tushadi va hisobotda "faqat tavsiya, amal bajarilmadi" deb ko'rsatiladi.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, goal TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    understanding TEXT, plan_note TEXT, plan_source TEXT, risks TEXT, questions TEXT, dag_run_id INTEGER,
    max_minutes INTEGER NOT NULL DEFAULT 60, max_cost REAL NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 2,
    created_at TEXT NOT NULL DEFAULT (datetime('now')), started_at TEXT, finished_at TEXT, stop_reason TEXT,
    report TEXT, reflection TEXT
);
CREATE TABLE IF NOT EXISTS mission_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id INTEGER NOT NULL, ts TEXT NOT NULL DEFAULT (datetime('now')), stage TEXT NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS mission_lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id INTEGER NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', memory_id INTEGER
);
"""
STATUSES = {"pending": "Kutmoqda (reja tayyor)", "planning": "Rejalashtirilmoqda", "waiting_approval": "Tasdiq kutmoqda", "running": "Bajarilmoqda",
            "paused": "To'xtatilgan", "retrying": "Qayta urinilmoqda", "verifying": "Tekshirilmoqda", "completed": "Bajarildi", "failed": "Bajarilmadi",
            "cancelled": "Bekor qilindi", "needs_input": "Ma'lumot kerak"}
DAG_TO_MISSION = {"done": "completed", "partial": "failed", "failed": "failed", "waiting_approval": "waiting_approval", "paused": "paused", "cancelled": "cancelled"}
VAGUE = re.compile(r"(?i)^(bir narsa|nimadir|shunaqa|qil|yordam ber|something|do it|help)\W*$")
CRITICAL_WORDS = re.compile(r"(?i)\b(pul o'tkaz|to'lov qil|o'chir|delete|remove|format|tozalab tashla|перевод|оплат|удали)\b")


class MissionError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class MissionEngine:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        core.dag.verifier = self.verify
        self._threads: dict[int, threading.Thread] = {}

    # ---------------- log ----------------
    def _log(self, mid: int, stage: str, note: str = ""):
        self.core.db.execute("INSERT INTO mission_log(mission_id, stage, note) VALUES (?,?,?)", (mid, stage, note[:500]))
        ev = getattr(self.core, "events", None)
        if ev:
            ev.publish("mission", id=mid, stage=stage)

    def _set(self, mid: int, **f):
        cols = ", ".join(f"{k}=?" for k in f)
        self.core.db.execute(f"UPDATE missions SET {cols} WHERE id=?", (*[json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in f.values()], mid))

    # ---------------- 1. Tushunish ----------------
    def understand(self, goal: str) -> dict:
        from . import intent as intent_mod
        it, conf = intent_mod.detect(goal)
        words = re.findall(r"\w+", goal)
        questions = []
        if len(words) < 3 or VAGUE.match(goal.strip()):
            questions.append("Maqsadni aniqroq yozing: nima qilinsin, qaysi fayl/tizim bilan va natija qanday bo'lsin?")
        if re.search(r"(?i)telegram", goal) and not self.core.telegram.token():
            questions.append("Telegram bot tokeni kiritilmagan — Telegram bo'limida ulang yoki bu qismni olib tashlang.")
        if re.search(r"(?i)instagram", goal) and not self.core.settings.instagram_accounts:
            questions.append("Instagram akkaunti ulanmagan — Instagram bo'limida ulang.")
        return {"intent": it, "confidence": conf, "questions": questions, "critical_words": bool(CRITICAL_WORDS.search(goal))}

    # ---------------- 2. Reja ----------------
    def _plan_nodes(self, goal: str, use_ai: bool | None) -> tuple[list[dict], str, str]:
        from .dag import PARALLEL_SPLIT
        from .planner import split_goal, step_for
        parts, note, source = None, "qoidalar bo'yicha ajratildi", "rules"
        if use_ai is not False:
            parts, note = self.core.planner._ai_split(goal)
            source = "ai" if parts else "rules"
        stages = [[p] for p in parts] if parts else [[x.strip() for x in PARALLEL_SPLIT.split(st) if x.strip()] for st in split_goal(goal)]
        nodes, prev = [], []
        for si, stage in enumerate(stages[:12]):
            cur = []
            for pi, part in enumerate(stage):
                st = step_for(part)
                key = f"s{si + 1}_{pi + 1}"
                nodes.append({"key": key, "title": part[:200], "agent": st["agent"], "payload": st["payload"], "depends_on": list(prev)})
                cur.append(key)
            prev = cur
        return nodes, note, source

    def create(self, goal: str, *, use_ai: bool | None = None, max_minutes: int = 60, max_cost: float = 0.0, max_attempts: int = 2,
               auto_start: bool = False, due_at: str | None = None) -> dict:
        goal = (goal or "").strip()
        if not goal:
            raise MissionError("Maqsad bo'sh")
        if len(goal) > 4000:
            raise MissionError("Maqsad juda uzun (4000 belgigacha)")
        cur = self.core.db.execute("INSERT INTO missions(goal, status, max_minutes, max_cost, max_attempts) VALUES (?,?,?,?,?)",
                                   (goal, "planning", max(1, min(int(max_minutes), 24 * 60)), max(0.0, float(max_cost)), max(1, min(int(max_attempts), 5))))
        mid = cur.lastrowid
        if due_at:
            self._set(mid, due_at=str(due_at)[:25])
        self._log(mid, "tushunish", goal[:200])
        u = self.understand(goal)
        nodes, note, source = self._plan_nodes(goal, use_ai)
        risks = []
        for n in nodes:
            a = self.core.permissions.assess(n["agent"], n["payload"])
            risks.append({"key": n["key"], "title": n["title"], **a})
            if not a["allowed"]:
                n["agent"], n["payload"] = "manager", {"text": n["title"]}       # ruxsatsiz bosqich — faqat maslahat
        run = self.core.dag.create(goal, nodes)
        self.core.db.execute("UPDATE dag_nodes SET max_attempts=? WHERE run_id=?", (max(1, min(int(max_attempts), 5)), run["id"]))
        if u["critical_words"]:
            risks.append({"key": "*", "title": "Maqsadda qaytarib bo'lmaydigan amal so'zlari bor (o'chirish/to'lov)", "risk": "CRITICAL", "level": "E",
                          "allowed": True, "needs_approval": True})
        status = "needs_input" if u["questions"] else "pending"
        self._set(mid, status=status, understanding=u, plan_note=note, plan_source=source, risks=risks, questions=u["questions"], dag_run_id=run["id"])
        self._log(mid, "reja", f"{len(nodes)} bosqich ({source}); {note}")
        self.core.audit.log("mission", f"Missiya yaratildi #{mid}: {goal[:80]}", target=f"mission#{mid}", risk="B")
        if auto_start and status == "pending" and self.may_auto_start(risks):
            self.start(mid)
        return self.get(mid)

    def answer(self, mid: int, text: str) -> dict:
        """Savollarga javob — maqsad aniqlashtiriladi va reja qayta tuziladi (eski reja bekor)."""
        m = self.get(mid)
        if m["status"] not in ("needs_input", "pending"):
            raise MissionError("Faqat boshlanmagan missiyani aniqlashtirish mumkin")
        self.core.dag.cancel(m["dag_run_id"])
        self._set(mid, status="cancelled", stop_reason="aniqlashtirildi — yangi missiya yaratildi", finished_at=_now())
        return self.create(f"{m['goal']}. {text.strip()}", max_minutes=m["max_minutes"], max_cost=m["max_cost"], max_attempts=m["max_attempts"])

    # ---------------- 3–5. Bajarish ----------------
    def start(self, mid: int, background: bool = True) -> dict:
        m = self.get(mid)
        if m["status"] in ("running", "verifying", "retrying"):
            raise MissionError("Missiya allaqachon bajarilmoqda")
        if m["status"] in ("completed", "cancelled"):
            raise MissionError("Tugagan yoki bekor qilingan missiyani qayta boshlab bo'lmaydi")
        if m["status"] == "needs_input":
            raise MissionError("Avval savollarga javob bering")
        if getattr(self.core, "automation_paused", False):
            raise MissionError("Favqulodda to'xtatish yoqilgan — avval avtomatikani qayta yoqing")
        if int(self.core.settings.autonomy_level) <= 0:
            raise MissionError("Avtonomlik darajasi 0 (faqat maslahat) — missiya bajarilmaydi, faqat reja ko'rsatiladi")
        self._set(mid, status="running", started_at=m["started_at"] or _now(), stop_reason=None, finished_at=None)
        self._log(mid, "bajarish", "boshlandi" if not m["started_at"] else "davom ettirildi (oxirgi checkpointdan)")
        self.core.audit.log("user", f"Missiya ishga tushirildi #{mid}", target=f"mission#{mid}", risk="B", approval_status="user_action")
        if background:
            th = threading.Thread(target=self._execute, args=(mid,), daemon=True)
            self._threads[mid] = th
            th.start()
        else:
            self._execute(mid)
        return self.get(mid)

    def _stop_check(self, mid: int):
        def check():
            if getattr(self.core, "automation_paused", False):
                return "favqulodda to'xtatish (Guardian / Telegram)"
            m = self.core.db.one("SELECT * FROM missions WHERE id=?", (mid,))
            if m["status"] in ("paused", "cancelled"):
                return m["stop_reason"] or "foydalanuvchi to'xtatdi"
            if m["started_at"]:
                elapsed = (datetime.now(timezone.utc) - datetime.strptime(m["started_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)).total_seconds()
                if elapsed > m["max_minutes"] * 60:
                    return f"vaqt limiti tugadi ({m['max_minutes']} daqiqa)"
            if m["max_cost"] > 0 and self._cost(m) > m["max_cost"]:
                return f"xarajat limiti tugadi ({m['max_cost']} {self.core.settings.currency})"
            return None
        return check

    def _cost(self, m: dict) -> float:
        r = self.core.db.one("SELECT COALESCE(SUM(cost),0) c FROM ai_usage WHERE ts>=?", (m["started_at"] or m["created_at"],))
        return round(r["c"] or 0, 6)

    def _execute(self, mid: int):
        m = self.get(mid)
        try:
            run = self.core.dag.run(m["dag_run_id"], stop_check=self._stop_check(mid))
        except Exception as e:
            self._set(mid, status="failed", stop_reason=f"{type(e).__name__}: {e}"[:300], finished_at=_now())
            self._log(mid, "xato", str(e))
            return
        cur = self.core.db.one("SELECT status FROM missions WHERE id=?", (mid,))["status"]
        if cur == "cancelled":
            self.core.dag.cancel(m["dag_run_id"])
            run = self.core.dag.get(m["dag_run_id"])
        self._set(mid, status="verifying")
        self._log(mid, "tekshirish", f"graf holati: {run['status']}")
        report = self.report(mid)
        final = "cancelled" if cur == "cancelled" else DAG_TO_MISSION.get(run["status"], "failed")
        fields = {"status": final, "report": report}
        if final in ("completed", "failed", "cancelled"):
            fields["finished_at"] = _now()
        if final == "paused":
            fields["stop_reason"] = run.get("stop_reason") or "to'xtatildi"
        self._set(mid, **fields)
        self._log(mid, "natija", STATUSES[final] + (f" — {fields.get('stop_reason')}" if fields.get("stop_reason") else ""))
        if final in ("completed", "failed"):
            self.reflect(mid)
            self.core.notifier.notify(f"Missiya #{mid}: {STATUSES[final]}", m["goal"][:150], severity="info" if final == "completed" else "warning", category="task")

    def pause(self, mid: int) -> dict:
        m = self.get(mid)
        if m["status"] not in ("running", "retrying"):
            raise MissionError("Faqat bajarilayotgan missiyani to'xtatish mumkin")
        self._set(mid, status="paused", stop_reason="foydalanuvchi to'xtatdi")
        self.core.dag.pause(m["dag_run_id"], "foydalanuvchi to'xtatdi")
        self._log(mid, "pauza", "foydalanuvchi to'xtatdi — ishlayotgan bosqich tugagach to'xtaydi")
        return self.get(mid)

    def pause_all(self, reason: str) -> list[int]:
        ids = [r["id"] for r in self.core.db.query("SELECT id FROM missions WHERE status IN ('running','retrying','verifying')")]
        for mid in ids:
            m = self.get(mid, with_report=False)
            self._set(mid, status="paused", stop_reason=reason)
            self.core.dag.pause(m["dag_run_id"], reason)
            self._log(mid, "pauza", reason)
        return ids

    def cancel(self, mid: int) -> dict:
        m = self.get(mid)
        if m["status"] in ("completed", "cancelled"):
            raise MissionError("Missiya allaqachon tugagan")
        self._set(mid, status="cancelled", stop_reason="foydalanuvchi bekor qildi", finished_at=_now())
        self.core.dag.cancel(m["dag_run_id"])
        self._log(mid, "bekor", "foydalanuvchi bekor qildi")
        return self.get(mid)

    def retry_step(self, mid: int, key: str) -> dict:
        m = self.get(mid)
        self.core.dag.retry_node(m["dag_run_id"], key)
        self._set(mid, status="pending", finished_at=None)
        self._log(mid, "qayta", f"{key} qayta navbatga qo'yildi")
        return self.get(mid)

    def may_auto_start(self, risks: list[dict]) -> bool:
        """Avtonomlik darajasi: 0–1 — hech qachon o'zi boshlamaydi; 2 — faqat LOW; 3–4 — HIGH/CRITICAL bo'lmasa.
        Har qanday darajada MEDIUM+ amallar agent ichida Approval Engine orqali tasdiq so'raydi."""
        lvl = int(self.core.settings.autonomy_level)
        risk = {r.get("risk") for r in risks}
        if lvl <= 1 or getattr(self.core, "automation_paused", False):
            return False
        if lvl == 2:
            return risk <= {"LOW"}
        return not (risk & {"HIGH", "CRITICAL"})

    def recover(self, resume: bool = False) -> list[int]:
        """Server qayta ishga tushganda: uzilgan missiyalar pauzaga, xohlansa — oxirgi checkpointdan davom."""
        self.core.dag.recover()
        ids = [r["id"] for r in self.core.db.query("SELECT id FROM missions WHERE status IN ('running','verifying','retrying')")]
        for mid in ids:
            self._set(mid, status="paused", stop_reason="JARVIS qayta ishga tushdi")
            self._log(mid, "tiklash", "server qayta ishga tushdi — checkpoint saqlangan")
            if resume and int(self.core.settings.autonomy_level) >= 4:      # o'zi davom ettirish — faqat Level 4
                self.start(mid)
        return ids

    # ---------------- Tekshirish ----------------
    def verify(self, node: dict, task: dict) -> tuple[bool, str]:
        from .permissions import PROFILES
        rule = (PROFILES.get(node["agent"]) or ("", "", "", "no_error"))[3]
        try:
            res = json.loads(task.get("result") or "null")
        except (TypeError, ValueError):
            res = task.get("result")
        if res in (None, "", {}, []):
            return False, "natija bo'sh"
        if isinstance(res, dict):
            if res.get("error") and not res.get("needs_approval"):
                return False, f"agent xato qaytardi: {str(res['error'])[:150]}"
            if rule == "tests" and isinstance(res.get("tests"), dict) and res["tests"].get("failed"):
                return False, f"testlar muvaffaqiyatsiz: {res['tests'].get('failed')}"
            if rule == "sources" and not (res.get("sources") or res.get("results") or res.get("url")):
                return False, "manba ko'rsatilmagan"
            if rule == "text" and not str(res.get("text") or res.get("answer") or "").strip():
                return False, "javob matni bo'sh"
        return True, "tekshiruvdan o'tdi" + (" (AI maslahati — amal bajarilmagan)" if node["agent"] == "manager" else "")

    # ---------------- Hisobot va refleksiya ----------------
    def report(self, mid: int) -> dict:
        m = self.get(mid, with_report=False)
        run = self.core.dag.get(m["dag_run_id"])
        steps = []
        for n in run["nodes"]:
            steps.append({"key": n["key"], "title": n["title"], "agent": n["agent"], "status": n["status"], "attempts": n.get("attempts") or 0,
                          "verified": n.get("verified"), "verify_note": n.get("verify_note"), "error": n.get("error"), "dead_letter": bool(n.get("dead_letter")),
                          "advice_only": n["agent"] == "manager", "approval_id": n.get("approval_id")})
        usage = self.core.db.query("SELECT provider, model, COUNT(*) n, ROUND(SUM(cost),6) cost, SUM(ok=0) errors FROM ai_usage WHERE ts>=? "
                                   "AND (? IS NULL OR ts<=?) GROUP BY provider, model", (m["started_at"] or m["created_at"], m["finished_at"], m["finished_at"]))
        done = [s for s in steps if s["status"] in ("done", "reused")]
        return {"steps": steps, "done": len(done), "total": len(steps), "advice_only": sum(s["advice_only"] for s in done),
                "failed": [s["key"] for s in steps if s["status"] in ("failed", "blocked")], "waiting_approval": [s["key"] for s in steps if s["status"] == "waiting_approval"],
                "dead_letter": [s["key"] for s in steps if s["dead_letter"]], "models": usage, "cost": self._cost(m),
                "note": "Xarajat — missiya davomidagi barcha AI so'rovlari (taxminiy: shu vaqtdagi boshqa so'rovlar ham kirishi mumkin)."}

    def reflect(self, mid: int) -> dict:
        m = self.get(mid)
        r = m["report"] or self.report(mid)
        lessons = []
        for s in r["steps"]:
            if s["attempts"] and s["attempts"] > 1 and s["status"] == "done":
                lessons.append(f"«{s['title'][:80]}» ({s['agent']}) {s['attempts']}-urinishda bajarildi — shu turdagi vazifalarda qayta urinish foydali.")
            if s["status"] in ("failed", "blocked") and s["error"]:
                lessons.append(f"«{s['title'][:80]}» bajarilmadi: {s['error'][:160]}")
            if s["advice_only"] and s["status"] == "done":
                lessons.append(f"«{s['title'][:80]}» uchun maxsus agent yo'q — faqat AI maslahati berildi (yangi skill kerak bo'lishi mumkin).")
        for u in r["models"]:
            if u["errors"]:
                lessons.append(f"{u['provider']} ({u['model']}) missiya davomida {u['errors']} marta xato berdi.")
        summary = {"goal_reached": m["status"] == "completed" and not r["failed"], "done": r["done"], "total": r["total"], "cost": r["cost"], "lessons": lessons}
        self._set(mid, reflection=summary)
        for text in lessons[:10]:
            self.core.db.execute("INSERT INTO mission_lessons(mission_id, content) VALUES (?,?)", (mid, text))
        self._log(mid, "refleksiya", f"{len(lessons)} ta xulosa (tasdiq kutmoqda)")
        return summary

    def lessons(self, status: str = "pending") -> list[dict]:
        return self.core.db.query("SELECT l.*, m.goal FROM mission_lessons l JOIN missions m ON m.id=l.mission_id WHERE l.status=? ORDER BY l.id DESC LIMIT 100", (status,))

    def decide_lesson(self, lid: int, accept: bool) -> dict:
        lesson = self.core.db.one("SELECT * FROM mission_lessons WHERE id=?", (lid,))
        if not lesson or lesson["status"] != "pending":
            raise MissionError("Xulosa topilmadi yoki ko'rib chiqilgan")
        mem_id = None
        if accept:
            mem = self.core.memory.add(lesson["content"], "procedural", source="mission_reflection", info_type="fact",
                                       reference=f"mission#{lesson['mission_id']}", title=f"Tajriba: missiya #{lesson['mission_id']}")
            mem_id = mem["id"]
        self.core.db.execute("UPDATE mission_lessons SET status=?, memory_id=? WHERE id=?", ("accepted" if accept else "rejected", mem_id, lid))
        return {"ok": True, "memory_id": mem_id}

    # ---------------- ko'rish ----------------
    def get(self, mid: int, with_report: bool = True) -> dict:
        m = self.core.db.one("SELECT * FROM missions WHERE id=?", (mid,))
        if not m:
            raise MissionError("Missiya topilmadi")
        for k in ("understanding", "risks", "questions", "report", "reflection"):
            m[k] = json.loads(m[k]) if m[k] else None
        m["status_label"] = STATUSES.get(m["status"], m["status"])
        if with_report:
            run = self.core.dag.get(m["dag_run_id"]) if m["dag_run_id"] else None
            m["graph"] = run
            m["log"] = self.core.db.query("SELECT ts, stage, note FROM mission_log WHERE mission_id=? ORDER BY id", (mid,))
            m["progress"] = round(100 * sum(n["status"] in ("done", "reused") for n in run["nodes"]) / max(1, len(run["nodes"]))) if run else 0
        return m

    def list(self, limit: int = 30) -> list[dict]:
        return [self.get(r["id"], with_report=False) | {"progress": self._progress(r["dag_run_id"])}
                for r in self.core.db.query("SELECT id, dag_run_id FROM missions ORDER BY id DESC LIMIT ?", (limit,))]

    def _progress(self, rid) -> int:
        if not rid:
            return 0
        r = self.core.db.one("SELECT COUNT(*) n, SUM(status IN ('done','reused')) d FROM dag_nodes WHERE run_id=?", (rid,))
        return round(100 * (r["d"] or 0) / max(1, r["n"]))

    def wait(self, mid: int, timeout: float = 30) -> dict:
        th = self._threads.get(mid)
        if th:
            th.join(timeout)
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout and self.get(mid, False)["status"] in ("running", "verifying", "retrying"):
            time.sleep(0.05)
        return self.get(mid)
