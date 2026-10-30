"""Browser Agent (Playwright). 1-bosqich: FAQAT O'QISH.

* Faqat `browser_allowed_domains` ro'yxatidagi saytlar ochiladi.
* Forma to'ldirish, tugma bosish, ma'lumot yuborish — yo'q (kelajakda D-darajali tasdiq bilan).
* CAPTCHA, 2FA va boshqa himoyalar chetlab o'tilmaydi. Login talab qilinsa — to'xtaydi va xabar beradi.
* Sahifa matni ishonchsiz ma'lumot sifatida qaytariladi.
O'rnatish (ixtiyoriy, ~150 MB): pip install playwright && python -m playwright install chromium
"""
from __future__ import annotations

import os
import urllib.parse
from datetime import datetime
from pathlib import Path

from .security import injection_score


class BrowserError(Exception):
    pass


def domain_allowed(url: str, allowed: list[str]) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return any(host == d.lower() or host.endswith("." + d.lower()) for d in allowed if d)


class BrowserAgent:
    def __init__(self, core):
        self.core = core

    def status(self) -> dict:
        try:
            import playwright  # noqa: F401
            installed = True
        except ImportError:
            installed = False
        return {"playwright": installed, "allowed_domains": self.core.settings.browser_allowed_domains,
                "mode": "faqat o'qish"}

    def _launch(self, p):
        exe = os.environ.get("JARVIS_CHROMIUM_PATH")
        return p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()

    def inspect(self, url: str, screenshot: bool = True) -> dict:
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            raise BrowserError("Faqat http/https")
        if not domain_allowed(url, self.core.settings.browser_allowed_domains):
            raise BrowserError("Bu domen ruxsat berilganlar ro'yxatida yo'q (Sozlamalar → Brauzer domenlari)")
        try:
            from playwright.sync_api import Error as PWError
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise BrowserError("Playwright o'rnatilmagan: pip install playwright && python -m playwright install chromium") from e
        try:
            with sync_playwright() as p:
                b = self._launch(p)
                page = b.new_page()
                resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                data = page.evaluate("""() => ({
                    title: document.title,
                    text: (document.body ? document.body.innerText : '').slice(0, 15000),
                    links: [...document.querySelectorAll('a[href]')].slice(0, 150).map(a => ({text: a.innerText.trim().slice(0, 80), href: a.href})),
                    forms: [...document.forms].map(f => ({action: f.action, method: f.method,
                        fields: [...f.elements].filter(e => e.name).map(e => ({name: e.name, type: e.type}))})),
                    tables: [...document.querySelectorAll('table')].slice(0, 20).map(t =>
                        [...t.querySelectorAll('th')].map(th => th.innerText.trim()).slice(0, 30)),
                    has_password: !!document.querySelector('input[type=password]'),
                    has_captcha: !!document.querySelector('[class*=captcha], iframe[src*=captcha], iframe[src*=recaptcha]')
                })""")
                shot = None
                if screenshot:
                    d = Path(self.core.settings.allowed_write_dirs[0]) / "screenshots"
                    d.mkdir(parents=True, exist_ok=True)
                    shot = str(d / f"sahifa_{datetime.now():%Y%m%d_%H%M%S_%f}.png")
                    page.screenshot(path=shot, full_page=False)
                status = resp.status if resp else None
                b.close()
        except PWError as e:
            raise BrowserError(f"Brauzer xatosi: {str(e).splitlines()[0]}") from None
        notes = []
        if data["has_password"]:
            notes.append("Sahifada login formasi bor. JARVIS parol kiritmaydi — kerak bo'lsa o'zingiz kirasiz.")
        if data["has_captcha"]:
            notes.append("CAPTCHA aniqlandi — chetlab o'tilmaydi.")
        flags = injection_score(data["text"])
        self.core.audit.log("browser_agent", f"Sahifa o'qildi: {url}", target=urllib.parse.urlparse(url).hostname,
                            risk="A", result=f"HTTP {status}")
        return {"url": url, "status": status, "title": data["title"], "text": data["text"], "links": data["links"],
                "forms": data["forms"], "table_headers": data["tables"], "screenshot": shot, "notes": notes,
                "injection_flags": flags, "trust": "untrusted"}

    def site_map(self, url: str) -> dict:
        """POS kabi saytning tuzilishini hujjatlashtirish: bo'limlar, formalar, jadvallar."""
        info = self.inspect(url)
        host = urllib.parse.urlparse(url).hostname
        internal = [lnk for lnk in info["links"] if urllib.parse.urlparse(lnk["href"]).hostname == host and lnk["text"]]
        return {"url": url, "title": info["title"], "sections": internal[:60],
                "forms": [{"action": f["action"], "method": f["method"], "fields": [x["name"] for x in f["fields"]]}
                          for f in info["forms"]],
                "tables": info["table_headers"], "notes": info["notes"], "screenshot": info["screenshot"]}


