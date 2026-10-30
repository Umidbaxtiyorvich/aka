import json

import pytest

from jarvis import net
from jarvis.ai_engine import AIError


class Fake:
    def __init__(self):
        self.calls, self.ollama_up, self.cloud_fail = [], True, False

    def __call__(self, method, url, data, headers, timeout):
        self.calls.append(url)
        body = json.loads(data) if data else {}
        if "/api/tags" in url:
            if not self.ollama_up:
                raise net.NetError("connection refused")
            return 200, json.dumps({"models": [{"name": "qwen2.5:1.5b"}, {"name": "qwen2.5:7b"}]})
        if "/api/chat" in url:
            if not self.ollama_up:
                raise net.NetError("connection refused")
            return 200, json.dumps({"message": {"content": f"lokal:{body['model']}"}, "prompt_eval_count": 12, "eval_count": 5})
        if "/chat/completions" in url:
            if self.cloud_fail:
                return 500, "{}"
            return 200, json.dumps({"choices": [{"message": {"content": "bulut javobi"}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 500}})
        return 404, "{}"


@pytest.fixture
def fake(core, monkeypatch):
    f = Fake()
    monkeypatch.setattr(net, "TRANSPORT", f)
    monkeypatch.setenv("JARVIS_AI_KEY_CLOUD", "sk-test-" + "k" * 20)
    core.settings.ai_providers = [
        {"id": "light", "kind": "ollama", "model": "qwen2.5:1.5b", "tier": "light"},
        {"id": "strong", "kind": "ollama", "model": "qwen2.5:7b", "tier": "strong"},
        {"id": "cloud", "kind": "openai_compatible", "base_url": "https://api.example.com/v1", "model": "big",
         "tier": "strong", "paid": True, "price_in_per_1k": 0.01, "price_out_per_1k": 0.03},
    ]
    core.reload_ai()
    return f


def msg(t):
    return [{"role": "user", "content": t}]


def test_simple_goes_light_complex_goes_strong(core, fake):
    r = core.ai.route(msg("salom, qandaysan?"))
    assert r["route"]["provider"] == "light" and r["route"]["tokens_measured"] and r["route"]["tokens_in"] == 12
    r = core.ai.route(msg("Bu python kodidagi xatoni tahlil qil: ```def f(: pass```"))
    assert r["route"]["provider"] == "strong" and "murakkab" in r["route"]["reason"]


def test_private_data_stays_local(core, fake):
    fake.ollama_up = False
    core.reload_ai()
    core.settings.paid_ai_allowed, core.settings.daily_cost_limit, core.settings.monthly_cost_limit = True, 5, 50
    r = core.ai.route(msg("Mijoz pasporti AB1234567, telefon +998 90 123 45 67 — tahlil qil"))
    assert r["route"]["provider"] == "offline"                                  # bulutga yuborilmadi
    assert any("maxfiy" in s["reason"] for s in r["route"]["skipped"])
    assert not any("/chat/completions" in c for c in fake.calls)


def test_fallback_is_visible_and_paid_needs_limits(core, fake):
    fake.ollama_up = False
    core.reload_ai()
    r = core.ai.route(msg("murakkab tahlil kerak"))
    assert r["route"]["provider"] == "offline"
    assert any("Pullik AI o'chirilgan" in a["error"] for a in r["route"]["fallbacks"])
    core.settings.paid_ai_allowed = True
    r = core.ai.route(msg("murakkab tahlil kerak"))
    assert any("limiti belgilanmagan" in a["error"] for a in r["route"]["fallbacks"])
    core.settings.daily_cost_limit, core.settings.monthly_cost_limit = 1.0, 10.0
    r = core.ai.route(msg("murakkab tahlil kerak"))
    assert r["route"]["provider"] == "cloud" and r["route"]["cost"] == pytest.approx(0.025) and r["route"]["cost_measured"]
    assert "Avval urinilgan" in core.ai.notice(r["route"])


def test_limit_reached_stops_paid(core, fake):
    fake.ollama_up = False
    core.reload_ai()
    core.settings.paid_ai_allowed, core.settings.daily_cost_limit, core.settings.monthly_cost_limit = True, 0.03, 10.0
    assert core.ai.route(msg("tahlil qil"))["route"]["provider"] == "cloud"      # 0.025
    r = core.ai.route(msg("tahlil qil"))                                           # 0.025+taxmin > 0.03
    assert r["route"]["provider"] == "offline" and any("Kunlik xarajat" in a["error"] for a in r["route"]["fallbacks"])
    assert any(n["category"] == "cost" for n in core.notifier.list())


def test_failures_recorded_and_all_fail(core, fake):
    fake.ollama_up = False
    fake.cloud_fail = True
    core.settings.ai_providers = [p for p in core.settings.ai_providers if p["id"] == "cloud"] + [
        {"id": "offline", "kind": "offline", "model": "rule-based", "tier": "fallback", "enabled": False}]
    core.settings.paid_ai_allowed, core.settings.daily_cost_limit, core.settings.monthly_cost_limit = True, 1, 10
    core.reload_ai()
    r = core.ai.route(msg("tahlil"))           # offline o'chirib bo'lmaydi — doim oxirgi zaxira
    assert r["route"]["provider"] == "offline"
    t = core.guard.today()
    assert t["failed"] == 1 and t["requests"] == 2
    assert core.guard.providers()


def test_daily_request_limit(core, fake):
    core.settings.daily_request_limit = 1
    core.ai.route(msg("salom"))
    with pytest.raises(AIError):
        core.settings.ai_providers = [p for p in core.settings.ai_providers if p["id"] == "light"]
        core.reload_ai()
        core.ai.route(msg("salom"))   # light bloklanadi; offline ham guard'dan o'tadi -> hech biri
    s = core.guard.summary()
    assert s["process"]["measured"] and s["today"]["tokens_measured"] == 17


def test_router_api_and_settings_validation(client):
    assert client.get("/api/ai/router").json()["providers"][-1]["kind"] == "offline"
    assert client.post("/api/ai/route-preview", json={"text": "kod xatosini tahlil qil"}).json()["complexity"] == "complex"
    assert client.get("/api/guard").json()["limits"]["paid_ai_allowed"] is False
    assert client.post("/api/settings", json={"medium_auto_actions": ["pos_sotuv"]}).status_code == 400
    assert client.post("/api/settings", json={"ai_providers": [{"id": "x", "kind": "openai_compatible", "model": "m",
                                                                 "base_url": "http://insecure"}]}).status_code == 400
    assert client.post("/api/settings", json={"daily_cost_limit": 2.5}).json()["daily_cost_limit"] == 2.5
    assert any(r["risk"] == "forbidden" for r in client.get("/api/policy").json())
    assert client.post("/api/policy/evaluate", json={"op": "shell_command", "params": {"command": "format c:"}}).json()["risk"] == "forbidden"


def test_recommend_setup_for_8gb_gtx1650():
    from jarvis.system_info import recommend_setup
    r = recommend_setup(7.8, 4.0)
    assert (r["light"], r["strong"], r["vision"]) == ("qwen2.5:1.5b", "qwen2.5:3b", "moondream")
    assert "medvram" in r["image_gen"]
    assert "Tavsiya etilmaydi" in recommend_setup(7.8, None)["image_gen"]
    assert recommend_setup(4, None)["light"] == "qwen2.5:0.5b"
