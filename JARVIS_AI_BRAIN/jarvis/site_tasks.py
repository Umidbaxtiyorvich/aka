"""Site Tasks — saytdagi amalni bir marta ko'rsatib o'rgatish, keyin buyruq bilan (tasdiq orqali) takrorlash.

Masalan, YesPOS'da "kirim": siz bir marta ko'rinadigan brauzerda kirim qilib ko'rsatasiz (kontragent tanlash, tovar, miqdor,
narx, "Saqlash"). JARVIS bosilgan tugmalar va to'ldirilgan maydonlarni yozib oladi; siz qaysi qiymatlar o'zgaruvchi ekanini
belgilaysiz (kontragent, tovar, miqdor, narx). Keyin chatda: "Ali akaga 10 ta Coca-Cola 12 000 dan kirim qil" → JARVIS
(AI orqali) parametrlarni ajratadi → TASDIQ so'raydi (D, moliyaviy bo'lsa E) → tasdiqdan keyin xuddi shu qadamlarni bajaradi,
natijani tekshiradi va skrinshot bilan hisobot beradi.

Xavfsizlik: parol maydonlari yozib olinmaydi; bajarish faqat tasdiqdan keyin, bir marta (takror yo'q); qadam xato bersa —
darhol to'xtaydi va holat "noma'lum" (POS'da tekshirish kerak) deb aytiladi; faqat shu ulanish domeni; CAPTCHA/2FA
chetlab o'tilmaydi.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path

from .security import contains_secret, redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, conn_id INTEGER NOT NULL, name TEXT NOT NULL, description TEXT, start_url TEXT,
    steps TEXT NOT NULL DEFAULT '[]', params TEXT NOT NULL DEFAULT '[]', success_text TEXT, status TEXT NOT NULL DEFAULT 'draft',
    financial INTEGER NOT NULL DEFAULT 0, runs INTEGER NOT NULL DEFAULT 0, verified INTEGER NOT NULL DEFAULT 0, last_status TEXT,
    note TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT
);
CREATE TABLE IF NOT EXISTS site_task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), task_id INTEGER, approval_id INTEGER, params TEXT,
    status TEXT NOT NULL, step INTEGER, error TEXT, screenshot TEXT
);
"""
FIN_RX = re.compile(r"(?i)kirim|chiqim|savdo|sotuv|to'?lov|qaytar|kassa|prixod|приход|расход|продаж|оплат|payment|invoice|refund")
RECORD_JS = r"""(() => {
  if (window.__jarvisRec) return; window.__jarvisRec = 1;
  const rec = (x) => { try { window.jarvisRecord(x); } catch (e) {} };
  const uniq = (s) => { try { return document.querySelectorAll(s).length === 1; } catch (e) { return false; } };
  const sel = (e) => {
    if (e.id && !/\d{5,}|^(:|ember|react)/i.test(e.id)) return '#' + CSS.escape(e.id);
    for (const a of ['name', 'data-testid', 'data-test', 'aria-label', 'placeholder', 'title']) {
      const v = e.getAttribute(a); if (!v) continue;
      const s = e.tagName.toLowerCase() + '[' + a + '="' + v.replace(/"/g, '\\"') + '"]'; if (uniq(s)) return s;
    }
    const t = (e.innerText || e.value || '').trim();
    if (t && t.length < 40 && /^(BUTTON|A|LI)$/.test(e.tagName)) return e.tagName.toLowerCase() + ':has-text("' + t.replace(/"/g, '') + '")';
    const p = []; let n = e;
    while (n && n.nodeType === 1 && p.length < 7) {
      if (n.id && !/\d{5,}/.test(n.id)) { p.unshift('#' + CSS.escape(n.id)); break; }
      let s = n.tagName.toLowerCase(); const par = n.parentElement;
      if (par) { const sib = [...par.children].filter(c => c.tagName === n.tagName); if (sib.length > 1) s += ':nth-of-type(' + (sib.indexOf(n) + 1) + ')'; }
      p.unshift(s); n = par;
    }
    return p.join(' > ');
  };
  const label = (e) => { const l = e.labels && e.labels[0];
    return ((l && l.innerText) || e.placeholder || e.getAttribute('aria-label') || e.name || e.id || '').trim().slice(0, 60); };
  document.addEventListener('change', (ev) => {
    const e = ev.target; if (!e || !e.matches || !e.matches('input,textarea,select')) return;
    if (e.type === 'password' || /parol|password|пароль/i.test(e.name + e.id)) return rec({op: 'secret_skipped'});
    if (e.tagName === 'SELECT') return rec({op: 'select', selector: sel(e), value: e.value, label: label(e), text: (e.options[e.selectedIndex] || {}).text || ''});
    if (e.type === 'checkbox' || e.type === 'radio') return rec({op: 'check', selector: sel(e), value: e.checked, label: label(e)});
    rec({op: 'fill', selector: sel(e), value: e.value, label: label(e)});
  }, true);
  document.addEventListener('click', (ev) => {
    const e = ev.target.closest && ev.target.closest('button,a,[role=button],[role=option],[role=menuitem],li,td,input[type=submit],input[type=button],label');
    if (!e) return;
    if (e.id === 'jarvis-done') { ev.preventDefault(); ev.stopPropagation(); return rec({op: 'done'}); }
    rec({op: 'click', selector: sel(e), text: (e.innerText || e.value || '').trim().slice(0, 40)});
  }, true);
  const add = () => { if (document.getElementById('jarvis-done') || !document.body) return;
    const b = document.createElement('button'); b.id = 'jarvis-done'; b.type = 'button'; b.textContent = "✅ JARVIS: o'rgatishni tugatdim";
    b.style.cssText = 'position:fixed;right:14px;bottom:14px;z-index:2147483647;padding:10px 14px;background:#16a34a;color:#fff;border:0;border-radius:8px;font:14px sans-serif;box-shadow:0 4px 14px rgba(0,0,0,.25)';
    document.body.appendChild(b); };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', add) : add();
})()"""


