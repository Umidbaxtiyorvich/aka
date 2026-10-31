"""Login Probe — sayt havolasidan kirish usulini aniqlash: qaysi maydonlar kerak (login, parol, email, telefon, ID/tashkilot kodi ...).

Jarayon (faqat O'QISH, hech narsa yuborilmaydi, login qilinmaydi):
1. Havola ochiladi (oddiy HTTP). Sahifadagi formalar va maydonlar o'qiladi.
2. Parol maydoni bo'lmasa — "Kirish / Login / Вход" havolasi topiladi va (faqat shu sayt ichida) bir marta ochiladi.
3. Sahifa JavaScript bilan chizilgan bo'lsa (maydon topilmasa) va brauzer agenti (Playwright) bor bo'lsa — sahifa brauzerda
   ochilib, maydonlar o'qiladi.
4. Har bir maydon turi aniqlanadi va o'zbekcha nomlanadi. SMS/OTP kodi va CAPTCHA saqlanmaydi — ular har kirishda
   foydalanuvchining o'zi tomonidan kiritiladi (JARVIS chetlab o'tmaydi).
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .. import net
from .base import ConnectorError, check_url

LOGIN_LINK = re.compile(r"(?i)\b(kirish|tizimga kirish|login|log in|sign in|signin|войти|вход|авторизац|kabinet|кабинет)\b")
SSO = {"Google": r"(?i)google", "Telegram": r"(?i)telegram", "OneID": r"(?i)one\s?id|id\.egov", "Facebook": r"(?i)facebook", "Apple": r"(?i)apple id|sign in with apple"}
SERVICES = {  # bu xizmatlar uchun rasmiy (API) bo'lim bor — sayt orqali avtomatik kirish bloklanadi yoki qoidaga zid
    "instagram.com": ("#instagram", "Instagram"), "facebook.com": ("#instagram", "Facebook / Meta"), "t.me": ("#telegram", "Telegram"),
    "telegram.org": ("#telegram", "Telegram"), "web.telegram.org": ("#telegram", "Telegram")}
CAPTCHA = re.compile(r"(?i)g-recaptcha|recaptcha|hcaptcha|cf-turnstile|captcha")
KINDS = [  # (tur, o'zbekcha nom, regex: name/id/placeholder/autocomplete/label)
    ("otp", "SMS / tasdiqlash kodi", r"otp|sms|one.?time|2fa|verification|tasdiqlash kod|код подтверж|confirm.?code|\bcode\b"),
    ("email", "Email", r"e-?mail|почта|pochta"),
    ("phone", "Telefon raqami", r"phone|tel\b|telefon|телефон|mobile|msisdn"),
    ("company", "Tashkilot / do'kon ID", r"company|tenant|organi[sz]ation|org.?id|shop|store|branch|filial|tashkilot|организац|компан|inn|stir|pinfl|account.?id|domain|workspace"),
    ("login", "Login (foydalanuvchi nomi)", r"login|user|username|логин|пользоват|foydalanuvchi|account"),
    ("id", "ID raqami", r"\bid\b|_id\b|номер|raqam"),
]


class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs, self.links, self.buttons, self.labels, self._label_for, self._label_text, self._in_a, self._a_href, self._a_text = [], [], [], {}, None, "", False, "", ""
        self.forms = 0

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "form":
            self.forms += 1
        elif tag in ("input", "select"):
            a["_tag"] = tag
            self.inputs.append(a)
        elif tag == "label":
            self._label_for, self._label_text = a.get("for"), ""
        elif tag == "a":
            self._in_a, self._a_href, self._a_text = True, a.get("href", ""), ""
        elif tag == "button":
            self.buttons.append(a.get("aria-label", "") + " " + a.get("title", ""))

    def handle_endtag(self, tag):
        if tag == "label" and self._label_for:
            self.labels[self._label_for] = self._label_text.strip()
            self._label_for = None
        elif tag == "a" and self._in_a:
            self.links.append((self._a_href, self._a_text.strip()))
            self._in_a = False

    def handle_data(self, data):
        if self._label_for is not None:
            self._label_text += data
        if self._in_a:
            self._a_text += data
        if self.buttons and data.strip():
            self.buttons[-1] += " " + data.strip()


def classify(inp: dict, label: str = "") -> tuple[str, str] | None:
    t = (inp.get("type") or "text").lower()
    if t in ("hidden", "submit", "button", "checkbox", "radio", "image", "reset", "file", "search"):
        return None
    if t == "password":
        return "password", "Parol"
    hint = " ".join(inp.get(k, "") for k in ("name", "id", "placeholder", "autocomplete", "aria-label")) + " " + label
    if t == "email":
        return "email", "Email"
    if t == "tel":
        return "phone", "Telefon raqami"
    for kind, uz, rx in KINDS:
        if re.search(rx, hint, re.I):
            return kind, uz
    if t in ("text", "number", ""):
        return "login", "Login (foydalanuvchi nomi)"
    return None


def _selector(inp: dict, idx: int) -> str:
    if inp.get("id") and re.fullmatch(r"[A-Za-z][\w\-:.]*", inp["id"]):
        return f"#{inp['id']}"
    if inp.get("name"):
        return f"input[name=\"{inp['name']}\"]"
    return f"input:nth-of-type({idx + 1})"


def _fields(inputs: list[dict], labels: dict) -> list[dict]:
    out, seen = [], set()
    for i, inp in enumerate(inputs):
        c = classify(inp, labels.get(inp.get("id", ""), ""))
        if not c:
            continue
        kind, uz = c
        key = kind if kind not in seen else f"{kind}{i}"
        seen.add(kind)
        out.append({"key": re.sub(r"[^a-z0-9_]", "", key)[:30], "kind": kind, "label": uz, "selector": _selector(inp, i),
                    "secret": True, "store": kind != "otp", "required": inp.get("required", None) is not None or kind == "password",
                    "hint": (inp.get("placeholder") or labels.get(inp.get("id", ""), "") or inp.get("name", ""))[:60]})
    return out


def _parse(html: str):
    p = _FormParser()
    try:
        p.feed(html)
    except Exception:
        pass
    return p


def _browser_inputs(url: str) -> tuple[list[dict], dict, str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ConnectorError("Brauzer agenti (Playwright) o'rnatilmagan", "not_supported") from None
    js = """() => [...document.querySelectorAll('input,select')].map(e => ({_tag: e.tagName.toLowerCase(), type: e.type||'', name: e.name||'',
        id: e.id||'', placeholder: e.placeholder||'', autocomplete: e.autocomplete||'', 'aria-label': e.getAttribute('aria-label')||'',
        _label: (e.labels && e.labels[0] ? e.labels[0].innerText : '')}))"""
    with sync_playwright() as p:
        import os
        kw = {"headless": True}
        if os.environ.get("JARVIS_CHROMIUM_PATH"):
            kw["executable_path"] = os.environ["JARVIS_CHROMIUM_PATH"]
        b = p.chromium.launch(**kw)
        try:
            page = b.new_page()
            page.goto(url, wait_until="networkidle", timeout=25000)
            items = page.evaluate(js)
            html = page.content()
            final = page.url
        finally:
            b.close()
    labels = {i["id"]: i.get("_label", "") for i in items if i.get("id")}
    return items, labels, html + f"<!--final:{final}-->"


def probe(url: str, use_browser: bool = True) -> dict:
    base = check_url(url, "Sayt manzili")
    host = (urlparse(base).hostname or "").lower().removeprefix("www.")
    svc = next((v for d, v in SERVICES.items() if host == d or host.endswith("." + d)), None)
    if svc:
        return {"url": base, "login_url": base, "method": "service", "fields": [], "guessed": False, "captcha": False, "otp": False, "sso": [],
                "notes": [f"{svc[1]} sayt sifatida ulanmaydi: u avtomatik kirishni bloklaydi va akkauntni vaqtincha muzlatishi mumkin. "
                          f"JARVIS'da {svc[1]} uchun rasmiy API orqali ishlaydigan alohida bo'lim bor."],
                "domain": host, "service_link": svc[0], "service": svc[1], "summary": f"{svc[1]} — maxsus bo'lim orqali ulanadi"}
    notes, method = [], "static"
    try:
        st, html = net.request("GET", base, timeout=20, headers={"Accept": "text/html"})
    except net.NetError as e:
        raise ConnectorError(f"Sayt ochilmadi: {e}", "error") from None
    if st >= 400:
        raise ConnectorError(f"Sayt xato qaytardi (HTTP {st})", "error")
    login_url, p = base, _parse(html)
    has_pwd = any((i.get("type") or "").lower() == "password" for i in p.inputs)
    if not has_pwd:
        for href, text in p.links:
            if LOGIN_LINK.search(text) or LOGIN_LINK.search(href):
                cand = urljoin(base, href)
                if urlparse(cand).netloc == urlparse(base).netloc and cand != base:
                    try:
                        st2, html2 = net.request("GET", cand, timeout=20, headers={"Accept": "text/html"})
                        p2 = _parse(html2)
                        if st2 < 400 and p2.inputs:
                            login_url, p, html = cand, p2, html2
                            notes.append(f"Kirish sahifasi topildi: {cand}")
                    except net.NetError:
                        pass
                break
    fields = _fields(p.inputs, p.labels)
    if not any(f["kind"] == "password" for f in fields) and use_browser:
        try:
            items, labels, html_b = _browser_inputs(login_url)
            bf = _fields(items, labels)
            if bf:
                fields, html, method = bf, html_b, "browser"
                notes.append("Sahifa JavaScript bilan chiziladi — maydonlar brauzerda aniqlandi")
        except ConnectorError as e:
            if not fields:
                notes.append(f"Sahifada forma topilmadi (JavaScript bilan chizilgan bo'lishi mumkin). {e} — standart 'login + parol' taklif qilinadi.")
        except Exception as e:
            notes.append(f"Brauzerda ochib bo'lmadi: {str(e)[:120]}")
    guessed = False
    if not fields:
        guessed = True
        fields = [{"key": "login", "kind": "login", "label": "Login (foydalanuvchi nomi)", "selector": "", "secret": True, "store": True, "required": True, "hint": ""},
                  {"key": "password", "kind": "password", "label": "Parol", "selector": "", "secret": True, "store": True, "required": True, "hint": ""}]
    text = html + " " + " ".join(p.buttons) + " " + " ".join(t for _, t in p.links)
    sso = [n for n, rx in SSO.items() if re.search(rf"(?i)(sign in|kirish|войти|continue|login).{{0,30}}{rx[4:]}|{rx[4:]}.{{0,20}}(orqali|bilan|login)", text)]
    captcha = bool(CAPTCHA.search(html))
    otp = any(f["kind"] == "otp" for f in fields)
    if captcha:
        notes.append("Saytda CAPTCHA bor — JARVIS uni chetlab o'tmaydi: birinchi kirishni 'Brauzerda kirish' bilan o'zingiz qilasiz, keyin sessiya saqlanadi.")
    if otp:
        notes.append("SMS/tasdiqlash kodi so'raladi — kod saqlanmaydi, har kirishda o'zingiz kiritasiz ('Brauzerda kirish').")
    if sso:
        notes.append(f"{', '.join(sso)} orqali kirish tugmasi bor — bu usulda parol JARVIS'ga berilmaydi: 'Brauzerda kirish' orqali o'zingiz kirasiz.")
    return {"url": base, "login_url": login_url, "method": method, "fields": fields, "guessed": guessed, "captcha": captcha, "otp": otp, "sso": sso,
            "notes": notes, "domain": urlparse(base).netloc,
            "summary": ("Kirish uchun kerak: " + ", ".join(f["label"] for f in fields if f["store"])) if fields else "Kirish formasi topilmadi"}
