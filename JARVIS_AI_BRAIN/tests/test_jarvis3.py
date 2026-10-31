"""JARVIS 3.0: xavfsizlik tuzatishlari, avtonomlik darajalari, Digital Twin, Proactive, Guardian, Asset Manager, Simulation Lab,
Office, Knowledge Researcher, Business prognoz, Creative imkoniyatlari, Skills Factory, qurilmalar. Tashqi tizimlar — mock."""
import json
import sqlite3
from datetime import date, timedelta

import pytest

from jarvis.approval import ApprovalError
from jarvis.mission import MissionError
from jarvis.plugins import PluginError
from jarvis.simlab import SimError


def _fake(core, agent, result):
    core.agents.agents[agent].handler = lambda p: result


# ---------------- Phase A ----------------
def test_emergency_stop_pauses_running_missions(core):
    _fake(core, "file_analysis", {"files": []})
    m = core.missions.create("fayllarni ko'rsat keyin test", use_ai=False)
    core.db.execute("UPDATE missions SET status='running', started_at=datetime('now') WHERE id=?", (m["id"],))
    msg = core.stop_automation("test")
    assert "1 ta missiya" in msg and core.missions.get(m["id"])["status"] == "paused"
    with pytest.raises(MissionError):
        core.missions.start(m["id"])                                         # global pauza paytida boshlanmaydi
    core.resume_automation()
    m2 = core.missions.create("fayllarni ko'rsat", use_ai=False)
    core.automation_paused = True
    assert core.missions._stop_check(m2["id"])() and "favqulodda" in core.missions._stop_check(m2["id"])()
    core.automation_paused = False


def test_approval_expiry(core):
    a = core.approvals.request(action_type="shell_command", target="pc", level="C", payload={"command": "mkdir x"}, summary="mkdir", requested_by="t")
    core.db.execute("UPDATE approvals SET created_at=datetime('now','-100 hours') WHERE id=?", (a["id"],))
    with pytest.raises(ApprovalError, match="muddati"):
        core.approvals.decide(a["id"], True, a["payload_hash"])
    assert core.approvals.get(a["id"])["status"] == "expired"
    b = core.approvals.request(action_type="shell_command", target="pc", level="C", payload={"command": "mkdir y"}, summary="mkdir", requested_by="t")
    core.approvals.decide(b["id"], True, b["payload_hash"])
    core.db.execute("UPDATE approvals SET decided_at=? WHERE id=?", ("2020-01-01T00:00:00+00:00", b["id"]))
    with pytest.raises(ApprovalError, match="muddati"):
        core.approvals.authorize_execution(b["id"], {"command": "mkdir y"})
    assert "approval_ttl_hours" in __import__("jarvis.config", fromlist=["LOCKED_KEYS"]).LOCKED_KEYS


# ---------------- Autonomy Levels ----------------
@pytest.mark.parametrize("level,low,medium,high", [(0, False, False, False), (1, False, False, False), (2, True, False, False),
                                                   (3, True, True, False), (4, True, True, False)])
def test_autonomy_levels_auto_start(core, level, low, medium, high):
    core.settings.autonomy_level = level
    ms = core.missions
    assert ms.may_auto_start([{"risk": "LOW"}]) is low
    assert ms.may_auto_start([{"risk": "LOW"}, {"risk": "MEDIUM"}]) is medium
    assert ms.may_auto_start([{"risk": "HIGH"}]) is high and ms.may_auto_start([{"risk": "CRITICAL"}]) is False


def test_level0_advice_only_and_level4_resume(core):
    _fake(core, "file_analysis", {"files": []})
    core.settings.autonomy_level = 0
    m = core.missions.create("fayllarni ko'rsat", use_ai=False, auto_start=True)
    assert m["status"] == "pending"
    with pytest.raises(MissionError, match="Level|darajasi 0"):
        core.missions.start(m["id"])
    core.settings.autonomy_level = 2
    core.db.execute("UPDATE missions SET status='running', started_at=datetime('now') WHERE id=?", (m["id"],))
    core.missions.recover(resume=True)
    assert core.missions.get(m["id"])["status"] == "paused"                 # Level 2 — o'zi davom etmaydi
    core.settings.autonomy_level = 4
    core.db.execute("UPDATE missions SET status='running' WHERE id=?", (m["id"],))
    core.missions.recover(resume=True)
    assert core.missions.wait(m["id"], 10)["status"] == "completed"


