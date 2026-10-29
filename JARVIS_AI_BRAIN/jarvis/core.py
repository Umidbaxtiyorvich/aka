"""JARVIS Core: modullarni bog'laydi va chat xabarlarini yo'naltiradi."""
from __future__ import annotations

import re
from pathlib import Path

from . import intent as intent_mod
from . import system_info
from .agents import AgentManager
from .ai_engine import SYSTEM_PROMPT, AIError
from .approval import ApprovalEngine
from .auth import AuthManager
from .backup import BackupManager
from .bi import BusinessIntelligence
from .audit import Audit
from .computer import ComputerAgent
from .config import Settings
from .db import Database
from .dag import TaskGraph
from .decisions import DecisionJournal
from .diagnostics import Diagnostics
from .files import FileIntelligence
from .memory import Memory, MemoryError_
from .browser import BrowserAgent
from .improve import Improver
from .instagram import InstagramManager
from .kgraph import KnowledgeGraph
from .notify import Notifier
from .planner import Planner
from .plugins import PluginManager
from .policy import PolicyEngine
from .pos import POSManager
from .research import Research, ResearchError
from .resource_guard import ResourceGuard
from .router import Router
from .sandbox import Sandbox
from .studio import Studio
from .telegram_bot import TelegramAssistant
from .telephony import Telephony
from .voice import Voice
from .security import contains_secret, redact

CAPABILITIES = {
    "ishlaydi": ["O'zbekcha matnli chat (kirill/lotin, xatoga chidamli)", "Doimiy xotira (qidiruv, tahrir, eksport, o'chirish)",
                 "Audit va xatolar jurnali", "Tasdiqlash tizimi (A–E, versiyaga bog'langan)", "Planner (maqsad → bosqichlar → agentlar)",
                 "Fayllarni o'qish (txt/csv/xlsx/pdf)", "Buyruq taklifi va tasdiqdan keyin bajarish", "Kod tahlili (Python)",
                 "Business Intelligence: CSV/Excel import, qoldiq, foyda, kam qolgan, noto'g'ri narx, takroriy hujjat, qarzdorlik",
                 "POS hujjat loyihasi → tasdiq → fayl eksporti (outbox) → tekshiruv", "Video: kesish, birlashtirish, 9:16, format, subtitr, ovoz, slayd-shou, sifat tekshiruvi (FFmpeg)",
                 "Rasm: tahlil, o'lcham presetlari, matn qo'shish, logo/avatar, generator uchun prompt", "Brauzer agenti: ruxsat berilgan saytni faqat o'qish (Playwright)",
                 "Bildirishnomalar (dashboard)", "Self-improvement: taklif → alohida worktree'da test → tasdiq → alohida branch"],
    "qisman": ["AI suhbat: Ollama ulansa (real Ollama bilan hali sinalmagan), aks holda offline",
               "Ovoz: brauzer STT/TTS (internet kerak); mahalliy Whisper ixtiyoriy o'rnatiladi",
               "Internet tadqiqoti: kod tayyor, siz yoqqaningizdan keyin ishlaydi (bulutda real tarmoq bilan sinalmagan)",
               "Telegram: bot kodi tayyor, token va ID kiritilgach ishlaydi (real Telegram bilan sinalmagan)",
               "Instagram: Graph API kodi tayyor, Business akkaunt + Meta App + token kerak (real API bilan sinalmagan)"],
    "hali_yoq": ["POS bilan to'g'ridan-to'g'ri API/brauzer kiritish (POS manzili kerak)", "AI rasm generatsiyasi (GPU yoki onlayn adapter)",
                 "Telefon qo'ng'irog'i (SIP provayder kerak, faqat reja va tasdiq tayyor)", "Dashboard autentifikatsiyasi (server faqat 127.0.0.1 da)"],
}


