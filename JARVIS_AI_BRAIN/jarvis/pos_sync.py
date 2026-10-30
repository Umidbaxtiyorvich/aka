"""POS hisobotlarini avtomatik o'qish (masalan YesPOS) — FAQAT O'QISH.

Oqim (jadval bo'yicha, `pos_sync.interval_hours`):
  siz kirgan brauzer sessiyasi → hisobot sahifalari → jadvallar CSV → BI import (manba bo'yicha almashtirish)
  → tahlil → muhim holatlar bo'yicha bildirishnoma (kam qolgan, noto'g'ri narx, takroriy hujjat, tafovut).
* POS'ga hech narsa yozilmaydi va bosilmaydi.
* Sessiya tugasa — sinxronlash to'xtaydi va "qayta kiring" bildirishnomasi keladi (kuniga bir marta).
* Sozlama (`settings.json` yoki dashboard):
  "pos_sync": {"enabled": true, "interval_hours": 6,
               "sources": [{"name": "qoldiq", "url": "https://app.yespos.uz/reports/...", "kind": "auto"}]}
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from .bi import BIError
from .browser import BrowserError

SCHEMA = """
CREATE TABLE IF NOT EXISTS pos_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), status TEXT NOT NULL,
    detail TEXT, imported INTEGER NOT NULL DEFAULT 0, alerts INTEGER NOT NULL DEFAULT 0
);
"""


class POSSyncError(Exception):
    pass


class POSSync:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        self._lock = threading.Lock()
        self._thread = None

    @property
    def cfg(self) -> dict:
        c = dict(self.core.settings.pos_sync or {})
        c.setdefault("enabled", False)
        c.setdefault("interval_hours", 6)
        c.setdefault("sources", [])
        return c

    def _record(self, status: str, detail: str, imported: int = 0, alerts: int = 0) -> dict:
        cur = self.core.db.execute("INSERT INTO pos_sync_runs(status, detail, imported, alerts) VALUES (?,?,?,?)",
                                   (status, detail[:2000], imported, alerts))
        return self.core.db.one("SELECT * FROM pos_sync_runs WHERE id=?", (cur.lastrowid,))

    def history(self, limit: int = 30) -> list[dict]:
        return self.core.db.query("SELECT * FROM pos_sync_runs ORDER BY id DESC LIMIT ?", (limit,))

    def status(self) -> dict:
        last = self.core.db.one("SELECT * FROM pos_sync_runs ORDER BY id DESC LIMIT 1")
        ok = self.core.db.one("SELECT * FROM pos_sync_runs WHERE status='ok' ORDER BY id DESC LIMIT 1")
        return {"config": self.cfg, "last_run": last, "last_success": ok, "session": self.core.session_browser.status(),
                "running": bool(self._thread and self._thread.is_alive())}

    def _alert_once(self, key: str, title: str, body: str, severity: str = "warning"):
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.core.db.one("SELECT 1 x FROM guard_alerts WHERE day=? AND kind=?", (day, key)):
            return 0
        self.core.db.execute("INSERT INTO guard_alerts(day, kind) VALUES (?,?)", (day, key))
        self.core.notifier.notify(title, body, severity=severity, category="pos")
        return 1

    def run(self) -> dict:
        """Bir martalik sinxronlash (qo'lda yoki jadval bo'yicha)."""
        sources = self.cfg["sources"]
        if not sources:
            raise POSSyncError("Hisobot manbalari sozlanmagan (POS ulanishi → Avtomatik o'qish)")
        if not self._lock.acquire(blocking=False):
            raise POSSyncError("Sinxronlash allaqachon ishlayapti")
        try:
            imported, problems, notes = 0, [], []
            for src in sources:
                name, url, kind = src.get("name") or url_name(src["url"]), src["url"], src.get("kind", "auto")
                try:
                    r = self.core.session_browser.extract_tables(url, wait_ms=int(src.get("wait_ms", 3000)))
                except BrowserError as e:
                    problems.append(f"{name}: {e}")
                    continue
                if r["status"] == "login_required":
                    self._alert_once("pos_login", "POS sessiyasi tugagan", "YesPOS'ga qayta kiring: POS ulanishi → «POS'ga kirish».")
                    rec = self._record("login_required", f"{name}: sessiya tugagan")
                    return rec | {"problems": [f"{name}: qayta kirish kerak"]}
                if not r["tables"]:
                    problems.append(f"{name}: sahifada jadval topilmadi")
                    continue
                for i, t in enumerate(r["tables"], 1):
                    try:
                        res = self.core.bi.import_file(t["path"], kind, replace_source=f"pos_sync:{name}:{i}")
                    except BIError as e:
                        problems.append(f"{name} #{i}: {e}")
                        continue
                    if res.get("unchanged"):
                        notes.append(f"{name} #{i}: o'zgarmagan")
                    else:
                        imported += res["rows_ok"]
                        notes.append(f"{name} #{i}: {res['kind']}, {res['rows_ok']} qator" + (f", {res['rows_bad']} xato" if res["rows_bad"] else ""))
            alerts = self._analyse()
            status = "ok" if not problems else ("partial" if imported or notes else "failed")
            if status == "failed":
                self._alert_once("pos_sync_failed", "POS sinxronlash ishlamadi", "; ".join(problems)[:400])
            self.core.audit.log("pos_sync", f"POS hisobotlari o'qildi: {status}", target="pos", risk="A",
                                result=f"{imported} qator, {alerts} ogohlantirish")
            return self._record(status, "; ".join(notes + problems), imported, alerts) | {"problems": problems, "notes": notes}
        finally:
            self._lock.release()

    def _analyse(self) -> int:
        r = self.core.bi.report()
        n = 0
        if r["low_stock"]:
            items = ", ".join(f"{x['name'] or x['sku']} ({x['current']})" for x in r["low_stock"][:8])
            n += self._alert_once("pos_low_stock", f"Kam qolgan mahsulotlar: {len(r['low_stock'])}", items)
        if r["price_issues"]:
            n += self._alert_once("pos_price", f"Narx/miqdor muammolari: {len(r['price_issues'])}",
                                  "; ".join(f"{x['sku']}: {x['issue']}" for x in r["price_issues"][:5]))
        if r["duplicates"]:
            n += self._alert_once("pos_dup", f"Takroriy hujjatlar: {len(r['duplicates'])}", "BI bo'limida tekshiring")
        big = [d for d in r["discrepancies"] if d.get("difference") not in (None, 0) and abs(d["difference"]) >= 10]
        if big:
            n += self._alert_once("pos_discrepancy", f"Omborda katta tafovut: {len(big)}",
                                  "; ".join(f"{d['sku']}: {d['difference']}" for d in big[:5]), severity="critical")
        return n

    # --- jadval ---
    def start(self, check_every_sec: int = 300):
        if self._thread and self._thread.is_alive():
            return

        def loop():
            while True:
                time.sleep(check_every_sec)
                cfg = self.cfg
                if getattr(self.core, "automation_paused", False) or not cfg["enabled"] or not cfg["sources"]:
                    continue
                last = self.core.db.one("SELECT ts FROM pos_sync_runs ORDER BY id DESC LIMIT 1")
                if last:
                    age = self.core.db.one("SELECT (julianday('now') - julianday(?)) * 24 AS h", (last["ts"],))["h"]
                    if age < float(cfg["interval_hours"]):
                        continue
                try:
                    self.run()
                except Exception as e:  # jadval xatosi serverni to'xtatmasin
                    self.core.audit.error("pos_sync", str(e))
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()


def url_name(url: str) -> str:
    from urllib.parse import urlparse
    return (urlparse(url).path.strip("/").replace("/", "_") or "hisobot")[:40]
