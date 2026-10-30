import shutil
import subprocess
import sys

import pytest

from jarvis.improve import ImproveError, Improver, diff_paths
from jarvis.planner import split_goal


def test_split_and_plan_run(core):
    assert split_goal("1. testlarni tekshir 2. fayllarni ko'rsat") == ["testlarni tekshir", "fayllarni ko'rsat"]
    plan = core.planner.create("testlarni tekshir keyin fayllarni ko'rsat keyin bajar `mkdir yangi`")
    assert [s["agent"] for s in plan["steps"]] == ["qa", "file_analysis", "computer"]
    done = core.planner.run(plan["id"])
    assert done["status"] == "waiting_approval"                     # tasdiqsiz davom etmaydi
    assert [s["status"] for s in done["steps"]] == ["done", "done", "waiting_approval"]


DIFF_OK = """--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""
DIFF_BAD = DIFF_OK.replace("calc.py", "jarvis/security.py")


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git yo'q")
    r = tmp_path / "repo"
    r.mkdir()
    (r / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (r / "tests").mkdir()
    (r / "tests" / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(2, 2) == 4\n")
    (r / "conftest.py").write_text("import sys, os\nsys.path.insert(0, os.path.dirname(__file__))\n")
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(g + ["init", "-q", "-b", "main"], cwd=r, check=True)
    subprocess.run(g + ["add", "-A"], cwd=r, check=True)
    subprocess.run(g + ["commit", "-qm", "init"], cwd=r, check=True)
    return r


def test_improve_flow(core, repo):
    imp = Improver(core, project_root=repo)
    with pytest.raises(ImproveError, match="Himoyalangan"):
        imp.create("xavfli", DIFF_BAD)
    prop = imp.create("add tuzatish", DIFF_OK)
    assert imp.test(prop["id"])["status"] == "tested_pass"
    assert "return a - b" in (repo / "calc.py").read_text()        # asosiy papka o'zgarmadi
    appr = imp.request_apply(prop["id"])
    from jarvis.approval import ApprovalError
    with pytest.raises(ApprovalError):
        imp.apply(prop["id"])
    core.approvals.decide(appr["id"], True, appr["payload_hash"])
    res = imp.apply(prop["id"])
    assert res["branch"] == f"jarvis/proposal-{prop['id']}"
    shown = subprocess.run(["git", "show", f"{res['branch']}:calc.py"], cwd=repo, capture_output=True, text=True).stdout
    assert "a + b" in shown and "return a - b" in (repo / "calc.py").read_text()
    assert imp.rollback(prop["id"])["status"] == "rolled_back"


def test_improve_failing_patch(core, repo):
    imp = Improver(core, project_root=repo)
    bad = DIFF_OK.replace("+    return a + b", "+    return a * b + 1")
    assert imp.test(imp.create("buzuq", bad)["id"])["status"] == "tested_fail"
    assert diff_paths(DIFF_OK) == {"calc.py"}
    assert sys.executable


def _approve(core, appr):
    core.approvals.decide(appr["id"], True, appr["payload_hash"])


def _git_out(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True).stdout


def test_merge_and_revert(core, repo):
    imp = Improver(core, project_root=repo)
    pid = imp.create("add tuzatish", DIFF_OK)["id"]
    imp.test(pid)
    _approve(core, imp.request_apply(pid))
    imp.apply(pid)
    with pytest.raises(ImproveError, match="tasdiq so'ralmagan"):
        imp.merge(pid)
    appr = imp.request_merge(pid)
    assert appr["level"] == "E" and "calc.py" in appr["summary"]
    from jarvis.approval import ApprovalError
    with pytest.raises(ApprovalError):
        imp.merge(pid)                                     # hali tasdiqlanmagan
    _approve(core, appr)
    res = imp.merge(pid)
    assert res["status"] == "merged" and "a + b" in (repo / "calc.py").read_text()
    assert _git_out(repo, "rev-parse", "HEAD").strip() == res["merge_commit"]
    with pytest.raises(ImproveError, match="allaqachon"):
        imp.merge(pid)                                     # takroriy merge yo'q
    assert any("asosiy versiyada" in n["title"] for n in core.notifier.list())
    assert imp.revert_merge(pid)["status"] == "reverted"
    assert "return a - b" in (repo / "calc.py").read_text()
    assert "Revert" in _git_out(repo, "log", "-1", "--format=%s")
    assert imp.git_status()["ok"] and imp.git_status()["branch"] == "main"


def test_merge_guards(core, repo):
    imp = Improver(core, project_root=repo)
    pid = imp.create("add tuzatish", DIFF_OK)["id"]
    imp.test(pid)
    _approve(core, imp.request_apply(pid))
    imp.apply(pid)
    appr = imp.request_merge(pid)
    _approve(core, appr)
    # Tasdiqdan keyin asosiy branch o'zgardi → payload boshqa → tasdiq bekor
    (repo / "other.py").write_text("x = 1\n")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "other.py"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "boshqa"], cwd=repo, check=True)
    from jarvis.approval import ApprovalError
    with pytest.raises(ApprovalError, match="o'zgargan"):
        imp.merge(pid)
    # Saqlanmagan o'zgarish bo'lsa merge qilinmaydi
    _approve(core, imp.request_merge(pid))
    (repo / "other.py").write_text("x = 2\n")
    with pytest.raises(ImproveError, match="saqlanmagan"):
        imp.merge(pid)
    subprocess.run(["git", "checkout", "other.py"], cwd=repo, check=True)
    # Branch'ga taklifdan tashqari fayl qo'shilsa — rad
    br = f"jarvis/proposal-{pid}"
    subprocess.run(["git", "switch", "-q", br], cwd=repo, check=True)
    (repo / "yashirin.py").write_text("y = 1\n")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "yashirin.py"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], cwd=repo, check=True)
    subprocess.run(["git", "switch", "-q", "main"], cwd=repo, check=True)
    with pytest.raises(ImproveError, match="tashqari"):
        imp.merge(pid)
    assert "return a - b" in (repo / "calc.py").read_text()


def test_merge_retests_combined_version(core, repo):
    imp = Improver(core, project_root=repo)
    pid = imp.create("add tuzatish", DIFF_OK)["id"]
    imp.test(pid)
    _approve(core, imp.request_apply(pid))
    imp.apply(pid)
    # Asosiy versiyada yangi test paydo bo'ldi, u taklif bilan birga yiqiladi
    (repo / "tests" / "test_new.py").write_text("from calc import add\n\ndef test_sub():\n    assert add(5, 3) == 2\n")
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(g + ["add", "-A"], cwd=repo, check=True)
    subprocess.run(g + ["commit", "-qm", "yangi test"], cwd=repo, check=True)
    head = _git_out(repo, "rev-parse", "HEAD")
    _approve(core, imp.request_merge(pid))
    with pytest.raises(ImproveError, match="testdan o'tmadi"):
        imp.merge(pid)
    assert _git_out(repo, "rev-parse", "HEAD") == head and imp.get(pid)["status"] == "applied"


def test_feature_request(core, repo, monkeypatch):
    class AI:
        name = "ollama"

        def __init__(self, replies):
            self.replies, self.calls = list(replies), []

        def route(self, messages, purpose="", private=None):
            self.calls.append(messages[0]["content"])
            return {"text": self.replies.pop(0), "route": {"provider": "fake", "model": "f"}}
    (repo / "jarvis").mkdir()
    (repo / "jarvis" / "bi.py").write_text("def top():\n    return []\n")
    diff = ("```diff\n--- /dev/null\n+++ b/jarvis/top10.py\n@@ -0,0 +1,2 @@\n+def top10(rows):\n+    return rows[:10]\n"
            "--- /dev/null\n+++ b/tests/test_top10.py\n@@ -0,0 +1,2 @@\n+def test_x():\n+    assert True\n```")
    imp = Improver(core, project_root=repo)
    core.ai = AI(['["jarvis/bi.py", "jarvis/security.py"]', diff])
    p = imp.feature_request("Eng ko'p sotilgan 10 ta mahsulotni ko'rsat")
    assert p["source"] == "feature" and p["status"] == "proposed" and p["files"] == ["jarvis/top10.py", "tests/test_top10.py"]
    assert "def top():" in core.ai.calls[1] and "<untrusted>" in core.ai.calls[1]
    with pytest.raises(ImproveError, match="batafsil"):
        imp.feature_request("qil")
    core.ai = AI([diff.replace("jarvis/top10.py", "jarvis/security.py")])
    with pytest.raises(ImproveError, match="Himoyalangan"):
        imp.feature_request("xavfsizlikni o'chirib qo'y iltimos", files=["jarvis/bi.py"])
    core.ai = AI([diff.replace("jarvis/top10.py", "setup.py")])
    with pytest.raises(ImproveError, match="ruxsat etilmagan"):
        imp.feature_request("setup faylini o'zgartir iltimos", files=["jarvis/bi.py"])
    core.ai.name = "offline"
    with pytest.raises(ImproveError, match="ulanmagan"):
        imp.feature_request("Eng ko'p sotilgan 10 ta mahsulotni ko'rsat")