class JarvisCore:
    def __init__(self, db_path: Path | None = None, settings: Settings | None = None):
        self.settings = settings or Settings.load()
        self.db = Database(db_path)
        self.audit = Audit(self.db)
        self.kgraph = KnowledgeGraph(self)
        self.memory = Memory(self.db, self.audit)
        self.memory.on_add = self.kgraph.on_memory
        self.policy = PolicyEngine(self.settings)
        self.approvals = ApprovalEngine(self.db, self.audit, self.policy)
        self.files = FileIntelligence(self.settings)
        self.computer = ComputerAgent(self.settings, self.approvals, self.audit)
        self.guard = ResourceGuard(self)
        self.ai = Router(self)
        self.bi = BusinessIntelligence(self.db, self.audit, self.settings, self.files)
        self.pos = POSManager(self.db, self.audit, self.approvals, self.settings)
        self.notifier = Notifier(self.db, self.settings)
        self.telegram = TelegramAssistant(self)
        self.notifier.telegram = self.telegram
        self.audit.on_error = lambda m, msg: self.notifier.notify(f"Xato: {m}", msg, severity="warning", category="error")
        self.research = Research(self)
        self.studio = Studio(self)
        self.instagram = InstagramManager(self)
        self.voice = Voice(self)
        self.browser = BrowserAgent(self)
        self.telephony = Telephony(self.settings, self.approvals)
        self.planner = Planner(self)
        self.decisions = DecisionJournal(self)
        self.sandbox = Sandbox(self)
        self.backup = BackupManager(self)
        self.dag = TaskGraph(self)
        self.plugins = PluginManager(self)
        self.diagnostics = Diagnostics(self)
        self.auth = AuthManager(self)
        self.improver = Improver(self)
        self.agents = AgentManager(self)

    def start_scheduler(self, every_sec: int = 60):
        """Fon jadvali: rejalashtirilgan Instagram postlari uchun tasdiq so'rash (avtomatik nashr yo'q)."""
        import threading
        import time as _t

        def loop():
            while True:
                _t.sleep(every_sec)
                try:
                    self.instagram.due_scheduled()
                except Exception as e:  # jadval xatosi serverni to'xtatmasin
                    self.audit.error("scheduler", str(e))
        threading.Thread(target=loop, daemon=True).start()

    def reload_ai(self):
        self.ai._avail_cache.clear()

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
            from .memory import label
            return out | {"text": "Topdim:\n" + "\n".join(
                f"• #{h['id']} {h['content']} [{label(h)}; manba: {h['reference'] or h['source']}, {h['observed_at'] or h['created_at']}"
                f"{'; ZID MA`LUMOT BOR' if h['status'] == 'conflict' else ''}]" for h in hits)}

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

        if intent == "research":
            q = re.sub(r"(?i)\b(internetdan|internetda|qidir\w*|izla\w*|topib ber)\b", "", text).strip(" :?")
            try:
                r = self.research.answer(q or text)
            except ResearchError as e:
                return out | {"text": str(e)}
            src = "\n".join(f"[{s['n']}] {s['title']} — {s['url']} ({s['fetched_at']}, ishonch {s['reliability']})" for s in r["sources"])
            return out | {"text": f"{r['answer']}\n\nManbalar:\n{src or 'yo‘q'}", "research": r}

        if intent == "bi_report":
            r = self.bi.report()
            if not r["has_data"]:
                return out | {"text": "Hali savdo/ombor ma'lumoti import qilinmagan. Business Intelligence bo'limida CSV yoki Excel faylni yuklang."}
            p = r["profit"]
            gp = p["gross_profit"] if p["gross_profit"] is not None else f"{p['gross_profit_known_only']} (tannarxi noma'lum: {', '.join(p['skus_without_cost'])})"
            return out | {"text": f"Savdo: {p['revenue']}, yalpi foyda: {gp}. Kam qolgan: {len(r['low_stock'])}, "
                                  f"narx muammosi: {len(r['price_issues'])}, takroriy hujjat: {len(r['duplicates'])}, "
                                  f"qoldiq tafovuti: {len(r['discrepancies'])}. Batafsil — BI bo'limida."}

        if intent == "plan":
            goal = text.split(":", 1)[1].strip() if ":" in text else text
            plan = self.planner.create(goal)
            steps = "\n".join(f"{s['n']}. {s['text']} → {s['agent']}" for s in plan["steps"])
            return out | {"text": f"Reja #{plan['id']} tuzildi:\n{steps}\nBajarish uchun Agentlar → Rejalar bo'limida «Bajarish»ni bosing.", "plan": plan}

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
            r = self.ai.route(messages)
            return {"text": r["text"] + "\n\n" + self.ai.notice(r["route"]), "provider": r["route"]["provider"],
                    "route": r["route"]}
        except AIError as e:
            self.audit.error("ai_engine", str(e))
            return {"text": "AI modeli javob bermadi. Xato logga yozildi. Sozlamalar → AI bo'limida holatni tekshiring.",
                    "provider": self.ai.name, "error": str(e)}
