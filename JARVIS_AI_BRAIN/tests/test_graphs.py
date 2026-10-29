import json
import time

import pytest

from jarvis.dag import DagError, topo_levels


def test_topology_validation():
    assert topo_levels([{"key": "a"}, {"key": "b", "depends_on": ["a"]}, {"key": "c", "depends_on": ["a"]},
                        {"key": "d", "depends_on": ["b", "c"]}]) == {"a": 0, "b": 1, "c": 1, "d": 2}
    with pytest.raises(DagError, match="sikl"):
        topo_levels([{"key": "a", "depends_on": ["b"]}, {"key": "b", "depends_on": ["a"]}])
    with pytest.raises(DagError, match="mavjud bo'lmagan"):
        topo_levels([{"key": "a", "depends_on": ["x"]}])


def test_parallel_failure_propagation_and_dedupe(core, monkeypatch):
    calls = []
    orig = core.agents._h_security

    def slow_security(p):
        calls.append(p.get("text"))
        time.sleep(0.3)
        return orig(p)
    core.agents.agents["security"].handler = slow_security
    g = core.dag.create("test", [
        {"key": "a", "agent": "security", "payload": {"text": "salom"}},
        {"key": "b", "agent": "developer", "payload": {"code": "x = 1"}},
        {"key": "a2", "agent": "security", "payload": {"text": "salom"}},              # a ning egizagi
        {"key": "bad", "agent": "developer", "payload": {}, "depends_on": ["b"]},
        {"key": "after_bad", "agent": "security", "payload": {"text": "x"}, "depends_on": ["bad"]},
        {"key": "after_bad2", "agent": "qa", "payload": {}, "depends_on": ["after_bad"]},
        {"key": "final_ok", "agent": "qa", "payload": {}, "depends_on": ["a", "b"]},
    ])
    core.agents.agents["developer"].handler = lambda p: (_ for _ in ()).throw(ValueError("kod yo'q")) if not p else core.agents.__class__._h_developer(core.agents, p)
    monkeypatch.setattr(core.dag, "safe_parallel", lambda r=None: 3)
    t0 = time.monotonic()
    r = core.dag.run(g["id"])
    st = {n["key"]: n["status"] for n in r["nodes"]}
    assert st["a"] == "done" and st["a2"] == "reused" and calls.count("salom") == 1     # takror bajarilmadi
    assert st["bad"] == "failed" and st["after_bad"] == "blocked" and st["after_bad2"] == "blocked"
    assert st["final_ok"] == "done" and r["status"] == "partial"
    assert time.monotonic() - t0 < 2.5
    levels = {n["key"]: n["level"] for n in r["nodes"]}
    assert levels["after_bad2"] == 3 and len(r["edges"]) == 5


def test_waiting_approval_and_resume(core):
    g = core.dag.from_text("bajar `mkdir yangi` keyin fayllarni ko'rsat")
    r = core.dag.run(g["id"])
    st = {n["key"]: n for n in r["nodes"]}
    assert st["s1_1"]["status"] == "waiting_approval" and st["s2_1"]["status"] == "pending" and r["status"] == "waiting_approval"
    aid = st["s1_1"]["approval_id"]
    a = core.approvals.get(aid)
    core.approvals.decide(aid, True, a["payload_hash"])
    core.settings.read_only_mode = False
    core.computer.execute(aid, a["payload"])
    r = core.dag.run(g["id"])
    assert r["status"] == "done" and all(n["status"] == "done" for n in r["nodes"])


def test_cancel_and_parallel_text(core):
    g = core.dag.from_text("xavfsizlikni tekshir hamda fayllarni ko'rsat keyin test")
    assert [n["depends_on"] for n in g["nodes"]] == [[], [], ["s1_1", "s1_2"]]
    core.dag.cancel(g["id"])
    with pytest.raises(DagError):
        core.dag.run(g["id"])
    assert all(n["status"] == "cancelled" for n in core.dag.get(g["id"])["nodes"])
    with pytest.raises(DagError):
        core.dag.create("x", [{"key": "a", "agent": "yoq_agent"}])


def test_knowledge_graph_links(core):
    m = core.memory.add("Ollama 11434 portda", "knowledge", project="JARVIS", source="https://ollama.com/docs")
    core.decisions.create(problem="Model tanlash", options=["a", "b"], chosen="a", rationale="RAM", project="JARVIS",
                              files=["jarvis/router.py"], sources=["https://ollama.com/docs"])
    t = core.agents.submit("security", "tekshiruv", {"text": "x"}, run_now=True)
    kg = core.kgraph
    proj = kg.find("project", "JARVIS")
    nb = kg.neighbors(proj["id"], depth=2)
    types = {n["type"] for n in nb["nodes"]}
    assert {"memory", "decision", "file", "source"} <= types
    assert any(e["rel"] == "performed_by" for e in kg.neighbors(kg.find("task", t["id"])["id"])["edges"])
    path = kg.path(kg.find("memory", m["id"])["id"], kg.find("file", "jarvis/router.py")["id"])
    assert path and path[-1]["to"] == "file:jarvis/router.py"
    assert kg.search("router")[0]["type"] == "file"
    core.audit.error("pos_agent", "timeout")
    eid = core.db.one("SELECT MAX(id) i FROM errors")["i"]
    from jarvis.improve import Improver
    Improver(core).create(f"POS timeout tuzatish error#{eid}", "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n")
    assert any(e["rel"] == "resolved_by" for e in kg.neighbors(kg.find("error", eid)["id"])["edges"])
    assert kg.rebuild()["nodes"] >= kg.stats()["nodes"] - 0
    assert json.dumps(kg.stats())


def test_graph_api(client):
    g = client.post("/api/dag", json={"goal": "xavfsizlikni tekshir hamda fayllarni ko'rsat"}).json()
    r = client.post(f"/api/dag/{g['id']}/run", json={}).json()
    assert r["status"] == "done" and r["counts"]["done"] == 2
    bad = client.post("/api/dag", json={"goal": "x", "nodes": [{"key": "a", "agent": "qa", "depends_on": ["a"]}]})
    assert bad.status_code == 400
    assert client.get("/api/kg").json()["nodes"] >= 2
    hits = client.get("/api/kg/search", params={"q": "qa", "type": "agent"}).json()
    assert client.get(f"/api/kg/node/{hits[0]['id']}").json()["edges"]
    assert client.post("/api/kg/link", json={"src_type": "error", "src_ref": "1", "rel": "nomalum", "dst_type": "x",
                                             "dst_ref": "y"}).status_code == 400
