"""POS Connector: hujjat loyihasi → aniq versiya tasdig'i → kiritish → qayta tekshirish → audit.

Loyiha tayyorlash (B) va tashqi POSga kiritish (D) — ikki alohida bosqich. Tasdiq hujjatning aniq
versiyasiga (sayt, akkaunt, tur, kontragent, mahsulotlar, miqdor, narx, summa) bog'lanadi.
Kiritishdan oldin konnektor shu idempotency kalitli hujjat POSda bormi — tekshiradi; natija
noma'lum bo'lsa, avtomatik qayta yuborilmaydi.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .approval import ApprovalEngine
from .audit import Audit
from .config import jarvis_home
from .db import Database

POS_SCHEMA = """
CREATE TABLE IF NOT EXISTS pos_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc_type TEXT NOT NULL, party TEXT NOT NULL, account TEXT,
    items TEXT NOT NULL, total REAL NOT NULL, note TEXT, version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft',  -- draft | pending_approval | approved | submitted | verified | unknown | failed | rejected
    approval_id INTEGER, external_id TEXT, last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""
DOC_TYPES = {"kirim", "chiqim", "sotuv", "qaytarish", "tolov"}


class POSError(Exception):
    pass


class UnknownOutcome(Exception):
    """Konnektor so'rov yuborildimi yoki yo'qmi bilmaydi (masalan, timeout)."""


class FileExportConnector:
    """Haqiqiy, xavfsiz konnektor: tasdiqlangan hujjatni POSga qo'lda import qilish uchun
    data/pos_outbox/ ga JSON + CSV qilib yozadi. Tashqi saytga hech narsa yubormaydi."""
    name = "file_export"

    def __init__(self, outbox: Path | None = None):
        self.outbox = outbox or jarvis_home() / "pos_outbox"
        self.outbox.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict:
        return {"connector": self.name, "connected": True, "note": f"Fayl eksporti: {self.outbox}"}

    def find_existing(self, key: str) -> str | None:
        p = self.outbox / f"{key}.json"
        return str(p) if p.exists() else None

    def create(self, key: str, doc: dict) -> str:
        p = self.outbox / f"{key}.json"
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = ["sku,nomi,miqdor,narx,summa"] + [
            f"{i['sku']},{i.get('name', '')},{i['qty']},{i['price']},{round(i['qty'] * i['price'], 2)}" for i in doc["items"]]
        p.with_suffix(".csv").write_text("\n".join(lines), encoding="utf-8")
        return str(p)

    def verify(self, key: str, doc: dict) -> bool:
        p = self.outbox / f"{key}.json"
        return p.exists() and json.loads(p.read_text(encoding="utf-8")) == doc


