"""MCP, ma'lumotlar bazasi, fayl va kompyuter (desktop) adapterlari."""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

from .. import instagram_mcp as _mcp
from ..security import is_within, redact
from .base import BaseConnector, ConnectorError, NotSupported, field


# ================= MCP (har qanday MCP server) =================
class MCPConnector(BaseConnector):
    """Model Context Protocol: handshake → tools / resources / prompts. Natijalar ishonchsiz ma'lumot sifatida belgilanadi.
    Faqat o'qiydigan (readOnlyHint) vositalar ma'lumot olishda ishlatiladi; qolganlari — faqat tasdiq bilan."""
    kind, title, protocols = "mcp", "MCP Server", ["MCP", "Bearer"]
    can_write = True
    FIELDS = [field("base_url", "MCP Server URL", "url", required=True, help_="https://server/mcp"),
              field("mcp_token", "Bearer token (ixtiyoriy)", "password", secret=True)]

    def _rpc(self, method, params=None, notify=False):
        url = _mcp.check_url(self.cfg.get("base_url", ""))
        self._id = getattr(self, "_id", 0) + 1
        msg = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {}), **({} if notify else {"id": self._id})}
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": _mcp.PROTOCOL}
        tok = self.secret("mcp_token")
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        if getattr(self, "_sid", None):
            h["Mcp-Session-Id"] = self._sid
        try:
            status, headers, body = _mcp.TRANSPORT(url, json.dumps(msg).encode(), h, 60)
        except _mcp.MCPError as e:
            raise ConnectorError(str(e), "error") from None
        if headers.get("mcp-session-id"):
            self._sid = headers["mcp-session-id"]
        if status in (401, 403):
            raise ConnectorError("MCP autentifikatsiyasi rad etildi", "auth_expired" if status == 401 else "permission_denied")
        if status == 429:
            raise ConnectorError("MCP so'rovlar chegarasi", "rate_limited", retry_after=60)
        if status >= 400:
            raise ConnectorError(f"MCP HTTP {status}", "error")
        if notify:
            return {}
        try:
            res = _mcp._parse_body(headers.get("content-type", ""), body, msg["id"])
        except _mcp.MCPError as e:
            raise ConnectorError(str(e), "error") from None
        if "error" in res:
            raise ConnectorError("MCP xatosi: " + redact(str(res["error"].get("message", "")))[:200], "error")
        return res.get("result", {})

    def health_check(self):
        init = self._rpc("initialize", {"protocolVersion": _mcp.PROTOCOL, "capabilities": {}, "clientInfo": {"name": "JARVIS", "version": "0.8"}})
        self._rpc("notifications/initialized", notify=True)
        self._caps = init.get("capabilities") or {}
        si = init.get("serverInfo") or {}
        return {"status": "connected", "note": f"{si.get('name', 'MCP')} {si.get('version', '')} · protokol {init.get('protocolVersion')}"}

    def discover(self):
        self.health_check()
        tools = self._rpc("tools/list", {}).get("tools", []) if "tools" in self._caps or not self._caps else []
        res = self._rpc("resources/list", {}).get("resources", []) if "resources" in self._caps else []
        prompts = self._rpc("prompts/list", {}).get("prompts", []) if "prompts" in self._caps else []
        ents = [{"name": t["name"], "source": "tool", "fields": sorted((t.get("inputSchema") or {}).get("properties", {})),
                 "readable": bool((t.get("annotations") or {}).get("readOnlyHint")),
                 "note": "faqat o'qish" if (t.get("annotations") or {}).get("readOnlyHint") else "tashqi ta'sirli — faqat tasdiq bilan"} for t in tools]
        ents += [{"name": r.get("uri"), "source": "resource", "fields": [], "readable": True} for r in res]
        return {"modules": ["tools"] * bool(tools) + ["resources"] * bool(res) + ["prompts"] * bool(prompts), "entities": ents,
                "note": f"{len(tools)} vosita, {len(res)} resurs, {len(prompts)} prompt"}

    def fetch_data(self, entity, *, since=None, cursor=None, limit=500):
        d = self.discover()
        e = next((x for x in d["entities"] if x["name"] == entity), None)
        if not e:
            raise ConnectorError(f"Noma'lum MCP obyekti: {entity}", "error")
        if not e["readable"]:
            raise NotSupported("Bu MCP vositasi o'qish uchun emas (tasdiq bilan chaqiriladi)")
        if e["source"] == "resource":
            r = self._rpc("resources/read", {"uri": entity})
            text = "\n".join(c.get("text", "") for c in r.get("contents", []))
        else:
            r = self._rpc("tools/call", {"name": entity, "arguments": {}})
            if r.get("structuredContent") is not None:
                sc = r["structuredContent"]
                rows = sc if isinstance(sc, list) else next((v for v in sc.values() if isinstance(v, list)), [sc]) if isinstance(sc, dict) else []
                return {"records": [x for x in rows if isinstance(x, dict)][:limit], "next": None, "untrusted": True}
            text = "\n".join(c.get("text", "") for c in r.get("content", []) if c.get("type") == "text")
        try:
            data = json.loads(text)
            rows = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), [data])
        except ValueError:
            rows = [{"text": text[:5000]}]
        return {"records": [x for x in rows if isinstance(x, dict)][:limit], "next": None, "untrusted": True}

    def write(self, entity, operation, payload):
        r = self._rpc("tools/call", {"name": entity, "arguments": payload.get("arguments", payload)})
        return {"is_error": bool(r.get("isError")), "content": _mcp.untrusted("\n".join(c.get("text", "") for c in r.get("content", [])))}


