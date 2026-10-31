"""Agent rejimi — chatda JARVIS odamday ishlaydi: topshiriqni tushunadi, kerakli vositalarni o'zi tanlaydi va chaqiradi,
natijani ko'rib keyingi qadamni o'ylaydi, oxirida o'zbekcha javob beradi.

* Fikrlash: ulangan AI modeli (AI Router orqali; maxfiy ma'lumot bo'lsa — faqat mahalliy model). Model yo'q bo'lsa —
  oldingi qoidaga asoslangan javob (yolg'on "o'yladim" yo'q).
* Vositalar: Tool Registry (default deny, agent chegarasi, limit, audit). O'qish vositalari (savdo, qoldiq, xotira, fayl,
  ulanishdan yangi ma'lumot olish) — darhol. Tashqariga ta'sir qiladigan (POS'ga kirim, saytda generatsiya, Instagram nashr,
  Direct, Telegram xabar) — FAQAT tasdiq so'rovi yaratadi; chatda "Tasdiqlash va bajarish" tugmasi chiqadi.
* Cheklovlar: ≤ 6 qadam, bir xil chaqiruv takrorlansa — to'xtaydi, natijalar qisqartirib modelga beriladi, parol/token
  modelga yuborilmaydi (redact), favqulodda to'xtatishda faqat o'qish.
"""
from __future__ import annotations

import json
import re

from .security import redact
from .tools import S, Tool, ToolError

MAX_STEPS = 6
SYSTEM = """Sen JARVIS — foydalanuvchining shaxsiy yordamchisi va biznes bo'yicha o'ng qo'lisan. Odamday fikrla: topshiriqni tushun,
kerak bo'lsa vositalardan foydalan, natijani tekshir va o'zbek tilida qisqa, aniq javob ber.

Javobing HAR DOIM faqat BITTA JSON obyekt bo'lsin (boshqa matn yo'q):
  {"tool": "<vosita id>", "args": {...}, "why": "nima uchun (qisqa)"}   — vositani chaqirish
  {"answer": "<foydalanuvchiga yakuniy javob>"}                          — tugatish

Qoidalar:
- Raqam va faktlarni TO'QIMA: savdo, qoldiq, qarz va h.k. uchun vositadan foydalan; ma'lumot yo'q bo'lsa — ochiq ayt.
- "Hozirgi", "bugungi" ma'lumot so'ralsa va ulanish bor bo'lsa — avval connection.refresh (saytga kirib yangi ma'lumot olish), keyin analyst.ask.
- Tashqi tizimga yozish (kirim, chiqim, savdo, nashr, xabar) vositalari faqat TASDIQ SO'ROVI yaratadi. Javobda "tasdiqlang" de, "bajarildi" dema.
- POS/saytda amal uchun o'rgatilgan amal (site.task) bo'lsa — parametrlarni foydalanuvchi gapidan aniq ajrat; noaniq bo'lsa — so'ra.
  Kerakli amal o'rgatilmagan bo'lsa — "Saytlar orqali topshiriq → Amalni o'rgatish" bo'limida bir marta ko'rsatishni taklif qil.
- Parol, kod, token so'rama va yozma. CAPTCHA/SMS'ni chetlab o'tishga urinma.
- Qila olmaydigan narsani qila olaman dema.

Vositalar:
{tools}

Ulangan tizimlar:
{conns}

O'rgatilgan sayt amallari (site.task uchun):
{tasks}
"""


def _parse(text: str) -> dict | None:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    i = t.find("{")
    while i != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(t[i:])
            if isinstance(obj, dict) and ("tool" in obj or "answer" in obj):
                return obj
        except ValueError:
            pass
        i = t.find("{", i + 1)
    return None


def _short(v, n: int = 2500) -> str:
    s = json.dumps(v, ensure_ascii=False, default=str)
    return redact(s if len(s) <= n else s[:n] + "…(qisqartirildi)")


