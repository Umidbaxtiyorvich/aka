"""JARVIS 3.0 ish maydonlari: Virtual AI Office, Knowledge Researcher, Business Command Center (prognoz/anomaliya), Creative Factory imkoniyatlari.

Barchasi mavjud modullar ustida — yangi ma'lumot manbasi yaratilmaydi:
* Office: agent profili (Permission Manager) + uning vazifalari (tasks), missiya bosqichlari (dag_nodes), xulosalar.
* Researcher: research.py (qidiruv, manbalar, ishonchlilik, injection belgilari) + manbalarni solishtirish + xotiraga TASDIQ bilan.
* Business: sinxronlangan savdo (ext_records) va BI importi; prognoz — oddiy trend (taxmin deb belgilanadi).
* Creative: har xizmatning HAQIQIY holati (o'rnatilganmi, ulanganmi, adapteri bormi).
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL, summary TEXT NOT NULL, sources TEXT NOT NULL, agreement TEXT,
    status TEXT NOT NULL DEFAULT 'pending', memory_id INTEGER, created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""
STOP = set("the and for with that this from are was have about which what when where uchun bilan va bu shu ham yoki eng bir".split())


class WorkspaceError(Exception):
    pass


# ---------------- Virtual AI Office ----------------
class Office:
    def __init__(self, core):
        self.core = core

    def rooms(self) -> list[dict]:
        db = self.core.db
        stats = {r["agent"]: r for r in db.query("SELECT agent, COUNT(*) n, SUM(status='done') done, SUM(status='failed') failed, MAX(created_at) last FROM tasks GROUP BY agent")}
        out = []
        for p in self.core.permissions.profiles():
            s = stats.get(p["key"]) or {}
            out.append(p | {"tasks_total": s.get("n") or 0, "tasks_done": s.get("done") or 0, "tasks_failed": s.get("failed") or 0, "last_active": s.get("last")})
        return out

    def room(self, key: str) -> dict:
        prof = next((p for p in self.core.permissions.profiles() if p["key"] == key), None)
        if not prof:
            raise WorkspaceError("Agent topilmadi")
        db = self.core.db
        tasks = db.query("SELECT id, title, status, created_at, finished_at, substr(result,1,400) result, error FROM tasks WHERE agent=? ORDER BY id DESC LIMIT 20", (key,))
        steps = db.query("SELECT n.run_id, n.key, n.title, n.status, n.attempts, n.verify_note, m.id mission_id, m.goal FROM dag_nodes n "
                         "LEFT JOIN missions m ON m.dag_run_id=n.run_id WHERE n.agent=? ORDER BY n.id DESC LIMIT 20", (key,))
        lessons = db.query("SELECT mission_id, content, status FROM mission_lessons WHERE content LIKE ? ORDER BY id DESC LIMIT 10", (f"%({key})%",))
        return {"agent": prof, "tasks": tasks, "mission_steps": steps, "lessons": lessons,
                "conversation": [{"from": key, "text": f"#{t['id']} {t['title']} → {t['status']}" + (f": {t['error']}" if t["error"] else "")} for t in tasks[:10]]}

    def collaborations(self) -> list[dict]:
        out = []
        for m in self.core.db.query("SELECT id, goal, status, dag_run_id FROM missions ORDER BY id DESC LIMIT 30"):
            agents = [r["agent"] for r in self.core.db.query("SELECT DISTINCT agent FROM dag_nodes WHERE run_id=?", (m["dag_run_id"],))]
            if len(agents) >= 2:
                out.append({"mission_id": m["id"], "goal": m["goal"][:120], "status": m["status"], "agents": agents})
        return out


# ---------------- Knowledge Researcher ----------------
def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[^\W\d_]{4,}", (text or "").lower()) if w not in STOP}


class KnowledgeResearcher:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)

    def investigate(self, query: str, pages: int = 4) -> dict:
        if not query.strip():
            raise WorkspaceError("Savol kerak")
        r = self.core.research.answer(query, pages=pages)
        srcs = r.get("sources") or []
        texts = {}
        for s in srcs:
            try:
                texts[s["url"]] = self.core.research.fetch(s["url"])["text"][:20000]
            except Exception:
                texts[s["url"]] = ""
        q = _terms(query)
        df = Counter(t for tx in texts.values() for t in _terms(tx))
        consensus = sorted((t for t, n in df.items() if n >= 2 and t not in q), key=lambda t: -df[t])[:15]
        domains = {re.sub(r"^www\.", "", s["url"].split("/")[2]) for s in srcs if "://" in s["url"]}
        agreement = {"sources": len(srcs), "independent_domains": len(domains), "shared_terms": consensus,
                     "flagged": [s["url"] for s in srcs if s.get("injection_flags")],
                     "confidence": "past" if len(domains) < 2 else ("o'rta" if len(domains) < 3 else "yuqori"),
                     "note": "Ishonch — mustaqil manbalar soni va mos kelishi bo'yicha (heuristik). Manbalarni o'zingiz ham tekshiring."}
        if srcs and not r["answer"].startswith("Manbalarni o'qib bo'lmadi"):
            fid = self.core.db.execute("INSERT INTO knowledge_findings(query, summary, sources, agreement) VALUES (?,?,?,?)",
                                       (query, r["answer"][:4000], json.dumps(srcs, ensure_ascii=False), json.dumps(agreement, ensure_ascii=False))).lastrowid
        else:
            fid = None
        return {"finding_id": fid, "answer": r["answer"], "sources": srcs, "agreement": agreement, "errors": r.get("errors", [])}

    def findings(self, status: str = "pending") -> list[dict]:
        rows = self.core.db.query("SELECT * FROM knowledge_findings WHERE status=? ORDER BY id DESC LIMIT 50", (status,))
        for x in rows:
            x["sources"], x["agreement"] = json.loads(x["sources"]), json.loads(x["agreement"] or "{}")
        return rows

    def decide(self, fid: int, accept: bool) -> dict:
        f = self.core.db.one("SELECT * FROM knowledge_findings WHERE id=?", (fid,))
        if not f or f["status"] != "pending":
            raise WorkspaceError("Xulosa topilmadi yoki ko'rib chiqilgan")
        mid = None
        if accept:
            srcs = json.loads(f["sources"])
            urls = [s["url"] for s in srcs][:5]
            m = self.core.memory.add(f"{f['query']}: {f['summary'][:1500]}", "knowledge", source=urls[0] if urls else "research",
                                     info_type="fact", reference=" ".join(urls), observed_at=(srcs[0].get("fetched_at") if srcs else None),
                                     title=f"Tadqiqot: {f['query'][:80]}", confidence=0.6)
            mid = m["id"]
        self.core.db.execute("UPDATE knowledge_findings SET status=?, memory_id=? WHERE id=?", ("accepted" if accept else "rejected", mid, fid))
        return {"ok": True, "memory_id": mid}


# ---------------- Business Command Center ----------------
class BusinessCenter:
    def __init__(self, core):
        self.core = core

    def daily_sales(self, days: int = 60) -> dict:
        from .integrations.analyst import _parse_date
        tot, srcs = defaultdict(float), set()
        start = date.today() - timedelta(days=days)
        for r in self.core.analyst._rows("sale"):
            d = _parse_date(r.get("date"))
            amt = r.get("amount") if r.get("amount") is not None else ((r.get("qty") or 0) * (r.get("price") or 0) if r.get("price") is not None else None)
            if d and d >= start and amt is not None:
                tot[d] += float(amt)
                srcs.add(r["_src"])
        for r in self.core.db.query("SELECT date, total FROM bi_movements WHERE doc_type='sotuv' AND total IS NOT NULL"):
            d = _parse_date(r["date"])
            if d and d >= start:
                tot[d] += float(r["total"])
                srcs.add("BI import")
        series = [{"date": str(start + timedelta(days=i)), "amount": round(tot.get(start + timedelta(days=i), 0.0), 2)} for i in range(days + 1)]
        first = next((i for i, x in enumerate(series) if x["amount"]), None)
        return {"series": series[first:] if first is not None else [], "sources": sorted(srcs)}

    def forecast(self, horizon: int = 7) -> dict:
        ds = self.daily_sales()
        ys = [x["amount"] for x in ds["series"]]
        if len(ys) < 14:
            return {"forecast": [], "method": "—", "sources": ds["sources"], "note": f"Prognoz uchun kamida 14 kunlik savdo kerak (hozir {len(ys)} kun). Taxmin qilinmadi."}
        n = len(ys)
        xs = list(range(n))
        mx, my = sum(xs) / n, sum(ys) / n
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sum((x - mx) ** 2 for x in xs) or 1)
        base = my - slope * mx
        wk = defaultdict(list)
        last_date = date.fromisoformat(ds["series"][-1]["date"])
        for i, y in enumerate(ys):
            trend = base + slope * i
            if trend > 0:
                wk[(last_date - timedelta(days=n - 1 - i)).weekday()].append(y / trend)
        factor = {k: sum(v) / len(v) for k, v in wk.items() if v}
        out = []
        for h in range(1, horizon + 1):
            d = last_date + timedelta(days=h)
            v = max(0.0, (base + slope * (n - 1 + h)) * factor.get(d.weekday(), 1.0))
            out.append({"date": str(d), "amount": round(v, 2)})
        return {"forecast": out, "trend_per_day": round(slope, 2), "method": "chiziqli trend × hafta kuni koeffitsiyenti (oxirgi 60 kun)",
                "sources": ds["sources"], "note": "Bu statistik TAXMIN, kafolat emas. Bayramlar, aksiyalar va qoldiq yetishmasligi hisobga olinmagan."}

    def anomalies(self) -> dict:
        ds = self.daily_sales()
        ys = [x["amount"] for x in ds["series"]]
        if len(ys) < 14:
            return {"anomalies": [], "note": "Kamida 14 kunlik savdo kerak."}
        out = []
        for i in range(7, len(ys)):
            win = ys[max(0, i - 28):i]
            mu = sum(win) / len(win)
            sd = math.sqrt(sum((y - mu) ** 2 for y in win) / len(win)) or 1.0
            z = (ys[i] - mu) / sd
            if abs(z) >= 2.5:
                out.append({"date": ds["series"][i]["date"], "amount": ys[i], "expected": round(mu, 2), "z": round(z, 2),
                            "kind": "keskin o'sish" if z > 0 else "keskin pasayish"})
        return {"anomalies": out[-20:], "method": "oldingi 28 kunga nisbatan z-baho ≥ 2.5", "sources": ds["sources"]}

    def overview(self) -> dict:
        a = self.core.analyst
        qs = {"today": "bugungi savdo qancha", "top": "eng ko'p sotilgan mahsulotlar", "low_stock": "qoldig'i kam mahsulotlar", "debts": "qarzdorlar", "stores": "qaysi do'konda savdo pasaydi"}
        res = {k: a.answer(q) for k, q in qs.items()}
        return {"answers": {k: {"text": v.get("text"), "sources": v.get("sources"), "limitations": v.get("limitations")} for k, v in res.items()},
                "connections": [c for c in self.core.integrations.health() if c["type"] in ("pos", "erp", "crm", "database", "files")],
                "mode_note": "Biznes ma'lumotlari faqat o'qiladi. Tashqi POS/ERP'ga yozish — taklif + tasdiq (moliyaviy — E daraja)."}


# ---------------- Creative Factory ----------------
class CreativeFactory:
    def __init__(self, core):
        self.core = core

    def capabilities(self) -> dict:
        c = self.core
        tools, ig = c.studio.tools(), c.imagegen.status()
        vp = c.voice_pro.status()
        capmap = c.ai_hub.capability_map()
        cloud = lambda cap: [f"{m['provider']}/{m['model']}" for m in capmap.get(cap, [])][:5]  # noqa: E731
        rows = [
            {"service": "Video montaj (FFmpeg): kesish, birlashtirish, 9:16, subtitr, ovoz, format", "status": "ready" if tools["ffmpeg"] else "missing",
             "note": "" if tools["ffmpeg"] else "FFmpeg o'rnatilmagan", "where": "#studio"},
            {"service": "Rasm: o'lcham, matn qo'shish, logo (Pillow)", "status": "ready" if tools["pillow"] else "missing", "note": "", "where": "#studio"},
            {"service": "Rasm yaratish — mahalliy Stable Diffusion WebUI", "status": "ready" if ig["generator"]["available"] else "not_configured",
             "note": ig["generator"].get("note", ""), "where": "#studio"},
            {"service": "Rasm tahlili — mahalliy vision model", "status": "ready" if ig["vision"]["available"] else "not_configured", "note": ig["vision"]["note"], "where": "#studio"},
            {"service": "Ovoz (TTS) — Azure o'zbek / espeak", "status": "ready" if vp["selected"]["tts"] not in ("browser", "none") else "browser_only", "note": f"hozir: {vp['selected']['tts']}", "where": "#voice"},
            {"service": "Subtitr / nutqni tanish (Whisper / Azure)", "status": "ready" if vp["selected"]["stt"] not in ("browser", "none") else "browser_only", "note": f"hozir: {vp['selected']['stt']}", "where": "#voice"},
            {"service": "Bulut rasm yaratish modellari", "status": "model_only" if cloud("image_generation") else "not_connected",
             "note": ("Ulangan modellar: " + ", ".join(cloud("image_generation")) + ". JARVIS'da ular uchun generatsiya adapteri HALI YO'Q — keyingi bosqich.")
             if cloud("image_generation") else "Rasm modeli bor provayder ulanmagan", "where": "#aihub"},
            {"service": "Bulut video yaratish", "status": "model_only" if cloud("video_generation") else "not_connected",
             "note": "Oddiy chat API bilan video yaratib bo'lmaydi — maxsus video servisi va adapter kerak (keyingi bosqich).", "where": "#aihub"},
            {"service": "Taqdimot (PPTX) yaratish", "status": "not_implemented", "note": "File Intelligence bosqichida (python-pptx)", "where": ""},
        ]
        return {"services": rows, "pipeline": ["matn/ssenariy (AI Router)", "ovoz (TTS)", "rasm/slaydlar", "video montaj (FFmpeg)", "subtitr", "Instagram (tasdiq bilan)"]}
