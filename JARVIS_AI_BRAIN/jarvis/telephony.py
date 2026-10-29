"""Telefon qo'ng'irog'i (ixtiyoriy, PULLIK).

Telegram xabari qo'ng'iroq EMAS. Haqiqiy qo'ng'iroq uchun tashqi provayder kerak:
* `twilio` — Twilio Voice API (daqiqasiga to'lov + raqam ijarasi; O'zbekistonga qo'ng'iroq narxi Twilio saytida).
  Sozlama: telephony_provider="twilio", telephony_from="+1...", telephony_account_sid="AC...";
  token: `python scripts/set_secret.py twilio_auth_token`. Twilio <Say> o'zbek tilini qo'llamaydi —
  xabar rus yoki ingliz tilida o'qiladi (telephony_voice_language).
Qoidalar (`telephony_rules`): [{"category": "pos", "severity": "critical", "phone": "+998..."}] — mos bildirishnoma
kelganda qo'ng'iroq REJASI va D-darajali tasdiq so'rovi yaratiladi. Qo'ng'iroq faqat siz tasdiqlagandan keyin.
"""
from __future__ import annotations

import re
from xml.sax.saxutils import escape

from . import net
from .approval import ApprovalEngine
from .secrets import get_secret


class TelephonyError(Exception):
    pass


class Telephony:
    def __init__(self, settings, approvals: ApprovalEngine):
        self.settings, self.approvals = settings, approvals

    def status(self) -> dict:
        p = self.settings.telephony_provider
        ready = p == "twilio" and bool(self.settings.telephony_account_sid and self.settings.telephony_from and get_secret("twilio_auth_token"))
        return {"configured": bool(p), "ready": ready, "provider": p or None, "cost_per_min": self.settings.telephony_cost_per_min,
                "rules": self.settings.telephony_rules,
                "note": ("Tayyor — har bir qo'ng'iroq tasdiq bilan" if ready else
                         "Provayder tanlangan, lekin SID/raqam/token to'liq emas" if p else
                         "O'chirilgan. Yoqish uchun pullik provayder (Twilio) kerak — narxini oldindan ko'rib chiqing.")}

    def plan_call(self, phone: str, message: str, reason: str, est_minutes: float = 1.0) -> dict:
        phone = phone.replace(" ", "")
        if not re.fullmatch(r"\+?\d{9,15}", phone):
            raise TelephonyError("Telefon raqami noto'g'ri formatda")
        if not self.settings.telephony_provider:
            raise TelephonyError("Telephony provayderi sozlanmagan — qo'ng'iroq rejalashtirilmaydi.")
        if not message.strip() or len(message) > 500:
            raise TelephonyError("Xabar 1–500 belgi bo'lishi kerak")
        cost = round(est_minutes * self.settings.telephony_cost_per_min, 2)
        return self.approvals.request(
            action_type="phone_call", target=self.settings.telephony_provider, level="D",
            payload={"phone": phone, "message": message, "reason": reason, "est_minutes": est_minutes, "est_cost": cost},
            summary=f"Qo'ng'iroq {phone}: {reason} (taxminiy narx {cost} {self.settings.currency}). Matn: «{message[:120]}»",
            requested_by="notifier", purpose=reason)

    def call(self, approval_id: int) -> dict:
        row = self.approvals.get(approval_id)
        if row["action_type"] != "phone_call":
            raise TelephonyError("Bu tasdiq qo'ng'iroq uchun emas")
        payload = row["payload"]
        self.approvals.authorize_execution(approval_id, payload)
        if self.settings.telephony_provider != "twilio":
            raise TelephonyError(f"'{self.settings.telephony_provider}' provayderi uchun adapter yo'q")
        sid, token = self.settings.telephony_account_sid, get_secret("twilio_auth_token")
        if not (sid and token and self.settings.telephony_from):
            raise TelephonyError("Twilio sozlamalari to'liq emas (SID, raqam, token)")
        lang = self.settings.telephony_voice_language or "ru-RU"
        twiml = f'<Response><Say language="{escape(lang)}">{escape(payload["message"])}</Say></Response>'
        import base64
        auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        try:
            r = net.post_json(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json",
                              form={"To": payload["phone"], "From": self.settings.telephony_from, "Twiml": twiml},
                              headers={"Authorization": f"Basic {auth}"}, timeout=30)
        except net.NetError as e:
            self.approvals.mark_result(approval_id, "unknown" if e.status is None else "executed")
            raise TelephonyError(f"Qo'ng'iroq xatosi: {e}" + (" — natija noma'lum, Twilio konsolida tekshiring" if e.status is None else "")) from None
        self.approvals.mark_result(approval_id, "executed")
        return {"call_sid": r.get("sid"), "status": r.get("status"), "to": payload["phone"]}

    def on_notification(self, note: dict) -> dict | None:
        """Bildirishnoma qoidaga mos kelsa — qo'ng'iroq rejasi (tasdiq kutadi). Hech qachon avtomatik qo'ng'iroq qilmaydi."""
        for rule in self.settings.telephony_rules or []:
            if rule.get("category") in (note["category"], "*") and rule.get("severity", "critical") == note["severity"]:
                try:
                    return self.plan_call(rule["phone"], f"JARVIS: {note['title']}. {note.get('body', '')}"[:480],
                                          f"Qoida: {note['category']}/{note['severity']}")
                except Exception:
                    return None
        return None
