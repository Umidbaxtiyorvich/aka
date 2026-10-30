"""Universal Integration Engine — soxta (mock) serverlar bilan. Bu real POS/ERP ulanishi EMAS: adapterlar mantig'i,
xavfsizlik, sinxronlash va tahlil to'g'ri ishlashini tekshiradi."""
import json
import sqlite3
import sys
from datetime import date, timedelta

import pytest

from jarvis import net
from jarvis.integrations import IntegrationError
from jarvis.integrations.mcp_db_files import check_select
from jarvis.integrations.base import ConnectorError

TODAY = date.today()


class FakeKeyring:
    store = {}

    @staticmethod
    def get_keyring():
        return "fake"

    @classmethod
    def set_password(cls, s, n, v):
        cls.store[(s, n)] = v

    @classmethod
    def get_password(cls, s, n):
        return cls.store.get((s, n))

    @classmethod
    def delete_password(cls, s, n):
        cls.store.pop((s, n), None)


@pytest.fixture(autouse=True)
def kr(monkeypatch, core):
    FakeKeyring.store = {}
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring)
    core.integrations.retry_delays = (0, 0, 0)
    return FakeKeyring


class FakeAPI:
    """REST server: /products (sahifali), /sales, OpenAPI; auth Bearer tekshiriladi."""
    def __init__(self, token="TOKEN-abc-123456"):
        self.token, self.calls, self.fail = token, [], {}
        self.products = [{"id": i, "nomi": f"Mahsulot {i}", "narx": 1000 * i, "tannarx": 700 * i, "qoldiq": i, "updated_at": f"2026-01-0{i}"} for i in range(1, 6)]
        self.sales = [{"chek": f"C{i}", "sana": str(TODAY - timedelta(days=i % 3)), "kod": (i % 5) + 1, "soni": 2, "summa": 2000 * ((i % 5) + 1)} for i in range(12)]

    def __call__(self, method, url, data, headers, timeout):
        self.calls.append((method, url, headers.get("Authorization")))
        if "fail" in self.fail and self.fail["fail"] > 0:
            self.fail["fail"] -= 1
            return 500, "{}"
        if headers.get("Authorization") != f"Bearer {self.token}":
            return 401, '{"error":"unauthorized"}'
        path = url.split("api.shop.test", 1)[1].split("?")[0]
        if path == "/openapi.json":
            return 200, json.dumps({"info": {"title": "Shop API"}, "paths": {"/products": {"get": {"tags": ["Mahsulotlar"]}}, "/sales": {"get": {"tags": ["Savdo"]}},
                                                                            "/products/{id}": {"get": {}}}})
        if path == "/products":
            page = int(url.split("page=")[1].split("&")[0]) if "page=" in url else 1
            return 200, json.dumps({"data": self.products[(page - 1) * 3: page * 3]})
        if path == "/sales":
            return 200, json.dumps(self.sales)
        if path == "/rate":
            return 429, "{}"
        if path == "/forbidden":
            return 403, "{}"
        if path.startswith("/products/") and method == "PATCH":
            return 200, '{"ok": true}'
        return 200 if path == "/" else 404, "{}"


def _rest(core, api, **extra):
    return core.integrations.create(name="Mango Market API", system_type="pos", adapter="rest", store="Mango Market",
                                    config={"base_url": "https://api.shop.test", "auth_type": "bearer",
                                            "entities": {"products": {"path": "/products", "list_key": "data", "page_param": "page", "limit_param": "limit"},
                                                         "sales": {"path": "/sales"}}, **extra},
                                    secrets={"token": api.token})


def test_vault_never_returns_secrets_and_redacts(client, core, monkeypatch):
    api = FakeAPI()
    monkeypatch.setattr(net, "TRANSPORT", api)
    c = _rest(core, api)
    assert c["secrets"] == ["token"] and "TOKEN-abc" not in json.dumps(client.get(f"/api/integrations/{c['id']}").json())
    assert "TOKEN-abc" not in json.dumps(client.get("/api/integrations").json())
    from jarvis.security import redact
    core.vault_value = core.integrations.vault.get(c["id"], "token")
    assert redact("xato: Bearer TOKEN-abc-123456 rad etildi") .count("TOKEN-abc") == 0
    with pytest.raises(Exception):
        core.integrations.vault.set(c["id"], "nomalum_maydon", "x")
    with pytest.raises(IntegrationError, match="maxfiy"):
        core.integrations.create(name="x", system_type="api", adapter="rest", config={"base_url": "https://a.test", "health_path": "/?password=Parol12345!"})
    core.integrations.vault.put_blob(c["id"], "session", b'{"cookies":[{"value":"SESSIONSECRET"}]}')
    from jarvis.config import jarvis_home
    raw = (jarvis_home() / "vault" / f"conn{c['id']}_session.bin").read_bytes()
    assert b"SESSIONSECRET" not in raw and b"SESSIONSECRET" in core.integrations.vault.get_blob(c["id"], "session")
    assert all("TOKEN-abc" not in json.dumps(r) for r in core.audit.recent(100))


