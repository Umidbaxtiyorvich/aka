"""Business Intelligence: POS eksport fayllarini (CSV/Excel) import qilish va tahlil.

Asl fayl faqat o'qiladi, hech qachon o'zgartirilmaydi. Har bir import fayl SHA-256 xeshi bilan qayd
etiladi — bir xil faylni ikki marta import qilish bloklanadi. Hech qanday raqam to'qib chiqarilmaydi:
ma'lumot bo'lmasa, natija bo'sh qaytadi.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import statistics
from collections import defaultdict
from pathlib import Path

from .audit import Audit
from .db import Database
from .files import FileAccessError

BI_SCHEMA = """
CREATE TABLE IF NOT EXISTS bi_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, file_name TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL, rows_ok INTEGER NOT NULL, rows_bad INTEGER NOT NULL, issues TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS bi_products (
    sku TEXT PRIMARY KEY, name TEXT, barcode TEXT, unit TEXT, cost REAL, price REAL,
    stock_reported REAL, min_stock REAL, import_id INTEGER
);
CREATE TABLE IF NOT EXISTS bi_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT, import_id INTEGER, doc_no TEXT, doc_type TEXT NOT NULL,
    date TEXT, party TEXT, sku TEXT NOT NULL, qty REAL NOT NULL, price REAL, total REAL
);
CREATE TABLE IF NOT EXISTS bi_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, import_id INTEGER, doc_no TEXT, date TEXT, party TEXT,
    amount REAL NOT NULL, direction TEXT NOT NULL
);
"""

# Ustun nomlari sinonimlari (o'zbek, rus, ingliz)
SYNONYMS = {
    "sku": ["sku", "kod", "code", "artikul", "артикул", "код", "mahsulot kodi", "product_code"],
    "name": ["name", "nom", "nomi", "mahsulot", "товар", "наименование", "product"],
    "barcode": ["barcode", "shtrix", "shtrix-kod", "shtrixkod", "штрихкод", "штрих-код", "ean"],
    "unit": ["unit", "birlik", "o'lchov", "olchov", "ед", "единица", "ед.изм"],
    "cost": ["cost", "tannarx", "xarid narxi", "kirim narxi", "sotib olish narxi", "закупка", "себестоимость", "purchase_price"],
    "price": ["price", "narx", "sotish narxi", "цена", "цена продажи", "sale_price"],
    "stock": ["stock", "qoldiq", "ostatok", "остаток", "balance"],
    "min_stock": ["min_stock", "minimal", "min qoldiq", "минимум"],
    "doc_no": ["doc_no", "hujjat", "hujjat raqami", "chek", "chek raqami", "номер", "документ", "receipt"],
    "doc_type": ["doc_type", "turi", "hujjat turi", "тип", "operation", "amal"],
    "date": ["date", "sana", "дата", "vaqt"],
    "party": ["party", "kontragent", "yetkazib beruvchi", "qabul qiluvchi", "mijoz", "контрагент", "поставщик", "клиент", "supplier", "customer"],
    "qty": ["qty", "miqdor", "soni", "количество", "кол-во", "quantity"],
    "total": ["total", "summa", "jami", "сумма", "итого", "amount"],
    "direction": ["direction", "yo'nalish", "направление"],
}
DOC_TYPES = {
    "kirim": ["kirim", "приход", "in", "purchase", "xarid"],
    "chiqim": ["chiqim", "расход", "out", "spisanie", "списание", "hisobdan chiqarish"],
    "sotuv": ["sotuv", "savdo", "продажа", "sale", "chek"],
    "qaytarish": ["qaytarish", "возврат", "return"],
}


class BIError(Exception):
    pass


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", str(h or "").strip().lower().replace("‘", "'").replace("ʻ", "'"))


def map_columns(headers: list[str]) -> dict[str, int]:
    out = {}
    for idx, h in enumerate(headers):
        n = _norm(h)
        for key, syns in SYNONYMS.items():
            if key not in out and n in syns:
                out[key] = idx
    return out


def _num(v) -> float | None:
    if v is None or str(v).strip() == "":
        return None
    s = str(v).replace(" ", "").replace(" ", "")
    if s.count(",") == 1 and "." not in s:
        s = s.replace(",", ".")
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _doc_type(v: str) -> str | None:
    n = _norm(v)
    for t, syns in DOC_TYPES.items():
        if n in syns:
            return t
    return None


def read_table(path: Path) -> list[list[str]]:
    ext = path.suffix.lower()
    if ext == ".csv":
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "cp1251"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise BIError("CSV kodlashi aniqlanmadi (UTF-8 yoki Windows-1251 kutiladi)")
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t") if text.strip() else csv.excel
        return [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if ext == ".xlsx":
        try:
            import openpyxl
        except ImportError as e:
            raise BIError("Excel uchun 'openpyxl' o'rnatilmagan") from e
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
        return [["" if c is None else str(c) for c in row] for row in ws.iter_rows(values_only=True)
                if any(c not in (None, "") for c in row)]
    raise BIError(f"Qo'llab-quvvatlanmaydigan format: {ext} (CSV yoki XLSX)")


class BusinessIntelligence:
    def __init__(self, db: Database, audit: Audit, settings, files):
        self.db, self.audit, self.settings, self.files = db, audit, settings, files
        db.conn.executescript(BI_SCHEMA)

    # ---------- import ----------
    def import_file(self, path: str, kind: str) -> dict:
        """kind: products | movements | payments"""
        if kind not in ("products", "movements", "payments"):
            raise BIError("kind: products, movements yoki payments")
        p = self.files._check_read(path)
        if not p.is_file():
            raise FileAccessError("Fayl topilmadi")
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        dup = self.db.one("SELECT id, created_at FROM bi_imports WHERE sha256=?", (digest,))
        if dup:
            raise BIError(f"Bu fayl allaqachon import qilingan (#{dup['id']}, {dup['created_at']}).")
        rows = read_table(p)
        if len(rows) < 2:
            raise BIError("Faylda sarlavha va kamida bitta qator bo'lishi kerak")
        cols = map_columns(rows[0])
        need = {"products": ["sku"], "movements": ["sku", "qty", "doc_type"]}.get(kind, [])
        if kind == "payments":
            if "total" not in cols or "party" not in cols:
                raise BIError(f"To'lovlar uchun 'summa' va 'kontragent' ustunlari kerak. Topilgan: {list(cols)}")
        else:
            missing = [c for c in need if c not in cols]
            if missing:
                raise BIError(f"Majburiy ustun topilmadi: {missing}. Topilgan: {list(cols)}. Sarlavhalar: {rows[0]}")

        cur = self.db.execute("INSERT INTO bi_imports(file_name, sha256, kind, rows_ok, rows_bad) VALUES (?,?,?,0,0)",
                              (p.name, digest, kind))
        imp_id = cur.lastrowid
        ok, issues = 0, []
        get = lambda r, k: (r[cols[k]].strip() if k in cols and cols[k] < len(r) else "")  # noqa: E731
        for i, r in enumerate(rows[1:], start=2):
            try:
                if kind == "products":
                    self._import_product(r, get, imp_id)
                elif kind == "movements":
                    self._import_movement(r, get, imp_id)
                else:
                    self._import_payment(r, get, imp_id)
                ok += 1
            except BIError as e:
                issues.append(f"{i}-qator: {e}")
        self.db.execute("UPDATE bi_imports SET rows_ok=?, rows_bad=?, issues=? WHERE id=?",
                        (ok, len(issues), "\n".join(issues[:200]), imp_id))
        self.audit.log("bi_agent", f"Import: {p.name} ({kind})", target=f"bi_import#{imp_id}", risk="B",
                       result=f"ok={ok}, xato={len(issues)}")
        return {"import_id": imp_id, "file": p.name, "kind": kind, "rows_ok": ok, "rows_bad": len(issues),
                "issues": issues[:50], "columns": cols}

    def _import_product(self, r, get, imp_id):
        sku = get(r, "sku")
        if not sku:
            raise BIError("mahsulot kodi bo'sh")
        vals = {k: _num(get(r, k)) for k in ("cost", "price", "stock", "min_stock")}
        for k, v in vals.items():
            if get(r, k) and v is None:
                raise BIError(f"'{k}' raqam emas: {get(r, k)!r}")
        self.db.execute(
            "INSERT INTO bi_products(sku, name, barcode, unit, cost, price, stock_reported, min_stock, import_id)"
            " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(sku) DO UPDATE SET name=excluded.name, barcode=excluded.barcode,"
            " unit=excluded.unit, cost=excluded.cost, price=excluded.price, stock_reported=excluded.stock_reported,"
            " min_stock=excluded.min_stock, import_id=excluded.import_id",
            (sku, get(r, "name"), get(r, "barcode"), get(r, "unit"), vals["cost"], vals["price"], vals["stock"],
             vals["min_stock"], imp_id))

    def _import_movement(self, r, get, imp_id):
        dt = _doc_type(get(r, "doc_type"))
        if not dt:
            raise BIError(f"noma'lum hujjat turi: {get(r, 'doc_type')!r}")
        qty = _num(get(r, "qty"))
        if qty is None:
            raise BIError("miqdor raqam emas")
        if qty <= 0:
            raise BIError(f"miqdor musbat bo'lishi kerak: {qty}")
        price, total = _num(get(r, "price")), _num(get(r, "total"))
        if total is None and price is not None:
            total = round(price * qty, 2)
        self.db.execute("INSERT INTO bi_movements(import_id, doc_no, doc_type, date, party, sku, qty, price, total)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (imp_id, get(r, "doc_no"), dt, get(r, "date"), get(r, "party"), get(r, "sku"), qty, price, total))

    def _import_payment(self, r, get, imp_id):
        amount = _num(get(r, "total"))
        if amount is None:
            raise BIError("summa raqam emas")
        d = _norm(get(r, "direction"))
        direction = "out" if d in ("out", "chiqim", "to'landi", "berildi", "расход") else "in"
        self.db.execute("INSERT INTO bi_payments(import_id, doc_no, date, party, amount, direction) VALUES (?,?,?,?,?,?)",
                        (imp_id, get(r, "doc_no"), get(r, "date"), get(r, "party"), amount, direction))

    def imports(self) -> list[dict]:
        return self.db.query("SELECT * FROM bi_imports ORDER BY id DESC")

    # ---------- tahlil ----------
    def stock(self) -> list[dict]:
        products = {p["sku"]: p for p in self.db.query("SELECT * FROM bi_products")}
        moves = defaultdict(lambda: defaultdict(float))
        for m in self.db.query("SELECT sku, doc_type, SUM(qty) q FROM bi_movements GROUP BY sku, doc_type"):
            moves[m["sku"]][m["doc_type"]] = m["q"]
        out = []
        for sku in sorted(set(products) | set(moves)):
            p, mv = products.get(sku, {}), moves.get(sku, {})
            has_moves = bool(mv)
            computed = mv.get("kirim", 0) + mv.get("qaytarish", 0) - mv.get("chiqim", 0) - mv.get("sotuv", 0)
            reported = p.get("stock_reported")
            out.append({"sku": sku, "name": p.get("name") or "", "unit": p.get("unit") or "",
                        "kirim": mv.get("kirim", 0), "chiqim": mv.get("chiqim", 0), "sotuv": mv.get("sotuv", 0),
                        "qaytarish": mv.get("qaytarish", 0),
                        "computed_from_movements": computed if has_moves else None, "reported_stock": reported,
                        "difference": round(reported - computed, 3) if has_moves and reported is not None else None,
                        "min_stock": p.get("min_stock"), "in_catalog": sku in products})
        return out

    def current_stock(self, row: dict) -> float | None:
        return row["reported_stock"] if row["reported_stock"] is not None else row["computed_from_movements"]

    def low_stock(self) -> list[dict]:
        out = []
        for r in self.stock():
            cur = self.current_stock(r)
            limit = r["min_stock"] if r["min_stock"] is not None else self.settings.low_stock_threshold
            if cur is not None and cur <= limit:
                out.append(r | {"current": cur, "limit": limit})
        return out

    def price_issues(self) -> list[dict]:
        issues = []
        for p in self.db.query("SELECT * FROM bi_products"):
            if p["price"] is not None and p["price"] <= 0:
                issues.append({"sku": p["sku"], "issue": "Sotish narxi 0 yoki manfiy", "value": p["price"]})
            elif p["cost"] is not None and p["price"] is not None and p["price"] < p["cost"]:
                issues.append({"sku": p["sku"], "issue": "Sotish narxi xarid narxidan past",
                               "value": f"{p['price']} < {p['cost']}"})
        by_sku = defaultdict(list)
        for m in self.db.query("SELECT * FROM bi_movements WHERE price IS NOT NULL AND doc_type='sotuv'"):
            by_sku[m["sku"]].append(m)
        for sku, ms in by_sku.items():
            if len(ms) < 3:
                continue
            med = statistics.median(m["price"] for m in ms)
            for m in ms:
                if med and abs(m["price"] - med) / med > 0.5:
                    issues.append({"sku": sku, "issue": "Narx odatdagidan 50%+ farq qiladi",
                                   "value": f"{m['price']} (median {med}), hujjat {m['doc_no']}"})
        for m in self.db.query("SELECT * FROM bi_movements WHERE price IS NOT NULL AND total IS NOT NULL"):
            if abs(m["price"] * m["qty"] - m["total"]) > max(1.0, 0.001 * abs(m["total"])):
                issues.append({"sku": m["sku"], "issue": "Narx × miqdor ≠ summa",
                               "value": f"{m['price']}×{m['qty']}≠{m['total']} (hujjat {m['doc_no']})"})
        return issues

    def duplicate_documents(self) -> list[dict]:
        dups = self.db.query(
            "SELECT doc_no, doc_type, COUNT(DISTINCT import_id) imports, COUNT(*) lines FROM bi_movements"
            " WHERE doc_no<>'' GROUP BY doc_no, doc_type HAVING COUNT(DISTINCT import_id) > 1")
        same = self.db.query(
            "SELECT date, party, doc_type, sku, qty, total, COUNT(*) n FROM bi_movements"
            " GROUP BY date, party, doc_type, sku, qty, total HAVING COUNT(*) > 1")
        return [{"type": "Bir xil hujjat raqami bir necha importda", **d} for d in dups] + \
               [{"type": "Bir xil qatorlar (sana, kontragent, mahsulot, miqdor, summa)", **d} for d in same]

    def profit(self) -> dict:
        products = {p["sku"]: p for p in self.db.query("SELECT * FROM bi_products")}
        revenue = cost = 0.0
        unknown_cost, per = [], []
        for m in self.db.query("SELECT sku, SUM(qty) q, SUM(total) t FROM bi_movements WHERE doc_type='sotuv' GROUP BY sku"):
            c = products.get(m["sku"], {}).get("cost")
            rev = m["t"] or 0.0
            revenue += rev
            if c is None:
                unknown_cost.append(m["sku"])
                per.append({"sku": m["sku"], "qty": m["q"], "revenue": rev, "cost": None, "profit": None})
                continue
            cost += c * m["q"]
            per.append({"sku": m["sku"], "qty": m["q"], "revenue": rev, "cost": round(c * m["q"], 2),
                        "profit": round(rev - c * m["q"], 2)})
        return {"revenue": round(revenue, 2), "cost_of_goods": round(cost, 2),
                "gross_profit": round(revenue - cost, 2) if not unknown_cost else None,
                "gross_profit_known_only": round(sum(p["profit"] for p in per if p["profit"] is not None), 2),
                "skus_without_cost": unknown_cost, "by_product": sorted(per, key=lambda x: -(x["revenue"] or 0))}

    def sales_by_day(self) -> list[dict]:
        return self.db.query("SELECT date, COUNT(DISTINCT doc_no) checks, SUM(qty) qty, SUM(total) total"
                             " FROM bi_movements WHERE doc_type='sotuv' GROUP BY date ORDER BY date")

    def debts(self) -> list[dict]:
        """Kontragent bo'yicha: kirim summasi − bizning to'lovlar (yetkazib beruvchiga qarz);
        sotuv summasi − ularning to'lovlari (mijoz qarzi). Faqat import qilingan ma'lumotga asoslanadi."""
        acc = defaultdict(lambda: {"purchases": 0.0, "sales": 0.0, "paid_out": 0.0, "paid_in": 0.0})
        for m in self.db.query("SELECT party, doc_type, SUM(total) t FROM bi_movements WHERE party<>'' GROUP BY party, doc_type"):
            if m["doc_type"] == "kirim":
                acc[m["party"]]["purchases"] += m["t"] or 0
            elif m["doc_type"] == "sotuv":
                acc[m["party"]]["sales"] += m["t"] or 0
        for p in self.db.query("SELECT party, direction, SUM(amount) a FROM bi_payments GROUP BY party, direction"):
            acc[p["party"]]["paid_out" if p["direction"] == "out" else "paid_in"] += p["a"]
        out = []
        for party, a in sorted(acc.items()):
            out.append({"party": party, **{k: round(v, 2) for k, v in a.items()},
                        "we_owe": round(a["purchases"] - a["paid_out"], 2),
                        "they_owe": round(a["sales"] - a["paid_in"], 2)})
        return out

    def discrepancies(self) -> list[dict]:
        return [r for r in self.stock() if r["difference"] not in (None, 0)] + \
               [r | {"note": "Harakat bor, lekin katalogda yo'q"} for r in self.stock() if not r["in_catalog"]]

    def report(self) -> dict:
        has_data = bool(self.db.one("SELECT 1 x FROM bi_imports"))
        return {"has_data": has_data, "imports": self.imports()[:10], "profit": self.profit(),
                "low_stock": self.low_stock(), "price_issues": self.price_issues(),
                "duplicates": self.duplicate_documents(), "discrepancies": self.discrepancies(),
                "debts": self.debts(), "sales_by_day": self.sales_by_day()}
