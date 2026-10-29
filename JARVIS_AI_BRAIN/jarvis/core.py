"""JARVIS Core: modullarni bog'laydi va chat xabarlarini yo'naltiradi."""
from __future__ import annotations

import re
from pathlib import Path

from . import intent as intent_mod
from . import system_info
from .agents import AgentManager
from .ai_engine import SYSTEM_PROMPT, AIError, build_provider
from .approval import ApprovalEngine
from .audit import Audit
from .computer import ComputerAgent
from .config import Settings
from .db import Database
from .files import FileIntelligence
from .memory import Memory, MemoryError_
from .security import contains_secret, redact

CAPABILITIES = {
    "ishlaydi": ["O'zbekcha matnli chat (kirill/lotin, xatoga chidamli buyruqlar)", "Doimiy xotira: qo'shish, qidirish, tahrirlash, eksport, o'chirish",
                 "Audit jurnali", "Tasdiqlash tizimi (A–E darajalar, versiyaga bog'langan xesh)", "Fayllarni o'qish (txt/csv/xlsx/pdf) — faqat ruxsat berilgan papkada",
                 "Buyruq taklifi va tasdiqdan keyin bajarish", "Kod tahlili (Python)", "O'z-o'zini tekshirish va testlar", "Tizim resurslari diagnostikasi"],
    "qisman": ["AI suhbat: Ollama ulansa ishlaydi, aks holda offline rejim"],
    "hali_yoq": ["Ovoz (STT/TTS)", "Internet tadqiqoti", "Brauzer agenti", "Rasm/video studiyasi", "Instagram", "Telegram", "POS va Business Intelligence", "Telefon qo'ng'irog'i"],
}


