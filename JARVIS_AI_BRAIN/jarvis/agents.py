"""Agent Manager va agentlar. Har bir agent — haqiqiy handler funksiyasi.
Tashqi xizmatga ulanmagan agentlar (Telegram, Instagram) aniq xato qaytaradi — ishlayotgandek ko'rsatilmaydi.
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
        A("research", "Tadqiqotchi", "Internetdan qidiradi, manba/sana/ishonch bilan javob beradi", ["web search", "fetch"], "A", self._h_research)
        A("browser", "Brauzer agenti", "Ruxsat berilgan saytni faqat o'qiydi va tuzilishini hujjatlashtiradi", ["playwright"], "A", self._h_browser)
        A("voice", "Ovoz agenti", "STT/TTS dvigatellari holati, mahalliy Whisper", ["web speech", "faster-whisper"], "B", self._h_voice)
        A("image", "Rasm agenti", "Rasm tahlili, o'lcham, matn, logo, generator prompti", ["pillow"], "B", self._h_image)
        A("video", "Video agenti", "FFmpeg: kesish, birlashtirish, 9:16, subtitr, ovoz, sifat", ["ffmpeg"], "B", self._h_video)
        A("instagram", "Instagram agenti", "Post/Reels/Stories loyihasi, kalendar, nashr (tasdiq bilan)", ["graph api"], "D", self._h_instagram)
        A("telegram", "Telegram agenti", "Bot holati va bildirishnomalar", ["bot api"], "D", self._h_telegram)
        A("bi", "Biznes tahlilchi", "Savdo, ombor, foyda, qarzdorlik tahlili", ["bi"], "B", self._h_bi)
        A("pos", "POS agenti", "Hujjat loyihasi va tasdiq so'rovi (kiritish faqat tasdiqdan keyin)", ["pos connector"], "D", self._h_pos)

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
        self.core.db.execute("UPDATE tasks SET status='running', started_at=? WHERE id=?",
                             (datetime.now(timezone.utc).isoformat(), tid))
        tg = getattr(self.core, "telegram", None)
        ev = getattr(self.core, "events", None)
        if ev:
            ev.publish("task.start", id=tid, agent=t["agent"], title=t["title"][:80])
        if tg:
            tg.event("task", f"Vazifa boshlandi: #{tid} {t['title'][:80]}", f"Agent: {agent.title}")
        try:
            result = agent.handler(json.loads(t["payload"] or "{}"))
            text = json.dumps(result, ensure_ascii=False, default=str)
            status = "waiting_approval" if isinstance(result, dict) and result.get("needs_approval") else "done"
            self.core.db.execute("UPDATE tasks SET status=?, result=?, finished_at=? WHERE id=?",
                                 (status, text[:20000], datetime.now(timezone.utc).isoformat(), tid))
            agent.status, agent.last_result, agent.last_error = "idle", text[:300], None
            self.core.audit.log(agent.key, f"Vazifa bajarildi: {t['title']}", target=f"task#{tid}", risk="A",
                                result=status)
            if tg:
                tg.event("task", f"Vazifa {'tasdiq kutmoqda' if status == 'waiting_approval' else 'tugadi'}: #{tid} {t['title'][:80]}")
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            self.core.db.execute("UPDATE tasks SET status='failed', error=?, finished_at=? WHERE id=?",
                                 (msg, datetime.now(timezone.utc).isoformat(), tid))
            agent.status, agent.last_error = "error", msg
            self.core.audit.log(agent.key, f"Vazifa xatosi: {t['title']}", target=f"task#{tid}", risk="A",
                                error_code=type(e).__name__, error_note=str(e))
            if tg:
                tg.event("task", f"Vazifa bajarilmadi: #{tid} {t['title'][:80]}", msg[:300], severity="warning")
            self.core.audit.error(agent.key, msg)
        finally:
            agent.current_task = None
            if ev:
                row = self.core.db.one("SELECT status FROM tasks WHERE id=?", (tid,))
                ev.publish("task.end", id=tid, agent=t["agent"], status=row["status"] if row else "unknown")
            if hasattr(self.core, "kgraph"):
                try:
                    self.core.kgraph.on_task(t)
                except Exception:
                    pass

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

    def _h_research(self, p):
        r = self.core.research
        return r.fetch(p["url"]) if p.get("op") == "fetch" else r.answer(p["query"])

    def _h_browser(self, p):
        b = self.core.browser
        return b.site_map(p["url"]) if p.get("op") == "site_map" else b.inspect(p["url"])

    def _h_voice(self, p):
        v = self.core.voice
        if p.get("op") == "transcribe":
            return v.transcribe(str(self.core.files._check_read(p["path"])))
        if p.get("op") == "tts":
            return v.synthesize(p["text"], speed=int(p.get("speed", 150)))
        return v.status()

    def _h_image(self, p):
        st, op = self.core.studio, p.get("op", "analyze")
        ops = {"analyze": lambda: st.analyze_image(p["path"]), "resize": lambda: st.resize(p["path"], p["preset"], p.get("mode", "fit")),
               "text": lambda: st.add_text(p["path"], p["text"], p.get("position", "bottom")),
               "logo": lambda: st.make_logo(p["text"], shape=p.get("shape", "circle")),
               "prompt": lambda: st.image_prompt(p["subject"], p.get("purpose", "instagram_post"), p.get("style", "zamonaviy, toza")),
               "generate": lambda: self.core.imagegen.generate(p["prompt"], negative=p.get("negative", ""), width=int(p.get("width", 1024)),
                                                               height=int(p.get("height", 1024)), steps=int(p.get("steps", 25))),
               "edit": lambda: self.core.imagegen.edit(p["path"], p["prompt"], strength=float(p.get("strength", 0.5))),
               "describe": lambda: self.core.imagegen.describe(p["path"], p.get("question") or "Bu rasmda nima tasvirlangan? O'zbek tilida qisqa tasvirlab ber.")}
        if op not in ops:
            raise ValueError(f"op: {list(ops)}")
        return ops[op]()

    def _h_video(self, p):
        st, op = self.core.studio, p.get("op", "probe")
        ops = {"probe": lambda: st.probe(p["path"]), "quality": lambda: st.quality_check(p["path"], p.get("target", "reels")),
               "trim": lambda: st.trim(p["path"], float(p["start"]), float(p["end"])), "concat": lambda: st.concat(p["paths"]),
               "vertical": lambda: st.to_vertical(p["path"], p.get("mode", "pad")), "convert": lambda: st.convert(p["path"], p["format"]),
               "subtitles": lambda: st.add_subtitles(p["path"], p["lines"], p.get("burn", True)),
               "audio": lambda: st.add_audio(p["path"], p["audio"], p.get("mix", False)),
               "slideshow": lambda: st.slideshow(p["images"], float(p.get("seconds", 3)), p.get("audio")),
               "auto_subtitles": lambda: st.auto_subtitles(p["path"], p.get("burn", True), p.get("language", "uz")),
               "voiceover": lambda: st.voiceover(p["path"], p["text"], p.get("mix", False), int(p.get("speed", 150)))}
        if op not in ops:
            raise ValueError(f"op: {list(ops)}")
        return ops[op]()

    def _h_instagram(self, p):
        ig, op = self.core.instagram, p.get("op", "status")
        if op == "draft":
            return ig.draft(p["account"], p.get("kind", "post"), p["caption"], p.get("media_url", ""), p.get("scheduled_at", ""))
        if op == "preview":
            return ig.preview(int(p["id"]))
        if op == "request_publish":
            return {"approval": ig.request_publish(int(p["id"])), "needs_approval": True}
        if op == "hashtags":
            from .instagram import suggest_hashtags
            return {"hashtags": suggest_hashtags(p.get("text", ""))}
        return {"accounts": [ig.account_status(a["name"]) for a in ig.accounts()]}

    def _h_telegram(self, p):
        tg = self.core.telegram
        if p.get("op") == "notify":
            return {"sent_to": tg.broadcast(p.get("text", "JARVIS test xabari"))}
        return tg.status()

    def _h_bi(self, p):
        bi, op = self.core.bi, p.get("op", "report")
        if op == "import":
            return bi.import_file(p["path"], p["kind"])
        return bi.report()

    def _h_pos(self, p):
        pos, op = self.core.pos, p.get("op", "status")
        if op == "draft":
            return pos.create_draft(p["doc_type"], p["party"], p["items"], p.get("note", ""), p.get("account", ""))
        if op == "request_approval":
            return pos.request_approval(int(p["id"])) | {"needs_approval": True}
        return pos.status()

    def _h_qa(self, p):
        from . import selfcheck
        out = {"health": selfcheck.health(self.core)}
        if p.get("release_gate"):
            out["release"] = selfcheck.run_release_gate()
        if p.get("run_tests"):
            out["tests"] = selfcheck.run_tests()
        return out
