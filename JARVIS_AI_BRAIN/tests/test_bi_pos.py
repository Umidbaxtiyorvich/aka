import pytest

from jarvis.approval import ApprovalError
from jarvis.bi import BIError
from jarvis.pos import POSError, UnknownOutcome

PRODUCTS = "Kod;Nomi;Shtrix-kod;Birlik;Tannarx;Sotish narxi;Qoldiq;Minimal\nA1;Non;4780001;dona;3000;4000;3;5\nB2;Sut;4780002;litr;9000;8500;20;\nC3;Shakar;4780003;kg;12000;0;7;\n"
MOVES = ("Hujjat raqami,Turi,Sana,Kontragent,Kod,Miqdor,Narx,Summa\n"
         "K-1,kirim,2026-10-01,Ali MChJ,A1,10,3000,30000\n"
         "S-1,sotuv,2026-10-02,Mijoz,A1,2,4000,8000\n"
         "S-2,sotuv,2026-10-02,Mijoz,A1,1,4000,4000\n"
         "S-3,sotuv,2026-10-03,Mijoz,A1,1,9000,9000\n"
         "S-4,sotuv,2026-10-03,Mijoz,B2,2,8500,18000\n"
         "X-1,nomalum,2026-10-03,,A1,1,1,1\n"
         "S-5,sotuv,2026-10-03,Mijoz,Z9,-1,1,1\n")
PAYMENTS = "Sana,Kontragent,Summa,Yo'nalish\n2026-10-05,Ali MChJ,20000,out\n"


def _write(core, name, text, enc="utf-8"):
    p = f"{core.settings.allowed_read_dirs[0]}/{name}"
    open(p, "w", encoding=enc).write(text)
    return p


def test_bi_import_and_analysis(core):
    src = _write(core, "mahsulot.csv", PRODUCTS, enc="cp1251")
    before = open(src, "rb").read()
    r = core.bi.import_file(src, "products")
    assert r["rows_ok"] == 3 and open(src, "rb").read() == before   # asl fayl o'zgarmadi
    with pytest.raises(BIError, match="allaqachon"):
        core.bi.import_file(src, "products")
    m = core.bi.import_file(_write(core, "harakat.csv", MOVES), "movements")
    assert m["rows_ok"] == 5 and m["rows_bad"] == 2
    core.bi.import_file(_write(core, "tolov.csv", PAYMENTS), "payments")

    low = {x["sku"] for x in core.bi.low_stock()}
    assert "A1" in low and "B2" not in low
    issues = " ".join(i["issue"] for i in core.bi.price_issues())
    assert "xarid narxidan past" in issues and "0 yoki manfiy" in issues and "≠ summa" in issues
    prof = core.bi.profit()
    assert prof["revenue"] == 39000 and prof["cost_of_goods"] == 3000 * 4 + 9000 * 2
    a1 = next(s for s in core.bi.stock() if s["sku"] == "A1")
    assert a1["computed_from_movements"] == 6 and a1["difference"] == -3
    debt = next(d for d in core.bi.debts() if d["party"] == "Ali MChJ")
    assert debt["we_owe"] == 10000


def test_bi_missing_columns(core):
    with pytest.raises(BIError, match="Majburiy"):
        core.bi.import_file(_write(core, "x.csv", "a,b\n1,2\n"), "movements")


def test_bi_empty_report_does_not_invent(core):
    r = core.bi.report()
    assert r["has_data"] is False and r["profit"]["revenue"] == 0 and r["low_stock"] == []


ITEMS = [{"sku": "A1", "name": "Non", "qty": 10, "price": 3000}]


def _approve(core, appr):
    core.approvals.decide(appr["id"], True, appr["payload_hash"])


def test_pos_two_stage_flow(core):
    d = core.pos.create_draft("kirim", "Ali MChJ", ITEMS)
    assert d["status"] == "draft" and d["total"] == 30000
    with pytest.raises(POSError):
        core.pos.submit(d["id"])                       # tasdiqsiz kiritilmaydi
    r = core.pos.request_approval(d["id"])
    with pytest.raises(ApprovalError):
        core.pos.submit(d["id"])                       # hali tasdiqlanmagan
    _approve(core, r["approval"])
    done = core.pos.submit(d["id"])
    assert done["status"] == "verified"
    with pytest.raises(ApprovalError, match="allaqachon"):
        core.pos.submit(d["id"])                       # takroriy kiritish yo'q
    with pytest.raises(POSError):
        core.pos.update_draft(d["id"], ITEMS)


def test_pos_change_after_approval_invalidates(core):
    d = core.pos.create_draft("kirim", "Ali MChJ", ITEMS)
    r = core.pos.request_approval(d["id"])
    _approve(core, r["approval"])
    d2 = core.pos.update_draft(d["id"], [ITEMS[0] | {"qty": 11}])
    assert d2["version"] == 2 and d2["status"] == "draft"
    assert core.approvals.get(r["approval"]["id"])["status"] == "invalidated"
    with pytest.raises(POSError):
        core.pos.submit(d["id"])
    r2 = core.pos.request_approval(d["id"])
    assert r2["approval"]["payload"]["version"] == 2 and r2["approval"]["payload"]["total"] == 33000


def test_pos_unknown_outcome_never_resends(core):
    class Flaky:
        name = "flaky"
        def __init__(self): self.store, self.calls = {}, 0
        def status(self): return {"connector": "flaky", "connected": True}
        def find_existing(self, k): return self.store.get(k)
        def create(self, k, doc):
            self.calls += 1
            self.store[k] = "EXT-1"           # aslida yozildi, lekin javob kelmadi
            raise UnknownOutcome("timeout")
        def verify(self, k, doc): return k in self.store

    core.pos.connector = Flaky()
    d = core.pos.create_draft("sotuv", "Mijoz", ITEMS)
    _approve(core, core.pos.request_approval(d["id"])["approval"])
    assert core.pos.submit(d["id"])["status"] == "unknown"
    with pytest.raises(POSError, match="noma'lum"):
        core.pos.submit(d["id"])
    assert core.pos.check_unknown(d["id"])["status"] == "verified"
    assert core.pos.connector.calls == 1


def test_pos_validation(core):
    with pytest.raises(POSError):
        core.pos.create_draft("kirim", "", ITEMS)
    with pytest.raises(POSError):
        core.pos.create_draft("kirim", "A", [{"sku": "A1", "qty": -1, "price": 1}])
    with pytest.raises(POSError):
        core.pos.create_draft("kirim", "A", ITEMS + ITEMS)
