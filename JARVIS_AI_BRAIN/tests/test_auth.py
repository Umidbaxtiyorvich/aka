import json

import pytest
from fastapi.testclient import TestClient

from jarvis.api import create_app
from jarvis.auth import AuthError, validate_pin


@pytest.fixture
def secured(core):
    core.settings.auth_enabled = True
    return TestClient(create_app(core))


def test_pin_rules():
    for bad in ("12345", "123456", "111111", "234567", "987654"):
        with pytest.raises(AuthError):
            validate_pin(bad)
    validate_pin("7391-qora-olma")


def test_api_requires_session(secured, core):
    r = secured.get("/api/status")
    assert r.status_code == 401 and r.json() == {"detail": "auth_required", "pin_set": False}
    assert secured.get("/").status_code == 200 and secured.get("/static/app.js").status_code == 200
    assert secured.post("/api/auth/setup", json={"pin": "123456"}).status_code == 400
    r = secured.post("/api/auth/setup", json={"pin": "jarvis-2026-uz"})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    assert secured.get("/api/status").status_code == 200
    assert secured.post("/api/auth/setup", json={"pin": "boshqa-pin-99"}).status_code == 409   # qayta o'rnatib bo'lmaydi
    stored = json.loads(core.auth.path.read_text())
    assert "jarvis-2026-uz" not in json.dumps(stored) and len(stored["hash"]) == 64
    secured.post("/api/auth/logout")
    assert secured.get("/api/status").status_code == 401


def test_lockout_and_change(secured, core):
    secured.post("/api/auth/setup", json={"pin": "jarvis-2026-uz"})
    secured.post("/api/auth/logout")
    for _ in range(5):
        assert secured.post("/api/auth/login", json={"pin": "notogri-pin"}).status_code == 401
    r = secured.post("/api/auth/login", json={"pin": "jarvis-2026-uz"})
    assert r.status_code == 429                                            # to'g'ri PIN ham bloklangan
    assert any(n["category"] == "security" for n in core.notifier.list())
    core.auth._fails.clear()
    assert secured.post("/api/auth/login", json={"pin": "jarvis-2026-uz"}).status_code == 200
    other = TestClient(create_app(core))
    other.post("/api/auth/login", json={"pin": "jarvis-2026-uz"})
    assert other.get("/api/status").status_code == 200
    assert secured.post("/api/auth/change", json={"current": "jarvis-2026-uz", "new": "yangi-pin-4821"}).status_code == 200
    assert other.get("/api/status").status_code == 401                     # boshqa sessiyalar bekor bo'ldi
    assert secured.get("/api/status").status_code == 200


def test_host_and_origin_protection(core):
    c = TestClient(create_app(core))
    assert c.get("/api/status", headers={"host": "evil.example.com"}).status_code == 400       # DNS rebinding
    r = c.post("/api/memory", json={"content": "x"}, headers={"origin": "https://evil.example.com"})
    assert r.status_code == 403
    assert c.post("/api/memory", json={"content": "lokal"}, headers={"origin": "http://127.0.0.1:8765"}).status_code == 200


def test_setup_only_from_localhost(core):
    with pytest.raises(AuthError, match="shu kompyuter"):
        core.auth.setup("jarvis-2026-uz", "192.168.1.50")