class SiteTaskError(Exception):
    pass


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", (s or "").lower().replace("'", "")).strip("_")
    return s[:30] or "qiymat"


def clean_steps(raw: list[dict]) -> list[dict]:
    """Yozib olingan hodisalarni tozalash: ketma-ket bir xil maydon — oxirgisi; takror bosishlar; 'done' — tugash."""
    out: list[dict] = []
    for e in raw:
        op = e.get("op")
        if op in ("done", "secret_skipped") or not e.get("selector") and op != "goto":
            continue
        if op == "fill" and out and out[-1]["op"] == "fill" and out[-1]["selector"] == e["selector"]:
            out[-1]["value"] = e.get("value", "")
            continue
        if op == "click" and out and out[-1]["op"] == "click" and out[-1].get("selector") == e.get("selector"):
            continue
        if op == "goto" and out and out[-1].get("op") == "click":
            continue                                     # bosishdan keyingi navigatsiya — bosishning o'zi yetarli
        step = {k: e.get(k) for k in ("op", "selector", "value", "label", "text", "url") if e.get(k) not in (None, "")}
        step["param"] = None
        if op in ("fill", "select") and step.get("label"):
            step["suggest"] = _slug(step["label"])
        out.append(step)
    return out


class SiteTasks:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        self._rec: dict[int, dict] = {}

    # ---------------- ko'rish ----------------
    def get(self, tid: int) -> dict:
        r = self.core.db.one("SELECT t.*, i.name conn_name, i.status conn_status FROM site_tasks t JOIN integrations i ON i.id=t.conn_id WHERE t.id=?", (tid,))
        if not r:
            raise SiteTaskError("Amal topilmadi")
        r["steps"], r["params"] = json.loads(r["steps"]), json.loads(r["params"])
        r["recording"] = tid in self._rec
        return r

    def list(self, conn_id: int | None = None) -> list[dict]:
        return [self.get(r["id"]) for r in self.core.db.query(
            "SELECT id FROM site_tasks" + (" WHERE conn_id=?" if conn_id else "") + " ORDER BY id DESC", (conn_id,) if conn_id else ())]

    def ready(self) -> list[dict]:
        return [t for t in self.list() if t["status"] == "ready"]

    # ---------------- o'rgatish (yozib olish) ----------------
    def start_recording(self, conn_id: int, name: str, start_url: str = "", *, headless: bool = False, driver=None, timeout_s: int = 900) -> dict:
        c = self.core.integrations.get(conn_id)
        if c["adapter"] != "website":
            raise SiteTaskError("O'rgatish faqat veb-sayt ulanishlari uchun")
        name = (name or "").strip()
        if not name:
            raise SiteTaskError("Amal nomini yozing (masalan: kirim)")
        base = (c.get("config") or {}).get("base_url", "")
        url = (start_url or base).strip()
        conn = self.core.integrations.connector(c)
        if not conn._same_origin(url):
            raise SiteTaskError("Boshlang'ich sahifa shu sayt ichida bo'lishi kerak")
        tid = self.core.db.execute("INSERT INTO site_tasks(conn_id, name, start_url, status, financial) VALUES (?,?,?, 'recording', ?)",
                                   (conn_id, name[:60], url, 1 if FIN_RX.search(name) else 0)).lastrowid
        state = {"events": [], "done": False}
        self._rec[tid] = state

        def work():
            note = ""
            try:
                note = self._record(conn, url, state, headless, driver, timeout_s)
            except Exception as e:                              # noqa: BLE001 — xato holatga yoziladi
                note = f"Xato: {str(e).splitlines()[0][:200]}"
            steps = clean_steps(state["events"])
            self.core.db.execute("UPDATE site_tasks SET steps=?, status=?, note=?, updated_at=datetime('now') WHERE id=?",
                                 (json.dumps(steps, ensure_ascii=False), "recorded" if steps else "empty", note, tid))
            self._rec.pop(tid, None)
            self.core.audit.log("site_tasks", f"Amal o'rgatildi: {name} ({len(steps)} qadam)", target=f"conn#{conn_id}", risk="B")
        if driver is not None:
            work()                                             # test / sinxron rejim
        else:
            threading.Thread(target=work, daemon=True, name=f"teach-{tid}").start()
        return self.get(tid)

    def _record(self, conn, url, state, headless, driver, timeout_s) -> str:
        sync_playwright, PWError = conn._pw()
        with sync_playwright() as p:
            b, ctx = conn._launch(p, headless=headless)
            try:
                ctx.expose_function("jarvisRecord", lambda e: (state["events"].append(e if isinstance(e, dict) else {}),
                                                               state.__setitem__("done", True) if isinstance(e, dict) and e.get("op") == "done" else None))
                ctx.add_init_script(RECORD_JS)
                page = ctx.new_page()
                page.goto(conn.cfg.get("login_url") or url, wait_until="domcontentloaded", timeout=45000)
                st = conn._login(page)
                if st != "connected":
                    if headless:
                        raise SiteTaskError(f"Kirib bo'lmadi: {st}")
                    t0 = time.time()                            # ko'rinadigan oynada foydalanuvchi o'zi kiradi (CAPTCHA/SMS)
                    while page.query_selector("input[type=password]") and time.time() - t0 < 300:
                        page.wait_for_timeout(1000)
                conn._save_state(ctx)
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                state["events"].clear()
                page.on("framenavigated", lambda f: f == page.main_frame and state["events"].append({"op": "goto", "url": f.url}))
                if driver:
                    driver(page)
                t0 = time.time()
                while not state["done"] and time.time() - t0 < timeout_s and not page.is_closed():
                    page.wait_for_timeout(500)
                conn._save_state(ctx)
                return "" if state["done"] else "Oyna yopildi yoki vaqt tugadi — yozib olingan qadamlar saqlandi"
            finally:
                try:
                    ctx.close()
                    b.close()
                except PWError:
                    pass

    def finalize(self, tid: int, name: str, description: str, steps: list[dict], success_text: str = "") -> dict:
        """Foydalanuvchi qadamlarni ko'rib, o'zgaruvchi qiymatlarni (param) belgilaydi."""
        t = self.get(tid)
        if t["recording"]:
            raise SiteTaskError("Hali yozib olinmoqda")
        old = {json.dumps({k: s.get(k) for k in ("op", "selector")}) for s in t["steps"]}
        params, clean = [], []
        for s in steps:
            if json.dumps({k: s.get(k) for k in ("op", "selector")}) not in old:
                raise SiteTaskError("Qadamlar o'zgartirilgan — faqat parametr belgilash va o'chirish mumkin")
            s = {k: s.get(k) for k in ("op", "selector", "value", "label", "text", "url", "param")}
            if s.get("param"):
                s["param"] = _slug(s["param"])
                if s["op"] not in ("fill", "select"):
                    raise SiteTaskError("Faqat to'ldiriladigan maydon parametr bo'la oladi")
                if s["param"] not in [p["name"] for p in params]:
                    params.append({"name": s["param"], "label": s.get("label") or s["param"], "example": s.get("value", "")})
                s["value"] = None
            elif s.get("value") and contains_secret(str(s["value"])):
                raise SiteTaskError("Qadamda maxfiy qiymat bor — uni parametr qiling yoki o'chiring")
            clean.append({k: v for k, v in s.items() if v not in (None, "") or k == "param"})
        if not any(s["op"] == "click" for s in clean):
            raise SiteTaskError("Amalda hech bo'lmasa bitta tugma bosilishi kerak (masalan: Saqlash)")
        name = (name or t["name"]).strip()[:60]
        self.core.db.execute("UPDATE site_tasks SET name=?, description=?, steps=?, params=?, success_text=?, status='ready', financial=?, "
                             "verified=0, updated_at=datetime('now') WHERE id=?",
                             (name, (description or "")[:300], json.dumps(clean, ensure_ascii=False), json.dumps(params, ensure_ascii=False),
                              (success_text or "").strip()[:100] or None, 1 if FIN_RX.search(f"{name} {description}") else 0, tid))
        return self.get(tid)

    def delete(self, tid: int) -> dict:
        self.get(tid)
        self.core.db.execute("DELETE FROM site_tasks WHERE id=?", (tid,))
        return {"deleted": tid}

    # ---------------- bajarish ----------------
    @staticmethod
    def _hash(t: dict) -> str:
        return hashlib.sha256(json.dumps([t["start_url"], t["steps"]], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]

    def propose(self, tid: int, params: dict, requested_by: str = "user") -> dict:
        t = self.get(tid)
        if t["status"] != "ready":
            raise SiteTaskError("Amal hali tayyor emas (o'rgatishni yakunlang)")
        if t["conn_status"] != "connected":
            raise SiteTaskError(f"'{t['conn_name']}' ulanmagan (holat: {t['conn_status']})")
        if int(self.core.settings.autonomy_level) <= 0:
            raise SiteTaskError("Avtonomlik Level 0 — saytda amal bajarilmaydi")
        params = {k: str(v).strip() for k, v in (params or {}).items() if str(v).strip()}
        need = [p["name"] for p in t["params"]]
        missing = [p["label"] for p in t["params"] if p["name"] not in params]
        if missing:
            raise SiteTaskError("Qiymat kerak: " + ", ".join(missing))
        extra = set(params) - set(need)
        if extra:
            raise SiteTaskError(f"Noma'lum parametr(lar): {sorted(extra)}")
        if any(contains_secret(v) or len(v) > 500 for v in params.values()):
            raise SiteTaskError("Qiymatlarda maxfiy ma'lumot yoki juda uzun matn bor")
        level = "E" if t["financial"] else "D"
        desc = ", ".join(f"{next(p['label'] for p in t['params'] if p['name'] == k)}: {v}" for k, v in params.items())
        appr = self.core.approvals.request(action_type="site_task", target=f"conn#{t['conn_id']}", level=level, account=t["conn_name"],
                                           payload={"task_id": tid, "params": params, "steps_hash": self._hash(t)},
                                           summary=f"«{t['conn_name']}»da «{t['name']}»: {desc}"[:300], requested_by=requested_by,
                                           purpose="Foydalanuvchi buyrug'i — o'rgatilgan sayt amali")
        return {"approval": appr, "task": {"id": tid, "name": t["name"], "conn": t["conn_name"], "params": params}}

    def execute(self, approval_id: int) -> dict:
        c = self.core
        appr = c.approvals.get(approval_id)
        if appr["action_type"] != "site_task":
            raise SiteTaskError("Bu tasdiq o'rgatilgan amal emas")
        p = appr["payload"]
        c.approvals.authorize_execution(approval_id, p)
        if getattr(c, "automation_paused", False):
            raise SiteTaskError("Favqulodda to'xtatish yoqilgan")
        t = self.get(p["task_id"])
        if self._hash(t) != p["steps_hash"]:
            raise SiteTaskError("Amal tasdiqdan keyin o'zgargan — qayta tasdiqlang")
        conn = c.integrations.connector(c.integrations.get(t["conn_id"]))
        out_dir = Path(c.settings.allowed_write_dirs[0]) / "exports" / "site"
        out_dir.mkdir(parents=True, exist_ok=True)
        rid = c.db.execute("INSERT INTO site_task_runs(task_id, approval_id, params, status) VALUES (?,?,?, 'running')",
                           (t["id"], approval_id, redact(json.dumps(p["params"], ensure_ascii=False)))).lastrowid
        progress = {"step": -1, "clicked": False}
        from .integrations.base import ConnectorError
        from .integrations.website import CAPTCHA_JS

        def act(page):
            if page.url.split("#")[0] != t["start_url"].split("#")[0]:
                page.goto(t["start_url"], wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            for i, s in enumerate(t["steps"]):
                progress["step"] = i
                if page.evaluate(CAPTCHA_JS):
                    raise ConnectorError("CAPTCHA chiqdi — chetlab o'tilmaydi", "user_action_required")
                op = s["op"]
                if op == "goto":
                    if not conn._same_origin(s["url"]):
                        raise ConnectorError("Boshqa domenga o'tish — to'xtatildi", "permission_denied")
                    if page.url.split("#")[0] != s["url"].split("#")[0]:
                        page.goto(s["url"], wait_until="domcontentloaded", timeout=30000)
                    continue
                loc = page.locator(s["selector"]).first
                loc.wait_for(state="visible", timeout=15000)
                val = p["params"].get(s["param"]) if s.get("param") else s.get("value")
                if op == "fill":
                    loc.fill(str(val or ""))
                elif op == "select":
                    try:
                        loc.select_option(value=str(val))
                    except Exception:
                        loc.select_option(label=str(val))
                elif op == "check":
                    loc.set_checked(bool(s.get("value")))
                elif op == "click":
                    loc.click(timeout=15000)
                    progress["clicked"] = True
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except Exception:
                        pass
                page.wait_for_timeout(350)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            ok = (t["success_text"] or "").lower() in page.evaluate("() => document.body.innerText").lower() if t["success_text"] else None
            shot = out_dir / f"amal_{rid}.png"
            page.screenshot(path=str(shot))
            return {"success_seen": ok, "screenshot": str(shot), "page": page.url}
        try:
            res = conn._session(act)
            status = "ok" if res["success_seen"] in (True, None) else "unknown"
            err = None if status == "ok" else f"Muvaffaqiyat belgisi («{t['success_text']}») ko'rinmadi — tizimda tekshiring"
        except Exception as e:                                  # noqa: BLE001
            res = {"screenshot": None}
            status = "unknown" if progress["clicked"] else "error"
            err = (f"{progress['step'] + 1}-qadamda to'xtadi: {str(e).splitlines()[0][:200]}"
                   + (" — ba'zi tugmalar bosilgan: natijani tizimda tekshiring (qayta yuborilmaydi)" if progress["clicked"] else " — hech narsa yuborilmadi"))
        c.approvals.mark_result(approval_id, "executed" if status == "ok" else "unknown")
        c.db.execute("UPDATE site_task_runs SET status=?, step=?, error=?, screenshot=? WHERE id=?", (status, progress["step"], err, res.get("screenshot"), rid))
        c.db.execute("UPDATE site_tasks SET runs=runs+1, last_status=?" + (", verified=1" if status == "ok" else "") + " WHERE id=?", (status, t["id"]))
        c.audit.log("site_tasks", f"Amal: {t['conn_name']} → {t['name']}: {status}", target=f"conn#{t['conn_id']}", risk=appr["level"],
                    approval_status="approved", result=status)
        return {"status": status, "error": err, "screenshot": res.get("screenshot"), "task": t["name"], "site": t["conn_name"],
                "verified": status == "ok" and bool(t["success_text"]),
                "note": "Bajarildi." + ("" if t["success_text"] else " (Muvaffaqiyat matni belgilanmagan — skrinshotni ko'ring.)") if status == "ok" else ""}

    def runs(self, limit: int = 30) -> list[dict]:
        return self.core.db.query("SELECT r.*, t.name FROM site_task_runs r LEFT JOIN site_tasks t ON t.id=r.task_id ORDER BY r.id DESC LIMIT ?", (limit,))
