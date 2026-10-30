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
from .browser import BrowserAgent, SessionBrowser
from .imagegen import ImageGen
from .improve import Improver
from .instagram import InstagramManager
from .kgraph import KnowledgeGraph
from .notify import Notifier
from .planner import Planner
from .plugins import PluginManager
from .policy import PolicyEngine
from .pos import POSManager
from .pos_sync import POSSync
from .research import Research, ResearchError
from .resource_guard import ResourceGuard
from .router import Router
from .sandbox import Sandbox
from .studio import Studio
from .telegram_bot import TelegramAssistant
from .instagram_mcp import InstagramMCP
from .selfheal import SelfHealer
from .brain import Brain
from .events import EventBus
from .memory_connect import MemoryConnector
from .integrations import IntegrationHub
from .integrations.analyst import Analyst
from .brain_core import BrainCore
from .telephony import Telephony
from .voice import Voice
from .security import contains_secret, redact

CAPABILITIES = {
    "ishlaydi": ["O'zbekcha chat (kirill/lotin, xatoga chidamli)", "Doimiy xotira + manba/ishonch (provenance)", "Qarorlar jurnali",
                 "Tasdiqlash + Policy Engine (low/medium/high/forbidden)", "Planner (AI mavjud bo'lsa AI bilan) va vazifalar grafi",
                 "Fayllarni o'qish (txt/csv/xlsx/pdf)", "Buyruqlar va dasturlarni tasdiq bilan ishga tushirish", "Sandbox'da kod sinash",
                 "Business Intelligence + Excel hisobot", "POS: loyiha → tasdiq → fayl eksporti yoki REST API",
                 "Video (FFmpeg): kesish, 9:16, subtitr, avtomatik subtitr (Whisper), o'zbekcha ovoz (espeak-ng)",
                 "Rasm: tahlil, o'lcham, matn, logo; mahalliy SD bilan yaratish; vision tahlil", "Brauzer agenti (faqat o'qish)",
                 "Zaxira nusxa va tiklash", "Diagnostika, release gate, kengaytmalar", "Dashboard PIN himoyasi"],
    "qisman": ["AI: Ollama/tashqi provayder ulansa (real xizmat bilan bu yerda sinalmagan), aks holda offline",
               "Telegram, Instagram (post/Reels/Direct), internet tadqiqoti, Twilio qo'ng'irog'i — kod tayyor, kalit kiritilgach ishlaydi",
               "Ovoz: brauzer STT (internet) yoki mahalliy Whisper (ixtiyoriy o'rnatiladi)"],
    "hali_yoq": ["POSga brauzer orqali yozish (POS sayti ma'lum bo'lgach)", "HTTPS (tarmoqqa ochish uchun)"],
}


