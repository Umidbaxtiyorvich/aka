import sys

import pytest

from jarvis.approval import ApprovalError


def test_app_launch_requires_allowlist_and_approval(core, tmp_path):
    core.settings.app_allowlist = {"test_ilova": [sys.executable, "-c", "import time; time.sleep(0.2)"]}
    with pytest.raises(ApprovalError, match="ro'yxatida yo'q"):
        core.computer.propose_app("cmd")
    with pytest.raises(ApprovalError, match="papkada emas"):
        core.computer.propose_app("test_ilova", file=str(tmp_path / "boshqa.txt"))
    r = core.computer.propose_app("test_ilova")
    a = r["approval"]
    assert a["status"] == "pending" and a["risk"] == "medium"
    with pytest.raises(ApprovalError):
        core.computer.launch_app(a["id"])
    core.approvals.decide(a["id"], True, a["payload_hash"])
    out = core.computer.launch_app(a["id"])
    assert out["pid"] > 0
    with pytest.raises(ApprovalError, match="allaqachon"):
        core.computer.launch_app(a["id"])                     # bir tasdiq — bir marta


def test_app_with_allowed_file(core):
    ws = core.settings.allowed_read_dirs[0]
    open(f"{ws}/eslatma.txt", "w").write("salom")
    core.settings.app_allowlist = {"ochuvchi": [sys.executable, "-c", "pass"]}
    a = core.computer.propose_app("ochuvchi", file=f"{ws}/eslatma.txt")["approval"]
    assert a["payload"]["argv"][-1].endswith("eslatma.txt")
