"""SPA POS (cloudshop/YesPOS kabi): ma'lumot HTML jadvalda emas, API (JSON) orqali; menyu havolasiz tugmalar; API token bilan.
JARVIS menyuni bosib ko'radi, JSON javoblarni ushlaydi, ulardan obyekt yasaydi va sinxronlay oladi."""
import http.server
import json
import threading

import pytest

from tests.test_site_skills import _browser, keyring  # noqa: F401

APP = """<html><head><title>Cloud POS</title></head><body><aside class="sidebar"><button id="m1">Tovarlar</button><button id="m2">Savdolar</button>
<a href="#/clients">Mijozlar</a><button id="m3">Chiqish</button></aside><div id="root">Bosh sahifa</div><script>
const tok = localStorage.getItem('t') || (localStorage.setItem('t', 'abc'), 'abc');
const load = (u) => fetch(u, {headers: {Authorization: 'Bearer ' + tok}}).then(r => r.json()).then(d => {
  document.getElementById('root').innerHTML = (d.data || d).map(x => '<div class="row">' + JSON.stringify(x) + '</div>').join(''); });
document.getElementById('m1').onclick = () => { history.pushState({}, '', '/app/products'); load('/api/v2/products?page=1'); };
document.getElementById('m2').onclick = () => { history.pushState({}, '', '/app/sales'); load('/api/v2/sales'); };
document.getElementById('m3').onclick = () => { document.title = 'CHIQDI'; };
const rpc = () => fetch('/api/rpc', {method: 'POST', headers: {Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json'},
  body: JSON.stringify({method: 'clients.list'})}).then(r => r.json()).then(d => { document.getElementById('root').innerText = JSON.stringify(d); });
window.addEventListener('hashchange', () => { if (location.hash === '#/clients') rpc(); });
if (location.hash === '#/clients') rpc();
if (location.pathname === '/app/products') load('/api/v2/products?page=1');
if (location.pathname === '/app/sales') load('/api/v2/sales');
</script></body></html>"""
PRODUCTS = {"data": [{"id": 1, "name": "Coca-Cola 1L", "price": 12000, "stock": 40, "category": {"name": "Ichimlik"}},
                     {"id": 2, "name": "Fanta 1L", "price": 11000, "stock": 3, "category": {"name": "Ichimlik"}}], "total": 2}
SALES = [{"receipt_id": "R-1", "date": "2026-10-31", "product": "Coca-Cola 1L", "qty": 2, "total": 24000}]


CLIENTS = {"jsonrpc": "2.0", "result": {"data": {"page": {"items": [{"client_id": 7, "fio": "Ali Valiyev", "telefon": "+998901112233", "qarz": 50000}]}}}}


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, body, ct="text/html; charset=utf-8", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        if self.path.startswith("/api/"):
            if self.headers.get("Authorization") != "Bearer abc":
                return self._send(json.dumps({"error": "unauthorized"}), "application/json", 401)
            return self._send(json.dumps(PRODUCTS if "products" in self.path else SALES), "application/json")
        self._send(APP)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.headers.get("Authorization") != "Bearer abc":
            return self._send(json.dumps({"error": "unauthorized"}), "application/json", 401)
        self._send(json.dumps(CLIENTS), "application/json")

    def log_message(self, *a):
        pass


@pytest.fixture
def spa():
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def test_spa_api_discovery_and_sync(core, client, spa, keyring, monkeypatch):  # noqa: F811
    _browser(monkeypatch)
    c = client.post("/api/integrations", json={"name": "Cloud POS", "system_type": "pos", "adapter": "website",
                                               "config": {"base_url": spa + "/app"}, "secrets": {}}).json()
    assert client.post(f"/api/integrations/{c['id']}/test").json()["status"] == "connected"
    d = client.post(f"/api/integrations/{c['id']}/discover")
    assert d.status_code == 200, d.text
    conn = d.json()
    names = {e["name"]: e for e in conn["entities"]}
    assert "products (API)" in names and "sales (API)" in names, (names, conn.get("status_note"))
    assert "category.name" in names["products (API)"]["fields"]
    assert conn["mapping"]["products (API)"]["entity"] == "product" and conn["mapping"]["sales (API)"]["entity"] == "sale"
    s = client.post(f"/api/integrations/{c['id']}/sync")
    assert s.status_code == 200, s.text
    n = core.db.one("SELECT COUNT(*) n FROM ext_records WHERE conn_id=?", (c["id"],))["n"]
    assert "rpc (API)" in names and names["rpc (API)"]["method"] == "POST"     # hash-marshrut (#/clients) va POST API, chuqur JSON
    assert conn["mapping"]["rpc (API)"]["entity"] == "customer"
    assert any(x["method"] == "POST" for x in conn["learning"]["extra"]["network"])   # o'rganish hisoboti
    assert n == 4                                                            # 2 tovar + 1 savdo + 1 mijoz — token bilan ishlaydigan API'dan


def test_auto_learn_after_connect(core, client, spa, keyring, monkeypatch):  # noqa: F811
    """Ulanish tekshirilib "ulangan" bo'lsa — JARVIS o'zi o'rganadi, xaritalaydi va ma'lumotni oladi (siz bosmasdan)."""
    import time
    _browser(monkeypatch)
    core.integrations.auto_learn = True
    c = client.post("/api/integrations", json={"name": "Cloud POS", "system_type": "pos", "adapter": "website",
                                               "config": {"base_url": spa + "/app"}, "secrets": {}}).json()
    t = client.post(f"/api/integrations/{c['id']}/test").json()
    assert t["auto_learn"]["started"]
    for _ in range(120):
        if core.db.one("SELECT COUNT(*) n FROM ext_records WHERE conn_id=?", (c["id"],))["n"] >= 4 and c["id"] not in core.integrations._learning:
            break
        time.sleep(0.5)
    assert core.db.one("SELECT COUNT(*) n FROM ext_records WHERE conn_id=?", (c["id"],))["n"] == 4
    assert any("tushunildi" in f["text"] for f in core.office_live.feed())
    assert client.post(f"/api/integrations/{c['id']}/test").json()["auto_learn"]["started"] is False   # yaqinda o'rganilgan
