"""Telegram Control Center (rasmiy Bot API, long polling).

Xavfsizlik modeli:
* Token faqat secret storage'da (dashboard → Telegram → token maydoni). Bot URL'i token saqlaydi — logga yozilmaydi.
* Boshqaruv egasi FAQAT BITTA akkaunt. Ulash: dashboard bir martalik kod (10 daqiqa) beradi → siz botga
  `/start KOD` yuborasiz → (raqam belgilangan bo'lsa) kontakt tugmasi bilan telefonni tasdiqlaysiz.
  Kontakt faqat o'zingizniki bo'lsa qabul qilinadi (contact.user_id == yuboruvchi).
* Xabar va buyruqlar faqat egasining shaxsiy chatidan (user_id VA chat_id mos) qabul qilinadi. Guruhlar,
  kanallar va boshqa odamlar e'tiborsiz qoldiriladi: javob yo'q, ma'lumot yo'q, faqat audit yozuvi.
* Token almashtirilsa, eski egalik bekor bo'ladi (token izi mos kelmaydi) — qayta ulash kerak.
* Telegram tasdiqlari: har so'rov uchun alohida tasodifiy kalit, muddat, bir martalik; qaror aynan yuborilgan
  versiya xeshi bilan qabul qilinadi (payload o'zgarsa — eski tugma ishlamaydi). E-daraja faqat dashboardda.
* Telefon qo'ng'irog'i: Bot API bot nomidan qo'ng'iroq qilishga ruxsat bermaydi — bu yerda qo'ng'iroq YO'Q.
  Haqiqiy qo'ng'iroq faqat alohida ulangan telefoniya xizmati (telephony.py, Twilio) orqali va tasdiq bilan.
"""
from __future__ import annotations

import hashlib
import re
import secrets as _secrets
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import net
from .secrets import get_secret
from .security import contains_secret, redact

API = "https://api.telegram.org"
LEVELS = "ABCDE"
EVENTS = {
    "startup": "JARVIS ishga tushganda", "error": "Tizim va agent xatolari", "api": "API/xizmat ishlamay qolganda",
    "instagram": "Instagram ulanishi va nashrlar", "telegram": "Telegram ulanishi", "task": "Vazifa boshlandi/tugadi/xato",
    "approval": "Tasdiqlash so'rovlari (tugmalar bilan)", "resources": "Kompyuter resurslari chegarada",
    "backup": "Zaxira nusxa xatolari", "security": "Xavfsizlik hodisalari", "code": "Kod o'zgarishlari", "pos": "POS hisobotlari",
}
INFO_EVENTS = {"startup", "task", "approval", "instagram", "code"}   # bular 'info' darajasida ham yuboriladi
HELP = ("JARVIS buyruqlari:\n"
        "/status — tizim holati\n/tasks — vazifalar\n/agents — agentlar\n/approvals — kutilayotgan tasdiqlar\n"
        "/approve ID — tasdiqlash\n/reject ID — rad etish\n/report — umumiy hisobot\n/voice — ovozli hisobot\n"
        "/stop — avtomatik jarayonlarni to'xtatish\n/errors — oxirgi xatolar\n/memory so'z — xotiradan qidirish\n/help — yordam\n\n"
        "Oddiy matn — JARVIS'ga topshiriq. Masalan: «Instagram'ga Reels tayyorla: https://.../video.mp4 mavzu: chegirma»")
