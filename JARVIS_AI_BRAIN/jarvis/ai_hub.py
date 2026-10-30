"""AI Provider Hub — provayderlar katalogi, ulash, tekshirish, modellarni aniqlash va imkoniyatlar katalogi.

Asosiy qoidalar:
* Katalog statik emas: `ai_custom_catalog` sozlamasi orqali yangi provayder qo'shiladi (kod o'zgarmaydi).
* Kalitlar faqat secrets (Credential Manager) da: `ai_key_<id>`. API ularni hech qachon qaytarmaydi.
* Tekshiruv: ulanish → kalit → modellar ro'yxati → kichik test so'rovi → imkoniyatlar → limit/quota → narx.
  Test so'rovi pullik provayderda FAQAT Cost Guard ruxsat bersa yuboriladi (pullik AI yoqilgan + limit bor).
* Bitta endpoint xatosi (masalan /models yo'q) provayderni "ishlamaydi" demaydi — "qisman" va qo'lda Model ID.
* Imkoniyatlar manbasi ko'rsatiladi: provider (API bergan), name_guess (model nomidan taxmin), user, test.
* LiteLLM: og'ir kutubxona o'rnatilmaydi — LiteLLM Proxy (OpenAI-mos gateway) sifatida ulanadi. Bedrock / Vertex
  kabi maxsus imzoli API'lar shu gateway orqali ishlatiladi.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone

from . import net
from .secrets import get_secret, has_secret
from .security import redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_models (
    provider_id TEXT NOT NULL, model_id TEXT NOT NULL, caps TEXT NOT NULL DEFAULT '[]', caps_source TEXT NOT NULL DEFAULT 'name_guess',
    context_len INTEGER, price_in REAL, price_out REAL, free INTEGER NOT NULL DEFAULT 0, available INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'api', last_seen TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY(provider_id, model_id)
);
CREATE TABLE IF NOT EXISTS ai_provider_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, provider_id TEXT NOT NULL, ts TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL, steps TEXT NOT NULL, note TEXT
);
"""

CAPABILITIES = {"text": "Matn yaratish", "reasoning": "Murakkab fikrlash", "coding": "Dasturlash", "image_understanding": "Rasmni tushunish",
                "image_generation": "Rasm yaratish", "video_understanding": "Videoni tushunish", "video_generation": "Video yaratish",
                "audio_input": "Audio kirish", "audio_output": "Audio chiqish", "speech_recognition": "Nutqni tanish", "translation": "Tarjima",
                "web_search": "Internet qidiruvi", "embeddings": "Embeddings", "reranking": "Reranking", "tool_calling": "Tool calling",
                "structured_output": "Strukturali javob (JSON)", "long_context": "Uzun kontekst", "file_understanding": "Fayllarni tushunish"}
STATUSES = {"connected": "Ulangan", "invalid_key": "API kalit noto'g'ri", "connection_failed": "Ulanib bo'lmadi", "rate_limited": "So'rovlar cheklandi (kuting)",
            "quota_exceeded": "Kvota tugagan", "billing_required": "To'lov/billing kerak", "model_unavailable": "Model mavjud emas",
            "partially_supported": "Qisman ishlaydi", "unchecked": "Tekshirilmagan", "not_configured": "Sozlanmagan"}
BLOCKING = {"invalid_key": None, "billing_required": None, "quota_exceeded": 3600, "rate_limited": 120}   # router uchun: soniya (None — qayta tekshirilguncha)

