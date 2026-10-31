"""Universal Integration Engine — Connector Registry, Auth (Vault), Discovery, Mapping, Sync, Monitor, Permissions, Audit.

Yangi tizim qo'shish uchun asosiy kodni o'zgartirish shart emas: adapter klassini ADAPTERS ga qo'shish yetarli.
Ma'lumotlar har bir ulanish (manba) bo'yicha ALOHIDA saqlanadi (ext_records.conn_id) — do'konlar aralashmaydi.
"""
from __future__ import annotations

import hashlib
import json
from urllib.parse import urlparse
import re
import time
from datetime import datetime, timezone

from ..security import contains_secret, redact
from . import mapping as M
from .base import MODES, STATUSES, ConnectorError, NotSupported
from .detect import detect
from .http_api import GraphQLConnector, ODataConnector, RestConnector
from .mcp_db_files import DatabaseConnector, DesktopConnector, FileConnector, MCPConnector
from .presets import PRESETS
from .vault import FIELDS as SECRET_FIELDS
from .vault import Vault, VaultError
from .website import WebsiteConnector

ADAPTERS = {c.kind: c for c in (RestConnector, ODataConnector, GraphQLConnector, MCPConnector, WebsiteConnector,
                                DatabaseConnector, FileConnector, DesktopConnector)}
SYSTEM_TYPES = {"pos": "POS", "erp": "ERP", "crm": "CRM", "website": "Website", "api": "API", "mcp": "MCP Server",
                "database": "Database", "files": "Files", "desktop": "Desktop App", "shop": "Internet-do'kon", "other": "Boshqa"}
FINANCIAL = ("price", "narx", "payment", "to'lov", "debt", "qarz", "cash", "kassa", "receipt", "chek", "delete", "remove", "refund")