class JarvisCore:
    def __init__(self, db_path: Path | None = None, settings: Settings | None = None):
        self.settings = settings or Settings.load()
        self.db = Database(db_path)
        self.events = EventBus()
        self.audit = Audit(self.db)
        self.kgraph = KnowledgeGraph(self)
        self.memory = Memory(self.db, self.audit)
        self.memory.on_add = self.kgraph.on_memory
        self.memory.events = self.events
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
        def _on_error(m, msg):
            self.events.publish("error", module=m)
            self.notifier.notify(f"Xato: {m}", msg, severity="warning", category="error")
        self.audit.on_error = _on_error
        self.research = Research(self)
        self.studio = Studio(self)
        self.imagegen = ImageGen(self)
        self.instagram = InstagramManager(self)
        self.instagram_mcp = InstagramMCP(self)
        self.voice = Voice(self)
        self.browser = BrowserAgent(self)
        self.session_browser = SessionBrowser(self)
        self.pos_sync = POSSync(self)
        self.telephony = Telephony(self.settings, self.approvals)
        self.notifier.telephony = self.telephony
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
        self.selfheal = SelfHealer(self)
        self.brain = Brain(self)
        self.connector = MemoryConnector(self)
        self.integrations = IntegrationHub(self)
        self.analyst = Analyst(self)
        self.brain_core = BrainCore(self)
        self.approvals.on_pending = self.telegram.on_approval_pending
        self.approvals.events = self.events
        self._health_state: dict = {}
        self.automation_paused = False

    def start_scheduler(self, every_sec: int = 60):
        """Fon jadvali: rejalashtirilgan Instagram postlari uchun tasdiq so'rash (avtomatik nashr yo'q)."""
        import threading
        import time as _t

        def loop():
            while True:
                _t.sleep(every_sec)
                if self.automation_paused:
                    continue
                try:
                    self.instagram.due_scheduled()
                except Exception as e:  # jadval xatosi serverni to'xtatmasin
                    self.audit.error("scheduler", str(e))
                try:
                    self.health_watch()
                except Exception as e:
                    self.audit.error("scheduler", f"health_watch: {e}")
        threading.Thread(target=loop, daemon=True).start()

    # --- monitoring: holat o'zgarganda (bir marta) xabar beradi ---
    def _transition(self, key: str, ok: bool, title_bad: str, body: str, category: str, title_ok: str | None = None):
        prev = self._health_state.get(key)
        self._health_state[key] = ok
        if prev is True and not ok:
            self.notifier.notify(title_bad, body, severity="warning", category=category)
        elif prev is False and ok and title_ok:
            self.notifier.notify(title_ok, "", severity="info", category=category)

    def health_watch(self, now: float | None = None) -> dict:
        import time as _t
        import psutil
        now = now or _t.time()
        out = {}
        vm, du = psutil.virtual_memory(), psutil.disk_usage(str(self.db.path.parent if hasattr(self.db, "path") else "."))
        problems = []
        if vm.percent >= 92:
            problems.append(f"RAM {vm.percent:.0f}% band")
        if du.free < 3 * 2**30:
            problems.append(f"diskda {du.free / 2**30:.1f} GB qoldi")
        out["resources"] = problems
        last = self._health_state.get("resources_at", 0)
        if problems and now - last > 3600:
            self._health_state["resources_at"] = now
            self.notifier.notify("Kompyuter resurslari chegarada", "; ".join(problems), severity="warning", category="resources")
        if self.settings.ai_provider == "ollama":
            ok = bool(self.ai.available()[0])
            self._transition("ollama", ok, "Mahalliy AI (Ollama) ishlamay qoldi", "Ollama dasturini oching", "api", "Mahalliy AI qayta ishlayapti")
            out["ollama"] = ok
        if now - self._health_state.get("ig_at", 0) > 1800:
            self._health_state["ig_at"] = now
            from .secrets import get_secret
            for a in self.settings.instagram_accounts:
                if get_secret(f"instagram_token_{a['name']}"):
                    st = self.instagram.account_status(a["name"])
                    self._transition(f"ig:{a['name']}", st["connected"], f"Instagram ulanishi uzildi: @{a['name']}", st.get("note", ""),
                                     "instagram", f"Instagram qayta ulandi: @{a['name']}")
            if self.settings.instagram_mcp_url:
                self.instagram_mcp.check()
        if now - self._health_state.get("integ_at", 0) > 300:          # ulanishlar holati va jadval bo'yicha sinxronlash
            self._health_state["integ_at"] = now
            self.integrations.monitor()
        last_heal = self._health_state.setdefault("heal_at", now)
        if now - last_heal > 6 * 3600:          # 6 soatda bir yengil tekshiruv: diagnostika + xatolarni guruhlash (test/taklifsiz)
            self._health_state["heal_at"] = now
            self.selfheal.run()
        return out

    # --- Telegram tasdig'idan keyin bajariladigan amallar (aniq ro'yxat) ---
    def execute_approved(self, approval_id: int) -> str | None:
        appr = self.approvals.get(approval_id)
        try:
            if appr["action_type"] == "instagram_publish":
                post = self.db.one("SELECT id FROM ig_posts WHERE approval_id=?", (approval_id,))
                if not post:
                    return None
                p = self.instagram.publish(post["id"])
                if p["status"] == "published":
                    return f"📤 Joylandi va tekshirildi (Instagram ID: {p['external_id']}). Post #{p['id']}."
                if p["status"] == "unknown":
                    return "⚠️ Natija noma'lum (tarmoq). Qayta yuborilmaydi — dashboardda 'tekshirish' ni bosing."
                return f"❌ Joylanmadi: {p.get('last_error')}\nYechim: media havolasi ommaviy https:// ekanini va token ruxsatlarini tekshiring."
            if appr["action_type"] == "integration_write":
                r = self.integrations.execute_write(approval_id)
                return f"✅ Tashqi tizimga yozildi: {str(r.get('result'))[:200]}"
            if appr["action_type"] == "instagram_mcp_call":
                r = self.instagram_mcp.execute_approval(approval_id)
                return ("❌ MCP vositasi xato qaytardi." if r["is_error"] else "✅ MCP amali bajarildi.") + " Natija dashboardda."
        except Exception as e:
            self.audit.error("execute_approved", f"{appr['action_type']}: {e}")
            return f"❌ Bajarilmadi: {e}"
        return "Amal tasdiqlandi — uni so'ragan modul (dashboard) davom ettiradi."

    def stop_automation(self, source: str = "dashboard") -> str:
        """Ruxsat etilgan avtomatik jarayonlarni to'xtatadi: jadval, POS sinxronlash, DAG navbati. Qayta yoqish — dashboardda."""
        self.automation_paused = True
        self.audit.log(source, "Avtomatik jarayonlar to'xtatildi", target="automation", risk="C", approval_status="user_action")
        return "⏸ Avtomatik jarayonlar to'xtatildi (jadval, POS sinxronlash). Qayta yoqish: dashboard → Telegram → 'Avtomatikani yoqish'."

    def resume_automation(self) -> None:
        self.automation_paused = False
        self.audit.log("user", "Avtomatik jarayonlar qayta yoqildi", target="automation", risk="C", approval_status="user_action")

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
        if intent not in ("memory_save", "memory_query"):
            brain = self.brain_core.think(text)          # POS / biznes / ulanishlar savollari — Brain Core (manba bilan)
            if brain:
                return out | brain

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
