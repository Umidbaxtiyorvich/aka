"""Tool Registry (default deny, agent chegarasi, sxema, timeout, retry, limit, audit) va Command Center (qidiruv, buyruqlar)."""
import time

import pytest

from jarvis.tools import Tool, ToolError


def test_catalog_schema_and_safety_rule(core):
    cat = {t["id"]: t for t in core.tools.catalog()}
    assert {"memory.search", "files.read", "analyst.ask", "computer.propose_command", "integration.propose_write"} <= set(cat)
    assert all(t["level"] in "AB" or t["approval"] for t in cat.values())       # C–E faqat tasdiq orqali
    with pytest.raises(ToolError, match="tasdiq"):
        core.tools.register(Tool("x.delete", "o'chir", "", "E", {}, "", lambda a: None, agents=["user"]))
    assert [t["id"] for t in core.tools.catalog("research")] and all("research" in t["agents"] for t in core.tools.catalog("research"))


def test_invoke_validates_and_logs_without_secrets(core):
    core.memory.add("Ombor shanba kuni yopiq", "knowledge", source="user")
    r = core.tools.invoke("memory.search", {"query": "ombor"})
    assert r["status"] == "ok" and r["result"] and r["result"][0]["content"].startswith("Ombor")
    with pytest.raises(ToolError, match="majburiy"):
        core.tools.invoke("memory.search", {})
    with pytest.raises(ToolError, match="Noma'lum argument"):
        core.tools.invoke("memory.search", {"query": "x", "rm": True})
    with pytest.raises(ToolError, match="turi"):
        core.tools.invoke("business.forecast", {"days": "ko'p"})
    with pytest.raises(ToolError, match="topilmadi"):
        core.tools.invoke("shell.rm_rf", {})
    secret = "sk-" + "z" * 40
    with pytest.raises(ToolError):
        core.tools.invoke("memory.propose", {"content": f"kalit {secret}"})
    calls = core.tools.calls()
    assert calls[0]["status"] in ("error", "denied") and secret not in str(calls)
    assert {c["status"] for c in calls} >= {"ok", "denied"}


def test_agent_permissions_default_deny_and_ceiling(core):
    with pytest.raises(ToolError, match="chaqira olmaydi"):
        core.tools.invoke("files.read", {"path": "x"}, caller="instagram")
    core.agents.agents["computer"].permission = "B"                     # chegarani pasaytiramiz
    with pytest.raises(ToolError, match="chegarasi"):
        core.tools.invoke("computer.propose_command", {"command": "mkdir a"}, caller="computer")
    core.agents.agents["computer"].permission = "E"
    r = core.tools.invoke("computer.propose_command", {"command": "mkdir a"}, caller="computer")
    assert r["status"] == "approval_requested" and r["result"]["approval"]["status"] == "pending"
    assert not (core.settings.allowed_write_dirs and __import__("os").path.exists(core.settings.allowed_write_dirs[0] + "/a"))   # bajarilmagan


def test_autonomy_level0_and_emergency_stop_limit_tools(core):
    core.settings.autonomy_level = 0
    assert core.tools.invoke("guardian.status", {})["status"] == "ok"            # A — ruxsat
    with pytest.raises(ToolError, match="Level 0"):
        core.tools.invoke("mission.create", {"goal": "fayllarni ko'rsat"})
    core.settings.autonomy_level = 2
    core.automation_paused = True
    with pytest.raises(ToolError, match="Favqulodda"):
        core.tools.invoke("memory.propose", {"content": "yangi bilim"}, caller="memory_agent")
    core.automation_paused = False


