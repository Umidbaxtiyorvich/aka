"""Telegram Control Center: bitta ega, ulash kodi, telefon tasdig'i, tugmali tasdiq, begonalar, ovoz, hodisalar."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from jarvis import net

TOKEN = "123456:" + "T" * 35
OWNER = {"id": 111, "first_name": "Umid", "username": "umid"}


class FakeTG:
    """Telegram Bot API o'rnini bosadi: yuborilgan so'rovlarni yozib boradi."""

    def __init__(self):
        self.calls, self.updates, self.mid = [], [], 100

    def __call__(self, method, url, data, headers, timeout):
        api = url.rsplit("/", 1)[-1]
        body = json.loads(data) if data and headers.get("Content-Type") == "application/json" else {}
        self.calls.append((api, body))
        if api == "getMe":
            return 200, json.dumps({"ok": True, "result": {"id": 1, "username": "jarvis_test_bot", "first_name": "JARVIS"}})
        if api == "getUpdates":
            res, self.updates = self.updates, []
            return 200, json.dumps({"ok": True, "result": res})
        if api == "getFile":
            return 200, json.dumps({"ok": True, "result": {"file_path": "voice/1.oga"}})
        self.mid += 1
        return 200, json.dumps({"ok": True, "result": {"message_id": self.mid}})

    def sent(self, api="sendMessage"):
        return [b for a, b in self.calls if a == api]


@pytest.fixture
def tg(core, monkeypatch):
    monkeypatch.setenv("JARVIS_TELEGRAM_BOT_TOKEN", TOKEN)
    fake = FakeTG()
    monkeypatch.setattr(net, "TRANSPORT", fake)
    return fake


def msg(uid, text=None, chat=None, ctype="private", **extra):
    m = {"from": {"id": uid, "first_name": "X"} if uid != OWNER["id"] else OWNER, "chat": {"id": chat or uid, "type": ctype}}
    if text is not None:
        m["text"] = text
    m.update(extra)
    return {"message": m}


def pair(core):
    code = core.telegram.pairing_start()["code"]
    assert core.telegram.handle_update(msg(111, f"/start {code}")) == "paired"
    return code


def test_pairing_single_owner_and_strangers_ignored(core, tg):
    st = core.telegram.pairing_start()
    assert len(st["code"]) == 6 and st["link"] == f"https://t.me/jarvis_test_bot?start={st['code']}"
    assert core.db.one("SELECT code_hash FROM telegram_pairing ORDER BY id DESC LIMIT 1")["code_hash"] != st["code"]   # faqat xesh
    # Noto'g'ri kod va kodsiz /start — javob yo'q
    assert core.telegram.handle_update(msg(999, "/start 000000")) is None
    assert core.telegram.handle_update(msg(999, "/start")) is None
    assert tg.sent() == []
    assert core.telegram.handle_update(msg(111, f"/start {st['code']}")) == "paired"
    assert core.telegram.configured() and core.telegram.owner()["user_id"] == 111
    # Kod bir martalik: boshqa odam o'sha kod bilan egallab ololmaydi
    assert core.telegram.handle_update(msg(999, f"/start {st['code']}")) is None
    assert core.telegram.handle_update(msg(999, "/status")) is None
    assert {m["chat_id"] for m in tg.sent()} == {111}                  # begonaga hech narsa yuborilmadi
    assert "begona" in tg.sent()[-1]["text"]                           # egasi ogohlantirildi
    assert core.telegram.owner()["user_id"] == 111
    # Guruh chatidan ega yozsa ham bajarilmaydi
    assert core.telegram.handle_update(msg(111, "/status", chat=-500, ctype="group")) is None
    # Egasi: buyruqlar ishlaydi
    assert "Holat: Online" in core.telegram.handle_update(msg(111, "/status"))
    assert any(n["category"] == "security" and "begona" in n["title"] for n in core.notifier.list())
    assert all(TOKEN not in json.dumps(r) for r in core.audit.recent(100))


def test_pairing_code_bruteforce_locked(core, tg):
    code = core.telegram.pairing_start()["code"]
    for _ in range(5):
        core.telegram.handle_update(msg(999, "/start 123123"))
    assert core.telegram.handle_update(msg(111, f"/start {code}")) is None     # 5 xatodan keyin yopiq
    assert not core.telegram.configured()


def test_pairing_code_expires(core, tg):
    code = core.telegram.pairing_start()["code"]
    core.db.execute("UPDATE telegram_pairing SET expires_at=?", ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),))
    assert core.telegram.handle_update(msg(111, f"/start {code}")) is None


def test_phone_verification_with_own_contact(core, tg):
    core.settings.telegram_owner_phone = "+998 90 123 45 67"
    code = core.telegram.pairing_start()["code"]
    assert core.telegram.handle_update(msg(111, f"/start {code}")) == "contact_requested"
    assert tg.sent()[-1]["reply_markup"]["keyboard"][0][0]["request_contact"] is True
    assert not core.telegram.configured()
    # Boshqa odamning kontakti (user_id mos emas) — rad
    assert core.telegram.handle_update(msg(111, contact={"phone_number": "998901234567", "user_id": 222})) == "phone_rejected"
    assert not core.telegram.configured()
    code = core.telegram.pairing_start()["code"]
    core.telegram.handle_update(msg(111, f"/start {code}"))
    assert core.telegram.handle_update(msg(111, contact={"phone_number": "+998901234567", "user_id": 111})) == "paired"
    o = core.telegram.owner()
    assert o["active"] and o["phone_verified"] and o["phone"] == "+998901234567"


def test_token_change_revokes_owner(core, tg, monkeypatch):
    pair(core)
    assert core.telegram.configured()
    monkeypatch.setenv("JARVIS_TELEGRAM_BOT_TOKEN", "999999:" + "Z" * 35)
    assert not core.telegram.configured()                 # token izi mos emas
    core.telegram.on_token_changed()
    assert core.telegram.owner() is None
    core.telegram.revoke()
    assert core.telegram.status()["owner"] is None


def _pending(core, level="D"):
    return core.approvals.request(action_type="instagram_publish", target="instagram", level=level, payload={"x": 1},
                                  summary="Instagram'ga Reels joylash", requested_by="test")


def _cb(uid, data, chat=None):
    return {"callback_query": {"id": "cb1", "from": {"id": uid}, "data": data,
                               "message": {"message_id": 5, "chat": {"id": chat or uid, "type": "private"}, "text": "..."}}}


def test_approval_buttons_owner_only_single_use(core, tg):
    pair(core)
    appr = _pending(core)
    m = tg.sent()[-1]
    assert "ruxsatingiz kerak" in m["text"] and "Reels" in m["text"]
    yes, no = (b["callback_data"] for b in m["reply_markup"]["inline_keyboard"][0])
    # Begona tugmani bossa — ishlamaydi
    assert core.telegram.handle_update(_cb(999, yes)) is None
    assert core.approvals.get(appr["id"])["status"] == "pending"
    # Soxta nonce — ishlamaydi
    assert "yaroqsiz" in core.telegram.handle_update(_cb(111, yes.rsplit(":", 2)[0] + ":XXXX:y"))
    # Egasi tasdiqlaydi
    assert "Tasdiqlandi" in core.telegram.handle_update(_cb(111, yes))
    assert core.approvals.get(appr["id"])["status"] == "approved"
    # Qayta ishlatib bo'lmaydi
    assert "allaqachon" in core.telegram.handle_update(_cb(111, no))
    assert core.approvals.get(appr["id"])["status"] == "approved"
    assert any("Telegram orqali qaror" in r["action"] for r in core.audit.recent(30))


def test_approval_expired_and_reject_and_commands(core, tg):
    pair(core)
    a1 = _pending(core)
    core.db.execute("UPDATE telegram_approvals SET expires_at=? WHERE approval_id=?",
                    ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), a1["id"]))
    yes = tg.sent()[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    assert "muddati o'tgan" in core.telegram.handle_update(_cb(111, yes)).lower()
    assert core.approvals.get(a1["id"])["status"] == "pending"
    a2 = core.approvals.request(action_type="pos_write", target="pos", level="D", payload={"y": 2}, summary="POS yozuvi", requested_by="t")
    assert "Rad etildi" in core.telegram.command(f"/reject {a2['id']}")
    assert core.approvals.get(a2["id"])["status"] == "rejected"
    assert "/approve ID" in core.telegram.command("/approve")


def test_level_e_only_in_dashboard(core, tg):
    pair(core)
    _pending(core, level="E")
    m = tg.sent()[-1]
    assert "faqat dashboardda" in m["text"] and "reply_markup" not in m


def test_payload_change_invalidates_telegram_button(core, tg):
    pair(core)
    appr = _pending(core)
    yes = tg.sent()[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    core.db.execute("UPDATE telegram_approvals SET payload_hash='boshqa' WHERE approval_id=?", (appr["id"],))
    assert "Qabul qilinmadi" in core.telegram.handle_update(_cb(111, yes))
    assert core.approvals.get(appr["id"])["status"] == "pending"


def test_event_filtering_and_startup_message(core, tg):
    core.notifier.notify("oddiy", severity="info")
    assert tg.sent() == []                                         # ega ulanmagan
    pair(core)
    n0 = len(tg.sent())
    core.notifier.notify("oddiy tizim xabari", severity="info", category="system")
    assert len(tg.sent()) == n0                                    # 'system' info yuborilmaydi
    n = core.notifier.notify("POS ishlamayapti", "timeout", severity="critical", category="pos")
    assert "telegram(1)" in n["delivered"] and "JARVIS: POS ishlamayapti" in tg.sent()[-1]["text"]
    core.notifier.notify("Tizim ishga tushdi", "Holat: Online", category="startup")
    assert "ishga tushdi" in tg.sent()[-1]["text"]
    core.settings.telegram_events = ["error"]
    k = len(tg.sent())
    core.notifier.notify("Tizim ishga tushdi", category="startup")
    assert len(tg.sent()) == k


def test_stop_command_pauses_automation(core, tg):
    pair(core)
    assert "to'xtatildi" in core.telegram.command("/stop") and core.automation_paused
    core.resume_automation()
    assert not core.automation_paused


def test_voice_command_requires_confirmation(core, tg, monkeypatch):
    pair(core)
    monkeypatch.setattr(net, "BYTES_TRANSPORT", lambda url, timeout: (200, b"OggS-fake"))

    class FakeModel:
        pass
    core.voice._model = FakeModel()
    monkeypatch.setattr(core.voice, "transcribe", lambda path, language="uz": {"text": "/status"})
    assert core.telegram.handle_update(msg(111, voice={"file_id": "F1", "duration": 2})) == "voice_confirm"
    m = tg.sent()[-1]
    assert "Tushundim" in m["text"] and "/status" in m["text"]
    yes = m["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    assert core.telegram.handle_update(_cb(111, yes)) == "Bajarildi."
    assert "Holat: Online" in tg.sent()[-2]["text"] or "Holat: Online" in tg.sent()[-1]["text"]
    assert "ishlatilgan" in core.telegram.handle_update(_cb(111, yes))


def test_voice_unavailable_is_honest(core, tg):
    pair(core)
    core.voice._model = None
    assert core.telegram.handle_update(msg(111, voice={"file_id": "F1"})) == "stt_unavailable"
    assert "yoqilmagan" in tg.sent()[-1]["text"]


def test_instagram_prepare_from_telegram(core, tg, monkeypatch):
    pair(core)
    assert "akkaunti ulanmagan" in core.telegram.command("Instagram'ga Reels tayyorla")
    core.settings.instagram_accounts = [{"name": "mango", "ig_user_id": "17841400000"}]
    r = core.telegram.command("Instagram sahifamga bugun Reels joylashga tayyorla: chegirma haftaligi")
    assert "loyihasi" in r and "https://" in r                     # media yo'q — halol aytadi
    r = core.telegram.command("Instagram'ga Reels tayyorla: https://cdn.example.com/v.mp4 chegirma haftaligi")
    assert "Tasdiqlash tugmalari" in r
    m = tg.sent()[-1]
    assert "Instagram" in m["text"] and m["reply_markup"]["inline_keyboard"][0][0]["text"].startswith("✅")


def test_telegram_api_endpoints(client, core, tg):
    r = client.post("/api/telegram/pair").json()
    assert r["code"] and "t.me/jarvis_test_bot" in r["link"]
    core.telegram.handle_update(msg(111, f"/start {r['code']}"))
    st = client.get("/api/telegram/status").json()
    assert st["owner"]["user_id"] == 111 and st["configured"] and "Twilio" in st["calls"]
    assert client.get("/api/telegram/history").json()["messages"]
    assert client.post("/api/telegram/revoke").json()["owner"] is None