def register_tools(core):
    """Agent uchun qo'shimcha vositalar: ulanishlar, jonli ma'lumot, o'rgatilgan amallar, sayt generatsiyasi, Instagram, Telegram."""
    c, R = core, core.tools.register

    def conns(_a):
        out = []
        for x in c.integrations.list():
            sk = [s["capability"] for s in c.site_skills.list(x["id"])]
            tk = [{"id": t["id"], "name": t["name"], "params": [p["name"] for p in t["params"]]} for t in c.site_tasks.list(x["id"]) if t["status"] == "ready"]
            out.append({"id": x["id"], "name": x["name"], "type": x["system_type"], "status": x["status"], "last_sync": x.get("last_sync"),
                        "records": x.get("records"), "can_generate": sk, "taught_actions": tk})
        return out

    def refresh(a):
        r = c.integrations.sync(int(a["conn_id"]), trigger="agent")
        return {k: r.get(k) for k in ("status", "counts", "note", "error") if k in r} or r

    def tg_send(a):
        if not c.telegram.owner():
            raise ToolError("Telegram egasi ulanmagan (Telegram bo'limida ulang)")
        appr = c.approvals.request(action_type="telegram_send", target="telegram_owner", level="D", payload={"text": a["text"][:3500]},
                                   summary=f"Telegram'ga xabar: «{a['text'][:80]}»", requested_by="chat_agent")
        return {"approval": appr}

    def ig_publish(a):
        return {"approval": c.instagram.request_publish(int(a["post_id"]))}

    def ig_dm(a):
        return {"approval": c.instagram.request_dm(int(a["draft_id"]))}

    U = ["user", "manager"]
    R(Tool("connections.list", "Ulanishlar", "Ulangan POS/sayt/API lar: holati, oxirgi sinxron, nima yarata oladi, o'rgatilgan amallar", "A", {}, "ro'yxat",
           conns, agents=U))
    R(Tool("connection.refresh", "Yangi ma'lumot olish", "Ulanishga (masalan, POS saytiga) HOZIR kirib, yangi ma'lumotni o'qib oladi (faqat o'qish)", "B",
           {"conn_id": S("integer", True, "ulanish id")}, "sinxronlash natijasi", refresh, agents=U, timeout=300, idempotent=False, rate_per_min=4))
    R(Tool("site.task", "O'rgatilgan sayt amali", "Saytda o'rgatilgan amal (masalan, POS'ga kirim) — TASDIQ so'rovi yaratadi", "D",
           {"task_id": S("integer", True, "amal id"), "params": S("object", True, "{parametr: qiymat}")}, "tasdiq so'rovi",
           lambda a: c.site_tasks.propose(int(a["task_id"]), a["params"], requested_by="chat_agent"), agents=["user"], idempotent=False, approval=True, rate_per_min=6))
    R(Tool("site.generate", "Saytda yaratish", "Ulangan saytda rasm/video/ovoz/matn yaratish (Site Skills) — TASDIQ so'rovi", "D",
           {"skill_id": S("integer", True, "ko'nikma id"), "prompt": S("string", True, "so'rov matni")}, "tasdiq so'rovi",
           lambda a: c.site_skills.propose(int(a["skill_id"]), a["prompt"], requested_by="chat_agent"), agents=["user"], idempotent=False, approval=True, rate_per_min=6))
    R(Tool("site.skills", "Sayt imkoniyatlari", "Qaysi ulangan sayt nimani yarata oladi (skill_id bilan)", "A", {}, "ro'yxat",
           lambda a: [{"skill_id": s["id"], "site": s["conn_name"], "capability": s["capability"], "status": s["conn_status"], "verified": bool(s["verified"])}
                      for s in c.site_skills.list()], agents=U))
    R(Tool("instagram.accounts", "Instagram akkauntlar", "Ulangan Instagram akkauntlari", "A", {}, "ro'yxat", lambda a: c.instagram.accounts(), agents=U))
    R(Tool("instagram.draft_post", "Instagram post loyihasi", "Post/reels/story loyihasi (nashr qilinmaydi)", "B",
           {"account": S("string", True, "akkaunt"), "caption": S("string", True, "matn"), "media_url": S("string", description="rasm/video URL"),
            "kind": S("string", description="post|reel|story", default="post")}, "loyiha",
           lambda a: c.instagram.draft(a["account"], a.get("kind", "post"), a["caption"], a.get("media_url", "")), agents=["user"], idempotent=False))
    R(Tool("instagram.request_publish", "Instagram nashr (tasdiq)", "Loyihani nashr qilish uchun TASDIQ so'rovi", "D",
           {"post_id": S("integer", True, "loyiha id")}, "tasdiq so'rovi", ig_publish, agents=["user"], idempotent=False, approval=True, rate_per_min=5))
    R(Tool("instagram.conversations", "Instagram Direct", "Direct suhbatlar ro'yxati", "A", {"account": S("string", True, "akkaunt")}, "suhbatlar",
           lambda a: c.instagram.conversations(a["account"]), agents=U))
    R(Tool("instagram.draft_dm", "Direct javob loyihasi", "Mijozga javob loyihasi (yuborilmaydi)", "B",
           {"account": S("string", True, "akkaunt"), "conversation_id": S("string", True, "suhbat id"), "reply": S("string", description="javob matni")}, "loyiha",
           lambda a: c.instagram.draft_dm(a["account"], a["conversation_id"], a.get("reply", "")), agents=["user"], idempotent=False))
    R(Tool("instagram.request_dm", "Direct yuborish (tasdiq)", "Direct javobni yuborish uchun TASDIQ so'rovi", "D",
           {"draft_id": S("integer", True, "loyiha id")}, "tasdiq so'rovi", ig_dm, agents=["user"], idempotent=False, approval=True, rate_per_min=5))
    R(Tool("telegram.send", "Telegram xabar (tasdiq)", "Sizning Telegram'ingizga xabar yuborish — TASDIQ so'rovi", "D",
           {"text": S("string", True, "matn")}, "tasdiq so'rovi", tg_send, agents=["user"], idempotent=False, approval=True, rate_per_min=5))


