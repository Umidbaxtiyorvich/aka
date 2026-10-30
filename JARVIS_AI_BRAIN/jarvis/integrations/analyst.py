"""POS Business Intelligence AI — ulangan barcha POS/ERP manbalari bo'yicha tahlil (ko'p do'kon).

Qoidalar:
* Faqat sinxronlangan ma'lumotdan (ext_records) hisoblaydi; ma'lumot yo'q bo'lsa — taxmin qilmaydi, "yo'q" deydi.
* Har javobda: manba(lar) (ulanish nomi), davr, hisoblash usuli va cheklovlar.
* Do'konlar aralashtirilmaydi: har ulanish (va uning 'store' yorlig'i) alohida hisoblanadi, umumiysi alohida qator.
* Sof foyda faqat xarajatlar (expense) manbasi bo'lsa; aks holda yalpi foyda va tushuntirish.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta


def _parse_date(v) -> date | None:
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:len(datetime.now().strftime(fmt))] if "%H" in fmt else s[:10], fmt).date()
        except ValueError:
            continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


PERIODS = {"bugun": "today", "today": "today", "сегодня": "today", "kecha": "yesterday", "вчера": "yesterday",
           "hafta": "week", "haftalik": "week", "неделя": "week", "oy": "month", "oylik": "month", "месяц": "month", "yil": "year", "yillik": "year", "год": "year"}


def period_range(name: str, today: date | None = None) -> tuple[date, date]:
    t = today or date.today()
    return {"today": (t, t), "yesterday": (t - timedelta(days=1), t - timedelta(days=1)), "week": (t - timedelta(days=6), t),
            "month": (t.replace(day=1), t), "year": (t.replace(month=1, day=1), t)}.get(name, (t, t))


def parse_question(q: str) -> dict:
    low = (q or "").lower().replace("‘", "'").replace("’", "'").replace("ʻ", "'")
    period = next((v for k, v in PERIODS.items() if re.search(rf"\b{k}", low)), None)
    if re.search(r"sof foyda|чистая прибыль|net profit", low):
        intent = "net_profit"
    elif re.search(r"foyda|прибыл|profit|rentabel|margin", low):
        intent = "profit"
    elif re.search(r"tugab|kam qol|qoldiq|остат|заканчива|low stock", low):
        intent = "low_stock"
    elif re.search(r"buyurtma qilish|zakaz|заказ|reorder|ko'proq olib", low):
        intent = "reorder"
    elif re.search(r"eng kam sotil|kam sotil|yomon sotil|хуже|least", low):
        intent = "bottom"
    elif re.search(r"eng ko'p sotil|yaxshi sotil|ko'p sotil|top|лучш|популяр|best", low):
        intent = "top"
    elif re.search(r"qarz|долг|debt", low):
        intent = "debts"
    elif re.search(r"qaysi do'kon|taqqosla|pasay|сравн|в каком магазин", low):
        intent = "stores"
    elif re.search(r"savdo|tushum|sotuv|продаж|выручк|sales|revenue|qancha sot", low):
        intent = "sales"
    elif re.search(r"ulanish|uzil|qaysi tizim|connection", low):
        intent = "connections"
    else:
        intent = None
    return {"intent": intent, "period": period or ("today" if intent in ("sales", "profit", "net_profit") else "month")}


def _money(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ") + " so'm"


class Analyst:
    def __init__(self, core):
        self.core = core

    def _rows(self, entity: str) -> list[dict]:
        out = []
        for r in self.core.db.query("SELECT e.conn_id, e.data, e.verification, i.name, i.store FROM ext_records e JOIN integrations i ON i.id=e.conn_id"
                                    " WHERE e.entity=? AND e.deleted=0", (entity,)):
            d = json.loads(r["data"])
            d["_conn"], d["_src"], d["_store"] = r["conn_id"], r["name"], d.get("store") or r["store"] or r["name"]
            d["_verified"] = r["verification"] == "mapping_confirmed"
            out.append(d)
        return out

    def _sales(self, period: str, today=None):
        a, b = period_range(period, today)
        rows = [r for r in self._rows("sale") if (d := _parse_date(r.get("date"))) and a <= d <= b]
        for r in rows:
            if r.get("amount") is None and r.get("qty") is not None and r.get("price") is not None:
                r["amount"] = r["qty"] * r["price"]
        return rows, (a, b)

    def _meta(self, rows, period, method, limits=None):
        srcs = sorted({r["_src"] for r in rows})
        unverified = sorted({r["_src"] for r in rows if not r["_verified"]})
        lim = list(limits or [])
        if unverified:
            lim.append(f"Maydonlar xaritasi tasdiqlanmagan: {', '.join(unverified)} — natija avtomatik xaritaga asoslangan")
        return {"sources": srcs, "period": [str(period[0]), str(period[1])] if period else None, "method": method, "limitations": lim}

    def answer(self, question: str, today: date | None = None) -> dict:
        p = parse_question(question)
        fn = {"sales": self.sales, "top": lambda per, t: self.top(per, t, best=True), "bottom": lambda per, t: self.top(per, t, best=False),
              "profit": self.profit, "net_profit": lambda per, t: self.profit(per, t, net=True), "low_stock": lambda per, t: self.low_stock(),
              "reorder": lambda per, t: self.reorder(t), "debts": lambda per, t: self.debts(), "stores": self.stores,
              "connections": lambda per, t: self.connections()}.get(p["intent"])
        if not fn:
            return {"handled": False}
        return {"handled": True, "intent": p["intent"], **fn(p["period"], today)}

    def _no_data(self, what):
        conns = self.core.db.one("SELECT COUNT(*) n FROM integrations")["n"]
        return {"text": f"{what} bo'yicha ma'lumot yo'q. " + ("Ulangan tizimlar sinxronlanmagan yoki savdo ma'lumoti xaritalanmagan — "
                "'Ulanishlar' bo'limida sinxronlashni ishga tushiring." if conns else "Hali hech qaysi POS ulanmagan ('Ulanishlar' → 'Yangi ulanish')."),
                "data": None, "sources": [], "period": None, "method": "—", "limitations": ["Taxmin qilinmadi"]}

    def sales(self, period, today=None):
        rows, rng = self._sales(period, today)
        if not rows:
            return self._no_data("Savdo")
        by = defaultdict(lambda: {"amount": 0.0, "lines": 0, "receipts": set()})
        for r in rows:
            s = by[r["_store"]]
            s["amount"] += r.get("amount") or 0
            s["lines"] += 1
            if r.get("receipt_no"):
                s["receipts"].add(r["receipt_no"])
        total = sum(v["amount"] for v in by.values())
        lines = [f"• {k}: {_money(v['amount'])}" + (f" ({len(v['receipts'])} chek)" if v["receipts"] else "") for k, v in sorted(by.items(), key=lambda x: -x[1]["amount"])]
        txt = f"Savdo ({rng[0]}{'' if rng[0] == rng[1] else ' — ' + str(rng[1])}): jami {_money(total)}\n" + "\n".join(lines)
        return {"text": txt, "data": {"total": total, "stores": {k: {"amount": v["amount"], "receipts": len(v["receipts"]), "lines": v["lines"]} for k, v in by.items()}},
                **self._meta(rows, rng, "Savdo qatorlari summasi (amount yoki qty×price) do'kon bo'yicha alohida, keyin jami")}

    def top(self, period, today=None, best=True, n=10):
        rows, rng = self._sales(period, today)
        if not rows:
            return self._no_data("Sotuv")
        agg = defaultdict(lambda: {"qty": 0.0, "amount": 0.0, "stores": set()})
        for r in rows:
            k = r.get("product_name") or r.get("sku") or "?"
            agg[k]["qty"] += r.get("qty") or 0
            agg[k]["amount"] += r.get("amount") or 0
            agg[k]["stores"].add(r["_store"])
        items = sorted(agg.items(), key=lambda x: -x[1]["qty"] if best else x[1]["qty"])[:n]
        txt = ("Eng ko'p" if best else "Eng kam") + f" sotilgan mahsulotlar ({rng[0]} — {rng[1]}):\n" + "\n".join(
            f"{i}. {k}: {v['qty']:g} dona, {_money(v['amount'])}" for i, (k, v) in enumerate(items, 1))
        return {"text": txt, "data": [{"product": k, "qty": v["qty"], "amount": v["amount"], "stores": sorted(v["stores"])} for k, v in items],
                **self._meta(rows, rng, "Sotilgan miqdor (qty) bo'yicha saralash", ["Umuman sotilmagan mahsulotlar bu ro'yxatga kirmaydi"] if not best else [])}

    def _products(self):
        prods = {}
        for p in self._rows("product"):
            prods[(p["_conn"], p.get("sku") or p.get("name"))] = p
        return prods

    def profit(self, period, today=None, net=False):
        rows, rng = self._sales(period, today)
        if not rows:
            return self._no_data("Foyda")
        prods = self._products()
        by_name = {(k[0], (p.get("name") or "").lower()): p for k, p in prods.items()}
        gross, revenue, missing, per = 0.0, 0.0, set(), defaultdict(float)
        for r in rows:
            p = prods.get((r["_conn"], r.get("sku"))) or by_name.get((r["_conn"], (r.get("product_name") or "").lower()))
            amt = r.get("amount") or 0
            revenue += amt
            if p and p.get("cost_price") is not None and r.get("qty") is not None:
                g = amt - r["qty"] * p["cost_price"]
                gross += g
                per[r.get("product_name") or r.get("sku")] += g
            else:
                missing.add(r.get("product_name") or r.get("sku") or "?")
        lim = []
        if missing:
            lim.append(f"{len(missing)} ta mahsulot uchun tannarx yo'q — ular foydaga kiritilmadi")
        top = sorted(per.items(), key=lambda x: -x[1])[:5]
        txt = f"Yalpi foyda ({rng[0]} — {rng[1]}): {_money(gross)} (tushum {_money(revenue)})"
        if top:
            txt += "\nEng ko'p foyda: " + "; ".join(f"{k} {_money(v)}" for k, v in top)
        data = {"revenue": revenue, "gross_profit": gross, "by_product": dict(top)}
        if net:
            exp = [e for e in self._rows("expense") if (d := _parse_date(e.get("date"))) and rng[0] <= d <= rng[1]]
            if exp:
                total_exp = sum(e.get("amount") or 0 for e in exp)
                data["expenses"], data["net_profit"] = total_exp, gross - total_exp
                txt += f"\nXarajatlar: {_money(total_exp)} → sof foyda: {_money(gross - total_exp)}"
            else:
                lim.append("Xarajatlar manbasi ulanmagan — SOF foyda hisoblanmadi, faqat yalpi foyda ko'rsatildi")
                txt += "\nSof foyda: hisoblab bo'lmaydi — xarajatlar ma'lumoti yo'q."
        return {"text": txt, "data": data, **self._meta(rows, rng, "Yalpi foyda = tushum − (sotilgan miqdor × tannarx)", lim)}

    def low_stock(self, threshold: float | None = None):
        thr = threshold if threshold is not None else float(self.core.settings.low_stock_threshold)
        prods = [p for p in self._products().values() if p.get("stock") is not None]
        if not prods:
            return self._no_data("Ombor qoldig'i")
        low = sorted([p for p in prods if p["stock"] <= thr], key=lambda p: p["stock"])
        txt = f"Kam qolgan mahsulotlar (≤ {thr:g}): {len(low)} ta\n" + "\n".join(f"• {p.get('name') or p.get('sku')}: {p['stock']:g} ({p['_store']})" for p in low[:20])
        return {"text": txt, "data": [{"product": p.get("name") or p.get("sku"), "stock": p["stock"], "store": p["_store"]} for p in low],
                **self._meta(prods, None, f"Qoldiq ≤ {thr:g} (Sozlamalar → kam qolgan chegarasi)")}

    def reorder(self, today=None, days: int = 14, cover_days: int = 7):
        rows, rng = self._sales("week", today)
        t = today or date.today()
        rows = [r for r in self._rows("sale") if (d := _parse_date(r.get("date"))) and t - timedelta(days=days - 1) <= d <= t]
        prods = self._products()
        if not rows or not prods:
            return self._no_data("Buyurtma tavsiyasi (savdo + qoldiq)")
        sold = defaultdict(float)
        for r in rows:
            sold[(r["_conn"], r.get("sku"))] += r.get("qty") or 0
        recs = []
        for k, p in prods.items():
            daily = sold.get(k, 0) / days
            if daily > 0 and p.get("stock") is not None and p["stock"] / daily < cover_days:
                recs.append({"product": p.get("name") or k[1], "store": p["_store"], "stock": p["stock"], "daily_avg": round(daily, 2),
                             "days_left": round(p["stock"] / daily, 1), "suggest_qty": max(0, round(daily * cover_days * 2 - p["stock"]))})
        recs.sort(key=lambda x: x["days_left"])
        txt = f"Buyurtma qilish tavsiyasi (oxirgi {days} kun savdosi, {cover_days} kunga yetmaydiganlar): {len(recs)} ta\n" + "\n".join(
            f"• {r['product']} ({r['store']}): qoldiq {r['stock']:g}, kuniga ~{r['daily_avg']:g}, ~{r['days_left']:g} kunga yetadi → ~{r['suggest_qty']} dona" for r in recs[:15])
        return {"text": txt, "data": recs, **self._meta(rows, (t - timedelta(days=days - 1), t), "kunlik o'rtacha sotuv × 14 kun − qoldiq",
                                                          ["Bu tavsiya — buyurtma avtomatik berilmaydi"])}

    def debts(self):
        cs, ss = self._rows("customer"), self._rows("supplier")
        if not cs and not ss:
            return self._no_data("Qarzdorlik")
        cd = sum(c.get("debt") or 0 for c in cs if (c.get("debt") or 0) > 0)
        sd = sum(s.get("debt") or 0 for s in ss if (s.get("debt") or 0) > 0)
        top = sorted([c for c in cs if (c.get("debt") or 0) > 0], key=lambda c: -c["debt"])[:10]
        txt = f"Mijozlar qarzi: {_money(cd)} ({len([c for c in cs if (c.get('debt') or 0) > 0])} ta)\nYetkazib beruvchilarga qarz: {_money(sd)}"
        if top:
            txt += "\nEng katta: " + "; ".join(f"{c.get('name')} {_money(c['debt'])}" for c in top[:5])
        return {"text": txt, "data": {"customers": cd, "suppliers": sd, "top": [{"name": c.get("name"), "debt": c["debt"], "store": c["_store"]} for c in top]},
                **self._meta(cs + ss, None, "Qarz maydoni musbat bo'lganlar yig'indisi (oxirgi sinxronlash holati)")}

    def stores(self, period, today=None):
        t = today or date.today()
        cur = [r for r in self._rows("sale") if (d := _parse_date(r.get("date"))) and t - timedelta(days=6) <= d <= t]
        prev = [r for r in self._rows("sale") if (d := _parse_date(r.get("date"))) and t - timedelta(days=13) <= d <= t - timedelta(days=7)]
        if not cur and not prev:
            return self._no_data("Do'konlar savdosi")
        def agg(rows):
            out = defaultdict(float)
            for r in rows:
                out[r["_store"]] += r.get("amount") or 0
            return out
        a, b = agg(cur), agg(prev)
        res = []
        for s in sorted(set(a) | set(b)):
            ch = ((a[s] - b[s]) / b[s] * 100) if b[s] else None
            res.append({"store": s, "this_week": a[s], "last_week": b[s], "change_pct": round(ch, 1) if ch is not None else None})
        res.sort(key=lambda x: -x["this_week"])
        down = [r for r in res if r["change_pct"] is not None and r["change_pct"] < 0]
        txt = "Do'konlar (oxirgi 7 kun vs oldingi 7 kun):\n" + "\n".join(
            f"• {r['store']}: {_money(r['this_week'])}" + (f" ({'+' if r['change_pct'] >= 0 else ''}{r['change_pct']}%)" if r["change_pct"] is not None else " (taqqoslash uchun oldingi hafta yo'q)") for r in res)
        if down:
            txt += "\nPasaygan: " + ", ".join(f"{r['store']} ({r['change_pct']}%)" for r in down)
        return {"text": txt, "data": res, **self._meta(cur + prev, (t - timedelta(days=13), t), "Har do'kon alohida: haftalik summa va o'zgarish foizi")}

    def connections(self):
        h = self.core.integrations.health()
        if not h:
            return {"text": "Hali hech qanday tizim ulanmagan.", "data": [], "sources": [], "period": None, "method": "—", "limitations": []}
        bad = [x for x in h if x["status"] not in ("connected", "syncing", "new")]
        txt = "Ulanishlar:\n" + "\n".join(f"• {x['name']} ({x['adapter']}): {x['status']}" + (f" — {x['note']}" if x["status"] != "connected" and x["note"] else "") for x in h)
        if bad:
            txt += f"\nMuammoli: {len(bad)} ta"
        return {"text": txt, "data": h, "sources": [x["name"] for x in h], "period": None, "method": "Oxirgi tekshiruv holati", "limitations": []}
