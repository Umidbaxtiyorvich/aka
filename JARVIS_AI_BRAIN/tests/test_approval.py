import pytest

from jarvis.approval import ApprovalError

DOC = {"doc_type": "kirim", "version": 1, "supplier": "Ali MChJ", "items": [{"sku": "A1", "qty": 10, "price": 5000}], "total": 50000}


def _req(core, payload=DOC, key=None):
    return core.approvals.request(action_type="pos_insert", target="pos.example", account="shop1", level="D",
                                  payload=payload, summary="Kirim hujjati", requested_by="pos_agent", idempotency_key=key)


def test_external_action_requires_exact_hash(core):
    a = _req(core)
    assert a["status"] == "pending"
    with pytest.raises(ApprovalError):
        core.approvals.authorize_execution(a["id"], DOC)
    with pytest.raises(ApprovalError):
        core.approvals.decide(a["id"], True, "notogri-xesh")
    core.approvals.decide(a["id"], True, a["payload_hash"])
    assert core.approvals.authorize_execution(a["id"], DOC)["status"] == "approved"


def test_changed_document_invalidates_approval(core):
    a = _req(core)
    core.approvals.decide(a["id"], True, a["payload_hash"])
    changed = DOC | {"total": 60000}
    with pytest.raises(ApprovalError):
        core.approvals.authorize_execution(a["id"], changed)
    assert core.approvals.get(a["id"])["status"] == "invalidated"
    new = core.approvals.invalidate_for_change(a["id"], changed)
    assert new["status"] == "pending" and new["payload_hash"] != a["payload_hash"]


def test_duplicate_and_unknown_protection(core):
    a = _req(core, key="kirim-42")
    assert _req(core, key="kirim-42")["id"] == a["id"]
    core.approvals.decide(a["id"], True, a["payload_hash"])
    core.approvals.mark_result(a["id"], "executed")
    with pytest.raises(ApprovalError, match="allaqachon"):
        core.approvals.authorize_execution(a["id"], DOC)
    b = _req(core, payload=DOC | {"version": 2})
    core.approvals.decide(b["id"], True, b["payload_hash"])
    core.approvals.mark_result(b["id"], "unknown")
    with pytest.raises(ApprovalError, match="noma'lum"):
        core.approvals.authorize_execution(b["id"], DOC | {"version": 2})


def test_read_level_auto_and_secret_rejected(core):
    a = core.approvals.request(action_type="read", target="x", level="A", payload={}, summary="o'qish", requested_by="t")
    assert a["status"] == "approved"
    with pytest.raises(ApprovalError):
        core.approvals.request(action_type="x", target="x", level="D", payload={"note": "password=hunter22"},
                               summary="x", requested_by="t")