# ================= Ma'lumotlar bazalari (faqat o'qish) =================
FORBIDDEN_SQL = re.compile(r"(?is)\b(insert|update|delete|drop|alter|create|truncate|replace|merge|grant|revoke|attach|detach|pragma|"
                           r"vacuum|exec|execute|call|copy|into\s+outfile|load_file|sleep|benchmark|lock|unlock|set\s)\b")
ENGINES = {"sqlite": (None, "sqlite3 (o'rnatilgan)"), "postgresql": ("psycopg", "pip install psycopg[binary]"),
           "mysql": ("pymysql", "pip install pymysql"), "mariadb": ("pymysql", "pip install pymysql"),
           "mssql": ("pyodbc", "pip install pyodbc + ODBC Driver 18"), "mongodb": ("pymongo", "pip install pymongo")}
IDENT = re.compile(r"^[A-Za-z_Ѐ-ӿ][\wЀ-ӿ$]{0,127}(\.[A-Za-z_Ѐ-ӿ][\wЀ-ӿ$]{0,127})?$")


def check_select(sql: str) -> str:
    """Bitta SELECT/WITH so'rovi; yozuvchi buyruqlar va bir nechta so'rov rad etiladi (seans darajasidagi READ ONLY'dan tashqari)."""
    s = re.sub(r"'(?:''|[^'])*'", "''", sql or "")           # satr literallarini olib tashlab tekshiramiz
    s = re.sub(r"--[^\n]*|/\*.*?\*/", " ", s, flags=re.S).strip().rstrip(";").strip()
    if ";" in s:
        raise ConnectorError("Bir nechta SQL so'rovi taqiqlangan", "permission_denied")
    if not re.match(r"(?is)^(select|with)\b", s):
        raise ConnectorError("Faqat SELECT so'rovlari (read-only)", "permission_denied")
    if FORBIDDEN_SQL.search(s):
        raise ConnectorError("So'rovda yozuvchi yoki xavfli buyruq bor — read-only rejimda taqiqlangan", "permission_denied")
    return (sql or "").strip().rstrip(";")


