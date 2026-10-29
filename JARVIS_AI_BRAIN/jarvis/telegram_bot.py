"""Telegram Assistant (rasmiy Bot API, long polling).

* Token faqat secret storage'da: `python scripts/set_secret.py telegram_bot_token`.
* Buyruqlar faqat settings.json dagi `telegram_allowed_ids` ro'yxatidagi foydalanuvchilardan qabul qilinadi.
  Boshqalarga javob berilmaydi, urinish audit va xavfsizlik bildirishnomasiga yoziladi.
* Tasdiqlashlar Telegram'da faqat ko'rsatiladi; qaror dashboardda (aniq versiya xeshi bilan) qabul qilinadi.
* Bot URL'i token saqlaydi — u hech qachon logga yozilmaydi.
"""
from __future__ import annotations

import threading
import time

from . import net
from .secrets import get_secret
from .security import redact

API = "https://api.telegram.org"
HELP = ("JARVIS buyruqlari:\n/holat — tizim holati\n/agentlar — agentlar\n/vazifalar — oxirgi vazifalar\n"
        "/tasdiqlar — kutilayotgan tasdiqlar\n/xatolar — oxirgi xatolar\n/xotira <so'z> — xotiradan qidirish\n"
        "Oddiy matn — JARVIS chatiga yuboriladi.")


class TelegramError(Exception):
    pass


class TelegramAssistant:
    def __init__(self, core):
        self.core = core
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.offset = 0
        self.last_error: str | None = None
        self._warned: set[int] = set()

    # --- holat ---
    def token(self) -> str | None:
        return get_secret("telegram_bot_token")

    def configured(self) -> bool:
        return bool(self.token()) and bool(self.core.settings.telegram_allowed_ids)

    def status(self) -> dict:
        return {"token_set": bool(self.token()), "allowed_ids": len(self.core.settings.telegram_allowed_ids),
                "running": bool(self._thread and self._thread.is_alive()), "last_error": self.last_error,
                "configured": self.configured()}

    def _call(self, method: str, **params) -> dict:
        token = self.token()
        if not token:
            raise TelegramError("Bot tokeni o'rnatilmagan (scripts/set_secret.py telegram_bot_token)")
        try:
            res = net.post_json(f"{API}/bot{token}/{method}", json_body=params, timeout=params.get("timeout", 0) + 15)
        except net.NetError as e:
            raise TelegramError(redact(f"Telegram API xatosi: {e} {e.body[:200]}")) from None
        if not res.get("ok"):
            raise TelegramError(redact(f"Telegram: {res.get('description', 'nomalum xato')}"))
        return res

    # --- yuborish ---
    def send(self, chat_id: int, text: str) -> None:
        self._call("sendMessage", chat_id=chat_id, text=redact(text)[:4000])

    def broadcast(self, text: str) -> int:
        """Bildirishnoma faqat sizning (ruxsat berilgan) IDlaringizga — bu oldindan belgilangan ruxsat doirasi."""
        sent = 0
        for cid in self.core.settings.telegram_allowed_ids:
            try:
                self.send(cid, text)
                sent += 1
            except TelegramError as e:
                self.last_error = str(e)
        return sent

    # --- qabul qilish ---
    def handle_update(self, upd: dict) -> str | None:
        msg = upd.get("message") or upd.get("edited_message")
        if not msg or "text" not in msg:
            return None
        uid, chat_id, text = msg.get("from", {}).get("id"), msg["chat"]["id"], msg["text"].strip()
        if uid not in self.core.settings.telegram_allowed_ids:
            self.core.audit.log("telegram_agent", "Ruxsatsiz foydalanuvchidan xabar rad etildi", target=f"tg_user:{uid}",
                                risk="A", approval_status="denied")
            if uid not in self._warned:
                self._warned.add(uid)
                self.core.notifier.notify("Telegram: ruxsatsiz urinish", f"Foydalanuvchi ID {uid} botga yozdi",
                                          severity="warning", category="security")
            return None
        reply = self.command(text)
        self.send(chat_id, reply)
        self.core.audit.log("telegram_agent", f"Buyruq: {text[:60]}", target=f"tg_user:{uid}", risk="A")
        return reply

    def command(self, text: str) -> str:
        c = self.core
        cmd, _, arg = text.partition(" ")
        cmd = cmd.lower().split("@")[0]
        if cmd in ("/start", "/yordam", "/help"):
            return HELP
        if cmd == "/holat":
            return c.chat("holat")["text"]
        if cmd == "/agentlar":
            return "\n".join(f"{'🟢' if a.status == 'idle' else '🔵' if a.status == 'running' else '🔴' if a.status == 'error' else '⚪'} "
                             f"{a.title}: {a.status}" for a in c.agents.agents.values())
        if cmd == "/vazifalar":
            ts = c.agents.tasks(10)
            return "\n".join(f"#{t['id']} {t['title']} — {t['status']}" for t in ts) or "Vazifalar yo'q"
        if cmd == "/tasdiqlar":
            ps = c.approvals.list("pending")
            if not ps:
                return "Kutilayotgan tasdiq yo'q"
            return "\n\n".join(f"#{a['id']} [{a['level']}] {a['summary']}\nTizim: {a['target']} · versiya {a['payload_hash'][:12]}"
                               for a in ps[:10]) + "\n\nTasdiqlash faqat dashboardda (aniq versiya bilan)."
        if cmd == "/xatolar":
            es = c.audit.recent_errors(5)
            return "\n".join(f"{e['ts']} {e['module']}: {e['message']}" for e in es) or "Xato yo'q"
        if cmd == "/xotira":
            hits = c.memory.search(arg, 5) if arg else []
            return "\n".join(f"#{h['id']} {h['content']}" for h in hits) or "Topilmadi"
        return c.chat(text)["text"]

    def poll_once(self, timeout: int = 25) -> int:
        res = self._call("getUpdates", offset=self.offset, timeout=timeout, allowed_updates=["message"])
        updates = res.get("result", [])
        for u in updates:
            self.offset = max(self.offset, u["update_id"] + 1)
            try:
                self.handle_update(u)
            except Exception as e:  # bitta xabar xatosi pollingni to'xtatmasin
                self.last_error = redact(str(e))
                self.core.audit.error("telegram_agent", str(e))
        return len(updates)

    # --- fon jarayoni ---
    def start(self) -> dict:
        if not self.configured():
            raise TelegramError("Token yoki telegram_allowed_ids sozlanmagan")
        if self._thread and self._thread.is_alive():
            return self.status()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.core.audit.log("telegram_agent", "Telegram bot ishga tushirildi", target="telegram", risk="C",
                            approval_status="user_action")
        return self.status()

    def stop(self) -> dict:
        self._stop.set()
        return self.status()

    def _loop(self):
        delay = 2
        while not self._stop.is_set():
            try:
                self.poll_once()
                delay, self.last_error = 2, None
            except TelegramError as e:
                self.last_error = str(e)
                self.core.audit.error("telegram_agent", str(e))
                self._stop.wait(delay)
                delay = min(delay * 2, 300)
            time.sleep(0.2)
