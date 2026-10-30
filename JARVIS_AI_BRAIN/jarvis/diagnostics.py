"""Observability & Diagnostics — yagona diagnostika hisoboti.

Holatlar: ok | warning | error | unknown ("tekshirib bo'lmadi") | not_configured.
Tekshirib bo'lmaydigan narsa hech qachon "ok" deb ko'rsatilmaydi. Hisobot va eksport maxfiy ma'lumotlardan tozalanadi.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import statistics
import subprocess
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from . import __version__, net
from .config import PROJECT_ROOT
from .secrets import get_secret
from .security import redact

ORDER = ["ok", "not_configured", "unknown", "warning", "error"]
CATEGORIES = [
    ("network", r"(?i)tarmoq|connection|timeout|timed out|neterror|refused|dns|unreachable|ulanib bo.lmadi"),
    ("permission", r"(?i)ruxsat|permission|taqiq|forbidden|denied|tasdiqlanmagan"),
    ("ai", r"(?i)ollama|model|\bai\b|router|token"),
    ("database", r"(?i)sqlite|database|integrity|locked"),
    ("external_api", r"(?i)telegram|instagram|graph api|meta|api xatosi"),
    ("validation", r"(?i)noto'g'ri|majburiy|kerak|invalid|valueerror|keyerror|topilmadi"),
]
CATEGORY_UZ = {"network": "Tarmoq", "permission": "Ruxsat/xavfsizlik", "ai": "AI modeli", "database": "Ma'lumotlar bazasi",
               "external_api": "Tashqi API", "validation": "Ma'lumot/kiritish", "other": "Boshqa"}


def categorize(message: str) -> str:
    for cat, rx in CATEGORIES:
        if re.search(rx, message or ""):
            return cat
    return "other"


class RequestMetrics:
    def __init__(self, maxlen: int = 5000):
        self.items: deque = deque(maxlen=maxlen)
        self.lock = threading.Lock()
        self.started = time.time()

    def add(self, method: str, path: str, status: int, ms: float):
        with self.lock:
            self.items.append((method, path, status, ms, time.time()))

    def summary(self) -> list[dict]:
        groups = defaultdict(list)
        with self.lock:
            for m, p, st, ms, _ in self.items:
                groups[(m, p)].append((st, ms))
        out = []
        for (m, p), rows in groups.items():
            ms = sorted(r[1] for r in rows)
            out.append({"route": f"{m} {p}", "count": len(rows), "p50_ms": round(statistics.median(ms), 1),
                        "p95_ms": round(ms[min(len(ms) - 1, int(len(ms) * 0.95))], 1), "max_ms": round(ms[-1], 1),
                        "errors_4xx": sum(1 for r in rows if 400 <= r[0] < 500), "errors_5xx": sum(1 for r in rows if r[0] >= 500)})
        return sorted(out, key=lambda r: -r["p95_ms"])


def _c(name, status, detail="", latency_ms=None, **extra) -> dict:
    return {"name": name, "status": status, "detail": detail, "latency_ms": latency_ms,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")} | extra


class Diagnostics:
    def __init__(self, core, metrics: RequestMetrics | None = None):
        self.core = core
        self.metrics = metrics or RequestMetrics()

    # --- komponentlar ---
    def backend(self) -> dict:
        up = int(time.time() - self.metrics.started)
        return _c("backend", "ok", f"JARVIS {__version__}, ishlash vaqti {up // 3600} soat {up % 3600 // 60} daqiqa", pid=os.getpid())

    def frontend(self) -> list[dict]:
        d = PROJECT_ROOT / "dashboard"
        files = ["index.html", "app.js", "modules.js", "advanced.js", "guides.js", "brain.js", "voice.js", "connections.js", "ai_hub.js", "mission.js", "style.css", "vendor/three/three.min.js", "vendor/three/OrbitControls.js"]
        missing = [f for f in files if not (d / f).exists() or (d / f).stat().st_size == 0]
        out = [_c("frontend_files", "error" if missing else "ok", f"yo'q yoki bo'sh: {missing}" if missing else f"{len(files)} ta fayl mavjud")]
        node = shutil.which("node")
        if not node:
            out.append(_c("frontend_js_syntax", "unknown", "tekshirib bo'lmadi: Node.js o'rnatilmagan"))
        else:
            bad = []
            for f in ("app.js", "modules.js", "advanced.js", "guides.js", "brain.js", "voice.js", "connections.js", "ai_hub.js", "mission.js"):
                p = subprocess.run([node, "--check", str(d / f)], capture_output=True, text=True, timeout=20)
                if p.returncode != 0:
                    bad.append(f"{f}: {p.stderr.strip().splitlines()[0] if p.stderr else 'xato'}")
            out.append(_c("frontend_js_syntax", "error" if bad else "ok", "; ".join(bad) or "barcha dashboard JS fayllari sintaksisi to'g'ri"))
        return out

    def database(self) -> dict:
        t0 = time.monotonic()
        try:
            self.core.db.one("SELECT 1 x")
            quick = self.core.db.one("PRAGMA quick_check")
            ms = round((time.monotonic() - t0) * 1000, 1)
            size = self.core.db.path.stat().st_size / 2**20 if self.core.db.path.exists() else 0
            ok = list(quick.values())[0] == "ok"
            return _c("database", "ok" if ok else "error", f"quick_check={list(quick.values())[0]}, hajm {size:.1f} MB", ms)
        except Exception as e:
            return _c("database", "error", str(e))

    def ai(self) -> list[dict]:
        out = []
        for p in self.core.ai.status():
            if p["kind"] == "offline":
                out.append(_c(f"ai:{p['id']}", "ok", "zaxira: qoidaga asoslangan javob (AI emas)"))
            else:
                out.append(_c(f"ai:{p['id']}", "ok" if p["available"] else "error", p["note"], model=p["model"], paid=p["paid"]))
        return out

    def telegram(self) -> dict:
        tg = self.core.telegram
        if not tg.token():
            return _c("telegram", "not_configured", "bot tokeni kiritilmagan")
        t0 = time.monotonic()
        try:
            r = tg._call("getMe")
            owner = tg.owner()
            if not (owner and owner["active"]):
                return _c("telegram", "warning", f"bot @{r['result'].get('username')} ishlaydi, lekin egasi ulanmagan "
                          "(dashboard → Telegram → 'Akkauntni ulash')", round((time.monotonic() - t0) * 1000, 1))
            return _c("telegram", "ok", f"bot @{r['result'].get('username')}, egasi ulangan", round((time.monotonic() - t0) * 1000, 1),
                      polling=tg.status()["running"])
        except Exception as e:
            msg = str(e)
            return _c("telegram", "unknown" if categorize(msg) == "network" else "error",
                      ("tekshirib bo'lmadi: " if categorize(msg) == "network" else "") + msg)

    def instagram(self) -> list[dict]:
        accs = self.core.settings.instagram_accounts
        if not accs:
            return [_c("instagram", "not_configured", "akkaunt sozlanmagan")]
        out = []
        for a in accs:
            if not get_secret(f"instagram_token_{a['name']}"):
                out.append(_c(f"instagram:{a['name']}", "not_configured", "token kiritilmagan"))
                continue
            st = self.core.instagram.account_status(a["name"])
            if st["connected"]:
                out.append(_c(f"instagram:{a['name']}", "ok", f"@{st.get('username')}"))
            else:
                net_issue = categorize(st.get("note", "")) == "network"
                out.append(_c(f"instagram:{a['name']}", "unknown" if net_issue else "error",
                              ("tekshirib bo'lmadi: " if net_issue else "") + st.get("note", "")))
        return out

    def internet(self) -> dict:
        if not self.core.settings.internet_enabled:
            return _c("internet", "not_configured", "internet tadqiqoti o'chirilgan")
        t0 = time.monotonic()
        try:
            st, _ = net.request("GET", "https://html.duckduckgo.com/html/", timeout=5)
            return _c("internet", "ok" if st < 500 else "error", f"qidiruv xizmati HTTP {st}", round((time.monotonic() - t0) * 1000, 1))
        except net.NetError as e:
            return _c("internet", "unknown", f"tekshirib bo'lmadi: {e}")

    def pos(self) -> dict:
        st = self.core.pos.status()
        if not st.get("connected"):
            return _c("pos", "not_configured", st.get("note", ""))
        outbox = getattr(self.core.pos.connector, "outbox", None)
        if outbox is not None:
            writable = os.access(outbox, os.W_OK)
            return _c("pos", "ok" if writable else "error", f"{st['connector']}: {outbox}" + ("" if writable else " — yozib bo'lmaydi"))
        return _c("pos", "unknown", f"{st['connector']}: holatni tekshirish usuli yo'q")

    def agents(self) -> dict:
        ag = [a.public() for a in self.core.agents.agents.values()]
        err = [a["key"] for a in ag if a["status"] == "error"]
        return _c("agents", "warning" if err else "ok", f"xatoli: {err}" if err else f"{len(ag)} ta agent", agents=[
            {k: a[k] for k in ("key", "title", "status", "current_task", "last_error")} for a in ag])

    def queue(self) -> dict:
        db = self.core.db
        q = self.core.agents.q.qsize()
        running = db.one("SELECT COUNT(*) n FROM tasks WHERE status IN ('queued','running')")["n"]
        dag_running = db.one("SELECT COUNT(*) n FROM dag_runs WHERE status='running'")["n"]
        last_ok = db.one("SELECT MAX(finished_at) t FROM tasks WHERE status='done'")["t"]
        failed24 = db.one("SELECT COUNT(*) n FROM tasks WHERE status='failed' AND julianday('now')-julianday(created_at) < 1")["n"]
        stuck = db.one("SELECT COUNT(*) n FROM tasks WHERE status='running' AND julianday('now')-julianday(COALESCE(started_at, created_at)) > 1.0/24")["n"]
        status = "error" if stuck else "warning" if failed24 else "ok"
        return _c("task_queue", status, f"navbatda {q}, faol {running}, graf {dag_running}, 24 soatda xato {failed24}"
                  + (f", 1 soatdan ortiq osilib qolgan {stuck}" if stuck else ""), last_success=last_ok)

    def backups(self) -> dict:
        st = self.core.backup.status()
        if st["last_success"] is None:
            return _c("backup", "warning", "hali zaxira nusxa olinmagan")
        if st["overdue"]:
            return _c("backup", "warning", f"oxirgi nusxa {st['age_hours']} soat oldin (jadval: {st['interval_hours']} soat)")
        return _c("backup", "ok", f"oxirgi nusxa {st['age_hours']} soat oldin, jami {st['count']}")

    def errors(self, limit: int = 200) -> dict:
        rows = self.core.audit.recent_errors(limit)
        by_cat: dict[str, list] = defaultdict(list)
        for e in rows:
            by_cat[categorize(e["message"])].append(e)
        return {"total": len(rows), "by_category": [{"category": c, "label": CATEGORY_UZ[c], "count": len(v),
                                                     "latest": v[0]["message"][:200], "latest_ts": v[0]["ts"]}
                                                    for c, v in sorted(by_cat.items(), key=lambda x: -len(x[1]))],
                "recent": [e | {"category": categorize(e["message"])} for e in rows[:20]]}

    # --- umumiy ---
    def run(self, external: bool = True) -> dict:
        comps = [self.backend(), *self.frontend(), self.database(), *self.ai(), self.pos(), self.agents(), self.queue(), self.backups()]
        if external:
            comps += [self.telegram(), *self.instagram(), self.internet()]
        else:
            comps += [_c("external_services", "unknown", "tashqi xizmatlar bu safar tekshirilmadi (external=0)")]
        core_bad = [c for c in comps if c["name"] in ("backend", "database", "frontend_files") and c["status"] == "error"]
        worst = max((c["status"] for c in comps), key=ORDER.index)
        overall = "down" if core_bad else "degraded" if worst in ("error", "warning") else "healthy"
        counts: dict[str, int] = defaultdict(int)
        for c in comps:
            counts[c["status"]] += 1
        return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "overall": overall,
                "counts": dict(counts), "components": comps, "errors": self.errors(), "responses": self.metrics.summary(),
                "resources": self.core.guard.process_resources(), "note": "'unknown' — tekshirib bo'lmadi; sog'lom deb hisoblanmaydi."}

    def export(self, external: bool = True) -> str:
        return redact(json.dumps(self.run(external), ensure_ascii=False, indent=1, default=str))
