"""Website Connector — admin panel, POS web paneli, CRM, ERP va boshqa veb-ilovalar (Playwright).

* Login va parol Vault'dan; ular faqat brauzer formasiga kiritiladi (log, prompt, GitHub'ga emas).
* Sessiya (cookie / storage state) Vault'da Fernet bilan shifrlangan holda saqlanadi.
* CAPTCHA yoki ikki bosqichli tasdiq (MFA) chiqsa — CHETLAB O'TILMAYDI: holat `user_action_required`,
  siz `interactive_login` bilan ko'rinadigan oynada o'zingiz o'tasiz, keyin sessiya saqlanadi.
* Faqat shu ulanish domeni ichida ishlaydi, sahifalarni sekin (1 so'rov/soniya) va cheklangan sonda o'qiydi.
* Hech narsa bosilmaydi va yuborilmaydi (login formasidan tashqari) — faqat o'qish.
"""
from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import urljoin, urlparse

from ..browser import TABLES_JS
from .base import BaseConnector, ConnectorError, check_url, field

CAPTCHA_JS = """() => !!(document.querySelector('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="turnstile"],.g-recaptcha,.h-captcha,[data-sitekey]')
  || /captcha/i.test(document.body ? document.body.innerText.slice(0, 5000) : ''))"""
MFA_JS = """() => !!(document.querySelector('input[autocomplete="one-time-code"],input[name*="otp" i],input[name*="2fa" i],input[name*="mfa" i],input[id*="otp" i]')
  || /(tasdiqlash kodi|sms kod|код подтверждения|одноразов|verification code|two-factor|2fa)/i.test(document.body ? document.body.innerText.slice(0, 5000) : ''))"""
PAGE_JS = """() => ({title: document.title,
  links: [...document.querySelectorAll('a[href]')].map(a => [a.href, (a.innerText||'').trim().slice(0,60)]).slice(0, 400),
  nav: [...document.querySelectorAll('nav a, aside a, [role=navigation] a, .menu a, .sidebar a')].map(a => (a.innerText||'').trim()).filter(Boolean).slice(0, 80),
  forms: [...document.querySelectorAll('form')].map(f => [...f.querySelectorAll('input,select,textarea')].map(i => i.name || i.id || i.type)).slice(0, 20),
  hasPassword: !!document.querySelector('input[type=password]')})"""


