import json
import zipfile

import pytest

from jarvis.approval import ApprovalError
from jarvis.backup import BackupError


def test_backup_verify_restore_roundtrip(core):
    m = core.memory.add("Muhim: yetkazib beruvchi Ali MChJ", source="user")
    r = core.backup.create("test")
    assert r["manifest"]["db_integrity"] == "ok" and r["manifest"]["secrets_included"] is False
    v = core.backup.verify(r["name"])
    assert v["ok"] and {c["check"] for c in v["checks"]} >= {"zip CRC", "sinov-tiklash: integrity_check"}
    core.memory.delete(m["id"])
    core.memory.add("Tiklashdan keyin yo'qolishi kerak bo'lgan yozuv")
    appr = core.backup.request_restore(r["name"])
    assert appr["level"] == "E" and appr["status"] == "pending"
    with pytest.raises(ApprovalError):
        core.backup.restore(r["name"], appr["id"])                  # tasdiqsiz tiklanmaydi
    core.approvals.decide(appr["id"], True, appr["payload_hash"])
    res = core.backup.restore(r["name"], appr["id"])
    contents = [x["content"] for x in core.memory.list()]
    assert "Muhim: yetkazib beruvchi Ali MChJ" in contents and not any("yo'qolishi" in c for c in contents)
    assert res["safety_backup"] in [i["name"] for i in core.backup.list()]
    assert core.memory.search("Ali")                                  # FTS indeksi ham tiklandi
    assert [h["action"] for h in core.backup._history()][-1] == "restore"


def test_tampered_backup_detected(core):
    core.settings.save()
    r = core.backup.create("t")
    p = core.backup.dir / r["name"]
    with zipfile.ZipFile(p) as z:
        items = {n: z.read(n) for n in z.namelist()}
    items["settings.json"] = b'{"ai_provider": "offline", "x": 1}'
    with zipfile.ZipFile(p, "w") as z:
        for n, b in items.items():
            z.writestr(n, b)
    v = core.backup.verify(r["name"])
    assert not v["ok"] and any(c["check"] == "sha256 settings.json" and not c["ok"] for c in v["checks"])
    with pytest.raises(BackupError):
        core.backup.request_restore(r["name"])
    assert any(n["category"] == "backup" and n["severity"] == "critical" for n in core.notifier.list())
    r2 = core.backup.create("t2")
    p2 = core.backup.dir / r2["name"]
    with zipfile.ZipFile(p2, "a") as z:
        z.writestr("yashirin.py", "print('x')")                      # manifestda yo'q fayl
    v2 = core.backup.verify(r2["name"])
    assert not v2["ok"] and "yashirin.py" in v2["checks"][-1]["note"]


def test_retention_and_secret_guard(core):
    core.settings.backup_keep = 2
    for i in range(4):
        core.backup.create(f"n{i}")
    assert len(core.backup.list()) == 2
    core.settings.save()
    sp = core.settings.path()
    sp.write_text(json.dumps({"note": "token=SuperSecretValue123"}), encoding="utf-8")
    with pytest.raises(BackupError, match="maxfiy"):
        core.backup.create("x")
    st = core.backup.status()
    assert st["last_failure"]["ok"] is False and st["count"] == 2


def test_auto_tick_and_api(client, core):
    assert core.backup.status()["overdue"]
    assert core.backup.tick()["name"]
    assert core.backup.tick() is None                                 # endi muddati o'tmagan
    d = client.get("/api/backups").json()
    assert d["status"]["count"] == 1 and d["items"][0]["last_verify"]["ok"]
    assert client.post("/api/backups/../../etc/passwd/verify").status_code in (400, 404)
