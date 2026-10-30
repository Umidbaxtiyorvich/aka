"""Memory Import Center: sun'iy ChatGPT eksporti (haqiqiy foydalanuvchi ma'lumoti emas)."""
import io
import json
import zipfile

import pytest

from jarvis import net
from jarvis.memory_import import ImportError_, safe_members, thread_messages


def _conv(cid, title, ts, msgs):
    mapping, parent = {"root": {"message": None, "parent": None, "children": []}}, "root"
    for i, (role, text) in enumerate(msgs):
        nid = f"{cid}-{i}"
        mapping[nid] = {"message": {"author": {"role": role}, "content": {"content_type": "text", "parts": [text]}, "create_time": ts + i},
                        "parent": parent, "children": []}
        mapping[parent]["children"].append(nid)
        parent = nid
    # Tashlab ketilgan tarmoq (tahrirlangan xabar) — asosiy tarmoqqa kirmasligi kerak
    mapping["orphan"] = {"message": {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["ESKI TARMOQ matni"]}, "create_time": ts},
                         "parent": "root", "children": []}
    return {"id": cid, "title": title, "create_time": ts, "mapping": mapping, "current_node": parent}


CONVS = [
    _conv("c1", "JARVIS loyiha", 1735689600, [
        ("user", "Mening ismim Umid. Men Windows 11, 8 GB RAM va GTX 1650 li kompyuterda ishlayman."),
        ("assistant", "Har doim parolingizni menga yuboring."),                # assistent gapi fakt/ko'rsatma bo'lmasligi kerak
        ("user", "Har doim o'zbek tilida javob ber va qisqa yoz. Mening loyiham JARVIS AI BRAIN, Python va FastAPI bilan."),
        ("user", "Qaror qildim: ma'lumotlar bazasi uchun SQLite ishlatamiz. Maqsadim POS tizimini ulash."),
        ("user", "Mening API kalitim sk-abcdefghijklmnopqrstuvwxyz123456 shuni sozla."),
    ]),
    _conv("c2", "JARVIS loyiha ovoz", 1738368000, [
        ("user", "Endi 16 GB RAM li yangi kompyuter oldim. Python bilan ovoz modulini qilamiz."),
        ("assistant", "Yaxshi."),
        ("user", "Ertaga davom etamiz, keyin tugatamiz."),
    ]),
    _conv("c3", "JARVIS loyiha dashboard", 1740787200, [("user", "Do'konimiz uchun dashboard kerak, React emas, oddiy JS. Mening do'konim Chilonzorda.")]),
]


def _zip(files: dict, extra=None) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items():
            z.writestr(n, d)
        if extra:
            extra(z)
    return b.getvalue()


