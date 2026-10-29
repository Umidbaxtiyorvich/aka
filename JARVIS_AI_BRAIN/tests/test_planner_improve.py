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
