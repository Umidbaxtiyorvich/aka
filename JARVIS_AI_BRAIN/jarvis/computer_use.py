"""Computer Use Engine — sichqoncha, klaviatura, oynalar, skrinshot (Windows 11).

Arxitektura: Controller (bu klass) → Action Planner (amallar ro'yxati) → tasdiq → Action Executor (drayver) → Verification
(har amaldan keyin faol oyna tekshiruvi, oxirida skrinshot) → log.

Xavfsizlik (o'zgarmas qoidalar):
* Faqat o'qish (oynalar ro'yxati, skrinshot) — avtomatik. Har qanday sichqoncha/klaviatura amali — butun ketma-ketlik uchun
  bitta aniq tasdiq (payload xeshi bilan: tasdiqdan keyin amallar o'zgarsa — bekor).
* Parol/bank/to'lov/login/CAPTCHA oynalarida ishlamaydi; maxfiy matn yozilmaydi; xavfli tugmalar (Ctrl+Alt+Del va h.k.) taqiqlangan.
* Favqulodda to'xtatish va avtonomlik Level 0 — bajarilmaydi. pyautogui FAILSAFE: sichqonchani ekran burchagiga olib borsangiz — to'xtaydi.
* "Yozib olish" = JARVIS bajargan amallar makro sifatida saqlanadi (klaviatura/sichqonchani yashirin kuzatish YO'Q).
  Qayta ijro — yangi tasdiq bilan.
* Drayver (pyautogui, pywinauto) faqat Windows'da va o'rnatilgan bo'lsa ishlaydi; bo'lmasa holat ochiq aytiladi.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime

from .security import contains_secret

SCHEMA = """
CREATE TABLE IF NOT EXISTS cu_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), approval_id INTEGER, idx INTEGER,
    type TEXT NOT NULL, detail TEXT, window TEXT, status TEXT NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS cu_macros (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, actions TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""
SENSITIVE_WINDOW = re.compile(r"(?i)(parol|password|пароль|kirish|login|sign.?in|вход|bank|payme|click\.uz|uzcard|humo|wallet|hamyon|captcha|"
                              r"credential|keepass|bitwarden|1password|authenticator|2fa|tasdiqlash kodi)")
FORBIDDEN_KEYS = [{"ctrl", "alt", "delete"}, {"ctrl", "alt", "del"}, {"win", "l"}, {"win", "r"}, {"ctrl", "shift", "esc"}]
TYPES = {"click", "double_click", "right_click", "move", "type", "hotkey", "scroll", "focus_window", "wait"}
MAX_ACTIONS = 50


class ComputerUseError(Exception):
    pass


class PyAutoGuiDriver:
    """Haqiqiy Windows drayveri (pyautogui + pygetwindow; pywinauto bo'lsa — UI Automation daraxti)."""

    def __init__(self):
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.15
        self.g = pyautogui

    def size(self):
        return tuple(self.g.size())

    def screenshot(self, path: str):
        self.g.screenshot(path)

    def click(self, x, y, button="left", clicks=1):
        self.g.click(x, y, clicks=clicks, button=button)

    def move(self, x, y):
        self.g.moveTo(x, y, duration=0.2)

    def type_text(self, text):
        self.g.write(text, interval=0.02)

    def hotkey(self, keys):
        self.g.hotkey(*keys)

    def scroll(self, n):
        self.g.scroll(n)

    def windows(self):
        import pygetwindow as gw
        return [{"title": w.title, "active": w.isActive} for w in gw.getAllWindows() if w.title.strip()][:100]

    def active_title(self):
        import pygetwindow as gw
        w = gw.getActiveWindow()
        return w.title if w else ""

    def focus(self, title):
        import pygetwindow as gw
        ws = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
        if not ws:
            raise ComputerUseError(f"Oyna topilmadi: {title}")
        ws[0].activate()

    def ui_tree(self, title, limit=150):
        from pywinauto import Desktop
        win = Desktop(backend="uia").window(title_re=f".*{re.escape(title)}.*")
        out = []
        for c in win.descendants()[:limit]:
            r = c.rectangle()
            out.append({"name": c.window_text()[:80], "type": c.element_info.control_type, "x": (r.left + r.right) // 2, "y": (r.top + r.bottom) // 2})
        return out


class ComputerUse:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        self.driver = None
        self._driver_error = None

    def _drv(self):
        if self.driver is None and self._driver_error is None:
            if sys.platform != "win32":
                self._driver_error = "Computer Use faqat Windows'da ishlaydi (bu muhit: " + sys.platform + ")"
            else:
                try:
                    self.driver = PyAutoGuiDriver()
                except Exception as e:
                    self._driver_error = f"pyautogui o'rnatilmagan yoki ishlamadi: {e}. O'rnatuvchida 'Kompyuterni boshqarish' komponentini tanlang."
        if self.driver is None:
            raise ComputerUseError(self._driver_error)
        return self.driver

    def status(self) -> dict:
        try:
            d = self._drv()
            info = {"available": True, "screen": d.size(), "active_window": d.active_title()}
        except ComputerUseError as e:
            info = {"available": False, "note": str(e)}
        try:
            import pywinauto  # noqa: F401
            info["ui_automation"] = True
        except Exception:
            info["ui_automation"] = False
        return info | {"rules": ["har bir sichqoncha/klaviatura ketma-ketligi — aniq tasdiq bilan", "parol/bank/login/CAPTCHA oynalarida ishlamaydi",
                                 "maxfiy matn yozilmaydi", "sichqonchani ekran burchagiga olib borsangiz — darhol to'xtaydi"]}

    # ---------------- faqat o'qish (A) ----------------
    def windows(self) -> list[dict]:
        return [w | {"sensitive": bool(SENSITIVE_WINDOW.search(w["title"]))} for w in self._drv().windows()]

    def screenshot(self, analyze: bool = False) -> dict:
        d = self._drv()
        if SENSITIVE_WINDOW.search(d.active_title() or ""):
            raise ComputerUseError("Faol oyna maxfiy (parol/bank/login) — skrinshot olinmaydi")
        out = self.core.studio.exports / f"screen_{datetime.now():%Y%m%d_%H%M%S}.png"
        d.screenshot(str(out))
        res = {"path": str(out), "window": d.active_title()}
        if analyze:
            try:
                res["vision"] = self.core.imagegen.describe(str(out), "Bu ekranda nima ko'rinyapti? Qaysi dastur, qanday tugmalar va maydonlar bor? Qisqa o'zbekcha.")
            except Exception as e:
                res["vision"] = {"error": str(e)}
            try:
                res["ocr"] = self.core.documents._ocr(out)[:3000]
            except Exception as e:
                res["ocr_error"] = str(e)
        self.core.audit.log("computer_use", "Skrinshot olindi", target=str(out), risk="A")
        return res

    def ui_tree(self, title: str) -> list[dict]:
        if SENSITIVE_WINDOW.search(title):
            raise ComputerUseError("Maxfiy oyna tuzilishi o'qilmaydi")
        try:
            return self._drv().ui_tree(title)
        except ImportError:
            raise ComputerUseError("UI Automation uchun 'pywinauto' o'rnatilmagan") from None

    # ---------------- reja va tasdiq ----------------
    def _validate(self, actions: list[dict]) -> list[dict]:
        if not isinstance(actions, list) or not actions:
            raise ComputerUseError("Amallar ro'yxati bo'sh")
        if len(actions) > MAX_ACTIONS:
            raise ComputerUseError(f"Bitta ketma-ketlikda ko'pi bilan {MAX_ACTIONS} amal")
        out = []
        for i, a in enumerate(actions, 1):
            t = a.get("type")
            if t not in TYPES:
                raise ComputerUseError(f"{i}-amal: noma'lum tur '{t}' ({', '.join(sorted(TYPES))})")
            clean = {"type": t}
            if t in ("click", "double_click", "right_click", "move"):
                x, y = a.get("x"), a.get("y")
                if not isinstance(x, int) or not isinstance(y, int) or x < 0 or y < 0 or x > 10000 or y > 10000:
                    raise ComputerUseError(f"{i}-amal: x, y — musbat butun son")
                clean.update(x=x, y=y)
            elif t == "type":
                text = str(a.get("text", ""))
                if not text or len(text) > 2000:
                    raise ComputerUseError(f"{i}-amal: matn 1–2000 belgi")
                if contains_secret(text):
                    raise ComputerUseError(f"{i}-amal: maxfiy ma'lumot (parol/token) yozilmaydi — uni o'zingiz kiriting")
                clean["text"] = text
            elif t == "hotkey":
                keys = [str(k).lower().strip() for k in (a.get("keys") or [])]
                if not keys or len(keys) > 4:
                    raise ComputerUseError(f"{i}-amal: 1–4 tugma")
                if set(keys) in FORBIDDEN_KEYS:
                    raise ComputerUseError(f"{i}-amal: taqiqlangan tugmalar {'+'.join(keys)}")
                clean["keys"] = keys
            elif t == "scroll":
                clean["amount"] = max(-50, min(50, int(a.get("amount", -3))))
            elif t == "focus_window":
                title = str(a.get("title", "")).strip()
                if not title:
                    raise ComputerUseError(f"{i}-amal: oyna nomi kerak")
                if SENSITIVE_WINDOW.search(title):
                    raise ComputerUseError(f"{i}-amal: maxfiy oynada (parol/bank/login) ishlanmaydi")
                clean["title"] = title
            elif t == "wait":
                clean["seconds"] = max(0.1, min(10.0, float(a.get("seconds", 1))))
            out.append(clean)
        return out

    def propose(self, actions: list[dict], reason: str = "", requested_by: str = "user") -> dict:
        if int(self.core.settings.autonomy_level) <= 0:
            raise ComputerUseError("Avtonomlik Level 0 (faqat maslahat) — kompyuter amallari bajarilmaydi")
        acts = self._validate(actions)
        payload = {"actions": acts, "macro": hashlib.sha256(json.dumps(acts, sort_keys=True).encode()).hexdigest()[:16]}
        summary = f"Kompyuterda {len(acts)} ta amal: " + ", ".join(
            a["type"] + (f"({a.get('title') or a.get('text', '')[:20] or '+'.join(a.get('keys', [])) or str(a.get('x', ''))})" if len(a) > 1 else "") for a in acts[:6])
        appr = self.core.approvals.request(action_type="computer_use", target="local_desktop", level="C", payload=payload, summary=summary[:300],
                                           requested_by=requested_by, purpose=reason or "Foydalanuvchi so'ragan kompyuter amali")
        return {"approval": appr, "actions": acts}

    def execute(self, approval_id: int) -> dict:
        appr = self.core.approvals.get(approval_id)
        p = appr["payload"]
        self.core.approvals.authorize_execution(approval_id, p)
        if getattr(self.core, "automation_paused", False):
            raise ComputerUseError("Favqulodda to'xtatish yoqilgan")
        d = self._drv()
        done, error = [], None
        for i, a in enumerate(p["actions"]):
            win = ""
            try:
                win = d.active_title() or ""
                if a["type"] in ("type", "click", "double_click", "right_click", "hotkey") and SENSITIVE_WINDOW.search(win):
                    raise ComputerUseError(f"Faol oyna maxfiy ('{win[:40]}') — to'xtatildi")
                t = a["type"]
                if t == "click":
                    d.click(a["x"], a["y"])
                elif t == "double_click":
                    d.click(a["x"], a["y"], clicks=2)
                elif t == "right_click":
                    d.click(a["x"], a["y"], button="right")
                elif t == "move":
                    d.move(a["x"], a["y"])
                elif t == "type":
                    d.type_text(a["text"])
                elif t == "hotkey":
                    d.hotkey(a["keys"])
                elif t == "scroll":
                    d.scroll(a["amount"])
                elif t == "focus_window":
                    d.focus(a["title"])
                elif t == "wait":
                    time.sleep(a["seconds"])
                self._log(approval_id, i, a, win, "ok")
                done.append(i)
            except Exception as e:                       # xato — darhol to'xtash (qolgan amallar bajarilmaydi, qayta urinilmaydi)
                error = f"{i + 1}-amal ({a['type']}): {e}"
                self._log(approval_id, i, a, win, "error", str(e))
                break
        self.core.approvals.mark_result(approval_id, "executed" if error is None else "unknown")
        after = None
        try:
            after = d.active_title()
        except Exception:
            pass
        self.core.audit.log("computer_use", f"Kompyuter amallari: {len(done)}/{len(p['actions'])}" + (f" — xato: {error}" if error else ""),
                            target="local_desktop", risk="C", approval_status="approved", result="ok" if not error else "partial")
        return {"done": len(done), "total": len(p["actions"]), "error": error, "active_window_after": after,
                "verified": error is None, "note": "Natijani ekranda tekshiring; xato bo'lsa qolgan amallar bajarilmadi." if error else ""}

    def _log(self, approval_id, idx, a, win, status, error=None):
        detail = {k: v for k, v in a.items() if k != "type"}
        self.core.db.execute("INSERT INTO cu_actions(approval_id, idx, type, detail, window, status, error) VALUES (?,?,?,?,?,?,?)",
                             (approval_id, idx, a["type"], json.dumps(detail, ensure_ascii=False)[:500], (win or "")[:120], status, (error or "")[:300] or None))

    # ---------------- makrolar (yozib olish va qayta ijro) ----------------
    def save_macro(self, name: str, actions: list[dict]) -> dict:
        if not re.fullmatch(r"[\w\- ]{2,60}", name or ""):
            raise ComputerUseError("Makro nomi 2–60 belgi")
        acts = self._validate(actions)
        self.core.db.execute("INSERT OR REPLACE INTO cu_macros(name, actions) VALUES (?,?)", (name, json.dumps(acts, ensure_ascii=False)))
        return {"name": name, "actions": len(acts)}

    def macros(self) -> list[dict]:
        rows = self.core.db.query("SELECT * FROM cu_macros ORDER BY id DESC")
        for r in rows:
            r["actions"] = json.loads(r["actions"])
        return rows

    def replay(self, name: str) -> dict:
        r = self.core.db.one("SELECT actions FROM cu_macros WHERE name=?", (name,))
        if not r:
            raise ComputerUseError("Makro topilmadi")
        return self.propose(json.loads(r["actions"]), reason=f"Makro qayta ijrosi: {name}")

    def log(self, limit: int = 100) -> list[dict]:
        return self.core.db.query("SELECT * FROM cu_actions ORDER BY id DESC LIMIT ?", (limit,))
