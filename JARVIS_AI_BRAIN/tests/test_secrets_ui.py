import pytest

from jarvis import secrets


class FakeKeyring:
    store = {}

    @classmethod
    def set_password(cls, svc, name, value):
        cls.store[(svc, name)] = value

    @classmethod
    def get_password(cls, svc, name):
        return cls.store.get((svc, name))

    @classmethod
    def delete_password(cls, svc, name):
        cls.store.pop((svc, name), None)


@pytest.fixture
def kr(monkeypatch):
    import sys
    FakeKeyring.store = {}
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring)
    return FakeKeyring


def test_secret_api_write_only(client, kr):
    r = client.post("/api/secrets", json={"name": "telegram_bot_token", "value": "123:ABC_maxfiy"})
    assert r.status_code == 200 and "maxfiy" not in r.text
    st = {x["name"]: x["set"] for x in client.get("/api/secrets").json()}
    assert st["telegram_bot_token"] is True and "123:ABC" not in client.get("/api/secrets").text
    assert "123:ABC_maxfiy" not in client.get("/api/audit").text
    assert client.post("/api/secrets", json={"name": "auth_pin", "value": "x"}).status_code == 400   # ruxsat etilmagan nom
    assert client.post("/api/secrets", json={"name": "pos_api_token", "value": ""}).status_code == 400
    client.post("/api/secrets/delete", json={"name": "telegram_bot_token"})
    assert not secrets.has_secret("telegram_bot_token")


def test_instagram_accounts_editable(client):
    assert client.post("/api/settings", json={"instagram_accounts": [{"name": "shop", "ig_user_id": "17841400000"}]}).status_code == 200
    assert client.get("/api/settings").json()["instagram_accounts"] == [{"name": "shop", "ig_user_id": "17841400000"}]
    assert client.post("/api/settings", json={"instagram_accounts": [{"name": "Shop!", "ig_user_id": "x"}]}).status_code == 400
    assert any(x["name"] == "instagram_token_shop" for x in client.get("/api/secrets").json())
