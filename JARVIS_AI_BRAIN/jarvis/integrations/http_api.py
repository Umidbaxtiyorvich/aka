"""REST, OData va GraphQL adapterlari.

Autentifikatsiya: yo'q / API kalit (sarlavha yoki query) / Bearer token / Basic / OAuth 2.0 client credentials.
Kalitlar Vault'dan olinadi va faqat so'rov sarlavhasida ishlatiladi (loglarda yashiriladi).
Javob kodlari: 401 → auth_expired (yoki noto'g'ri kalit), 403 → permission_denied, 429 → rate_limited (Retry-After),
5xx/tarmoq → error. Aniqlash (OpenAPI/$metadata/introspection) cheklangan sonli so'rov bilan.
"""
from __future__ import annotations

import base64
import json
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

from .. import net
from ..security import redact
from .base import BaseConnector, ConnectorError, NotSupported, check_url, field

AUTH_FIELDS = [
    field("auth_type", "Autentifikatsiya", "select", options=["none", "api_key_header", "api_key_query", "bearer", "basic", "oauth2_client_credentials"], default="bearer"),
    field("api_key_name", "API kalit nomi (sarlavha yoki parametr)", default="X-API-Key"),
    field("api_key", "API kalit", "password", secret=True),
    field("token", "Access token / Bearer", "password", secret=True),
    field("username", "Login (Basic)", secret=True),
    field("password", "Parol (Basic)", "password", secret=True),
    field("token_url", "OAuth token URL"), field("client_id", "OAuth client_id"),
    field("client_secret", "OAuth client_secret", "password", secret=True), field("scope", "OAuth scope"),
]
OPENAPI_PATHS = ["/openapi.json", "/swagger.json", "/api/openapi.json", "/v3/api-docs", "/swagger/v1/swagger.json"]


class HttpBase(BaseConnector):
    timeout = 20

    def base(self) -> str:
        return check_url(self.cfg.get("base_url", ""), "API Base URL")

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Accept": "application/json", **(extra or {})}
        a = self.cfg.get("auth_type", "none")
        if a == "api_key_header":
            k = self.secret("api_key")
            if not k:
                raise ConnectorError("API kalit kiritilmagan", "auth_failed")
            h[self.cfg.get("api_key_name") or "X-API-Key"] = k
        elif a == "bearer":
            t = self.secret("token")
            if not t:
                raise ConnectorError("Access token kiritilmagan", "auth_failed")
            h["Authorization"] = f"Bearer {t}"
        elif a == "basic":
            u, p = self.secret("username"), self.secret("password")
            if not (u and p):
                raise ConnectorError("Login yoki parol kiritilmagan", "auth_failed")
            h["Authorization"] = "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()
        elif a == "oauth2_client_credentials":
            h["Authorization"] = f"Bearer {self._oauth_token()}"
        return h

    def _oauth_token(self) -> str:
        tok = getattr(self, "_tok", None)
        if tok and tok[1] > time.time() + 30:
            return tok[0]
        url = check_url(self.cfg.get("token_url", ""), "OAuth token URL")
        sec = self.secret("client_secret")
        if not (self.cfg.get("client_id") and sec):
            raise ConnectorError("OAuth client_id yoki client_secret yo'q", "auth_failed")
        status, body = net.request("POST", url, form={"grant_type": "client_credentials", "client_id": self.cfg["client_id"],
                                                      "client_secret": sec, **({"scope": self.cfg["scope"]} if self.cfg.get("scope") else {})},
                                   timeout=self.timeout)
        if status >= 400:
            raise ConnectorError(f"OAuth token olinmadi (HTTP {status})", "auth_failed")
        d = json.loads(body or "{}")
        self._tok = (d.get("access_token", ""), time.time() + float(d.get("expires_in", 3600)))
        return self._tok[0]

    def _params(self, params: dict | None) -> dict:
        p = dict(params or {})
        if self.cfg.get("auth_type") == "api_key_query":
            k = self.secret("api_key")
            if not k:
                raise ConnectorError("API kalit kiritilmagan", "auth_failed")
            p[self.cfg.get("api_key_name") or "api_key"] = k
        return p

    def request(self, method: str, path_or_url: str, *, params=None, json_body=None, headers=None, raw=False):
        url = path_or_url if path_or_url.startswith(("http://", "https://")) else self.base() + "/" + path_or_url.lstrip("/")
        if urlparse(url).netloc != urlparse(self.base()).netloc:
            raise ConnectorError("Boshqa domenga so'rov yuborilmaydi", "error")
        try:
            status, body = net.request(method, url, params=self._params(params), json_body=json_body,
                                       headers=self._headers(headers), timeout=self.timeout)
        except net.NetError as e:
            raise ConnectorError(redact(f"Tarmoq xatosi: {e}"), "error") from None
        if status == 401:
            raise ConnectorError("Autentifikatsiya rad etildi (401): kalit noto'g'ri yoki muddati tugagan", "auth_expired")
        if status == 403:
            raise ConnectorError("Ruxsat yo'q (403): bu hisobda shu ma'lumotga huquq yo'q", "permission_denied")
        if status == 429:
            raise ConnectorError("So'rovlar chegarasi (429) — keyinroq qayta uriniladi", "rate_limited", retry_after=60)
        if status >= 400:
            raise ConnectorError(f"Server xatosi: HTTP {status} {redact(body[:150])}", "error")
        if raw:
            return body
        try:
            return json.loads(body) if body else {}
        except ValueError:
            raise ConnectorError("Javob JSON emas", "error") from None