class RestApiConnector:
    """Umumiy REST konnektor — POS rasmiy API bersa. Sozlama (maxfiy emas) `pos_api`:
      {"base_url": "https://pos.example.uz/api", "create_path": "/documents",
       "find_path": "/documents?external_key={key}", "auth_header": "Authorization", "auth_scheme": "Bearer"}
    Token: `python scripts/set_secret.py pos_api_token` (cheklangan huquqli token tavsiya etiladi).
    * Har so'rovda `Idempotency-Key` sarlavhasi va `external_key` maydoni — takroriy kiritishdan himoya.
    * Tarmoq xatosi/timeout → UnknownOutcome (qayta yuborilmaydi, find_path bilan tekshiriladi).
    * Faqat o'qish rejimida yozish bloklanadi (POSManager.submit)."""
    name = "api"

    def __init__(self, settings):
        self.cfg = dict(getattr(settings, "pos_api", {}) or {})

    def _url(self, key: str, path_key: str, k: str = "") -> str:
        base = self.cfg.get("base_url", "").rstrip("/")
        if not base.startswith("https://"):
            raise POSError("pos_api.base_url https:// bilan boshlanishi kerak")
        return base + self.cfg.get(path_key, "").replace("{key}", k)

    def _headers(self, extra: dict | None = None) -> dict:
        from .secrets import get_secret
        tok = get_secret("pos_api_token")
        if not tok:
            raise POSError("POS API tokeni yo'q: python scripts/set_secret.py pos_api_token")
        return {self.cfg.get("auth_header", "Authorization"): f"{self.cfg.get('auth_scheme', 'Bearer')} {tok}".strip()} | (extra or {})

    def status(self) -> dict:
        from .secrets import has_secret
        ok = bool(self.cfg.get("base_url")) and has_secret("pos_api_token")
        return {"connector": self.name, "connected": ok,
                "note": "REST API: " + (self.cfg.get("base_url") or "base_url sozlanmagan") + ("" if has_secret("pos_api_token") else " · token yo'q")}

    def find_existing(self, key: str) -> str | None:
        from . import net
        try:
            r = net.get_json(self._url("", "find_path", key), headers=self._headers(), timeout=20)
        except net.NetError as e:
            raise POSError(f"POS API (qidiruv) xatosi: {e}") from None
        items = r.get("data", r.get("items", r if isinstance(r, list) else []))
        if isinstance(items, list) and items:
            first = items[0]
            return str(first.get("id", first)) if isinstance(first, dict) else str(first)
        return None

    def create(self, key: str, doc: dict) -> str:
        from . import net
        try:
            r = net.post_json(self._url(key, "create_path"), json_body=doc | {"external_key": key},
                              headers=self._headers({"Idempotency-Key": key}), timeout=30)
        except net.NetError as e:
            if e.status is None:           # javob kelmadi — natija noma'lum
                raise UnknownOutcome(str(e)) from None
            raise POSError(f"POS API rad etdi: HTTP {e.status} {e.body[:200]}") from None
        return str(r.get("id") or r.get("document_id") or key)

    def verify(self, key: str, doc: dict) -> bool:
        return self.find_existing(key) is not None


class NotConfiguredConnector:
    """API yoki brauzer konnektori — POS manzili va ruxsat berilgach yoziladi."""

    def __init__(self, name: str):
        self.name = name

    def status(self) -> dict:
        return {"connector": self.name, "connected": False,
                "note": "Hali sozlanmagan: POS manzili, rasmiy API yoki brauzer sessiyasi kerak."}

    def _fail(self, *a, **k):
        raise POSError(f"'{self.name}' konnektori hali sozlanmagan. Hozircha 'file_export' ishlating.")

    find_existing = create = verify = _fail


def make_connector(settings):
    if settings.pos_connector == "file_export":
        return FileExportConnector()
    if settings.pos_connector == "api":
        return RestApiConnector(settings)
    return NotConfiguredConnector(settings.pos_connector)


def doc_payload(doc: dict, site: str) -> dict:
    """Tasdiq xeshi hisoblanadigan kanonik ko'rinish."""
    return {"site": site, "account": doc["account"] or "", "doc_type": doc["doc_type"], "party": doc["party"],
            "version": doc["version"], "items": doc["items"], "total": doc["total"], "note": doc["note"] or ""}


