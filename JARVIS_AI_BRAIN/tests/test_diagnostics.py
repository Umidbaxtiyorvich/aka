import json

from jarvis import net
from jarvis.diagnostics import categorize


def test_categorize():
    assert categorize("Tarmoq xatosi: connection refused") == "network"
    assert categorize("Ruxsat berilmagan joy") == "permission"
    assert categorize("Ollama bilan bog'lanib bo'lmadi") in ("ai", "network")
    assert categorize("sqlite3.OperationalError: database is locked") == "database"
    assert categorize("bir narsa") == "other"


def test_unknown_is_not_healthy(core, monkeypatch):
    monkeypatch.setenv("JARVIS_TELEGRAM_BOT_TOKEN", "123456:" + "T" * 35)
    core.settings.telegram_allowed_ids = [1]
    core.settings.internet_enabled = True

    def down(*a):
        raise net.NetError("Tarmoq xatosi: connection refused")
    monkeypatch.setattr(net, "TRANSPORT", down)
    d = core.diagnostics.run(external=True)
    comp = {c["name"]: c for c in d["components"]}
    assert comp["telegram"]["status"] == "unknown" and "tekshirib bo'lmadi" in comp["telegram"]["detail"]
    assert comp["internet"]["status"] == "unknown"
    assert comp["database"]["status"] == "ok" and comp["backend"]["status"] == "ok"
    assert comp["instagram"]["status"] == "not_configured"
    assert comp["backup"]["status"] == "warning"                 # hali nusxa yo'q
    assert d["overall"] == "degraded"


def test_external_api_error_vs_unknown(core, monkeypatch):
    monkeypatch.setenv("JARVIS_TELEGRAM_BOT_TOKEN", "123456:" + "T" * 35)
    core.settings.telegram_allowed_ids = [1]
    monkeypatch.setattr(net, "TRANSPORT", lambda *a: (401, json.dumps({"ok": False, "description": "Unauthorized"})))
    assert core.diagnostics.telegram()["status"] == "error"


def test_diagnostics_api_and_redacted_export(client, core):
    client.get("/api/status")
    client.get("/api/status")
    core.audit.error("telegram_agent", "Telegram API xatosi: token=SuperSecretValue123")
    d = client.get("/api/diagnostics", params={"external": False}).json()
    assert any(r["route"] == "GET /api/status" and r["count"] == 2 for r in d["responses"])
    assert any(c["name"] == "external_services" and c["status"] == "unknown" for c in d["components"])
    assert d["errors"]["by_category"]
    exp = client.get("/api/diagnostics/export", params={"external": False})
    assert "attachment" in exp.headers["content-disposition"] and "SuperSecretValue123" not in exp.text
    js = {c["name"]: c for c in d["components"]}["frontend_js_syntax"]
    assert js["status"] in ("ok", "unknown")
