"""Jonli ofis — JARVIS butun ofisni boshqaradi: har bir xodim (agent) o'z vazifasi va ish jadvali bilan ishlaydi,
menejer (JARVIS) topshiriqlarni taqsimlaydi, hamma narsa jonli lentada ko'rinadi.

Xodimlar: Menejer, Hisobchi (POS), SMM (Instagram), Kotib (Telegram), Tahlilchi, Dizayner (saytlar orqali),
Dasturchi (JARVIS'ni o'zi rivojlantiradi), Qo'riqchi (tizim va xavfsizlik).

Ish jadvali (routines) — o'zi bajaradigan "mayda ishlar": POS'dan yangi ma'lumot olish, ertalabki hisobot, kam qolgan
tovarlar, Instagram Direct'ga javob LOYIHALARI, tizim nazorati, o'zini rivojlantirish g'oyalari. Hammasi faqat o'qish yoki
loyiha tayyorlash; tashqariga yozish (nashr, xabar, kirim) — har doim siz tasdiqlaydigan so'rov. Siz istalgan xodimga
topshiriq bera olasiz (AI agent rejimi, xodimning vositalari bilan). Favqulodda to'xtatish va avtonomlik darajasi
hamma xodimlarga amal qiladi.
"""
from __future__ import annotations

