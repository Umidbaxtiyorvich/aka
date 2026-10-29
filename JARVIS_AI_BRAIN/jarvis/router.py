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
from .security import contains_secret

COMPLEX_HINTS = re.compile(
    r"(?i)(```|traceback|exception|xato(ni|lar)?\b|debug|kod(ni)?\b|funksiya|python|sql|javascript|tahlil|analiz|"
    r"solishtir|strategiya|reja tuz|arxitektura|optimallashtir|refaktor|функци|анализ|сравни|ошибк)")
PII = re.compile(r"(?i)(\b[A-Z]{2}\s?\d{7}\b|\+?998[\s-]?\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}|\bpasport|\bjshshir|\bинн\b)")


class OpenAICompatProvider:
    """OpenAI-compatible /v1/chat/completions (OpenRouter, Groq, LM Studio va boshqalar)."""

    def __init__(self, pid: str, base_url: str, model: str, timeout: int = 60):
        self.name, self.base_url, self.model, self.timeout = pid, base_url.rstrip("/"), model, timeout

    def available(self) -> tuple[bool, str]:
        return (True, "kalit bor") if get_secret(f"ai_key_{self.name}") else (False, f"Kalit yo'q: set_secret.py ai_key_{self.name}")

    def chat_ex(self, messages: list[dict]) -> dict:
        key = get_secret(f"ai_key_{self.name}")
        if not key:
            raise AIError("API kaliti yo'q")
        try:
            r = net.post_json(f"{self.base_url}/chat/completions", json_body={"model": self.model, "messages": messages},
                              headers={"Authorization": f"Bearer {key}"}, timeout=self.timeout)
        except net.NetError as e:
            raise AIError(f"{self.name}: {e}") from None
        try:
            text = r["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise AIError(f"{self.name}: kutilmagan javob") from None
        u = r.get("usage") or {}
        return {"text": text, "tokens_in": u.get("prompt_tokens"), "tokens_out": u.get("completion_tokens")}


class AnthropicProvider:
    """Anthropic Messages API."""

    def __init__(self, pid: str, model: str, base_url: str = "https://api.anthropic.com", timeout: int = 60):
        self.name, self.model, self.base_url, self.timeout = pid, model, base_url.rstrip("/"), timeout

    def available(self) -> tuple[bool, str]:
        return (True, "kalit bor") if get_secret(f"ai_key_{self.name}") else (False, f"Kalit yo'q: set_secret.py ai_key_{self.name}")

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
            raise AIError(f"{self.name}: {e}") from None
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


class Router:
    """core.ai sifatida ishlatiladi: eski interfeys (name, model, available, chat) saqlangan."""

    def __init__(self, core):
        self.core = core
        self._avail_cache: dict[str, tuple[float, bool, str]] = {}
        self.last_route: dict | None = None

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
            p.setdefault("paid", p["kind"] in ("openai_compatible", "anthropic"))
            p.setdefault("price_in_per_1k", 0.0)
            p.setdefault("price_out_per_1k", 0.0)
        return profs

    def _build(self, p: dict):
        s = self.core.settings
        if p["kind"] == "offline":
            return OfflineProvider()
        if p["kind"] == "ollama":
            return OllamaProvider(p.get("base_url") or s.ollama_url, p["model"], s.ai_timeout_sec)
        if p["kind"] == "openai_compatible":
            return OpenAICompatProvider(p["id"], p["base_url"], p["model"], s.ai_timeout_sec)
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
        self._avail_cache[p["id"]] = (now, ok, note)
        return ok, note

    def status(self) -> list[dict]:
        out = []
        for p in self.profiles():
            ok, note = self._available(p)
            out.append(p | {"available": ok, "note": note})
        return out

    # --- tanlash ---
    def plan(self, messages: list[dict], purpose: str = "", private: bool | None = None) -> dict:
        complexity = classify(messages, purpose)
        priv = is_private(messages) if private is None else private
        order = ["strong", "light"] if complexity == "complex" else ["light", "strong"]
        cands, skipped = [], []
        for p in self.profiles():
            if p["kind"] == "offline":
                continue
            if priv and not p["local"]:
                skipped.append({"provider": p["id"], "reason": "maxfiy ma'lumot — faqat mahalliy model"})
                continue
            cands.append(p)
        cands.sort(key=lambda p: (order.index(p["tier"]) if p["tier"] in order else 2, p["paid"], not p["local"]))
        cands.append(next(p for p in self.profiles() if p["kind"] == "offline"))
        return {"complexity": complexity, "private": priv, "candidates": cands, "skipped": skipped}

    def route(self, messages: list[dict], purpose: str = "", private: bool | None = None) -> dict:
        plan = self.plan(messages, purpose, private)
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
            try:
                res = self._build(p).chat_ex(messages)
            except AIError as e:
                ms = int((time.monotonic() - t0) * 1000)
                guard.record(provider=p["id"], model=p["model"], tier=p["tier"], purpose=purpose, paid=p["paid"],
                             tokens_in=est_in, tokens_measured=False, duration_ms=ms, ok=False, error=str(e))
                self.core.audit.error("ai_router", f"{p['id']}: {e}")
                self._avail_cache.pop(p["id"], None)
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
            reason = (f"{'murakkab' if plan['complexity'] == 'complex' else 'oddiy'} vazifa"
                      + (", maxfiy ma'lumot → mahalliy" if plan["private"] else "")
                      + (", pullik" if p["paid"] else ", bepul/mahalliy"))
            self.last_route = {"provider": p["id"], "model": p["model"], "tier": p["tier"], "reason": reason,
                               "fallbacks": attempts, "skipped": plan["skipped"], "duration_ms": ms,
                               "tokens_in": tin, "tokens_out": tout, "tokens_measured": measured, **cost}
            return {"text": res["text"], "route": self.last_route}
        raise AIError("Hech bir model javob bermadi: " + "; ".join(f"{a['provider']}: {a['error']}" for a in attempts))

    @staticmethod
    def notice(route: dict) -> str:
        """Model almashtirilganini yashirmaslik uchun foydalanuvchiga ko'rinadigan izoh."""
        parts = [f"Model: {route['provider']} ({route['model']}) — {route['reason']}"]
        if route["fallbacks"]:
            parts.append("Avval urinilgan: " + "; ".join(f"{a['provider']} ({a['error'][:60]})" for a in route["fallbacks"]))
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
