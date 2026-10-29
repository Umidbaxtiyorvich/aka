"""Telefon qo'ng'irog'i — loyiha (keyingi bosqich).

Haqiqiy qo'ng'iroq uchun tashqi SIP/telephony provayder (pullik) kerak. Telegram xabari qo'ng'iroq EMAS.
Hozir: qo'ng'iroq rejasini tuzish va D-darajali tasdiq so'rovi (raqam, matn, sabab, taxminiy narx).
Provayder adapteri ulanmaguncha qo'ng'iroq bajarilmaydi.
"""
from __future__ import annotations

import re

from .approval import ApprovalEngine


class TelephonyError(Exception):
    pass


class Telephony:
    def __init__(self, settings, approvals: ApprovalEngine):
        self.settings, self.approvals = settings, approvals

    def status(self) -> dict:
        p = self.settings.telephony_provider
        return {"configured": bool(p), "provider": p or None, "cost_per_min": self.settings.telephony_cost_per_min,
                "note": "Provayder adapteri hali yozilmagan — qo'ng'iroqlar bajarilmaydi." if p else
                        "O'chirilgan. Yoqish uchun SIP/telephony provayderi tanlanadi (pullik, narxi oldindan ko'rsatiladi)."}

    def plan_call(self, phone: str, message: str, reason: str, est_minutes: float = 1.0) -> dict:
        if not re.fullmatch(r"\+?\d{9,15}", phone.replace(" ", "")):
            raise TelephonyError("Telefon raqami noto'g'ri formatda")
        if not self.settings.telephony_provider:
            raise TelephonyError("Telephony provayderi sozlanmagan — qo'ng'iroq rejalashtirilmaydi.")
        cost = round(est_minutes * self.settings.telephony_cost_per_min, 2)
        return self.approvals.request(
            action_type="phone_call", target=self.settings.telephony_provider, level="D",
            payload={"phone": phone, "message": message, "reason": reason, "est_minutes": est_minutes, "est_cost": cost},
            summary=f"Qo'ng'iroq {phone}: {reason} (taxminiy narx {cost})", requested_by="notifier")
