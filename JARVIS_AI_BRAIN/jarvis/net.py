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


def _default_bytes_transport(url: str, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise NetError(f"Tarmoq xatosi: {e}") from e


BYTES_TRANSPORT = _default_bytes_transport


def get_bytes(url: str, timeout: float = 60, max_bytes: int = 25 * 2**20) -> bytes:
    status, data = BYTES_TRANSPORT(url, timeout)
    if status >= 400:
        raise NetError(f"HTTP {status}", status)
    if len(data) > max_bytes:
        raise NetError("Fayl juda katta")
    return data


def post_multipart(url: str, fields: dict, files: dict[str, tuple[str, bytes, str]], timeout: float = 60) -> dict:
    """multipart/form-data (masalan, Telegram sendVoice). files: {maydon: (fayl_nomi, baytlar, mime)}."""
    import uuid
    boundary = "jarvis" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (name, data, mime) in files.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                     f"Content-Type: {mime}\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    h = {"User-Agent": USER_AGENT, "Content-Type": f"multipart/form-data; boundary={boundary}"}
    status, body = TRANSPORT("POST", url, b"".join(parts), h, timeout)
    return _parse(status, body)


def _default_raw_transport(method: str, url: str, data: bytes | None, headers: dict, timeout: float) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read(), {k.lower(): v for k, v in (e.headers or {}).items()}
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise NetError(f"Tarmoq xatosi: {e}") from e


RAW_TRANSPORT = _default_raw_transport


def post_raw(url: str, data: bytes, headers: dict, timeout: float = 60) -> tuple[int, bytes, dict]:
    """Ikkilik javob (masalan, TTS audio) uchun POST."""
    return RAW_TRANSPORT("POST", url, data, {"User-Agent": USER_AGENT, **headers}, timeout)
