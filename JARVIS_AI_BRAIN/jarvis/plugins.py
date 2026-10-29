"""Plugin & Extension Architecture.

Kengaytma = papka: `plugin.json` (manifest) + Python fayl(lar). Joylashuvi: `plugins/` (loyiha bilan keladi) va
`JARVIS_HOME/plugins/` (foydalanuvchi).

Xavfsizlik:
* Yangi yoki o'zgargan kengaytma hech qachon ishonchli deb qabul qilinmaydi: yoqish — C-darajali tasdiq,
  tasdiq aniq versiya, fayllar xeshi va so'ralgan ruxsatlarga bog'lanadi. Fayl o'zgarsa → 'untrusted'.
* Ruxsatlar minimal va aniq: memory.read, memory.write, notify, network. Boshqasi so'ralsa — manifest rad etiladi.
* Kod JARVIS jarayonida EMAS, sandbox'da ishlaydi (statik tekshiruv + audit-hook + limitlar).
  Kengaytma JARVIS'ga to'g'ridan-to'g'ri murojaat qila olmaydi: u natija va "amallar" ro'yxatini qaytaradi,
  JARVIS esa faqat berilgan ruxsat doirasidagi amallarni bajaradi.
* Ketma-ket 3 xato → avtomatik to'xtatiladi ('error').

Kengaytma interfeysi: `def run(input: dict, ctx: dict) -> dict` →
  {"result": ..., "actions": [{"type": "notify", "title": "...", "body": "..."},
                              {"type": "memory.write", "content": "..."}]}
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

from .config import PROJECT_ROOT, jarvis_home
from .sandbox import static_check
from .security import contains_secret, redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS plugins (
    name TEXT PRIMARY KEY, version TEXT, path TEXT NOT NULL, source TEXT NOT NULL, hash TEXT, trusted_hash TEXT,
    status TEXT NOT NULL DEFAULT 'disabled', config TEXT NOT NULL DEFAULT '{}', granted TEXT NOT NULL DEFAULT '[]',
    manifest TEXT, last_error TEXT, runs INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,
    consecutive_errors INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS plugin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), name TEXT NOT NULL,
    level TEXT NOT NULL, message TEXT NOT NULL
);
"""
PERMISSIONS = {"memory.read": "Xotiradan qidirish natijalarini oladi",
               "memory.write": "Xotiraga 'model xulosasi' sifatida yozuv qo'shadi",
               "notify": "Dashboard bildirishnomasi yuboradi",
               "network": "Internetga chiqadi (sandbox'da tarmoq ochiladi)"}
CONFIG_TYPES = {"number": (int, float), "string": (str,), "boolean": (bool,)}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
RESULT_MARK = "__JARVIS_PLUGIN_RESULT__"
HARNESS = '''
import json, sys, importlib.util
data = json.loads(sys.stdin.read() or "{}")
spec = importlib.util.spec_from_file_location("jarvis_plugin", "plugin/%s")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
out = mod.run(data.get("input") or {}, data.get("ctx") or {})
print("%s" + json.dumps(out, ensure_ascii=False, default=str))
'''


class PluginError(Exception):
    pass