def test_connector_schedule_respects_autonomy(core, monkeypatch):
    core.settings.autonomy_level = 1
    called = []
    monkeypatch.setattr(core.integrations, "sync", lambda *a, **k: called.append(a) or {})
    core.db.execute("INSERT INTO integrations(name, system_type, adapter, config, status, sync_interval_min, enabled) VALUES ('x','files','files','{}','connected',1,1)")
    monkeypatch.setattr(core.integrations, "_status", lambda *a, **k: None)
    core.integrations.monitor()
    assert not called                                                     # Level 1 — jadval bo'yicha sinxronlash yo'q
    core.settings.autonomy_level = 2
    core.integrations.monitor()
    assert called                                                         # Level 2 — xavfsiz o'qish sinxronlashi ishlaydi


# ---------------- Digital Twin ----------------
def test_digital_twin_profile_only_approved_and_suggestions(core):
    core.memory.add("Javoblar o'zbek tilida va qisqa bo'lsin", "preference", source="user")
    core.memory.add("JARVIS AI BRAIN loyihasi", "project", source="user", title="JARVIS")
    core.memory.add("Model o'ylashicha foydalanuvchi kech uxlaydi", "semantic", source="ai_router")     # model xulosasi — profilga kirmaydi
    prof = core.twin.profile()
    assert prof["sections"]["preferences"]["items"] and prof["sections"]["projects"]["items"]
    assert not any("kech uxlaydi" in i["content"] for s in prof["sections"].values() for i in s["items"])
    for _ in range(3):
        core.missions.create("hisobotni ko'rsat va tahlil qil", use_ai=False)
    sug = core.twin.suggestions()
    assert any(s["kind"] == "repeat" for s in sug) and any(s["kind"] == "focus" for s in sug)
    pid = prof["sections"]["preferences"]["items"][0]["id"]
    core.twin.edit(pid, "Javoblar o'zbek tilida, batafsil")
    assert core.memory.get(pid)["content"].endswith("batafsil")
    core.twin.delete(pid)
    assert not core.twin.profile()["sections"]["preferences"]["items"]


# ---------------- Proactive + Guardian ----------------
def test_proactive_scan_notify_once_and_reports(core):
    m = core.missions.create("fayllarni ko'rsat", use_ai=False, due_at="2020-01-01 00:00:00")
    core.db.execute("UPDATE missions SET status='paused' WHERE id=?", (m["id"],))
    a = core.approvals.request(action_type="shell_command", target="pc", level="C", payload={"command": "mkdir z"}, summary="mkdir z", requested_by="t")
    core.db.execute("UPDATE approvals SET created_at=datetime('now','-65 hours') WHERE id=?", (a["id"],))
    keys = {i["key"] for i in core.proactive.scan()}
    assert f"overdue:{m['id']}" in keys and f"mission:{m['id']}:paused" in keys and f"approval_exp:{a['id']}" in keys
    first = core.proactive.notify_new()
    assert first and not core.proactive.notify_new()                       # bir kunda bir marta
    from datetime import datetime, timezone
    r = core.proactive.tick(datetime(2026, 11, 2, 9, tzinfo=timezone.utc))   # dushanba — kunlik + haftalik
    assert set(r["reports"]) == {"daily", "weekly"} and core.proactive.tick(datetime(2026, 11, 2, 10, tzinfo=timezone.utc))["reports"] == []
    rep = core.proactive.reports()[0]["report"]
    assert "Savdo ma'lumoti yo'q" in rep["sales"]
    n = core.db.one("SELECT COUNT(*) n FROM notifications WHERE category='proactive'")["n"]
    assert n >= 3


