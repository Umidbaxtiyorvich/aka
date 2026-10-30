"""Resource & Cost Guard — AI so'rovlari, tokenlar, xarajat, vaqt va resurslarni kuzatadi va cheklaydi.

Halollik qoidasi: har bir ko'rsatkich `measured` (haqiqiy o'lchov) yoki `estimated` (taxmin) deb belgilanadi.
* Tokenlar: provayder API qaytarsa — o'lchangan; aks holda belgilar/4 — taxminiy.
* Xarajat: token × siz kiritgan narx. Provayderning haqiqiy hisob-fakturasi emas.
* RAM/CPU: psutil bilan o'lchanadi; o'lchab bo'lmasa — "o'lchab bo'lmadi".
Pullik so'rovlar: `paid_ai_allowed` o'chiq bo'lsa yoki limit belgilanmagan/tugagan bo'lsa — bloklanadi.
"""
from __future__ import annotations

from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')),
    provider TEXT NOT NULL, model TEXT, tier TEXT, purpose TEXT, paid INTEGER NOT NULL DEFAULT 0,
    tokens_in INTEGER, tokens_out INTEGER, tokens_measured INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0, cost_measured INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER, ok INTEGER NOT NULL, retries INTEGER NOT NULL DEFAULT 0, error TEXT, fallback_from TEXT
);
CREATE TABLE IF NOT EXISTS model_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), usage_id INTEGER,
    provider TEXT NOT NULL, model TEXT, score INTEGER NOT NULL, source TEXT NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS guard_alerts (day TEXT NOT NULL, kind TEXT NOT NULL, PRIMARY KEY(day, kind));