def test_rest_auth_errors_and_https_only(core, monkeypatch):
    api = FakeAPI()
    monkeypatch.setattr(net, "TRANSPORT", api)
    with pytest.raises(IntegrationError):
        core.integrations.test(core.integrations.create(name="x", system_type="api", adapter="rest", config={"base_url": "http://evil.test"})["id"])
    c = _rest(core, api)
    assert core.integrations.test(c["id"])["status"] == "connected"
    core.integrations.update(c["id"], secrets={"token": "eskirgan-token-999"})
    with pytest.raises(IntegrationError, match="401"):
        core.integrations.test(c["id"])
    assert core.integrations.get(c["id"])["status"] == "auth_expired"
    core.integrations.update(c["id"], secrets={"token": api.token}, config={"health_path": "/rate"})
    with pytest.raises(IntegrationError, match="429"):
        core.integrations.test(c["id"])
    assert core.integrations.get(c["id"])["status"] == "rate_limited"
    core.integrations.update(c["id"], config={"health_path": "/forbidden"})
    with pytest.raises(IntegrationError):
        core.integrations.test(c["id"])
    assert core.integrations.get(c["id"])["status"] == "permission_denied"


def test_discover_map_sync_incremental_full_and_dupes(core, monkeypatch):
    api = FakeAPI()
    monkeypatch.setattr(net, "TRANSPORT", api)
    c = _rest(core, api)
    d = core.integrations.discover(c["id"])
    assert {"Mahsulotlar", "Savdo"} <= set(d["modules"])
    mp = d["mapping"]
    assert mp["products"]["entity"] == "product" and mp["products"]["fields"]["nomi"] == "name" and mp["products"]["fields"]["tannarx"] == "cost_price"
    assert mp["sales"]["entity"] == "sale" and mp["sales"]["fields"]["summa"] == "amount"
    assert d["learning"]["data_available"]["product"] and "unmapped" in d["learning"]["entities"][0]
    core.integrations.confirm_mapping(c["id"], "products", "product", {"id": "sku", "nomi": "name", "narx": "sale_price", "tannarx": "cost_price", "qoldiq": "stock"})
    core.integrations.confirm_mapping(c["id"], "sales", "sale", {"chek": "receipt_no", "sana": "date", "kod": "sku", "soni": "qty", "summa": "amount"})
    r = core.integrations.sync(c["id"])
    assert r["status"] == "ok" and r["counts"]["products"]["new"] == 5 and r["counts"]["sales"]["new"] == 12
    r2 = core.integrations.sync(c["id"])
    assert r2["counts"]["products"]["new"] == 0                                  # takror yozilmadi
    api.products[0]["narx"] = 1500
    api.products[0]["updated_at"] = "2026-02-01"
    assert core.integrations.sync(c["id"], "full")["counts"]["products"]["changed"] == 1
    api.products.pop()
    assert core.integrations.sync(c["id"], "full")["counts"]["products"]["deleted"] == 1
    st = core.db.one("SELECT cursor FROM sync_state WHERE conn_id=? AND source_entity='products'", (c["id"],))
    assert st["cursor"] == "2026-02-01"
    api.fail["fail"] = 2                                                         # 2 marta 500 → qayta urinish bilan o'tadi
    assert core.integrations.sync(c["id"])["status"] == "ok"
    recs = core.integrations.records(c["id"], "product")
    assert recs[0]["data"]["store"] == "Mango Market" and recs[0]["verification"] == "mapping_confirmed"
    assert core.integrations.sync_history(c["id"])
    assert core.kgraph.search("Mahsulot 1")                                       # Knowledge Graph'ga bog'landi