def test_guardian_status_and_safe_actions(core):
    st = core.guardian.status()
    keys = {c["key"] for c in st["checks"]}
    assert {"ram", "disk", "db", "ai", "cost", "backup", "errors", "security", "automation"} <= keys
    assert "ok" in core.guardian.run("db_quick_check")["result"]
    core.guardian.run("emergency_stop")
    assert core.automation_paused
    core.guardian.run("resume_automation")
    assert not core.automation_paused
    with pytest.raises(ValueError):
        core.guardian.run("delete_everything")
    assert core.db.one("SELECT COUNT(*) n FROM guardian_events")["n"] == 3


# ---------------- Asset Manager ----------------
def test_asset_manager_index_search_duplicates_backup(core, tmp_path):
    ws = tmp_path / "workspace"
    (ws / "docs").mkdir()
    (ws / "docs" / "hisobot.txt").write_text("Oylik savdo hisoboti: Chilonzor do'koni", encoding="utf-8")
    (ws / "docs" / "nusxa.txt").write_text("Oylik savdo hisoboti: Chilonzor do'koni", encoding="utf-8")
    (ws / ".env").write_text("API_KEY=x", encoding="utf-8")
    (ws / "secret.txt").write_text("password = sk-" + "a" * 40, encoding="utf-8")
    (ws / "rasm.png").write_bytes(b"\x89PNG....")
    st = core.assets.index()
    assert st["new"] == 4 and st["skipped"] >= 1
    hits = core.assets.search("chilonzor")
    assert {h["name"] for h in hits} == {"hisobot.txt", "nusxa.txt"}
    secret = core.db.one("SELECT snippet FROM file_index WHERE name='secret.txt'")
    assert secret["snippet"] is None                                      # maxfiy matn indeksga yozilmadi
    d = core.assets.duplicates()
    assert d["groups"][0]["count"] == 2 and "o'chirilmaydi" in d["note"]
    assert core.assets.stats()["total"] == 4
    b = core.assets.backup(str(ws / "docs" / "hisobot.txt"))
    assert (ws / "docs" / "hisobot.txt").exists() and b["size"] > 0
    (ws / "docs" / "nusxa.txt").unlink()
    assert core.assets.index()["removed"] == 1


# ---------------- Simulation Lab ----------------
def test_simlab_sql_on_copy_never_touches_production(core, tmp_path):
    core.memory.add("Sinov xotirasi", "long_term", source="user")
    before = core.db.one("SELECT COUNT(*) n FROM memories")["n"]
    r = core.simlab.sql("jarvis", ["DELETE FROM memories", "UPDATE settings_nope SET x=1"])
    mem = next(d for d in r["diff"] if d["table"] == "memories")
    assert mem["before"] == before and mem["after"] == 0 and mem["deleted"] == before
    assert r["status"] == "errors" and not r["results"][1]["ok"] and r["production_changed"] is False
    assert core.db.one("SELECT COUNT(*) n FROM memories")["n"] == before
    with pytest.raises(SimError):
        core.simlab.sql("jarvis", ["ATTACH DATABASE '/tmp/x.db' AS x"])
    db = tmp_path / "workspace" / "pos.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT, price REAL)")
        c.execute("INSERT INTO products(name, price) VALUES ('Non', 3000)")
    conn = core.integrations.create(name="POS baza", system_type="database", adapter="database", config={"engine": "sqlite", "path": str(db)})
    r = core.simlab.sql(f"conn:{conn['id']}", ["UPDATE products SET price=3500 WHERE name='Non'"])
    p = next(d for d in r["diff"] if d["table"] == "products")
    assert p["updated"] == 1 and p["examples"][0]["after"]["price"] == 3500
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT price FROM products").fetchone()[0] == 3000


