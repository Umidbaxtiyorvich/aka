"""Personal Command Center — global qidiruv va har bo'limdan ishlaydigan buyruq satri.

* Qidiruv: xotira (FTS), missiyalar, vazifalar, indekslangan fayllar, ulanishlar, bildirishnomalar, bilimlar grafi, tool'lar.
  Natijalar faqat o'qiladi; har biri dashboard'dagi tegishli bo'limga havola bilan.
* Buyruqlar: "/" bilan qisqa buyruqlar (qidir, missiya, holat, to'xtat, davom, hisobot, tool) yoki oddiy matn → JARVIS chat
  (Brain Core / Mission Engine / AI Router). Ovoz ham shu yo'ldan foydalanadi (bir xil qoidalar, bir xil tasdiqlar).
* Xavfli narsa yo'q: "/to'xtat" — favqulodda to'xtatish (xavfsiz tomonga), qolganlari o'qish yoki reja tuzish.
"""
from __future__ import annotations

import re

QUICK = {"/qidir": "Hamma joydan qidirish: /qidir <so'z>", "/missiya": "Missiya yaratish: /missiya <maqsad>",
         "/holat": "Tizim va missiyalar holati", "/to'xtat": "Favqulodda to'xtatish (barcha avtomatika va missiyalar)",
         "/davom": "Avtomatikani qayta yoqish", "/hisobot": "Kunlik hisobot", "/tool": "Tool chaqirish: /tool <id> {json}",
         "/yordam": "Buyruqlar ro'yxati"}
STOP_RX = re.compile(r"(?i)^(/to'?xtat|/stop|jarvis,?\s*(hammasini\s*)?to'?xtat|missiyalarni to'?xtat)\b")
STATUS_RX = re.compile(r"(?i)^(/holat|missiya(lar)?\s*holati|holat qanday|jarvis,?\s*holat)\b")


class CommandCenter:
    def __init__(self, core):
        self.core = core

    def search(self, q: str, limit: int = 8) -> dict:
        q = (q or "").strip()
        if len(q) < 2:
            return {"query": q, "groups": []}
        c, like, groups = self.core, f"%{q}%", []

        def g(kind, title, link, items):
            if items:
                groups.append({"kind": kind, "title": title, "link": link, "items": items[:limit]})
        g("memory", "Xotira", "#memx", [{"id": m["id"], "text": (m.get("title") or m["content"])[:140], "meta": m["kind"]} for m in c.memory.search(q, limit)])
        g("mission", "Missiyalar", "#mission", [{"id": r["id"], "text": r["goal"][:140], "meta": r["status"]}
                                                for r in c.db.query("SELECT id, goal, status FROM missions WHERE goal LIKE ? ORDER BY id DESC LIMIT ?", (like, limit))])
        g("task", "Vazifalar", "#agents", [{"id": r["id"], "text": r["title"][:140], "meta": f"{r['agent']} · {r['status']}"}
                                           for r in c.db.query("SELECT id, title, agent, status FROM tasks WHERE title LIKE ? ORDER BY id DESC LIMIT ?", (like, limit))])
        g("file", "Fayllar", "#assets", [{"id": r["path"], "text": r["name"], "meta": r["path"]} for r in c.assets.search(q, limit=limit)])
        g("connection", "Ulanishlar", "#connections", [{"id": x["id"], "text": x["name"], "meta": x["status"]} for x in c.integrations.health()
                                                        if q.lower() in f"{x['name']} {x['type']} {x['adapter']}".lower()])
        g("notification", "Bildirishnomalar", "#notifications", [{"id": r["id"], "text": r["title"][:140], "meta": r["ts"]}
                                                                  for r in c.db.query("SELECT id, title, ts FROM notifications WHERE title LIKE ? OR body LIKE ? ORDER BY id DESC LIMIT ?", (like, like, limit))])
        g("graph", "Bilimlar grafi", "#graph", [{"id": r["id"], "text": r["label"][:140], "meta": r["type"]}
                                                for r in c.db.query("SELECT id, label, type FROM kg_nodes WHERE label LIKE ? LIMIT ?", (like, limit))])
        g("tool", "Tool'lar", "#tools", [{"id": t["id"], "text": t["name"], "meta": f"{t['risk']} · {t['id']}"} for t in c.tools.catalog()
                                         if q.lower() in f"{t['id']} {t['name']} {t['description']}".lower()])
        return {"query": q, "groups": groups, "total": sum(len(x["items"]) for x in groups)}

    def run(self, text: str, source: str = "command") -> dict:
        t = (text or "").strip()
        if not t:
            raise ValueError("Bo'sh buyruq")
        c = self.core
        if t in ("/yordam", "/help", "/"):
            return {"kind": "help", "text": "\n".join(f"{k} — {v}" for k, v in QUICK.items())}
        if STOP_RX.match(t):
            return {"kind": "stop", "text": c.stop_automation(source)}
        if t.startswith("/davom"):
            c.resume_automation()
            return {"kind": "resume", "text": "▶ Avtomatika qayta yoqildi. To'xtatilgan missiyalarni Mission Control'da 'Davom ettirish' bilan davom ettiring."}
        if STATUS_RX.match(t):
            ms = c.db.query("SELECT id, goal, status FROM missions WHERE status NOT IN ('completed','cancelled') ORDER BY id DESC LIMIT 5")
            g = c.guardian.status()
            lines = [f"Tizim: {g['overall']} · avtonomlik Level {c.settings.autonomy_level}" + (" · ⏸ to'xtatilgan" if c.automation_paused else "")]
            lines += [f"#{m['id']} {m['status']}: {m['goal'][:70]}" for m in ms] or ["Faol missiya yo'q"]
            pend = c.db.one("SELECT COUNT(*) n FROM approvals WHERE status='pending'")["n"]
            lines.append(f"Kutilayotgan tasdiqlar: {pend}")
            return {"kind": "status", "text": "\n".join(lines), "link": "#mission"}
        if t.startswith("/hisobot"):
            r = c.proactive.report("daily")
            return {"kind": "report", "text": f"Missiyalar: {r['missions'] or 'yo‘q'} · AI so'rovlar: {r['ai_requests']} · xatolar: {r['errors']}\n{r['sales']}", "data": r}
        if t.startswith("/qidir"):
            return {"kind": "search", **self.search(t[6:].strip())}
        if t.startswith("/missiya"):
            t = "missiya: " + t[8:].strip()
        if t.startswith("/tool"):
            import json
            m = re.match(r"/tool\s+(\S+)\s*(\{.*\})?\s*$", t, re.S)
            if not m:
                raise ValueError("Format: /tool <id> {\"arg\": \"qiymat\"}")
            try:
                args = json.loads(m.group(2) or "{}")
            except ValueError:
                raise ValueError("Argumentlar JSON noto'g'ri") from None
            r = c.tools.invoke(m.group(1), args, caller="user")
            return {"kind": "tool", "text": f"{r['tool']}: {r['status']} ({r['duration_ms']} ms)", "data": r}
        r = c.chat(t)
        return {"kind": "chat", "text": r.get("text", ""), "mission_id": r.get("mission_id"), "link": "#mission" if r.get("mission_id") else "#chat"}
