"""Self-healing: xato imzolari, takrorlanish, alohida nusxadagi testlar, kvota va 'hech narsa o'zi qo'llanmaydi'."""
import shutil
import subprocess

import pytest

from jarvis.improve import Improver
from jarvis.selfheal import DAILY_PROPOSALS, signature


def test_signature_normalizes_variable_parts():
    a = signature("pos", "Timeout 30s on /home/u/data/file1.csv id=deadbeef12")
    b = signature("pos", "Timeout 45s on C:\\Users\\x\\file2.csv id=abcdef9912")
    assert a == b and signature("bi", "boshqa xato") != a


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git yo'q")
    r = tmp_path / "repo"
    (r / "tests").mkdir(parents=True)
    (r / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (r / "tests" / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(2, 2) == 4\n")
    (r / "conftest.py").write_text("import sys, os\nsys.path.insert(0, os.path.dirname(__file__))\n")
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(g + ["init", "-q", "-b", "main"], cwd=r, check=True)
    subprocess.run(g + ["add", "-A"], cwd=r, check=True)
    subprocess.run(g + ["commit", "-qm", "init"], cwd=r, check=True)
    return r


class FakeAI:
    name, model = "ollama", "fake"

    def __init__(self):
        self.calls = 0

    def status(self):
        return []

    def route(self, messages, purpose="", private=None):
        self.calls += 1
        assert "REGRESSIYA TESTI" in messages[0]["content"]
        diff = ("--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a + b\n+    return int(a) + int(b)\n"
                "--- /dev/null\n+++ b/tests/test_regress_add.py\n@@ -0,0 +1,4 @@\n+from calc import add\n+\n+def test_str():\n+    assert add('2', 2) == 4\n")
        return {"text": f"```diff\n{diff}```", "route": {"provider": "fake", "model": "f"}}


def test_run_groups_recurring_and_runs_tests_isolated(core, repo, monkeypatch):
    core.improver = Improver(core, project_root=repo)
    for i in range(4):
        core.audit.error("calc", f"TypeError: unsupported operand on row {i}")
    core.audit.error("bi", "bir martalik")
    r = core.selfheal.run(run_tests=True)
    rec = r["recurring"]
    assert len(rec) == 1 and rec[0]["module"] == "calc" and rec[0]["count"] == 4
    assert r["tests"]["ran"] and r["tests"]["passed"] and r["git"]["ok"] and r["proposal"] is None
    assert (repo / "calc.py").read_text() == "def add(a, b):\n    return a + b\n"         # asosiy papka o'zgarmadi
    assert any(n["type"] == "test_run" for n in core.kgraph.search("passed"))
    assert core.selfheal.history()[0]["overall"]


def test_propose_respects_ai_quota_and_never_applies(core, repo, monkeypatch):
    core.improver = Improver(core, project_root=repo)
    (repo / "jarvis").mkdir()
    (repo / "jarvis" / "calc.py").write_text("x = 1\n")
    for i in range(3):
        core.audit.error("calc", f"TypeError: unsupported operand on row {i}")
    monkeypatch.setattr(type(core.ai), "name", property(lambda self: "offline"))
    assert "AI modeli ulanmagan" in core.selfheal.run(propose=True)["proposal"]["note"]
    monkeypatch.undo()
    fake = FakeAI()
    monkeypatch.setattr(core.improver.core, "ai", fake)
    p = core.selfheal.run(propose=True)["proposal"]
    assert p["created"] and p["has_regression_test"]
    prop = core.improver.get(p["created"])
    assert prop["status"] == "proposed" and prop["has_test"]                                # faqat taklif
    # Bir imzo uchun 24 soatda bitta
    assert core.selfheal.run(propose=True)["proposal"]["created"] is None and fake.calls == 1
    core.db.execute("UPDATE selfheal_proposals SET signature='boshqa'")
    for _ in range(DAILY_PROPOSALS):
        core.db.execute("INSERT INTO selfheal_proposals(signature) VALUES ('x')")
    assert "Kunlik limit" in core.selfheal.run(propose=True)["proposal"]["note"]


def test_selfheal_api(client):
    r = client.post("/api/selfheal/run").json()
    assert "overall" in r and r["tests"] is None and "avtomatik qo'llanmadi" in r["note"]
    assert client.get("/api/selfheal/history").json()