def run_approved(core, approval_id: int) -> dict:
    """Tasdiqlangan amalni turiga qarab bajarish (chatdagi "Tasdiqlash va bajarish" tugmasi)."""
    a = core.approvals.get(approval_id)
    t = a["action_type"]
    if t == "site_task":
        return core.site_tasks.execute(approval_id)
    if t == "site_action":
        return core.site_skills.execute(approval_id)
    if t == "integration_write":
        return core.integrations.execute_write(approval_id)
    if t == "instagram_publish":
        r = core.db.one("SELECT id FROM ig_posts WHERE approval_id=?", (approval_id,))
        if not r:
            raise ToolError("Post topilmadi")
        return {"status": "ok", "result": core.instagram.publish(r["id"])}
    if t == "instagram_dm":
        r = core.db.one("SELECT id FROM ig_dm_drafts WHERE approval_id=?", (approval_id,))
        if not r:
            raise ToolError("Direct loyihasi topilmadi")
        return {"status": "ok", "result": core.instagram.send_dm(r["id"])}
    if t == "telegram_send":
        core.approvals.authorize_execution(approval_id, a["payload"])
        res = core.telegram.send_owner(a["payload"]["text"])
        core.approvals.mark_result(approval_id, "executed" if res else "unknown")
        return {"status": "ok" if res else "error", "error": None if res else "Telegram egasi topilmadi"}
    raise ToolError("Bu turdagi amal o'z bo'limida bajariladi (Tasdiqlashlar)")


