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
