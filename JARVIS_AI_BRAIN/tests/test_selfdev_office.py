"""Self-Dev (o'zini rivojlantirish) va Jonli ofis: g'oya → AI patch → worktree testi → (xato bo'lsa qayta) → qabul → merge →
kuzatuv → muammo bo'lsa avtomatik qaytarish. Haqiqiy git repo (vaqtinchalik), soxta AI."""
import shutil
import subprocess
from datetime import datetime

import pytest

from jarvis.improve import ALWAYS_PROTECTED, Improver, ImproveError


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git yo'q")
    r = tmp_path / "repo"
    (r / "jarvis").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / "jarvis" / "__init__.py").write_text("")
    (r / "jarvis" / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (r / "tests" / "test_calc.py").write_text("from jarvis.calc import add\n\ndef test_add():\n    assert add(2, 2) == 4\n")
    (r / "conftest.py").write_text("import sys, os\nsys.path.insert(0, os.path.dirname(__file__))\n")
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(g + ["init", "-q", "-b", "main"], cwd=r, check=True)
    subprocess.run(g + ["add", "-A"], cwd=r, check=True)
    subprocess.run(g + ["commit", "-qm", "init"], cwd=r, check=True)
    return r

BAD = "```diff\n--- /dev/null\n+++ b/jarvis/mul.py\n@@ -0,0 +1,2 @@\n+def mul(a, b):\n+    return a * b\n```"
GOOD = ("```diff\n--- a/jarvis/calc.py\n+++ b/jarvis/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
        "--- /dev/null\n+++ b/tests/test_add2.py\n@@ -0,0 +1,4 @@\n+from jarvis.calc import add\n+\n+def test_add2():\n+    assert add(1, 2) == 3\n```")


class AI:
    name = "ollama"

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def route(self, messages, purpose="", private=None, allow_paid=False):
        self.calls.append(messages[-1]["content"])
        return {"text": self.replies.pop(0), "route": {"provider": "fake", "model": "f"}}

    def status(self):
        return [{"id": "fake", "kind": "ollama", "available": True}]

    def available(self):
        return True, "fake"


def test_selfdev_develop_retry_accept_watch_revert(core, repo, monkeypatch):
    core.improver = Improver(core, project_root=repo)
    core.ai = AI(["[]", BAD, "[]", GOOD])
    sd = core.selfdev
    idea = sd.request("Qo'shish funksiyasi noto'g'ri ishlaydi — tuzat va test qo'sh")
    assert idea["status"] == "new" and sd.status()["ready"]
    r = sd.develop(idea["id"], background=False)
    assert r["status"] == "ready" and r["attempts"] == 2, r["note"]          # 1-urinish testdan o'tmadi → xatoni o'qib qayta yozdi
    assert "Oldingi urinish testdan o'tmadi" in core.ai.calls[2] or "Oldingi urinish testdan o'tmadi" in core.ai.calls[3]
    assert "a - b" in (repo / "jarvis" / "calc.py").read_text()                         # asosiy kod hali o'zgarmagan
    assert r["proposal"]["files"] == ["jarvis/calc.py", "tests/test_add2.py"]
    with pytest.raises(Exception, match="confirm"):
        sd.accept(idea["id"])
    res = sd.accept(idea["id"], confirm=True)
    assert res["merge"]["status"] == "merged" and "a + b" in (repo / "jarvis" / "calc.py").read_text()
    assert res["restart"]["restarting"] is False                              # testda qayta ishga tushmaydi
    assert sd.watch_tick()["watching"]
    for _ in range(12):                                                       # yangi versiyada xatolar keskin ko'paydi
        core.audit.error("demo", "yangi versiya xatosi")
    w = sd.watch_tick()
    assert w["reverted"] and "a - b" in (repo / "jarvis" / "calc.py").read_text()        # o'zi orqaga qaytardi
    assert sd.get(idea["id"])["status"] == "reverted"
    log = subprocess.run(["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True).stdout
    assert "Revert" in log                                                    # tarix saqlangan (git revert)


def test_selfdev_guards_and_collect(core, repo):
    assert {"jarvis/selfdev.py", "jarvis/improve.py", "jarvis/approval.py", "jarvis/policy.py"} <= ALWAYS_PROTECTED
    core.improver = Improver(core, project_root=repo)
    core.ai = AI([BAD.replace("jarvis/mul.py", "jarvis/selfdev.py")])
    with pytest.raises(ImproveError, match="Himoyalangan"):
        core.improver.feature_request("o'zingni rivojlantirish qoidasini o'zgartir", files=["jarvis/calc.py"])
    core.selfdev.log_agent_run("video montaj qilib ber", "Kechirasiz, buni qila olmayman — vosita yo'q", [])
    c = core.selfdev.collect()
    assert c["added"] >= 1 and any("video montaj" in i["title"] for i in c["ideas"])
    assert core.selfdev.collect()["added"] == 0                               # takror qo'shilmaydi
    with pytest.raises(Exception, match="tayyor"):
        core.selfdev.accept(c["ideas"][0]["id"], confirm=True)                 # tayyor bo'lmagan g'oya qabul qilinmaydi


def test_office_staff_routines_tick(core, client):
    o = client.get("/api/office/live").json()
    assert len(o["staff"]) == 8 and {s["key"] for s in o["staff"]} >= {"hisobchi", "smm", "dasturchi", "qorovul"}
    assert len(o["routines"]) == 6 and all(r["enabled"] for r in o["routines"])
    sent = []
    core.notifier.notify = lambda title, body="", **kw: sent.append(title)
    done = core.office_live.tick(now=datetime(2026, 11, 2, 9, 5))
    titles = {d["title"]: d["status"] for d in done}
    assert titles["Ertalabki hisobot"] == "ok" and "☀ Ertalabki hisobot" in sent
    assert titles["POS'dan yangi ma'lumot olish"] == "skipped"                # ulanish yo'q — halol "bajariladigan narsa yo'q"
    assert not any(d["title"] == "Ertalabki hisobot" for d in core.office_live.tick(now=datetime(2026, 11, 2, 9, 6)))   # kuniga bir marta
    core.automation_paused = True
    assert core.office_live.tick(now=datetime(2026, 11, 3, 9, 5)) == []      # favqulodda to'xtatish
    core.automation_paused = False
    assert client.post("/api/office/routines", json={"role": "smm", "prompt": "har kuni post g'oyasi", "schedule": "har kuni"}).status_code == 400
    r = client.post("/api/office/routines", json={"role": "smm", "title": "Post g'oyasi", "prompt": "Bugungi post g'oyasini tayyorla", "schedule": "daily:10:00"})
    assert r.status_code == 200
    run = client.post(f"/api/office/routines/{r.json()['id']}/run").json()
    assert run["status"] == "skipped"                                          # AI yo'q — agent ishi bajarilmaydi, yolg'on natija yo'q
    feed = client.get("/api/office/feed").json()
    assert any(f["role"] == "tahlilchi" for f in feed)
    a = client.post("/api/office/ask", json={"role": "hisobchi", "text": "salom"}).json()
    assert a["role"] == "hisobchi" and "AI modeli ulanmagan" in a["note"]
    msg = core.chat("o'zingni rivojlantir: Excel fayldan grafik chizib bera oladigan bo'l")
    assert msg["intent"] == "selfdev" and core.selfdev.list()[0]["source"] == "chat"