def test_multi_store_analyst(core, monkeypatch):
    api = FakeAPI()
    monkeypatch.setattr(net, "TRANSPORT", api)
    a = _rest(core, api)
    b = core.integrations.create(name="OAZIS fayl", system_type="pos", adapter="rest", store="OAZIS Supermarket",
                                 config={"base_url": "https://api.shop.test", "auth_type": "bearer", "entities": {"sales": {"path": "/sales"}}},
                                 secrets={"token": api.token})
    for c in (a, b):
        core.integrations.discover(c["id"])
        core.integrations.confirm_mapping(c["id"], "sales", "sale", {"chek": "receipt_no", "sana": "date", "kod": "sku", "soni": "qty", "summa": "amount"})
    core.integrations.confirm_mapping(a["id"], "products", "product", {"id": "sku", "nomi": "name", "narx": "sale_price", "tannarx": "cost_price", "qoldiq": "stock"})
    core.integrations.sync(a["id"])
    core.integrations.sync(b["id"])
    r = core.analyst.answer("Bugun qancha savdo bo'ldi?")
    assert r["handled"] and r["intent"] == "sales"
    assert set(r["data"]["stores"]) == {"Mango Market", "OAZIS Supermarket"}        # do'konlar aralashmadi
    assert r["data"]["total"] == sum(v["amount"] for v in r["data"]["stores"].values())
    assert r["sources"] and r["period"][0] == str(TODAY) and r["method"]
    assert core.analyst.answer("Haftalik eng ko'p sotilgan mahsulotlar")["intent"] == "top"
    p = core.analyst.answer("Bu oy qancha foyda oldik?")
    assert p["data"]["gross_profit"] > 0
    assert any("tannarx yo'q" in x for x in p["limitations"])                    # OAZIS'da mahsulot (tannarx) ma'lumoti yo'q
    n = core.analyst.answer("Bugungi sof foydani hisobla")
    assert "net_profit" not in n["data"] and any("SOF foyda hisoblanmadi" in x for x in n["limitations"])
    ls = core.analyst.answer("Qaysi mahsulot tugab qolayapti?")
    assert ls["intent"] == "low_stock" and all(x["stock"] <= core.settings.low_stock_threshold for x in ls["data"])
    assert core.analyst.answer("Qaysi do'konda savdo pasaygan?")["intent"] == "stores"
    assert core.analyst.answer("Qaysi mahsulotni ko'proq buyurtma qilish kerak?")["intent"] == "reorder"
    assert core.analyst.answer("salom")["handled"] is False


def test_analyst_no_data_does_not_guess(core):
    r = core.analyst.answer("Bugun qancha savdo bo'ldi?")
    assert r["data"] is None and "ma'lumot yo'q" in r["text"] and "Taxmin qilinmadi" in r["limitations"]


def test_odata_1c_and_graphql(core, monkeypatch):
    meta = ('<edmx:Edmx xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx"><edmx:DataServices><Schema xmlns="http://docs.oasis-open.org/odata/ns/edm">'
            '<EntityType Name="Catalog_Номенклатура"><Property Name="Ref_Key"/><Property Name="Description"/><Property Name="Артикул"/></EntityType>'
            '<EntityContainer><EntitySet Name="Catalog_Номенклатура" EntityType="StandardODATA.Catalog_Номенклатура"/></EntityContainer></Schema></edmx:DataServices></edmx:Edmx>')

    def fake(method, url, data, headers, timeout):
        if "$metadata" in url:
            return 200, meta
        if "graphql" in url:
            q = json.loads(data)["query"]
            if "__schema" in q:
                return 200, json.dumps({"data": {"__schema": {"queryType": {"fields": [{"name": "products", "type": {"kind": "LIST", "ofType": {"kind": "OBJECT", "name": "P"}}},
                                                                                       {"name": "me", "type": {"kind": "OBJECT", "name": "U"}}]}}}})
            if "__typename" in q:
                return 200, '{"data":{"__typename":"Query"}}'
            return 200, json.dumps({"data": {"products": [{"id": 1, "name": "Non"}]}})
        return 200, json.dumps({"value": [{"Ref_Key": "a1", "Description": "Non", "Артикул": "N1"}]})
    monkeypatch.setattr(net, "TRANSPORT", fake)
    od = core.integrations.create(name="1C", system_type="erp", adapter="", preset="1c_ut", config={"base_url": "https://1c.test/ut/odata/standard.odata", "entity_sets": ""},
                                  secrets={"username": "admin", "password": "p@ss-1c-xyz"})
    assert od["adapter"] == "odata" and core.integrations.test(od["id"])["status"] == "connected"
    d = core.integrations.discover(od["id"])
    assert d["entities"][0]["name"] == "Catalog_Номенклатура" and "Артикул" in d["entities"][0]["fields"]
    assert d["mapping"]["Catalog_Номенклатура"]["entity"] == "product"
    gq = core.integrations.create(name="GQL", system_type="api", adapter="graphql",
                                  config={"base_url": "https://gql.test/graphql", "auth_type": "none", "queries": {"products": "{ products { id name } }"}})
    gd = core.integrations.discover(gq["id"])
    assert [e["name"] for e in gd["entities"]] == ["products"]
    assert core.integrations.connector(core.integrations.get(gq["id"])).fetch_data("products")["records"][0]["name"] == "Non"