def test_simlab_write_preview_and_mission_dry_run(core):
    conn = core.integrations.create(name="CRM", system_type="crm", adapter="rest", config={"base_url": "https://crm.example.uz"}, mode="authorized")
    core.db.execute("INSERT INTO ext_records(conn_id, source_entity, source_id, entity, data, raw, hash, retrieved_at, first_seen) "
                    "VALUES (?, 'products', '7', 'product', '{}', ?, 'h', datetime('now'), datetime('now'))", (conn["id"], json.dumps({"id": 7, "price": 3000})))
    r = core.simlab.write_preview(conn["id"], "products", "update", {"price": 3500}, record_id="7")
    assert r["changed"] == {"price": {"before": 3000, "after": 3500}} and r["required_approval"].startswith("E")
    assert not core.approvals.list("pending")                              # hech qanday tasdiq/so'rov yaratilmadi
    d = core.simlab.mission("fayllarni ko'rsat keyin papkada bajar `mkdir x`")
    assert d["approvals_needed"] == ["s2_1"] and d["would_auto_start"] is False and not core.missions.list()
    assert len(core.simlab.history()) == 2


# ---------------- Office, Researcher, Business, Creative ----------------
def test_office_rooms_and_collaboration(core):
    _fake(core, "file_analysis", {"files": []})
    _fake(core, "qa", {"health": "ok"})
    m = core.missions.start(core.missions.create("fayllarni ko'rsat keyin test", use_ai=False)["id"], background=False)
    assert m["status"] == "completed"
    rooms = {r["key"]: r for r in core.office.rooms()}
    assert rooms["file_analysis"]["tasks_done"] == 1
    room = core.office.room("qa")
    assert room["mission_steps"][0]["mission_id"] == m["id"] and room["conversation"]
    assert core.office.collaborations()[0]["agents"] == ["file_analysis", "qa"]


def test_knowledge_researcher_compares_and_saves_with_approval(core, monkeypatch):
    core.settings.internet_enabled = True
    pages = {"https://a.uz/x": "Toshkent metrosi 1977 yilda ochilgan. Metro bekatlari chiroyli.",
             "https://b.com/y": "Toshkent metrosi 1977 yil noyabrda ochilgan bekatlari bilan mashhur.",
             "https://c.org/z": "Metro haqida: 1977 yilda ochilgan, Toshkent bekatlari."}
    monkeypatch.setattr(core.research, "search", lambda q, limit=6: [{"url": u, "title": u, "snippet": ""} for u in pages])
    monkeypatch.setattr(core.research, "fetch", lambda u, max_chars=20000: {"url": u, "title": u, "text": pages[u], "fetched_at": "2026-10-30",
                                                                            "reliability": 0.6, "reliability_note": "", "injection_flags": []})
    r = core.researcher.investigate("Toshkent metrosi qachon ochilgan?")
    assert r["agreement"]["independent_domains"] == 3 and r["agreement"]["confidence"] == "yuqori" and "bekatlari" in r["agreement"]["shared_terms"]
    assert not core.memory.list("knowledge")
    out = core.researcher.decide(r["finding_id"], True)
    mem = core.memory.get(out["memory_id"])
    assert mem["kind"] == "knowledge" and "https://a.uz/x" in mem["reference"]


def test_business_forecast_needs_data_then_works(core, tmp_path):
    assert core.business.forecast()["forecast"] == [] and "14 kunlik" in core.business.forecast()["note"]
    conn = core.integrations.create(name="POS", system_type="pos", adapter="files", config={"path": str(tmp_path / "workspace")})
    today = date.today()
    for i in range(30):
        d = today - timedelta(days=29 - i)
        amt = 1000 + 10 * i + (5000 if i == 25 else 0)
        core.db.execute("INSERT INTO ext_records(conn_id, source_entity, source_id, entity, data, raw, hash, retrieved_at, first_seen) "
                        "VALUES (?, 'sales', ?, 'sale', ?, '{}', 'h', datetime('now'), datetime('now'))", (conn["id"], str(i), json.dumps({"date": str(d), "amount": amt})))
    f = core.business.forecast(7)
    assert len(f["forecast"]) == 7 and f["trend_per_day"] > 0 and "TAXMIN" in f["note"]
    an = core.business.anomalies()["anomalies"]
    assert any(a["kind"] == "keskin o'sish" for a in an)
    assert "today" in core.business.overview()["answers"]