"""


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


class CostLimitError(Exception):
    pass


class ResourceGuard:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        core.db.ensure_columns("tasks", {"started_at": "TEXT"})

    @property
    def s(self):
        return self.core.settings

    # --- yozish ---
    def record(self, *, provider: str, model: str | None, tier: str = "", purpose: str = "", paid: bool = False,
               tokens_in: int | None = None, tokens_out: int | None = None, tokens_measured: bool = False,
               price_in: float = 0.0, price_out: float = 0.0, duration_ms: int = 0, ok: bool = True,
               retries: int = 0, error: str = "", fallback_from: str = "") -> dict:
        cost = ((tokens_in or 0) * price_in + (tokens_out or 0) * price_out) / 1000 if paid else 0.0
        cur = self.core.db.execute(
            "INSERT INTO ai_usage(provider, model, tier, purpose, paid, tokens_in, tokens_out, tokens_measured, cost,"
            " cost_measured, duration_ms, ok, retries, error, fallback_from) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (provider, model, tier, purpose, int(paid), tokens_in, tokens_out, int(tokens_measured), round(cost, 6),
             int(tokens_measured and paid), duration_ms, int(ok), retries, error[:300], fallback_from))
        if paid:
            self._check_thresholds()
        return {"cost": round(cost, 6), "cost_measured": tokens_measured and paid, "usage_id": cur.lastrowid}

    # --- hisob ---
    def _sum(self, where: str, params: tuple = ()) -> dict:
        r = self.core.db.one(
            "SELECT COUNT(*) n, COALESCE(SUM(cost),0) cost, COALESCE(SUM(1-ok),0) failed, COALESCE(SUM(retries),0) retries,"
            " COALESCE(SUM(CASE WHEN tokens_measured=1 THEN COALESCE(tokens_in,0)+COALESCE(tokens_out,0) END),0) tok_m,"
            " COALESCE(SUM(CASE WHEN tokens_measured=0 THEN COALESCE(tokens_in,0)+COALESCE(tokens_out,0) END),0) tok_e,"
            " COALESCE(SUM(CASE WHEN paid=1 AND cost_measured=0 THEN cost END),0) cost_est"
            f" FROM ai_usage WHERE {where}", params)
        return {"requests": r["n"], "failed": r["failed"], "retries": r["retries"], "cost": round(r["cost"], 4),
                "cost_estimated_part": round(r["cost_est"], 4), "tokens_measured": r["tok_m"], "tokens_estimated": r["tok_e"]}

    def today(self) -> dict:
        return self._sum("date(ts)=date('now')")

    def month(self) -> dict:
        return self._sum("strftime('%Y-%m', ts)=strftime('%Y-%m','now')")

    # --- cheklov ---
    def check(self, *, paid: bool, est_cost: float = 0.0) -> tuple[bool, str]:
        t = self.today()
        if self.s.daily_request_limit and t["requests"] >= self.s.daily_request_limit:
            return False, f"Kunlik AI so'rov limiti tugadi ({self.s.daily_request_limit})"
        if not paid:
            return True, "bepul/mahalliy"
        if not self.s.paid_ai_allowed:
            return False, "Pullik AI o'chirilgan (Sozlamalar → Xarajat nazorati)"
        if self.s.daily_cost_limit <= 0 or self.s.monthly_cost_limit <= 0:
            return False, "Pullik AI uchun kunlik va oylik xarajat limiti belgilanmagan"
        mx = float(getattr(self.s, "ai_max_request_cost", 0) or 0)
        if mx > 0 and est_cost > mx:
            return False, f"Bir so'rov uchun maksimal xarajatdan oshadi ({est_cost:.4f} > {mx} {self.s.currency})"
        if t["cost"] + est_cost > self.s.daily_cost_limit:
            self._alert("daily_limit", f"Kunlik limit ({self.s.daily_cost_limit} {self.s.currency}) tugadi — pullik so'rovlar to'xtatildi")
            return False, f"Kunlik xarajat limiti tugaydi ({t['cost']}+{est_cost:.4f} > {self.s.daily_cost_limit} {self.s.currency})"
        m = self.month()
        if m["cost"] + est_cost > self.s.monthly_cost_limit:
            self._alert("monthly_limit", f"Oylik limit ({self.s.monthly_cost_limit} {self.s.currency}) tugadi")
            return False, f"Oylik xarajat limiti tugaydi ({m['cost']}+{est_cost:.4f} > {self.s.monthly_cost_limit} {self.s.currency})"
        return True, "limit doirasida"

    def _alert(self, kind: str, text: str):
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.core.db.one("SELECT 1 x FROM guard_alerts WHERE day=? AND kind=?", (day, kind)):
            return
        self.core.db.execute("INSERT INTO guard_alerts(day, kind) VALUES (?,?)", (day, kind))
        if hasattr(self.core, "notifier"):
            self.core.notifier.notify("Xarajat nazorati", text, severity="warning", category="cost")

    def _check_thresholds(self):
        pct = self.s.cost_warn_percent / 100
        if self.s.daily_cost_limit > 0 and self.today()["cost"] >= pct * self.s.daily_cost_limit:
            self._alert("daily_warn", f"Kunlik AI xarajati limitning {self.s.cost_warn_percent}% iga yetdi")
        if self.s.monthly_cost_limit > 0 and self.month()["cost"] >= pct * self.s.monthly_cost_limit:
            self._alert("monthly_warn", f"Oylik AI xarajati limitning {self.s.cost_warn_percent}% iga yetdi")

    # --- hisobot ---
    def providers(self) -> list[dict]:
        rows = self.core.db.query(
            "SELECT provider, model, COUNT(*) n, ROUND(AVG(ok)*100,1) success_pct, CAST(AVG(duration_ms) AS INT) avg_ms,"
            " ROUND(SUM(cost),4) cost, SUM(CASE WHEN fallback_from<>'' THEN 1 ELSE 0 END) as fallbacks_in"
            " FROM ai_usage GROUP BY provider, model ORDER BY n DESC")
        return rows

    def process_resources(self) -> dict:
        try:
            import psutil
            p = psutil.Process()
            vm = psutil.virtual_memory()
            return {"measured": True, "jarvis_rss_mb": round(p.memory_info().rss / 2**20, 1),
                    "jarvis_cpu_percent": p.cpu_percent(interval=0.1), "jarvis_threads": p.num_threads(),
                    "system_ram_used_percent": vm.percent, "system_cpu_percent": psutil.cpu_percent(interval=None)}
        except Exception as e:  # psutil yo'q yoki ruxsat yo'q
            return {"measured": False, "note": f"o'lchab bo'lmadi: {type(e).__name__}"}

    def local_model_resources(self) -> dict:
        from . import net
        url = self.s.ollama_url.rstrip("/") + "/api/ps"
        try:
            data = net.get_json(url, timeout=2)
        except Exception:
            return {"measured": False, "note": "Ollama ishlamayapti yoki javob bermadi — o'lchab bo'lmadi"}
        return {"measured": True, "models": [{"name": m.get("name"), "size_mb": round(m.get("size", 0) / 2**20),
                                              "vram_mb": round(m.get("size_vram", 0) / 2**20)} for m in data.get("models", [])]}

    def task_durations(self) -> list[dict]:
        return self.core.db.query(
            "SELECT agent, COUNT(*) n, ROUND(AVG((julianday(finished_at)-julianday(COALESCE(started_at, created_at)))*86400000)) avg_ms,"
            " SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed FROM tasks WHERE finished_at IS NOT NULL GROUP BY agent")

    def reliability(self) -> dict:
        """Qayta urinishlar va xatolar (bugun): AI chaqiruvlari, fallbacklar, modul xatolari, vazifa xatolari."""
        db = self.core.db
        ai = db.query("SELECT provider, SUM(ok=0) failed, SUM(retries) retries, SUM(fallback_from IS NOT NULL AND fallback_from<>'') fallbacks,"
                      " COUNT(*) n FROM ai_usage WHERE ts >= date('now') GROUP BY provider ORDER BY failed DESC")
        errs = db.query("SELECT module, COUNT(*) n FROM errors WHERE ts >= date('now') GROUP BY module ORDER BY n DESC LIMIT 10")
        tasks = db.one("SELECT SUM(status='failed') failed, COUNT(*) n FROM tasks WHERE created_at >= date('now')")
        return {"ai": ai, "errors_by_module": errs, "tasks_today": {"total": tasks["n"] or 0, "failed": tasks["failed"] or 0},
                "measured": True, "note": "Bugungi (UTC) yozuvlardan hisoblangan — real vaqt oqimi emas."}

    def summary(self) -> dict:
        s = self.s
        return {"today": self.today(), "month": self.month(),
                "limits": {"paid_ai_allowed": s.paid_ai_allowed, "daily_cost_limit": s.daily_cost_limit,
                           "monthly_cost_limit": s.monthly_cost_limit, "daily_request_limit": s.daily_request_limit,
                           "warn_percent": s.cost_warn_percent, "currency": s.currency},
                "providers": self.providers(), "process": self.process_resources(),
                "task_durations": self.task_durations(), "reliability": self.reliability(),
                "notes": ["Xarajat = token × siz kiritgan narx (provayder hisob-fakturasi emas).",
                          "Token 'estimated' bo'lsa — belgilar/4 taxmini, haqiqiy o'lchov emas."]}
