import pytest

from jarvis.approval import ApprovalError


def test_policy_categories(core):
    p = core.policy
    assert p.evaluate("read").risk == "low" and not p.evaluate("read").requires_approval
    assert p.evaluate("settings_change").requires_approval
    assert p.evaluate("pos_sotuv").risk == "high" and p.evaluate("pos_sotuv").level == "D"
    assert p.evaluate("bypass_captcha").risk == "forbidden"
    assert p.evaluate("nomalum_amal").risk == "high"                       # noma'lum — ehtiyot
    assert p.evaluate("shell_command", command="format c:").risk == "forbidden"
    assert p.evaluate("shell_command", command="curl http://x").risk == "forbidden"   # allowlist'da yo'q
    assert p.evaluate("shell_read", "A", command="git status").risk == "low"


def test_requested_level_cannot_go_below_policy(core):
    a = core.approvals.request(action_type="instagram_publish", target="ig", level="A", payload={"x": 1},
                               summary="past daraja so'rash urinishi", requested_by="t")
    assert a["level"] == "D" and a["status"] == "pending" and a["risk"] == "high" and a["reversible"] == 0
    with pytest.raises(ApprovalError, match="Taqiqlangan"):
        core.approvals.request(action_type="bypass_captcha", target="pos", level="E", payload={}, summary="x", requested_by="t")
    assert any(r["approval_status"] == "forbidden" for r in core.audit.recent(5))


def test_medium_auto_is_opt_in(core):
    a = core.approvals.request(action_type="settings_change", target="s", level="C", payload={"k": 1}, summary="s", requested_by="t")
    assert a["status"] == "pending"
    core.settings.medium_auto_actions = ["settings_change"]
    b = core.approvals.request(action_type="settings_change", target="s", level="C", payload={"k": 2}, summary="s", requested_by="t")
    assert b["status"] == "approved"
    core.settings.medium_auto_actions = ["pos_sotuv"]                       # high hech qachon avtomatik emas
    c = core.approvals.request(action_type="pos_sotuv", target="pos", level="D", payload={"k": 3}, summary="s", requested_by="t")
    assert c["status"] == "pending"
