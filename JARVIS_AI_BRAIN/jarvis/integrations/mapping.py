"""Schema Mapping — tashqi maydonlarni JARVIS yagona ma'lumot modeliga moslash (uz / ru / en sinonimlar).

Noma'lum maydonlar taxmin bilan to'ldirilmaydi: ular `unmapped` ro'yxatida qoladi va foydalanuvchi tekshiradi.
Har bir moslik ishonch darajasi bilan; tahlilda faqat foydalanuvchi tasdiqlagan yoki ishonchi yuqori xaritalar ishlatiladi.
"""
from __future__ import annotations

import re

MODEL = {
    "product": {"sku": ["sku", "code", "kod", "artikul", "артикул", "код", "product_id", "item_id", "id"],
                "barcode": ["barcode", "shtrix", "shtrixkod", "штрихкод", "ean", "upc"],
                "name": ["name", "nomi", "mahsulot", "tovar", "наименование", "название", "товар", "номенклатура", "title", "description"],
                "category": ["category", "kategoriya", "turkum", "группа", "категория"],
                "cost_price": ["cost", "cost_price", "purchase_price", "tannarx", "kirim narxi", "sotib olish narxi", "закупочная", "себестоимость", "закуп"],
                "sale_price": ["price", "sale_price", "narx", "narxi", "sotish narxi", "цена", "цена продажи", "розничная"],
                "stock": ["stock", "qty", "quantity", "qoldiq", "soni", "miqdor", "остаток", "количество", "balance", "on_hand"],
                "unit": ["unit", "birlik", "ед", "единица"], "warehouse": ["warehouse", "ombor", "склад", "store_id"]},
    "sale": {"date": ["date", "sana", "vaqt", "created_at", "sold_at", "дата", "время", "datetime", "time"],
             "receipt_no": ["receipt", "check", "chek", "чек", "номер чека", "receipt_id", "order_id", "doc_no"],
             "sku": ["sku", "code", "kod", "артикул", "код", "product_id", "item_id"],
             "product_name": ["product", "mahsulot", "tovar", "товар", "наименование", "item", "name"],
             "qty": ["qty", "quantity", "soni", "miqdor", "количество", "count"],
             "price": ["price", "narx", "цена", "unit_price"], "amount": ["amount", "sum", "summa", "total", "jami", "сумма", "итого", "revenue"],
             "cashier": ["cashier", "kassir", "кассир", "user", "seller", "sotuvchi"], "register": ["register", "kassa", "касса", "pos_id", "terminal"],
             "payment_type": ["payment", "to'lov", "tolov", "оплата", "payment_type", "method"], "store": ["store", "do'kon", "dokon", "магазин", "branch", "filial"]},
    "customer": {"id": ["id", "customer_id", "client_id"], "name": ["name", "mijoz", "xaridor", "клиент", "покупатель", "fio", "фио"],
                 "phone": ["phone", "telefon", "телефон", "tel"], "debt": ["debt", "qarz", "долг", "balance", "задолженность"]},
    "supplier": {"id": ["id", "supplier_id", "vendor_id"], "name": ["name", "yetkazib beruvchi", "поставщик", "vendor", "supplier"],
                 "phone": ["phone", "telefon", "телефон"], "debt": ["debt", "qarz", "долг", "задолженность"]},
    "payment": {"date": ["date", "sana", "дата"], "amount": ["amount", "summa", "sum", "сумма"], "method": ["method", "type", "turi", "вид оплаты"],
                "party": ["customer", "supplier", "mijoz", "контрагент"], "doc_no": ["doc", "number", "raqam", "номер"]},
    "movement": {"date": ["date", "sana", "дата"], "sku": ["sku", "code", "kod", "код"], "qty": ["qty", "quantity", "soni", "количество"],
                 "type": ["type", "turi", "вид", "operation"], "doc_no": ["doc", "number", "nakladnoy", "накладная"], "supplier": ["supplier", "поставщик"]},
    "expense": {"date": ["date", "sana", "дата"], "amount": ["amount", "summa", "сумма"], "category": ["category", "turi", "статья", "category"]},
}
ENTITY_HINTS = {"product": r"product|mahsulot|tovar|item|номенклатур|товар|catalog|goods|stock|qoldiq|остат",
                "sale": r"sale|sotuv|savdo|receipt|check|chek|order|чек|продаж|реализац",
                "customer": r"customer|client|mijoz|xaridor|клиент|покупател|контрагент",
                "supplier": r"supplier|vendor|yetkaz|поставщ", "payment": r"payment|to'lov|tolov|оплат|касса|cash",
                "movement": r"movement|kirim|chiqim|приход|расход|поступлен|перемещ|income|arrival", "expense": r"expense|xarajat|расход|затрат"}


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-.]+", " ", str(s).lower()).strip()


def guess_entity(name: str, fields: list[str]) -> tuple[str | None, float]:
    n = _norm(name)
    for ent, rx in ENTITY_HINTS.items():
        if re.search(rx, n):
            return ent, 0.8
    # Eng ko'p maydoni mos kelgan obyekt (kichik obyektlar — masalan expense — nisbat hisobiga ustun chiqmasligi uchun avval soni)
    best, key = None, (0, 0.0)
    for ent, spec in MODEL.items():
        hits = sum(1 for f in fields if any(_norm(f) == _norm(s) or _norm(s) in _norm(f).split() for syns in spec.values() for s in syns))
        k = (hits, hits / max(1, len(spec)))
        if k > key:
            best, key = ent, k
    return (best, round(min(0.7, key[0] / max(1, len(fields))), 2)) if key[0] >= 2 else (None, 0.0)


def map_fields(entity: str, fields: list[str]) -> dict:
    spec, out, used = MODEL.get(entity, {}), {}, set()
    for f in fields:
        nf = _norm(f)
        for canon, syns in spec.items():
            if canon in used:
                continue
            if any(nf == _norm(s) for s in syns):
                out[f], _ = canon, used.add(canon)
                break
    for f in fields:                               # ikkinchi bosqich: qisman moslik (masalan "Цена продажи, сум")
        if f in out:
            continue
        nf = _norm(f)
        for canon, syns in spec.items():
            if canon not in used and any(len(_norm(s)) >= 3 and _norm(s) in nf for s in syns):
                out[f], _ = canon, used.add(canon)
                break
    unmapped = [f for f in fields if f not in out]
    conf = round(len(out) / max(1, len(fields)), 2) if fields else 0.0
    return {"fields": out, "unmapped": unmapped, "confidence": conf}


def suggest(entities: list[dict]) -> dict:
    out = {}
    for e in entities:
        ent, ec = guess_entity(e["name"], e.get("fields") or [])
        if not ent:
            out[e["name"]] = {"entity": None, "fields": {}, "unmapped": e.get("fields") or [], "confidence": 0.0, "status": "unknown"}
            continue
        m = map_fields(ent, e.get("fields") or [])
        out[e["name"]] = {"entity": ent, **m, "confidence": round((ec + m["confidence"]) / 2, 2), "status": "suggested"}
    return out


def to_number(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v).replace("\xa0", "").replace(" ", ""))
    if s.count(",") and s.count("."):
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif s.count(",") == 1 and len(s.split(",")[1]) <= 2:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


NUMERIC = {"cost_price", "sale_price", "stock", "qty", "price", "amount", "debt"}


def apply(mapping: dict, row: dict) -> dict:
    out = {}
    for src, canon in (mapping.get("fields") or {}).items():
        if src in row:
            v = row[src]
            out[canon] = to_number(v) if canon in NUMERIC else (str(v).strip() if v is not None else None)
    return out