def _records(data, list_key: str = ""):
    if list_key:
        for k in list_key.split("."):
            data = (data or {}).get(k) if isinstance(data, dict) else None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("data", "items", "results", "value", "records", "rows"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


class RestConnector(HttpBase):
    kind, title, protocols = "rest", "REST API", ["REST", "JSON", "API Key", "Bearer", "Basic", "OAuth 2.0"]
    can_write = True
    FIELDS = [field("base_url", "API Base URL", "url", required=True, help_="https://api.misol.uz/v1"),
              field("health_path", "Holat tekshiruvi yo'li", default="/"), field("openapi_url", "OpenAPI (swagger) manzili (ixtiyoriy)"),
              field("entities", "Obyektlar (JSON): {\"products\": {\"path\": \"/products\", \"list_key\": \"data\", \"id_field\": \"id\", \"updated_field\": \"updated_at\", \"since_param\": \"updated_since\", \"page_param\": \"page\", \"limit_param\": \"limit\"}}", "json"),
              field("write_endpoints", "Yozish yo'llari (JSON, ixtiyoriy): {\"products.update\": {\"method\": \"PATCH\", \"path\": \"/products/{id}\"}}", "json"),
              *AUTH_FIELDS]

    def health_check(self) -> dict:
        self.request("GET", self.cfg.get("health_path") or "/", raw=True)
        return {"status": "connected", "note": "API javob berdi"}

    def authenticate(self) -> dict:
        self._headers()
        return self.health_check()

    def discover(self) -> dict:
        ents = dict(self.cfg.get("entities") or {})
        modules, note = [], ""
        spec = None
        cands = [self.cfg["openapi_url"]] if self.cfg.get("openapi_url") else OPENAPI_PATHS
        for p in cands[:5]:                    # cheklangan so'rovlar soni
            try:
                spec = self.request("GET", p)
                if isinstance(spec, dict) and spec.get("paths"):
                    break
                spec = None
            except ConnectorError as e:
                if e.status in ("auth_expired", "permission_denied", "rate_limited"):
                    raise
        if spec:
            for path, ops in spec["paths"].items():
                if "get" in ops and "{" not in path:
                    name = re.sub(r"[^a-z0-9_]+", "_", path.strip("/").split("/")[-1].lower()) or "root"
                    ents.setdefault(name, {"path": path})
                    modules.append((ops["get"].get("tags") or [path.strip("/").split("/")[0]])[0])
            note = f"OpenAPI topildi: {spec.get('info', {}).get('title', '')}"
        entities = []
        for name, e in ents.items():
            try:
                rows = _records(self.request("GET", e["path"], params={e.get("limit_param") or "limit": 3}), e.get("list_key", ""))
                cols = sorted({k for r in rows[:3] if isinstance(r, dict) for k in r})
                entities.append({"name": name, "source": e["path"], "fields": cols, "sample_count": len(rows), "readable": True})
            except ConnectorError as err:
                if err.status in ("auth_expired", "rate_limited"):
                    raise
                entities.append({"name": name, "source": e["path"], "fields": [], "readable": False, "note": str(err)})
        self._ents = ents
        return {"modules": sorted(set(modules)) or sorted(ents), "entities": entities,
                "note": note or ("Obyektlar sozlamadan olindi" if ents else "OpenAPI topilmadi — 'Obyektlar' maydonini to'ldiring")}

    def _entity(self, entity: str) -> dict:
        discovered = {e["name"]: {"path": e["source"]} for e in (self.conn.get("entities") or []) if str(e.get("source", "")).startswith("/")}
        ents = discovered | getattr(self, "_ents", {}) | dict(self.cfg.get("entities") or {})
        if entity not in ents:
            raise ConnectorError(f"Noma'lum obyekt: {entity}", "error")
        return ents[entity]

    def fetch_data(self, entity: str, *, since=None, cursor=None, limit: int = 500) -> dict:
        e = self._entity(entity)
        params = {e.get("limit_param") or "limit": limit}
        if since and e.get("since_param"):
            params[e["since_param"]] = since
        if e.get("page_param"):
            params[e["page_param"]] = cursor or 1
        url = cursor if isinstance(cursor, str) and cursor.startswith("http") else e["path"]
        data = self.request("GET", url, params=params if not (isinstance(cursor, str) and cursor.startswith("http")) else None)
        rows = _records(data, e.get("list_key", ""))
        nxt = None
        if isinstance(data, dict) and isinstance(data.get("next"), str) and data["next"]:
            nxt = urljoin(self.base() + "/", data["next"])
        elif e.get("page_param") and rows:          # server o'z sahifa o'lchamini qo'llashi mumkin — bo'sh sahifagacha davom etamiz
            nxt = int(cursor or 1) + 1
        return {"records": [r for r in rows if isinstance(r, dict)], "next": nxt}

    def write(self, entity: str, operation: str, payload: dict) -> dict:
        ep = (self.cfg.get("write_endpoints") or {}).get(f"{entity}.{operation}")
        if not ep:
            raise NotSupported(f"{entity}.{operation} uchun yozish yo'li sozlanmagan")
        path = ep["path"].format(**{k: v for k, v in payload.items() if isinstance(v, (str, int))})
        return {"response": self.request(ep.get("method", "POST"), path, json_body=payload.get("data", payload))}


class ODataConnector(HttpBase):
    """OData (masalan, 1C:Enterprise "standart OData interfeysi" — /odata/standard.odata). Faqat o'qish."""
    kind, title, protocols = "odata", "OData", ["OData", "Basic", "Bearer"]
    FIELDS = [field("base_url", "OData manzili", "url", required=True, help_="https://server/baza/odata/standard.odata"),
              field("entity_sets", "Kerakli EntitySet'lar (vergul bilan, ixtiyoriy)"), *AUTH_FIELDS]

    def health_check(self) -> dict:
        self.request("GET", "$metadata", raw=True, headers={"Accept": "application/xml"})
        return {"status": "connected", "note": "OData $metadata o'qildi"}

    def discover(self) -> dict:
        xml = self.request("GET", "$metadata", raw=True, headers={"Accept": "application/xml"})
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            raise ConnectorError("$metadata XML emas", "error") from None
        types = {}
        for et in root.iter():
            if et.tag.endswith("EntityType"):
                types[et.get("Name")] = [p.get("Name") for p in et if p.tag.endswith("Property")]
        wanted = {x.strip() for x in (self.cfg.get("entity_sets") or "").split(",") if x.strip()}
        entities = []
        for es in root.iter():
            if es.tag.endswith("EntitySet"):
                name, typ = es.get("Name"), (es.get("EntityType") or "").split(".")[-1]
                if wanted and name not in wanted:
                    continue
                entities.append({"name": name, "source": name, "fields": types.get(typ, []), "readable": True})
        modules = sorted({e["name"].split("_")[0] for e in entities})
        return {"modules": modules, "entities": entities[:500], "note": f"{len(entities)} ta EntitySet"}

    def fetch_data(self, entity: str, *, since=None, cursor=None, limit: int = 500) -> dict:
        if not re.fullmatch(r"[\wЀ-ӿ]+", entity):
            raise ConnectorError("Noto'g'ri EntitySet nomi", "error")
        skip = int(cursor or 0)
        data = self.request("GET", entity, params={"$format": "json", "$top": limit, "$skip": skip})
        rows = _records(data)
        return {"records": rows, "next": skip + limit if len(rows) >= limit else None}


class GraphQLConnector(HttpBase):
    kind, title, protocols = "graphql", "GraphQL", ["GraphQL", "Bearer", "API Key"]
    FIELDS = [field("base_url", "GraphQL endpoint", "url", required=True, help_="https://api.misol.uz/graphql"),
              field("queries", "So'rovlar (JSON, ixtiyoriy): {\"products\": \"{ products { id name price } }\"}", "json"), *AUTH_FIELDS]
    INTROSPECT = "{ __schema { queryType { fields { name type { kind name ofType { kind name ofType { kind name } } } } } } }"

    def gql(self, query: str, variables: dict | None = None) -> dict:
        d = self.request("POST", self.base(), json_body={"query": query, "variables": variables or {}})
        if d.get("errors"):
            raise ConnectorError("GraphQL xatosi: " + redact(str(d["errors"][0].get("message", d["errors"][0])))[:200], "error")
        return d.get("data") or {}

    def health_check(self) -> dict:
        self.gql("{ __typename }")
        return {"status": "connected", "note": "GraphQL javob berdi"}

    def discover(self) -> dict:
        d = self.gql(self.INTROSPECT)
        entities = []
        for f in ((d.get("__schema") or {}).get("queryType") or {}).get("fields") or []:
            t, is_list = f["type"], False
            while t:
                if t.get("kind") == "LIST":
                    is_list = True
                t = t.get("ofType")
            if is_list:
                entities.append({"name": f["name"], "source": f["name"], "fields": [], "readable": True})
        for name, q in (self.cfg.get("queries") or {}).items():
            if not any(e["name"] == name for e in entities):
                entities.append({"name": name, "source": "query", "fields": [], "readable": True})
        return {"modules": [e["name"] for e in entities], "entities": entities,
                "note": "Introspection orqali. Maydonlarni olish uchun 'So'rovlar' maydonida so'rovni yozing."}

    def fetch_data(self, entity: str, *, since=None, cursor=None, limit: int = 500) -> dict:
        q = (self.cfg.get("queries") or {}).get(entity)
        if not q:
            raise NotSupported(f"'{entity}' uchun GraphQL so'rovi sozlanmagan (So'rovlar maydoni)")
        d = self.gql(q, {"limit": limit, "cursor": cursor, "since": since})
        rows = d.get(entity) if isinstance(d.get(entity), list) else _records(next(iter(d.values()), []))
        return {"records": [r for r in rows or [] if isinstance(r, dict)], "next": None}
