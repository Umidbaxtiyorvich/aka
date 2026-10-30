"""Mission Engine: tushunish → reja → ruxsat → bajarish → tekshirish → hisobot → refleksiya; checkpoint, retry, dead-letter, tiklash."""
import pytest

from jarvis.mission import MissionError


def _fake(core, agent, results):
    """Agent handlerini ketma-ket natijalar bilan almashtiradi (Exception — xato)."""
    calls = []

    def h(p):
        calls.append(p)
        r = results[min(len(calls), len(results)) - 1]
        if isinstance(r, Exception):
            raise r
        return r
    core.agents.agents[agent].handler = h
    return calls


def test_understanding_questions_and_answer(core):
    m = core.missions.create("qil")
    assert m["status"] == "needs_input" and m["questions"]
    with pytest.raises(MissionError):
        core.missions.start(m["id"])
    m2 = core.missions.answer(m["id"], "fayllarni ko'rsat keyin test")
    assert m2["status"] == "pending" and len(m2["graph"]["nodes"]) == 2
    assert core.missions.get(m["id"])["status"] == "cancelled"


def test_safe_mission_runs_to_completion_with_report(core):
    _fake(core, "file_analysis", [{"files": ["a.txt"]}])
    m = core.missions.create("fayllarni ko'rsat keyin test", auto_start=False, use_ai=False)
    assert all(r["risk"] == "LOW" for r in m["risks"]) and m["status"] == "pending"
    m = core.missions.start(m["id"], background=False)
    assert m["status"] == "completed", m["log"]
    rep = m["report"]
    assert rep["done"] == rep["total"] == 2 and all(s["verified"] == 1 for s in rep["steps"])
    assert [x["stage"] for x in m["log"]][:3] == ["tushunish", "reja", "bajarish"] and m["reflection"]["goal_reached"]


def test_retry_idempotent_then_success_and_lesson(core):
    calls = _fake(core, "file_analysis", [RuntimeError("disk band"), {"files": []}, {"files": ["x"]}])
    m = core.missions.create("fayllarni ko'rsat", use_ai=False, max_attempts=3)
    m = core.missions.start(m["id"], background=False)
    assert m["status"] == "completed" and len(calls) >= 2
    step = m["report"]["steps"][0]
    assert step["attempts"] >= 2
    lessons = core.missions.lessons()
    assert any("urinishda bajarildi" in x["content"] for x in lessons)
    out = core.missions.decide_lesson(lessons[0]["id"], True)
    mem = core.memory.get(out["memory_id"])
    assert mem["kind"] == "procedural" and mem["reference"] == f"mission#{m['id']}"


def test_non_idempotent_failure_dead_letter_and_manual_retry(core):
    calls = _fake(core, "qa", [RuntimeError("buzildi")])
    m = core.missions.create("test keyin fayllarni ko'rsat", use_ai=False, max_attempts=3)
    _fake(core, "file_analysis", [{"files": []}])
    m = core.missions.start(m["id"], background=False)
    assert m["status"] == "failed" and len(calls) == 1               # qayta urinilmadi (idempotent emas)
    assert m["report"]["dead_letter"] == ["s1_1"] and any(n["status"] == "blocked" for n in m["graph"]["nodes"])
    _fake(core, "qa", [{"health": "ok"}])
    m = core.missions.retry_step(m["id"], "s1_1")
    assert m["status"] == "pending"
    m = core.missions.start(m["id"], background=False)
    assert m["status"] == "completed"


def test_verification_rejects_empty_result(core):
    _fake(core, "file_analysis", [{}])
    m = core.missions.start(core.missions.create("fayllarni ko'rsat", use_ai=False, max_attempts=2)["id"], background=False)
    step = m["report"]["steps"][0]
    assert m["status"] == "failed" and step["verified"] == 0 and "bo'sh" in step["verify_note"] and step["attempts"] == 2


