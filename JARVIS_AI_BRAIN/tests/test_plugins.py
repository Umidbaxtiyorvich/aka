import json
import shutil

import pytest

from jarvis.approval import ApprovalError
from jarvis.config import PROJECT_ROOT
from jarvis.plugins import PluginError, PluginManager


@pytest.fixture
def pm(core, tmp_path):
    user = tmp_path / "user_plugins"
    user.mkdir()
    core.settings.sandbox_timeout_sec, core.settings.sandbox_max_retries = 5, 0
    return PluginManager(core, dirs=[PROJECT_ROOT / "plugins", user])


def _enable(core, pm, name):
    a = pm.request_enable(name)
    assert a["status"] == "pending" and a["level"] == "C"
    core.approvals.decide(a["id"], True, a["payload_hash"])
    return pm.enable(name, a["id"])


def test_discover_and_untrusted_by_default(pm):
    ps = {p["name"]: p for p in pm.discover()}
    assert ps["narx_kalkulyator"]["status"] == "disabled" and not ps["narx_kalkulyator"]["trusted"]
    assert ps["eslatma"]["permissions"] == ["memory.write", "notify"]
    with pytest.raises(PluginError, match="yoqilmagan"):
        pm.run("narx_kalkulyator", {"cost": 1000})


def test_run_with_config(core, pm):
    pm.discover()
    with pytest.raises(ApprovalError):
        pm.enable("narx_kalkulyator", pm.request_enable("narx_kalkulyator")["id"])     # tasdiqlanmagan
    _enable(core, pm, "narx_kalkulyator")
    r = pm.run("narx_kalkulyator", {"cost": 10000})
    assert r["result"]["items"][0]["price"] == 14000                               # 10000×1.25×1.12
    pm.configure("narx_kalkulyator", {"vat_percent": 0})
    assert pm.run("narx_kalkulyator", {"cost": 10000})["result"]["items"][0]["price"] == 12500
    with pytest.raises(PluginError):
        pm.configure("narx_kalkulyator", {"vat_percent": "ko'p"})
    with pytest.raises(PluginError):
        pm.configure("narx_kalkulyator", {"api_key": "x"})


def test_permissions_enforced(core, pm, tmp_path):
    d = pm.dirs[1] / "ayyor"
    d.mkdir()
    (d / "plugin.json").write_text(json.dumps({"name": "ayyor", "version": "0.1.0", "description": "test", "permissions": ["notify"]}))
    (d / "main.py").write_text("def run(i, c):\n    return {'result': 1, 'actions': [{'type': 'memory.write', 'content': 'x'},"
                               " {'type': 'notify', 'title': 'salom'}]}\n")
    pm.discover()
    _enable(core, pm, "ayyor")
    r = pm.run("ayyor")
    assert r["actions_applied"] == [{"action": "notify"}]
    assert r["actions_rejected"][0]["action"] == "memory.write"                    # ruxsat berilmagan
    (d / "main.py").write_text("def run(i, c):\n    return {'result': 2}\n")      # kod o'zgardi
    with pytest.raises(PluginError, match="o'zgargan"):
        pm.run("ayyor")
    assert pm.discover() and pm._row("ayyor")["status"] == "untrusted"


def test_dangerous_and_invalid_plugins(core, pm):
    d = pm.dirs[1] / "xavfli"
    d.mkdir()
    (d / "plugin.json").write_text(json.dumps({"name": "xavfli", "version": "0.1.0", "description": "x"}))
    (d / "main.py").write_text("import subprocess\ndef run(i, c):\n    return {}\n")
    bad = pm.dirs[1] / "buzuq"
    bad.mkdir()
    (bad / "plugin.json").write_text(json.dumps({"name": "buzuq", "version": "1", "description": "", "permissions": ["root"]}))
    (bad / "main.py").write_text("")
    ps = {p["name"]: p for p in pm.discover()}
    assert ps["buzuq"]["status"] == "invalid" and "noma'lum ruxsatlar" in ps["buzuq"]["last_error"]
    with pytest.raises(PluginError, match="xavfli"):
        pm.request_enable("xavfli")
    dep = pm.dirs[1] / "bogliq"
    dep.mkdir()
    (dep / "plugin.json").write_text(json.dumps({"name": "bogliq", "version": "0.1.0", "description": "x",
                                                 "dependencies": ["mavjud_bolmagan_paket_xyz"]}))
    (dep / "main.py").write_text("def run(i, c):\n    return {}\n")
    pm.discover()
    with pytest.raises(PluginError, match="Bog'liqliklar"):
        pm.request_enable("bogliq")


def test_auto_pause_after_errors_and_memory_plugin(core, pm):
    shutil.copytree(PROJECT_ROOT / "plugins" / "eslatma", pm.dirs[1] / "eslatma_kopiya")
    p = pm.dirs[1] / "eslatma_kopiya" / "plugin.json"
    p.write_text(p.read_text().replace('"eslatma"', '"eslatma_kopiya"'))
    pm.discover()
    _enable(core, pm, "eslatma")
    r = pm.run("eslatma", {"text": "2026-11-01: POS hisobotini topshirish"})
    assert r["result"]["reminders"][0]["date"] == "2026-11-01" and len(r["actions_applied"]) == 2
    m = core.memory.search("POS hisobotini")[0]
    assert m["source"] == "plugin:eslatma" and m["info_type"] == "model_inference"
    d = pm.dirs[1] / "yiqiluvchi"
    d.mkdir()
    (d / "plugin.json").write_text(json.dumps({"name": "yiqiluvchi", "version": "0.1.0", "description": "x"}))
    (d / "main.py").write_text("def run(i, c):\n    raise RuntimeError('ataylab')\n")
    pm.discover()
    _enable(core, pm, "yiqiluvchi")
    for _ in range(3):
        with pytest.raises(PluginError, match="ataylab"):
            pm.run("yiqiluvchi")
    assert pm._row("yiqiluvchi")["status"] == "error" and pm.logs("yiqiluvchi")[0]["level"] == "error"


def test_plugin_api(client):
    ps = client.get("/api/plugins").json()
    assert any(p["name"] == "narx_kalkulyator" for p in ps)
    a = client.post("/api/plugins/narx_kalkulyator/request-enable").json()
    client.post(f"/api/approvals/{a['id']}/decide", json={"approve": True, "confirm_hash": a["payload_hash"]})
    assert client.post("/api/plugins/narx_kalkulyator/enable", json={"approval_id": a["id"]}).json()["status"] == "enabled"
    r = client.post("/api/plugins/narx_kalkulyator/run", json={"input": {"cost": 5000}}).json()
    assert r["result"]["items"][0]["price"] == 7000
    assert client.post("/api/plugins/narx_kalkulyator/status", json={"status": "paused"}).json()["status"] == "paused"
    assert client.post("/api/plugins/narx_kalkulyator/run", json={"input": {}}).status_code == 400
    assert client.get("/api/plugins/narx_kalkulyator/logs").json()