ALIASES = {"/holat": "/status", "/vazifalar": "/tasks", "/agentlar": "/agents", "/tasdiqlar": "/approvals",
           "/xatolar": "/errors", "/xotira": "/memory", "/yordam": "/help", "/hisobot": "/report", "/ovoz": "/voice"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS telegram_owner (
    id INTEGER PRIMARY KEY CHECK (id = 1), user_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, username TEXT, first_name TEXT,
    phone TEXT, phone_verified INTEGER NOT NULL DEFAULT 0, token_fp TEXT NOT NULL, paired_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS telegram_pairing (
    id INTEGER PRIMARY KEY AUTOINCREMENT, code_hash TEXT NOT NULL, expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS telegram_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), direction TEXT NOT NULL,
    kind TEXT NOT NULL, text TEXT
);
CREATE TABLE IF NOT EXISTS telegram_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, approval_id INTEGER NOT NULL, nonce TEXT NOT NULL, payload_hash TEXT NOT NULL,
    message_id INTEGER, expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0, outcome TEXT, decided_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS telegram_voice_cmds (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nonce TEXT NOT NULL, text TEXT NOT NULL, expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
"""


class TelegramError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


class TelegramAssistant:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.offset = 0
        self.last_error: str | None = None
        self.last_command: str | None = None
        self.connected: bool | None = None
        self.bot: dict = {}
        self._pending_owner: dict | None = None     # kod to'g'ri, telefon tasdig'i kutilmoqda
        self._bad_codes: list[float] = []
        self._warned: set = set()

    # ---------------- token va egalik ----------------
    def token(self) -> str | None:
        return get_secret("telegram_bot_token")

    def _token_fp(self) -> str:
        t = self.token() or ""
        return hashlib.sha256(("jarvis-tg:" + t).encode()).hexdigest()[:24]

    def owner(self) -> dict | None:
        o = self.core.db.one("SELECT * FROM telegram_owner WHERE id=1")
        if not o:
            return None
        o["token_matches"] = o["token_fp"] == self._token_fp()
        o["phone_required"] = bool(_digits(self.core.settings.telegram_owner_phone))
        o["active"] = o["token_matches"] and (o["phone_verified"] or not o["phone_required"])
        return o

    def configured(self) -> bool:
        o = self.owner()
        return bool(self.token()) and bool(o and o["active"])

    def _is_owner(self, user_id, chat_id, chat_type: str = "private") -> bool:
        o = self.owner()
        return bool(o and o["active"] and chat_type == "private" and user_id == o["user_id"] and chat_id == o["chat_id"])

    def pairing_start(self) -> dict:
        """Dashboard'dan: bir martalik ulash kodi. Kod faqat xeshi bilan saqlanadi."""
        if not self.token():
            raise TelegramError("Avval bot tokenini kiriting")
        code = f"{_secrets.randbelow(10**6):06d}"
        exp = _now() + timedelta(minutes=10)
        self.core.db.execute("UPDATE telegram_pairing SET used=1 WHERE used=0")
        self.core.db.execute("INSERT INTO telegram_pairing(code_hash, expires_at) VALUES (?,?)",
                             (hashlib.sha256(code.encode()).hexdigest(), exp.isoformat()))
        self._pending_owner = None
        self.core.audit.log("telegram_agent", "Telegram ulash kodi yaratildi", target="telegram", risk="C", approval_status="user_action")
        username = self.bot.get("username") or self._bot_info().get("username")
        return {"code": code, "expires_at": exp.isoformat(), "bot_username": username,
                "link": f"https://t.me/{username}?start={code}" if username else None}

    def _check_code(self, code: str) -> bool:
        now = time.time()
        self._bad_codes = [t for t in self._bad_codes if now - t < 3600]
        if len(self._bad_codes) >= 5:
            return False                              # soatiga 5 ta noto'g'ri urinishdan keyin ulash yopiladi
        row = self.core.db.one("SELECT * FROM telegram_pairing WHERE used=0 ORDER BY id DESC LIMIT 1")
        ok = bool(row and code and _now() < datetime.fromisoformat(row["expires_at"])
                  and _secrets.compare_digest(hashlib.sha256(code.encode()).hexdigest(), row["code_hash"]))
        if ok:
            self.core.db.execute("UPDATE telegram_pairing SET used=1 WHERE id=?", (row["id"],))
        else:
            self._bad_codes.append(now)
        return ok

    def _bind_owner(self, frm: dict, chat_id: int, phone: str = "", verified: bool = False):
        self.core.db.execute("DELETE FROM telegram_owner")
        self.core.db.execute("INSERT INTO telegram_owner(id, user_id, chat_id, username, first_name, phone, phone_verified, token_fp, paired_at)"
                             " VALUES (1,?,?,?,?,?,?,?,?)", (frm["id"], chat_id, frm.get("username"), frm.get("first_name"),
                                                             phone, int(verified), self._token_fp(), _now().isoformat()))
        self.core.audit.log("telegram_agent", "Telegram egasi ulandi", target=f"tg_user:{frm['id']}", risk="D", approval_status="user_action")
        self.core.notifier.notify("Telegram ulandi", f"Egasi: {frm.get('first_name') or ''} @{frm.get('username') or '-'}",
                                  severity="info", category="security")

    def revoke(self, reason: str = "foydalanuvchi bekor qildi") -> dict:
        had = self.core.db.one("SELECT user_id FROM telegram_owner WHERE id=1")
        self.core.db.execute("DELETE FROM telegram_owner")
        self.core.db.execute("UPDATE telegram_pairing SET used=1 WHERE used=0")
        self.core.db.execute("UPDATE telegram_approvals SET used=1, outcome='revoked' WHERE used=0")
        self._pending_owner = None
        if had:
            self.core.audit.log("telegram_agent", f"Telegram egaligi bekor qilindi: {reason}", target="telegram", risk="D",
                                approval_status="user_action")
        return self.status()

    def on_token_changed(self):
        """Token almashsa: bot to'xtaydi, eski egalik va tugmalar bekor bo'ladi."""
        self.stop()
        self.offset, self.bot, self.connected = 0, {}, None
        self.revoke("bot tokeni almashtirildi")

    # ---------------- holat ----------------
    def _bot_info(self) -> dict:
        if not self.token():
            return {}
        try:
            self.bot = self._call("getMe")["result"]
        except TelegramError as e:
            self.last_error = str(e)
        return self.bot

    def status(self) -> dict:
        o = self.owner()
        last_out = self.core.db.one("SELECT ts, text FROM telegram_messages WHERE direction='out' ORDER BY id DESC LIMIT 1")
        return {"token_set": bool(self.token()), "running": bool(self._thread and self._thread.is_alive()),
                "connected": self.connected, "bot": {k: self.bot.get(k) for k in ("username", "first_name")} if self.bot else None,
                "owner": ({k: o[k] for k in ("user_id", "chat_id", "username", "first_name", "phone", "phone_verified",
                                             "paired_at", "token_matches", "active", "phone_required")} if o else None),
                "expected_phone": self.core.settings.telegram_owner_phone, "pairing_waiting_phone": bool(self._pending_owner),
                "configured": self.configured(), "last_error": self.last_error, "last_command": self.last_command,
                "last_sent": last_out, "events": EVENTS, "enabled_events": self.core.settings.telegram_events,
                "voice_alerts": self.core.settings.telegram_voice_alerts, "approvals": self.core.settings.telegram_approvals,
                "approval_ttl_min": self.core.settings.telegram_approval_ttl_min,
                "approval_max_level": self.core.settings.telegram_approval_max_level,
                "voice": {"tts": bool(shutil.which("espeak-ng") or shutil.which("espeak")), "ffmpeg": bool(shutil.which("ffmpeg")),
                          "stt_loaded": getattr(self.core.voice, "_model", None) is not None},
                "calls": "Telegram Bot API qo'ng'iroq qila olmaydi. Qo'ng'iroq uchun Bildirishnomalar → Twilio (alohida, pullik, tasdiq bilan)."}

    def history(self, limit: int = 100) -> dict:
        return {"messages": self.core.db.query("SELECT * FROM telegram_messages ORDER BY id DESC LIMIT ?", (limit,)),
                "approvals": self.core.db.query(
                    "SELECT t.*, a.summary, a.level, a.status AS approval_status FROM telegram_approvals t "
                    "LEFT JOIN approvals a ON a.id=t.approval_id ORDER BY t.id DESC LIMIT ?", (limit,)),
                "errors": self.core.db.query("SELECT ts, message FROM errors WHERE module='telegram_agent' ORDER BY id DESC LIMIT 30")}

    def _log(self, direction: str, kind: str, text: str):
        self.core.db.execute("INSERT INTO telegram_messages(direction, kind, text) VALUES (?,?,?)",
                             (direction, kind, redact(text or "")[:500]))

    # ---------------- Bot API ----------------
    def _call(self, method: str, **params) -> dict:
        token = self.token()
        if not token:
            raise TelegramError("Bot tokeni kiritilmagan (dashboard → Telegram)")
        try:
            res = net.post_json(f"{API}/bot{token}/{method}", json_body=params, timeout=params.get("timeout", 0) + 15)
        except net.NetError as e:
            raise TelegramError(redact(f"Telegram API xatosi: {e} {e.body[:200]}").replace(token, "***")) from None
        if not res.get("ok"):
            raise TelegramError(redact(f"Telegram: {res.get('description', 'nomalum xato')}"))
        return res

    def send(self, chat_id: int, text: str, buttons: list[list[dict]] | None = None, reply_markup: dict | None = None) -> dict:
        params = {"chat_id": chat_id, "text": redact(text)[:4000]}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        elif reply_markup:
            params["reply_markup"] = reply_markup
        res = self._call("sendMessage", **params)
        self._log("out", "text", params["text"])
        return res.get("result", {})

    def send_owner(self, text: str, buttons=None) -> dict | None:
        o = self.owner()
        if not (o and o["active"] and self.token()):
            return None
        return self.send(o["chat_id"], text, buttons)

    def broadcast(self, text: str) -> int:
        """Eski nom (moslik uchun): faqat egasiga yuboradi."""
        try:
            return 1 if self.send_owner(text) is not None else 0
        except TelegramError as e:
            self.last_error = str(e)
            return 0

    def send_voice(self, text: str, chat_id: int | None = None) -> dict:
        """Matnni o'zbekcha ovozga aylantirib, Telegram ovozli xabari sifatida yuboradi."""
        o = self.owner()
        chat_id = chat_id or (o["chat_id"] if o and o["active"] else None)
        if not chat_id:
            raise TelegramError("Telegram egasi ulanmagan")
        wav = Path(self.core.voice.synthesize(text[:1500])["output"])
        ffmpeg = shutil.which("ffmpeg")
        try:
            if ffmpeg:
                ogg = wav.with_suffix(".ogg")
                subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libopus", "-b:a", "32k", str(ogg)],
                               capture_output=True, timeout=120, check=True)
                method, field, name, mime, data = "sendVoice", "voice", "jarvis.ogg", "audio/ogg", ogg.read_bytes()
                ogg.unlink(missing_ok=True)
            else:
                method, field, name, mime, data = "sendAudio", "audio", "jarvis.wav", "audio/wav", wav.read_bytes()
        finally:
            wav.unlink(missing_ok=True)
        try:
            res = net.post_multipart(f"{API}/bot{self.token()}/{method}", {"chat_id": chat_id}, {field: (name, data, mime)}, timeout=120)
        except net.NetError as e:
            raise TelegramError(f"Ovozli xabar yuborilmadi: HTTP {e.status}") from None
        self._log("out", "voice", text)
        return res

    # ---------------- bildirishnomalar ----------------
    def wants(self, category: str, severity: str) -> bool:
        s = self.core.settings
        return (s.telegram_notify and category in s.telegram_events and (severity != "info" or category in INFO_EVENTS)
                and self.configured())

    def event(self, category: str, title: str, body: str = "", severity: str = "info") -> bool:
        if not self.wants(category, severity):
            return False
        icon = {"critical": "🔴", "warning": "🟡"}.get(severity, "🔵")
        try:
            self.send_owner(f"{icon} JARVIS: {title}" + (f"\n{body}" if body else ""))
            if severity == "critical" and self.core.settings.telegram_voice_alerts:
                try:
                    self.send_voice(f"Diqqat. {title}. {body}"[:600])
                except Exception as e:  # ovoz bo'lmasa ham matn yetib borgan
                    self.last_error = redact(str(e))
            return True
        except TelegramError as e:
            self.last_error = str(e)
            return False

    # ---------------- Telegram orqali tasdiqlash ----------------
    def on_approval_pending(self, appr: dict) -> None:
        s = self.core.settings
        if not (s.telegram_approvals and "approval" in s.telegram_events and self.configured()):
            return
        allowed = LEVELS.index(appr["level"]) <= LEVELS.index(s.telegram_approval_max_level if s.telegram_approval_max_level in LEVELS else "D")
        text = (f"🟣 JARVIS: Sizning ruxsatingiz kerak.\nAmal: {appr['summary']}\nTizim: {appr['target']}"
                + (f"\nAkkaunt: {appr['account']}" if appr.get("account") else "")
                + f"\nXavf darajasi: {appr['level']}" + (f" ({appr.get('risk')})" if appr.get("risk") else "")
                + f"\nTasdiq #{appr['id']} · versiya {appr['payload_hash'][:10]}")
        if not allowed:
            self.send_owner(text + "\n\nBu darajadagi amal faqat dashboardda tasdiqlanadi.")
            return
        nonce = _secrets.token_urlsafe(9)
        exp = _now() + timedelta(minutes=max(1, int(s.telegram_approval_ttl_min)))
        cur = self.core.db.execute("INSERT INTO telegram_approvals(approval_id, nonce, payload_hash, expires_at) VALUES (?,?,?,?)",
                                   (appr["id"], nonce, appr["payload_hash"], exp.isoformat()))
        msg = self.send_owner(text + f"\nMuddati: {exp.astimezone():%H:%M} gacha",
                              [[{"text": "✅ TASDIQLASH", "callback_data": f"a:{cur.lastrowid}:{nonce}:y"},
                                {"text": "❌ RAD ETISH", "callback_data": f"a:{cur.lastrowid}:{nonce}:n"}]])
        if msg:
            self.core.db.execute("UPDATE telegram_approvals SET message_id=? WHERE id=?", (msg.get("message_id"), cur.lastrowid))

    def _decide(self, row: dict, approve: bool) -> str:
        """Bitta Telegram tasdiq yozuvi bo'yicha qaror. Hamma tekshiruvlar shu yerda."""
        if row["used"]:
            return "Bu tugma allaqachon ishlatilgan."
        if _now() >= datetime.fromisoformat(row["expires_at"]):
            self.core.db.execute("UPDATE telegram_approvals SET used=1, outcome='expired' WHERE id=?", (row["id"],))
            return "Tasdiqlash muddati o'tgan. Dashboardda yoki yangi so'rov bilan qayta urinib ko'ring."
        appr = self.core.approvals.get(row["approval_id"])
        max_level = self.core.settings.telegram_approval_max_level if self.core.settings.telegram_approval_max_level in LEVELS else "D"
        if LEVELS.index(appr["level"]) > LEVELS.index(max_level):
            return "Bu darajadagi amal faqat dashboardda tasdiqlanadi."
        self.core.db.execute("UPDATE telegram_approvals SET used=1, decided_at=? WHERE id=?", (_now().isoformat(), row["id"]))
        try:
            # Qaror aynan Telegram'ga yuborilgan versiya xeshi bilan: payload o'zgargan bo'lsa — rad
            res = self.core.approvals.decide(appr["id"], approve, row["payload_hash"])
        except Exception as e:
            self.core.db.execute("UPDATE telegram_approvals SET outcome=? WHERE id=?", (f"error: {e}"[:200], row["id"]))
            return f"Qabul qilinmadi: {e}"
        self.core.db.execute("UPDATE telegram_approvals SET outcome=? WHERE id=?", (res["status"], row["id"]))
        self.core.audit.log("telegram_agent", f"Telegram orqali qaror: {res['status']} — {appr['summary'][:80]}",
                            target=f"approval#{appr['id']}", risk=appr["level"], approval_status=res["status"])
        if not approve:
            return f"❌ Rad etildi: {appr['summary']}\nAmal bajarilmaydi."
        out = f"✅ Tasdiqlandi: {appr['summary']}"
        if self.core.settings.telegram_execute_after_approval:
            ex = self.core.execute_approved(appr["id"])
            if ex:
                out += "\n\n" + ex
        return out

    def _approval_by_id(self, approval_id: int) -> dict | None:
        return self.core.db.one("SELECT * FROM telegram_approvals WHERE approval_id=? AND used=0 ORDER BY id DESC LIMIT 1",
                                (approval_id,))

    # ---------------- qabul qilish ----------------
    def handle_update(self, upd: dict) -> str | None:
        if "callback_query" in upd:
            return self._handle_callback(upd["callback_query"])
        msg = upd.get("message")
        if not msg:
            return None
        frm, chat = msg.get("from") or {}, msg.get("chat") or {}
        uid, chat_id, ctype = frm.get("id"), chat.get("id"), chat.get("type", "private")
        text = (msg.get("text") or "").strip()
        if ctype != "private":
            self.core.audit.log("telegram_agent", "Guruh/kanal xabari e'tiborsiz qoldirildi", target=f"tg_chat:{chat_id}", risk="A",
                                approval_status="denied")
            return None
        # --- ulash jarayoni (ega hali yo'q) ---
        if not self.owner() or not self.owner()["token_matches"]:
            return self._pairing_message(frm, chat_id, text, msg.get("contact"))
        o = self.owner()
        if not o["active"] and uid == o["user_id"] and msg.get("contact"):
            return self._verify_contact(frm, chat_id, msg["contact"])
        if not self._is_owner(uid, chat_id, ctype):
            # Begona: javob yo'q, ma'lumot yo'q. Faqat audit (va birinchi marta xavfsizlik bildirishnomasi).
            self.core.audit.log("telegram_agent", "Ruxsatsiz foydalanuvchi xabari rad etildi", target=f"tg_user:{uid}", risk="A",
                                approval_status="denied")
            if uid not in self._warned:
                self._warned.add(uid)
                self.core.notifier.notify("Telegram: begona foydalanuvchi botga yozdi", f"ID {uid}. Javob berilmadi.",
                                          severity="warning", category="security")
            return None
        if msg.get("voice") or msg.get("audio"):
            return self._handle_voice(chat_id, msg.get("voice") or msg.get("audio"))
        if not text:
            return None
        self._log("in", "text", text)
        self.last_command = text[:100]
        reply = self.command(text)
        if reply:
            self.send(chat_id, reply)
        self.core.audit.log("telegram_agent", f"Buyruq: {redact(text)[:60]}", target=f"tg_user:{uid}", risk="A")
        return reply

    def _pairing_message(self, frm: dict, chat_id: int, text: str, contact: dict | None) -> str | None:
        if contact and self._pending_owner and frm.get("id") == self._pending_owner["frm"]["id"]:
            return self._verify_contact(frm, chat_id, contact)
        m = re.match(r"^/start(?:@\w+)?\s+(\d{6})$", text)
        if not m:
            self.core.audit.log("telegram_agent", "Ulanmagan botga xabar (kodsiz) e'tiborsiz qoldirildi", target=f"tg_user:{frm.get('id')}",
                                risk="A", approval_status="denied")
            return None
        if not self._check_code(m.group(1)):
            self.core.audit.log("telegram_agent", "Noto'g'ri yoki eskirgan ulash kodi", target=f"tg_user:{frm.get('id')}", risk="C",
                                approval_status="denied")
            return None
        if _digits(self.core.settings.telegram_owner_phone):
            self._pending_owner = {"frm": frm, "chat_id": chat_id, "until": time.time() + 600}
            self.send(chat_id, "Kod to'g'ri. Endi telefon raqamingizni tasdiqlang — pastdagi tugmani bosing.",
                      reply_markup={"keyboard": [[{"text": "📱 Raqamni tasdiqlash", "request_contact": True}]],
                                    "one_time_keyboard": True, "resize_keyboard": True})
            return "contact_requested"
        self._bind_owner(frm, chat_id)
        self.send(chat_id, "✅ Ulandi. JARVIS endi faqat shu akkaunt bilan ishlaydi.\n\n" + HELP)
        return "paired"

    def _verify_contact(self, frm: dict, chat_id: int, contact: dict) -> str | None:
        expected = _digits(self.core.settings.telegram_owner_phone)
        phone = _digits(contact.get("phone_number"))
        own = contact.get("user_id") == frm.get("id")
        match = bool(expected) and (phone.endswith(expected[-9:]) if len(expected) >= 9 else phone == expected)
        if not own or not match:
            self.core.audit.log("telegram_agent", "Telefon tasdig'i rad etildi" + ("" if own else " (boshqa odam kontakti)"),
                                target=f"tg_user:{frm.get('id')}", risk="C", approval_status="denied")
            self.send(chat_id, "Raqam mos kelmadi. Dashboardda yangi ulash kodini oling.", reply_markup={"remove_keyboard": True})
            self._pending_owner = None
            return "phone_rejected"
        if self._pending_owner and self._pending_owner["frm"]["id"] == frm.get("id") and time.time() < self._pending_owner["until"]:
            self._bind_owner(frm, chat_id, "+" + phone, verified=True)
        elif self.owner() and self.owner()["user_id"] == frm.get("id"):
            self.core.db.execute("UPDATE telegram_owner SET phone=?, phone_verified=1 WHERE id=1", ("+" + phone,))
        else:
            return None
        self._pending_owner = None
        self.send(chat_id, "✅ Raqam tasdiqlandi. JARVIS endi faqat shu akkaunt bilan ishlaydi.", reply_markup={"remove_keyboard": True})
        self.send(chat_id, HELP)
        return "paired"

    def _handle_callback(self, cq: dict) -> str | None:
        frm, msg = cq.get("from") or {}, cq.get("message") or {}
        chat = msg.get("chat") or {}
        if not self._is_owner(frm.get("id"), chat.get("id"), chat.get("type", "private")):
            self.core.audit.log("telegram_agent", "Begona tugma bosishi rad etildi", target=f"tg_user:{frm.get('id')}", risk="C",
                                approval_status="denied")
            try:
                self._call("answerCallbackQuery", callback_query_id=cq.get("id"), text="Ruxsat yo'q")
            except TelegramError:
                pass
            return None
        data = cq.get("data") or ""
        result = "Noma'lum tugma."
        m = re.match(r"^a:(\d+):([\w-]+):([yn])$", data)
        v = re.match(r"^v:(\d+):([\w-]+):([yn])$", data)
        if m:
            row = self.core.db.one("SELECT * FROM telegram_approvals WHERE id=?", (int(m.group(1)),))
            if row and _secrets.compare_digest(row["nonce"], m.group(2)):
                result = self._decide(row, m.group(3) == "y")
            else:
                result = "Tugma yaroqsiz."
        elif v:
            result = self._voice_decide(int(v.group(1)), v.group(2), v.group(3) == "y", chat.get("id"))
        self._log("in", "button", data[:40])
        try:
            self._call("answerCallbackQuery", callback_query_id=cq.get("id"), text=result[:180])
            if msg.get("message_id"):
                self._call("editMessageText", chat_id=chat.get("id"), message_id=msg["message_id"],
                           text=redact((msg.get("text") or "") + "\n\n" + result)[:4000])
        except TelegramError as e:
            self.last_error = str(e)
        return result

    # ---------------- ovozli buyruqlar ----------------
    def _handle_voice(self, chat_id: int, voice: dict) -> str:
        if getattr(self.core.voice, "_model", None) is None:
            self.send(chat_id, "Ovozni matnga aylantirish yoqilmagan. Dashboard → Voice bo'limida Whisper modelini yuklang.")
            return "stt_unavailable"
        try:
            f = self._call("getFile", file_id=voice["file_id"])["result"]
            data = net.get_bytes(f"{API}/file/bot{self.token()}/{f['file_path']}", max_bytes=20 * 2**20)
        except (TelegramError, net.NetError) as e:
            self.send(chat_id, f"Ovozli xabarni yuklab bo'lmadi: {e}")
            return "download_failed"
        tmp = Path(tempfile.mkdtemp(prefix="jarvis_tg_voice_")) / "voice.ogg"
        tmp.write_bytes(data)
        try:
            text = self.core.voice.transcribe(str(tmp))["text"].strip()
        except Exception as e:
            self.send(chat_id, f"Ovozni tanib bo'lmadi: {e}")
            return "stt_failed"
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)
        self._log("in", "voice", text)
        if not text:
            self.send(chat_id, "Ovozdan matn chiqmadi.")
            return "empty"
        nonce = _secrets.token_urlsafe(9)
        cur = self.core.db.execute("INSERT INTO telegram_voice_cmds(nonce, text, expires_at) VALUES (?,?,?)",
                                   (nonce, redact(text)[:1000], (_now() + timedelta(minutes=10)).isoformat()))
        self.send(chat_id, f"🎙 Tushundim: «{text[:500]}»\nShu buyruqni bajaraymi?",
                  [[{"text": "✅ Ha, bajar", "callback_data": f"v:{cur.lastrowid}:{nonce}:y"},
                    {"text": "❌ Yo'q", "callback_data": f"v:{cur.lastrowid}:{nonce}:n"}]])
        return "voice_confirm"

    def _voice_decide(self, vid: int, nonce: str, yes: bool, chat_id: int) -> str:
        row = self.core.db.one("SELECT * FROM telegram_voice_cmds WHERE id=?", (vid,))
        if not row or not _secrets.compare_digest(row["nonce"], nonce) or row["used"]:
            return "Tugma yaroqsiz yoki ishlatilgan."
        self.core.db.execute("UPDATE telegram_voice_cmds SET used=1 WHERE id=?", (vid,))
        if _now() >= datetime.fromisoformat(row["expires_at"]):
            return "Muddati o'tgan."
        if not yes:
            return "Bekor qilindi."
        reply = self.command(row["text"])
        self.send(chat_id, reply)
        return "Bajarildi."

    # ---------------- buyruqlar ----------------
    def command(self, text: str) -> str:
        c = self.core
        cmd, _, arg = text.partition(" ")
        cmd = ALIASES.get(cmd.lower().split("@")[0], cmd.lower().split("@")[0])
        arg = arg.strip()
        if cmd in ("/start", "/help"):
            return HELP
        if cmd == "/status":
            return self.status_text()
        if cmd == "/agents":
            return "\n".join(f"{'🟢' if a.status == 'idle' else '🔵' if a.status == 'running' else '🔴' if a.status == 'error' else '⚪'} "
                             f"{a.title}: {a.status}" for a in c.agents.agents.values())
        if cmd == "/tasks":
            ts = c.agents.tasks(10)
            return "\n".join(f"#{t['id']} {t['title']} — {t['status']}" for t in ts) or "Vazifalar yo'q"
        if cmd == "/approvals":
            ps = c.approvals.list("pending")
            return "\n\n".join(f"#{a['id']} [{a['level']}] {a['summary']}" for a in ps[:10]) + "\n\n/approve ID yoki /reject ID" if ps else "Kutilayotgan tasdiq yo'q"
        if cmd in ("/approve", "/reject"):
            if not arg.isdigit():
                return f"Ishlatish: {cmd} ID"
            row = self._approval_by_id(int(arg))
            if not row:
                return "Bu tasdiq uchun Telegram so'rovi yo'q yoki allaqachon hal qilingan (yoki faqat dashboardda tasdiqlanadi)."
            return self._decide(row, cmd == "/approve")
        if cmd == "/errors":
            es = c.audit.recent_errors(5)
            return "\n".join(f"{e['ts']} {e['module']}: {e['message']}" for e in es) or "Xato yo'q"
        if cmd == "/memory":
            hits = c.memory.search(arg, 5) if arg else []
            return "\n".join(f"#{h['id']} {h['content']}" for h in hits) or "Topilmadi"
        if cmd == "/report":
            return self.report_text()
        if cmd == "/voice":
            try:
                self.send_voice(self.status_text().replace("JARVIS:", "JARVIS hisoboti."))
                return "🎙 Ovozli hisobot yuborildi."
            except Exception as e:
                return f"Ovozli hisobot yuborilmadi: {e}"
        if cmd == "/stop":
            return c.stop_automation(source="telegram")
        if cmd.startswith("/"):
            return "Noma'lum buyruq. /help"
        if re.search(r"(?i)instagram", text) and re.search(r"(?i)\b(reels?|post|stor(y|ies))\b", text) and re.search(r"(?i)(tayyorla|joyla)", text):
            return self.instagram_prepare(text)
        return c.chat(text)["text"]

    def status_text(self) -> str:
        c = self.core
        agents = [a for a in c.agents.agents.values() if getattr(a, "implemented", True)]
        busy = sum(1 for a in agents if a.status == "running")
        pend = len(c.approvals.list("pending"))
        errs = c.db.one("SELECT COUNT(*) n FROM errors WHERE ts >= datetime('now','-1 day')")["n"]
        ai = c.ai.name if hasattr(c.ai, "name") else "?"
        return (f"JARVIS: Tizim holati.\nHolat: Online\nAgentlar: {len(agents)} ta faol ({busy} ta ishlayapti)\n"
                f"AI: {ai}\nKutilayotgan tasdiqlar: {pend}\nSo'nggi 24 soatdagi xatolar: {errs}")

    def report_text(self) -> str:
        c = self.core
        tasks = c.db.query("SELECT status, COUNT(*) n FROM tasks WHERE created_at >= datetime('now','-1 day') GROUP BY status")
        ig = c.db.query("SELECT status, COUNT(*) n FROM ig_posts GROUP BY status") if c.db.one(
            "SELECT 1 FROM sqlite_master WHERE name='ig_posts'") else []
        return (self.status_text() + "\n\nVazifalar (24 soat): " + (", ".join(f"{t['status']}: {t['n']}" for t in tasks) or "yo'q")
                + "\nInstagram postlari: " + (", ".join(f"{r['status']}: {r['n']}" for r in ig) or "yo'q"))

    def instagram_prepare(self, text: str) -> str:
        """Telegram'dan: «Instagram'ga Reels tayyorla ...» → loyiha → tekshiruv → tasdiq tugmalari."""
        c = self.core
        accs = c.settings.instagram_accounts
        if not accs:
            return "Instagram akkaunti ulanmagan. Dashboard → Instagram → yo'riqnoma."
        acc = next((a["name"] for a in accs if a["name"].lower() in text.lower()), accs[0]["name"])
        kind = "reel" if re.search(r"(?i)reels?", text) else "story" if re.search(r"(?i)stor", text) else "post"
        url = (re.search(r"https://\S+", text) or [None])[0] if re.search(r"https://\S+", text) else ""
        topic = re.sub(r"https://\S+", "", text)
        from .instagram import suggest_hashtags
        caption = ""
        if getattr(c.ai, "name", "offline") != "offline":
            try:
                r = c.ai.route([{"role": "user", "content": "Instagram uchun qisqa, jozibali o'zbekcha caption yoz (2-4 jumla, emoji mumkin, "
                                 f"hashtagsiz). Mavzu (foydalanuvchi so'rovi):\n<untrusted>{topic[:800]}</untrusted>"}], purpose="text")
                caption = r["text"].strip()[:1500]
            except Exception:
                caption = ""
        if not caption or contains_secret(caption):
            caption = re.sub(r"(?i)instagram\S*|reels?|post|stor(y|ies)|tayyorla\S*|joyla\S*|sahifam\S*|bugun", "", topic).strip(" :,.-") or "Yangi kontent"
        tags = suggest_hashtags(topic)
        try:
            draft = c.instagram.draft(acc, kind, caption, url, hashtags=tags)
        except Exception as e:
            return f"Loyiha yaratilmadi: {e}"
        pv = c.instagram.preview(draft["id"])
        head = f"📝 Instagram loyihasi #{draft['id']} (@{acc}, {kind})\n\n{draft['caption'][:900]}"
        if not pv["ready"]:
            return head + "\n\nHali joylab bo'lmaydi: " + "; ".join(pv["issues"]) + \
                "\nMedia uchun ommaviy https:// havola bilan qayta yozing (Instagram API talabi)."
        try:
            c.instagram.request_publish(draft["id"])
        except Exception as e:
            return head + f"\n\nTasdiq so'rovi yaratilmadi: {e}"
        return head + "\n\nTasdiqlash tugmalari alohida xabarda. Tasdiqlamaguningizcha hech narsa joylanmaydi."

    # ---------------- polling ----------------
    def poll_once(self, timeout: int = 25) -> int:
        res = self._call("getUpdates", offset=self.offset, timeout=timeout, allowed_updates=["message", "callback_query"])
        updates = res.get("result", [])
        for u in updates:
            self.offset = max(self.offset, u["update_id"] + 1)
            try:
                self.handle_update(u)
            except Exception as e:  # bitta xabar xatosi pollingni to'xtatmasin
                self.last_error = redact(str(e))
                self.core.audit.error("telegram_agent", str(e))
        return len(updates)

    def start(self) -> dict:
        if not self.token():
            raise TelegramError("Bot tokeni kiritilmagan")
        if self._thread and self._thread.is_alive():
            return self.status()
        self._bot_info()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.core.audit.log("telegram_agent", "Telegram bot ishga tushirildi", target="telegram", risk="C", approval_status="user_action")
        return self.status()

    def stop(self) -> dict:
        self._stop.set()
        return self.status()

    def _set_connected(self, ok: bool, err: str = ""):
        if self.connected is True and not ok:
            # Telegram uzildi — Telegram orqali aytib bo'lmaydi, dashboard bildirishnomasi
            self.core.notifier.notify("Telegram ulanishi uzildi", err[:300], severity="warning", category="telegram")
        if self.connected is False and ok:
            self.event("telegram", "Telegram ulanishi tiklandi", severity="info")
        self.connected = ok

    def _loop(self):
        delay = 2
        while not self._stop.is_set():
            try:
                self.poll_once()
                delay, self.last_error = 2, None
                self._set_connected(True)
            except TelegramError as e:
                self.last_error = str(e)
                self.core.audit.error("telegram_agent", str(e))
                self._set_connected(False, str(e))
                self._stop.wait(delay)
                delay = min(delay * 2, 300)
            time.sleep(0.2)