class DatabaseConnector(BaseConnector):
    kind, title = "database", "Ma'lumotlar bazasi"
    protocols = ["PostgreSQL", "MySQL", "MariaDB", "SQLite", "Microsoft SQL Server", "MongoDB", "ODBC"]
    FIELDS = [field("engine", "Baza turi", "select", required=True, options=list(ENGINES), default="sqlite"),
              field("path", "SQLite fayl yo'li (ruxsat berilgan papkada)"), field("host", "Host"), field("port", "Port", "number"),
              field("database", "Baza nomi"), field("username", "Foydalanuvchi", secret=True),
              field("db_password", "Parol", "password", secret=True), field("options", "Qo'shimcha (JSON, masalan sslmode)", "json")]

    def _driver(self):
        eng = self.cfg.get("engine", "sqlite")
        if eng not in ENGINES:
            raise ConnectorError(f"Noma'lum baza turi: {eng}", "error")
        mod, hint = ENGINES[eng]
        if mod:
            try:
                return eng, __import__(mod)
            except ImportError:
                raise NotSupported(f"{eng} drayveri o'rnatilmagan: {hint}") from None
        return eng, sqlite3

    def _connect(self):
        eng, drv = self._driver()
        c = self.cfg
        try:
            if eng == "sqlite":
                p = c.get("path", "")
                if not p or not is_within(p, self.core.settings.allowed_read_dirs):
                    raise ConnectorError("SQLite fayli ruxsat berilgan papkada bo'lishi kerak (Sozlamalar → o'qish papkalari)", "permission_denied")
                if not Path(p).exists():
                    raise ConnectorError("SQLite fayli topilmadi", "error")
                return eng, sqlite3.connect(f"file:{Path(p).as_posix()}?mode=ro", uri=True, timeout=10)     # OS darajasida faqat o'qish
            user, pwd = self.secret("username"), self.secret("db_password")
            if eng == "postgresql":
                conn = drv.connect(host=c.get("host"), port=int(c.get("port") or 5432), dbname=c.get("database"), user=user, password=pwd,
                                   connect_timeout=10, **(c.get("options") or {}))
                conn.read_only = True
                return eng, conn
            if eng in ("mysql", "mariadb"):
                conn = drv.connect(host=c.get("host"), port=int(c.get("port") or 3306), database=c.get("database"), user=user, password=pwd,
                                   connect_timeout=10, read_timeout=60)
                with conn.cursor() as cur:
                    cur.execute("SET SESSION TRANSACTION READ ONLY")
                return eng, conn
            if eng == "mssql":
                cs = (f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={c.get('host')},{c.get('port') or 1433};DATABASE={c.get('database')};"
                      f"UID={user};PWD={pwd};ApplicationIntent=ReadOnly;Encrypt=yes;TrustServerCertificate=yes")
                return eng, drv.connect(cs, timeout=10, readonly=True)
            if eng == "mongodb":
                cl = drv.MongoClient(host=c.get("host"), port=int(c.get("port") or 27017), username=user, password=pwd, serverSelectionTimeoutMS=8000)
                return eng, cl[c.get("database")]
        except ConnectorError:
            raise
        except Exception as e:
            msg = redact(str(e))
            st = "auth_failed" if re.search(r"(?i)password|auth|login|access denied", msg) else "error"
            raise ConnectorError(f"Bazaga ulanib bo'lmadi: {msg[:200]}", st) from None

    def health_check(self):
        eng, conn = self._connect()
        if eng == "mongodb":
            conn.command("ping")
        else:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            conn.close()
        return {"status": "connected", "note": f"{eng}: ulanish ishlaydi (faqat o'qish)"}

    def discover(self):
        eng, conn = self._connect()
        ents, rels = [], []
        if eng == "mongodb":
            for name in conn.list_collection_names()[:200]:
                doc = conn[name].find_one() or {}
                ents.append({"name": name, "source": "collection", "fields": sorted(map(str, doc.keys())), "readable": True})
            return {"modules": ["collections"], "entities": ents, "relations": [], "note": f"{len(ents)} kolleksiya"}
        cur = conn.cursor()
        if eng == "sqlite":
            tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'")]
            for t in tables[:300]:
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')]
                for fk in conn.execute(f'PRAGMA foreign_key_list("{t}")'):
                    rels.append({"from": f"{t}.{fk[3]}", "to": f"{fk[2]}.{fk[4]}"})
                ents.append({"name": t, "source": "table", "fields": cols, "readable": True})
        else:
            schema_filter = {"postgresql": "table_schema NOT IN ('pg_catalog','information_schema')",
                             "mysql": "table_schema = DATABASE()", "mariadb": "table_schema = DATABASE()", "mssql": "1=1"}[eng]
            cur.execute(f"SELECT table_schema, table_name, column_name FROM information_schema.columns WHERE {schema_filter} "
                        "ORDER BY table_schema, table_name, ordinal_position")
            by = {}
            for sch, t, col in cur.fetchall():
                by.setdefault(f"{sch}.{t}" if eng in ("postgresql", "mssql") else t, []).append(col)
            ents = [{"name": k, "source": "table", "fields": v, "readable": True} for k, v in list(by.items())[:300]]
        conn.close()
        return {"modules": ["tables"], "entities": ents, "relations": rels, "note": f"{len(ents)} jadval"}

    def query(self, sql: str, params: tuple | list = (), limit: int = 500) -> dict:
        """Parametrli SELECT (SQL injection'dan himoya: qiymatlar faqat parametr sifatida)."""
        eng, conn = self._connect()
        if eng == "mongodb":
            raise NotSupported("MongoDB uchun SQL emas — fetch_data ishlating")
        sql = check_select(sql)
        wrapped = f"SELECT TOP {int(limit)} * FROM ({sql}) AS q" if eng == "mssql" else f"SELECT * FROM ({sql}) AS q LIMIT {int(limit)}"
        cur = conn.cursor()
        try:
            cur.execute(wrapped, tuple(params))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception as e:
            raise ConnectorError(f"So'rov xatosi: {redact(str(e))[:200]}", "error") from None
        finally:
            conn.close()
        return {"columns": cols, "rows": rows}

    def fetch_data(self, entity, *, since=None, cursor=None, limit=500):
        if not IDENT.match(entity or ""):
            raise ConnectorError("Noto'g'ri jadval nomi", "error")
        eng, conn = self._connect()
        if eng == "mongodb":
            rows = list(conn[entity].find({}, limit=limit, skip=int(cursor or 0)))
            for r in rows:
                r["_id"] = str(r.get("_id"))
            return {"records": rows, "next": (int(cursor or 0) + limit) if len(rows) >= limit else None}
        conn.close()
        known = {e["name"] for e in self.discover()["entities"]}
        if entity not in known:
            raise ConnectorError("Jadval topilmadi", "error")
        q = ".".join(f'"{p}"' if eng != "mysql" else f"`{p}`" for p in entity.split("."))
        off = int(cursor or 0)
        sql = f"SELECT * FROM {q}" + (f" ORDER BY 1 OFFSET {off} ROWS" if eng == "mssql" else "")
        res = self.query(sql, (), limit=limit) if eng == "mssql" else self._page(sql, limit, off)
        return {"records": res["rows"], "next": off + limit if len(res["rows"]) >= limit else None}

    def _page(self, sql, limit, off):
        eng, conn = self._connect()
        cur = conn.cursor()
        try:
            cur.execute(f"SELECT * FROM ({check_select(sql)}) AS q LIMIT {int(limit)} OFFSET {int(off)}")
            cols = [d[0] for d in cur.description]
            return {"columns": cols, "rows": [dict(zip(cols, r)) for r in cur.fetchall()]}
        finally:
            conn.close()