def plugin_hash(d: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(x for x in d.rglob("*") if x.is_file() and "__pycache__" not in x.parts):
        h.update(p.relative_to(d).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def validate_manifest(m: dict, d: Path) -> list[str]:
    errs = []
    if not NAME_RE.match(str(m.get("name", ""))):
        errs.append("name: kichik lotin harflar, raqam va _ (2–41 belgi)")
    if not VERSION_RE.match(str(m.get("version", ""))):
        errs.append("version: X.Y.Z ko'rinishida")
    if not str(m.get("description", "")).strip():
        errs.append("description majburiy")
    entry = m.get("entry", "main.py")
    ep = (d / entry).resolve()
    if d.resolve() not in ep.parents or ep.suffix != ".py" or not ep.exists():
        errs.append(f"entry fayli topilmadi yoki papkadan tashqarida: {entry}")
    bad = [p for p in m.get("permissions", []) if p not in PERMISSIONS]
    if bad:
        errs.append(f"noma'lum ruxsatlar: {bad}")
    for k, spec in (m.get("config") or {}).items():
        if spec.get("type") not in CONFIG_TYPES:
            errs.append(f"config.{k}.type: {list(CONFIG_TYPES)}")
    if not isinstance(m.get("dependencies", []), list):
        errs.append("dependencies ro'yxat bo'lishi kerak")
    return errs


class PluginManager:
    def __init__(self, core, dirs: list[Path] | None = None):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        self.dirs = dirs or [PROJECT_ROOT / "plugins", jarvis_home() / "plugins"]
        self.dirs[-1].mkdir(parents=True, exist_ok=True)

    def _log(self, name: str, level: str, msg: str):
        self.core.db.execute("INSERT INTO plugin_logs(name, level, message) VALUES (?,?,?)", (name, level, redact(msg)[:2000]))

    def _row(self, name: str) -> dict:
        r = self.core.db.one("SELECT * FROM plugins WHERE name=?", (name,))
        if not r:
            raise PluginError(f"Kengaytma topilmadi: {name}")
        r["config"], r["granted"] = json.loads(r["config"]), json.loads(r["granted"])
        r["manifest"] = json.loads(r["manifest"] or "{}")
        return r

    # --- topish ---
    def discover(self) -> list[dict]:
        for base in self.dirs:
            if not base.exists():
                continue
            for d in sorted(p for p in base.iterdir() if (p / "plugin.json").exists()):
                try:
                    m = json.loads((d / "plugin.json").read_text(encoding="utf-8"))
                except json.JSONDecodeError as e:
                    m = {"name": d.name}
                    errs = [f"plugin.json o'qilmadi: {e}"]
                else:
                    errs = validate_manifest(m, d)
                name = m.get("name") if NAME_RE.match(str(m.get("name", ""))) else d.name
                h = plugin_hash(d)
                src = "bundled" if base == self.dirs[0] else "user"
                old = self.core.db.one("SELECT * FROM plugins WHERE name=?", (name,))
                if old is None:
                    self.core.db.execute("INSERT INTO plugins(name, version, path, source, hash, status, manifest, last_error)"
                                         " VALUES (?,?,?,?,?,?,?,?)",
                                         (name, m.get("version"), str(d), src, h, "invalid" if errs else "disabled",
                                          json.dumps(m, ensure_ascii=False), "; ".join(errs) or None))
                    continue
                status = old["status"]
                if errs:
                    status = "invalid"
                elif old["trusted_hash"] and h != old["trusted_hash"] and status in ("enabled", "paused"):
                    status = "untrusted"
                    self.core.notifier.notify(f"Kengaytma o'zgardi: {name}", "Fayllari tasdiqlangan versiyadan farq qiladi — "
                                              "qayta tasdiqlanmaguncha ishlamaydi.", severity="warning", category="security")
                elif status == "invalid":
                    status = "disabled"
                self.core.db.execute("UPDATE plugins SET version=?, path=?, hash=?, status=?, manifest=?, last_error=?,"
                                     " updated_at=datetime('now') WHERE name=?",
                                     (m.get("version"), str(d), h, status, json.dumps(m, ensure_ascii=False),
                                      "; ".join(errs) if errs else old["last_error"], name))
        return self.list()

    def list(self) -> list[dict]:
        out = []
        for r in self.core.db.query("SELECT name FROM plugins ORDER BY name"):
            p = self._row(r["name"])
            m = p["manifest"]
            out.append({k: p[k] for k in ("name", "version", "source", "status", "granted", "config", "last_error", "runs", "errors")}
                       | {"description": m.get("description"), "permissions": m.get("permissions", []),
                          "permission_info": {x: PERMISSIONS.get(x) for x in m.get("permissions", [])},
                          "dependencies": m.get("dependencies", []), "missing_dependencies": self._missing(m),
                          "config_schema": m.get("config", {}), "trusted": bool(p["trusted_hash"]) and p["trusted_hash"] == p["hash"]})
        return out

    @staticmethod
    def _missing(m: dict) -> list[str]:
        return [d for d in m.get("dependencies", []) if importlib.util.find_spec(str(d)) is None]

    def logs(self, name: str, limit: int = 50) -> list[dict]:
        return self.core.db.query("SELECT * FROM plugin_logs WHERE name=? ORDER BY id DESC LIMIT ?", (name, limit))

    # --- ishonch va holat ---
    def _code_findings(self, p: dict) -> list[dict]:
        d = Path(p["path"])
        net = "network" in p["manifest"].get("permissions", [])
        out = []
        for f in sorted(d.rglob("*.py")):
            for x in static_check(f.read_text(encoding="utf-8"), allow_network=net):
                out.append(x | {"file": f.name})
        return out

    def request_enable(self, name: str) -> dict:
        self.discover()
        p = self._row(name)
        if p["status"] == "invalid":
            raise PluginError(f"Manifest noto'g'ri: {p['last_error']}")
        missing = self._missing(p["manifest"])
        if missing:
            raise PluginError(f"Bog'liqliklar o'rnatilmagan: {missing}")
        blocked = [f for f in self._code_findings(p) if f["severity"] == "block"]
        if blocked:
            raise PluginError("Kodda xavfli qismlar bor: " + "; ".join(f"{b['file']}:{b['line']} {b['msg']}" for b in blocked[:5]))
        perms = p["manifest"].get("permissions", [])
        return self.core.approvals.request(
            action_type="plugin_enable", target=f"plugin:{name}", level="C", requested_by="plugin_manager",
            payload={"name": name, "version": p["version"], "hash": p["hash"], "permissions": perms},
            summary=f"Kengaytmani yoqish: {name} v{p['version']} — ruxsatlar: {', '.join(perms) or 'yo‘q'}",
            purpose=p["manifest"].get("description", ""))

    def enable(self, name: str, approval_id: int) -> dict:
        p = self._row(name)
        perms = p["manifest"].get("permissions", [])
        self.core.approvals.authorize_execution(approval_id, {"name": name, "version": p["version"], "hash": p["hash"],
                                                              "permissions": perms})
        self.core.approvals.mark_result(approval_id, "executed")
        cfg = self._defaults(p["manifest"]) | p["config"]
        self.core.db.execute("UPDATE plugins SET status='enabled', trusted_hash=?, granted=?, config=?, consecutive_errors=0,"
                             " last_error=NULL WHERE name=?", (p["hash"], json.dumps(perms), json.dumps(cfg), name))
        self._log(name, "info", f"Yoqildi (v{p['version']}, ruxsatlar: {perms})")
        self.core.audit.log("plugin_manager", f"Kengaytma yoqildi: {name}", target=f"plugin:{name}", risk="C", approval_status="approved")
        return self._row(name)

    def set_status(self, name: str, status: str) -> dict:
        p = self._row(name)
        if status not in ("disabled", "paused", "enabled"):
            raise PluginError("Holat: disabled, paused yoki enabled")
        if status == "enabled":
            if p["status"] != "paused" or p["trusted_hash"] != plugin_hash(Path(p["path"])):
                raise PluginError("Faqat to'xtatilgan va o'zgarmagan kengaytma davom ettiriladi; aks holda qayta tasdiq kerak")
        if status == "disabled":
            self.core.db.execute("UPDATE plugins SET status='disabled', trusted_hash=NULL, granted='[]' WHERE name=?", (name,))
        else:
            self.core.db.execute("UPDATE plugins SET status=? WHERE name=?", (status, name))
        self._log(name, "info", f"Holat: {status}")
        return self._row(name)

    @staticmethod
    def _defaults(m: dict) -> dict:
        return {k: v.get("default") for k, v in (m.get("config") or {}).items() if "default" in v}

    def configure(self, name: str, config: dict) -> dict:
        p = self._row(name)
        schema = p["manifest"].get("config") or {}
        unknown = [k for k in config if k not in schema]
        if unknown:
            raise PluginError(f"Noma'lum sozlamalar: {unknown}")
        for k, v in config.items():
            t = schema[k]["type"]
            if not isinstance(v, CONFIG_TYPES[t]) or (t == "number" and isinstance(v, bool)):
                raise PluginError(f"{k}: {t} bo'lishi kerak")
        if contains_secret(json.dumps(config)):
            raise PluginError("Sozlamada maxfiy kalit bo'lmasligi kerak (secret storage ishlating)")
        cfg = self._defaults(p["manifest"]) | p["config"] | config
        missing = [k for k, v in schema.items() if v.get("required") and cfg.get(k) in (None, "")]
        if missing:
            raise PluginError(f"Majburiy sozlamalar: {missing}")
        self.core.db.execute("UPDATE plugins SET config=? WHERE name=?", (json.dumps(cfg, ensure_ascii=False), name))
        return self._row(name)

    # --- ishga tushirish ---
    def run(self, name: str, input_: dict | None = None) -> dict:
        p = self._row(name)
        if p["status"] != "enabled":
            raise PluginError(f"Kengaytma yoqilmagan (holat: {p['status']})")
        d = Path(p["path"])
        if plugin_hash(d) != p["trusted_hash"]:
            self.core.db.execute("UPDATE plugins SET status='untrusted' WHERE name=?", (name,))
            raise PluginError("Kengaytma fayllari tasdiqdan keyin o'zgargan — qayta tasdiqlash kerak")
        m, granted = p["manifest"], set(p["granted"])
        schema = m.get("config") or {}
        missing_cfg = [k for k, v in schema.items() if v.get("required") and p["config"].get(k) in (None, "")]
        if missing_cfg:
            raise PluginError(f"Majburiy sozlamalar kiritilmagan: {missing_cfg}")
        input_ = input_ or {}
        ctx = {"config": p["config"], "plugin": {"name": name, "version": p["version"]}, "permissions": sorted(granted)}
        if "memory.read" in granted and input_.get("query"):
            ctx["memory"] = [{"content": x["content"], "source": x["source"], "info_type": x["info_type"]}
                             for x in self.core.memory.search(str(input_["query"]), 10)]
        files = {f"plugin/{f.relative_to(d).as_posix()}": f.read_text(encoding="utf-8")
                 for f in d.rglob("*") if f.is_file() and f.suffix in (".py", ".json", ".txt", ".csv") and "__pycache__" not in f.parts}
        entry = m.get("entry", "main.py")
        s = self.core.settings
        r = self.core.sandbox.execute(HARNESS % (entry, RESULT_MARK), allow_network="network" in granted,
                                      stdin=json.dumps({"input": input_, "ctx": ctx}, ensure_ascii=False),
                                      timeout=s.sandbox_timeout_sec, memory_mb=s.sandbox_memory_mb, files=files,
                                      findings=self._code_findings(p), kind=f"plugin:{name}")
        out = None
        if r["status"] == "ok" and RESULT_MARK in r["stdout"]:
            try:
                out = json.loads(r["stdout"].split(RESULT_MARK, 1)[1].strip().splitlines()[0])
            except (json.JSONDecodeError, IndexError):
                out = None
        if out is None or not isinstance(out, dict):
            err = (r["stderr"].strip().splitlines() or [r["status"]])[-1]
            return self._fail(name, f"{r['status']}: {err}", r["id"])
        applied, rejected = self._apply_actions(name, granted, out.get("actions") or [])
        self.core.db.execute("UPDATE plugins SET runs=runs+1, consecutive_errors=0 WHERE name=?", (name,))
        self._log(name, "info", f"Ishladi (sandbox#{r['id']}, {r['duration_ms']} ms); amallar: {len(applied)}, rad: {len(rejected)}")
        return {"result": out.get("result"), "actions_applied": applied, "actions_rejected": rejected, "sandbox_run": r["id"],
                "duration_ms": r["duration_ms"]}

    def _fail(self, name: str, msg: str, run_id: int) -> dict:
        self.core.db.execute("UPDATE plugins SET errors=errors+1, consecutive_errors=consecutive_errors+1, last_error=? WHERE name=?",
                             (msg[:500], name))
        self._log(name, "error", msg)
        p = self._row(name)
        if p["consecutive_errors"] >= 3:
            self.core.db.execute("UPDATE plugins SET status='error' WHERE name=?", (name,))
            self.core.notifier.notify(f"Kengaytma to'xtatildi: {name}", "Ketma-ket 3 xato. " + msg[:200], severity="warning", category="plugin")
        raise PluginError(f"Kengaytma xatosi: {msg}")

    def _apply_actions(self, name: str, granted: set, actions: list) -> tuple[list, list]:
        applied, rejected = [], []
        for a in actions[:20]:
            t = a.get("type") if isinstance(a, dict) else None
            need = {"notify": "notify", "memory.write": "memory.write"}.get(t)
            if not need or need not in granted:
                rejected.append({"action": t, "reason": "ruxsat berilmagan" if need else "noma'lum amal"})
                self._log(name, "warning", f"Rad etilgan amal: {t}")
                continue
            try:
                if t == "notify":
                    self.core.notifier.notify(f"[{name}] {str(a.get('title', ''))[:150]}", str(a.get("body", "")), category="plugin")
                else:
                    self.core.memory.add(str(a.get("content", "")), "knowledge", source=f"plugin:{name}", info_type="model_inference",
                                         confidence=0.5)
                applied.append({"action": t})
            except Exception as e:
                rejected.append({"action": t, "reason": str(e)})
        return applied, rejected