def test_creative_capabilities_are_honest(core):
    caps = core.creative.capabilities()["services"]
    video = next(s for s in caps if s["service"].startswith("Bulut video"))
    assert video["status"] in ("not_connected", "model_only") and "adapter" in video["note"]
    assert any(s["status"] == "not_implemented" for s in caps)


# ---------------- Skills Factory ----------------
def test_skill_scaffold_test_enable_version_rollback(core):
    p = core.plugins.scaffold("matn_hisob", "Matndagi so'zlarni sanaydi")
    assert p["status"] == "disabled" and p["created_by"] == "template"
    t = core.plugins.test("matn_hisob")
    assert t["passed"], t
    appr = core.plugins.request_enable("matn_hisob")
    core.approvals.decide(appr["id"], True, appr["payload_hash"])
    core.plugins.enable("matn_hisob", appr["id"])
    assert core.plugins.run("matn_hisob", {"text": "bir ikki uch"})["result"]["words"] == 3
    v1 = core.plugins.versions("matn_hisob")
    assert len(v1) == 1 and v1[0]["current"]
    path = core.plugins._row("matn_hisob")["path"]
    with open(f"{path}/main.py", "a", encoding="utf-8") as f:
        f.write("\n# o'zgartirildi\n")
    core.plugins.discover()
    assert core.plugins._row("matn_hisob")["status"] == "untrusted"
    r = core.plugins.rollback("matn_hisob", v1[0]["id"])
    assert r["status"] == "disabled" and r["hash"] == v1[0]["hash"]
    with pytest.raises(PluginError):
        core.plugins.scaffold("matn_hisob", "takror")
    with pytest.raises(PluginError):
        core.plugins.scaffold("Bad Name", "x")


def test_skill_with_dangerous_code_fails_test(core):
    core.plugins.scaffold("xavfli", "sinov")
    path = core.plugins._row("xavfli")["path"]
    with open(f"{path}/main.py", "w", encoding="utf-8") as f:
        f.write("import subprocess\n\ndef run(input, ctx):\n    subprocess.run('rm -rf /', shell=True)\n    return {'result': 1}\n")
    core.plugins.discover()
    t = core.plugins.test("xavfli")
    assert not t["passed"] and t["findings"]
    with pytest.raises(PluginError):
        core.plugins.request_enable("xavfli")


# ---------------- API + devices ----------------
def test_jarvis3_api(client, core):
    for path in ("/api/twin", "/api/proactive", "/api/guardian", "/api/assets", "/api/office/rooms", "/api/business/forecast",
                 "/api/creative/capabilities", "/api/simlab/history", "/api/researcher/findings", "/api/devices"):
        r = client.get(path)
        assert r.status_code == 200, (path, r.text)
    assert client.post("/api/guardian/rm_rf").status_code == 400
    assert client.post("/api/settings", json={"autonomy_level": 7}).status_code == 400
    assert client.post("/api/settings", json={"autonomy_level": 3}).status_code == 200 and core.settings.autonomy_level == 3
    assert client.post("/api/settings", json={"approval_ttl_hours": 9999}).json().get("approval_ttl_hours", 72) == 72    # qulflangan
    r = client.post("/api/simlab/sql", json={"target": "jarvis", "statements": ["DELETE FROM audit_log"]})
    assert r.status_code == 200 and r.json()["production_changed"] is False
    assert client.post("/api/skills", json={"name": "api_skill", "description": "API orqali"}).status_code == 200
    assert client.post("/api/skills/api_skill/test").json()["passed"]
    assert client.post("/api/devices/nope/revoke").status_code == 404
    from jarvis import __version__
    assert client.get("/api/auth/status").json()["version"] == __version__     # JARVIS.exe eski serverni shu orqali aniqlaydi


def test_device_sessions_list_and_revoke(core):
    tok = core.auth._new_session("192.168.1.20")
    s = core.auth.sessions(tok)
    assert s[0]["client"] == "192.168.1.20" and s[0]["current"] and not s[0]["local"] and tok not in json.dumps(s)
    assert core.auth.revoke(s[0]["id"]) and not core.auth.check(tok)
