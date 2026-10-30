"""Instagram MCP Connector (Model Context Protocol, Streamable HTTP).

* Manzil: settings.instagram_mcp_url (https://, yoki shu kompyuterdagi http://127.0.0.1 / localhost).
* Autentifikatsiya: ixtiyoriy Bearer token — faqat secret storage'da (instagram_mcp_token).
* Ulanish: initialize → tools/list. Vositalar MCP annotatsiyalari bo'yicha ajratiladi:
  readOnlyHint=true — o'qish (darhol chaqirish mumkin); qolganlari tashqi ta'sirli — faqat tasdiq bilan.
* MCP serverdan kelgan har qanday matn ISHONCHSIZ ma'lumot: u <untrusted> ichida qaytariladi va JARVIS uchun
  ko'rsatma sifatida qabul qilinmaydi.
* Bu modul Instagram API'ni o'zi chaqirmaydi — MCP server qaysi amallarni bersa, faqat o'shalar mavjud.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .secrets import get_secret
from .security import redact

PROTOCOL = "2025-06-18"
CATEGORIES = [("publish", r"publish|post|reel|story|upload|media_create|schedule"), ("comment", r"comment|reply|hide|delete"),
              ("dm", r"direct|dm|message|inbox|conversation"), ("stats", r"insight|analytic|stat|metric|report|performance"),
              ("account", r"account|profile|user|me\b"), ("media", r"media|list|get")]


class MCPError(Exception):
    pass


def _default_transport(url: str, body: bytes, headers: dict, timeout: float) -> tuple[int, dict, str]:
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise MCPError(f"Tarmoq xatosi: {e}") from None


TRANSPORT = _default_transport      # testlarda almashtiriladi


def check_url(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("https://") or re.match(r"^http://(127\.0\.0\.1|localhost)(:\d+)?/", url + "/"):
        return url
    raise MCPError("MCP manzili https:// bo'lishi kerak (yoki shu kompyuterdagi http://127.0.0.1)")


def _parse_body(ctype: str, body: str, want_id: int) -> dict:
    if "text/event-stream" in (ctype or ""):
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    msg = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if msg.get("id") == want_id:
                    return msg
        raise MCPError("MCP javobida kutilgan xabar yo'q")
    try:
        return json.loads(body) if body else {}
    except ValueError:
        raise MCPError("MCP javobi JSON emas") from None


def categorize(tool: dict) -> str:
    name = f"{tool.get('name', '')} {tool.get('title', '')}".lower()
    for cat, rx in CATEGORIES:
        if re.search(rx, name):
            return cat
    return "other"


def untrusted(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)[:20000]
    return f"<untrusted source=\"instagram_mcp\">\n{redact(text)[:20000]}\n</untrusted>"


class InstagramMCP:
    def __init__(self, core):
        self.core = core
        self.session_id: str | None = None
        self.server: dict = {}
        self.tools: list[dict] = []
        self.last_check: str | None = None
        self.last_error: str | None = None
        self.healthy: bool | None = None
        self._id = 0

    # --- past daraja ---
    def url(self) -> str:
        return self.core.settings.instagram_mcp_url

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "MCP-Protocol-Version": PROTOCOL, "User-Agent": "JARVIS-AI-BRAIN"}
        tok = get_secret("instagram_mcp_token")
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _rpc(self, method: str, params: dict | None = None, notify: bool = False, timeout: float = 30) -> dict:
        url = check_url(self.url())
        msg = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}
        if not notify:
            self._id += 1
            msg["id"] = self._id
        status, headers, body = TRANSPORT(url, json.dumps(msg).encode(), self._headers(), timeout)
        if headers.get("mcp-session-id"):
            self.session_id = headers["mcp-session-id"]
        if status in (401, 403):
            raise MCPError("MCP autentifikatsiyasi rad etildi (instagram_mcp_token ni tekshiring)")
        if status == 404 and self.session_id:
            self.session_id = None
            raise MCPError("MCP sessiyasi tugagan — qayta ulaning")
        if status >= 400:
            raise MCPError(f"MCP HTTP {status}: {redact(body[:200])}")
        if notify:
            return {}
        res = _parse_body(headers.get("content-type", ""), body, msg["id"])
        if "error" in res:
            raise MCPError(f"MCP xatosi: {redact(str(res['error'].get('message', res['error'])))[:300]}")
        return res.get("result", {})

    # --- ulanish ---
    def connect(self) -> dict:
        if not self.url():
            raise MCPError("Instagram MCP manzili kiritilmagan")
        self.session_id = None
        try:
            init = self._rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                            "clientInfo": {"name": "JARVIS AI BRAIN", "version": "0.5"}})
            self._rpc("notifications/initialized", notify=True)
            self.server = {"name": (init.get("serverInfo") or {}).get("name"), "version": (init.get("serverInfo") or {}).get("version"),
                           "protocol": init.get("protocolVersion")}
            tools, cursor = [], None
            for _ in range(10):
                r = self._rpc("tools/list", {"cursor": cursor} if cursor else {})
                tools += r.get("tools", [])
                cursor = r.get("nextCursor")
                if not cursor:
                    break
            self.tools = [{"name": t.get("name"), "title": t.get("title") or "", "description": redact(t.get("description") or "")[:300],
                           "read_only": bool((t.get("annotations") or {}).get("readOnlyHint")),
                           "destructive": bool((t.get("annotations") or {}).get("destructiveHint")),
                           "category": categorize(t), "input_schema": t.get("inputSchema") or {}} for t in tools if t.get("name")]
            self._health(True)
        except MCPError as e:
            self._health(False, str(e))
            raise
        self.core.audit.log("instagram_mcp", f"MCP ulandi: {self.server.get('name')} ({len(self.tools)} ta vosita)", target="instagram_mcp", risk="B")
        return self.status()

    def _health(self, ok: bool, err: str = ""):
        self.last_check = datetime.now(timezone.utc).isoformat()
        if self.healthy is True and not ok:
            self.core.notifier.notify("Instagram MCP ulanishi uzildi", err[:300], severity="warning", category="instagram")
        self.healthy, self.last_error = ok, (None if ok else err)

    def check(self) -> dict:
        """Monitoring: qayta ulanib ko'radi (jadval bo'yicha)."""
        if not self.url():
            return self.status()
        try:
            self.connect()
        except MCPError:
            pass
        return self.status()

    def status(self) -> dict:
        caps = sorted({t["category"] for t in self.tools})
        return {"url": self.url(), "token_set": bool(get_secret("instagram_mcp_token")), "connected": bool(self.healthy),
                "healthy": self.healthy, "server": self.server, "tools": [{k: t[k] for k in ("name", "title", "description", "read_only",
                                                                                            "destructive", "category")} for t in self.tools],
                "capabilities": caps, "last_check": self.last_check, "last_error": self.last_error}

    # --- vositalar ---
    def _tool(self, name: str) -> dict:
        t = next((x for x in self.tools if x["name"] == name), None)
        if not t:
            raise MCPError(f"Bunday MCP vositasi yo'q: {name} (avval 'Ulanish' ni bosing)")
        return t

    def call(self, name: str, arguments: dict | None = None, *, approved: bool = False) -> dict:
        """Faqat o'qiydigan vositalar darhol; tashqi ta'sirlilar faqat tasdiqdan keyin (execute_approval orqali)."""
        t = self._tool(name)
        if not t["read_only"] and not approved:
            raise MCPError("Bu vosita tashqi ta'sirli — avval tasdiq so'rang")
        if not self.session_id:
            self.connect()
        res = self._rpc("tools/call", {"name": name, "arguments": arguments or {}}, timeout=120)
        parts = [c.get("text", "") if c.get("type") == "text" else f"[{c.get('type')}]" for c in res.get("content", [])]
        if res.get("structuredContent") is not None:
            parts.append(json.dumps(res["structuredContent"], ensure_ascii=False))
        out = {"tool": name, "is_error": bool(res.get("isError")), "content": untrusted("\n".join(parts))}
        self.core.audit.log("instagram_mcp", f"MCP vositasi: {name}", target="instagram_mcp", risk="B" if t["read_only"] else "D",
                            result="error" if out["is_error"] else "ok")
        return out

    def request_call(self, name: str, arguments: dict | None = None, summary: str = "") -> dict:
        t = self._tool(name)
        if t["read_only"]:
            raise MCPError("Bu vosita faqat o'qiydi — tasdiq shart emas, to'g'ridan-to'g'ri chaqiring")
        return self.core.approvals.request(
            action_type="instagram_mcp_call", target="instagram_mcp", level="D",
            payload={"tool": name, "arguments": arguments or {}}, requested_by="instagram_mcp",
            summary=summary or f"Instagram (MCP) amali: {name} {json.dumps(arguments or {}, ensure_ascii=False)[:120]}")

    def execute_approval(self, approval_id: int) -> dict:
        appr = self.core.approvals.get(approval_id)
        payload = appr["payload"]
        self.core.approvals.authorize_execution(approval_id, payload)
        try:
            out = self.call(payload["tool"], payload.get("arguments"), approved=True)
        except MCPError:
            self.core.approvals.mark_result(approval_id, "unknown")
            raise
        self.core.approvals.mark_result(approval_id, "executed")
        return out
