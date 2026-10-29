"""Umumiy HTTP yordamchi (faqat standart kutubxona). Testlarda TRANSPORT almashtiriladi."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "JARVIS-AI-BRAIN/0.2 (+local assistant)"


class NetError(Exception):
    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status, self.body = status, body


def _default_transport(method: str, url: str, data: bytes | None, headers: dict, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise NetError(f"Tarmoq xatosi: {e}") from e


TRANSPORT = _default_transport


def request(method: str, url: str, *, params: dict | None = None, form: dict | None = None,
            json_body: dict | None = None, timeout: float = 20, headers: dict | None = None) -> tuple[int, str]:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    h = {"User-Agent": USER_AGENT, **(headers or {})}
    data = None
    if json_body is not None:
        data, h["Content-Type"] = json.dumps(json_body).encode(), "application/json"
    elif form is not None:
        data, h["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    return TRANSPORT(method, url, data, h, timeout)


def get_json(url: str, **kw) -> dict:
    status, body = request("GET", url, **kw)
    return _parse(status, body)


def post_json(url: str, **kw) -> dict:
    status, body = request("POST", url, **kw)
    return _parse(status, body)


def _parse(status: int, body: str) -> dict:
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        data = {"raw": body[:500]}
    if status >= 400:
        raise NetError(f"HTTP {status}", status, body[:500])
    return data