def test_timeout_retry_and_rate_limit(core):
    calls = []

    def flaky(a):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("vaqtinchalik")
        return {"ok": True}
    core.tools.register(Tool("t.flaky", "flaky", "", "A", {}, "", flaky, agents=["user"]))
    r = core.tools.invoke("t.flaky", {})
    assert r["status"] == "ok" and r["attempts"] == 2
    once = []
    core.tools.register(Tool("t.once", "once", "", "B", {}, "", lambda a: once.append(1) or (_ for _ in ()).throw(RuntimeError("x")),
                             agents=["user"], idempotent=False))
    with pytest.raises(ToolError):
        core.tools.invoke("t.once", {})
    assert len(once) == 1                                                       # idempotent emas — qayta urinilmadi
    core.tools.register(Tool("t.slow", "slow", "", "A", {}, "", lambda a: time.sleep(3), agents=["user"], timeout=1))
    with pytest.raises(ToolError, match="Timeout"):
        core.tools.invoke("t.slow", {})
    core.tools.register(Tool("t.lim", "lim", "", "A", {}, "", lambda a: 1, agents=["user"], rate_per_min=2))
    core.tools.invoke("t.lim", {})
    core.tools.invoke("t.lim", {})
    with pytest.raises(ToolError, match="limit"):
        core.tools.invoke("t.lim", {})


def test_mission_tool_and_propose_memory(core):
    core.agents.agents["file_analysis"].handler = lambda p: {"files": []}
    r = core.tools.invoke("mission.create", {"goal": "fayllarni ko'rsat"})
    assert r["result"]["steps"] == 1 and core.missions.wait(r["result"]["id"], 10)["status"] == "completed"
    p = core.tools.invoke("memory.propose", {"content": "POS hisobotlari har kuni 9:00 da"}, caller="memory_agent")
    assert p["result"]["suggestion_id"] and not core.memory.search("hisobotlari")           # tasdiqsiz xotiraga yozilmadi
    assert core.researcher.decide(p["result"]["suggestion_id"], True)["memory_id"]


def test_global_search_and_commands(core, tmp_path):
    core.memory.add("Chilonzor do'koni ijarasi 5 mln", "knowledge", source="user")
    core.missions.create("Chilonzor hisobotini ko'rsat", use_ai=False)
    r = core.command.search("chilonzor")
    kinds = {g["kind"] for g in r["groups"]}
    assert {"memory", "mission"} <= kinds and r["total"] >= 2
    assert core.command.search("a")["groups"] == []
    assert "/missiya" in core.command.run("/yordam")["text"]
    st = core.command.run("/holat")
    assert "avtonomlik Level" in st["text"] and "Kutilayotgan tasdiqlar" in st["text"]
    assert core.command.run("/to'xtat")["kind"] == "stop" and core.automation_paused
    core.command.run("/davom")
    assert not core.automation_paused
    core.agents.agents["file_analysis"].handler = lambda p: {"files": []}
    m = core.command.run("/missiya fayllarni ko'rsat")
    assert m["mission_id"] and core.missions.wait(m["mission_id"], 10)["status"] == "completed"
    t = core.command.run('/tool memory.search {"query": "chilonzor"}')
    assert t["kind"] == "tool" and t["data"]["status"] == "ok"
    with pytest.raises(ValueError):
        core.command.run("/tool memory.search {bad json}")
    # Chat/ovoz orqali ham: "jarvis to'xtat" — favqulodda to'xtatish
    assert core.chat("jarvis to'xtat")["intent"] == "command_stop" and core.automation_paused
    core.resume_automation()


def test_api(client, core):
    assert client.get("/api/tools").status_code == 200
    assert client.post("/api/tools/memory.search/invoke", json={"args": {}}).status_code == 400
    assert client.post("/api/tools/guardian.status/invoke", json={"args": {}}).json()["status"] == "ok"
    assert client.get("/api/search?q=guardian").json()["groups"][0]["kind"] == "tool"
    assert client.post("/api/command", json={"text": ""}).status_code == 400
    assert client.post("/api/command", json={"text": "/holat"}).json()["kind"] == "status"
    assert client.get("/api/tools/calls").json()[0]["tool"] == "guardian.status"
