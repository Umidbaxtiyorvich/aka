"""Adaptive AI Router — vazifa murakkabligi, maxfiylik, narx va mavjudlikka qarab modelni tanlaydi.

Qoidalar:
* Oddiy vazifa → `light` tier; murakkab (kod, tahlil, uzun matn) → `strong` tier.
* Maxfiy ma'lumot (parol, karta, pasport, telefon, `private=True`) → faqat mahalliy modellar. Mahalliy model
  bo'lmasa, tashqi modelga YUBORILMAYDI — foydalanuvchiga aytiladi.
* Bir provayder ishlamasa → ruxsat etilgan keyingisiga o'tadi (fallback) va bu javobda ko'rsatiladi.
* Pullik provayder → Resource Guard limitini tekshiradi; limit bo'lmasa yoki tugagan bo'lsa — o'tkazib yuboriladi.
* Har bir urinish (muvaffaqiyatli yoki xato) ai_usage jadvaliga yoziladi.
"""
from __future__ import annotations

import re
import time

from . import net
from .ai_engine import AIError, OfflineProvider, OllamaProvider
from .resource_guard import estimate_tokens
from .secrets import get_secret
from .security import contains_secret, redact

COMPLEX_HINTS = re.compile(
    r"(?i)(```|traceback|exception|xato(ni|lar)?\b|debug|kod(ni)?\b|funksiya|python|sql|javascript|tahlil|analiz|"
    r"solishtir|strategiya|reja tuz|arxitektura|optimallashtir|refaktor|функци|анализ|сравни|ошибк)")
PII = re.compile(r"(?i)(\b[A-Z]{2}\s?\d{7}\b|\+?998[\s-]?\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}|\bpasport|\bjshshir|\bинн\b)")