class AgentLoop:
    def __init__(self, core):
        self.core = core

    def ready(self) -> bool:
        if not getattr(self.core.settings, "agent_mode", True):
            return False
        return any(p["kind"] != "offline" and p["available"] for p in self.core.ai.status())

    def _system(self) -> str:
        c = self.core
        tools = "\n".join(f"- {t['id']} ({t['level']}{', TASDIQ' if t['approval'] else ''}): {t['description']}. args: "
                          + json.dumps({k: v["type"] + ("*" if v.get("required") else "") for k, v in t["inputs"].items()}, ensure_ascii=False)
                          for t in c.tools.catalog("user"))
        conns = "\n".join(f"- #{x['id']} {x['name']} ({x['system_type']}, {x['status']}, oxirgi sinxron: {x.get('last_sync') or 'yo`q'})"
                          for x in c.integrations.list()) or "- yo'q"
        tasks = "\n".join(f"- task_id={t['id']} «{t['name']}» ({t['conn_name']}): parametrlar " + ", ".join(f"{p['name']} ({p['label']}, misol: {p.get('example', '')})" for p in t["params"])
                          for t in c.site_tasks.ready()) or "- yo'q"
        return SYSTEM.replace("{tools}", tools).replace("{conns}", conns).replace("{tasks}", tasks)

    def run(self, text: str, allow_paid: bool = False) -> dict | None:
        c = self.core
        hist = list(reversed(c.db.query("SELECT role, content FROM conversations ORDER BY id DESC LIMIT 9")))[:-1]
        msgs = [{"role": "system", "content": self._system()}]
        msgs += [{"role": h["role"], "content": h["content"][:1500]} for h in hist[-8:] if h["role"] in ("user", "assistant")]
        msgs.append({"role": "user", "content": text})
        steps, approvals, seen, route = [], [], set(), None
        for _ in range(MAX_STEPS):
            res = c.ai.route(msgs, purpose="agent", allow_paid=allow_paid)
            route = res.get("route") or {}
            if route.get("kind") == "offline" or route.get("provider") in ("offline", "rule-based", "jarvis"):
                return None if not steps else {"text": "AI modeli javob bermadi. Bajarilgan qadamlar pastda.", "steps": steps, "approvals": approvals, "intent": "agent"}
            obj = _parse(res.get("text", ""))
            if obj is None or "answer" in obj:
                answer = (obj or {}).get("answer") or res.get("text", "").strip()
                return {"text": answer, "steps": steps, "approvals": approvals, "intent": "agent", "route": route}
            tid, args = str(obj.get("tool", "")), obj.get("args") or {}
            key = tid + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
            if key in seen:
                msgs.append({"role": "user", "content": "Bu chaqiruv allaqachon bajarildi. Endi yakuniy javob ber (answer)."})
                continue
            seen.add(key)
            step = {"tool": tid, "args": json.loads(redact(json.dumps(args, ensure_ascii=False, default=str))), "why": str(obj.get("why", ""))[:200]}
            try:
                r = c.tools.invoke(tid, args, caller="user")
                step["status"] = r["status"]
                out = r["result"]
                appr = (out or {}).get("approval") if isinstance(out, dict) else None
                if r["status"] == "approval_requested" and appr:
                    approvals.append({k: appr.get(k) for k in ("id", "summary", "level", "payload_hash", "action_type", "status")})
                    out = {"tasdiq_sorovi": appr.get("id"), "holat": "foydalanuvchi tasdig'ini kutmoqda", "xulosa": appr.get("summary")}
            except Exception as e:                       # noqa: BLE001 — xato modelga ko'rsatiladi, u boshqa yo'l tanlaydi
                step["status"], out = "error", {"xato": str(e)[:300]}
            step["result"] = _short(out, 600)
            steps.append(step)
            msgs.append({"role": "assistant", "content": json.dumps({"tool": tid, "args": args}, ensure_ascii=False, default=str)[:1500]})
            msgs.append({"role": "user", "content": f"Vosita natijasi ({tid}): {_short(out)}\nKeyingi qadam yoki yakuniy javob (faqat JSON)."})
        return {"text": "Qadamlar limiti tugadi — topshiriqni aniqroq yoki bo'lib bering.", "steps": steps, "approvals": approvals, "intent": "agent", "route": route}
