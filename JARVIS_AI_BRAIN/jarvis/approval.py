"""Approval Engine.

Tasdiq aniq amalga bog'lanadi: amal turi + tizim/sayt + akkaunt + to'liq payload (hujjat
versiyasi, mahsulotlar, miqdor, narx, summa). Payload SHA-256 xeshi saqlanadi; bajarishda
payload qayta xeshlanadi — mos kelmasa, tasdiq bekor bo'ladi.

Darajalar:
  A — o'qish/tahlil (avtomatik)          B — mahalliy loyiha/draft (avtomatik, ko'rsatiladi)
  C — mahalliy fayl/sozlama o'zgarishi   D — tashqi tizim, xabar, post, moliyaviy amal (har biri alohida)
  E — o'chirish / qaytarib bo'lmaydigan (alohida ogohlantirish)
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .audit import Audit
from .db import Database
from .security import contains_secret

AUTO_LEVELS = {"A", "B"}
LEVEL_INFO = {
    "A": "O'qish va tahlil — avtomatik",
    "B": "Mahalliy draft — avtomatik, natija ko'rsatiladi",
    "C": "Fayl yoki sozlamani o'zgartirish — aniq tasdiq",
    "D": "Tashqi tizim / xabar / post / moliyaviy amal — har bir amal uchun alohida tasdiq",
    "E": "O'chirish yoki qaytarib bo'lmaydigan amal — OGOHLANTIRISH va aniq tasdiq",
}


class ApprovalError(Exception):
    pass


def payload_hash(action_type: str, target: str, account: str | None, payload: dict) -> str:
    canon = json.dumps({"a": action_type, "t": target, "acc": account or "", "p": payload},
                       sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


class ApprovalEngine:
    def __init__(self, db: Database, audit: Audit):
        self.db, self.audit = db, audit

    def request(self, *, action_type: str, target: str, level: str, payload: dict, summary: str,
                requested_by: str, account: str | None = None, idempotency_key: str | None = None) -> dict:
        if level not in LEVEL_INFO:
            raise ApprovalError(f"Noma'lum daraja: {level}")
        if contains_secret(json.dumps(payload, ensure_ascii=False)):
            raise ApprovalError("Payload ichida maxfiy ma'lumot bor — tasdiqqa qo'yilmaydi.")
        h = payload_hash(action_type, target, account, payload)
        if idempotency_key:
            existing = self.db.one("SELECT * FROM approvals WHERE idempotency_key=?", (idempotency_key,))
            if existing:
                return existing
        status = "approved" if level in AUTO_LEVELS else "pending"
        cur = self.db.execute(
            "INSERT INTO approvals(action_type, target, account, level, payload, payload_hash, summary, status,"
            " requested_by, idempotency_key) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (action_type, target, account, level, json.dumps(payload, ensure_ascii=False), h, summary,
             status, requested_by, idempotency_key),
        )
        self.audit.log(requested_by, f"Tasdiq so'raldi: {summary}", target=target, risk=level, approval_status=status)
        return self.get(cur.lastrowid)

    def get(self, approval_id: int) -> dict:
        row = self.db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if not row:
            raise ApprovalError("Tasdiq topilmadi")
        row["payload"] = json.loads(row["payload"])
        row["level_info"] = LEVEL_INFO[row["level"]]
        return row

    def list(self, status: str | None = None) -> list[dict]:
        sql = "SELECT id FROM approvals" + (" WHERE status=?" if status else "") + " ORDER BY id DESC LIMIT 200"
        return [self.get(r["id"]) for r in self.db.query(sql, (status,) if status else ())]

    def decide(self, approval_id: int, approve: bool, confirm_hash: str) -> dict:
        """Foydalanuvchi ko'rgan aniq versiya xeshini yuborishi shart (umumiy "ha" yetmaydi)."""
        row = self.get(approval_id)
        if row["status"] != "pending":
            raise ApprovalError(f"Bu tasdiq holati: {row['status']}")
        if confirm_hash != row["payload_hash"]:
            raise ApprovalError("Xesh mos emas: siz boshqa versiyani tasdiqlayapsiz.")
        status = "approved" if approve else "rejected"
        self.db.execute("UPDATE approvals SET status=?, decided_at=? WHERE id=?",
                        (status, datetime.now(timezone.utc).isoformat(), approval_id))
        self.audit.log("user", f"Qaror: {status} — {row['summary']}", target=row["target"], risk=row["level"],
                       approval_status=status)
        return self.get(approval_id)

    def invalidate_for_change(self, approval_id: int, new_payload: dict) -> dict:
        """Hujjat o'zgarsa, eski tasdiq bekor qilinadi va yangisi so'raladi."""
        row = self.get(approval_id)
        self.db.execute("UPDATE approvals SET status='invalidated' WHERE id=?", (approval_id,))
        self.audit.log("approval_engine", f"Hujjat o'zgardi, tasdiq bekor: #{approval_id}", target=row["target"],
                       risk=row["level"], approval_status="invalidated")
        return self.request(action_type=row["action_type"], target=row["target"], level=row["level"],
                            payload=new_payload, summary=row["summary"] + " (yangi versiya)",
                            requested_by=row["requested_by"], account=row["account"])

    def authorize_execution(self, approval_id: int, payload: dict) -> dict:
        """Bajarishdan oldin chaqiriladi. Payload o'zgargan yoki tasdiqlanmagan bo'lsa, xato."""
        row = self.get(approval_id)
        if row["status"] == "executed":
            raise ApprovalError("Bu amal allaqachon bajarilgan (takroriy kiritishdan himoya).")
        if row["status"] == "unknown":
            raise ApprovalError("Oldingi natija noma'lum — avval tashqi tizimdagi holatni tekshiring.")
        if row["status"] != "approved":
            raise ApprovalError(f"Tasdiqlanmagan (holat: {row['status']}).")
        h = payload_hash(row["action_type"], row["target"], row["account"], payload)
        if h != row["payload_hash"]:
            self.db.execute("UPDATE approvals SET status='invalidated' WHERE id=?", (approval_id,))
            raise ApprovalError("Payload tasdiqdan keyin o'zgargan — tasdiq bekor qilindi.")
        return row

    def mark_result(self, approval_id: int, outcome: str) -> None:
        assert outcome in {"executed", "unknown", "approved"}
        self.db.execute("UPDATE approvals SET status=?, executed_at=? WHERE id=?",
                        (outcome, datetime.now(timezone.utc).isoformat(), approval_id))
