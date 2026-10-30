"""3D Brain, jonli hodisalar (SSE), Graph Explorer API, Memory Explorer va Memory Connection Engine."""
import json
import time

import pytest

from jarvis.memory import MemoryError_


def test_events_from_real_modules(core):
    s0 = core.events.seq
    m = core.memory.add("Do'kon soat 9 da ochiladi", "long_term")
    core.memory.search("do'kon")
    core.audit.error("pos", "timeout")
    types = [e["type"] for e in core.events.since(s0)]
    assert "memory.add" in types and "memory.search" in types and "error" in types
    assert any(e.get("id") == m["id"] for e in core.events.since(s0) if e["type"] == "memory.add")
    core.agents.submit("qa", "tekshiruv", {"action": "health"}, run_now=True)
    types = [e["type"] for e in core.events.since(s0)]
    assert "task.start" in types and "task.end" in types
    assert core.events.snapshot()["active"]["tasks"] == 0


def test_ai_events_start_end(core):
    s0 = core.events.seq
    core.ai.route([{"role": "user", "content": "salom"}])
    ev = [e for e in core.events.since(s0) if e["type"].startswith("ai.")]
    assert [e["type"] for e in ev] == ["ai.start", "ai.end"] and ev[1]["ok"] is True
    assert core.events.snapshot()["active"]["ai"] == 0


def test_sse_stream_once(client, core):
    s0 = core.events.seq
    core.memory.add("SSE sinovi uchun xotira", "long_term")
    r = client.get(f"/api/events/stream?since={s0}&once=true")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    datas = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]
    assert any(d.get("type") == "memory.add" for d in datas)
    assert "event: hello" in r.text


def test_brain_regions_real_state(client, core):
    core.audit.error("security", "x")
    st = client.get("/api/brain/state").json()
    ids = [r["id"] for r in st["regions"]]
    assert ids == ["memory", "reasoning", "planning", "language", "vision", "creative", "agents", "security"]
    mem = next(r for r in st["regions"] if r["id"] == "memory")
    assert "memories" in mem and "biologik miya simulyatsiyasi emas" in st["note"]
    sec = client.get("/api/brain/region/security").json()
    assert sec["errors_24h"] >= 1 and any(a["key"] == "security" for a in sec["agents"])
    assert client.get("/api/brain/region/yoq").status_code == 400


def test_graph_explorer_filters_and_categories(client, core):
    core.memory.add("Mango Market loyihasi uchun narxlar", "project", project="mango")
    core.memory.add("Python API endpoint qoidasi", "knowledge")
    core.kgraph.rebuild()
    g = client.get("/api/kg/graph").json()
    cats = {n["cat"] for n in g["nodes"]}
    assert {"memories", "projects", "knowledge", "skills", "agents", "apis"} <= cats
    assert len(g["categories"]) == 15 and g["total"] >= len(g["nodes"])
    only = client.get("/api/kg/graph?categories=projects").json()
    assert only["nodes"] and all(n["cat"] == "projects" for n in only["nodes"])
    assert all(n["type"] == "memory" for n in client.get("/api/kg/graph?categories=knowledge&q=Python").json()["nodes"])
    page = client.get("/api/kg/graph?limit=5&offset=0").json()
    assert len(page["nodes"]) == 5 and page["has_more"]
    assert client.get("/api/kg/graph?since=2999-01-01").json()["nodes"] == []
    assert client.get("/api/kg/graph?source=jarvis:capabilities").json()["nodes"]


