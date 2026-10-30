"""Proactive Intelligence + JARVIS Guardian.

Proactive: tugallanmagan missiyalar, muddati yaqin/o'tgan vazifalar, eski tasdiqlar, kutilayotgan xulosalar/importlar, uzilgan
ulanishlar va AI provayderlar, xatolar — bir kunda bir marta bildirishnoma; kunlik/haftalik hisobot. HECH QANDAY tashqi amal
bajarmaydi: bildirishnoma faqat foydalanuvchi belgilagan kanallarga (dashboard; Telegram — `telegram_events` da "proactive" bo'lsa).

Guardian: CPU/RAM/disk, baza, AI provayderlar, xarajat (anomaliya ham), zaxira, xatolar, xavfsizlik holati, ulanishlar.
Tiklash faqat oq ro'yxatdagi XAVFSIZ amallar bilan (qaytariladigan, tashqi ta'sirsiz); favqulodda to'xtatish — bitta tugma.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS proactive_seen (key TEXT NOT NULL, day TEXT NOT NULL, PRIMARY KEY(key, day));
CREATE TABLE IF NOT EXISTS proactive_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, period TEXT NOT NULL, report TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(kind, period)
);
CREATE TABLE IF NOT EXISTS guardian_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), action TEXT NOT NULL, auto INTEGER NOT NULL, result TEXT
);
"""


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(ts).replace(" ", "T"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


class Proactive:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        core.db.ensure_columns("missions", {"due_at": "TEXT"})

    def scan(self) -> list[dict]:
        db, now, out = self.core.db, _utc(), []
        add = lambda key, sev, title, body="", link="": out.append({"key": key, "severity": sev, "title": title, "body": body, "link": link})  # noqa: E731
        for m in db.query("SELECT id, goal, status, due_at, stop_reason FROM missions WHERE status NOT IN ('completed','cancelled') ORDER BY id DESC LIMIT 50"):
            due = _parse(m["due_at"]) if m["due_at"] else None
            if due and due < now:
                add(f"overdue:{m['id']}", "warning", f"Muddati o'tgan missiya #{m['id']}", m["goal"][:150], "#mission")
            elif due and due - now < timedelta(hours=24):
                add(f"due:{m['id']}", "info", f"Muddati yaqin (24 soat ichida): missiya #{m['id']}", m["goal"][:150], "#mission")
            if m["status"] in ("paused", "failed", "waiting_approval", "needs_input"):
                add(f"mission:{m['id']}:{m['status']}", "info", f"Tugallanmagan missiya #{m['id']} ({m['status']})",
                    (m["stop_reason"] or m["goal"])[:150], "#mission")
        ttl = self.core.approvals.ttl_hours or 72
        for a in db.query("SELECT id, summary, created_at FROM approvals WHERE status='pending'"):
            t = _parse(a["created_at"])
            if t and now - t > timedelta(hours=max(1, ttl - 12)):
                add(f"approval_exp:{a['id']}", "warning", f"Tasdiq muddati tugayapti: #{a['id']}", a["summary"][:150], "#approvals")
            elif t and now - t > timedelta(hours=12):
                add(f"approval_old:{a['id']}", "info", f"Tasdiq kutmoqda (12 soatdan ortiq): #{a['id']}", a["summary"][:150], "#approvals")
        n = db.one("SELECT COUNT(*) n FROM mission_lessons WHERE status='pending'")["n"]
        if n:
            add("lessons", "info", f"{n} ta yangi tajriba xulosasi tasdiqni kutmoqda", "", "#mission")
        for r in db.query("SELECT id, filename FROM memory_imports WHERE status='ready'"):
            add(f"import:{r['id']}", "info", f"ChatGPT importi ko'rib chiqilmagan: {r['filename']}", "", "#memimport")
        for c in self.core.integrations.health():
            if c["enabled"] and c["status"] in ("error", "auth_failed", "auth_expired", "user_action_required", "permission_denied"):
                add(f"integ:{c['id']}:{c['status']}", "warning", f"Ulanishda muammo: {c['name']} ({c['status']})", c["note"] or "", "#connections")
        for p in self.core.settings.ai_providers:
            why = self.core.ai_hub.blocked(p.get("id", ""))
            if why:
                add(f"ai:{p['id']}", "warning", f"AI provayder vaqtincha ishlatilmayapti: {p['id']}", why, "#aihub")
        e = db.one("SELECT COUNT(*) n FROM errors WHERE ts >= datetime('now','-1 day')")["n"]
        if e >= 5:
            add("errors_day", "warning", f"Oxirgi 24 soatda {e} ta xato", "Xatolar bo'limida sabablar guruhlangan", "#errors")
        for s in self.core.twin.suggestions():
            if s["kind"] == "repeat":
                add(f"twin:{s['text'][:60]}", "info", "Avtomatlashtirish taklifi", s["text"], s["link"])
        return out

    def notify_new(self) -> list[dict]:
        day, sent = _utc().strftime("%Y-%m-%d"), []
        for it in self.scan():
            if self.core.db.one("SELECT 1 FROM proactive_seen WHERE key=? AND day=?", (it["key"], day)):
                continue
            self.core.db.execute("INSERT INTO proactive_seen(key, day) VALUES (?,?)", (it["key"], day))
            self.core.notifier.notify(it["title"], it["body"], severity=it["severity"], category="proactive")
            sent.append(it)
        return sent

    def report(self, kind: str = "daily") -> dict:
        days = 1 if kind == "daily" else 7
        since = (_utc() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        db = self.core.db
        ms = {r["status"]: r["n"] for r in db.query("SELECT status, COUNT(*) n FROM missions WHERE created_at>=? GROUP BY status", (since,))}
        ai = db.one("SELECT COUNT(*) n, ROUND(COALESCE(SUM(cost),0),4) cost, SUM(ok=0) errors FROM ai_usage WHERE ts>=?", (since,))
        rep = {"kind": kind, "since": since, "missions": ms, "ai_requests": ai["n"], "ai_cost": ai["cost"], "ai_errors": ai["errors"] or 0,
               "errors": db.one("SELECT COUNT(*) n FROM errors WHERE ts>=?", (since,))["n"],
               "pending_approvals": db.one("SELECT COUNT(*) n FROM approvals WHERE status='pending'")["n"],
               "new_memories": db.one("SELECT COUNT(*) n FROM memories WHERE created_at>=?", (since,))["n"],
               "attention": [i["title"] for i in self.scan()][:15]}
        sales = self.core.analyst.answer("bugungi savdo" if kind == "daily" else "shu hafta savdo")
        rep["sales"] = sales.get("text") if sales.get("data") else "Savdo ma'lumoti yo'q (POS ulanmagan yoki sinxronlanmagan)"
        return rep

    def tick(self, now: datetime | None = None) -> dict:
        now = now or _utc()
        sent = self.notify_new()
        made = []
        for kind, period in (("daily", now.strftime("%Y-%m-%d")), ("weekly", now.strftime("%G-W%V"))):
            if kind == "weekly" and now.weekday() != 0:
                continue
            if now.hour < 7 or self.core.db.one("SELECT 1 FROM proactive_reports WHERE kind=? AND period=?", (kind, period)):
                continue
            rep = self.report(kind)
            self.core.db.execute("INSERT INTO proactive_reports(kind, period, report) VALUES (?,?,?)", (kind, period, json.dumps(rep, ensure_ascii=False)))
            body = (f"Missiyalar: {rep['missions'] or 'yo‘q'} · AI so'rov: {rep['ai_requests']} (xarajat {rep['ai_cost']}) · xatolar: {rep['errors']} · "
                    f"kutilayotgan tasdiqlar: {rep['pending_approvals']}\n{rep['sales']}")
            self.core.notifier.notify("Kunlik hisobot" if kind == "daily" else "Haftalik hisobot", body, category="proactive")
            made.append(kind)
        return {"notified": len(sent), "reports": made}

    def reports(self, limit: int = 20) -> list[dict]:
        rows = self.core.db.query("SELECT * FROM proactive_reports ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["report"] = json.loads(r["report"])
        return rows


class Guardian:
    SAFE_ACTIONS = {"clear_ai_cache": "AI holat keshini tozalash", "recheck_providers": "Bloklangan AI provayderlarni bepul qayta tekshirish (modellar ro'yxati)",
                    "check_connections": "Ulanishlar holatini tekshirish (faqat o'qish)", "db_quick_check": "Baza butunligini tekshirish (PRAGMA quick_check)",
                    "backup_now": "Mahalliy zaxira nusxa yaratish", "emergency_stop": "Favqulodda to'xtatish (jadval, sinxronlash, missiyalar)",
                    "resume_automation": "Avtomatikani qayta yoqish"}

    def __init__(self, core):
        self.core = core
        self._started = time.time()

    def status(self) -> dict:
        c, checks = self.core, []
        add = lambda key, title, st, value, note="", action=None: checks.append({"key": key, "title": title, "status": st, "value": value, "note": note, "action": action})  # noqa: E731
        try:
            import psutil
            cpu, vm = psutil.cpu_percent(interval=0.1), psutil.virtual_memory()
            du = psutil.disk_usage(str(c.db.path.parent))
            rss = psutil.Process().memory_info().rss / 2**20
            add("cpu", "CPU", "ok" if cpu < 85 else "warn", f"{cpu:.0f}%")
            add("ram", "RAM", "ok" if vm.percent < 85 else "warn" if vm.percent < 93 else "bad", f"{vm.percent:.0f}% (JARVIS: {rss:.0f} MB)",
                "8 GB'da og'ir modellarni bir vaqtda ishlatmang" if vm.percent >= 85 else "")
            add("disk", "Disk", "ok" if du.free > 10 * 2**30 else "warn" if du.free > 3 * 2**30 else "bad", f"{du.free / 2**30:.1f} GB bo'sh")
        except Exception as e:
            add("resources", "Resurslar", "warn", "o'lchab bo'lmadi", str(e)[:100])
        size = sum(p.stat().st_size for p in c.db.path.parent.glob(c.db.path.name + "*") if p.exists()) / 2**20
        add("db", "Ma'lumotlar bazasi", "ok", f"{size:.1f} MB", "", "db_quick_check")
        ov = c.ai_hub.overview()
        blocked = [p["id"] for p in c.settings.ai_providers if c.ai_hub.blocked(p.get("id", ""))]
        add("ai", "AI provayderlar", "ok" if not blocked else "warn", f"{ov['connected']}/{ov['providers']} ulangan · AI: {c.ai.name}",
            ("bloklangan: " + ", ".join(blocked)) if blocked else "", "recheck_providers" if blocked else None)
        t, m, s = c.guard.today(), c.guard.month(), c.settings
        prev = c.db.one("SELECT COALESCE(SUM(cost),0)/7.0 avg FROM ai_usage WHERE ts>=datetime('now','-8 day') AND ts<date('now')")["avg"] or 0
        st = "ok"
        note = f"kunlik limit {s.daily_cost_limit}, oylik {s.monthly_cost_limit} {s.currency}" if s.paid_ai_allowed else "pullik AI o'chiq"
        if s.daily_cost_limit and t["cost"] >= 0.8 * s.daily_cost_limit:
            st = "warn"
        if prev > 0 and t["cost"] > 3 * prev and t["cost"] > 0.05:
            st, note = "warn", f"bugungi xarajat o'rtachadan 3 baravar ko'p (o'rtacha {prev:.4f})"
        add("cost", "API xarajatlari", st, f"bugun {t['cost']} · oy {m['cost']} {s.currency}", note)
        bl = c.backup.list()
        age_h = None
        if bl and bl[0].get("created"):
            ct = _parse(bl[0]["created"])
            age_h = (_utc() - ct).total_seconds() / 3600 if ct else None
        lim = (s.backup_interval_hours or 24) * 2
        add("backup", "Zaxira nusxa", "ok" if age_h is not None and age_h < lim else "warn",
            f"oxirgisi {age_h:.0f} soat oldin" if age_h is not None else "hali yo'q", "", "backup_now")
        e = c.db.one("SELECT COUNT(*) n FROM errors WHERE ts>=datetime('now','-1 day')")["n"]
        add("errors", "Xatolar (24 soat)", "ok" if e < 5 else "warn", str(e), "", None)
        bad = [x["name"] for x in c.integrations.health() if x["enabled"] and x["status"] in ("error", "auth_failed", "auth_expired", "permission_denied")]
        add("connections", "Ulanishlar", "ok" if not bad else "warn", f"{len(bad)} ta muammo", ", ".join(bad), "check_connections")
        crit = c.db.one("SELECT COUNT(*) n FROM approvals WHERE status='pending' AND level='E'")["n"]
        untrusted = c.db.one("SELECT COUNT(*) n FROM plugins WHERE status='untrusted'")["n"]
        sec_notes = [x for x in (f"{crit} ta CRITICAL tasdiq kutmoqda" if crit else "", f"{untrusted} ta o'zgargan kengaytma" if untrusted else "",
                                 "PIN o'chirilgan" if not s.auth_enabled else "") if x]
        add("security", "Xavfsizlik", "ok" if not sec_notes else "warn", "read-only" if s.read_only_mode else "yozish yoqilgan", "; ".join(sec_notes))
        add("automation", "Avtomatika", "warn" if c.automation_paused else "ok",
            ("to'xtatilgan" if c.automation_paused else "ishlamoqda") + f" · avtonomlik: Level {s.autonomy_level}", "",
            "resume_automation" if c.automation_paused else "emergency_stop")
        add("uptime", "Ishlash vaqti", "ok", f"{(time.time() - self._started) / 3600:.1f} soat")
        worst = "bad" if any(x["status"] == "bad" for x in checks) else "warn" if any(x["status"] == "warn" for x in checks) else "ok"
        return {"overall": worst, "checks": checks, "actions": self.SAFE_ACTIONS,
                "events": c.db.query("SELECT * FROM guardian_events ORDER BY id DESC LIMIT 20")}

    def run(self, action: str, auto: bool = False) -> dict:
        c = self.core
        if action not in self.SAFE_ACTIONS:
            raise ValueError("Bu amal Guardian'ning xavfsiz ro'yxatida yo'q")
        if action == "clear_ai_cache":
            c.reload_ai()
            res = "AI keshi tozalandi"
        elif action == "recheck_providers":
            res = "; ".join(f"{p['id']}: {c.ai_hub.verify(p['id'], test_model=False)['status']}"
                            for p in c.settings.ai_providers if c.ai_hub.blocked(p.get("id", ""))) or "bloklangan provayder yo'q"
        elif action == "check_connections":
            c.integrations.monitor()
            res = "ulanishlar tekshirildi"
        elif action == "db_quick_check":
            res = "; ".join(r[0] for r in c.db.conn.execute("PRAGMA quick_check").fetchall())[:200]
        elif action == "backup_now":
            b = c.backup.create("guardian")
            res = f"zaxira: {b.get('name', b)}"
        elif action == "emergency_stop":
            res = c.stop_automation("guardian")
        else:
            c.resume_automation()
            res = "avtomatika qayta yoqildi"
        c.db.execute("INSERT INTO guardian_events(action, auto, result) VALUES (?,?,?)", (action, int(auto), str(res)[:300]))
        c.audit.log("guardian", f"Guardian: {self.SAFE_ACTIONS[action]} → {str(res)[:100]}", target="guardian", risk="B" if action != "emergency_stop" else "C",
                    approval_status="auto" if auto else "user_action")
        return {"action": action, "result": res}

    def auto_recover(self) -> list[dict]:
        """Avtomatik — faqat ta'sirsiz amallar: bloklangan provayderni bepul qayta tekshirish (soatiga bir)."""
        last = self.core.db.one("SELECT ts FROM guardian_events WHERE action='recheck_providers' AND auto=1 ORDER BY id DESC LIMIT 1")
        if any(self.core.ai_hub.blocked(p.get("id", "")) for p in self.core.settings.ai_providers) and (
                not last or (_utc() - (_parse(last["ts"]) or _utc())).total_seconds() > 3600):
            return [self.run("recheck_providers", auto=True)]
        return []
