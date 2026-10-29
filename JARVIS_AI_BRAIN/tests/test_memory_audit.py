import json

import pytest

from jarvis.memory import MemoryError_


def test_memory_crud_search_export(core):
    m = core.memory.add("Hisobot har dushanba tayyorlanadi", "long_term", source="test", confidence=0.9)
    assert core.memory.search("hisobot")[0]["id"] == m["id"]
    core.memory.update(m["id"], "Hisobot har juma tayyorlanadi")
    assert core.memory.search("juma")
    assert json.loads(core.memory.export())[0]["source"] == "test"
    core.memory.delete(m["id"])
    assert core.memory.search("juma") == []


def test_memory_rejects_secrets_and_bad_kind(core):
    with pytest.raises(MemoryError_):
        core.memory.add("POS parol: Qwerty12345")
    with pytest.raises(MemoryError_):
        core.memory.add("salom", kind="nomalum")


def test_conflict_is_flagged_not_merged(core):
    core.memory.add("Ombor hisoboti dushanba kuni yuboriladi")
    m = core.memory.add("Ombor hisoboti dushanba kuni yuborilmaydi emas")
    assert m["status"] == "conflict" and m["conflicts_with"]
    assert len(core.memory.list()) == 2


def test_audit_never_stores_secrets(core):
    core.audit.log("t", "login token=SuperSecret999", result="api_key: sk-abcdefghijklmnopqrstu")
    row = core.audit.recent(1)[0]
    assert "SuperSecret999" not in row["action"] and "sk-abc" not in row["result"]
