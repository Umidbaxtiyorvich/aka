"""Site Skills / Task Router: ulangan saytdan topshiriq bajarish (shu kompyuterdagi sinov sayti + haqiqiy Chromium)."""
import http.server
import os
import sys
import threading
from pathlib import Path

import pytest

LOGIN = '<form method="post" action="/login"><input name="username"><input type="password" name="password"><button type="submit">Kirish</button></form>'
APP = """<html><head><title>Rasm studiya</title></head><body><nav><a href="/app">Rasm</a> <a href="/tr">Tarjima</a></nav>
<textarea id="p" placeholder="Describe your image"></textarea><button id="g">Generate</button><div id="out"></div>
<script>document.getElementById('g').onclick = () => setTimeout(() => {
  const c = document.createElement('canvas'); c.width = 256; c.height = 256; const x = c.getContext('2d');
  x.fillStyle = '#c00'; x.fillRect(0, 0, 256, 256); x.fillStyle = '#fff'; x.fillText(document.getElementById('p').value, 10, 128);
  const i = new Image(); i.src = c.toDataURL('image/png'); document.getElementById('out').appendChild(i); }, 600);</script></body></html>"""
TR = """<html><head><title>Tarjimon</title></head><body><textarea id="t" placeholder="Matn kiriting (translate)"></textarea><button id="b">Translate</button>
<div id="r"></div><script>document.getElementById('b').onclick = () => setTimeout(() => {
  document.getElementById('r').innerText = 'TARJIMA: ' + document.getElementById('t').value.toUpperCase(); }, 400);</script></body></html>"""


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, body, code=200, headers=()):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        authed = "sid=ok" in (self.headers.get("Cookie") or "")
        if self.path in ("/app", "/tr") and authed:
            return self._send(APP if self.path == "/app" else TR)
        if self.path in ("/", "/app", "/tr"):
            return self._send(LOGIN) if not authed else self._send("", 302, [("Location", "/app")])
        self._send("yo'q", 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode()
        if "username=demo" in body and "password=sir-123" in body:
            return self._send("", 302, [("Set-Cookie", "sid=ok; Path=/"), ("Location", "/app")])
        self._send(LOGIN, 200)

    def log_message(self, *a):
        pass


@pytest.fixture
def site():
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


@pytest.fixture
def keyring(monkeypatch):
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
    return store


def _browser(monkeypatch):
    pytest.importorskip("playwright.sync_api")
    if os.path.exists("/opt/pw-browsers/chromium") and not os.environ.get("JARVIS_CHROMIUM_PATH"):
        monkeypatch.setenv("JARVIS_CHROMIUM_PATH", "/opt/pw-browsers/chromium")
    from jarvis.integrations.website import WebsiteConnector
    monkeypatch.setattr(WebsiteConnector, "delay", 0)


def test_router_without_sites_is_honest(core):
    p = core.site_skills.plan("rasm yaratib ber: tog'dagi qal'a")
    assert p["capability"] == "image.generate" and p["prompt"] == "tog'dagi qal'a"
    assert p["choice"] is None and "yo'q" in p["text"]                     # SD sozlanmagan, sayt ulanmagan — yolg'on "bajarildi" yo'q
    v = core.site_skills.plan("video yarat: dengiz bo'yi")
    assert v["capability"] == "video.generate" and not v["options"][0]["available"]
    assert core.site_skills.plan("bugungi savdoni kiritib qo'y: savdo kirit 500 ming")["financial"]
    assert core.site_skills.detect_task("salom, qalaysan") is None
    r = core.chat("rasm chizib ber: mushuk")
    assert r["intent"] == "task_router" and r["plan"]["capability"] == "image.generate"


def test_site_skill_detect_approve_execute(core, client, site, keyring, monkeypatch):
    _browser(monkeypatch)
    c = client.post("/api/integrations", json={"name": "Rasm studiya", "system_type": "website", "adapter": "website",
                                               "config": {"base_url": site}, "secrets": {"username": "demo", "password": "sir-123"}})
    assert c.status_code == 200, c.text
    cid = c.json()["id"]
    t = client.post(f"/api/integrations/{cid}/test").json()
    assert t["status"] == "connected", t
    d = client.post(f"/api/integrations/{cid}/discover")
    assert d.status_code == 200, d.text
    skills = client.get("/api/site-skills", params={"conn_id": cid}).json()["skills"]
    caps = {(s["capability"], s["url"].rsplit("/", 1)[-1]) for s in skills}
    assert ("image.generate", "app") in caps and ("translate", "tr") in caps, caps

    plan = client.post("/api/do/plan", json={"text": "rasm studiyada rasm yaratib ber: qizil olma"}).json()
    top = plan["options"][plan["choice"]]
    assert top["kind"] == "site" and top["conn_id"] == cid and top["available"] and top["named"]
    r = client.post("/api/do/run", json={"skill_id": top["skill_id"], "prompt": plan["prompt"]}).json()
    appr = r["approval"]
    assert appr["status"] == "pending" and appr["level"] == "D"
    assert client.post(f"/api/site-skills/execute/{appr['id']}").status_code == 400          # tasdiqsiz bajarilmaydi
    client.post(f"/api/approvals/{appr['id']}/decide", json={"approve": True, "confirm_hash": appr["payload_hash"]})
    res = client.post(f"/api/site-skills/execute/{appr['id']}").json()
    assert res["status"] == "ok", res
    f = Path(res["outputs"][0])
    assert f.exists() and f.read_bytes().startswith(b"\x89PNG") and Path(res["screenshot"]).exists()
    assert client.post(f"/api/site-skills/execute/{appr['id']}").status_code == 400          # ikki marta bajarilmaydi
    assert any(s["verified"] for s in client.get("/api/site-skills", params={"conn_id": cid}).json()["skills"] if s["capability"] == "image.generate")

    tr = next(s for s in skills if s["capability"] == "translate")
    a2 = client.post("/api/do/run", json={"skill_id": tr["id"], "prompt": "salom dunyo"}).json()["approval"]
    client.post(f"/api/approvals/{a2['id']}/decide", json={"approve": True, "confirm_hash": a2["payload_hash"]})
    res2 = client.post(f"/api/site-skills/execute/{a2['id']}").json()
    assert res2["status"] == "ok" and "TARJIMA: SALOM DUNYO" in res2["text"], res2

    bad = client.post("/api/do/run", json={"skill_id": tr["id"], "prompt": "parol: sk-abcdefghijklmnopqrstuvwx1234"})
    assert bad.status_code == 400                                                              # maxfiy matn saytga yuborilmaydi
    assert "sir-123" not in str(client.get("/api/site-skills").json())
