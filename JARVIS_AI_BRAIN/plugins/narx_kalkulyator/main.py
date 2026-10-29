"""Narx kalkulyatori: sotish = tannarx × (1 + ustama%) × (1 + QQS%), yaxlitlangan."""


def run(input, ctx):
    cfg = ctx.get("config", {})
    items = input.get("items") or ([{"name": input.get("name", ""), "cost": input["cost"]}] if "cost" in input else [])
    if not items:
        return {"result": {"error": "cost yoki items kiritilmagan"}}
    step = cfg.get("round_to") or 1
    out = []
    for it in items:
        cost = float(it["cost"])
        net = cost * (1 + cfg["markup_percent"] / 100)
        gross = net * (1 + cfg["vat_percent"] / 100)
        price = round(gross / step) * step
        out.append({"name": it.get("name", ""), "cost": cost, "price_without_vat": round(net, 2), "price": price,
                    "margin": round(price / (1 + cfg["vat_percent"] / 100) - cost, 2)})
    return {"result": {"items": out, "vat_percent": cfg["vat_percent"], "markup_percent": cfg["markup_percent"]}}
