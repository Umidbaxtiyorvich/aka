"""Ichki hodisalar oqimi (3D Brain va Graph Explorer uchun real vaqt).

Modullar haqiqiy hodisalarni e'lon qiladi: AI so'rovi boshlandi/tugadi, xotiradan qidirildi, xotira qo'shildi,
vazifa boshlandi/tugadi, xato, tasdiq so'rovi, grafga aloqa qo'shildi. Dashboard ularni Server-Sent Events
(/api/events/stream) orqali oladi — qo'shimcha kutubxona (websockets) shart emas, uvicorn'ning o'zi yetadi.
Hodisalarda maxfiy ma'lumot bo'lmaydi: faqat turi, modul, id va qisqa (redaktsiya qilingan) yorliq.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from .security import redact

TYPES = {"ai.start", "ai.end", "memory.search", "memory.add", "task.start", "task.end", "error", "approval", "kg.link",
         "system"}


class EventBus:
    def __init__(self, maxlen: int = 1000):
        self._buf: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self.seq = 0
        self.muted = 0                 # >0 bo'lsa (masalan, grafni qayta qurishda) kg.link e'lon qilinmaydi
        self.active: dict[str, int] = {"ai": 0, "tasks": 0}

    def publish(self, type_: str, **data) -> int:
        if type_ not in TYPES or (type_ == "kg.link" and self.muted):
            return self.seq
        clean = {k: (redact(v)[:160] if isinstance(v, str) else v) for k, v in data.items()}
        with self._cond:
            if type_ == "ai.start":
                self.active["ai"] += 1
            elif type_ == "ai.end":
                self.active["ai"] = max(0, self.active["ai"] - 1)
            elif type_ == "task.start":
                self.active["tasks"] += 1
            elif type_ == "task.end":
                self.active["tasks"] = max(0, self.active["tasks"] - 1)
            self.seq += 1
            self._buf.append({"seq": self.seq, "ts": time.time(), "type": type_, **clean})
            self._cond.notify_all()
            return self.seq

    def since(self, seq: int, limit: int = 200) -> list[dict]:
        with self._lock:
            return [e for e in self._buf if e["seq"] > seq][-limit:]

    def wait(self, seq: int, timeout: float) -> list[dict]:
        with self._cond:
            if self.seq <= seq:
                self._cond.wait(timeout)
        return self.since(seq)

    def snapshot(self) -> dict:
        with self._lock:
            return {"seq": self.seq, "active": dict(self.active), "server_time": time.time(), "buffered": len(self._buf)}
