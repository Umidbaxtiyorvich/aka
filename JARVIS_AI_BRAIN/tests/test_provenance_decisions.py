import pytest

from jarvis.decisions import DecisionError
from jarvis.memory import MemoryError_, label


def test_provenance_types_and_verification(core):
    u = core.memory.add("Do'kon soat 9 da ochiladi", source="user_chat")
    assert u["info_type"] == "user_given" and label(u) == "Foydalanuvchi ma'lumoti"
    w = core.memory.add("FFmpeg subtitles filtri libass talab qiladi", "knowledge", source="https://ffmpeg.org/ffmpeg-filters.html")
    assert w["info_type"] == "fact" and w["reference"].startswith("https://") and label(w) == "Tekshirilmagan fakt"
    with pytest.raises(MemoryError_, match="Manbasiz"):
        core.memory.add("Dollar kursi 12900", info_type="fact", verified=True)
    with pytest.raises(MemoryError_):
        core.memory.verify(u["id"], "")
    v = core.memory.verify(w["id"], "https://ffmpeg.org/ffmpeg-filters.html#subtitles", "hujjat o'qildi")
    assert label(v) == "Tasdiqlangan fakt" and v["verified_at"]
    e = core.memory.update(w["id"], "FFmpeg subtitles filtri libass talab qilmaydi")
    assert label(e) == "Tekshirilmagan fakt"                                 # tahrirdan keyin qayta tekshirish kerak
    m = core.memory.add("Model fikricha savdo oshadi", source="ai_router")
    assert label(m) == "Model xulosasi"


def test_numeric_conflict_and_compare(core):
    core.memory.add("Non narxi 4000 so'm", source="https://pos.example/narx")
    b = core.memory.add("Non narxi 4500 so'm", source="user_chat")
    assert b["status"] == "conflict"
    pv = core.memory.provenance(b["id"])
    assert pv["conflicts"] and pv["conflicts"][0]["reason"] == "raqamlar farqi"
    cmp_ = core.memory.compare("Non narxi")
    assert len(cmp_["items"]) == 2 and cmp_["verified_count"] == 0 and "ehtiyot" in cmp_["summary"]


def test_stale_detection(core):
    m = core.memory.add("Eski ma'lumot", source="https://x.example", observed_at="2020-01-01")
    assert core.memory.is_stale(core.memory.get(m["id"]))
    assert any(s["id"] == m["id"] for s in core.memory.stale_items())


def test_decision_journal_immutable_history(core):
    d = core.decisions.create(problem="Qaysi AI model?", options=["qwen2.5:1.5b", "llama3.2:3b"], chosen="qwen2.5:1.5b",
                              rationale="8 GB RAM", sources=["docs/ARCHITECTURE.md"], risks="sifat past bo'lishi mumkin",
                              expected_outcome="javob < 10 s", review_at="2020-01-01", files=["jarvis/router.py"])
    assert core.decisions.due_for_review()[0]["id"] == d["id"]
    with pytest.raises(DecisionError, match="tarixiy"):
        core.decisions.update(d["id"], chosen="llama3.2:3b")
    u = core.decisions.update(d["id"], actual_outcome="javob 6 s", note="o'lchandi")
    assert u["events"][-1]["field"] == "actual_outcome" and u["events"][-1]["old_value"] is None
    r = core.decisions.revise(d["id"], reason="GPU topildi", chosen="llama3.2:3b", rationale="6 GB VRAM bor")
    assert r["old"]["status"] == "superseded" and r["old"]["chosen"] == "qwen2.5:1.5b"   # eski qiymat saqlangan
    assert r["new"]["supersedes"] == d["id"] and "GPU topildi" in r["new"]["rationale"]
    assert [h["id"] for h in core.decisions.history(d["id"])] == [d["id"], r["new"]["id"]]
    assert "chosen" in core.decisions.compare(d["id"], r["new"]["id"])["differences"]
    assert core.decisions.list(q="AI model")
    with pytest.raises(DecisionError):
        core.decisions.create(problem="x", options=["a"], chosen="b", rationale="y")


def test_provenance_decision_api(client):
    m = client.post("/api/memory", json={"content": "Ollama 11434 portda ishlaydi", "kind": "knowledge",
                                         "source": "https://ollama.com/docs", "info_type": "fact"}).json()
    assert client.get(f"/api/memory/{m['id']}/provenance").json()["label"] == "Tekshirilmagan fakt"
    assert client.post(f"/api/memory/{m['id']}/verify", json={"reference": ""}).status_code == 400
    assert client.post(f"/api/memory/{m['id']}/verify", json={"reference": "https://ollama.com/docs/api"}).json()["verified"] == 1
    assert client.get("/api/knowledge/compare", params={"q": "Ollama"}).json()["verified_count"] == 1
    d = client.post("/api/decisions", json={"problem": "Backup qayerda?", "options": ["lokal", "bulut"], "chosen": "lokal",
                                            "rationale": "maxfiylik"}).json()
    r = client.post(f"/api/decisions/{d['id']}/revise", json={"reason": "tashqi disk", "changes": {"chosen": "bulut",
                                                                                                    "options": ["lokal", "bulut"]}}).json()
    assert r["old"]["status"] == "superseded"
    assert len(client.get(f"/api/decisions/{d['id']}").json()["chain"]) == 2
    assert client.post(f"/api/decisions/{d['id']}/update", json={"status": "reviewed"}).status_code == 400