class JarvisCore:
    def __init__(self, db_path: Path | None = None, settings: Settings | None = None):
        self.settings = settings or Settings.load()
        self.db = Database(db_path)
        self.audit = Audit(self.db)
        self.memory = Memory(self.db, self.audit)
        self.approvals = ApprovalEngine(self.db, self.audit)
        self.files = FileIntelligence(self.settings)
        self.computer = ComputerAgent(self.settings, self.approvals, self.audit)
        self.ai = build_provider(self.settings)
        self.agents = AgentManager(self)

    def reload_ai(self):
        self.ai = build_provider(self.settings)

    # --- chat ---
    def chat(self, text: str) -> dict:
        safe_in = redact(text)
        intent, conf = intent_mod.detect(text)
        self.db.execute("INSERT INTO conversations(role, content, intent) VALUES ('user',?,?)", (safe_in, intent))
        if contains_secret(text):
            reply = {"text": "Xabaringizda parol yoki token bor ko'rinadi. Uni chatga yozmang — u saqlanmadi va "
                             "yashirildi. Maxfiy kalitlar Windows Credential Manager orqali ulanadi (docs/SECURITY.md).",
                     "intent": "secret_blocked"}
        else:
            reply = self.route(text, intent, conf)
        self.db.execute("INSERT INTO conversations(role, content, intent) VALUES ('assistant',?,?)",
                        (redact(reply["text"]), reply.get("intent")))
        return reply

    def route(self, text: str, intent: str | None = None, conf: float = 0.0) -> dict:
        if intent is None:
            intent, conf = intent_mod.detect(text)
        norm = intent_mod.normalize(text)
        out = {"intent": intent, "confidence": conf}

        if intent == "memory_save":
            content = text.split(":", 1)[1].strip() if ":" in text else re.sub(r"(?i)\b(eslab qol|esla|yodda tut|saqla)\b", "", text).strip()
            if not content:
                return out | {"text": "Nimani eslab qolay? Masalan: «Eslab qol: hisobotlar har dushanba»."}
            try:
                m = self.memory.add(content, "long_term", source="user_chat")
            except MemoryError_ as e:
                return out | {"text": str(e)}
            warn = f" Diqqat: #{m['conflicts_with']} bilan zid bo'lishi mumkin — Xotira bo'limida tekshiring." if m["conflicts_with"] else ""
            return out | {"text": f"Eslab qoldim (#{m['id']}).{warn}", "memory": m}

        if intent == "memory_search":
            q = text.split(":", 1)[1] if ":" in text else norm
            hits = self.memory.search(q, limit=5)
            if not hits:
                return out | {"text": "Xotirada mos ma'lumot topilmadi."}
            return out | {"text": "Topdim:\n" + "\n".join(f"• #{h['id']} {h['content']} (manba: {h['source']}, {h['created_at']})" for h in hits)}

        if intent == "task_create":
            content = text.split(":", 1)[1].strip() if ":" in text else text
            m = self.memory.add(content, "task", source="user_chat")
            return out | {"text": f"Vazifa rejaga qo'shildi (#{m['id']}). Xotira → 'task' bo'limida ko'rasiz."}

        if intent == "status":
            s = system_info.snapshot()
            ok, note = self.ai.available()
            return out | {"text": f"Tizim: {s['os']}, RAM {s['ram_total_gb']} GB ({s['ram_used_percent']}% band), "
                                  f"bo'sh disk {s['disk_free_gb']} GB. AI: {note}. "
                                  f"Kutilayotgan tasdiqlar: {len(self.approvals.list('pending'))}."}

        if intent == "help":
            c = CAPABILITIES
            return out | {"text": "✅ Ishlaydi: " + "; ".join(c["ishlaydi"]) + "\n⚠️ Qisman: " + "; ".join(c["qisman"])
                                  + "\n⏳ Hali yo'q: " + "; ".join(c["hali_yoq"])}

        if intent == "run_tests":
            t = self.agents.submit("qa", "Tizimni tekshirish", {}, run_now=True)
            return out | {"text": f"Tekshiruv bajarildi (vazifa #{t['id']}). Natija 'Testlar' bo'limida.", "task": t}

        if intent == "command":
            m = re.search(r"`([^`]+)`", text)
            if not m:
                return out | {"text": "Qaysi buyruqni? Buyruqni `teskari tirnoq` ichida yozing, masalan: bajar `dir`"}
            t = self.agents.submit("computer", f"Buyruq: {m.group(1)}", {"command": m.group(1)}, run_now=True)
            if t["status"] == "failed":
                return out | {"text": f"Buyruqni tayyorlab bo'lmadi: {t['error']}", "task": t}
            if t["status"] == "waiting_approval":
                return out | {"text": "Buyruq o'zgartirish kiritishi mumkin, shuning uchun 'Tasdiqlashlar' bo'limiga qo'yildi. "
                                      "Nima qilishini o'qib, keyin tasdiqlang.", "task": t}
            return out | {"text": "Bu faqat o'qiydigan buyruq (A daraja). 'Tasdiqlashlar' bo'limida «Bajarish» tugmasi bilan ishga tushiring.", "task": t}

        if intent == "file_read":
            items = self.files.list_dir()
            names = ", ".join(i["name"] for i in items[:20]) or "bo'sh"
            return out | {"text": f"Ruxsat berilgan papka: {self.settings.allowed_read_dirs[0]}\nIchida: {names}"}

        if intent == "greeting" and self.ai.name == "offline":
            return out | {"text": "Assalomu alaykum! Men JARVIS. Nima qila olishimni bilish uchun «yordam» deb yozing."}

        if intent == "unknown" and self.ai.name == "offline":
            return out | {"text": "Tushunmadim. Aniqroq yozing: masalan «eslab qol: ...», «xotira: ...», «vazifa: ...», "
                                  "«holat», «fayllar», «test» yoki «bajar `buyruq`». AI ulanmagan (offline rejim)."}

        return out | self._ask_ai(text)

    def _ask_ai(self, text: str) -> dict:
        context = self.memory.search(intent_mod.normalize(text), limit=5)
        mem = "\n".join(f"- {m['content']} (manba: {m['source']})" for m in context)
        history = self.db.query("SELECT role, content FROM conversations ORDER BY id DESC LIMIT 6")[::-1]
        messages = [{"role": "system", "content": SYSTEM_PROMPT + ("\nXotiradan:\n" + mem if mem else "")}]
        messages += [{"role": h["role"], "content": h["content"]} for h in history[:-1]]
        messages.append({"role": "user", "content": text})
        try:
            answer = self.ai.chat(messages)
            return {"text": answer, "provider": self.ai.name}
        except AIError as e:
            self.audit.error("ai_engine", str(e))
            return {"text": "AI modeli javob bermadi. Xato logga yozildi. Sozlamalar → AI bo'limida holatni tekshiring.",
                    "provider": self.ai.name, "error": str(e)}
