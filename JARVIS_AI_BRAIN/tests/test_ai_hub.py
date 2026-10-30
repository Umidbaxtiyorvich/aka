"""AI Provider Hub + Smart Router: sun'iy (mock) provayder serverlari bilan. Real API kalitlari ishlatilmaydi."""
import json
import sys

import pytest

from jarvis import net


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


class Cloud:
    """Bir nechta provayderni taqlid qiladi: host bo'yicha xatti-harakat."""

    def __init__(self):
        self.calls, self.mode = [], {}

    def __call__(self, method, url, data, headers, timeout):
        self.calls.append((method, url, headers))
        body = json.loads(data) if data else {}
        host = url.split("/")[2]
        m = self.mode.get(host, "ok")
        if m == "down":
            raise net.NetError("connection refused")
        if m == "badkey":
            return 401, json.dumps({"error": {"message": "Incorrect API key provided"}})
        if m == "quota" and method == "POST":
            return 429, json.dumps({"error": {"message": "You exceeded your current quota", "type": "insufficient_quota"}})
        if m == "billing" and method == "POST":
            return 402, json.dumps({"error": "Payment required"})
        if url.endswith("/api/tags"):
            return 200, json.dumps({"models": [{"name": "qwen2.5:1.5b"}, {"name": "moondream:latest"}]})
        if url.endswith("/api/chat"):
            return 200, json.dumps({"message": {"content": "OK lokal"}})
        if url.endswith("/models"):
            if m == "nomodels":
                return 404, "not found"
            if "openrouter" in host:
                return 200, json.dumps({"data": [
                    {"id": "google/gemini-2.5-flash", "context_length": 1000000, "pricing": {"prompt": "0.0000003", "completion": "0.0000025"},
                     "architecture": {"input_modalities": ["text", "image", "file"], "output_modalities": ["text"]}, "supported_parameters": ["tools", "response_format"]},
                    {"id": "meta-llama/llama-3.3-8b-instruct:free", "context_length": 8000, "pricing": {"prompt": "0", "completion": "0"},
                     "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}}]})
            return 200, json.dumps({"data": [{"id": "gpt-4.1-mini"}, {"id": "text-embedding-3-small"}, {"id": "gpt-image-1"}]})
        if url.endswith("/key"):
            return 200, json.dumps({"data": {"limit": 10, "usage": 0.5}})
        if "/chat/completions" in url:
            content = " ".join(str(x.get("content")) for x in body.get("messages", []))
            return 200, json.dumps({"choices": [{"message": {"content": f"OK {body.get('model')} :: {content[:20]}"}}],
                                    "usage": {"prompt_tokens": 10, "completion_tokens": 3}})
        return 404, "{}"


@pytest.fixture
def cloud(core, monkeypatch):
    FakeKeyring.store = {}
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring)
    f = Cloud()
    monkeypatch.setattr(net, "TRANSPORT", f)
    core.settings.ai_providers = []
    core.settings.save = lambda: None
    return f


def _paid_ok(core):
    core.settings.paid_ai_allowed, core.settings.daily_cost_limit, core.settings.monthly_cost_limit = True, 1.0, 10.0


def test_catalog_is_extensible(core, cloud):
    cat = core.ai_hub.catalog()["providers"]
    for k in ("openai", "gemini", "claude", "openrouter", "groq", "deepseek", "mistral", "xai", "cohere", "perplexity", "together", "fireworks",
              "nvidia", "azure_openai", "bedrock", "vertex", "huggingface", "github", "replicate", "vercel", "litellm", "qwen", "cerebras",
              "sambanova", "deepinfra", "novita", "ollama", "lmstudio", "vllm", "custom", "omniroute"):
        assert k in cat, k
    core.settings.ai_custom_catalog = {"myai": {"title": "MyAI", "kind": "openai_compatible", "base_url": "https://api.myai.uz/v1", "model": "m1"}}
    assert core.ai_hub.catalog()["providers"]["myai"]["custom"] is True
    p = core.ai_hub.add(catalog_id="myai", api_key="sk-myai-" + "x" * 20)
    assert p["base_url"] == "https://api.myai.uz/v1" and p["key_set"]


def test_add_verify_free_steps_without_paid_permission(core, cloud):
    p = core.ai_hub.add(catalog_id="openai", api_key="sk-test-" + "a" * 30)
    assert "sk-test" not in json.dumps(p)                     # kalit hech qachon qaytmaydi
    v = core.ai_hub.verify(p["id"])
    names = [s["step"] for s in v["steps"]]
    assert "modellar" in names and v["status"] == "connected" and "o'tkazilmadi" in v["note"]
    test_step = next(s for s in v["steps"] if s["step"] == "test")
    assert test_step["ok"] is None and "pullik" in test_step["detail"]
    assert not any(c[0] == "POST" for c in cloud.calls)       # ruxsatsiz pullik so'rov yuborilmadi
    caps = {m["model_id"]: m for m in core.ai_hub.models("openai")}
    assert caps["text-embedding-3-small"]["caps"] == ["embeddings"] and caps["gpt-image-1"]["caps"] == ["image_generation"]
    assert caps["gpt-4.1-mini"]["caps_source"] == "name_guess"
    _paid_ok(core)
    v = core.ai_hub.verify("openai")
    assert v["status"] == "connected" and next(s for s in v["steps"] if s["step"] == "test")["ok"] is True


def test_openrouter_provider_caps_prices_and_key_check(core, cloud):
    core.ai_hub.add(catalog_id="openrouter", api_key="sk-or-" + "b" * 30, model="google/gemini-2.5-flash")
    v = core.ai_hub.verify("openrouter", test_model=False)
    assert any(s["step"] == "kalit" and s["ok"] for s in v["steps"])
    ms = {m["model_id"]: m for m in core.ai_hub.models("openrouter")}
    g = ms["google/gemini-2.5-flash"]
    assert g["caps_source"] == "provider" and {"image_understanding", "file_understanding", "tool_calling", "long_context"} <= set(g["caps"])
    assert abs(g["price_in"] - 0.0003) < 1e-9 and ms["meta-llama/llama-3.3-8b-instruct:free"]["free"] == 1


@pytest.mark.parametrize("mode,status", [("badkey", "invalid_key"), ("down", "connection_failed"), ("quota", "quota_exceeded"), ("billing", "billing_required")])
def test_verify_error_statuses(core, cloud, mode, status):
    _paid_ok(core)
    cloud.mode["api.groq.com"] = mode
    core.ai_hub.add(catalog_id="groq", api_key="gsk_" + "c" * 30)
    assert core.ai_hub.verify("groq")["status"] == status


def test_models_endpoint_missing_is_partial_not_failed(core, cloud):
    _paid_ok(core)
    cloud.mode["api.deepseek.com"] = "nomodels"
    core.ai_hub.add(catalog_id="deepseek", api_key="sk-ds-" + "d" * 30)
    v = core.ai_hub.verify("deepseek")
    assert v["status"] == "partially_supported" and "ro'yxati olinmadi" in v["note"]
    core.ai_hub.add_model("deepseek", "deepseek-reasoner")
    assert "reasoning" in {m["model_id"]: m for m in core.ai_hub.models("deepseek")}["deepseek-reasoner"]["caps"]


def test_no_key_not_configured_and_local_ollama(core, cloud):
    core.ai_hub.add(catalog_id="mistral")
    assert core.ai_hub.verify("mistral")["status"] == "not_configured"
    core.ai_hub.add(catalog_id="ollama")
    v = core.ai_hub.verify("ollama")
    assert v["status"] == "connected" and core.ai_hub.get("ollama")["local"] and not core.ai_hub.get("ollama")["paid"]
    assert core.ai_hub.add(catalog_id="lmstudio")["needs_key"] is False
    with pytest.raises(Exception):
        core.ai_hub.add(catalog_id="custom", pid="bad", base_url="http://evil.example.com/v1")      # tashqi http ruxsat yo'q


def test_router_capability_strategy_and_fallback(core, cloud):
    _paid_ok(core)
    core.ai_hub.add(catalog_id="ollama")
    core.ai_hub.verify("ollama")                               # moondream → image_understanding (taxmin)
    core.ai_hub.add(catalog_id="openai", api_key="sk-test-" + "a" * 30, price_in=0.4, price_out=1.6)
    core.ai_hub.verify("openai")
    # Rasm vazifasi: ollama ichidan vision modeli tanlanadi
    plan = core.ai.plan([{"role": "user", "content": "rasmni tasvirla"}], purpose="vision", private=True)
    first = plan["candidates"][0]
    assert first["id"] == "ollama" and first["model"] == "moondream:latest" and plan["capability"] == "image_understanding"
    # free_only — pullik o'tkazib yuboriladi
    core.settings.ai_strategy = "free_only"
    plan = core.ai.plan([{"role": "user", "content": "salom"}])
    assert all(not p["paid"] for p in plan["candidates"]) and any("bepul" in s["reason"] for s in plan["skipped"])
    # Pullikdan oldin tasdiq
    core.settings.ai_strategy, core.settings.ai_confirm_paid = "quality", True
    r = core.ai.route([{"role": "user", "content": "murakkab tahlil qil"}], purpose="reasoning")
    assert r["route"]["provider"] == "ollama" and r["route"]["paid_confirm_needed"]
    r = core.ai.route([{"role": "user", "content": "murakkab tahlil qil"}], purpose="reasoning", allow_paid=True)
    assert r["route"]["provider"] == "openai"
    # Ishlatish paytida kvota tugadi → keyingi so'rov boshqa modelga
    cloud.mode["api.openai.com"] = "quota"
    r = core.ai.route([{"role": "user", "content": "yana tahlil"}], purpose="reasoning", allow_paid=True)
    assert r["route"]["provider"] == "ollama" and r["route"]["fallbacks"][0]["provider"] == "openai"
    assert core.ai_hub.blocked("openai")
    r = core.ai.route([{"role": "user", "content": "yana"}], purpose="reasoning", allow_paid=True)
    assert "Kvota" in r["route"]["fallbacks"][0]["error"]
    log = core.db.query("SELECT provider, ok, fallback_from FROM ai_usage WHERE purpose='reasoning' ORDER BY id")
    assert any(x["fallback_from"] == "openai" and x["ok"] for x in log)


def test_budget_per_request_and_allowed_providers(core, cloud):
    _paid_ok(core)
    core.ai_hub.add(catalog_id="openai", api_key="sk-test-" + "a" * 30, price_in=50, price_out=50)
    core.ai_hub.add(catalog_id="ollama")
    core.settings.ai_max_request_cost = 0.01
    r = core.ai.route([{"role": "user", "content": "murakkab tahlil " * 50}], purpose="reasoning")
    assert r["route"]["provider"] == "ollama" and "maksimal" in r["route"]["fallbacks"][0]["error"]
    core.settings.ai_max_request_cost, core.settings.ai_allowed_providers = 0, ["ollama"]
    plan = core.ai.plan([{"role": "user", "content": "salom"}])
    assert [p["id"] for p in plan["candidates"]] == ["ollama", "offline"]


def test_all_down_uses_internal_functions(core, cloud):
    cloud.mode["127.0.0.1:11434"] = "down"
    core.ai_hub.add(catalog_id="ollama")
    r = core.ai.route([{"role": "user", "content": "salom"}])
    assert r["route"]["provider"] == "offline"


def test_hub_api_flow(client, core, cloud):
    r = client.post("/api/ai/hub/providers", json={"catalog_id": "gemini", "api_key": "AIza" + "e" * 35})
    assert r.status_code == 200 and "AIza" not in r.text and r.json()["verification"]["status"] == "connected"
    assert client.get("/api/ai/hub/overview").json()["providers"] == 1
    assert client.post("/api/ai/hub/providers/gemini/default?task=code").json()["routes"]["code"] == "gemini"
    assert client.post("/api/ai/hub/providers/gemini/caps", json={"model_id": "gemini-2.5-flash", "caps": ["text", "coding"]}).status_code == 200
    assert {m["model_id"]: m for m in client.get("/api/ai/hub/models?provider=gemini").json()}["gemini-2.5-flash"]["caps_source"] == "user"
    assert client.post("/api/ai/hub/providers/gemini/caps", json={"model_id": "x", "caps": ["telepathy"]}).status_code == 400
    assert "current" in client.get("/api/ai/live").json()
    assert client.post("/api/settings", json={"ai_strategy": "magic"}).status_code == 400
    assert client.delete("/api/ai/hub/providers/gemini").status_code == 200
    assert not core.ai_hub.list() and "AIza" not in client.get("/api/audit").text