# kind: openai_compatible | anthropic | ollama | azure_openai.  auth: bearer | x-api-key | api-key | none
_O = "openai_compatible"
CATALOG = {
    "openai": {"title": "OpenAI / ChatGPT", "kind": _O, "base_url": "https://api.openai.com/v1", "model": "gpt-4.1-mini", "logo": "🟢", "key_url": "https://platform.openai.com/api-keys"},
    "gemini": {"title": "Google Gemini", "kind": _O, "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.5-flash", "logo": "🔷",
               "key_url": "https://aistudio.google.com/apikey", "free_note": "Bepul daraja bor (kunlik cheklangan)"},
    "claude": {"title": "Anthropic Claude", "kind": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-sonnet-5-5", "logo": "🟠",
               "auth": "x-api-key", "key_url": "https://console.anthropic.com/settings/keys"},
    "openrouter": {"title": "OpenRouter", "kind": _O, "base_url": "https://openrouter.ai/api/v1", "model": "openrouter/auto", "logo": "🔀",
                   "models_public": True, "key_check_path": "/key", "key_url": "https://openrouter.ai/keys", "free_note": "':free' modellar bepul (cheklangan)"},
    "omniroute": {"title": "OmniRoute", "kind": _O, "base_url": "http://localhost:20128/v1", "model": "", "logo": "🧭", "local": True,
                  "note": "O'zingiz ishga tushiradigan AI gateway. Manzilni OmniRoute sozlamasidan tekshiring."},
    "groq": {"title": "Groq", "kind": _O, "base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile", "logo": "⚡",
             "key_url": "https://console.groq.com/keys", "free_note": "Bepul daraja bor (daqiqalik limit)"},
    "deepseek": {"title": "DeepSeek", "kind": _O, "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "logo": "🐋", "key_url": "https://platform.deepseek.com/api_keys"},
    "mistral": {"title": "Mistral AI", "kind": _O, "base_url": "https://api.mistral.ai/v1", "model": "mistral-small-latest", "logo": "🌬", "key_url": "https://console.mistral.ai/api-keys"},
    "xai": {"title": "xAI Grok", "kind": _O, "base_url": "https://api.x.ai/v1", "model": "grok-3-mini", "logo": "✖", "key_url": "https://console.x.ai"},
    "cohere": {"title": "Cohere", "kind": _O, "base_url": "https://api.cohere.ai/compatibility/v1", "model": "command-r-plus", "logo": "🟣", "key_url": "https://dashboard.cohere.com/api-keys"},
    "perplexity": {"title": "Perplexity", "kind": _O, "base_url": "https://api.perplexity.ai", "model": "sonar", "logo": "🔎", "models_path": None,
                   "key_url": "https://www.perplexity.ai/settings/api", "caps_hint": ["web_search"]},
    "together": {"title": "Together AI", "kind": _O, "base_url": "https://api.together.xyz/v1", "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "logo": "🤝"},
    "fireworks": {"title": "Fireworks AI", "kind": _O, "base_url": "https://api.fireworks.ai/inference/v1", "model": "accounts/fireworks/models/llama-v3p3-70b-instruct", "logo": "🎆"},
    "nvidia": {"title": "NVIDIA NIM", "kind": _O, "base_url": "https://integrate.api.nvidia.com/v1", "model": "meta/llama-3.3-70b-instruct", "logo": "🟩",
               "key_url": "https://build.nvidia.com", "free_note": "Sinov kreditlari beriladi"},
    "azure_openai": {"title": "Azure OpenAI", "kind": "azure_openai", "base_url": "https://<resurs>.openai.azure.com", "model": "<deployment nomi>", "logo": "☁",
                     "auth": "api-key", "models_path": None, "params": {"api_version": "2024-10-21"}, "note": "Model ID o'rniga deployment nomini kiriting."},
    "bedrock": {"title": "AWS Bedrock (LiteLLM orqali)", "kind": _O, "base_url": "http://localhost:4000/v1", "model": "bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0",
                "logo": "🟧", "gateway": True, "note": "AWS imzosi (SigV4) kerak — LiteLLM Proxy'da AWS kalitlarini sozlab, shu yerga proxy manzilini kiriting."},
    "vertex": {"title": "Google Vertex AI (LiteLLM orqali)", "kind": _O, "base_url": "http://localhost:4000/v1", "model": "vertex_ai/gemini-2.5-flash", "logo": "🔺",
               "gateway": True, "note": "Google Cloud service account kerak — LiteLLM Proxy orqali ulanadi."},
    "huggingface": {"title": "Hugging Face", "kind": _O, "base_url": "https://router.huggingface.co/v1", "model": "meta-llama/Llama-3.1-8B-Instruct", "logo": "🤗",
                    "key_url": "https://huggingface.co/settings/tokens"},
    "github": {"title": "GitHub Models", "kind": _O, "base_url": "https://models.github.ai/inference", "model": "openai/gpt-4.1-mini", "logo": "🐙", "models_path": None,
               "key_url": "https://github.com/settings/tokens", "free_note": "GitHub akkaunti bilan bepul sinov limiti"},
    "replicate": {"title": "Replicate (rasm/video)", "kind": "media", "base_url": "https://api.replicate.com/v1", "model": "", "logo": "🔁", "models_path": None,
                  "key_url": "https://replicate.com/account/api-tokens", "note": "Chat API emas: rasm/video modellar uchun (Media AI Studio bosqichida ulanadi)."},
    "vercel": {"title": "Vercel AI Gateway", "kind": _O, "base_url": "https://ai-gateway.vercel.sh/v1", "model": "openai/gpt-4.1-mini", "logo": "▲"},
    "litellm": {"title": "LiteLLM Proxy (gateway)", "kind": _O, "base_url": "http://localhost:4000/v1", "model": "", "logo": "🚦", "local": True, "gateway": True,
                "note": "100+ provayderni bitta OpenAI-mos manzilga birlashtiradi. `pip install litellm[proxy]` va `litellm --config config.yaml` (JARVIS avtomatik o'rnatmaydi)."},
    "qwen": {"title": "Qwen (Alibaba DashScope)", "kind": _O, "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "logo": "🌀"},
    "cerebras": {"title": "Cerebras", "kind": _O, "base_url": "https://api.cerebras.ai/v1", "model": "llama-3.3-70b", "logo": "🧠", "free_note": "Bepul daraja bor"},
    "sambanova": {"title": "SambaNova", "kind": _O, "base_url": "https://api.sambanova.ai/v1", "model": "Meta-Llama-3.3-70B-Instruct", "logo": "🟥"},
    "deepinfra": {"title": "DeepInfra", "kind": _O, "base_url": "https://api.deepinfra.com/v1/openai", "model": "meta-llama/Llama-3.3-70B-Instruct", "logo": "🌊"},
    "novita": {"title": "Novita AI", "kind": _O, "base_url": "https://api.novita.ai/v3/openai", "model": "meta-llama/llama-3.3-70b-instruct", "logo": "✨"},
    "ollama": {"title": "Ollama (mahalliy)", "kind": "ollama", "base_url": "http://127.0.0.1:11434", "model": "qwen2.5:1.5b", "logo": "🦙", "auth": "none", "local": True,
               "models_path": "/api/tags", "free_note": "Bepul, internetsiz"},
    "lmstudio": {"title": "LM Studio (mahalliy)", "kind": _O, "base_url": "http://localhost:1234/v1", "model": "", "logo": "🖥", "auth": "none", "local": True},
    "vllm": {"title": "vLLM (mahalliy server)", "kind": _O, "base_url": "http://localhost:8000/v1", "model": "", "logo": "🚀", "auth": "none", "local": True},
    "custom": {"title": "Boshqa OpenAI-mos API", "kind": _O, "base_url": "", "model": "", "logo": "🔌"},
}

LOCAL_HOST = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(/|$)")


def guess_caps(model_id: str, hint: list | None = None) -> list[str]:
    """Model nomidan imkoniyatlarni TAXMIN qiladi (manba: name_guess — foydalanuvchiga shunday ko'rsatiladi)."""
    m = (model_id or "").lower()
    if re.search(r"rerank", m):
        return ["reranking"]
    if re.search(r"embed", m):
        return ["embeddings"]
    if re.search(r"dall-e|gpt-image|imagen|flux|stable-diffusion|sdxl|sd3|ideogram|recraft|playground-v", m):
        return ["image_generation"]
    if re.search(r"sora|veo|kling|runway|luma|hailuo|wan2|seedance|video-gen|hunyuan-video", m):
        return ["video_generation"]
    if re.search(r"whisper|transcribe|speech-to-text|\bstt\b", m):
        return ["speech_recognition", "audio_input"]
    if re.search(r"\btts\b|-tts|text-to-speech", m):
        return ["audio_output"]
    caps = {"text", "translation"}
    big = not re.search(r"(0\.5|1\.5|1|2|3)b\b|mini-?1b|tiny|nano", m)
    if big:
        caps.add("structured_output")
    if re.search(r"cod(e|er|estral)|devstral|claude|gpt-4|gpt-5|o[34]\b|o[34]-|deepseek|qwen|grok|gemini|llama-3\.[13]-70|llama-4|kimi|glm|mistral-(large|medium)", m):
        caps.add("coding")
    if re.search(r"\bo[134]\b|o[134]-|r1|reasoner|thinking|qwq|claude|gpt-5|gemini-(2\.5|3)|grok-[34]|magistral|kimi-k2|sonnet|opus", m):
        caps.add("reasoning")
    if re.search(r"vision|\bvl\b|-vl|vl:|llava|moondream|pixtral|gpt-4o|gpt-4\.1|gpt-5|claude|gemini|llama-4|gemma-?3|qwen2\.5vl|qwen-vl|grok-.*vision", m):
        caps.add("image_understanding")
    if re.search(r"gemini|claude|gpt-4\.1|gpt-5|128k|200k|1m\b|qwen-long|kimi|command-r", m):
        caps.add("long_context")
    if re.search(r"gemini|claude|gpt-4\.1|gpt-5", m):
        caps.add("file_understanding")
    if re.search(r"gemini", m):
        caps |= {"video_understanding", "audio_input"}
    if re.search(r"gpt-4o-audio|audio-preview", m):
        caps |= {"audio_input", "audio_output"}
    if re.search(r"gpt|claude|gemini|mistral|qwen|llama-3|llama-4|grok|deepseek|command|kimi|glm", m) and big:
        caps.add("tool_calling")
    if re.search(r"sonar|search|online", m):
        caps.add("web_search")
    return sorted(caps | set(hint or []))


class HubError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class AIHub:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)

    @property
    def s(self):
        return self.core.settings

    # ---------------- katalog ----------------
    def catalog(self) -> dict:
        cat = {k: dict(v) for k, v in CATALOG.items()}
        for k, v in (getattr(self.s, "ai_custom_catalog", {}) or {}).items():   # foydalanuvchi qo'shgan provayder turlari
            if isinstance(v, dict) and v.get("base_url") and v.get("kind") in ("openai_compatible", "anthropic", "ollama", "azure_openai"):
                cat.setdefault(k, {"logo": "🔌", **v, "custom": True})
        for v in cat.values():
            v.setdefault("auth", "bearer")
            v.setdefault("models_path", "/models")
            v.setdefault("local", bool(LOCAL_HOST.match(v.get("base_url") or "")))
        return {"providers": cat, "capabilities": CAPABILITIES, "statuses": STATUSES}

    def _provider(self, pid: str) -> dict:
        p = next((dict(x) for x in self.s.ai_providers if x.get("id") == pid), None)
        if not p:
            raise HubError("Bunday provayder ulanmagan")
        return p

    def _meta(self, p: dict) -> dict:
        cat = self.catalog()["providers"]
        base = cat.get(p.get("catalog") or "", cat["custom"] if p["kind"] == "openai_compatible" else {})
        return {**base, **{k: p[k] for k in ("auth", "models_path") if k in p}}

    # ---------------- ulash / o'zgartirish ----------------
    def add(self, *, catalog_id: str, pid: str = "", base_url: str = "", model: str = "", api_key: str = "", api_type: str = "",
            params: dict | None = None, price_in: float = 0.0, price_out: float = 0.0, tier: str = "") -> dict:
        cat = self.catalog()["providers"]
        if catalog_id not in cat:
            raise HubError("Katalogda bunday provayder yo'q")
        c = cat[catalog_id]
        if c["kind"] == "media":
            raise HubError(f"{c['title']}: chat modeli emas — Media AI Studio bosqichida ulanadi")
        pid = re.sub(r"[^a-z0-9_-]", "", (pid or catalog_id).lower())[:40]
        if not pid or pid in ("offline",):
            raise HubError("Provayder ID noto'g'ri")
        if any(x.get("id") == pid for x in self.s.ai_providers):
            raise HubError(f"'{pid}' allaqachon ulangan — boshqa ID tanlang yoki tahrirlang")
        url = (base_url or c["base_url"]).strip().rstrip("/")
        local = bool(LOCAL_HOST.match(url)) or c.get("local", False)
        if not re.match(r"^https?://", url) or "<" in url:
            raise HubError("API Base URL to'liq kiriting (https://...)")
        if not local and not url.startswith("https://"):
            raise HubError("Tashqi provayder uchun faqat https:// manzil")
        kind = api_type or c["kind"]
        if kind not in ("openai_compatible", "anthropic", "ollama", "azure_openai"):
            raise HubError("API turi: openai_compatible, anthropic, ollama yoki azure_openai")
        model = (model or c.get("model") or "").strip()
        if "<" in model:
            model = ""
        prov = {"id": pid, "kind": kind, "catalog": catalog_id, "base_url": url, "model": model or "?", "tier": tier or ("strong" if catalog_id in ("claude", "openai", "gemini") else "light"),
                "local": local and kind != "anthropic", "paid": not local, "price_in_per_1k": float(price_in or 0), "price_out_per_1k": float(price_out or 0),
                "enabled": True, "params": {**(c.get("params") or {}), **(params or {})}, "auth": c.get("auth", "bearer")}
        if api_key:
            self._set_key(pid, api_key)
        self.s.ai_providers = [*self.s.ai_providers, prov]
        self._save(f"AI provayder ulandi: {pid} ({c['title']})")
        return self.get(pid)

    def update(self, pid: str, **kw) -> dict:
        provs = [dict(x) for x in self.s.ai_providers]
        p = next((x for x in provs if x.get("id") == pid), None)
        if not p:
            raise HubError("Bunday provayder ulanmagan")
        if kw.get("api_key"):
            self._set_key(pid, kw["api_key"])
        for k in ("model", "base_url", "tier"):
            if kw.get(k):
                p[k] = str(kw[k]).strip().rstrip("/") if k == "base_url" else str(kw[k]).strip()
        if p["base_url"] and not p["base_url"].startswith("https://") and not LOCAL_HOST.match(p["base_url"]):
            raise HubError("Tashqi provayder uchun faqat https:// manzil")
        for k, cast in (("enabled", bool), ("price_in_per_1k", float), ("price_out_per_1k", float)):
            if kw.get(k) is not None:
                p[k] = cast(kw[k])
        if kw.get("params") is not None:
            p["params"] = dict(kw["params"])
        self.s.ai_providers = provs
        self._save(f"AI provayder o'zgartirildi: {pid}" + (" (kalit almashtirildi)" if kw.get("api_key") else ""))
        return self.get(pid)

    def remove(self, pid: str, delete_key: bool = True) -> dict:
        self._provider(pid)
        self.s.ai_providers = [x for x in self.s.ai_providers if x.get("id") != pid]
        self.s.ai_task_routes = {k: v for k, v in (self.s.ai_task_routes or {}).items() if v != pid}
        if delete_key and has_secret(f"ai_key_{pid}"):
            from .secrets import delete_secret
            try:
                delete_secret(f"ai_key_{pid}")
            except Exception:
                pass
        self.core.db.execute("DELETE FROM ai_models WHERE provider_id=?", (pid,))
        self._save(f"AI provayder o'chirildi: {pid}")
        return {"ok": True}

    def set_default(self, pid: str, task: str = "chat") -> dict:
        self._provider(pid)
        self.s.ai_task_routes = {**(self.s.ai_task_routes or {}), task: pid}
        self._save(f"Standart model: {task} → {pid}")
        return {"ok": True, "routes": self.s.ai_task_routes}

    def _set_key(self, pid: str, key: str):
        from .secrets import set_secret
        key = key.strip()
        if len(key) < 8 or any(ch.isspace() for ch in key):
            raise HubError("API kalit noto'g'ri ko'rinishda")
        set_secret(f"ai_key_{pid}", key)
        self.core.audit.log("secrets", f"AI kaliti kiritildi/almashtirildi: ai_key_{pid}", target=f"ai_key_{pid}", risk="C", approval_status="user_action")

    def _save(self, msg: str):
        self.s.save()
        self.core.reload_ai()
        self.core.audit.log("ai_hub", msg, target="ai_providers", risk="C", approval_status="user_action")

    # ---------------- ko'rish ----------------
    def last_check(self, pid: str) -> dict | None:
        r = self.core.db.one("SELECT * FROM ai_provider_checks WHERE provider_id=? ORDER BY id DESC LIMIT 1", (pid,))
        if r:
            r["steps"] = json.loads(r["steps"])
        return r

    def blocked(self, pid: str) -> str | None:
        """Router uchun: oxirgi tekshiruv/xato holati modelni vaqtincha ishlatmaslikni talab qiladimi."""
        r = self.core.db.one("SELECT status, ts, note FROM ai_provider_checks WHERE provider_id=? ORDER BY id DESC LIMIT 1", (pid,))
        if not r or r["status"] not in BLOCKING:
            return None
        ttl = BLOCKING[r["status"]]
        if ttl is not None and datetime.now(timezone.utc) - datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) > timedelta(seconds=ttl):
            return None
        return f"{STATUSES[r['status']]} ({r['ts']})"

    def models(self, pid: str | None = None) -> list[dict]:
        rows = self.core.db.query("SELECT * FROM ai_models" + (" WHERE provider_id=?" if pid else "") + " ORDER BY provider_id, model_id", (pid,) if pid else ())
        for r in rows:
            r["caps"] = json.loads(r["caps"])
        return rows

    def usage(self, pid: str) -> dict:
        db = self.core.db
        u = db.one("SELECT COUNT(*) n, SUM(ok=0) errors, SUM(COALESCE(tokens_in,0)+COALESCE(tokens_out,0)) tokens, ROUND(SUM(cost),6) cost, MAX(ts) last_used "
                   "FROM ai_usage WHERE provider=?", (pid,))
        errs = db.query("SELECT ts, error FROM ai_usage WHERE provider=? AND ok=0 ORDER BY id DESC LIMIT 5", (pid,))
        return {"requests": u["n"] or 0, "errors": u["errors"] or 0, "tokens": u["tokens"] or 0, "cost": u["cost"] or 0, "last_used": u["last_used"], "recent_errors": errs}

    def get(self, pid: str) -> dict:
        p = self._provider(pid)
        meta = self._meta(p)
        ms = self.models(pid)
        cur = next((m for m in ms if m["model_id"] == p["model"]), None)
        chk = self.last_check(pid)
        return {**p, "title": meta.get("title", pid), "logo": meta.get("logo", "🔌"), "key_set": has_secret(f"ai_key_{pid}"),
                "needs_key": meta.get("auth", "bearer") != "none", "status": chk["status"] if chk else "unchecked", "last_check": chk,
                "models_count": len(ms), "capabilities": cur["caps"] if cur else guess_caps(p["model"], meta.get("caps_hint")),
                "caps_source": cur["caps_source"] if cur else "name_guess", "usage": self.usage(pid), "free_note": meta.get("free_note", ""),
                "note": meta.get("note", ""), "key_url": meta.get("key_url", ""), "gateway": meta.get("gateway", False),
                "blocked": self.blocked(pid), "default_for": [k for k, v in (self.s.ai_task_routes or {}).items() if v == pid]}

    def list(self) -> list[dict]:
        return [self.get(p["id"]) for p in self.s.ai_providers if p.get("id")]

    def overview(self) -> dict:
        g = self.core.guard
        provs = self.list()
        t, m = g.today(), g.month()
        fb = self.core.db.one("SELECT COUNT(*) n FROM ai_usage WHERE ok=1 AND fallback_from IS NOT NULL AND fallback_from<>'' AND date(ts)=date('now')")["n"]
        local = [p for p in provs if p["kind"] == "ollama"]
        return {"providers": len(provs), "connected": sum(p["status"] == "connected" for p in provs),
                "offline": sum(p["status"] in ("connection_failed", "invalid_key", "billing_required", "quota_exceeded") for p in provs),
                "models": self.core.db.one("SELECT COUNT(*) n FROM ai_models WHERE available=1")["n"], "today": t, "month": m, "fallbacks_today": fb,
                "local_ai": (local[0]["status"] if local else "not_configured"), "currency": self.s.currency, "paid_ai_allowed": self.s.paid_ai_allowed}

    # ---------------- imkoniyatlar ----------------
    def set_caps(self, pid: str, model_id: str, caps: list[str]) -> dict:
        bad = [c for c in caps if c not in CAPABILITIES]
        if bad:
            raise HubError(f"Noma'lum imkoniyat: {bad}")
        self._provider(pid)
        self.core.db.execute("INSERT INTO ai_models(provider_id, model_id, caps, caps_source, source) VALUES (?,?,?,?,?) "
                             "ON CONFLICT(provider_id, model_id) DO UPDATE SET caps=excluded.caps, caps_source='user'",
                             (pid, model_id, json.dumps(sorted(set(caps))), "user", "manual"))
        return {"ok": True}

    def add_model(self, pid: str, model_id: str) -> dict:
        """Ro'yxat endpointi bo'lmagan provayder uchun Model ID qo'lda."""
        p = self._provider(pid)
        model_id = model_id.strip()
        if not model_id or len(model_id) > 200:
            raise HubError("Model ID kerak")
        self._upsert(pid, [{"model_id": model_id, "caps": guess_caps(model_id, self._meta(p).get("caps_hint")), "caps_source": "name_guess", "source": "manual"}])
        return {"ok": True}

    def capability_map(self) -> dict:
        """Har bir imkoniyat uchun qaysi ulangan model(lar) — router tanlov tartibida."""
        out = {c: [] for c in CAPABILITIES}
        active = {p["id"]: p for p in self.s.ai_providers if p.get("enabled", True)}
        for m in self.models():
            if m["provider_id"] in active and m["available"]:
                for c in m["caps"]:
                    out.setdefault(c, []).append({"provider": m["provider_id"], "model": m["model_id"], "source": m["caps_source"]})
        return out

    def models_with(self, pid: str, cap: str) -> list[str]:
        return [m["model_id"] for m in self.models(pid) if cap in m["caps"] and m["available"]]

    def _upsert(self, pid: str, items: list[dict]):
        db = self.core.db
        for it in items:
            old = db.one("SELECT caps_source FROM ai_models WHERE provider_id=? AND model_id=?", (pid, it["model_id"]))
            if old and old["caps_source"] == "user":                       # foydalanuvchi tahriri saqlanadi
                db.execute("UPDATE ai_models SET available=1, last_seen=?, context_len=COALESCE(?, context_len), price_in=COALESCE(?, price_in), "
                           "price_out=COALESCE(?, price_out) WHERE provider_id=? AND model_id=?",
                           (_now(), it.get("context_len"), it.get("price_in"), it.get("price_out"), pid, it["model_id"]))
                continue
            db.execute("INSERT INTO ai_models(provider_id, model_id, caps, caps_source, context_len, price_in, price_out, free, available, source, last_seen) "
                       "VALUES (?,?,?,?,?,?,?,?,1,?,?) ON CONFLICT(provider_id, model_id) DO UPDATE SET caps=excluded.caps, caps_source=excluded.caps_source, "
                       "context_len=excluded.context_len, price_in=excluded.price_in, price_out=excluded.price_out, free=excluded.free, available=1, last_seen=excluded.last_seen",
                       (pid, it["model_id"], json.dumps(it["caps"]), it["caps_source"], it.get("context_len"), it.get("price_in"), it.get("price_out"),
                        int(bool(it.get("free"))), it.get("source", "api"), _now()))

    # ---------------- tekshiruv ----------------
    def _headers(self, p: dict, meta: dict) -> dict:
        key = get_secret(f"ai_key_{p['id']}") or ""
        auth = p.get("auth") or meta.get("auth", "bearer")
        if not key or auth == "none":
            return {}
        if auth == "x-api-key":
            return {"x-api-key": key, "anthropic-version": "2023-06-01"}
        if auth == "api-key":
            return {"api-key": key}
        return {"Authorization": f"Bearer {key}"}

    @staticmethod
    def classify(status: int | None, body: str = "") -> str:
        b = (body or "").lower()
        if status is None:
            return "connection_failed"
        if status in (401,) or (status == 403 and re.search(r"key|token|auth|unauthori|forbidden", b)):
            return "invalid_key"
        if status == 402 or re.search(r"billing|payment required|insufficient[_ ]balance|add (a )?payment|credit balance", b):
            return "billing_required"
        if status == 429:
            return "quota_exceeded" if re.search(r"quota|insufficient_quota|exceeded your|credits|resource_exhausted|limit reached for", b) else "rate_limited"
        if status in (404, 400) and re.search(r"model", b) and re.search(r"not (found|exist)|does not exist|unknown|invalid model|not available|unsupported", b):
            return "model_unavailable"
        if status == 403:
            return "invalid_key"
        if 200 <= status < 300:
            return "connected"
        return "connection_failed"

    def _parse_models(self, p: dict, meta: dict, data) -> list[dict]:
        items = data.get("models") if p["kind"] == "ollama" else (data.get("data") if isinstance(data, dict) else data)
        out = []
        for m in (items or [])[:2000]:
            if not isinstance(m, dict):
                continue
            mid = m.get("name") if p["kind"] == "ollama" else m.get("id")
            if not mid:
                continue
            mid = str(mid).removeprefix("models/")
            arch, price = m.get("architecture") or {}, m.get("pricing") or {}
            if arch.get("input_modalities") or arch.get("output_modalities"):     # OpenRouter: provayder bergan haqiqiy ma'lumot
                ins, outs = set(arch.get("input_modalities") or []), set(arch.get("output_modalities") or [])
                caps = {"text", "translation"} if "text" in outs else set()
                caps |= {"image_understanding"} if "image" in ins else set()
                caps |= {"file_understanding"} if "file" in ins else set()
                caps |= {"audio_input"} if "audio" in ins else set()
                caps |= {"image_generation"} if "image" in outs else set()
                sp = set(m.get("supported_parameters") or [])
                caps |= {"tool_calling"} if "tools" in sp else set()
                caps |= {"structured_output"} if {"response_format", "structured_outputs"} & sp else set()
                caps |= {"reasoning"} if {"reasoning", "include_reasoning"} & sp else set()
                caps |= {"long_context"} if (m.get("context_length") or 0) >= 128000 else set()
                caps |= set(c for c in guess_caps(mid) if c in ("coding", "web_search"))
                src = "provider"
            else:
                caps, src = set(guess_caps(mid, meta.get("caps_hint"))), "name_guess"
            pin, pout = price.get("prompt"), price.get("completion")
            try:
                pin, pout = (float(pin) * 1000 if pin is not None else None), (float(pout) * 1000 if pout is not None else None)
            except (TypeError, ValueError):
                pin = pout = None
            free = p.get("local") or str(mid).endswith(":free") or (pin == 0 and pout == 0)
            out.append({"model_id": mid, "caps": sorted(caps), "caps_source": src, "context_len": m.get("context_length") or m.get("context_window"),
                        "price_in": pin, "price_out": pout, "free": free, "source": "api"})
        return out

    def _test_request(self, p: dict, meta: dict, model: str, headers: dict) -> tuple[int | None, str, str]:
        """Kichik test so'rovi: (status, body, matn). Tarmoq xatosi → (None, xato, "")."""
        prompt = "Reply with exactly: OK"
        base, kind = p["base_url"].rstrip("/"), p["kind"]
        if kind == "ollama":
            url, body = f"{base}/api/chat", {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False, "options": {"num_predict": 8}}
        elif kind == "anthropic":
            url, body = f"{base}/v1/messages", {"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": prompt}]}
        elif kind == "azure_openai":
            ver = (p.get("params") or {}).get("api_version", "2024-10-21")
            url, body = f"{base}/openai/deployments/{model}/chat/completions?api-version={ver}", {"messages": [{"role": "user", "content": prompt}], "max_tokens": 8}
        else:
            url, body = f"{base}/chat/completions", {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 8}
        try:
            st, txt = net.request("POST", url, json_body=body, headers=headers, timeout=min(60, self.s.ai_timeout_sec))
        except net.NetError as e:
            return None, str(e), ""
        try:
            d = json.loads(txt)
            out = (d.get("message") or {}).get("content") if kind == "ollama" else (
                "".join(b.get("text", "") for b in d.get("content", []) if isinstance(b, dict)) if kind == "anthropic"
                else d["choices"][0]["message"]["content"])
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            out = ""
        return st, txt, out or ""

    def verify(self, pid: str, test_model: bool = True) -> dict:
        p = self._provider(pid)
        meta = self._meta(p)
        steps, status, note = [], "unchecked", ""
        step = lambda name, ok, detail: steps.append({"step": name, "ok": ok, "detail": redact(str(detail))[:300]})  # noqa: E731
        needs_key = (p.get("auth") or meta.get("auth", "bearer")) != "none"
        if needs_key and not has_secret(f"ai_key_{pid}"):
            step("kalit", False, "API kalit kiritilmagan")
            return self._finish(pid, "not_configured", steps, "API kalit kiritilmagan")
        headers = self._headers(p, meta)
        base = p["base_url"].rstrip("/")
        mpath = p.get("models_path", meta.get("models_path", "/models"))
        models_ok, key_verified = False, False
        # 1–3. Ulanish, kalit va modellar ro'yxati
        if mpath:
            try:
                st, body = net.request("GET", base + mpath, headers=headers, timeout=15)
                cls = self.classify(st, body)
                step("ulanish", True, f"server javob berdi (HTTP {st})")
                if cls == "connected":
                    models = self._parse_models(p, meta, json.loads(body or "{}"))
                    self.core.db.execute("UPDATE ai_models SET available=0 WHERE provider_id=? AND source='api'", (pid,))
                    self._upsert(pid, models)
                    models_ok, key_verified = True, needs_key and not meta.get("models_public")
                    step("modellar", True, f"{len(models)} ta model topildi")
                    if needs_key:
                        step("kalit", key_verified or None, "kalit qabul qilindi" if key_verified else "modellar ro'yxati ochiq — kalit test so'rovida tekshiriladi")
                elif cls in ("invalid_key", "billing_required", "quota_exceeded", "rate_limited"):
                    step("kalit", False, f"{STATUSES[cls]} (HTTP {st})")
                    return self._finish(pid, cls, steps, STATUSES[cls])
                else:
                    step("modellar", None, f"modellar ro'yxati olinmadi (HTTP {st}) — Model ID'ni qo'lda kiritish mumkin")
            except net.NetError as e:
                step("ulanish", False, f"server bilan aloqa yo'q: {e}")
                return self._finish(pid, "connection_failed", steps, "Manzil javob bermadi (internet yoki URL'ni tekshiring)")
            except ValueError:
                step("modellar", None, "javob JSON emas — Model ID'ni qo'lda kiriting")
        else:
            step("modellar", None, "bu provayderda modellar ro'yxati endpointi yo'q — Model ID qo'lda")
        if meta.get("key_check_path") and needs_key:
            try:
                st, body = net.request("GET", base + meta["key_check_path"], headers=headers, timeout=15)
                cls = self.classify(st, body)
                if cls == "connected":
                    key_verified = True
                    info = (json.loads(body or "{}").get("data") or {})
                    step("kalit", True, f"kalit haqiqiy; limit: {info.get('limit')}, sarflangan: {info.get('usage')}")
                elif cls != "connection_failed":
                    step("kalit", False, STATUSES[cls])
                    return self._finish(pid, cls, steps, STATUSES[cls])
            except (net.NetError, ValueError):
                pass
        # 4. Kichik test so'rovi
        model = p["model"] if p["model"] not in ("", "?") else next((m["model_id"] for m in self.models(pid) if "text" in m["caps"]), "")
        tested = None
        if not test_model:
            step("test", None, "test so'rovi so'ralmadi")
        elif not model:
            step("test", None, "Model ID tanlanmagan — ro'yxatdan tanlang yoki qo'lda kiriting")
        else:
            allowed, why = (True, "") if p.get("local") or not p.get("paid", True) else self.core.guard.check(paid=True, est_cost=0.0001)
            if not allowed:
                step("test", None, f"test so'rovi yuborilmadi (pullik): {why}. Sozlamalarda pullik AI va limit belgilansa tekshiriladi.")
            else:
                t0 = time.monotonic()
                st, body, text = self._test_request(p, meta, model, headers)
                ms = int((time.monotonic() - t0) * 1000)
                cls = self.classify(st, body)
                self.core.guard.record(provider=pid, model=model, tier=p.get("tier", ""), purpose="verify", paid=bool(p.get("paid")) and not p.get("local"),
                                       tokens_in=8, tokens_out=2, duration_ms=ms, ok=cls == "connected", error="" if cls == "connected" else STATUSES[cls])
                if cls == "connected" and text.strip():
                    tested, key_verified = True, True
                    step("test", True, f"{model} javob berdi ({ms} ms): {text.strip()[:40]}")
                    self.core.db.execute("UPDATE ai_models SET caps_source=CASE WHEN caps_source='name_guess' THEN 'test' ELSE caps_source END "
                                         "WHERE provider_id=? AND model_id=?", (pid, model))
                    if not self.core.db.one("SELECT 1 FROM ai_models WHERE provider_id=? AND model_id=?", (pid, model)):
                        self._upsert(pid, [{"model_id": model, "caps": guess_caps(model, meta.get("caps_hint")), "caps_source": "test", "source": "manual"}])
                else:
                    tested = False
                    step("test", False, f"{STATUSES.get(cls, cls)}" + (f" (HTTP {st})" if st else f": {body}"))
                    if cls != "connected":
                        return self._finish(pid, cls, steps, STATUSES[cls])
        # 7. Narx
        mrow = next((m for m in self.models(pid) if m["model_id"] == model), None)
        if mrow and mrow["price_in"] is not None:
            step("narx", True, f"{model}: kirish {mrow['price_in']:.4f}, chiqish {mrow['price_out']:.4f} USD / 1K token (provayder ma'lumoti)")
        elif not p.get("local"):
            step("narx", None, "narx API orqali berilmadi — provayder saytidan qo'lda kiriting (xarajat hisobi uchun)")
        if tested and models_ok:
            status = "connected"
        elif tested:
            status, note = "partially_supported", "Model ishlaydi, lekin modellar ro'yxati olinmadi"
        elif models_ok and key_verified:
            status, note = "connected", "Kalit va modellar tekshirildi; generatsiya testi o'tkazilmadi"
        elif models_ok:
            status, note = "partially_supported", "Server ishlaydi; kalit/generatsiya hali tasdiqlanmadi"
        else:
            status, note = "partially_supported", "To'liq tekshirib bo'lmadi — Model ID va test so'rovini tekshiring"
        return self._finish(pid, status, steps, note or STATUSES[status])

    def _finish(self, pid: str, status: str, steps: list, note: str) -> dict:
        self.core.db.execute("INSERT INTO ai_provider_checks(provider_id, status, steps, note) VALUES (?,?,?,?)", (pid, status, json.dumps(steps, ensure_ascii=False), note))
        self.core.router_cache_clear(pid)
        self.core.audit.log("ai_hub", f"AI provayder tekshirildi: {pid} → {status}", target=pid, risk="A")
        return {"provider": pid, "status": status, "label": STATUSES.get(status, status), "note": note, "steps": steps}

    def mark_runtime_error(self, pid: str, message: str):
        """Router ishlatish paytidagi xato (401/402/429 ...) — keyingi so'rovlar boshqa modelga o'tishi uchun."""
        m = re.search(r"HTTP (\d{3})", message or "")
        cls = self.classify(int(m.group(1)) if m else None, message)
        if cls in BLOCKING:
            self.core.db.execute("INSERT INTO ai_provider_checks(provider_id, status, steps, note) VALUES (?,?,?,?)",
                                 (pid, cls, "[]", f"ishlatish paytida: {redact(message)[:200]}"))
