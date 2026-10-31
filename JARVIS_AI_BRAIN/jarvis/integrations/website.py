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
  hasPassword: !!document.querySelector('input[type=password]'),
  buttons: [...document.querySelectorAll('button, [role=button], input[type=submit]')].map(b => (b.innerText || b.value || b.getAttribute('aria-label') || '').trim().slice(0, 50)).filter(Boolean).slice(0, 60),
  prompts: [...document.querySelectorAll('textarea, [contenteditable=true], input[type=text], input:not([type])')].filter(e => e.offsetParent !== null && !(e.form && e.form.querySelector('input[type=password]')))
    .filter(e => e.tagName !== 'INPUT' || /prompt|describe|ask|message|tasvir|so.rov|imagine|idea|text|query|translat|matn/i.test((e.placeholder||'') + (e.name||'') + (e.getAttribute('aria-label')||'')))
    .map(e => ({hint: (e.placeholder || e.getAttribute('aria-label') || e.name || '').slice(0, 80),
                selector: e.id ? '#' + CSS.escape(e.id) : (e.name ? e.tagName.toLowerCase() + '[name="' + e.name + '"]' : null)})).slice(0, 5)})"""
# Topshiriq bajarish (Site Skills): so'rov maydoni va tugmani topish, yangi natijani (rasm/matn) kutish
FIND_JS = """(kind) => {
  const vis = e => e && e.offsetParent !== null && !e.disabled;
  if (kind === 'prompt') {
    const c = [...document.querySelectorAll('textarea, [contenteditable=true], input[type=text], input:not([type])')].filter(vis)
      .filter(e => !/search|qidir|поиск|email|login|user/i.test((e.placeholder||'') + (e.name||'') + (e.type||'')) || e.tagName === 'TEXTAREA');
    const e = c.find(x => x.tagName === 'TEXTAREA') || c.find(x => x.isContentEditable) || c[0];
    if (!e) return null;
    e.setAttribute('data-jarvis', 'prompt'); return '[data-jarvis="prompt"]';
  }
  const rx = /generat|create|yarat|imagine|send|yubor|submit|run|translat|tarjima|сгенер|созда|отправ|перев|go\b|start/i;
  const b = [...document.querySelectorAll('button, [role=button], input[type=submit]')].filter(vis)
    .find(x => rx.test((x.innerText || x.value || '') + ' ' + (x.getAttribute('aria-label') || '') + ' ' + (x.title || '')));
  if (!b) return null;
  b.setAttribute('data-jarvis', 'submit'); return '[data-jarvis="submit"]';
}"""
IMGS_JS = """() => [...document.images].filter(i => i.complete && i.naturalWidth >= 200 && i.naturalHeight >= 200 && i.offsetParent !== null)
  .map(i => i.currentSrc || i.src).concat([...document.querySelectorAll('video[src], video source[src], audio[src], audio source[src], a[download][href]')]
  .map(v => v.src || v.href)).filter(Boolean)"""
PAYWALL_JS = """() => /(out of credits|not enough credits|insufficient credits|upgrade to (pro|premium|continue)|buy credits|subscribe to continue|kredit (tugadi|yetarli emas)|пополните баланс|недостаточно кредитов)/i
  .test(document.body ? document.body.innerText.slice(-6000) : '')"""
NAV_JS = """() => [...document.querySelectorAll('nav a, nav button, aside a, aside button, [role=navigation] a, [role=menuitem], .menu a, .sidebar a, .sidebar button, '
  + '[class*=sidebar] a, [class*=menu] a, [class*=nav] a, [class*=sidebar] li, [class*=menu] li')]
  .filter(e => e.offsetParent !== null).map(e => (e.innerText || '').trim().split('\\n')[0]).filter(t => t && t.length < 40)
  .filter((t, i, a) => a.indexOf(t) === i).slice(0, 40)"""
SKIP_NAV = re.compile(r"(?i)log ?out|sign ?out|chiqish|выход|выйти|delete|o'?chir|удал|remove|tozala|очист|sotish|sell|касса|kassa|оплат|to'?lov|pay|"
                      r"yangi|new|create|добав|создать|qo'?shish|add|import|export|eksport|sozlama|settings|настройк|profil|profile")


def _json_rows(obj, depth: int = 0):
    """JSON ichidan eng katta "obyektlar ro'yxati"ni topish (API javobi: {data: [...]}, {items: [...]}, [...])."""
    best = obj if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj[:20]) else None
    if depth < 5:
        kids = obj.values() if isinstance(obj, dict) else (obj[:3] if isinstance(obj, list) and best is None else [])
        for v in kids:
            r = _json_rows(v, depth + 1)
            if r and (best is None or len(r) > len(best)):
                best = r
    return best


TRACKERS = re.compile(r"(?i)google|gstatic|doubleclick|yandex|mc\.|metrika|facebook|fbcdn|sentry|hotjar|clarity|intercom|crisp|jivo|tawk|"
                      r"segment|mixpanel|amplitude|onesignal|firebase|cloudflareinsights|newrelic|bugsnag|gravatar|cdn")
GRID_JS = """(limit) => { const rows = [...document.querySelectorAll('[role=row]')].filter(r => r.offsetParent !== null);
  if (rows.length < 2) return [];
  const cells = r => [...r.querySelectorAll('[role=columnheader],[role=cell],[role=gridcell]')].map(c => (c.innerText || '').trim());
  const head = cells(rows[0]); if (head.length < 2) return [];
  return [[head, ...rows.slice(1, limit + 1).map(cells).filter(c => c.length === head.length)]]; }"""


def _shape(obj) -> str:
    if isinstance(obj, dict):
        return "{" + ", ".join(list(obj)[:6]) + ("…" if len(obj) > 6 else "") + "}"
    if isinstance(obj, list):
        return f"[{len(obj)} ta]"
    return type(obj).__name__


def _flat(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, dict):
            out.update({f"{k}.{k2}": v2 for k2, v2 in v.items() if not isinstance(v2, (dict, list))})
        elif not isinstance(v, list):
            out[k] = v
    return out


def _site(host: str) -> str:
    parts = (host or "").lower().split(".")
    return ".".join(parts[-3:] if len(parts) > 2 and parts[-2] in ("co", "com", "org", "net") else parts[-2:])


MAGIC = {b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"GIF8": ".gif", b"RIFF": ".webp", b"ID3": ".mp3", b"\xff\xfb": ".mp3", b"OggS": ".ogg"}


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

    def _api_ok(self, url: str) -> bool:
        """Saytning o'z serveri (boshqa subdomen yoki alohida API domeni ham bo'lishi mumkin) — reklama/statistika xizmatlari emas."""
        host = urlparse(url).hostname or ""
        return _site(host) == _site(urlparse(self.base()).hostname) or not TRACKERS.search(host)

    @staticmethod
    def _key(url: str) -> str:
        """Sahifa kaliti: hash-marshrutli SPA (#/products) sahifalari alohida hisoblanadi."""
        base, _, frag = url.partition("#")
        return base + ("#" + frag if frag.startswith(("/", "!")) else "")

    def discover(self):
        maxp = max(1, min(int(self.cfg.get("max_pages") or 20), 60))

        def crawl(page):
            seen, queue, pages, modules = set(), [page.url], [], []
            apis: dict = {}

            def on_resp(resp):                          # SPA saytlar ma'lumotni API (JSON) orqali yuklaydi — sayt o'zi yuborgan javoblar o'qiladi
                try:
                    req = resp.request
                    if req.resource_type not in ("xhr", "fetch"):
                        return
                    ct = resp.headers.get("content-type") or ""
                    entry = {"method": req.method, "host": urlparse(resp.url).hostname, "path": urlparse(resp.url).path[:120], "status": resp.status,
                             "type": ct.split(";")[0][:40]}
                    if len(netlog) < 120:
                        netlog.append(entry)
                    if "json" not in ct or not self._api_ok(resp.url) or resp.status >= 400:
                        return
                    data = resp.json()
                    entry["shape"] = _shape(data)
                    rows = _json_rows(data)
                    entry["rows"] = len(rows) if rows else 0
                    if rows:
                        key = f"{req.method} {urlparse(resp.url).hostname}{urlparse(resp.url).path}"
                        fields = sorted({k for r in rows[:20] for k in _flat(r)})
                        if key not in apis or len(rows) > apis[key]["count"]:
                            apis[key] = {"url": resp.url, "method": req.method, "page": page.url, "fields": fields, "count": len(rows),
                                         "path": urlparse(resp.url).path}
                except Exception:                           # noqa: BLE001 — bitta javob o'qilmasa ham davom etadi
                    pass
            netlog: list = []
            page.on("response", on_resp)
            try:
                page.reload(wait_until="domcontentloaded", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            explicit = [u.strip() for u in (self.cfg.get("pages") or "").splitlines() if u.strip()]
            queue = explicit + queue
            while queue and len(pages) < maxp:
                url = self._key(queue.pop(0))
                if url in seen or not self._same_origin(url) or re.search(r"(?i)logout|signout|chiqish|выход|delete|remove", url):
                    continue
                seen.add(url)
                if url != self._key(page.url):
                    time.sleep(self.delay)
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                page.wait_for_timeout(1200)                 # SPA ma'lumotni kechroq yuklashi mumkin
                info = page.evaluate(PAGE_JS)
                tables = page.evaluate(TABLES_JS, 3) or page.evaluate(GRID_JS, 3)
                modules += info["nav"]
                pages.append({"url": page.url, "title": info["title"], "tables": [{"columns": t[0], "sample_rows": len(t) - 1} for t in tables],
                              "forms": info["forms"], "prompts": info.get("prompts", []), "buttons": info.get("buttons", [])})
                for href, _ in info["links"]:
                    if self._same_origin(href) and self._key(href) not in seen:
                        queue.append(href)
            # Menyu bo'limlarini bosib ko'rish (SPA: havolasiz menyular). Faqat navigatsiya — xavfli so'zli tugmalar bosilmaydi.
            clicked = 0
            for text in page.evaluate(NAV_JS) if pages else []:
                if clicked >= maxp or SKIP_NAV.search(text):
                    continue
                try:
                    if not self._same_origin(page.url):
                        page.goto(self.base(), wait_until="domcontentloaded", timeout=30000)
                    page.get_by_text(text, exact=True).first.click(timeout=5000)
                    clicked += 1
                    time.sleep(self.delay)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    page.wait_for_timeout(1200)
                    if self._key(page.url) not in seen and self._same_origin(page.url):
                        seen.add(self._key(page.url))
                        info = page.evaluate(PAGE_JS)
                        tables = page.evaluate(TABLES_JS, 3) or page.evaluate(GRID_JS, 3)
                        pages.append({"url": page.url, "title": info["title"] or text, "tables": [{"columns": t[0], "sample_rows": len(t) - 1} for t in tables],
                                      "forms": info["forms"], "prompts": info.get("prompts", []), "buttons": info.get("buttons", [])})
                except Exception:                           # noqa: BLE001
                    continue
            return pages, modules, apis, netlog
        pages, modules, apis, netlog = self._session(crawl)
        ents = [{"name": f"{p['title'] or p['url']} #{i + 1}" if len(p["tables"]) > 1 else (p["title"] or p["url"]), "source": p["url"],
                 "table_index": i, "fields": t["columns"], "readable": True} for p in pages for i, t in enumerate(p["tables"])]
        names = {e["name"] for e in ents}
        for _key, a in apis.items():
            path = a["path"]
            seg = next((s for s in reversed(path.strip("/").split("/")) if s and not s.isdigit() and not re.fullmatch(r"v\d+|api|list|index", s)), path)
            name = f"{seg} (API)"
            while name in names:
                name += "+"
            names.add(name)
            ents.append({"name": name, "source": "json:" + a["url"], "page": a["page"], "fields": a["fields"], "readable": True, "kind": "api",
                         "rows_seen": a["count"], "method": a["method"]})
        n_api = len(apis)
        seen_json = sum(1 for n in netlog if "json" in n.get("type", ""))
        return {"modules": sorted(set(m for m in modules if len(m) < 40))[:60], "entities": ents, "pages": pages, "network": netlog,
                "note": f"{len(pages)} sahifa o'rganildi: {len(ents) - n_api} jadval va {n_api} ta API ma'lumot manbai topildi (faqat o'qildi)"
                        + ("" if ents else f" — o'qiladigan ma'lumot topilmadi (tarmoqda {len(netlog)} ta so'rov, {seen_json} ta JSON ko'rildi). "
                                                 "Batafsil → 'O'rganish hisoboti'da sayt nimalar yuborganini ko'ring yoki tovarlar/savdolar sahifasi "
                                                 "manzilini 'O'qiladigan sahifalar'ga yozing.")}

    def perform(self, skill: dict, prompt: str, out_dir, run_id: int, timeout_s: int = 180) -> dict:
        """Tasdiqlangan topshiriqni saytda bajarish: so'rovni yozish, tugmani bosish, yangi natijani olish (faqat shu domen)."""
        import base64
        from pathlib import Path
        url = skill["url"]
        if not self._same_origin(url):
            raise ConnectorError("Boshqa domenda amal bajarilmaydi", "permission_denied")
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        def act(page):
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            if page.query_selector("input[type=password]"):
                raise ConnectorError("Sessiya tugagan — Ulanishlar'da qayta 'Tekshirish' yoki 'Brauzerda kirish'", "auth_expired")
            if page.evaluate(CAPTCHA_JS):
                raise ConnectorError("Saytda CAPTCHA — chetlab o'tilmaydi ('Brauzerda kirish' bilan o'zingiz o'ting)", "user_action_required")
            before_imgs, before_text = set(page.evaluate(IMGS_JS)), page.evaluate("() => document.body.innerText")
            sel = skill.get("prompt_selector")
            if not sel or not page.query_selector(sel):
                sel = page.evaluate(FIND_JS, "prompt")
            if not sel:
                raise ConnectorError("Sahifada so'rov (prompt) maydoni topilmadi — Sayt ko'nikmalarida sahifa yoki selektorni tuzating", "error")
            el = page.query_selector(sel)
            if el.evaluate("e => e.isContentEditable"):
                el.click()
                page.keyboard.type(prompt, delay=5)
            else:
                el.fill(prompt)
            sub = skill.get("submit_selector")
            if not sub or not page.query_selector(sub):
                sub = page.evaluate(FIND_JS, "submit")
            (page.click(sub) if sub else el.press("Enter"))
            t0, new, text, last, stable = time.time(), [], "", None, 0
            while time.time() - t0 < timeout_s:
                page.wait_for_timeout(2000)
                if page.evaluate(PAYWALL_JS):
                    raise ConnectorError("Sayt to'lov yoki kredit so'rayapti — JARVIS hech narsa sotib olmaydi. Tarifni o'zingiz tekshiring.", "permission_denied")
                if page.evaluate(CAPTCHA_JS):
                    raise ConnectorError("CAPTCHA chiqdi — chetlab o'tilmaydi", "user_action_required")
                if skill.get("result") in ("image", "media"):
                    new = [x for x in page.evaluate(IMGS_JS) if x not in before_imgs]
                    if new:
                        page.wait_for_timeout(2500)              # qolgan variantlar ham chiqsin
                        new = [x for x in page.evaluate(IMGS_JS) if x not in before_imgs]
                        break
                else:
                    rs = skill.get("result_selector")
                    if rs and page.query_selector(rs):
                        cur = page.inner_text(rs)
                    else:
                        old = set(before_text.splitlines())
                        cur = "\n".join(ln for ln in page.evaluate("() => document.body.innerText").splitlines()
                                        if ln.strip() and ln not in old and ln.strip() != prompt.strip())
                    if cur and cur == last:
                        stable += 1
                        if stable >= 2:
                            text = cur
                            break
                    else:
                        stable, last = 0, cur
            files = []
            for i, src in enumerate(new[:6]):
                try:
                    if src.startswith("data:"):
                        data = base64.b64decode(src.split(",", 1)[1])
                    elif src.startswith("blob:"):
                        data = base64.b64decode(page.evaluate("""async (u) => { const b = await (await fetch(u)).blob();
                            return await new Promise(r => { const f = new FileReader(); f.onload = () => r(f.result.split(',')[1]); f.readAsDataURL(b); }); }""", src))
                    else:
                        if not src.startswith("http"):
                            continue
                        resp = page.context.request.get(src, timeout=60000)
                        if not resp.ok:
                            continue
                        data = resp.body()
                    if len(data) > 50 * 1024 * 1024:
                        continue
                    ext = next((e for m, e in MAGIC.items() if data.startswith(m)), ".mp4" if data[4:8] == b"ftyp" else None)
                    if not ext:
                        continue
                    f = out_dir / f"sayt_{run_id}_{i + 1}{ext}"
                    f.write_bytes(data)
                    files.append(str(f))
                except Exception:
                    continue
            shot = out_dir / f"sayt_{run_id}_ekran.png"
            try:
                page.screenshot(path=str(shot), full_page=False)
            except Exception:
                shot = None
            return {"outputs": files, "text": text[:8000], "screenshot": str(shot) if shot else None, "page": page.url}
        return self._session(act)

    def _fetch_json(self, api: str, page_url: str, limit: int, method: str = "GET") -> dict:
        if not self._api_ok(api) or not self._same_origin(page_url):
            raise ConnectorError("Boshqa domen o'qilmaydi", "permission_denied")

        def read(page):
            got = {}

            def on(resp):
                try:
                    if urlparse(resp.url).path == urlparse(api).path and "json" in (resp.headers.get("content-type") or ""):
                        rows = _json_rows(resp.json())
                        if rows is not None:
                            got["rows"] = rows
                except Exception:                           # noqa: BLE001
                    pass
            try:                                            # 1) to'g'ridan-to'g'ri (cookie sessiyasi bilan) — faqat GET
                if method != "GET":
                    raise ValueError("POST — faqat sahifa orqali")
                r = page.context.request.get(api, timeout=30000)
                if r.ok and "json" in (r.headers.get("content-type") or ""):
                    rows = _json_rows(r.json())
                    if rows is not None:
                        got["rows"] = rows
            except Exception:                               # noqa: BLE001
                pass
            if "rows" not in got:                           # 2) sahifani ochib, sayt o'zi yuklagan javobni olish (token bilan ishlaydigan saytlar)
                page.on("response", on)
                page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                if page.query_selector("input[type=password]"):
                    raise ConnectorError("Sessiya tugagan — qayta kirish kerak", "auth_expired")
            if "rows" not in got:
                raise ConnectorError("Sayt bu ma'lumotni bermadi (API javobi kelmadi) — 'O'rganish'ni qayta bosing", "error")
            return got["rows"]
        rows = self._session(read)
        return {"records": [_flat(r) for r in rows[:limit]], "next": None}

    def fetch_data(self, entity, *, since=None, cursor=None, limit=5000):
        ent = next((e for e in (self.conn.get("entities") or []) if e["name"] == entity), None)
        url = ent["source"] if ent else entity
        if url.startswith("json:"):
            return self._fetch_json(url[5:], (ent or {}).get("page") or self.base(), limit, (ent or {}).get("method", "GET"))
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