def test_risky_step_waits_for_approval_and_never_auto_runs(core):
    m = core.missions.create("papkada bajar `mkdir hisobot`", use_ai=False, auto_start=True)
    assert m["status"] == "pending"                                   # MEDIUM — avtomatik boshlanmadi
    risk = m["risks"][0]
    assert risk["risk"] == "MEDIUM" and risk["needs_approval"]
    m = core.missions.start(m["id"], background=False)
    assert m["status"] == "waiting_approval" and m["report"]["waiting_approval"] == ["s1_1"]
    pend = core.approvals.list("pending")
    assert pend and pend[0]["action_type"] == "shell_command"


def test_forbidden_command_is_downgraded_to_advice(core):
    a = core.permissions.assess("computer", {"command": "format c:"})
    assert not a["allowed"] and a["risk"] == "CRITICAL"
    m = core.missions.create("bajar `format c:`", use_ai=False)
    assert m["graph"]["nodes"][0]["agent"] == "manager"
    assert any(p["key"] == "computer" and p["max_risk"] == "CRITICAL" for p in core.permissions.profiles())


def test_time_limit_pauses_and_resume(core):
    _fake(core, "file_analysis", [{"files": []}])
    m = core.missions.create("fayllarni ko'rsat keyin test", use_ai=False, max_minutes=1)
    core.db.execute("UPDATE missions SET started_at=datetime('now','-5 minutes') WHERE id=?", (m["id"],))
    m = core.missions.start(m["id"], background=False)
    assert m["status"] == "paused" and "vaqt limiti" in m["stop_reason"]
    core.db.execute("UPDATE missions SET max_minutes=60, started_at=datetime('now') WHERE id=?", (m["id"],))
    assert core.missions.start(m["id"], background=False)["status"] == "completed"


def test_recover_after_restart_checkpoint(core):
    m = core.missions.create("fayllarni ko'rsat keyin rasm chiz", use_ai=False)
    rid = m["dag_run_id"]
    core.db.execute("UPDATE missions SET status='running', started_at=datetime('now') WHERE id=?", (m["id"],))
    core.db.execute("UPDATE dag_runs SET status='running' WHERE id=?", (rid,))
    core.db.execute("UPDATE dag_nodes SET status='done', result='{\"files\": []}' WHERE run_id=? AND key='s1_1'", (rid,))   # checkpoint
    core.db.execute("UPDATE dag_nodes SET status='running' WHERE run_id=? AND key='s2_1'", (rid,))
    assert core.missions.recover(resume=False) == [m["id"]]
    m = core.missions.get(m["id"])
    nodes = {n["key"]: n for n in m["graph"]["nodes"]}
    assert m["status"] == "paused" and nodes["s1_1"]["status"] == "done"
    assert nodes["s2_1"]["status"] == "failed" and nodes["s2_1"]["dead_letter"] == 1     # manager idempotent emas — ikki marta bajarilmaydi


def test_cancel_and_chat_command(core):
    m = core.missions.create("fayllarni ko'rsat", use_ai=False)
    assert core.missions.cancel(m["id"])["status"] == "cancelled"
    with pytest.raises(MissionError):
        core.missions.start(m["id"])
    _fake(core, "file_analysis", [{"files": []}])
    r = core.chat("missiya: fayllarni ko'rsat")
    assert r["intent"] == "mission" and "avtomatik boshlandi" in r["text"]
    assert core.missions.wait(r["mission_id"], 10)["status"] == "completed"


def test_mission_api(client, core):
    _fake(core, "file_analysis", [{"files": []}])
    r = client.post("/api/missions", json={"goal": "fayllarni ko'rsat", "use_ai": False})
    mid = r.json()["id"]
    assert client.post(f"/api/missions/{mid}/start", json={}).status_code == 200
    assert core.missions.wait(mid, 10)["status"] == "completed"
    assert client.get("/api/missions").json()[0]["progress"] == 100
    assert client.post(f"/api/missions/{mid}/explode").status_code == 404
    assert client.post(f"/api/missions/{mid}/cancel").status_code == 400
    assert any(a["key"] == "qa" for a in client.get("/api/permissions/agents").json())
