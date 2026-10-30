"""Digital Twin — foydalanuvchining FAQAT tasdiqlangan ma'lumotlaridan (afzallik, ish uslubi, loyiha, qaror, maqsad) profil.

* Manba — Memory Brain (alohida nusxa saqlanmaydi): tahrirlash/o'chirish xotiraning o'zida, shuning uchun hamma joyda bir xil.
* Model xulosalari va AI yozuvlari profilga kirmaydi (faqat user_given / tasdiqlangan import / tasdiqlangan tajriba).
* Takliflar faqat taklif: JARVIS foydalanuvchi nomidan qaror qabul qilmaydi va tashqi amal bajarmaydi.
* Profil AI promptlariga avtomatik qo'shilmaydi (shaxsiy ma'lumot tashqi provayderga ketmasligi uchun).
"""
from __future__ import annotations

import re
from collections import Counter

SECTIONS = {"preferences": ("Afzalliklar va muloqot uslubi", ("preference",)), "work_style": ("Ish uslubi va tajriba", ("procedural",)),
            "projects": ("Loyihalar", ("project",)), "decisions": ("Qarorlar", ("decision",)), "technical": ("Texnologiyalar va muhit", ("technical",)),
            "goals": ("Maqsadlar va uzoq muddatli", ("long_term",)), "profile": ("Profil va ko'nikmalar", ("semantic",))}
APPROVED_SOURCES = ("user", "dashboard", "telegram", "import:", "mission_reflection", "memory_explorer")


def _approved(m: dict) -> bool:
    src = str(m.get("source") or "")
    return m.get("info_type") != "model_inference" and (src.startswith(APPROVED_SOURCES) or src == "")


class DigitalTwin:
    def __init__(self, core):
        self.core = core

    def profile(self) -> dict:
        out, total = {}, 0
        for key, (title, kinds) in SECTIONS.items():
            items = []
            for k in kinds:
                for m in self.core.memory.list(k, limit=200):
                    if m.get("status") == "deleted" or not _approved(m):
                        continue
                    items.append({"id": m["id"], "title": m.get("title"), "content": m["content"], "source": m["source"],
                                  "date": m.get("observed_at") or m.get("created_at"), "confidence": m.get("confidence"), "status": m.get("status")})
            out[key] = {"title": title, "items": items}
            total += len(items)
        return {"sections": out, "total": total,
                "note": "Faqat siz kiritgan yoki tasdiqlagan ma'lumotlar. Tahrirlash/o'chirish — shu yerda yoki Memory Explorer'da."}

    def edit(self, mid: int, content: str) -> dict:
        return self.core.memory.update(mid, content)

    def delete(self, mid: int) -> dict:
        self.core.memory.delete(mid)
        self.core.audit.log("user", f"Digital Twin ma'lumoti o'chirildi: memory#{mid}", target=f"memory#{mid}", risk="C", approval_status="user_action")
        return {"ok": True}

    def suggestions(self) -> list[dict]:
        db, out = self.core.db, []
        goals = Counter(re.sub(r"\W+", " ", r["goal"].lower()).strip() for r in db.query("SELECT goal FROM missions WHERE status<>'cancelled'"))
        for g, n in goals.most_common(5):
            if n >= 3:
                out.append({"kind": "repeat", "text": f"«{g[:80]}» {n} marta bajarilgan — uni Workflow yoki skill qilib avtomatlashtirish mumkin.",
                            "link": "#mission"})
        for r in db.query("SELECT id, goal, status FROM missions WHERE status IN ('paused','waiting_approval','failed','needs_input') ORDER BY id DESC LIMIT 5"):
            out.append({"kind": "unfinished", "text": f"Missiya #{r['id']} tugallanmagan ({r['status']}): {r['goal'][:80]}", "link": "#mission"})
        for r in db.query("SELECT content FROM memory_import_items WHERE status='imported' AND flags LIKE '%unfinished%' ORDER BY conv_date DESC LIMIT 3"):
            out.append({"kind": "unfinished", "text": "ChatGPT'dagi tugallanmagan ish: " + r["content"][:120], "link": "#memx"})
        projects = self.core.memory.list("project", limit=50)
        if projects:
            p = max(projects, key=lambda m: m.get("observed_at") or m.get("created_at") or "")
            out.append({"kind": "focus", "text": f"Eng so'nggi loyiha: {(p.get('title') or p['content'])[:100]} — davom ettirish uchun missiya tuzaymi?", "link": "#mission"})
        prefs = [m for m in self.core.memory.list("preference", limit=20) if _approved(m)]
        if not prefs:
            out.append({"kind": "profile", "text": "Afzalliklaringiz kiritilmagan — masalan, javob tili va uslubini Memory'ga qo'shing yoki ChatGPT eksportini import qiling.",
                        "link": "#memimport"})
        return out
