"""Agent rejimi + o'rgatilgan sayt amali: sinov POS sayti (login, kirim formasi) + haqiqiy Chromium + soxta AI modeli.

Soxta AI aniq JSON qadamlar qaytaradi — shu bilan agent sikli (vosita tanlash → natija → javob), tasdiq va bajarish sinaladi.
Bu haqiqiy AI sifatini sinamaydi: haqiqiy modelning qanchalik to'g'ri o'ylashi ulangan modelga bog'liq.
"""
import http.server
import json
import threading
import urllib.parse

import pytest

from tests.test_site_skills import _browser, keyring  # noqa: F401 — fixture

KIRIMLAR: list[dict] = []
LOGIN = '<form method="post" action="/login"><input name="login"><input type="password" name="parol"><button type="submit">Kirish</button></form>'
FORM = """<html><head><title>YesPOS demo — Kirim</title></head><body><h2>Yangi kirim</h2><form method="post" action="/kirim">
<label for="k">Kontragent</label><select id="k" name="kontragent"><option value="">—</option><option value="ali">Ali aka</option><option value="vali">Vali savdo</option></select>
<label for="t">Tovar</label><input id="t" name="tovar"><label for="m">Miqdor</label><input id="m" name="miqdor"><label for="n">Narx</label><input id="n" name="narx">
<button type="submit" id="save">Saqlash</button></form></body></html>"""


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, body, code=200, headers=()):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        ok = "sid=ok" in (self.headers.get("Cookie") or "")
        if not ok:
            return self._send(LOGIN)
        if self.path.startswith("/kirim"):
            return self._send(FORM)
        self._send('<a href="/kirim">Kirim</a>')

    def do_POST(self):
        body = urllib.parse.parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode())
        if self.path == "/login":
            if body.get("login") == ["admin"] and body.get("parol") == ["p-777"]:
                return self._send("", 302, [("Set-Cookie", "sid=ok; Path=/"), ("Location", "/kirim")])
            return self._send(LOGIN)
        KIRIMLAR.append({k: v[0] for k, v in body.items()})
        self._send(f"<p>Kirim saqlandi #{len(KIRIMLAR)}</p><a href='/kirim'>yana</a>")

    def log_message(self, *a):
        pass


@pytest.fixture
def pos():
    KIRIMLAR.clear()
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def test_parse_and_no_ai_fallback(core):
    from jarvis.agent_loop import _parse
    assert _parse('```json\n{"tool": "x", "args": {}}\n```')["tool"] == "x"
    assert _parse('Mana: {"answer": "salom"} tamom')["answer"] == "salom"
    assert _parse("oddiy matn") is None
    assert not core.agent.ready()                                     # model yo'q — agent rejimi o'chiq, oddiy javob
    assert core.chat("salom")["intent"] != "agent"
    ids = {t["id"] for t in core.tools.catalog("user")}
    assert {"connections.list", "connection.refresh", "site.task", "site.generate", "instagram.request_publish", "telegram.send"} <= ids
    assert all(t["approval"] for t in core.tools.catalog() if t["level"] in "CDE")


def test_teach_kirim_then_agent_proposes_and_executes(core, client, pos, keyring, monkeypatch):  # noqa: F811
    _browser(monkeypatch)
    c = client.post("/api/integrations", json={"name": "YesPOS", "system_type": "pos", "adapter": "website",
                                               "config": {"base_url": pos}, "secrets": {"username": "admin", "password": "p-777"}}).json()
    assert client.post(f"/api/integrations/{c['id']}/test").json()["status"] == "connected"

    def show(page):                                                   # foydalanuvchi bir marta ko'rsatadi
        page.select_option("#k", "ali")
        page.fill("#t", "Coca-Cola 1L")
        page.fill("#m", "5")
        page.fill("#n", "11000")
        page.click("#m")                                              # change hodisasi uchun fokusni almashtirish
        page.click("#save")
        page.wait_for_selector("text=Kirim saqlandi")
        page.goto(pos + "/kirim")
        page.click("#jarvis-done")
    t = core.site_tasks.start_recording(c["id"], "kirim", pos + "/kirim", headless=True, driver=show, timeout_s=20)
    assert t["status"] == "recorded", t
    ops = [(s["op"], s.get("selector")) for s in t["steps"]]
    assert ("select", "#k") in ops and ("fill", "#t") in ops and ("click", "#save") in ops, ops
    assert "p-777" not in json.dumps(t)                                # parol yozib olinmagan
    KIRIMLAR.clear()                                                  # o'rgatishdagi namuna kirim
    steps = [s | {"param": {"#k": "kontragent", "#t": "tovar", "#m": "miqdor", "#n": "narx"}.get(s.get("selector"))} if s["op"] in ("fill", "select") else s
             for s in t["steps"] if not (s["op"] == "goto")]
    r = client.post(f"/api/site-tasks/{t['id']}/finalize", json={"name": "kirim", "description": "POS'ga tovar kirimi", "steps": steps,
                                                                 "success_text": "Kirim saqlandi"})
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["status"] == "ready" and task["financial"] == 1 and [p["name"] for p in task["params"]] == ["kontragent", "tovar", "miqdor", "narx"]

    # Soxta AI: 1) ulanishlarni ko'radi 2) site.task chaqiradi 3) javob beradi
    script = [{"tool": "connections.list", "args": {}, "why": "qaysi POS"},
              {"tool": "site.task", "args": {"task_id": task["id"], "params": {"kontragent": "vali", "tovar": "Fanta 1L", "miqdor": "12", "narx": "9500"}}},
              {"answer": "Vali savdo uchun 12 ta Fanta 1L (9 500 so'm) kirimi tayyor — tasdiqlang."}]
    seen = []

    def fake_route(msgs, purpose="", private=None, allow_paid=False):
        seen.append(msgs[-1]["content"])
        return {"text": json.dumps(script[len(seen) - 1], ensure_ascii=False), "route": {"provider": "test-ai", "model": "fake"}}
    monkeypatch.setattr(core.ai, "route", fake_route)
    monkeypatch.setattr(core.agent, "ready", lambda: True)
    res = client.post("/api/chat", json={"text": "Vali savdoga 12 ta Fanta 1L 9500 dan kirim qil"}).json()
    assert res["intent"] == "agent" and "tasdiqlang" in res["text"]
    assert [s["tool"] for s in res["steps"]] == ["connections.list", "site.task"] and "YesPOS" in seen[1]
    appr = res["approvals"][0]
    assert appr["level"] == "E" and "Fanta" in appr["summary"] and not KIRIMLAR             # tasdiqsiz hech narsa kiritilmadi
    assert client.post(f"/api/approvals/{appr['id']}/run").status_code == 400
    client.post(f"/api/approvals/{appr['id']}/decide", json={"approve": True, "confirm_hash": appr["payload_hash"]})
    out = client.post(f"/api/approvals/{appr['id']}/run").json()
    assert out["status"] == "ok" and out["verified"], out
    assert KIRIMLAR == [{"kontragent": "vali", "tovar": "Fanta 1L", "miqdor": "12", "narx": "9500"}]
    assert client.post(f"/api/approvals/{appr['id']}/run").status_code == 400            # ikki marta kiritilmaydi
    bad = client.post(f"/api/site-tasks/{task['id']}/propose", json={"params": {"tovar": "x"}})
    assert bad.status_code == 400 and "Qiymat kerak" in bad.text
