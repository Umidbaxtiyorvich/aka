import os

import pytest

from jarvis.approval import ApprovalError
from jarvis.sandbox import static_check


@pytest.fixture
def sb(core):
    core.settings.sandbox_timeout_sec, core.settings.sandbox_max_retries = 3, 0
    return core.sandbox


def _approved(core, sb, code, **kw):
    r = sb.run_python(code, **kw)
    assert r["status"] == "needs_approval" and r["approval"]["level"] == "E"
    a = r["approval"]
    core.approvals.decide(a["id"], True, a["payload_hash"])
    return sb.run_python(code, approval_id=a["id"], **kw)


def test_static_check():
    assert not [f for f in static_check("print(1+1)") if f["severity"] == "block"]
    assert any(f["severity"] == "block" for f in static_check("import subprocess"))
    assert any(f["severity"] == "block" for f in static_check("eval('1')"))
    assert any(f["severity"] == "block" for f in static_check("open('/etc/passwd')"))
    assert any(f["severity"] == "block" for f in static_check("import urllib.request"))
    assert not any(f["severity"] == "block" for f in static_check("import urllib.request", allow_network=True))
    assert static_check("def f(:")[0]["msg"].startswith("Sintaksis")


def test_safe_code_runs_and_is_recorded(core, sb):
    r = sb.run_python("print(sum(range(10)))\nopen('chiqish.txt', 'w').write('ok')")
    assert r["status"] == "ok" and r["stdout"].strip() == "45" and r["created_files"] == ["chiqish.txt"]
    assert sb.history()[0]["id"] == r["id"] and r["limits"]["network"] is False


def test_runtime_blocks_even_after_approval(core, sb, tmp_path):
    outside = tmp_path / "tashqi.txt"
    r = _approved(core, sb, f"open({str(outside)!r}, 'w').write('x')")
    assert r["status"] == "error" and "taqiqlangan" in r["stderr"] and not outside.exists()
    r = _approved(core, sb, "import os\nos.system('echo salom')")
    assert "os.system" in r["stderr"]
    r = sb.run_python("import importlib\nimportlib.import_module('sub' + 'process').run(['echo', 'x'])")
    assert r["status"] == "error" and "subprocess.Popen" in r["stderr"]          # statikdan o'tsa ham runtime ushlaydi
    r = _approved(core, sb, "import socket\nsocket.create_connection(('1.1.1.1', 80), timeout=2)")
    assert "tarmoq" in r["stderr"]


def test_limits(core, sb, monkeypatch):
    assert sb.run_python("while True:\n    pass")["status"] in ("timeout", "cpu_limit")
    core.settings.sandbox_memory_mb = 200
    r = sb.run_python("import time\nx = bytearray(400 * 1024 * 1024)\ntime.sleep(2)")
    assert r["status"] == "memory_limit"
    monkeypatch.setenv("JARVIS_FAKE_API_KEY", "secret-value-123")
    r = sb.run_python("import os\nprint(os.environ.get('JARVIS_FAKE_API_KEY'))")
    assert r["stdout"].strip() == "None"


def test_unapproved_unsafe_not_run(core, sb):
    r = sb.run_python("import subprocess")
    assert r["status"] == "needs_approval"
    with pytest.raises(ApprovalError):
        sb.run_python("import subprocess", approval_id=r["approval"]["id"])        # hali tasdiqlanmagan
    with pytest.raises(ApprovalError):
        sb.run_python("import subprocess\nprint(2)", approval_id=r["approval"]["id"])   # boshqa kod — xesh mos emas


def test_run_command_policy(core, sb):
    r = sb.run_command("echo salom")
    assert r["status"] == "ok" and "salom" in r["stdout"] and "tarmoq cheklanmagan" in r["isolation"]
    with pytest.raises(ApprovalError):
        sb.run_command("curl http://example.com")
    with pytest.raises(ApprovalError):
        sb.run_command("mkdir x")
    info = sb.isolation_info()
    assert "OS izolyatsiyasi emas" in info["level"] and info["not_guaranteed"]
    assert os.path.isdir(sb.base)


def test_sandbox_api(client):
    assert client.get("/api/sandbox").json()["isolation"]["backend"] == "process"
    assert client.post("/api/sandbox/python", json={"code": "print(7*6)"}).json()["stdout"].strip() == "42"
    assert client.post("/api/sandbox/python", json={"code": "import ctypes"}).json()["status"] == "needs_approval"
    assert client.post("/api/sandbox/command", json={"text": "format c:"}).status_code == 400
