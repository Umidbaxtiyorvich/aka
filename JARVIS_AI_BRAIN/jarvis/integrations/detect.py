"""Protocol Detection — URL yoki host bo'yicha ulanish usulini aniqlash (cheklangan sonli so'rov bilan).

Ko'pi bilan ~8 ta so'rov, har biri 6 soniya; 429 (rate limit) yoki 401/403 kelsa to'xtaydi. Parol/kalit
yuborilmaydi — faqat ommaviy javob turiga qaraladi. Natija: nomzodlar (adapter, ishonch, sabab) va tavsiya.
"""
from __future__ import annotations

import json
import socket
from urllib.parse import urlparse

from .. import instagram_mcp as _mcp
from .. import net
from .base import ConnectorError, check_url
from .http_api import OPENAPI_PATHS

DB_PORTS = {5432: "postgresql", 3306: "mysql", 1433: "mssql", 27017: "mongodb"}


def detect(url: str = "", host: str = "", port: int | None = None, budget: int = 8) -> dict:
    cands, log = [], []

    def add(adapter, conf, why):
        cands.append({"adapter": adapter, "confidence": conf, "why": why})

    if host and port:
        try:
            with socket.create_connection((host, int(port)), timeout=4):
                eng = DB_PORTS.get(int(port))
                add("database", 0.8 if eng else 0.4, f"{host}:{port} port ochiq" + (f" — odatda {eng}" if eng else ""))
        except OSError as e:
            log.append(f"{host}:{port} ulanmadi: {e}")
    if url:
        try:
            base = check_url(url)
        except ConnectorError as e:
            return {"candidates": [], "recommended": None, "log": [str(e)]}
        used = 0

        def get(u, method="GET", body=None, headers=None):
            nonlocal used
            if used >= budget:
                raise StopIteration
            used += 1
            st, txt = net.request(method, u, json_body=body, headers=headers or {}, timeout=6)
            if st == 429:
                raise StopIteration
            return st, txt
        try:
            st, txt = get(base, headers={"Accept": "text/html,application/json"})
            low = txt[:20000].lower()
            if st < 400 and "<html" in low:
                if 'type="password"' in low or "type='password'" in low or "type=password" in low:
                    add("website", 0.85, "HTML sahifada parol maydoni — veb-panel (login orqali)")
                else:
                    add("website", 0.5, "HTML sahifa")
            elif st < 400:
                try:
                    json.loads(txt)
                    add("rest", 0.7, "JSON javob")
                except ValueError:
                    pass
            if st in (401, 403):
                add("rest", 0.5, f"HTTP {st} — autentifikatsiya talab qilinadi (API bo'lishi mumkin)")
            if "odata" in base.lower() or "$metadata" in low:
                st2, t2 = get(base.rstrip("/") + "/$metadata", headers={"Accept": "application/xml"})
                if st2 < 400 and "edmx" in t2.lower():
                    add("odata", 0.95, "$metadata (EDMX) topildi — OData (masalan, 1C)")
                elif st2 in (401, 403):
                    add("odata", 0.6, "$metadata autentifikatsiya so'raydi — OData bo'lishi mumkin")
            for p in OPENAPI_PATHS[:3]:
                st3, t3 = get(base.rstrip("/") + p)
                if st3 < 400 and '"paths"' in t3:
                    add("rest", 0.95, f"OpenAPI hujjati: {p}")
                    break
            gq = base if base.endswith("graphql") else base.rstrip("/") + "/graphql"
            st4, t4 = get(gq, "POST", {"query": "{ __typename }"})
            if st4 < 500 and '"data"' in t4 and "__typename" in t4:
                add("graphql", 0.95, f"GraphQL javob berdi: {urlparse(gq).path}")
            if base.rstrip("/").endswith("/mcp") or "mcp" in urlparse(base).hostname:
                try:
                    sc, hd, bd = _mcp.TRANSPORT(base, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                        "protocolVersion": _mcp.PROTOCOL, "capabilities": {}, "clientInfo": {"name": "JARVIS-detect", "version": "1"}}}).encode(),
                        {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}, 6)
                    if sc < 400 and "protocolVersion" in bd:
                        add("mcp", 0.97, "MCP initialize javobi")
                    elif sc in (401, 403):
                        add("mcp", 0.6, "MCP token so'raydi")
                except _mcp.MCPError as e:
                    log.append(str(e))
        except StopIteration:
            log.append("So'rovlar chegarasi tugadi yoki server 429 qaytardi — aniqlash to'xtatildi")
        except net.NetError as e:
            log.append(f"Tarmoq: {e}")
        log.append(f"{used} so'rov yuborildi")
    best = {}
    for c in cands:
        if c["adapter"] not in best or c["confidence"] > best[c["adapter"]]["confidence"]:
            best[c["adapter"]] = c
    ranked = sorted(best.values(), key=lambda c: -c["confidence"])
    return {"candidates": ranked, "recommended": ranked[0]["adapter"] if ranked else None, "log": log,
            "note": "Bu taxmin. Ulanish faqat 'Ulanishni tekshirish' muvaffaqiyatli bo'lgandagina tasdiqlanadi."}