class WebsiteConnector(BaseConnector):
    kind, title, protocols = "website", "Veb-sayt / web panel", ["HTTPS", "Browser automation (Playwright)", "Form login"]
    FIELDS = [field("base_url", "Sayt manzili", "url", required=True, help_="https://app.misol.uz"),
              field("login_url", "Login sahifasi (ixtiyoriy)"), field("username", "Login", secret=True),
              field("password", "Parol", "password", secret=True),
              field("pages", "O'qiladigan sahifalar (har qatorda bitta URL, ixtiyoriy)", "textarea"),
              field("username_selector", "Login maydoni selektori (ixtiyoriy)"), field("password_selector", "Parol maydoni selektori (ixtiyoriy)"),
              field("max_pages", "Aniqlashda ko'pi bilan sahifalar", "number", default=20),
              field("login_fields", "Kirish maydonlari (sayt tekshiruvidan avtomatik)", "json")]
    delay = 1.0                  # sahifalar orasidagi pauza (saytga yuk bermaslik uchun); testlarda 0

    def base(self):
        return check_url(self.cfg.get("base_url", ""), "Sayt manzili")

    def _same_origin(self, url: str) -> bool:
        return urlparse(url).netloc == urlparse(self.base()).netloc

    def _pw(self):
        try:
            from playwright.sync_api import Error as PWError
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ConnectorError("Playwright o'rnatilmagan (o'rnatuvchida 'brauzer agenti' ni tanlang)", "not_supported") from None
        return sync_playwright, PWError

    def _launch(self, p, headless=True):
        kw = {"headless": headless}
        exe = os.environ.get("JARVIS_CHROMIUM_PATH")
        if exe:
            kw["executable_path"] = exe
        b = p.chromium.launch(**kw)
        state = self.core.integrations.vault.get_blob(self.cid, "session") if self.cid else None
        ctx = b.new_context(storage_state=json.loads(state) if state else None, viewport={"width": 1366, "height": 900})
        return b, ctx

    def _save_state(self, ctx):
        if self.cid:
            self.core.integrations.vault.put_blob(self.cid, "session", json.dumps(ctx.storage_state()).encode())

    def _login(self, page) -> str:
        """Login formasi bo'lsa — kiradi. Qaytaradi: connected | auth_failed | user_action_required."""
        if page.evaluate(CAPTCHA_JS):
            return "user_action_required:CAPTCHA"
        if not page.query_selector("input[type=password]"):
            return "connected"
        lf = self.cfg.get("login_fields") or []
        if lf:                                        # sayt tekshiruvi aniqlagan maydonlar (login, email, telefon, tashkilot ID ...)
            if any(f.get("kind") == "otp" for f in lf):
                return "user_action_required:MFA"
            for f in lf:
                if not f.get("store", True) or not f.get("selector"):
                    continue
                val = self.secret(f"f_{f['key']}")
                if not val:
                    raise ConnectorError(f"'{f.get('label', f['key'])}' kiritilmagan", "auth_failed")
                if not page.query_selector(f["selector"]):
                    raise ConnectorError(f"Saytda '{f.get('label')}' maydoni topilmadi (sayt o'zgargan bo'lishi mumkin) — 'Saytni qayta tekshirish'", "auth_failed")
                page.fill(f["selector"], val)
            psel = next((f["selector"] for f in lf if f.get("kind") == "password" and f.get("selector")), "input[type=password]")
            btn = page.query_selector("button[type=submit], input[type=submit], form button")
            (btn.click() if btn else page.press(psel, "Enter"))
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(800)
            if page.evaluate(CAPTCHA_JS):
                return "user_action_required:CAPTCHA"
            if page.evaluate(MFA_JS):
                return "user_action_required:MFA"
            return "auth_failed" if page.query_selector("input[type=password]") else "connected"
        user, pwd = self.secret("username"), self.secret("password")
        if not (user and pwd):
            raise ConnectorError("Login yoki parol kiritilmagan", "auth_failed")
        psel = self.cfg.get("password_selector") or "input[type=password]"
        usel = self.cfg.get("username_selector") or ("input[type=email], input[name*=login i], input[name*=user i], input[name*=phone i], "
                                                      "input[type=tel], input[type=text]")
        u = page.query_selector(usel)
        if u:
            u.fill(user)
        page.fill(psel, pwd)
        btn = page.query_selector("button[type=submit], input[type=submit], form button")
        (btn.click() if btn else page.press(psel, "Enter"))
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(800)
        if page.evaluate(CAPTCHA_JS):
            return "user_action_required:CAPTCHA"
        if page.evaluate(MFA_JS):
            return "user_action_required:MFA"
        if page.query_selector("input[type=password]"):
            return "auth_failed"
        return "connected"

    def _session(self, fn):
        sync_playwright, PWError = self._pw()
        try:
            with sync_playwright() as p:
                b, ctx = self._launch(p)
                try:
                    page = ctx.new_page()
                    page.goto(self.cfg.get("login_url") or self.base(), wait_until="domcontentloaded", timeout=45000)
                    st = self._login(page)
                    if st.startswith("user_action_required"):
                        raise ConnectorError(f"{st.split(':')[1]} chiqdi — chetlab o'tilmaydi. 'Qo'lda kirish' tugmasi bilan o'zingiz o'ting.",
                                             "user_action_required")
                    if st == "auth_failed":
                        raise ConnectorError("Login yoki parol noto'g'ri (sayt login sahifasida qoldi)", "auth_failed")
                    self._save_state(ctx)
                    return fn(page)
                finally:
                    ctx.close()
                    b.close()
        except PWError as e:
            raise ConnectorError(f"Brauzer xatosi: {str(e).splitlines()[0][:200]}", "error") from None

    def authenticate(self):
        return self._session(lambda page: {"status": "connected", "note": f"Kirildi: {page.title()[:80]}"})

    health_check = authenticate

    def interactive_login(self, timeout_s: int = 600) -> dict:
        """Ko'rinadigan oyna: CAPTCHA/MFA'ni siz o'tasiz. Oyna yopilgach sessiya shifrlangan holda saqlanadi."""
        sync_playwright, PWError = self._pw()
        with sync_playwright() as p:
            b, ctx = self._launch(p, headless=False)
            page = ctx.new_page()
            page.goto(self.cfg.get("login_url") or self.base(), timeout=60000)
            t0 = time.time()
            while time.time() - t0 < timeout_s and not page.is_closed():
                page.wait_for_timeout(1000)
                try:
                    if not page.query_selector("input[type=password]") and not page.evaluate(CAPTCHA_JS) and not page.evaluate(MFA_JS):
                        page.wait_for_timeout(1500)
                        break
                except PWError:
                    break
            self._save_state(ctx)
            ctx.close()
            b.close()
        return {"status": "connected", "note": "Sessiya shifrlangan holda saqlandi"}

    def discover(self):
        maxp = max(1, min(int(self.cfg.get("max_pages") or 20), 60))

        def crawl(page):
            seen, queue, pages, modules = set(), [page.url], [], []
            explicit = [u.strip() for u in (self.cfg.get("pages") or "").splitlines() if u.strip()]
            queue = explicit + queue
            while queue and len(pages) < maxp:
                url = queue.pop(0).split("#")[0]
                if url in seen or not self._same_origin(url) or re.search(r"(?i)logout|signout|chiqish|выход|delete|remove", url):
                    continue
                seen.add(url)
                if url != page.url:
                    time.sleep(self.delay)
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                info = page.evaluate(PAGE_JS)
                tables = page.evaluate(TABLES_JS, 3)
                modules += info["nav"]
                pages.append({"url": page.url, "title": info["title"], "tables": [{"columns": t[0], "sample_rows": len(t) - 1} for t in tables],
                              "forms": info["forms"]})
                for href, _ in info["links"]:
                    if self._same_origin(href) and href.split("#")[0] not in seen:
                        queue.append(href)
            return pages, modules
        pages, modules = self._session(crawl)
        ents = [{"name": f"{p['title'] or p['url']} #{i + 1}" if len(p["tables"]) > 1 else (p["title"] or p["url"]), "source": p["url"],
                 "table_index": i, "fields": t["columns"], "readable": True} for p in pages for i, t in enumerate(p["tables"])]
        return {"modules": sorted(set(m for m in modules if len(m) < 40))[:60], "entities": ents, "pages": pages,
                "note": f"{len(pages)} sahifa o'rganildi, {len(ents)} jadval topildi (faqat o'qildi)"}

    def fetch_data(self, entity, *, since=None, cursor=None, limit=5000):
        ent = next((e for e in (self.conn.get("entities") or []) if e["name"] == entity), None)
        url = ent["source"] if ent else entity
        if not url.startswith("http"):
            url = urljoin(self.base() + "/", url)
        if not self._same_origin(url):
            raise ConnectorError("Boshqa domen o'qilmaydi", "permission_denied")
        idx = int((ent or {}).get("table_index", 0))

        def read(page):
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            if page.query_selector("input[type=password]"):
                raise ConnectorError("Sessiya tugagan — qayta kirish kerak", "auth_expired")
            return page.evaluate(TABLES_JS, limit)
        tables = self._session(read)
        if not tables or idx >= len(tables):
            return {"records": [], "next": None}
        head, *rows = tables[idx]
        return {"records": [dict(zip(head, r)) for r in rows], "next": None}