def test_graph_with_thousands_of_nodes_is_fast(core):
    db = core.db
    with db._lock:
        db.conn.executemany("INSERT INTO kg_nodes(type, ref, label) VALUES (?,?,?)", [("memory", f"x{i}", f"tugun {i}") for i in range(5000)])
        ids = [r[0] for r in db.conn.execute("SELECT id FROM kg_nodes WHERE ref LIKE 'x%'").fetchall()]
        db.conn.executemany("INSERT OR IGNORE INTO kg_edges(src, rel, dst) VALUES (?,?,?)",
                            [(ids[i], "related_to", ids[(i * 7 + 3) % len(ids)]) for i in range(len(ids))])
        db.conn.commit()
    t0 = time.monotonic()
    g = core.kgraph.graph(limit=3000)
    dt = time.monotonic() - t0
    assert len(g["nodes"]) == 3000 and g["edges"] and g["has_more"]
    assert dt < 5, f"graf so'rovi juda sekin: {dt:.2f}s"


def test_memory_connection_engine(client, core):
    a = core.connector.ingest("Mango Market do'koni har dushanba soat 9 da ochiladi")["memory"]
    dup = core.connector.ingest("Mango Market do'koni har dushanba soat 9 da ochiladi")
    assert dup["duplicate"] and dup["memory"]["id"] == a["id"]                 # takror yozilmadi
    near = core.connector.ingest("Mango Market do'koni har dushanba soat 9 da ochiladi va kechqurun yopiladi")
    assert not near["duplicate"] and a["id"] in near["analysis"]["auto_links"] + near["analysis"]["suggested_links"]
    rel = client.get(f"/api/memory/{near['memory']['id']}/related").json()
    assert any(r["id"] == a["id"] for r in rel)
    assert core.connector.guess_kind("Python API endpoint 500 xato qaytaryapti") == "technical"
    assert core.connector.guess_kind("Men qora qahvani yoqtiraman") == "preference"
    assert core.connector.guess_kind("Kecha soat 3 da uchrashuv bo'ldi") == "episodic"
    # Taklif qilingan aloqa — foydalanuvchi tasdig'i bilan
    far = core.connector.ingest("Mango Market do'koni yakshanba yopiq bo'ladi")              # o'xshashlik ~0.33
    assert a["id"] in far["analysis"]["suggested_links"] and a["id"] not in far["analysis"]["auto_links"]
    sug = client.get("/api/memory/suggestions").json()
    sid = next(s["id"] for s in sug if s["src"] == far["memory"]["id"] and s["dst"] == a["id"])
    assert client.post(f"/api/memory/suggestions/{sid}", json={"accept": True}).json()["status"] == "accepted"
    assert client.post(f"/api/memory/suggestions/{sid}", json={"accept": False}).status_code == 400    # qayta hal qilib bo'lmaydi
    assert client.post("/api/memory/suggestions/999999", json={"accept": True}).status_code == 400


def test_memory_explorer_api(client, core):
    with pytest.raises(MemoryError_, match="foydalanuvchi"):
        core.memory.add("AI taxmini: foydalanuvchi choyni yoqtiradi", "preference", source="ai")
    m = core.memory.add("Ish vaqti 9:00-18:00", "working", title="Ish vaqti")
    cats = {c["kind"]: c for c in client.get("/api/memory/categories").json()}
    assert cats["working"]["count"] == 1 and cats["preference"]["label"] == "User-approved Preferences"
    assert len(cats) >= 8
    ex = client.get("/api/memory/explore?kind=working").json()
    assert ex[0]["name"] == "Ish vaqti" and ex[0]["category"] == "Working Memory" and "reliability" in ex[0]
    r = client.put(f"/api/memory/{m['id']}", json={"content": "Ish vaqti 9:00-19:00", "title": "Yangi vaqt", "kind": "long_term"}).json()
    assert r["title"] == "Yangi vaqt" and r["kind"] == "long_term"
    core.memory.add("Narx 5000 so'm", "long_term")
    core.memory.add("Narx 6000 so'm", "long_term")
    assert any(x["status"] == "conflict" for x in client.get("/api/memory/explore?status=conflict").json())
    a = client.post("/api/memory/analyze", json={"text": "Narx 5000 so'm"}).json()
    assert a["duplicate_of"] and a["conflicts"]
