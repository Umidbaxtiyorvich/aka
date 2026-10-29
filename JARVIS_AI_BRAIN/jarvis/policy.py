"""Policy Engine — har bir amal uchun markaziy qoida: low / medium / high / forbidden.

* low     — ichki, qaytariladigan amal (o'qish, tahlil, lokal draft): avtomatik (A/B).
* medium  — mahalliy o'zgarish: standart holatda tasdiq (C); foydalanuvchi `medium_auto_actions`
            ro'yxatiga qo'shgan amallargina avtomatik.
* high    — tashqi tizim, moliya, xabar, o'chirish, qaytarib bo'lmaydigan: har doim aniq tasdiq (D/E).
* forbidden — xavfsizlik qoidalariga zid: hech qachon bajarilmaydi, tasdiq bilan ham.

ApprovalEngine.request() har bir so'rovni shu yerdan o'tkazadi: chaqiruvchi kod past daraja so'rasa ham,
siyosatdagi minimal daraja qo'llanadi. Tasdiqni chetlab o'tadigan yashirin yo'l yo'q.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

LEVEL_ORDER = "ABCDE"
RISK_OF_LEVEL = {"A": "low", "B": "low", "C": "medium", "D": "high", "E": "high"}

# action_type -> (risk, minimal daraja, qaytarib bo'ladimi, ta'sir tavsifi)
ACTIONS: dict[str, tuple[str, str, bool, str]] = {
    "read": ("low", "A", True, "Faqat o'qish — hech narsa o'zgarmaydi"),
    "analysis": ("low", "A", True, "Ichki tahlil"),
    "local_draft": ("low", "B", True, "Mahalliy loyiha fayli yoki yozuv yaratiladi"),
    "shell_read": ("low", "A", True, "Faqat o'qiydigan buyruq (fayl ro'yxati, holat)"),
    "shell_command": ("medium", "C", False, "Kompyuterda buyruq bajariladi"),
    "sandbox_run": ("low", "B", True, "Xavfsiz deb topilgan kod cheklangan vaqtinchalik papkada ishga tushiriladi"),
    "sandbox_unsafe_run": ("high", "E", False, "Xavfli deb topilgan kod cheklangan muhitda ishga tushiriladi"),
    "settings_change": ("medium", "C", True, "JARVIS sozlamasi o'zgaradi"),
    "code_change": ("medium", "C", True, "Alohida git branch'ga commit (asosiy branch o'zgarmaydi)"),
    "plugin_enable": ("medium", "C", True, "Kengaytma ishga tushirishga ruxsat oladi"),
    "pos_kirim": ("high", "D", False, "Tashqi POSga kirim hujjati kiritiladi"),
    "pos_chiqim": ("high", "D", False, "Tashqi POSga chiqim hujjati kiritiladi"),
    "pos_sotuv": ("high", "D", False, "Tashqi POSga savdo kiritiladi"),
    "pos_qaytarish": ("high", "D", False, "Tashqi POSga qaytarish kiritiladi"),
    "pos_tolov": ("high", "D", False, "Moliyaviy to'lov yozuvi kiritiladi"),
    "instagram_publish": ("high", "D", False, "Instagram'da ommaviy nashr"),
    "instagram_reply": ("high", "D", False, "Instagram izohiga ommaviy javob"),
    "telegram_send": ("high", "D", False, "Telegram orqali xabar yuboriladi"),
    "phone_call": ("high", "D", False, "Pullik telefon qo'ng'irog'i"),
    "paid_ai_call": ("high", "D", False, "Pullik AI xizmatiga so'rov (xarajat)"),
    "backup_restore": ("high", "E", False, "Joriy ma'lumotlar zaxira nusxasi bilan almashtiriladi"),
    "file_delete": ("high", "E", False, "Fayl o'chiriladi"),
}
# Hech qachon bajarilmaydigan amallar
FORBIDDEN: dict[str, str] = {
    "bypass_captcha": "CAPTCHA yoki 2FA'ni chetlab o'tish taqiqlangan",
    "bypass_login": "Login/himoyani chetlab o'tish taqiqlangan",
    "store_secret_plain": "Maxfiy kalitni ochiq saqlash taqiqlangan",
    "send_secret_external": "Maxfiy ma'lumotni tashqariga yuborish taqiqlangan",
    "modify_security_policy": "JARVIS o'z xavfsizlik qoidalarini o'zgartira olmaydi",
    "disable_approval": "Tasdiqlash tizimini o'chirish taqiqlangan",
    "write_outside_allowed": "Ruxsat berilgan papkalardan tashqariga yozish taqiqlangan",
}
FORBIDDEN_COMMANDS = re.compile(
    r"(?i)\b(format\s+[a-z]:|diskpart|bcdedit|cipher\s+/w|vssadmin\s+delete|reg\s+delete\s+hk(lm|ey_local)|"
    r"mkfs|dd\s+if=.*of=/dev/|shutdown|Set-MpPreference|netsh\s+advfirewall\s+set.*off|"
    r"Disable-WindowsOptionalFeature|net\s+user\s+\S+\s+/add|takeown\s+/f\s+c:\\windows)")


class PolicyViolation(Exception):
    pass


@dataclass
class PolicyDecision:
    action_type: str
    risk: str                 # low | medium | high | forbidden
    level: str                # A..E
    requires_approval: bool
    reversible: bool
    impact: str
    reason: str

    def public(self) -> dict:
        return asdict(self)


class PolicyEngine:
    def __init__(self, settings):
        self.settings = settings

    def evaluate(self, action_type: str, requested_level: str | None = None, *, command: str | None = None) -> PolicyDecision:
        if action_type in FORBIDDEN or action_type in set(self.settings.forbidden_actions):
            return PolicyDecision(action_type, "forbidden", "E", True, False, "—",
                                  FORBIDDEN.get(action_type, "Foydalanuvchi siyosati bo'yicha taqiqlangan"))
        if command is not None:
            if FORBIDDEN_COMMANDS.search(command):
                return PolicyDecision(action_type, "forbidden", "E", True, False, "Tizimga jiddiy zarar",
                                      "Bu buyruq xavfsizlik siyosati bo'yicha taqiqlangan")
            allow = {a.lower() for a in self.settings.command_allowlist}
            if allow:
                for part in re.split(r"&&|\|\||[;&|\n]|\$\(|`", command):
                    if not part.strip():
                        continue
                    first = re.split(r"\s+", part.strip(), maxsplit=1)[0]
                    first = re.sub(r"\.(exe|cmd|bat|ps1)$", "", first.rsplit("\\", 1)[-1].rsplit("/", 1)[-1], flags=re.I)
                    if first.lower() not in allow:
                        return PolicyDecision(action_type, "forbidden", "E", True, False, "—",
                                              f"'{first}' ruxsat etilgan buyruqlar ro'yxatida yo'q (command_allowlist)")
        risk, min_level, reversible, impact = ACTIONS.get(action_type, ("high", "D", False, "Noma'lum amal — ehtiyot chorasi"))
        level = max(min_level, requested_level or min_level, key=LEVEL_ORDER.index)
        risk = max(risk, RISK_OF_LEVEL[level], key=["low", "medium", "high"].index)
        if risk == "low":
            return PolicyDecision(action_type, risk, level, False, reversible, impact, "Past xavf — avtomatik")
        if risk == "medium" and action_type in self.settings.medium_auto_actions and level == "C":
            return PolicyDecision(action_type, risk, level, False, reversible, impact,
                                  "O'rta xavf — siz sozlagan siyosat bo'yicha avtomatik")
        why = "O'rta xavf — aniq tasdiq kerak" if risk == "medium" else "Yuqori xavf — har bir amal uchun alohida tasdiq"
        return PolicyDecision(action_type, risk, level, True, reversible, impact, why)

    def enforce(self, action_type: str, requested_level: str | None = None, *, command: str | None = None) -> PolicyDecision:
        d = self.evaluate(action_type, requested_level, command=command)
        if d.risk == "forbidden":
            raise PolicyViolation(d.reason)
        return d

    def table(self) -> list[dict]:
        rows = [{"action_type": k, "risk": v[0], "min_level": v[1], "reversible": v[2], "impact": v[3],
                 "auto": v[0] == "low" or (v[0] == "medium" and k in self.settings.medium_auto_actions)}
                for k, v in ACTIONS.items()]
        rows += [{"action_type": k, "risk": "forbidden", "min_level": "—", "reversible": False, "impact": v, "auto": False}
                 for k, v in FORBIDDEN.items()]
        return rows