def test_database_sqlite_read_only(core, tmp_path):
    db = tmp_path / "ws" / "pos.db"
    db.parent.mkdir(exist_ok=True)
    core.settings.allowed_read_dirs = [str(tmp_path / "ws")]
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE tovar(id INTEGER PRIMARY KEY, nomi TEXT, narx REAL, qoldiq REAL);"
                      "CREATE TABLE sotuv(id INTEGER PRIMARY KEY, tovar_id INTEGER REFERENCES tovar(id), sana TEXT, soni REAL, summa REAL);"
                      "INSERT INTO tovar VALUES (1,'Non',3000,2),(2,'Sut',9000,40);")
    con.commit()
    con.close()
    c = core.integrations.create(name="Lokal baza", system_type="database", adapter="database", config={"engine": "sqlite", "path": str(db)})
    assert core.integrations.test(c["id"])["status"] == "connected"
    d = core.integrations.discover(c["id"])
    assert {e["name"] for e in d["entities"]} == {"tovar", "sotuv"} and d["discovery"]["relations"]
    conn = core.integrations.connector(core.integrations.get(c["id"]))
    assert conn.query("SELECT nomi FROM tovar WHERE narx > ?", [5000])["rows"] == [{"nomi": "Sut"}]
    for bad in ["UPDATE tovar SET narx=0", "SELECT 1; DROP TABLE tovar", "DELETE FROM tovar", "PRAGMA table_info(tovar)", "ATTACH 'x' AS y"]:
        with pytest.raises(ConnectorError):
            conn.query(bad)
    with pytest.raises(ConnectorError):
        conn.fetch_data('tovar"; DROP TABLE tovar; --')
    assert len(conn.fetch_data("tovar")["records"]) == 2
    raw = sqlite3.connect(f"file:{db}?mode=ro", uri=True)                          # OS darajasidagi himoya ham tekshiriladi
    with pytest.raises(sqlite3.OperationalError):
        raw.execute("DELETE FROM tovar")
    out = core.integrations.create(name="Begona", system_type="database", adapter="database", config={"engine": "sqlite", "path": "/etc/passwd.db"})
    with pytest.raises(IntegrationError, match="ruxsat"):
        core.integrations.test(out["id"])
    pg = core.integrations.create(name="PG", system_type="database", adapter="database", config={"engine": "postgresql", "host": "127.0.0.1"})
    with pytest.raises(IntegrationError, match="drayveri o'rnatilmagan|ulanib bo'lmadi"):
        core.integrations.test(pg["id"])
    assert check_select("SELECT * FROM t WHERE name = 'delete me'")                # literal ichidagi so'z — ruxsat


