import base64
import json

import pytest

from jarvis import net
from jarvis.imagegen import ImageGenError
from jarvis.improve import ImproveError, Improver
from jarvis.planner import parse_ai_steps

PNG = base64.b64encode(bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                                     "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()


class FakeAI:
    """Router o'rniga: oxirgi so'rovni saqlaydi va tayyor javob qaytaradi."""
    name, model = "ollama", "fake"

    def __init__(self, text):
        self.text, self.calls = text, []

    def route(self, messages, purpose="", private=None):
        self.calls.append((messages, purpose))
        return {"text": self.text, "route": {"provider": "fake", "model": "fake-1"}}


def test_parse_ai_steps():
    assert parse_ai_steps('Mana: ["test", "fayllarni ko\'rsat"]') == ["test", "fayllarni ko'rsat"]
    assert parse_ai_steps("tushunarsiz") is None
    assert parse_ai_steps(json.dumps([str(i) for i in range(20)])) is None


def test_ai_planner_and_fallback(core, monkeypatch):
    monkeypatch.setattr(core, "ai", FakeAI('["xavfsizlikni tekshir", "savdo hisobotini ko\'rsat", "bajar `mkdir x`"]'))
    p = core.planner.create("Do'kon holatini bilib, keyin papka och")
    assert p["source"] == "ai" and [s["agent"] for s in p["steps"]] == ["qa", "bi", "computer"]
    assert "<untrusted>" in core.ai.calls[0][0][0]["content"]
    monkeypatch.setattr(core, "ai", FakeAI("kechirasiz, bilmayman"))
    p2 = core.planner.create("testlarni tekshir keyin fayllarni ko'rsat")
    assert p2["source"] == "rules" and "tushunarsiz" in p2["note"] and len(p2["steps"]) == 2
    monkeypatch.setattr(core.ai, "name", "offline")
    assert core.planner.create("test")["source"] == "rules"


def test_ai_patch_suggestion_goes_through_proposal_flow(core, monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    (proj / "jarvis").mkdir(parents=True)
    (proj / "jarvis" / "pos.py").write_text("def total(a, b):\n    return a - b\n")
    core.audit.error("pos_agent", "jami summa noto'g'ri hisoblandi")
    eid = core.db.one("SELECT MAX(id) i FROM errors")["i"]
    diff = "```diff\n--- a/jarvis/pos.py\n+++ b/jarvis/pos.py\n@@ -1,2 +1,2 @@\n def total(a, b):\n-    return a - b\n+    return a + b\n```"
    monkeypatch.setattr(core, "ai", FakeAI(diff))
    imp = Improver(core, project_root=proj)
    p = imp.suggest_patch(eid)
    assert p["status"] == "proposed" and p["source"] == "ai" and f"error#{eid}" in p["title"]
    assert "jami summa" in core.ai.calls[0][0][0]["content"] and core.ai.calls[0][1] == "code"
    with pytest.raises(ImproveError, match="himoyalangan"):
        imp.suggest_patch(eid, file="jarvis/security.py")
    monkeypatch.setattr(core, "ai", FakeAI("diff yozolmadim"))
    with pytest.raises(ImproveError, match="yaroqli"):
        imp.suggest_patch(eid)
    monkeypatch.setattr(core.ai, "name", "offline")
    with pytest.raises(ImproveError, match="ulanmagan"):
        imp.suggest_patch(eid)


def test_image_generation_adapter(core, monkeypatch):
    with pytest.raises(ImageGenError, match="sozlanmagan"):
        core.imagegen.generate("non")
    core.settings.image_gen_url = "http://127.0.0.1:7860"
    seen = {}

    def fake(method, url, data, headers, timeout):
        if "txt2img" in url:
            seen["body"] = json.loads(data)
            return 200, json.dumps({"images": [PNG], "info": json.dumps({"seed": 42})})
        if "img2img" in url:
            return 200, json.dumps({"images": [PNG]})
        if "sd-models" in url:
            return 200, json.dumps([{"model_name": "sd15"}])
        return 404, "{}"
    monkeypatch.setattr(net, "TRANSPORT", fake)
    r = core.imagegen.generate("issiq non, do'kon", width=1000, height=3000)
    assert r["seed"] == 42 and open(r["outputs"][0], "rb").read(4) == b"\x89PNG"
    assert seen["body"]["width"] == 1000 and seen["body"]["height"] == 2048       # chegaralangan
    src = core.settings.allowed_read_dirs[0] + "/kirish.png"
    open(src, "wb").write(base64.b64decode(PNG))
    assert core.imagegen.edit(src, "qizil fon")["outputs"]
    assert core.imagegen.status()["generator"]["models"] == ["sd15"]


def test_vision_local_only(core, monkeypatch):
    src = core.settings.allowed_read_dirs[0] + "/r.png"
    open(src, "wb").write(base64.b64decode(PNG))
    with pytest.raises(ImageGenError, match="sozlanmagan"):
        core.imagegen.describe(src)
    core.settings.vision_model = "moondream"
    urls = []

    def fake(method, url, data, headers, timeout):
        urls.append(url)
        body = json.loads(data)
        assert body["messages"][0]["images"] and body["model"] == "moondream"
        return 200, json.dumps({"message": {"content": "Bitta piksel tasvir."}, "prompt_eval_count": 10, "eval_count": 4})
    monkeypatch.setattr(net, "TRANSPORT", fake)
    r = core.imagegen.describe(src)
    assert r["description"] == "Bitta piksel tasvir." and r["info_type"] == "model_inference"
    assert all(u.startswith(core.settings.ollama_url) for u in urls)                 # faqat mahalliy Ollama
    with pytest.raises(Exception):
        core.imagegen.describe("/etc/hostname")