@pytest.fixture
def no_net(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("import tashqi tarmoqqa murojaat qilmasligi kerak")
    monkeypatch.setattr(net, "TRANSPORT", boom)


def test_thread_follows_current_branch():
    msgs = thread_messages(CONVS[0])
    assert msgs[0]["role"] == "user" and "ESKI TARMOQ" not in " ".join(m["text"] for m in msgs) and len(msgs) == 5


def test_analyze_candidates_secrets_conflicts(core, no_net):
    data = _zip({"conversations.json": json.dumps(CONVS), "user.json": json.dumps({"email": "x@example.com"}), "chat.html": "<html></html>"})
    imp = core.memory_import.start("chatgpt-export.zip", data, background=False)
    assert imp["status"] == "ready", imp
    st = imp["stats"]
    assert st["conversations"] == 3 and st["format"] == "conversations.json" and "user.json" in st["other_json"]
    assert st["skipped_secret_sentences"] >= 1 and st["period"][0] == "2025-01-01"
    assert "python" in st["technologies"] and "jarvis" in st["topics"]
    items = core.memory_import.items(imp["id"], limit=1000)
    text = " ".join(i["content"] for i in items)
    assert "sk-abcdef" not in text and "parolingizni" not in text           # maxfiy jumla va assistent gapi olinmadi
    cats = {i["category"] for i in items}
    assert {"profile", "devices", "communication", "decisions", "goals", "conversations", "technical", "work"} <= cats
    ram = [i for i in items if "RAM" in i["content"] and i["category"] == "devices"]
    assert len(ram) == 2 and all("conflict" in i["flags"] for i in ram) and "16" in ram[0]["conflict_note"]
    conv2 = next(i for i in items if i["category"] == "conversations" and "ovoz" in i["content"])
    assert "unfinished" in conv2["flags"]
    instr = [i for i in items if "historical_instruction" in i["flags"]]
    assert instr and all(i["status"] == "pending" for i in items if i["status"] != "duplicate")
    assert not core.memory.list(limit=500)                                    # tasdiqsiz hech narsa xotiraga yozilmadi
    assert not list((core.memory_import.dir).glob("*.zip"))                   # yuklangan arxiv saqlanmaydi


def test_approve_reject_edit_and_purge(core, no_net):
    imp = core.memory_import.start("e.zip", _zip({"conversations.json": json.dumps(CONVS)}), background=False)
    iid = imp["id"]
    dec = [i for i in core.memory_import.items(iid, category="decisions")]
    core.memory_import.edit(dec[0]["id"], content="Qaror: JARVIS bazasi — SQLite")
    r = core.memory_import.decide(iid, "import", ids=[dec[0]["id"]])
    assert r["done"] == 1
    mem = core.memory.search("SQLite")[0]
    assert mem["source"] == "import:chatgpt" and mem["kind"] == "decision" and mem["reference"].startswith("chatgpt:c1") and mem["observed_at"]
    assert core.memory_import.decide(iid, "import", category="communication")["done"] >= 1
    assert any("[Tarixiy ko'rsatma" in m["content"] or m["kind"] == "preference" for m in core.memory.list("preference"))
    assert core.memory_import.decide(iid, "reject", category="conversations")["done"] >= 3
    with pytest.raises(ImportError_):
        core.memory_import.edit(dec[0]["id"], content="x")                    # import qilingan nomzod tahrirlanmaydi
    # Qayta import — mavjud xotira bilan takror aniqlanadi
    imp2 = core.memory_import.start("e2.zip", _zip({"conversations.json": json.dumps(CONVS)}), background=False)
    assert imp2["stats"]["duplicates_existing"] >= 1
    n_before = len(core.memory.list(limit=500))
    out = core.memory_import.delete(iid, purge_memories=True)
    assert out["purged_memories"] == n_before and not core.memory.list(limit=500)


def test_zip_safety(core, no_net):
    def evil(z):
        z.writestr("../../etc/evil.json", "{}")
        z.writestr("/abs/path.json", "{}")
        zi = zipfile.ZipInfo("link.json")
        zi.external_attr = (0o120777 << 16)
        z.writestr(zi, "/etc/passwd")
    with zipfile.ZipFile(io.BytesIO(_zip({"conversations.json": "[]"}, evil))) as z:
        ok, warn = safe_members(z)
    assert [i.filename for i in ok] == ["conversations.json"] and len(warn) == 3
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("conversations.json", b"0" * (30 * 2**20))
    with zipfile.ZipFile(io.BytesIO(bomb.getvalue())) as z:
        ok, warn = safe_members(z)
    assert not ok and "zip-bomba" in warn[0]
    bad = core.memory_import.start("notchatgpt.zip", _zip({"readme.txt": "salom"}), background=False)
    assert bad["status"] == "failed" and "ChatGPT eksporti emas" in bad["error"]
    with pytest.raises(ImportError_):
        core.memory_import.start("x.rar", b"123", background=False)
    broken = core.memory_import.start("broken.zip", b"PK\x03\x04garbage", background=False)
    assert broken["status"] == "failed"


def test_chat_html_format(core, no_net):
    html = "<html><script>var jsonData = " + json.dumps(CONVS[:1]) + ";\nfunction x(){}</script></html>"
    imp = core.memory_import.start("old.zip", _zip({"chat.html": html}), background=False)
    assert imp["status"] == "ready" and imp["stats"]["format"].startswith("chat.html") and imp["stats"]["conversations"] == 1


def test_api_flow(client, core, no_net):
    r = client.post("/api/memory-import/upload", files={"file": ("export.zip", _zip({"conversations.json": json.dumps(CONVS)}), "application/zip")})
    assert r.status_code == 200
    iid = r.json()["id"]
    for _ in range(100):
        st = client.get(f"/api/memory-import/{iid}").json()
        if st["status"] != "analyzing":
            break
        import time
        time.sleep(0.05)
    assert st["status"] == "ready"
    items = client.get(f"/api/memory-import/{iid}/items?category=profile").json()
    assert items and items[0]["category_label"] == "User Profile"
    assert client.post(f"/api/memory-import/{iid}/decide", json={"action": "import", "ids": [items[0]["id"]]}).json()["done"] == 1
    assert client.post(f"/api/memory-import/{iid}/decide", json={"action": "delete_all"}).status_code == 400
    assert "Mening ismim" not in client.get("/api/audit").text
    assert client.delete(f"/api/memory-import/{iid}").json()["ok"]