class OpenAICompatProvider:
    """OpenAI-compatible /v1/chat/completions (OpenRouter, Groq, Gemini, LiteLLM Proxy, LM Studio, vLLM va boshqalar)."""

    def __init__(self, pid: str, base_url: str, model: str, timeout: int = 60, *, needs_key: bool = True, params: dict | None = None):
        self.name, self.base_url, self.model, self.timeout = pid, base_url.rstrip("/"), model, timeout
        self.needs_key, self.params = needs_key, dict(params or {})

    def available(self) -> tuple[bool, str]:
        if not self.needs_key:
            return True, "kalit talab qilinmaydi (mahalliy server)"
        return (True, "kalit bor") if get_secret(f"ai_key_{self.name}") else (False, f"Kalit yo'q: ai_key_{self.name}")

    def _url_headers(self, key: str) -> tuple[str, dict]:
        return f"{self.base_url}/chat/completions", ({"Authorization": f"Bearer {key}"} if key else {})

    def chat_ex(self, messages: list[dict]) -> dict:
        key = get_secret(f"ai_key_{self.name}") or ""
        if self.needs_key and not key:
            raise AIError("API kaliti yo'q")
        url, headers = self._url_headers(key)
        extra = {k: v for k, v in self.params.items() if k in ("temperature", "top_p", "max_tokens", "reasoning_effort")}
        try:
            r = net.post_json(url, json_body={"model": self.model, "messages": messages, **extra}, headers=headers, timeout=self.timeout)
        except net.NetError as e:
            raise AIError(f"{self.name}: {e} {redact(e.body or '')[:160]}".strip()) from None
        try:
            text = r["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise AIError(f"{self.name}: kutilmagan javob") from None
        u = r.get("usage") or {}
        return {"text": text, "tokens_in": u.get("prompt_tokens"), "tokens_out": u.get("completion_tokens")}


class AzureOpenAIProvider(OpenAICompatProvider):
    """Azure OpenAI: deployment nomi model o'rnida, `api-key` sarlavhasi."""

    def _url_headers(self, key: str) -> tuple[str, dict]:
        ver = self.params.get("api_version", "2024-10-21")
        return f"{self.base_url}/openai/deployments/{self.model}/chat/completions?api-version={ver}", {"api-key": key}


class AnthropicProvider:
    """Anthropic Messages API."""

    def __init__(self, pid: str, model: str, base_url: str = "https://api.anthropic.com", timeout: int = 60):
        self.name, self.model, self.base_url, self.timeout = pid, model, base_url.rstrip("/"), timeout

    def available(self) -> tuple[bool, str]:
        return (True, "kalit bor") if get_secret(f"ai_key_{self.name}") else (False, f"Kalit yo'q: ai_key_{self.name}")

    def chat_ex(self, messages: list[dict]) -> dict:
        key = get_secret(f"ai_key_{self.name}")
        if not key:
            raise AIError("API kaliti yo'q")
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        msgs = [m for m in messages if m["role"] in ("user", "assistant")]
        body = {"model": self.model, "max_tokens": 1024, "messages": msgs} | ({"system": system} if system else {})
        try:
            r = net.post_json(f"{self.base_url}/v1/messages", json_body=body, timeout=self.timeout,
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        except net.NetError as e:
            raise AIError(f"{self.name}: {e} {redact(e.body or '')[:160]}".strip()) from None
        text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
        if not text:
            raise AIError(f"{self.name}: bo'sh javob")
        u = r.get("usage") or {}
        return {"text": text, "tokens_in": u.get("input_tokens"), "tokens_out": u.get("output_tokens")}


def classify(messages: list[dict], purpose: str = "") -> str:
    text = " ".join(m.get("content", "") for m in messages if m.get("role") != "system")
    if purpose in ("code", "analysis", "research") or len(text) > 600 or COMPLEX_HINTS.search(text):
        return "complex"
    return "simple"


def is_private(messages: list[dict]) -> bool:
    text = " ".join(m.get("content", "") for m in messages if m.get("role") != "system")
    return contains_secret(text) or bool(PII.search(text))


# Tayyor provayder andozalari. Model nomlari o'zgarishi mumkin — dashboardda tahrirlanadi. Kalit: ai_key_<id>.
PROVIDER_PRESETS = {
    "claude": {"id": "claude", "kind": "anthropic", "model": "claude-sonnet-5-5", "tier": "strong", "paid": True,
               "note": "Anthropic Claude API (console.anthropic.com). Kuchli fikrlash va kod."},
    "groq": {"id": "groq", "kind": "openai_compatible", "base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile",
             "tier": "light", "paid": True, "note": "Groq (console.groq.com) — juda tez javob, OpenAI-mos API."},
    "gemini": {"id": "gemini", "kind": "openai_compatible", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "model": "gemini-2.5-flash", "tier": "strong", "paid": True, "note": "Google Gemini (aistudio.google.com) — OpenAI-mos endpoint."},
    "ollama": {"id": "local", "kind": "ollama", "model": "qwen2.5:1.5b", "tier": "light", "paid": False, "note": "Mahalliy model (bepul, internetsiz)."},
}
# Vazifa turlari → afzal provayder id (settings.ai_task_routes). Maxfiy ma'lumot baribir faqat mahalliy modelga ketadi.
TASK_TYPES = {"chat": "Oddiy suhbat", "reasoning": "Murakkab fikrlash", "code": "Kod yozish", "pos": "POS / biznes tahlili",
              "voice": "Ovozli javob", "vision": "Rasm va hujjat tahlili", "research": "Internet qidiruvi", "agents": "Agent boshqaruvi",
              "document": "Katta hujjat tahlili", "translation": "Tarjima"}
# Vazifa → kerakli imkoniyat. required=True — imkoniyatsiz model ishlatilmaydi (masalan, rasmni matn modeli ko'rmaydi).
PURPOSE_CAP = {"code": ("coding", False), "analysis": ("reasoning", False), "reasoning": ("reasoning", False), "vision": ("image_understanding", True),
               "research": ("web_search", False), "document": ("long_context", False), "translation": ("translation", False),
               "agents": ("tool_calling", False), "pos": ("reasoning", False)}
STRATEGIES = {"balanced": "Muvozanat", "cheapest": "Avval eng arzon", "quality": "Sifat ustuvor", "speed": "Tezlik ustuvor", "free_only": "Faqat bepul/mahalliy"}


class Router:
    """core.ai sifatida ishlatiladi: eski interfeys (name, model, available, chat) saqlangan."""

    def __init__(self, core):
        self.core = core
        self._avail_cache: dict[str, tuple[float, bool, str]] = {}
        self.last_route: dict | None = None
        self.current: dict | None = None

    # --- provayderlar ---
    def profiles(self) -> list[dict]:
        s = self.core.settings
        if s.ai_providers:
            profs = [dict(p) for p in s.ai_providers if p.get("enabled", True)]
        else:
            profs = []
            if s.ai_provider == "ollama":
                profs.append({"id": "ollama", "kind": "ollama", "model": s.ollama_model, "tier": "light", "local": True})
        if not any(p["kind"] == "offline" for p in profs):
            profs.append({"id": "offline", "kind": "offline", "model": "rule-based", "tier": "fallback", "local": True})
        for p in profs:
            p.setdefault("tier", "light")
            p.setdefault("local", p["kind"] in ("ollama", "offline"))
            p.setdefault("paid", p["kind"] in ("openai_compatible", "anthropic", "azure_openai") and not p["local"])
            p.setdefault("price_in_per_1k", 0.0)
            p.setdefault("price_out_per_1k", 0.0)
        return profs

    def _build(self, p: dict):
        s = self.core.settings
        if p["kind"] == "offline":
            return OfflineProvider()
        if p["kind"] == "ollama":
            return OllamaProvider(p.get("base_url") or s.ollama_url, p["model"], s.ai_timeout_sec)
        if p["kind"] in ("openai_compatible", "azure_openai"):
            cls = AzureOpenAIProvider if p["kind"] == "azure_openai" else OpenAICompatProvider
            return cls(p["id"], p["base_url"], p["model"], s.ai_timeout_sec, needs_key=p.get("auth", "bearer") != "none", params=p.get("params"))
        if p["kind"] == "anthropic":
            return AnthropicProvider(p["id"], p["model"], p.get("base_url") or "https://api.anthropic.com", s.ai_timeout_sec)
        raise AIError(f"Noma'lum provayder turi: {p['kind']}")

    def _available(self, p: dict) -> tuple[bool, str]:
        now = time.monotonic()
        c = self._avail_cache.get(p["id"])
        if c and now - c[0] < 60:
            return c[1], c[2]
        try:
            ok, note = self._build(p).available()
        except AIError as e:
            ok, note = False, str(e)
        hub = getattr(self.core, "ai_hub", None)
        blk = hub.blocked(p["id"]) if hub and ok and p["kind"] != "offline" else None
        if blk:
            ok, note = False, blk
        self._avail_cache[p["id"]] = (now, ok, note)
        return ok, note

    def status(self) -> list[dict]:
        out = []
        for p in self.profiles():
            ok, note = self._available(p)
            out.append(p | {"available": ok, "note": note})
        return out

    # --- tanlash ---
    def _speed(self) -> dict:
        rows = self.core.db.query("SELECT provider, AVG(duration_ms) ms FROM (SELECT provider, duration_ms FROM ai_usage WHERE ok=1 ORDER BY id DESC LIMIT 300) GROUP BY provider")
        return {r["provider"]: r["ms"] or 0 for r in rows}

    def _pick_model(self, p: dict, cap: str | None, required: bool) -> dict | None:
        """Provayder ichidan vazifaga mos modelni tanlaydi (imkoniyatlar katalogi bo'yicha)."""
        hub = getattr(self.core, "ai_hub", None)
        if not cap or not hub or p["kind"] == "offline":
            return p
        from .ai_hub import guess_caps
        known = {m["model_id"]: m["caps"] for m in hub.models(p["id"])}
        own = known.get(p["model"]) or guess_caps(p["model"])
        if cap in own:
            return p | {"cap_match": True}
        alt = hub.models_with(p["id"], cap)
        if alt:
            return p | {"model": alt[0], "cap_match": True, "model_switched": f"{p['model']} → {alt[0]} ({cap})"}
        return None if required else p | {"cap_match": False}

    def plan(self, messages: list[dict], purpose: str = "", private: bool | None = None, allow_paid: bool = False) -> dict:
        s = self.core.settings
        complexity = classify(messages, purpose)
        priv = is_private(messages) if private is None else private
        order = ["strong", "light"] if complexity == "complex" else ["light", "strong"]
        cap, required = PURPOSE_CAP.get(purpose, (None, False))
        strategy = getattr(s, "ai_strategy", "balanced") or "balanced"
        allowed = set(getattr(s, "ai_allowed_providers", []) or [])
        cands, skipped = [], []
        for p in self.profiles():
            if p["kind"] == "offline":
                continue
            if allowed and p["id"] not in allowed and not p["local"]:
                skipped.append({"provider": p["id"], "reason": "ruxsat berilgan provayderlar ro'yxatida yo'q"})
                continue
            if priv and not p["local"]:
                skipped.append({"provider": p["id"], "reason": "maxfiy ma'lumot — faqat mahalliy model"})
                continue
            if p["paid"] and strategy == "free_only":
                skipped.append({"provider": p["id"], "reason": "strategiya: faqat bepul/mahalliy"})
                continue
            if p["paid"] and getattr(s, "ai_confirm_paid", False) and not allow_paid:
                skipped.append({"provider": p["id"], "reason": "pullik — sizning tasdig'ingiz kerak", "needs_confirm": True})
                continue
            m = self._pick_model(p, cap, required)
            if m is None:
                skipped.append({"provider": p["id"], "reason": f"{cap} imkoniyati yo'q"})
                continue
            cands.append(m)
        q = self.quality()
        spd = self._speed() if strategy == "speed" else {}
        qs = lambda p: -(q.get(p["id"], {}).get("score", 0.5) if q.get(p["id"], {}).get("enough") else 0.5)  # noqa: E731
        tier = lambda p: order.index(p["tier"]) if p["tier"] in order else 2  # noqa: E731
        capk = lambda p: 0 if p.get("cap_match", True) else 1  # noqa: E731
        if strategy == "cheapest":
            key = lambda p: (capk(p), p["paid"], p["price_in_per_1k"] + p["price_out_per_1k"], tier(p), qs(p))  # noqa: E731
        elif strategy == "quality":
            key = lambda p: (capk(p), 0 if p["tier"] == "strong" else 1, qs(p), p["paid"])  # noqa: E731
        elif strategy == "speed":
            key = lambda p: (capk(p), spd.get(p["id"], 5000 if not p["local"] else 8000), p["paid"])  # noqa: E731
        else:
            # Bir xil daraja/narx/joylashuvda — foydalanuvchi fikri va testlar bo'yicha yaxshirog'i oldinda (kamida 5 baho bo'lsa)
            key = lambda p: (capk(p), tier(p), p["paid"], not p["local"], qs(p))  # noqa: E731
        cands.sort(key=key)
        pref = (getattr(s, "ai_task_routes", {}) or {}).get(purpose or "chat")
        routed = None
        if pref:
            hit = next((p for p in cands if p["id"] == pref), None)
            if hit:
                cands.remove(hit)
                cands.insert(0, hit)
                routed = pref
            elif any(x["provider"] == pref for x in skipped):
                why = next(x["reason"] for x in skipped if x["provider"] == pref)
                routed = f"{pref} (maxfiylik sababli o'tkazib yuborildi)" if why.startswith("maxfiy") else f"{pref} (o'tkazib yuborildi: {why})"
        # Fallback tartibi: tanlangan → boshqa mos modellar → mahalliy → JARVIS ichki funksiyalari (offline) — oxirida
        cands.append(next(p for p in self.profiles() if p["kind"] == "offline"))
        return {"complexity": complexity, "task_route": routed, "private": priv, "candidates": cands, "skipped": skipped,
                "capability": cap, "strategy": strategy, "paid_confirm_needed": any(x.get("needs_confirm") for x in skipped)}

    def route(self, messages: list[dict], purpose: str = "", private: bool | None = None, allow_paid: bool = False) -> dict:
        ev = getattr(self.core, "events", None)
        if ev:
            ev.publish("ai.start", purpose=purpose or "chat")
        ok, provider = False, None
        try:
            res = self._route(messages, purpose, private, allow_paid)
            ok, provider = True, res["route"]["provider"]
            return res
        finally:
            self.current = None
            if ev:
                ev.publish("ai.end", ok=ok, provider=provider)

    def _route(self, messages: list[dict], purpose: str = "", private: bool | None = None, allow_paid: bool = False) -> dict:
        plan = self.plan(messages, purpose, private, allow_paid)
        guard = self.core.guard
        attempts, est_in = [], estimate_tokens(" ".join(m["content"] for m in messages))
        for p in plan["candidates"]:
            ok, note = self._available(p)
            if not ok:
                attempts.append({"provider": p["id"], "error": f"mavjud emas: {note}"})
                continue
            est_cost = (est_in * p["price_in_per_1k"] + 500 * p["price_out_per_1k"]) / 1000 if p["paid"] else 0.0
            allowed, why = guard.check(paid=p["paid"], est_cost=est_cost)
            if not allowed:
                attempts.append({"provider": p["id"], "error": why})
                continue
            t0 = time.monotonic()
            self.current = {"provider": p["id"], "model": p["model"], "task": purpose or "chat", "task_label": TASK_TYPES.get(purpose or "chat", purpose),
                            "capability": plan["capability"], "paid": p["paid"], "local": p["local"], "attempt": len(attempts) + 1,
                            "fallback": bool(attempts), "strategy": plan["strategy"], "started": time.time()}
            ev = getattr(self.core, "events", None)
            if ev:
                ev.publish("ai.route", provider=p["id"], model=p["model"], task=purpose or "chat", fallback=bool(attempts))
            try:
                res = self._build(p).chat_ex(messages)
            except AIError as e:
                ms = int((time.monotonic() - t0) * 1000)
                guard.record(provider=p["id"], model=p["model"], tier=p["tier"], purpose=purpose, paid=p["paid"],
                             tokens_in=est_in, tokens_measured=False, duration_ms=ms, ok=False, error=str(e),
                             fallback_from=",".join(a["provider"] for a in attempts))
                self.core.audit.error("ai_router", f"{p['id']}: {e}")
                self._avail_cache.pop(p["id"], None)
                hub = getattr(self.core, "ai_hub", None)
                if hub and p["kind"] != "offline":
                    hub.mark_runtime_error(p["id"], str(e))
                attempts.append({"provider": p["id"], "error": str(e)})
                continue
            ms = int((time.monotonic() - t0) * 1000)
            measured = res.get("tokens_in") is not None and res.get("tokens_out") is not None
            tin = res["tokens_in"] if measured else est_in
            tout = res["tokens_out"] if measured else estimate_tokens(res["text"])
            cost = guard.record(provider=p["id"], model=p["model"], tier=p["tier"], purpose=purpose, paid=p["paid"],
                                tokens_in=tin, tokens_out=tout, tokens_measured=measured, price_in=p["price_in_per_1k"],
                                price_out=p["price_out_per_1k"], duration_ms=ms, ok=True,
                                fallback_from=",".join(a["provider"] for a in attempts))
            qp = self.quality().get(p["id"], {})
            reason = (f"{'murakkab' if plan['complexity'] == 'complex' else 'oddiy'} vazifa"
                      + (", maxfiy ma'lumot → mahalliy" if plan["private"] else "")
                      + (", pullik" if p["paid"] else ", bepul/mahalliy")
                      + (f", sifat bahosi past ({qp['score']:.0%})" if qp.get("enough") and qp["score"] < 0.4 else ""))
            if p.get("model_switched"):
                reason += f", vazifaga mos model: {p['model_switched']}"
            self.last_route = {"provider": p["id"], "model": p["model"], "tier": p["tier"], "reason": reason, "task": purpose or "chat",
                               "capability": plan["capability"], "strategy": plan["strategy"], "paid_confirm_needed": plan["paid_confirm_needed"],
                               "fallbacks": attempts, "skipped": plan["skipped"], "duration_ms": ms,
                               "tokens_in": tin, "tokens_out": tout, "tokens_measured": measured, **cost}
            return {"text": res["text"], "route": self.last_route}
        raise AIError("Hech bir model javob bermadi: " + "; ".join(f"{a['provider']}: {a['error']}" for a in attempts)
                      + (" · Pullik model sizning tasdig'ingizni kutmoqda" if plan["paid_confirm_needed"] else ""))

    # --- sifat: foydalanuvchi fikri + o'rnatilgan testlar ---
    EVAL_PROBES = [("2+2 nechiga teng? Faqat raqam yoz.", r"\b4\b"),
                   ("Faqat bitta so'z bilan javob ber: O'zbekiston poytaxti qaysi shahar?", r"(?i)toshkent|tashkent"),
                   ('Faqat shu JSON ni qaytar: {"ok": true}', r'"ok"\s*:\s*true')]

    def feedback(self, usage_id: int, good: bool, note: str = "") -> dict:
        u = self.core.db.one("SELECT provider, model FROM ai_usage WHERE id=?", (usage_id,))
        if not u:
            raise AIError("Bunday javob topilmadi")
        if self.core.db.one("SELECT 1 FROM model_feedback WHERE usage_id=? AND source='user'", (usage_id,)):
            self.core.db.execute("DELETE FROM model_feedback WHERE usage_id=? AND source='user'", (usage_id,))   # fikrni o'zgartirish
        self.core.db.execute("INSERT INTO model_feedback(usage_id, provider, model, score, source, note) VALUES (?,?,?,?,?,?)",
                             (usage_id, u["provider"], u["model"], 1 if good else -1, "user", (note or "")[:300]))
        return self.quality().get(u["provider"], {})

    def quality(self) -> dict:
        rows = self.core.db.query("SELECT provider, source, SUM(score > 0) up, SUM(score < 0) down FROM model_feedback GROUP BY provider, source")
        out: dict = {}
        for r in rows:
            d = out.setdefault(r["provider"], {"user_up": 0, "user_down": 0, "eval_pass": 0, "eval_fail": 0})
            if r["source"] == "user":
                d["user_up"], d["user_down"] = r["up"] or 0, r["down"] or 0
            else:
                d["eval_pass"], d["eval_fail"] = r["up"] or 0, r["down"] or 0
        for d in out.values():
            good, n = d["user_up"] + d["eval_pass"], d["user_up"] + d["user_down"] + d["eval_pass"] + d["eval_fail"]
            d["votes"], d["score"], d["enough"] = n, round((good + 1) / (n + 2), 3), n >= 5     # Laplace silliqlash
        return out

    def evaluate(self, provider_id: str) -> dict:
        """O'rnatilgan qisqa testlar bilan modelni sinaydi. Pullik provayder faqat Cost Guard ruxsat bersa."""
        p = next((x for x in self.profiles() if x["id"] == provider_id), None)
        if not p or p["kind"] == "offline":
            raise AIError("Bunday provayder yo'q (yoki offline — uni baholab bo'lmaydi)")
        ok, note = self._available(p)
        if not ok:
            raise AIError(f"Provayder mavjud emas: {note}")
        if p["paid"]:
            allowed, why = self.core.guard.check(paid=True, est_cost=len(self.EVAL_PROBES) * 600 * p["price_out_per_1k"] / 1000)
            if not allowed:
                raise AIError(f"Pullik test bloklandi: {why}")
        results = []
        for prompt, rx in self.EVAL_PROBES:
            t0 = time.monotonic()
            try:
                text = self._build(p).chat_ex([{"role": "user", "content": prompt}])["text"]
                passed = bool(re.search(rx, text))
            except AIError as e:
                text, passed = f"xato: {e}", False
            ms = int((time.monotonic() - t0) * 1000)
            u = self.core.guard.record(provider=p["id"], model=p["model"], tier=p["tier"], purpose="eval", paid=p["paid"],
                                       tokens_in=estimate_tokens(prompt), tokens_out=estimate_tokens(text), duration_ms=ms, ok=passed)
            self.core.db.execute("INSERT INTO model_feedback(usage_id, provider, model, score, source, note) VALUES (?,?,?,?,?,?)",
                                 (u["usage_id"], p["id"], p["model"], 1 if passed else -1, "eval", prompt[:80]))
            results.append({"prompt": prompt, "passed": passed, "answer": text[:200], "duration_ms": ms})
        return {"provider": p["id"], "model": p["model"], "passed": sum(r["passed"] for r in results), "total": len(results),
                "results": results, "quality": self.quality().get(p["id"], {})}

    @staticmethod
    def notice(route: dict) -> str:
        """Model almashtirilganini yashirmaslik uchun foydalanuvchiga ko'rinadigan izoh."""
        parts = [f"Model: {route['provider']} ({route['model']}) — {route['reason']}"]
        if route["fallbacks"]:
            parts.append("Avval urinilgan: " + "; ".join(f"{a['provider']} ({a['error'][:60]})" for a in route["fallbacks"]))
        if route.get("paid_confirm_needed"):
            parts.append("Pullik (kuchliroq) model sizning tasdig'ingizni kutmoqda — chatdagi tugma bilan ruxsat bering")
        if route.get("cost"):
            parts.append(f"Xarajat: {route['cost']} {'(token o‘lchangan)' if route.get('cost_measured') else '(taxminiy)'}")
        return "ℹ️ " + " · ".join(parts)

    # --- eski interfeys ---
    @property
    def name(self) -> str:
        for p in self.plan([{"role": "user", "content": "salom"}])["candidates"]:
            if p["kind"] == "offline" or self._available(p)[0]:
                return p["kind"] if p["kind"] in ("offline", "ollama") else p["id"]
        return "offline"

    @property
    def model(self) -> str:
        for p in self.plan([{"role": "user", "content": "salom"}])["candidates"]:
            if p["kind"] == "offline" or self._available(p)[0]:
                return p["model"]
        return "rule-based"

    def available(self) -> tuple[bool, str]:
        st = self.status()
        real = [p for p in st if p["kind"] != "offline" and p["available"]]
        if real:
            return True, "Mavjud modellar: " + ", ".join(f"{p['id']}({p['model']})" for p in real)
        notes = "; ".join(f"{p['id']}: {p['note']}" for p in st if p["kind"] != "offline")
        return True, "Modelsiz rejim (qoidaga asoslangan)" + (f" — {notes}" if notes else "")

    def chat(self, messages: list[dict]) -> str:
        return self.route(messages)["text"]