# ---------------- Foydalanuvchi sessiyasi (POS kabi login talab qiladigan saytlar) ----------------
TABLES_JS = """(maxRows) => [...document.querySelectorAll('table')].map(t => {
    const rows = [...t.querySelectorAll('tr')].slice(0, maxRows).map(r => [...r.querySelectorAll('th,td')].map(c => c.innerText.trim()));
    return rows.filter(r => r.length && r.some(x => x));
}).filter(t => t.length > 1)"""


class SessionBrowser:
    """Siz o'zingiz kirgan brauzer sessiyasi (alohida profil papkasida).

    * `open_login(url)` — ko'rinadigan brauzer oynasi ochiladi; loginni SIZ kiritasiz (JARVIS parolni ko'rmaydi
      va saqlamaydi; CAPTCHA/2FA'ni ham siz o'tasiz). Oynani yopganingizda sessiya profilda qoladi.
    * `extract_tables(url)` — shu sessiya bilan sahifani faqat O'QIYDI, jadvallarni CSV qilib
      workspace/imports/ ga saqlaydi (keyin Business Intelligence'ga import qilasiz). Hech narsa bosilmaydi va yuborilmaydi.
    * Profil (cookie'lar) `JARVIS_HOME/browser_profile` da — Git'ga ham, zaxira nusxaga ham kirmaydi.
      Sessiyani o'chirish: `forget()`.
    """

    def __init__(self, core):
        self.core = core
        self._login_thread = None

    @property
    def profile(self):
        from .config import jarvis_home
        p = jarvis_home() / "browser_profile"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _check(self, url: str):
        if urllib.parse.urlparse(url).scheme != "https" and urllib.parse.urlparse(url).hostname not in ("127.0.0.1", "localhost"):
            raise BrowserError("Sessiya bilan faqat https:// saytlar ochiladi")
        if not domain_allowed(url, self.core.settings.browser_allowed_domains):
            raise BrowserError("Bu domen ruxsat berilganlar ro'yxatida yo'q (Sozlamalar → Brauzer domenlari)")
        if self._login_thread and self._login_thread.is_alive():
            raise BrowserError("Login oynasi hali ochiq — avval uni yoping")

    def _pw(self):
        try:
            from playwright.sync_api import Error as PWError
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise BrowserError("Playwright o'rnatilmagan: pip install playwright && python -m playwright install chromium") from e
        return sync_playwright, PWError

    def _context(self, p, headless: bool):
        exe = os.environ.get("JARVIS_CHROMIUM_PATH")
        kw = {"headless": headless, "viewport": {"width": 1366, "height": 900}}
        if exe:
            kw["executable_path"] = exe
        return p.chromium.launch_persistent_context(str(self.profile), **kw)

    def status(self) -> dict:
        has = any(self.profile.iterdir())
        return {"profile_exists": has, "login_window_open": bool(self._login_thread and self._login_thread.is_alive()),
                "profile_dir": str(self.profile)}

    def open_login(self, url: str) -> dict:
        self._check(url)
        sync_playwright, PWError = self._pw()
        import threading

        def run():
            try:
                with sync_playwright() as p:
                    ctx = self._context(p, headless=False)
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    page.goto(url, timeout=60000)
                    closed = threading.Event()
                    ctx.on("close", lambda *_: closed.set())
                    page.on("close", lambda *_: closed.set())
                    closed.wait(timeout=1800)       # 30 daqiqadan keyin avtomatik yopiladi
                    try:
                        ctx.close()
                    except PWError:
                        pass
            except Exception as e:
                self.core.audit.error("browser_agent", f"Login oynasi xatosi: {e}")
        self._login_thread = threading.Thread(target=run, daemon=True)
        self._login_thread.start()
        self.core.audit.log("browser_agent", f"Login oynasi ochildi: {urllib.parse.urlparse(url).hostname}", target=url,
                            risk="A", approval_status="user_action")
        return {"status": "opened", "note": "Brauzer oynasida o'zingiz kiring, so'ng oynani yoping. JARVIS parolni ko'rmaydi."}

    def extract_tables(self, url: str, max_rows: int = 5000, wait_ms: int = 2500) -> dict:
        self._check(url)
        sync_playwright, PWError = self._pw()
        import csv
        from datetime import datetime
        from pathlib import Path
        try:
            with sync_playwright() as p:
                ctx = self._context(p, headless=True)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except PWError:
                    pass
                page.wait_for_timeout(wait_ms)
                final_url, title = page.url, page.title()
                needs_login = page.evaluate("() => !!document.querySelector('input[type=password]')")
                tables = page.evaluate(TABLES_JS, max_rows)
                ctx.close()
        except PWError as e:
            raise BrowserError(f"Brauzer xatosi: {str(e).splitlines()[0]}") from None
        if needs_login and not tables:
            return {"status": "login_required", "url": final_url,
                    "note": "Sessiya yo'q yoki muddati tugagan. «POS'ga kirish» tugmasi bilan o'zingiz kiring."}
        out_dir = Path(self.core.settings.allowed_write_dirs[0]) / "imports"
        out_dir.mkdir(parents=True, exist_ok=True)
        host = (urllib.parse.urlparse(url).hostname or "sayt").split(".")[0]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        files = []
        for i, t in enumerate(tables, 1):
            f = out_dir / f"{host}_{stamp}_{i}.csv"
            with open(f, "w", newline="", encoding="utf-8-sig") as fh:
                csv.writer(fh).writerows(t)
            files.append({"path": str(f), "rows": len(t) - 1, "columns": t[0]})
        flags = injection_score(" ".join(" ".join(r) for t in tables for r in t[:50]))
        self.core.audit.log("browser_agent", f"Jadvallar o'qildi: {title[:60]}", target=urllib.parse.urlparse(url).hostname, risk="A",
                            result=f"{len(files)} jadval")
        return {"status": "ok", "title": title, "url": final_url, "tables": files, "injection_flags": flags,
                "note": ("Jadval topilmadi — hisobot sahifasida sanani tanlab, jadval ko'ringanidan keyin qayta urinib ko'ring "
                         "yoki POS'ning o'z 'Excel'ga eksport' tugmasidan foydalaning.") if not files else
                        "CSV fayllar tayyor. Business Intelligence → Import orqali yuklang (asl POS ma'lumoti o'zgarmaydi)."}

    def forget(self) -> dict:
        import shutil
        if self._login_thread and self._login_thread.is_alive():
            raise BrowserError("Login oynasi ochiq — avval yoping")
        shutil.rmtree(self.profile, ignore_errors=True)
        self.core.audit.log("browser_agent", "Brauzer sessiyasi (cookie'lar) o'chirildi", target="browser_profile", risk="C",
                            approval_status="user_action")
        return {"status": "forgotten"}
