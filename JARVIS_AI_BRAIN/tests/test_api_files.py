def test_status_and_chat(client):
    s = client.get("/api/status").json()
    assert s["ai"]["provider"] == "offline" and s["settings"]["read_only_mode"]
    assert any(a["key"] == "manager" and a["implemented"] for a in s["agents"])
    assert client.post("/api/chat", json={"text": "yordam"}).json()["intent"] == "help"
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_memory_api(client):
    r = client.post("/api/memory", json={"content": "Loyiha: JARVIS", "kind": "project", "project": "jarvis"})
    mid = r.json()["id"]
    assert client.get("/api/memory?q=JARVIS").json()
    assert client.post("/api/memory", json={"content": "token=abcdefgh123"}).status_code == 400
    assert client.delete(f"/api/memory/{mid}").status_code == 200


def test_settings_cannot_change_security(client):
    r = client.post("/api/settings", json={"ai_provider": "offline", "read_only_mode": False})
    assert r.status_code == 200 and r.json()["read_only_mode"] is True
    assert client.post("/api/settings", json={"ai_provider": "paid_cloud"}).status_code == 400


def test_files_scope(client, core, tmp_path):
    ws = core.settings.allowed_read_dirs[0]
    open(f"{ws}/savdo.csv", "w").write("nom,miqdor\nnon,5\nsut,3\n")
    r = client.get("/api/files/read", params={"path": f"{ws}/savdo.csv"}).json()
    assert r["analysis"]["rows"] == 2
    assert client.get("/api/files/read", params={"path": "/etc/passwd"}).status_code == 400
    open(f"{ws}/.env", "w").write("X=1")
    assert client.get("/api/files/read", params={"path": f"{ws}/.env"}).status_code == 400


def test_approval_api_requires_hash(client):
    r = client.post("/api/computer/propose", json={"command": "mkdir x"}).json()
    aid = r["approval"]["id"]
    assert client.post(f"/api/approvals/{aid}/decide", json={"approve": True, "confirm_hash": "x"}).status_code == 400
    assert client.post(f"/api/approvals/{aid}/execute").status_code == 400