SCHEMA = """
CREATE TABLE IF NOT EXISTS integrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, system_type TEXT NOT NULL, adapter TEXT NOT NULL, preset TEXT,
    store TEXT, config TEXT NOT NULL DEFAULT '{}', mode TEXT NOT NULL DEFAULT 'read_only', status TEXT NOT NULL DEFAULT 'new',
    status_note TEXT, modules TEXT NOT NULL DEFAULT '[]', entities TEXT NOT NULL DEFAULT '[]', mapping TEXT NOT NULL DEFAULT '{}',
    learning TEXT, sync_interval_min INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
    last_sync TEXT, last_ok TEXT, last_check TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT
);
CREATE TABLE IF NOT EXISTS ext_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT, conn_id INTEGER NOT NULL, source_entity TEXT NOT NULL, source_id TEXT NOT NULL,
    entity TEXT, data TEXT NOT NULL, raw TEXT NOT NULL, hash TEXT NOT NULL, confidence REAL, verification TEXT NOT NULL DEFAULT 'unverified',
    retrieved_at TEXT NOT NULL, first_seen TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, untrusted INTEGER NOT NULL DEFAULT 0,
    UNIQUE(conn_id, source_entity, source_id)
);
CREATE INDEX IF NOT EXISTS ext_records_ent ON ext_records(conn_id, entity, deleted);
CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, conn_id INTEGER NOT NULL, mode TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
    status TEXT NOT NULL, counts TEXT, error TEXT, trigger TEXT
);
CREATE TABLE IF NOT EXISTS sync_state (conn_id INTEGER NOT NULL, source_entity TEXT NOT NULL, cursor TEXT, PRIMARY KEY(conn_id, source_entity));
CREATE TABLE IF NOT EXISTS integration_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, conn_id INTEGER NOT NULL, entity TEXT NOT NULL, operation TEXT NOT NULL, payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft', approval_id INTEGER, result TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class IntegrationError(ValueError):
    pass


class IntegrationHub:
    retry_delays = (1, 2, 4)            # sinxronlashda qayta urinishlar (testlarda 0)

    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        self.vault = Vault(core)

    # ---------------- Registry ----------------
    def catalog(self) -> dict:
        return {"adapters": {k: {"title": c.title, "protocols": c.protocols, "fields": c.FIELDS, "can_write": c.can_write} for k, c in ADAPTERS.items()},
                "presets": PRESETS, "system_types": SYSTEM_TYPES, "modes": MODES, "statuses": sorted(STATUSES)}

    def _row(self, r: dict) -> dict:
        for k in ("config", "modules", "entities", "mapping"):
            r[k] = json.loads(r[k] or ("{}" if k in ("config", "mapping") else "[]"))
        r["learning"] = json.loads(r["learning"]) if r.get("learning") else None
        r["secrets"] = [f["field"] for f in self.vault.fields(r["id"])]
        r["records"] = self.core.db.one("SELECT COUNT(*) n FROM ext_records WHERE conn_id=? AND deleted=0", (r["id"],))["n"]
        return r

    def get(self, cid: int) -> dict:
        r = self.core.db.one("SELECT * FROM integrations WHERE id=?", (cid,))
        if not r:
            raise IntegrationError("Ulanish topilmadi")
        return self._row(r)

    def list(self, system_type: str = "") -> list[dict]:
        rows = self.core.db.query("SELECT * FROM integrations" + (" WHERE system_type=?" if system_type else "") + " ORDER BY id",
                                  (system_type,) if system_type else ())
        return [self._row(r) for r in rows]

    def _clean_config(self, adapter: str, config: dict) -> dict:
        cls = ADAPTERS[adapter]
        allowed = {f["key"]: f for f in cls.FIELDS if not f["secret"]}
        out = {}
        for k, v in (config or {}).items():
            if k not in allowed or v in (None, ""):
                continue
            if allowed[k]["type"] == "json" and isinstance(v, str):
                try:
                    v = json.loads(v)
                except ValueError:
                    raise IntegrationError(f"'{allowed[k]['label']}' maydoni yaroqli JSON emas") from None
            if contains_secret(json.dumps(v, ensure_ascii=False)):
                raise IntegrationError(f"'{k}' maydonida maxfiy ma'lumotga o'xshash qiymat bor — uni maxfiy maydonga kiriting")
            out[k] = v
        return out

    def create(self, *, name: str, system_type: str, adapter: str, config: dict | None = None, secrets: dict | None = None,
               store: str = "", preset: str = "", mode: str = "read_only", sync_interval_min: int = 0) -> dict:
        if preset and preset in PRESETS:
            p = PRESETS[preset]
            adapter, system_type = adapter or p["adapter"], system_type or p["system_type"]
            config = {**p["config"], **(config or {})}
        if adapter not in ADAPTERS:
            raise IntegrationError(f"Noma'lum adapter: {adapter}")
        if system_type not in SYSTEM_TYPES:
            raise IntegrationError("Noma'lum tizim turi")
        if not (name or "").strip():
            raise IntegrationError("Tizim nomi kerak")
        if mode not in MODES:
            raise IntegrationError("Noma'lum rejim")
        cfg = self._clean_config(adapter, config or {})
        missing = [f["label"] for f in ADAPTERS[adapter].FIELDS if f["required"] and not f["secret"] and not cfg.get(f["key"])]
        if missing:
            raise IntegrationError(f"Majburiy maydonlar: {', '.join(missing)}")
        cur = self.core.db.execute("INSERT INTO integrations(name, system_type, adapter, preset, store, config, mode, sync_interval_min, updated_at)"
                                   " VALUES (?,?,?,?,?,?,?,?,?)", (name.strip()[:80], system_type, adapter, preset or None, (store or "").strip()[:80] or None,
                                                                 json.dumps(cfg, ensure_ascii=False), mode, max(0, int(sync_interval_min)), _now()))
        cid = cur.lastrowid
        try:
            self.set_secrets(cid, secrets or {})
        except VaultError:
            self.core.db.execute("DELETE FROM integrations WHERE id=?", (cid,))
            raise
        self.core.audit.log("integration", f"Ulanish qo'shildi: {name} ({adapter})", target=f"conn#{cid}", risk="C", approval_status="user_action")
        self._kg_conn(self.get(cid))
        return self.get(cid)

    def update(self, cid: int, *, config: dict | None = None, secrets: dict | None = None, name: str | None = None, store: str | None = None,
               sync_interval_min: int | None = None, enabled: bool | None = None) -> dict:
        c = self.get(cid)
        if config is not None:
            cfg = {**c["config"], **self._clean_config(c["adapter"], config)}
            self.core.db.execute("UPDATE integrations SET config=?, updated_at=? WHERE id=?", (json.dumps(cfg, ensure_ascii=False), _now(), cid))
        for col, v in (("name", name), ("store", store), ("sync_interval_min", sync_interval_min), ("enabled", enabled)):
            if v is not None:
                self.core.db.execute(f"UPDATE integrations SET {col}=?, updated_at=? WHERE id=?", (int(v) if col in ("sync_interval_min", "enabled") else v, _now(), cid))
        if secrets:
            self.set_secrets(cid, secrets)
        self.core.audit.log("integration", f"Ulanish o'zgartirildi: #{cid}", target=f"conn#{cid}", risk="C", approval_status="user_action")
        return self.get(cid)

    def set_secrets(self, cid: int, secrets: dict):
        for k, v in (secrets or {}).items():
            if v in (None, ""):
                continue
            if k not in SECRET_FIELDS and not re.fullmatch(r"f_[a-z0-9_]{1,30}", k):     # f_* — sayt tekshiruvi aniqlagan kirish maydonlari
                raise IntegrationError(f"Noma'lum maxfiy maydon: {k}")
            self.vault.set(cid, k, str(v))
        if secrets and self.core.db.one("SELECT 1 FROM integrations WHERE id=? AND status='connected'", (cid,)):
            self._status(cid, "new", "Kirish ma'lumotlari o'zgardi — qayta tekshiring")

    def set_mode(self, cid: int, mode: str) -> dict:
        if mode not in MODES:
            raise IntegrationError("Noma'lum rejim")
        self.get(cid)
        self.core.db.execute("UPDATE integrations SET mode=?, updated_at=? WHERE id=?", (mode, _now(), cid))
        self.core.audit.log("integration", f"Ruxsat darajasi: {mode}", target=f"conn#{cid}", risk="D", approval_status="user_action")
        return self.get(cid)

    def delete(self, cid: int) -> dict:
        c = self.get(cid)
        self.vault.delete_all(cid)
        for t in ("ext_records", "sync_runs", "sync_state", "integration_proposals"):
            self.core.db.execute(f"DELETE FROM {t} WHERE conn_id=?", (cid,))
        self.core.db.execute("DELETE FROM integrations WHERE id=?", (cid,))
        self.core.audit.log("integration", f"Ulanish o'chirildi: {c['name']} (kalitlar va yuklangan ma'lumotlar)", target=f"conn#{cid}", risk="D",
                            approval_status="user_action")
        return {"deleted": cid}

    # ---------------- Adapter ----------------
    def connector(self, c: dict):
        return ADAPTERS[c["adapter"]](c, lambda f: self.vault.get(c["id"], f), self.core)

    def _status(self, cid: int, status: str, note: str = ""):
        prev = self.core.db.one("SELECT status, name FROM integrations WHERE id=?", (cid,))
        self.core.db.execute("UPDATE integrations SET status=?, status_note=?, last_check=?" + (", last_ok=?" if status == "connected" else "") + " WHERE id=?",
                             (status, redact(note)[:300], _now(), *([_now()] if status == "connected" else []), cid))
        bad = {"disconnected", "auth_expired", "auth_failed", "permission_denied", "error", "user_action_required"}
        if prev and prev["status"] == "connected" and status in bad:
            self.core.notifier.notify(f"Ulanish uzildi: {prev['name']}", f"Holat: {status}. {redact(note)[:200]}", severity="warning", category="integration")
        elif prev and prev["status"] in bad and status == "connected":
            self.core.notifier.notify(f"Ulanish tiklandi: {prev['name']}", "", category="integration")

    def _call(self, cid: int, what: str, fn):
        try:
            res = fn()
        except ConnectorError as e:
            self._status(cid, e.status, str(e))
            self.core.audit.log("integration", f"{what}: {e.status}", target=f"conn#{cid}", risk="A", error_code=e.status, error_note=redact(str(e))[:200])
            raise IntegrationError(redact(str(e))) from None
        except Exception as e:
            self._status(cid, "error", f"{type(e).__name__}: {e}")
            self.core.audit.error("integration", f"conn#{cid} {what}: {e}")
            raise IntegrationError(redact(f"{what} xatosi: {e}")) from None
        return res

    def test(self, cid: int) -> dict:
        c = self.get(cid)
        r = self._call(cid, "test", lambda: self.connector(c).connect())
        self._status(cid, r.get("status", "connected"), r.get("note", ""))
        self.core.audit.log("integration", f"Ulanish tekshirildi: {c['name']} → {r.get('status')}", target=f"conn#{cid}", risk="A")
        out = self.get(cid) | {"result": r}
        if out["status"] == "connected" and self.auto_learn:
            out["auto_learn"] = self.auto_learn_start(cid)
        return out

    # ---------------- Avtomatik o'rganish (faqat o'qish) ----------------
    auto_learn = True                                       # testlarda o'chiriladi
    _learning: set = set()

    def needs_learning(self, c: dict) -> bool:
        if not c.get("entities"):
            return True
        last = (c.get("learning") or {}).get("learned_at")
        try:
            t = datetime.fromisoformat(last)
            t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - t).total_seconds() > 24 * 3600
        except (TypeError, ValueError):
            return True

    def auto_learn_start(self, cid: int, force: bool = False) -> dict:
        """Ulanish ishlasa — fonda o'zi o'rganadi (discover), xaritalaydi va sinxronlaydi. Hammasi faqat o'qish."""
        c = self.get(cid)
        if cid in self._learning:
            return {"started": False, "note": "o'rganilmoqda…"}
        if not force and not self.needs_learning(c):
            return {"started": False, "note": "yaqinda o'rganilgan"}
        import threading
        self._learning.add(cid)
        self._status(cid, "connected", "⏳ JARVIS saytni o'zi o'rganmoqda va ma'lumotni olmoqda (1–3 daqiqa) — sahifani keyinroq yangilang")

        def work():
            off = getattr(self.core, "office_live", None)
            try:
                if off:
                    off.log("hisobchi", f"{c['name']}: saytni o'rganyapman (bo'limlar, jadvallar, API)…", "work")
                d = self.discover(cid)
                n = len(d.get("entities") or [])
                mapped = [k for k, v in (d.get("mapping") or {}).items() if v.get("entity")]
                if off:
                    off.log("hisobchi", f"{c['name']}: {n} ta ma'lumot manbai topildi, {len(mapped)} tasi tushunildi", "done" if mapped else "warn")
                if mapped:
                    s = self.sync(cid, trigger="auto_learn")
                    if off:
                        off.log("hisobchi", f"{c['name']}: ma'lumot olindi — {json.dumps(s.get('counts') or {}, ensure_ascii=False)[:150]}", "done")
            except Exception as e:                          # noqa: BLE001 — holat ulanish kartasida ko'rinadi
                self.core.audit.error("integration", f"auto_learn #{cid}: {e}")
                if off:
                    off.log("hisobchi", f"{c['name']}: o'rganishda muammo — {str(e)[:150]}", "error")
            finally:
                self._learning.discard(cid)
        threading.Thread(target=work, daemon=True, name=f"learn-{cid}").start()
        return {"started": True, "note": "JARVIS saytni o'zi o'rganmoqda va ma'lumotni olmoqda (1–3 daqiqa)"}

    def disconnect(self, cid: int) -> dict:
        c = self.get(cid)
        try:
            self.connector(c).disconnect()
        except Exception:
            pass
        p = self.vault._blob_path(cid, "session")
        if p.exists():
            p.unlink()                          # brauzer sessiyasi o'chiriladi
        self.core.db.execute("UPDATE integrations SET enabled=0 WHERE id=?", (cid,))
        self._status(cid, "disconnected", "Foydalanuvchi uzdi")
        self.core.audit.log("integration", f"Ulanish uzildi: {c['name']}", target=f"conn#{cid}", risk="C", approval_status="user_action")
        return self.get(cid)

    # ---------------- Discovery & Learning ----------------
    def discover(self, cid: int) -> dict:
        c = self.get(cid)
        d = self._call(cid, "discover", lambda: self.connector(c).discover())
        ents = d.get("entities", [])
        sugg = M.suggest(ents)
        self._ai_map(ents, sugg)
        old = c["mapping"] or {}
        for k, v in sugg.items():                    # foydalanuvchi tasdiqlagan xaritalar saqlanadi
            if old.get(k, {}).get("status") == "confirmed":
                sugg[k] = old[k]
        readable = [e for e in ents if e.get("readable")]
        learning = {"system": c["name"], "adapter": c["adapter"], "connection": "muvaffaqiyatli", "modules": d.get("modules", []),
                    "entities": [{"name": e["name"], "readable": e.get("readable", False), "maps_to": sugg.get(e["name"], {}).get("entity"),
                                  "confidence": sugg.get(e["name"], {}).get("confidence", 0), "unmapped": sugg.get(e["name"], {}).get("unmapped", [])}
                                 for e in ents],
                    "data_available": {k: any(v.get("entity") == k for v in sugg.values()) for k in M.MODEL},
                    "relations": d.get("relations", []), "note": d.get("note", ""), "extra": {k: d[k] for k in ("known_business_apps", "local_ports", "network") if k in d},
                    "learned_at": _now(), "mode": c["mode"],
                    "warning": "Noma'lum maydonlar to'ldirilmagan — 'unmapped' ro'yxatini tekshiring. Tahlilda faqat tasdiqlangan yoki ishonchli xaritalar ishlatiladi."}
        self.core.db.execute("UPDATE integrations SET modules=?, entities=?, mapping=?, learning=?, updated_at=? WHERE id=?",
                             (json.dumps(d.get("modules", []), ensure_ascii=False), json.dumps(ents, ensure_ascii=False, default=str),
                              json.dumps(sugg, ensure_ascii=False), json.dumps(learning, ensure_ascii=False, default=str), _now(), cid))
        self._status(cid, "connected", d.get("note", ""))
        self._kg_discovery(self.get(cid))
        ss = getattr(self.core, "site_skills", None)
        if ss and c["adapter"] == "website":                # sayt nima qila oladi (rasm/video/matn yaratish ...) — Site Skills
            try:
                ss.detect(cid, d.get("pages", []))
            except Exception as e:                         # noqa: BLE001 — aniqlash xatosi ulanishni buzmaydi
                self.core.audit.error("site_skills", f"Ko'nikma aniqlash: {e}")
        self.core.audit.log("integration", f"O'rganildi: {c['name']} — {len(ents)} obyekt, o'qiladigan {len(readable)}", target=f"conn#{cid}", risk="A")
        return self.get(cid) | {"discovery": {k: v for k, v in d.items() if k != "entities"}}

    def _ai_map(self, ents: list[dict], sugg: dict):
        """Lug'at bilan tushunilmagan obyektlarni AI'dan so'rash (faqat obyekt va maydon NOMLARI yuboriladi, qiymatlar emas)."""
        unknown = [e for e in ents if not (sugg.get(e["name"]) or {}).get("entity") and e.get("fields")][:8]
        ai = getattr(self.core, "ai", None)
        if not unknown or not ai or not any(p["kind"] != "offline" and p["available"] for p in ai.status()):
            return
        spec = {k: list(v) for k, v in M.MODEL.items()}
        q = ("POS/biznes tizimidan olingan ma'lumot manbalari (nomi va maydon nomlari). Har biri JARVIS modelidagi qaysi obyektga mos va "
             f"maydonlari qaysi maydonga mos? Model: {json.dumps(spec, ensure_ascii=False)}\nManbalar: "
             + json.dumps([{"name": e["name"], "fields": e["fields"][:40]} for e in unknown], ensure_ascii=False)
             + '\nFaqat JSON qaytar: {"<manba nomi>": {"entity": "product|sale|customer|supplier|payment|movement|expense|null", '
               '"fields": {"<manba maydoni>": "<model maydoni>"}}}. Ishonching komil bo\'lmasa — null.')
        try:
            r = ai.route([{"role": "user", "content": q}], purpose="analysis", private=False)
            if (r.get("route") or {}).get("provider") == "offline":
                return
            import re as _re
            m = _re.search(r"\{.*\}", r.get("text", ""), _re.S)
            ans = json.loads(m.group(0)) if m else {}
        except Exception:                                   # noqa: BLE001 — AI bo'lmasa lug'at natijasi qoladi
            return
        for e in unknown:
            a = ans.get(e["name"]) if isinstance(ans, dict) else None
            ent = (a or {}).get("entity")
            if ent not in M.MODEL:
                continue
            fields = {f: t for f, t in ((a or {}).get("fields") or {}).items() if f in e["fields"] and t in M.MODEL[ent]}
            if not fields:
                continue
            sugg[e["name"]] = {"entity": ent, "fields": fields, "unmapped": [f for f in e["fields"] if f not in fields],
                               "confidence": 0.6, "status": "ai_suggested"}

    def confirm_mapping(self, cid: int, source_entity: str, entity: str | None, fields: dict) -> dict:
        c = self.get(cid)
        if entity and entity not in M.MODEL:
            raise IntegrationError("Noma'lum JARVIS obyekti")
        bad = [v for v in fields.values() if entity and v and v not in M.MODEL[entity]]
        if bad:
            raise IntegrationError(f"Noma'lum maydon(lar): {bad}")
        src_fields = next((e.get("fields", []) for e in c["entities"] if e["name"] == source_entity), [])
        m = c["mapping"]
        m[source_entity] = {"entity": entity, "fields": {k: v for k, v in fields.items() if v}, "unmapped": [f for f in src_fields if not fields.get(f)],
                            "confidence": 1.0, "status": "confirmed"}
        self.core.db.execute("UPDATE integrations SET mapping=? WHERE id=?", (json.dumps(m, ensure_ascii=False), cid))
        self.core.db.execute("UPDATE ext_records SET verification='mapping_confirmed' WHERE conn_id=? AND source_entity=?", (cid, source_entity))
        self.core.audit.log("user", f"Maydonlar xaritasi tasdiqlandi: #{cid} {source_entity} → {entity}", target=f"conn#{cid}", risk="A",
                            approval_status="user_action")
        return self.get(cid)

    # ---------------- Sync ----------------
    def sync(self, cid: int, mode: str = "incremental", trigger: str = "manual", max_records: int = 50000) -> dict:
        c = self.get(cid)
        if not c["enabled"]:
            raise IntegrationError("Ulanish o'chirilgan (uzilgan) — avval qayta yoqing")
        if mode not in ("incremental", "full"):
            raise IntegrationError("Rejim: incremental yoki full")
        targets = {k: v for k, v in (c["mapping"] or {}).items() if v.get("entity") and (v.get("status") == "confirmed" or v.get("confidence", 0) >= 0.5)}
        if not targets:
            if not c["entities"]:
                raise IntegrationError("Bu saytdan hali o'qiladigan ma'lumot topilmagan — avval 'O'rganish'ni bosing. Topilmasa: sayt sozlamalarida "
                                       "'O'qiladigan sahifalar'ga tovarlar/savdolar sahifasi manzilini yozing.")
            raise IntegrationError(f"{len(c['entities'])} ta ma'lumot manbai topildi, lekin qaysi biri tovar, savdo yoki mijoz ekanini aniqlab bo'lmadi — "
                                   "'Batafsil' → maydonlar xaritasida belgilang.")
        run = self.core.db.execute("INSERT INTO sync_runs(conn_id, mode, started_at, status, trigger) VALUES (?,?,?,?,?)",
                                   (cid, mode, _now(), "running", trigger)).lastrowid
        self._status(cid, "syncing", f"{mode} sinxronlash")
        conn = self.connector(c)
        counts, errors = {}, []
        ents = {e["name"]: e for e in c["entities"]}
        for src, mp in targets.items():
            cnt = {"new": 0, "changed": 0, "same": 0, "deleted": 0}
            state = self.core.db.one("SELECT cursor FROM sync_state WHERE conn_id=? AND source_entity=?", (cid, src))
            since = state["cursor"] if (state and mode == "incremental") else None
            seen, cursor, fetched, last_upd = set(), None, 0, since
            id_field = next((k for k, v in mp["fields"].items() if v in ("sku", "id", "receipt_no")), None)
            try:
                while fetched < max_records:
                    page = None
                    for attempt, delay in enumerate((0, *self.retry_delays)):
                        if delay:
                            time.sleep(delay)
                        try:
                            page = conn.fetch_data(src if src in ents else src, since=since, cursor=cursor)
                            break
                        except ConnectorError as e:
                            if e.status in ("auth_expired", "auth_failed", "permission_denied", "user_action_required", "not_supported") or attempt == len(self.retry_delays):
                                raise
                            if e.status == "rate_limited":
                                raise
                    recs = page["records"]
                    for row in recs:
                        raw = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                        h = hashlib.sha256(raw.encode()).hexdigest()
                        sid = str(row.get(id_field)) if id_field and row.get(id_field) not in (None, "") else h[:24]
                        if mp["entity"] == "sale" and not id_field:
                            sid = h[:24]
                        seen.add(sid)
                        data = M.apply(mp, row)
                        if c.get("store"):
                            data.setdefault("store", c["store"])
                        ex = self.core.db.one("SELECT id, hash FROM ext_records WHERE conn_id=? AND source_entity=? AND source_id=?", (cid, src, sid))
                        if not ex:
                            self.core.db.execute("INSERT INTO ext_records(conn_id, source_entity, source_id, entity, data, raw, hash, confidence, verification,"
                                                 " retrieved_at, first_seen, untrusted) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                                 (cid, src, sid, mp["entity"], json.dumps(data, ensure_ascii=False), raw[:20000], h, mp.get("confidence"),
                                                  "mapping_confirmed" if mp.get("status") == "confirmed" else "unverified", _now(), _now(), int(bool(page.get("untrusted")))))
                            cnt["new"] += 1
                        elif ex["hash"] != h:
                            self.core.db.execute("UPDATE ext_records SET data=?, raw=?, hash=?, retrieved_at=?, deleted=0 WHERE id=?",
                                                 (json.dumps(data, ensure_ascii=False), raw[:20000], h, _now(), ex["id"]))
                            cnt["changed"] += 1
                        else:
                            self.core.db.execute("UPDATE ext_records SET retrieved_at=?, deleted=0 WHERE id=?", (_now(), ex["id"]))
                            cnt["same"] += 1
                        upd = row.get("updated_at") or row.get("modified")
                        if upd and (not last_upd or str(upd) > str(last_upd)):
                            last_upd = str(upd)
                    fetched += len(recs)
                    cursor = page.get("next")
                    if not cursor or not recs:
                        break
                if mode == "full" and seen:          # o'chirilgan yozuvlar faqat to'liq sinxronlashda aniqlanadi (tashqi tizimda hech narsa o'chirilmaydi)
                    rows = self.core.db.query("SELECT id, source_id FROM ext_records WHERE conn_id=? AND source_entity=? AND deleted=0", (cid, src))
                    gone = [r["id"] for r in rows if r["source_id"] not in seen]
                    for rid in gone:
                        self.core.db.execute("UPDATE ext_records SET deleted=1 WHERE id=?", (rid,))
                    cnt["deleted"] = len(gone)
                if last_upd:
                    self.core.db.execute("INSERT OR REPLACE INTO sync_state(conn_id, source_entity, cursor) VALUES (?,?,?)", (cid, src, last_upd))
            except ConnectorError as e:
                errors.append(f"{src}: {e}")
                self._status(cid, e.status, str(e))
            counts[src] = cnt
        status = "failed" if errors and not any(sum(v.values()) for v in counts.values()) else ("partial" if errors else "ok")
        self.core.db.execute("UPDATE sync_runs SET finished_at=?, status=?, counts=?, error=? WHERE id=?",
                             (_now(), status, json.dumps(counts), redact("; ".join(errors))[:1000] or None, run))
        self.core.db.execute("UPDATE integrations SET last_sync=? WHERE id=?", (_now(), cid))
        if status != "failed":
            self._status(cid, "connected", f"Sinxronlandi: {sum(v['new'] for v in counts.values())} yangi, {sum(v['changed'] for v in counts.values())} o'zgargan")
        else:
            self.core.notifier.notify(f"Sinxronlash xatosi: {c['name']}", redact("; ".join(errors))[:300], severity="warning", category="integration")
        self._kg_records(self.get(cid))
        self.core.audit.log("integration", f"Sinxronlash ({mode}): {c['name']} → {status}", target=f"conn#{cid}", risk="A", result=json.dumps(counts)[:200])
        return {"run_id": run, "status": status, "counts": counts, "errors": [redact(e) for e in errors]}

    def sync_history(self, cid: int | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT r.*, i.name FROM sync_runs r JOIN integrations i ON i.id=r.conn_id" + (" WHERE r.conn_id=?" if cid else "") + " ORDER BY r.id DESC LIMIT ?"
        return self.core.db.query(sql, (cid, limit) if cid else (limit,))

    def records(self, cid: int, entity: str = "", limit: int = 200, offset: int = 0) -> list[dict]:
        sql, p = "SELECT * FROM ext_records WHERE conn_id=? AND deleted=0", [cid]
        if entity:
            sql += " AND (entity=? OR source_entity=?)"
            p += [entity, entity]
        rows = self.core.db.query(sql + " ORDER BY id LIMIT ? OFFSET ?", (*p, min(limit, 2000), offset))
        for r in rows:
            r["data"] = json.loads(r["data"])
            r.pop("raw", None)
        return rows

    # ---------------- Yozish (faqat tasdiq bilan) ----------------
    def request_write(self, cid: int, entity: str, operation: str, payload: dict, summary: str = "") -> dict:
        c = self.get(cid)
        if c["mode"] == "read_only":
            raise IntegrationError("Bu ulanish 'Faqat o'qish' rejimida — o'zgartirish taklif qilinmaydi")
        if contains_secret(json.dumps(payload, ensure_ascii=False)):
            raise IntegrationError("Taklifda maxfiy ma'lumot bor")
        pid = self.core.db.execute("INSERT INTO integration_proposals(conn_id, entity, operation, payload) VALUES (?,?,?,?)",
                                   (cid, entity, operation, json.dumps(payload, ensure_ascii=False))).lastrowid
        if c["mode"] == "assistant":
            return {"proposal_id": pid, "status": "draft",
                    "note": "Yordamchi rejim: o'zgartirish faqat taklif sifatida saqlandi. Bajarish uchun 'Ruxsatli avtomatlashtirish' rejimi kerak."}
        financial = any(w in f"{entity} {operation} {json.dumps(payload, ensure_ascii=False)}".lower() for w in FINANCIAL)
        appr = self.core.approvals.request(
            action_type="integration_write", target=f"conn#{cid}", level="E" if financial else "D",
            payload={"proposal": pid, "conn": cid, "entity": entity, "operation": operation, "data": payload}, requested_by="integration",
            account=c["name"], summary=summary or f"{c['name']}: {entity}.{operation} — {json.dumps(payload, ensure_ascii=False)[:120]}"
                                                  + (" (MOLIYAVIY — kuchli tasdiq, faqat dashboardda)" if financial else ""))
        self.core.db.execute("UPDATE integration_proposals SET status='pending_approval', approval_id=? WHERE id=?", (appr["id"], pid))
        return {"proposal_id": pid, "status": "pending_approval", "approval": appr, "financial": financial}

    def execute_write(self, approval_id: int) -> dict:
        appr = self.core.approvals.get(approval_id)
        p = appr["payload"]
        self.core.approvals.authorize_execution(approval_id, p)
        c = self.get(p["conn"])
        if c["mode"] != "authorized":
            raise IntegrationError("Ulanish rejimi o'zgargan — bajarilmaydi")
        try:
            res = self.connector(c).write(p["entity"], p["operation"], p["data"])
        except NotSupported as e:
            self.core.approvals.mark_result(approval_id, "executed")
            self.core.db.execute("UPDATE integration_proposals SET status='not_supported', result=? WHERE id=?", (str(e), p["proposal"]))
            raise IntegrationError(str(e)) from None
        except ConnectorError as e:
            self.core.approvals.mark_result(approval_id, "unknown")
            self.core.db.execute("UPDATE integration_proposals SET status='unknown', result=? WHERE id=?", (redact(str(e)), p["proposal"]))
            raise IntegrationError(f"Natija noma'lum — qayta yuborilmaydi, tizimda tekshiring: {e}") from None
        self.core.approvals.mark_result(approval_id, "executed")
        self.core.db.execute("UPDATE integration_proposals SET status='executed', result=? WHERE id=?", (json.dumps(res, default=str)[:2000], p["proposal"]))
        self.core.audit.log("integration", f"Tashqi tizimga yozildi: {c['name']} {p['entity']}.{p['operation']}", target=f"conn#{c['id']}", risk=appr["level"],
                            approval_status="approved")
        return {"status": "executed", "result": res}

    def proposals(self, cid: int | None = None) -> list[dict]:
        return self.core.db.query("SELECT * FROM integration_proposals" + (" WHERE conn_id=?" if cid else "") + " ORDER BY id DESC LIMIT 200",
                                  (cid,) if cid else ())

    # ---------------- Monitor & jadval ----------------
    def monitor(self, now: float | None = None) -> list[dict]:
        out = []
        for c in self.list():
            if not c["enabled"] or c["status"] == "new":
                continue
            due_check = not c["last_check"] or (datetime.now(timezone.utc) - datetime.strptime(c["last_check"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)).total_seconds() > 900
            if due_check and c["adapter"] not in ("website", "desktop"):     # brauzerli tekshiruv og'ir — faqat sinxronlashda
                try:
                    self.test(c["id"])
                except IntegrationError:
                    pass
            if c["sync_interval_min"] and not getattr(self.core, "automation_paused", False) and int(self.core.settings.autonomy_level) >= 2:
                last = c["last_sync"]
                if not last or (datetime.now(timezone.utc) - datetime.strptime(last, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)).total_seconds() > c["sync_interval_min"] * 60:
                    try:
                        out.append(self.sync(c["id"], trigger="schedule"))
                    except IntegrationError as e:
                        out.append({"conn": c["id"], "error": str(e)})
        return out

    def probe_login(self, url: str) -> dict:
        """Sayt havolasi → kirish sahifasi va kerakli maydonlar (faqat o'qish). Mos andoza (YesPOS/BITO ...) ham taklif qilinadi."""
        from .login_probe import probe
        r = probe(url)
        dom = r["domain"].lower()
        r["preset"] = next((k for k, p in PRESETS.items() if p.get("config", {}).get("base_url") and urlparse(p["config"]["base_url"]).netloc.split(".")[-2:] == dom.split(".")[-2:]), None)
        self.core.audit.log("integration", f"Sayt kirish usuli tekshirildi: {dom} ({len(r['fields'])} maydon)", target=dom, risk="A")
        return r

    def detect(self, **kw) -> dict:
        return detect(**kw)

    def health(self) -> list[dict]:
        return [{"id": c["id"], "name": c["name"], "type": c["system_type"], "adapter": c["adapter"], "status": c["status"], "note": c["status_note"],
                 "store": c["store"], "mode": c["mode"], "last_sync": c["last_sync"], "records": c["records"], "enabled": c["enabled"]} for c in self.list()]

    # ---------------- Knowledge Graph ----------------
    def _kg_conn(self, c):
        self.core.kgraph.node("integration", c["id"], f"{c['name']} ({c['adapter']})", {"type": c["system_type"]}, source=f"integration:{c['id']}")

    def _kg_discovery(self, c):
        kg, src = self.core.kgraph, ("integration", c["id"], f"{c['name']} ({c['adapter']})")
        for e in c["entities"][:300]:
            mp = c["mapping"].get(e["name"], {})
            kg.link(src, "related_to", ("ext_entity", f"{c['id']}:{e['name']}", f"{e['name']}" + (f" → {mp['entity']}" if mp.get("entity") else "")))

    def _kg_records(self, c):
        kg = self.core.kgraph
        ev = getattr(self.core, "events", None)
        if ev:
            ev.muted += 1
        try:
            for r in self.core.db.query("SELECT source_entity, source_id, data FROM ext_records WHERE conn_id=? AND entity='product' AND deleted=0 LIMIT 300", (c["id"],)):
                d = json.loads(r["data"])
                kg.node("business", f"{c['id']}:product:{r['source_id']}", f"{d.get('name') or r['source_id']} · {c.get('store') or c['name']}",
                        source=f"integration:{c['id']}")
                kg.link(("ext_entity", f"{c['id']}:{r['source_entity']}", None), "related_to", ("business", f"{c['id']}:product:{r['source_id']}", None))
        finally:
            if ev:
                ev.muted -= 1