import threading
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS office_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now','localtime')), role TEXT NOT NULL, text TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'info'
);
CREATE TABLE IF NOT EXISTS office_routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, title TEXT NOT NULL, action TEXT NOT NULL, prompt TEXT,
    schedule TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, last_run TEXT, last_status TEXT, last_result TEXT, builtin INTEGER NOT NULL DEFAULT 0
);
"""
STAFF = [
    {"key": "menejer", "name": "JARVIS — menejer", "emoji": "🧠", "role": "Ofisni boshqaradi, topshiriqlarni xodimlarga taqsimlaydi", "tools": None},
    {"key": "hisobchi", "name": "Hisobchi", "emoji": "🧾", "role": "POS: savdo, qoldiq, kirim/chiqim (yozish — tasdiq bilan)",
     "tools": ["connections.list", "connection.refresh", "analyst.ask", "business.forecast", "site.task", "integration.propose_write", "memory.search"]},
    {"key": "smm", "name": "SMM menejer", "emoji": "📸", "role": "Instagram: post, Direct, statistika (nashr — tasdiq bilan)",
     "tools": ["instagram.accounts", "instagram.draft_post", "instagram.request_publish", "instagram.conversations", "instagram.draft_dm", "instagram.request_dm",
               "site.skills", "site.generate", "memory.search"]},
    {"key": "kotib", "name": "Kotib", "emoji": "✉", "role": "Telegram xabarlar, eslatmalar, xotira", "tools": ["telegram.send", "memory.search", "memory.propose"]},
    {"key": "tahlilchi", "name": "Tahlilchi", "emoji": "📊", "role": "Hisobot, prognoz, internet tadqiqoti, hujjatlar",
     "tools": ["analyst.ask", "business.forecast", "research.web", "docs.extract", "docs.find", "assets.search", "connections.list"]},
    {"key": "dizayner", "name": "Dizayner", "emoji": "🎨", "role": "Rasm, video, ovoz — ulangan saytlar va o'z agentlari orqali", "tools": ["site.skills", "site.generate"]},
    {"key": "dasturchi", "name": "Dasturchi", "emoji": "👨‍💻", "role": "JARVIS'ni o'zi rivojlantiradi: kamchilik → kod → test → sizga taqdim",
     "tools": ["selfdev.request", "guardian.status"]},
    {"key": "qorovul", "name": "Qo'riqchi", "emoji": "🛡", "role": "Tizim holati, xavfsizlik, AI xarajati", "tools": ["guardian.status", "security.scan_text"]},
]
DEFAULT_ROUTINES = [
    ("hisobchi", "POS'dan yangi ma'lumot olish", "pos_refresh", "every:60"),
    ("tahlilchi", "Ertalabki hisobot", "morning_brief", "daily:09:00"),
    ("hisobchi", "Kam qolgan tovarlar", "low_stock", "daily:18:00"),
    ("smm", "Instagram Direct — javob loyihalari", "ig_inbox", "every:30"),
    ("qorovul", "Tizim nazorati", "guard", "every:15"),
    ("dasturchi", "O'zini rivojlantirish (g'oya → kod → test)", "selfdev", "daily:03:00"),
]
TOOL_ROLE = {"connection": "hisobchi", "connections": "hisobchi", "analyst": "tahlilchi", "business": "tahlilchi", "integration": "hisobchi",
             "site": "dizayner", "instagram": "smm", "telegram": "kotib", "memory": "kotib", "research": "tahlilchi", "docs": "tahlilchi",
             "guardian": "qorovul", "security": "qorovul", "selfdev": "dasturchi", "computer": "menejer", "mission": "menejer"}


class OfficeError(Exception):
    pass


class OfficeLive:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        if not core.db.one("SELECT 1 FROM office_routines WHERE builtin=1"):
            for role, title, action, sch in DEFAULT_ROUTINES:
                core.db.execute("INSERT INTO office_routines(role, title, action, schedule, builtin) VALUES (?,?,?,?,1)", (role, title, action, sch))
        self.working: dict[str, str] = {}
        self._lock = threading.Lock()
        self._guard_prev = None

    # ---------------- lenta ----------------
    def log(self, role: str, text: str, kind: str = "info"):
        from .security import redact
        self.core.db.execute("INSERT INTO office_activity(role, text, kind) VALUES (?,?,?)", (role, redact(text)[:400], kind))
        ev = getattr(self.core, "events", None)
        if ev:
            ev.publish("office", role=role, text=text[:200], kind=kind)

    def log_tool(self, tool_id: str, status: str):
        role = TOOL_ROLE.get(tool_id.split(".")[0], "menejer")
        t = self.core.tools.tools.get(tool_id)
        self.log(role, f"{t.name if t else tool_id}: {'tasdiq so`raldi' if status == 'approval_requested' else status}",
                 "approval" if status == "approval_requested" else ("error" if status == "error" else "work"))

    def feed(self, limit: int = 60, after: int = 0) -> list[dict]:
        return self.core.db.query("SELECT * FROM office_activity WHERE id>? ORDER BY id DESC LIMIT ?", (after, limit))

    # ---------------- holat ----------------
    def staff(self) -> list[dict]:
        db, out = self.core.db, []
        pend = db.query("SELECT requested_by, COUNT(*) n FROM approvals WHERE status='pending' GROUP BY requested_by")
        waiting = {r["requested_by"]: r["n"] for r in pend}
        for s in STAFF:
            last = db.one("SELECT ts, text, kind FROM office_activity WHERE role=? ORDER BY id DESC LIMIT 1", (s["key"],))
            today = db.one("SELECT COUNT(*) n FROM office_activity WHERE role=? AND date(ts)=date('now','localtime')", (s["key"],))["n"]
            routines = db.query("SELECT id, title, schedule, enabled, last_run, last_status FROM office_routines WHERE role=?", (s["key"],))
            w = {"smm": waiting.get("instagram_agent", 0), "hisobchi": waiting.get("integration", 0),
                 "dasturchi": db.one("SELECT COUNT(*) n FROM dev_ideas WHERE status='ready'")["n"] if self._has("dev_ideas") else 0}.get(s["key"], 0)
            status = "working" if s["key"] in self.working else ("waiting" if w else "idle")
            out.append({k: v for k, v in s.items() if k != "tools"} | {"status": status, "current": self.working.get(s["key"]), "waiting": w,
                                                                       "last": last, "today": today, "routines": routines,
                                                                       "tools": s["tools"] or ["(hammasi)"]})
        return out

    def _has(self, table: str) -> bool:
        return bool(self.core.db.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)))

    def overview(self) -> dict:
        c = self.core
        return {"staff": self.staff(), "feed": self.feed(40), "routines": self.routines(),
                "paused": bool(getattr(c, "automation_paused", False)), "autonomy": int(c.settings.autonomy_level),
                "ai": c.agent.ready(), "pending_approvals": c.db.one("SELECT COUNT(*) n FROM approvals WHERE status='pending'")["n"]}

    # ---------------- jadval ----------------
    def routines(self) -> list[dict]:
        return self.core.db.query("SELECT * FROM office_routines ORDER BY role, id")

    def save_routine(self, role: str, title: str, prompt: str, schedule: str, rid: int | None = None, enabled: bool = True) -> dict:
        if role not in {s["key"] for s in STAFF}:
            raise OfficeError("Xodim topilmadi")
        self._parse(schedule)
        if rid:
            r = self.core.db.one("SELECT * FROM office_routines WHERE id=?", (rid,))
            if not r:
                raise OfficeError("Jadval topilmadi")
            if r["builtin"]:
                self.core.db.execute("UPDATE office_routines SET schedule=?, enabled=? WHERE id=?", (schedule, int(enabled), rid))
            else:
                self.core.db.execute("UPDATE office_routines SET role=?, title=?, prompt=?, schedule=?, enabled=? WHERE id=?",
                                     (role, title[:80], prompt[:2000], schedule, int(enabled), rid))
        else:
            if len((prompt or "").strip()) < 5:
                raise OfficeError("Xodim nima qilishini yozing")
            rid = self.core.db.execute("INSERT INTO office_routines(role, title, action, prompt, schedule, enabled) VALUES (?,?, 'agent', ?,?,?)",
                                       (role, (title or prompt)[:80], prompt[:2000], schedule, int(enabled))).lastrowid
        self.log("menejer", f"Ish jadvali yangilandi: {title or prompt[:40]} ({schedule})")
        return self.core.db.one("SELECT * FROM office_routines WHERE id=?", (rid,))

    def delete_routine(self, rid: int) -> dict:
        r = self.core.db.one("SELECT builtin FROM office_routines WHERE id=?", (rid,))
        if not r:
            raise OfficeError("Topilmadi")
        if r["builtin"]:
            raise OfficeError("Asosiy jadvalni o'chirib bo'lmaydi — o'chirib qo'ying (enabled)")
        self.core.db.execute("DELETE FROM office_routines WHERE id=?", (rid,))
        return {"deleted": rid}

    @staticmethod
    def _parse(schedule: str) -> tuple[str, int, int]:
        try:
            kind, val = schedule.split(":", 1)
            if kind == "every":
                n = int(val)
                if not 5 <= n <= 1440:
                    raise ValueError
                return "every", n, 0
            if kind == "daily":
                h, m = (int(x) for x in val.split(":"))
                if not (0 <= h < 24 and 0 <= m < 60):
                    raise ValueError
                return "daily", h, m
        except ValueError:
            pass
        raise OfficeError("Jadval formati: every:<daqiqa 5–1440> yoki daily:SS:DD (masalan daily:09:00)")

    def _due(self, r: dict, now: datetime) -> bool:
        kind, a, b = self._parse(r["schedule"])
        last = datetime.fromisoformat(r["last_run"]) if r["last_run"] else None
        if kind == "every":
            return last is None or (now - last).total_seconds() >= a * 60
        target = now.replace(hour=a, minute=b, second=0, microsecond=0)
        return now >= target and (last is None or last < target)

    def tick(self, now: datetime | None = None) -> list[dict]:
        """Jadval (har daqiqa): vaqti kelgan ishlarni bajaradi. To'xtatish va Level 0 hurmat qilinadi."""
        c, now, done = self.core, now or datetime.now(), []
        try:
            c.selfdev.watch_tick()                          # yangi versiya kuzatuvi (bo'lsa)
        except Exception as e:                              # noqa: BLE001
            c.audit.error("office", f"watch: {e}")
        if getattr(c, "automation_paused", False):
            return done
        for r in self.core.db.query("SELECT * FROM office_routines WHERE enabled=1"):
            if int(c.settings.autonomy_level) <= 0 and r["action"] != "guard":
                continue
            try:
                if self._due(r, now):
                    done.append(self.run_routine(r["id"], now=now))
            except OfficeError:
                continue
        return done

    def run_routine(self, rid: int, now: datetime | None = None) -> dict:
        r = self.core.db.one("SELECT * FROM office_routines WHERE id=?", (rid,))
        if not r:
            raise OfficeError("Topilmadi")
        if not self._lock.acquire(timeout=1):
            raise OfficeError("Boshqa ish bajarilmoqda — birozdan keyin")
        self.working[r["role"]] = r["title"]
        status, result = "ok", ""
        try:
            fn = None if r["action"] == "agent" else getattr(self, f"_r_{r['action']}", None)
            result = fn() if fn else self._r_agent(r)
            if result is None:
                status, result = "skipped", "bajariladigan narsa yo'q"
        except Exception as e:                              # noqa: BLE001 — bitta ish xatosi ofisni to'xtatmaydi
            status, result = "error", str(e)[:300]
        finally:
            self.working.pop(r["role"], None)
            self._lock.release()
        self.core.db.execute("UPDATE office_routines SET last_run=?, last_status=?, last_result=? WHERE id=?",
                             ((now or datetime.now()).isoformat(timespec="seconds"), status, str(result)[:1000], rid))
        if status != "skipped":
            self.log(r["role"], f"{r['title']}: {str(result)[:200]}", "error" if status == "error" else "done")
        return {"id": rid, "title": r["title"], "status": status, "result": result}

    # ---------------- asosiy ishlar ----------------
    def _r_pos_refresh(self):
        c, out = self.core, []
        for x in c.integrations.list():
            if x["status"] == "connected" and x.get("entities") and x["system_type"] in ("pos", "erp", "shop", "website", "crm"):
                try:
                    r = c.integrations.sync(x["id"], trigger="office")
                    out.append(f"{x['name']}: {r.get('status', 'ok')}")
                except Exception as e:                      # noqa: BLE001
                    out.append(f"{x['name']}: xato — {str(e)[:80]}")
        return "; ".join(out) if out else None

    def _r_morning_brief(self):
        c = self.core
        r = c.proactive.report("daily")
        pend = c.db.one("SELECT COUNT(*) n FROM approvals WHERE status='pending'")["n"]
        ideas = c.db.one("SELECT COUNT(*) n FROM dev_ideas WHERE status='ready'")["n"]
        text = (f"Savdo: {r.get('sales') or 'maʼlumot yoʻq'}\nMissiyalar: {r.get('missions') or 'yoʻq'} · AI so'rovlar: {r.get('ai_requests')} · xatolar: {r.get('errors')}\n"
                f"Tasdiq kutayotganlar: {pend}" + (f"\nJARVIS yaxshilanishi tayyor: {ideas} ta (Rivojlanish bo'limi)" if ideas else ""))
        c.notifier.notify("☀ Ertalabki hisobot", text, category="report")
        return "hisobot yuborildi"

    def _r_low_stock(self):
        r = self.core.analyst.answer("Qaysi tovarlar kam qolgan?")
        if not r.get("data"):
            return None
        self.core.notifier.notify("📦 Kam qolgan tovarlar", str(r.get("text") or r.get("answer") or "")[:1500], category="report")
        return "ro'yxat yuborildi"

    def _r_ig_inbox(self):
        c, made = self.core, 0
        accs = [a.get("name") for a in c.instagram.accounts() if a.get("name")]
        if not accs:
            return None
        drafted = {r["conversation_id"] for r in c.db.query("SELECT conversation_id FROM ig_dm_drafts WHERE created_at >= datetime('now','-1 day')")}
        for name in accs:
            try:
                convs = c.instagram.conversations(name, limit=10)
            except Exception as e:                          # noqa: BLE001
                return f"Instagram ({name}): {str(e)[:120]}"
            for conv in convs:
                cid = conv.get("id")
                if not cid or cid in drafted:
                    continue
                try:
                    c.instagram.draft_dm(name, cid)
                    made += 1
                except Exception:                           # noqa: BLE001 — javob kerak bo'lmagan suhbat (kiruvchi xabar yo'q)
                    continue
        if made:
            c.notifier.notify("📸 Direct javob loyihalari", f"{made} ta javob loyihasi tayyor — Instagram bo'limida tekshirib tasdiqlang.", category="instagram")
        return f"{made} ta javob loyihasi" if made else None

    def _r_guard(self):
        g = self.core.guardian.status()
        ov = g.get("overall")
        prev, self._guard_prev = self._guard_prev, ov
        if ov != "ok" and prev != ov:
            bad = [f"{x.get('title') or x.get('key')}: {x.get('note') or x.get('value')}" for x in g.get("checks", []) if x.get("status") != "ok"]
            self.core.notifier.notify("🛡 Tizimda e'tibor kerak", "\n".join(bad[:6]), severity="warning", category="guardian")
            return "ogohlantirish: " + "; ".join(bad[:3])
        return None if prev == ov else f"holat: {ov}"

    def _r_selfdev(self):
        r = self.core.selfdev.auto_tick()
        return f"ishga kirishdi: {r['title'][:80]}" if r else None

    def _r_agent(self, r: dict):
        if not self.core.agent.ready():
            return None
        res = self.core.agent.run(r["prompt"], role=r["role"])
        return (res or {}).get("text", "")[:600] or None

    # ---------------- xodimga topshiriq ----------------
    def ask(self, role: str, text: str) -> dict:
        s = next((x for x in STAFF if x["key"] == role), None)
        if not s:
            raise OfficeError("Xodim topilmadi")
        if not (text or "").strip():
            raise OfficeError("Topshiriq bo'sh")
        self.log(role, f"Yangi topshiriq: {text[:120]}", "work")
        if not self.core.agent.ready():
            r = self.core.chat(text)
            self.log(role, (r.get("text") or "")[:200], "done")
            return r | {"role": role, "note": "AI modeli ulanmagan — oddiy rejimda javob berildi"}
        self.working[role] = text[:80]
        try:
            r = self.core.agent.run(text, role=role) or {"text": "AI javob bermadi"}
        finally:
            self.working.pop(role, None)
        self.log(role, (r.get("text") or "")[:200], "done")
        return r | {"role": role}