def test_files_and_desktop(core, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    core.settings.allowed_read_dirs = [str(ws)]
    (ws / "savdo.csv").write_text("Sana;Mahsulot;Soni;Summa\n2026-01-01;Non;2;6000\n", encoding="utf-8")
    (ws / "mijoz.json").write_text(json.dumps([{"mijoz": "Ali", "qarz": 5000}]), encoding="utf-8")
    c = core.integrations.create(name="Eksportlar", system_type="files", adapter="files", config={"path": str(ws)})
    d = core.integrations.discover(c["id"])
    assert {e["name"] for e in d["entities"]} == {"savdo.csv", "mijoz.json"}
    assert d["mapping"]["savdo.csv"]["entity"] == "sale" and d["mapping"]["savdo.csv"]["fields"]["Summa"] == "amount"
    assert core.integrations.connector(core.integrations.get(c["id"])).fetch_data("savdo.csv")["records"][0]["Mahsulot"] == "Non"
    dk = core.integrations.create(name="PC", system_type="desktop", adapter="desktop")
    r = core.integrations.test(dk["id"])
    assert r["status"] in ("connected", "not_supported")
    disc = core.integrations.connector(core.integrations.get(dk["id"])).discover()
    assert "UI Automation bu versiyada yo'q" in disc["note"]


def test_write_requires_mode_and_strong_approval(core, monkeypatch):
    api = FakeAPI()
    monkeypatch.setattr(net, "TRANSPORT", api)
    c = _rest(core, api, write_endpoints={"products.update": {"method": "PATCH", "path": "/products/{id}"}})
    with pytest.raises(IntegrationError, match="Faqat o'qish"):
        core.integrations.request_write(c["id"], "products", "update", {"id": 1, "data": {"nomi": "Yangi"}})
    core.integrations.set_mode(c["id"], "assistant")
    assert core.integrations.request_write(c["id"], "products", "update", {"id": 1, "data": {"nomi": "Yangi"}})["status"] == "draft"
    core.integrations.set_mode(c["id"], "authorized")
    r = core.integrations.request_write(c["id"], "products", "update", {"id": 1, "data": {"nomi": "Yangi"}})
    assert r["approval"]["level"] == "D" and not r["financial"]
    fin = core.integrations.request_write(c["id"], "products", "update", {"id": 1, "data": {"narx": 2000}}, summary="Narx o'zgartirish")
    assert fin["financial"] and fin["approval"]["level"] == "E"
    from jarvis.approval import ApprovalError
    with pytest.raises(ApprovalError):
        core.integrations.execute_write(r["approval"]["id"])                        # tasdiqsiz bajarilmaydi
    core.approvals.decide(r["approval"]["id"], True, r["approval"]["payload_hash"])
    assert core.integrations.execute_write(r["approval"]["id"])["status"] == "executed"
    assert any(m == "PATCH" for m, u, a in api.calls)


def test_monitor_notifies_on_disconnect(core, monkeypatch):
    api = FakeAPI()
    monkeypatch.setattr(net, "TRANSPORT", api)
    c = _rest(core, api)
    core.integrations.test(c["id"])
    api.token = "server-tomonda-almashdi"
    core.db.execute("UPDATE integrations SET last_check='2000-01-01 00:00:00' WHERE id=?", (c["id"],))
    core.integrations.monitor()
    assert core.integrations.get(c["id"])["status"] == "auth_expired"
    assert any(n["category"] == "integration" and "uzildi" in n["title"] for n in core.notifier.list())


def test_detect_protocols(core, monkeypatch):
    def fake(method, url, data, headers, timeout):
        if "panel.test" in url:
            return (200, '<html><form><input type="password"></form></html>') if url.rstrip("/").endswith("panel.test") else (404, "")
        if url.endswith("/openapi.json"):
            return 200, '{"paths": {"/x": {}}}'
        if url.endswith("/graphql"):
            return 200, '{"data":{"__typename":"Query"}}'
        return 404, ""
    monkeypatch.setattr(net, "TRANSPORT", fake)
    r = core.integrations.detect(url="https://api.test")
    assert {c["adapter"] for c in r["candidates"]} >= {"rest", "graphql"} and r["recommended"] in ("rest", "graphql")
    w = core.integrations.detect(url="https://panel.test")
    assert w["recommended"] == "website"
    assert core.integrations.detect(url="http://evil.test")["candidates"] == []


def test_api_flow(client, core, monkeypatch):
    api = FakeAPI()
    monkeypatch.setattr(net, "TRANSPORT", api)
    cat = client.get("/api/integrations/catalog").json()
    assert {"rest", "odata", "graphql", "mcp", "website", "database", "files", "desktop"} <= set(cat["adapters"]) and "yespos" in cat["presets"]
    r = client.post("/api/integrations", json={"name": "Do'kon API", "system_type": "pos", "adapter": "rest", "store": "Mango",
                                               "config": {"base_url": "https://api.shop.test", "auth_type": "bearer", "entities": json.dumps({"sales": {"path": "/sales"}})},
                                               "secrets": {"token": api.token}}).json()
    assert r["secrets"] == ["token"]
    assert client.post(f"/api/integrations/{r['id']}/test").json()["status"] == "connected"
    assert client.post(f"/api/integrations/{r['id']}/discover").json()["mapping"]["sales"]["entity"] == "sale"
    sres = client.post(f"/api/integrations/{r['id']}/sync").json()
    assert sres["status"] == "ok", sres
    assert client.post("/api/analyst/ask", json={"question": "bugun qancha savdo"}).json()["handled"]
    assert client.post(f"/api/integrations/{r['id']}/webhook").status_code == 403
    core.integrations.vault.set(r["id"], "webhook_secret", "hook-secret-777")
    assert client.post(f"/api/integrations/{r['id']}/webhook", headers={"X-JARVIS-Token": "hook-secret-777"}).json()["status"] == "ok"
    assert client.delete(f"/api/integrations/{r['id']}").json()["deleted"] == r["id"]
    assert not core.db.one("SELECT 1 FROM ext_records WHERE conn_id=?", (r["id"],))


# ---------------- MCP ----------------
def test_mcp_connector_tools_resources(core, monkeypatch):
    from jarvis import instagram_mcp as m

    def fake(url, body, headers, timeout):
        msg = json.loads(body)
        meth = msg["method"]
        if meth == "notifications/initialized":
            return 202, {}, ""
        res = {"initialize": {"protocolVersion": m.PROTOCOL, "serverInfo": {"name": "crm-mcp", "version": "2"}, "capabilities": {"tools": {}, "resources": {}}},
               "tools/list": {"tools": [{"name": "list_clients", "annotations": {"readOnlyHint": True}}, {"name": "delete_client"}]},
               "resources/list": {"resources": [{"uri": "crm://stats"}]},
               "tools/call": {"structuredContent": {"clients": [{"id": 1, "name": "Ali", "debt": 5000}]}}}.get(meth, {})
        return 200, {"content-type": "application/json", "mcp-session-id": "s1"}, json.dumps({"jsonrpc": "2.0", "id": msg.get("id"), "result": res})
    monkeypatch.setattr(m, "TRANSPORT", fake)
    c = core.integrations.create(name="CRM MCP", system_type="mcp", adapter="mcp", config={"base_url": "https://crm.test/mcp"}, secrets={"mcp_token": "mcp-tok-123"})
    assert "crm-mcp" in core.integrations.test(c["id"])["status_note"]
    d = core.integrations.discover(c["id"])
    ents = {e["name"]: e for e in d["entities"]}
    assert ents["list_clients"]["readable"] and not ents["delete_client"]["readable"] and "crm://stats" in ents
    conn = core.integrations.connector(core.integrations.get(c["id"]))
    r = conn.fetch_data("list_clients")
    assert r["untrusted"] and r["records"][0]["name"] == "Ali"
    with pytest.raises(ConnectorError):
        conn.fetch_data("delete_client")


# ---------------- Website (Playwright, lokal soxta sayt) ----------------
LOGIN = '<html><body><form method="post" action="/login"><input name="login" type="text"><input name="parol" type="password"><button type="submit">Kirish</button></form></body></html>'


def _site(variant="ok"):
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, html, cookie=None, code=200, loc=None):
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            if loc:
                self.send_header("Location", loc)
            self.end_headers()
            self.wfile.write(html.encode())

        def authed(self):
            return "sess=ok" in (self.headers.get("Cookie") or "")

        def do_GET(self):
            if self.path.startswith("/logout"):
                return self._send("logged out", cookie="sess=; Max-Age=0")
            if not self.authed():
                return self._send(LOGIN)
            if self.path.startswith("/reports"):
                return self._send("<html><head><title>Hisobotlar</title></head><body><table><tr><th>Sana</th><th>Mahsulot</th><th>Soni</th><th>Summa</th></tr>"
                                  f"<tr><td>{TODAY}</td><td>Non</td><td>3</td><td>9 000</td></tr><tr><td>{TODAY}</td><td>Sut</td><td>1</td><td>12 000</td></tr></table></body></html>")
            return self._send('<html><head><title>Bosh sahifa</title></head><body><nav><a href="/reports">Hisobotlar</a><a href="/logout">Chiqish</a></nav></body></html>')

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n).decode()
            if variant == "captcha":
                return self._send('<html><body><div class="g-recaptcha" data-sitekey="x"></div>' + LOGIN + "</body></html>")
            if variant == "mfa":
                return self._send('<html><body>SMS kod kiriting<input name="otp" autocomplete="one-time-code"></body></html>', cookie="sess=half")
            if "login=admin" in body and "parol=togri-parol" in body:
                return self._send("", cookie="sess=ok; Path=/", code=302, loc="/")
            return self._send(LOGIN)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