# ================= Fayllar (CSV / Excel / JSON / XML) =================
class FileConnector(BaseConnector):
    kind, title, protocols = "files", "Fayl importi", ["CSV", "Excel", "JSON", "XML"]
    FIELDS = [field("path", "Fayl yoki papka (ruxsat berilgan papkada)", required=True)]
    EXT = (".csv", ".xlsx", ".json", ".xml")

    def _files(self):
        p = Path(self.cfg.get("path", ""))
        if not str(p) or not is_within(p, self.core.settings.allowed_read_dirs):
            raise ConnectorError("Fayl ruxsat berilgan papkada bo'lishi kerak", "permission_denied")
        if p.is_dir():
            return sorted(f for f in p.iterdir() if f.suffix.lower() in self.EXT)[:200]
        if not p.exists():
            raise ConnectorError("Fayl topilmadi", "error")
        return [p]

    def health_check(self):
        n = len(self._files())
        return {"status": "connected", "note": f"{n} ta fayl"}

    def _read(self, f: Path, limit: int = 100000) -> list[dict]:
        s = f.suffix.lower()
        if s == ".csv":
            raw = f.read_bytes()[:50 * 2**20].decode("utf-8-sig", errors="replace")
            dialect = csv.Sniffer().sniff(raw[:5000], delimiters=",;\t") if raw.strip() else csv.excel
            return list(csv.DictReader(raw.splitlines(), dialect=dialect))[:limit]
        if s == ".xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
            ws = wb.worksheets[0]
            it = ws.iter_rows(values_only=True)
            head = [str(h) if h is not None else f"col{i}" for i, h in enumerate(next(it, []))]
            return [dict(zip(head, r)) for _, r in zip(range(limit), it)]
        if s == ".json":
            d = json.loads(f.read_text(encoding="utf-8"))
            rows = d if isinstance(d, list) else next((v for v in d.values() if isinstance(v, list)), [d])
            return [r for r in rows if isinstance(r, dict)][:limit]
        if s == ".xml":
            root = ET.parse(f).getroot()
            kids = list(root)
            return [{c.tag: (c.text or "").strip() for c in k} | dict(k.attrib) for k in kids][:limit]
        return []

    def discover(self):
        ents = []
        for f in self._files():
            try:
                rows = self._read(f, 20)
                ents.append({"name": f.name, "source": str(f), "fields": sorted({k for r in rows for k in r}), "readable": True})
            except Exception as e:
                ents.append({"name": f.name, "source": str(f), "fields": [], "readable": False, "note": str(e)[:120]})
        return {"modules": ["files"], "entities": ents, "note": f"{len(ents)} fayl"}

    def fetch_data(self, entity, *, since=None, cursor=None, limit=5000):
        f = next((x for x in self._files() if x.name == entity), None)
        if not f:
            raise ConnectorError("Fayl topilmadi", "error")
        off = int(cursor or 0)
        rows = self._read(f, off + limit)[off:]
        return {"records": rows, "next": off + limit if len(rows) >= limit else None}