class POSManager:
    def __init__(self, db: Database, audit: Audit, approvals: ApprovalEngine, settings, connector=None):
        self.db, self.audit, self.approvals, self.settings = db, audit, approvals, settings
        db.conn.executescript(POS_SCHEMA)
        self.connector = connector or make_connector(settings)

    @property
    def site(self) -> str:
        return self.settings.pos_site or "file_export (lokal)"

    @staticmethod
    def _validate(doc_type: str, party: str, items: list[dict]) -> tuple[list[dict], float]:
        if doc_type not in DOC_TYPES:
            raise POSError(f"Hujjat turi: {sorted(DOC_TYPES)}")
        if not party.strip():
            raise POSError("Yetkazib beruvchi/qabul qiluvchi ko'rsatilmagan")
        if not items:
            raise POSError("Hujjatda mahsulot yo'q")
        clean, skus = [], set()
        for i, it in enumerate(items, 1):
            try:
                qty, price = float(it["qty"]), float(it["price"])
            except (KeyError, TypeError, ValueError) as e:
                raise POSError(f"{i}-qator: miqdor va narx raqam bo'lishi kerak") from e
            sku = str(it.get("sku", "")).strip()
            if not sku:
                raise POSError(f"{i}-qator: mahsulot kodi yo'q")
            if qty <= 0 or price < 0:
                raise POSError(f"{i}-qator: miqdor > 0 va narx ≥ 0 bo'lishi kerak")
            if sku in skus:
                raise POSError(f"{i}-qator: '{sku}' takrorlangan — bitta qatorga birlashtiring")
            skus.add(sku)
            clean.append({"sku": sku, "name": str(it.get("name", "")), "qty": qty, "price": price})
        return clean, round(sum(i["qty"] * i["price"] for i in clean), 2)

    def get(self, doc_id: int) -> dict:
        d = self.db.one("SELECT * FROM pos_documents WHERE id=?", (doc_id,))
        if not d:
            raise POSError("Hujjat topilmadi")
        d["items"] = json.loads(d["items"])
        return d

    def list(self) -> list[dict]:
        return [self.get(r["id"]) for r in self.db.query("SELECT id FROM pos_documents ORDER BY id DESC LIMIT 200")]

    def create_draft(self, doc_type: str, party: str, items: list[dict], note: str = "", account: str = "") -> dict:
        clean, total = self._validate(doc_type, party, items)
        cur = self.db.execute("INSERT INTO pos_documents(doc_type, party, account, items, total, note) VALUES (?,?,?,?,?,?)",
                              (doc_type, party.strip(), account, json.dumps(clean, ensure_ascii=False), total, note))
        self.audit.log("pos_agent", f"Hujjat loyihasi: {doc_type}, {party}, {total}", target=f"pos_doc#{cur.lastrowid}", risk="B")
        return self.get(cur.lastrowid)

    def update_draft(self, doc_id: int, items: list[dict], party: str | None = None, note: str | None = None) -> dict:
        d = self.get(doc_id)
        if d["status"] in ("submitted", "verified", "unknown"):
            raise POSError(f"Holati '{d['status']}' — o'zgartirib bo'lmaydi. Yangi hujjat yarating.")
        clean, total = self._validate(d["doc_type"], party or d["party"], items)
        if d["approval_id"]:
            appr = self.approvals.get(d["approval_id"])
            if appr["status"] in ("pending", "approved"):
                self.db.execute("UPDATE approvals SET status='invalidated' WHERE id=?", (d["approval_id"],))
                self.audit.log("pos_agent", f"Hujjat o'zgardi — tasdiq #{d['approval_id']} bekor qilindi",
                               target=f"pos_doc#{doc_id}", risk="D", approval_status="invalidated")
        self.db.execute("UPDATE pos_documents SET items=?, total=?, party=?, note=?, version=version+1, status='draft',"
                        " approval_id=NULL, updated_at=datetime('now') WHERE id=?",
                        (json.dumps(clean, ensure_ascii=False), total, (party or d["party"]).strip(),
                         d["note"] if note is None else note, doc_id))
        return self.get(doc_id)

    def idempotency_key(self, d: dict) -> str:
        return f"pos-{d['id']}-v{d['version']}"

    def request_approval(self, doc_id: int) -> dict:
        d = self.get(doc_id)
        if d["status"] != "draft":
            raise POSError(f"Faqat loyiha holatidagi hujjat tasdiqqa yuboriladi (hozir: {d['status']})")
        payload = doc_payload(d, self.site)
        lines = "; ".join(f"{i['sku']} {i['qty']}×{i['price']}" for i in d["items"])
        appr = self.approvals.request(
            action_type=f"pos_{d['doc_type']}", target=self.site, account=d["account"] or None, level="D",
            payload=payload, requested_by="pos_agent", idempotency_key=self.idempotency_key(d),
            summary=f"POSga {d['doc_type']} kiritish: {d['party']}, v{d['version']}, jami {d['total']} ({lines})")
        self.db.execute("UPDATE pos_documents SET status='pending_approval', approval_id=? WHERE id=?", (appr["id"], doc_id))
        return {"document": self.get(doc_id), "approval": appr}

    def submit(self, doc_id: int) -> dict:
        d = self.get(doc_id)
        if d["status"] == "unknown":
            raise POSError("Oldingi kiritish natijasi noma'lum. Avval 'Tekshirish' tugmasi bilan POSdagi holatni aniqlang.")
        if not d["approval_id"]:
            raise POSError("Tasdiq so'ralmagan")
        if self.settings.read_only_mode and self.connector.name != "file_export":
            raise POSError("Faqat o'qish rejimi: tashqi POSga yozish bloklangan. Hozircha file_export ishlating.")
        payload = doc_payload(d, self.site)
        self.approvals.authorize_execution(d["approval_id"], payload)   # versiya/xesh tekshiruvi
        key = self.idempotency_key(d)
        existing = self.connector.find_existing(key)
        if existing:   # takroriy kiritishdan himoya
            self._finish(d, "verified", existing, "Hujjat POSda allaqachon bor — qayta yuborilmadi")
            return self.get(doc_id)
        try:
            ext = self.connector.create(key, payload)
        except UnknownOutcome as e:
            self.approvals.mark_result(d["approval_id"], "unknown")
            self.db.execute("UPDATE pos_documents SET status='unknown', last_error=? WHERE id=?", (str(e), doc_id))
            self.audit.log("pos_agent", f"Kiritish natijasi noma'lum: pos_doc#{doc_id}", target=self.site, risk="D",
                           approval_status="approved", error_code="UNKNOWN", error_note=str(e))
            return self.get(doc_id)
        except Exception as e:
            self.db.execute("UPDATE pos_documents SET status='failed', last_error=? WHERE id=?", (str(e), doc_id))
            self.audit.log("pos_agent", f"Kiritish xatosi: pos_doc#{doc_id}", target=self.site, risk="D",
                           approval_status="approved", error_code=type(e).__name__, error_note=str(e))
            raise
        self.approvals.mark_result(d["approval_id"], "executed")
        verified = self.connector.verify(key, payload)
        self._finish(d, "verified" if verified else "submitted", ext,
                     "Kiritildi va tekshirildi" if verified else "Kiritildi, lekin tekshiruv tasdiqlamadi")
        return self.get(doc_id)

    def check_unknown(self, doc_id: int) -> dict:
        """Noma'lum holat: POSda bormi — tekshiradi. Bor bo'lsa 'verified', yo'q bo'lsa qayta tasdiq kerak."""
        d = self.get(doc_id)
        if d["status"] != "unknown":
            raise POSError("Hujjat 'unknown' holatida emas")
        existing = self.connector.find_existing(self.idempotency_key(d))
        if existing:
            self.approvals.mark_result(d["approval_id"], "executed")
            self._finish(d, "verified", existing, "Tekshiruv: hujjat POSda topildi")
        else:
            self.db.execute("UPDATE approvals SET status='invalidated' WHERE id=?", (d["approval_id"],))
            self.db.execute("UPDATE pos_documents SET status='draft', approval_id=NULL WHERE id=?", (doc_id,))
            self.audit.log("pos_agent", f"Tekshiruv: hujjat POSda yo'q, qayta tasdiq kerak (pos_doc#{doc_id})",
                           target=self.site, risk="D", approval_status="invalidated")
        return self.get(doc_id)

    def _finish(self, d, status, ext, note):
        self.db.execute("UPDATE pos_documents SET status=?, external_id=?, updated_at=? WHERE id=?",
                        (status, ext, datetime.now(timezone.utc).isoformat(), d["id"]))
        self.audit.log("pos_agent", f"{note}: pos_doc#{d['id']} v{d['version']}", target=self.site, risk="D",
                       approval_status="approved", result=status, verified="yes" if status == "verified" else "no")

    def status(self) -> dict:
        return {"site": self.settings.pos_site or None, **self.connector.status()}
