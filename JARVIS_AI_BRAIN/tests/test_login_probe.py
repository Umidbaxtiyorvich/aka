"""Sayt havolasidan kirish usulini aniqlash: maydonlar, kirish sahifasi, CAPTCHA/SMS/SSO, saqlash va kirish."""
import json

import pytest

from jarvis import net
from jarvis.integrations.base import ConnectorError
from jarvis.integrations.login_probe import probe

HOME = """<html><body><h1>POS tizimi</h1><a href="/auth/login">Tizimga kirish</a><a href="https://other.uz/login">boshqa sayt</a></body></html>"""
LOGIN = """<html><body><form action="/auth"><label for="org">Tashkilot ID</label><input id="org" name="company_id" required>
<input type="email" name="email" placeholder="Email"><input type="password" name="pass" id="pwd"><input type="hidden" name="csrf" value="x">
<input type="checkbox" name="remember"><button type="submit">Kirish</button></form></body></html>"""
OTP = """<form><input type="tel" name="phone"><input name="sms_code" placeholder="SMS kod"><div class="g-recaptcha"></div>
<button>Telegram orqali kirish</button></form>"""


def fake(pages):
    def t(method, url, data, headers, timeout):
        for k, v in pages.items():
            if url.rstrip("/").endswith(k):
                return 200, v
        return 404, "not found"
    return t


def test_probe_follows_login_link_and_detects_fields(monkeypatch):
    monkeypatch.setattr(net, "TRANSPORT", fake({"pos.uz": HOME, "/auth/login": LOGIN}))
    r = probe("https://pos.uz", use_browser=False)
    assert r["login_url"] == "https://pos.uz/auth/login"
    kinds = [f["kind"] for f in r["fields"]]
    assert kinds == ["company", "email", "password"]                       # hidden/checkbox/submit o'tkazildi
    assert r["fields"][0]["selector"] == "#org" and r["fields"][0]["label"].startswith("Tashkilot")
    assert all(f["secret"] for f in r["fields"]) and "Parol" in r["summary"] and not r["captcha"]


def test_probe_otp_captcha_sso_and_guess(monkeypatch):
    monkeypatch.setattr(net, "TRANSPORT", fake({"bank.uz": OTP}))
    r = probe("https://bank.uz", use_browser=False)
    assert r["captcha"] and r["otp"] and "Telegram" in r["sso"]
    otp = next(f for f in r["fields"] if f["kind"] == "otp")
    assert otp["store"] is False and any("chetlab o'tmaydi" in n for n in r["notes"])
    monkeypatch.setattr(net, "TRANSPORT", fake({"spa.uz": "<div id=app></div><script src=app.js></script>"}))
    g = probe("https://spa.uz", use_browser=False)
    assert g["guessed"] and [f["kind"] for f in g["fields"]] == ["login", "password"]
    with pytest.raises(ConnectorError):
        probe("http://evil.example.com")                                     # faqat https (yoki localhost)


def test_probe_api_and_save_with_detected_fields(client, core, monkeypatch):
    monkeypatch.setattr(net, "TRANSPORT", fake({"pos.uz": HOME, "/auth/login": LOGIN}))
    r = client.post("/api/integrations/probe-login", json={"url": "https://pos.uz"})
    assert r.status_code == 200
    d = r.json()
    import sys
    store = {}

    class KR:
        @staticmethod
        def get_keyring(): return KR
        @staticmethod
        def set_password(svc, name, value): store[name] = value
        @staticmethod
        def get_password(svc, name): return store.get(name)
        @staticmethod
        def delete_password(svc, name): store.pop(name, None)
    monkeypatch.setitem(sys.modules, "keyring", KR)
    c = client.post("/api/integrations", json={"name": "Mening POS", "system_type": "pos", "adapter": "website",
                                               "config": {"base_url": d["url"], "login_url": d["login_url"], "login_fields": d["fields"]},
                                               "secrets": {"f_company": "ORG-77", "f_email": "a@b.uz", "f_password": "Parol-123!"}})
    assert c.status_code == 200, c.text
    body = c.json()
    assert set(body["secrets"]) == {"f_company", "f_email", "f_password"} and "Parol-123" not in json.dumps(body)
    assert client.post("/api/integrations", json={"name": "x", "system_type": "pos", "adapter": "website", "config": {"base_url": "https://pos.uz"},
                                                  "secrets": {"bad key": "1"}}).status_code == 400
    assert client.post("/api/integrations/probe-login", json={"url": "ftp://x"}).status_code == 400


def test_probe_redirects_official_services():
    r = probe("https://www.instagram.com/accounts/login/", use_browser=False)   # tarmoqqa chiqmaydi
    assert r["service_link"] == "#instagram" and not r["fields"] and "rasmiy API" in r["notes"][0]