# ================= Kompyuterdagi dasturlar (Windows) =================
KNOWN_APPS = {r"1c|1с|1cv8|предприятие": "1C:Enterprise", r"info.?enterprise|инфо": "Info-Enterprise", r"yespos": "YesPOS",
              r"bito": "BITO", r"cloudshop": "CloudShop", r"postgres": "PostgreSQL", r"mysql|mariadb": "MySQL/MariaDB",
              r"sql server": "Microsoft SQL Server", r"mongodb": "MongoDB"}
PORTS = {5432: "PostgreSQL", 3306: "MySQL/MariaDB", 1433: "MS SQL Server", 27017: "MongoDB", 1541: "1C server", 1540: "1C agent", 80: "lokal web", 8080: "lokal web"}


class DesktopConnector(BaseConnector):
    """O'rnatilgan dasturlar, ishlayotgan jarayonlar va lokal portlarni FAQAT O'QIYDI (registr, psutil).
    Parol yoki login qidirilmaydi. UI Automation (tugmalarni bosish) — bu versiyada YO'Q."""
    kind, title, protocols = "desktop", "Kompyuter dasturlari", ["Windows registry", "process list", "local ports"]
    FIELDS = [field("filter", "Qidiruv (ixtiyoriy): dastur nomi")]

    def health_check(self):
        return {"status": "connected" if os.name == "nt" else "not_supported",
                "note": "Windows'da o'rnatilgan dasturlar ro'yxati o'qiladi" if os.name == "nt" else "Faqat Windows kompyuterda ishlaydi"}

    def installed(self) -> list[dict]:
        if os.name != "nt":
            return []
        import winreg
        out, seen = [], set()
        roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                 (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
        for hive, path in roots:
            try:
                key = winreg.OpenKey(hive, path)
            except OSError:
                continue
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                    get = lambda n: (winreg.QueryValueEx(sub, n)[0] if True else None)  # noqa: E731
                    name = get("DisplayName")
                except OSError:
                    continue
                if not name or name in seen:
                    continue
                seen.add(name)
                rec = {"name": name}
                for k, n in (("version", "DisplayVersion"), ("publisher", "Publisher"), ("location", "InstallLocation")):
                    try:
                        rec[k] = winreg.QueryValueEx(sub, n)[0]
                    except OSError:
                        rec[k] = ""
                out.append(rec)
        return sorted(out, key=lambda r: r["name"].lower())

    def discover(self):
        import psutil
        apps = self.installed()
        flt = (self.cfg.get("filter") or "").lower()
        if flt:
            apps = [a for a in apps if flt in a["name"].lower()]
        known = [a | {"system": s} for a in apps for rx, s in KNOWN_APPS.items() if re.search(rx, a["name"], re.I)]
        procs = sorted({p.info["name"] for p in psutil.process_iter(["name"]) if p.info.get("name")})
        ports = []
        try:
            for c in psutil.net_connections(kind="tcp"):
                if c.status == "LISTEN" and c.laddr and c.laddr.port in PORTS:
                    ports.append({"port": c.laddr.port, "guess": PORTS[c.laddr.port]})
        except (psutil.AccessDenied, PermissionError):
            ports.append({"port": None, "guess": "portlarni ko'rish uchun ruxsat yo'q"})
        return {"modules": ["installed_apps", "processes", "local_ports"],
                "entities": [{"name": "installed_apps", "source": "registry", "fields": ["name", "version", "publisher", "location"], "readable": True}],
                "known_business_apps": known, "processes": procs[:300], "local_ports": ports,
                "note": ("Windows emas — ro'yxat bo'sh" if os.name != "nt" else f"{len(apps)} dastur, {len(known)} ta biznes dasturi aniqlandi")
                        + ". API yoki baza topilsa, uni alohida ulanish sifatida qo'shing. UI Automation bu versiyada yo'q."}

    def fetch_data(self, entity, *, since=None, cursor=None, limit=5000):
        if entity != "installed_apps":
            raise ConnectorError("Faqat installed_apps", "error")
        return {"records": self.installed()[:limit], "next": None}