@pytest.fixture
def chromium(monkeypatch):
    pytest.importorskip("playwright.sync_api")
    import glob
    import os
    exe = os.environ.get("JARVIS_CHROMIUM_PATH") or next(iter(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome")), None)
    if exe:
        monkeypatch.setenv("JARVIS_CHROMIUM_PATH", exe)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            p.chromium.launch(**({"executable_path": exe} if exe else {})).close()
    except Exception as e:
        pytest.skip(f"Chromium yo'q: {str(e).splitlines()[0]}")


def test_website_login_discover_fetch(core, chromium):
    from jarvis.integrations.website import WebsiteConnector
    WebsiteConnector.delay = 0
    srv, url = _site()
    try:
        c = core.integrations.create(name="POS panel", system_type="pos", adapter="website", store="Mango",
                                     config={"base_url": url}, secrets={"username": "admin", "password": "xato-parol-555"})
        with pytest.raises(IntegrationError, match="noto'g'ri"):
            core.integrations.test(c["id"])
        assert core.integrations.get(c["id"])["status"] == "auth_failed"
        core.integrations.update(c["id"], secrets={"password": "togri-parol"})
        assert core.integrations.test(c["id"])["status"] == "connected"
        assert core.integrations.vault.get_blob(c["id"], "session")                   # sessiya shifrlangan holda saqlandi
        d = core.integrations.discover(c["id"])
        assert "Hisobotlar" in d["modules"] and d["entities"][0]["fields"] == ["Sana", "Mahsulot", "Soni", "Summa"]
        assert not any("logout" in p["url"] for p in d["discovery"]["pages"])        # chiqish havolasi bosilmadi
        assert d["mapping"][d["entities"][0]["name"]]["entity"] == "sale"
        r = core.integrations.sync(c["id"])
        assert r["status"] == "ok" and core.analyst.answer("bugun qancha savdo")["data"]["total"] == 21000
    finally:
        srv.shutdown()


@pytest.mark.parametrize("variant,word", [("captcha", "CAPTCHA"), ("mfa", "MFA")])
def test_website_captcha_mfa_not_bypassed(core, chromium, variant, word):
    srv, url = _site(variant)
    try:
        c = core.integrations.create(name="Panel", system_type="website", adapter="website", config={"base_url": url},
                                     secrets={"username": "admin", "password": "togri-parol"})
        with pytest.raises(IntegrationError, match=word):
            core.integrations.test(c["id"])
        assert core.integrations.get(c["id"])["status"] == "user_action_required"
    finally:
        srv.shutdown()


def test_brain_core_chat_routes_business_questions(core, monkeypatch):
    api = FakeAPI()
    monkeypatch.setattr(net, "TRANSPORT", api)
    c = _rest(core, api)
    core.integrations.discover(c["id"])
    core.integrations.sync(c["id"])
    r = core.chat("JARVIS, bugun do'konlar savdosi qanday?")
    assert "Savdo" in r["text"] and "Manba: Mango Market API" in r["text"]
    steps = [s["step"] for s in r["brain"]["trace"]]
    assert steps == ["tushunish", "xotira", "vosita", "ruxsat", "bajarish", "tekshirish", "javob"]
    assert "ulanish" in core.chat("Qaysi tizim bilan aloqa uzildi?")["text"].lower()
    st = core.brain_core.status()
    assert "Brain Core" in st["architecture"] and any(a["key"] == "business_analyst" for a in st["agents"])


def test_task_routes_respect_privacy(core):
    core.settings.ai_providers = [{"id": "local", "kind": "ollama", "model": "m", "tier": "light"},
                                  {"id": "claude", "kind": "anthropic", "model": "c", "tier": "strong"}]
    core.settings.ai_task_routes = {"code": "claude"}
    p = core.ai.plan([{"role": "user", "content": "funksiya yoz"}], purpose="code")
    assert p["candidates"][0]["id"] == "claude" and p["task_route"] == "claude"
    p2 = core.ai.plan([{"role": "user", "content": "parolim: Qwerty12345 shu kodni tuzat"}], purpose="code")
    assert p2["candidates"][0]["id"] == "local" and "maxfiylik" in p2["task_route"]
