"""Site Skills — ulangan saytlardan topshiriq bajarish uchun foydalanish ("rasm yarat", "video yarat", "tarjima qil" ...).

Qanday ishlaydi:
1. Sayt ulanib o'rganilganda (discover) JARVIS har sahifadagi so'rov maydonlari va tugmalarni ko'rib, sayt nima qila olishini
   aniqlaydi (masalan "Generate image" tugmasi + prompt maydoni → rasm yaratish). Ma'lum saytlar (Leonardo, Ideogram,
   ChatGPT, Gemini, Suno, DeepL ...) domen bo'yicha ham taniladi. Siz ko'nikmani qo'lda qo'shishingiz/tuzatishingiz mumkin.
2. Topshiriq berilganda (chat, buyruq satri, "Topshiriq" oynasi) Task Router topshiriq turini aniqlaydi va variantlarni
   tuzadi: avval ULANGAN saytlar (siz nomini aytgan sayt — birinchi), keyin JARVIS'ning o'z agentlari.
3. Saytda bajarish = sizning hisobingizdan tashqi tizimda amal (kredit/pul sarflanishi mumkin) → HAR SAFAR aniq tasdiq (D).
   Tasdiqdan keyin brauzer agenti saytga kiradi, so'rovni yozadi, tugmani bosadi, natijani (rasm fayllari yoki matn) kutib
   oladi va JARVIS papkasiga saqlaydi + isbot uchun skrinshot.
4. Xavfsizlik: maxfiy matn yuborilmaydi; faqat shu sayt domeni; CAPTCHA/2FA chetlab o'tilmaydi; sayt to'lov yoki kredit
   so'rasa — to'xtaydi (JARVIS hech narsa sotib olmaydi); moliyaviy yozuvlar (savdo, to'lov, kirim/chiqim) bu yo'l bilan
   bajarilmaydi — ular POS yozish takliflari orqali alohida tasdiqlanadi.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .security import contains_secret, redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT, conn_id INTEGER NOT NULL, capability TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
    prompt_selector TEXT, submit_selector TEXT, result_selector TEXT, source TEXT NOT NULL DEFAULT 'detected', confidence REAL NOT NULL DEFAULT 0.5,
    verified INTEGER NOT NULL DEFAULT 0, runs INTEGER NOT NULL DEFAULT 0, last_run TEXT, last_status TEXT, enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(conn_id, capability, url)
);
CREATE TABLE IF NOT EXISTS site_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), skill_id INTEGER, conn_id INTEGER, approval_id INTEGER,
    capability TEXT, prompt TEXT, status TEXT NOT NULL, outputs TEXT, text TEXT, error TEXT
);
"""

GEN = r"(yarat|yaratib|chiz|chizib|generatsiya|generat|tayyorla|qilib ber|qil\b|ishla|create|generate|make|draw|design|нарисуй|сгенерир|создай|сделай)"
CAPS: dict[str, dict] = {
    "image.generate": {"uz": "Rasm yaratish", "icon": "🖼", "result": "image",
                       "intent": rf"(?i)(rasm|surat|tasvir|logo|logotip|banner|poster|afisha|illyustratsiya|image|picture|photo|картин|изображ|рисун).{{0,40}}{GEN}|{GEN}.{{0,25}}(rasm|surat|logo|image|picture|картин)",
                       "site": r"(?i)generate image|create image|text.to.image|image generat|ai art|imagine|rasm yarat|сгенерировать изображ|создать изображ|generate|create"},
    "video.generate": {"uz": "Video yaratish", "icon": "🎬", "result": "media",
                       "intent": rf"(?i)(video|rolik|klip|reels|видео|ролик).{{0,40}}{GEN}|{GEN}.{{0,25}}(video|rolik|видео)",
                       "site": r"(?i)generate video|create video|text.to.video|image.to.video|video generat|видео"},
    "audio.generate": {"uz": "Ovoz / musiqa yaratish", "icon": "🎵", "result": "media",
                       "intent": rf"(?i)(musiqa|qo'?shiq|ovoz|audio|music|song|voice|музык|песн|озвуч).{{0,40}}{GEN}|{GEN}.{{0,25}}(musiqa|qo'?shiq|music|song|ovoz)|ovozlashtir|озвучь",
                       "site": r"(?i)generate (music|song|audio|speech)|text.to.speech|create song|музык"},
    "translate":      {"uz": "Tarjima", "icon": "🌐", "result": "text",
                       "intent": r"(?i)tarjima qil|tarjima qilib|o'?gir(ib)?\b|translate|переведи|перевод",
                       "site": r"(?i)translat|перевод|tarjima"},
    "text.generate":  {"uz": "Matn yozish / AI javob", "icon": "✍", "result": "text",
                       "intent": rf"(?i)(matn|maqola|post|xat|reklama matni|ssenariy|tavsif|text|article|caption|текст|стать).{{0,30}}(yoz|yozib|tuz|{GEN})|(yoz|yozib ber)\b.{{0,30}}(matn|maqola|post|xat)",
                       "site": r"(?i)ask anything|message chatgpt|send a message|savol bering|enter a prompt|сообщение|chat"},
}
# Ma'lum saytlar (domen → imkoniyatlar). Ro'yxat — taxmin: sayt o'zgarsa yoki tarif ruxsat bermasa, bajarishda aniq aytiladi.
KNOWN = {
    "leonardo.ai": ["image.generate", "video.generate"], "ideogram.ai": ["image.generate"], "playground.com": ["image.generate"],
    "firefly.adobe.com": ["image.generate"], "krea.ai": ["image.generate", "video.generate"], "midjourney.com": ["image.generate"],
    "lexica.art": ["image.generate"], "civitai.com": ["image.generate"], "canva.com": ["image.generate"],
    "chatgpt.com": ["text.generate", "image.generate", "translate"], "chat.openai.com": ["text.generate", "image.generate", "translate"],
    "gemini.google.com": ["text.generate", "image.generate", "translate"], "claude.ai": ["text.generate", "translate"],
    "copilot.microsoft.com": ["text.generate", "image.generate"], "chat.deepseek.com": ["text.generate", "translate"],
    "runwayml.com": ["video.generate"], "app.runwayml.com": ["video.generate"], "pika.art": ["video.generate"], "klingai.com": ["video.generate"],
    "suno.com": ["audio.generate"], "elevenlabs.io": ["audio.generate"], "translate.google.com": ["translate"], "deepl.com": ["translate"],
}
FINANCIAL = re.compile(r"(?i)(savdo|sotuv|to'?lov|kirim|chiqim|qaytarish|chek|kassa|oplata|оплат|продаж|приход|расход|payment|refund|invoice)\s*(kirit|qil|yarat|o'?tkaz|ur|провед|созда)")


def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


class SiteSkillError(Exception):
    pass


class SiteSkills:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)

    # ---------------- ko'nikmalar ----------------
    def list(self, conn_id: int | None = None) -> list[dict]:
        rows = self.core.db.query("SELECT s.*, i.name conn_name, i.status conn_status, i.adapter FROM site_skills s JOIN integrations i ON i.id=s.conn_id"
                                  + (" WHERE s.conn_id=?" if conn_id else "") + " ORDER BY s.verified DESC, s.confidence DESC, s.id",
                                  (conn_id,) if conn_id else ())
        for r in rows:
            r["label"] = CAPS.get(r["capability"], {}).get("uz", r["capability"])
        return rows

    def catalog(self) -> dict:
        return {k: {"uz": v["uz"], "icon": v["icon"], "result": v["result"]} for k, v in CAPS.items()}

    def _upsert(self, conn_id, cap, url, *, title=None, source="detected", confidence=0.5, prompt_selector=None, submit_selector=None):
        old = self.core.db.one("SELECT id, source FROM site_skills WHERE conn_id=? AND capability=? AND url=?", (conn_id, cap, url))
        if old:
            if old["source"] == "user":                    # foydalanuvchi sozlagan ko'nikma avtomatik o'zgartirilmaydi
                return old["id"]
            self.core.db.execute("UPDATE site_skills SET confidence=MAX(confidence, ?), prompt_selector=COALESCE(?, prompt_selector), "
                                 "submit_selector=COALESCE(?, submit_selector) WHERE id=?", (confidence, prompt_selector, submit_selector, old["id"]))
            return old["id"]
        return self.core.db.execute(
            "INSERT INTO site_skills(conn_id, capability, title, url, prompt_selector, submit_selector, source, confidence) VALUES (?,?,?,?,?,?,?,?)",
            (conn_id, cap, title or CAPS[cap]["uz"], url, prompt_selector, submit_selector, source, confidence)).lastrowid

    def detect(self, conn_id: int, pages: list[dict] | None = None) -> list[dict]:
        """Ulanish uchun ko'nikmalarni aniqlash: ma'lum domen + o'rganilgan sahifalardagi so'rov maydoni va tugmalar."""
        c = self.core.integrations.get(conn_id)
        if c["adapter"] != "website":
            return []
        base = (c.get("config") or {}).get("base_url", "")
        for dom, caps in KNOWN.items():
            if _host(base) == dom or _host(base).endswith("." + dom):
                for cap in caps:
                    self._upsert(conn_id, cap, base, source="preset", confidence=0.6)
        for p in pages or []:
            if not p.get("prompts"):
                continue                                      # so'rov maydoni yo'q sahifa — generatsiya sahifasi emas
            text = " ".join([p.get("title") or ""] + (p.get("buttons") or []) + [x.get("hint", "") for x in p["prompts"]])
            for cap, spec in CAPS.items():
                if re.search(spec["site"], text):
                    strong = bool(re.search(spec["site"].replace("|generate|create", ""), text))
                    pr = p["prompts"][0]
                    self._upsert(conn_id, cap, p["url"], title=f"{CAPS[cap]['uz']} — {(p.get('title') or '')[:40]}".strip(" —"),
                                 confidence=0.7 if strong else 0.4, prompt_selector=pr.get("selector"))
        self.core.audit.log("site_skills", f"Ko'nikmalar aniqlandi: {c['name']}", target=f"conn#{conn_id}", risk="A")
        return self.list(conn_id)

    def save(self, conn_id: int, capability: str, url: str, title: str = "", prompt_selector: str = "", submit_selector: str = "",
             result_selector: str = "", skill_id: int | None = None) -> dict:
        if capability not in CAPS:
            raise SiteSkillError("Noma'lum imkoniyat")
        c = self.core.integrations.get(conn_id)
        if c["adapter"] != "website":
            raise SiteSkillError("Hozircha ko'nikmalar faqat veb-sayt ulanishlari uchun")
        base = (c.get("config") or {}).get("base_url", "")
        url = (url or base).strip()
        if _host(url) != _host(base):
            raise SiteSkillError("Ko'nikma sahifasi shu ulanish domenida bo'lishi kerak")
        vals = (capability, title or CAPS[capability]["uz"], url, prompt_selector or None, submit_selector or None, result_selector or None)
        if skill_id:
            self.core.db.execute("UPDATE site_skills SET capability=?, title=?, url=?, prompt_selector=?, submit_selector=?, result_selector=?, "
                                 "source='user', verified=0 WHERE id=? AND conn_id=?", (*vals, skill_id, conn_id))
        else:
            skill_id = self.core.db.execute("INSERT OR REPLACE INTO site_skills(capability, title, url, prompt_selector, submit_selector, result_selector, "
                                            "conn_id, source, confidence) VALUES (?,?,?,?,?,?,?, 'user', 0.9)", (*vals, conn_id)).lastrowid
        self.core.audit.log("user", f"Sayt ko'nikmasi saqlandi: {c['name']} → {capability}", target=f"conn#{conn_id}", risk="B")
        return self.get(skill_id)

    def get(self, skill_id: int) -> dict:
        r = self.core.db.one("SELECT s.*, i.name conn_name, i.status conn_status FROM site_skills s JOIN integrations i ON i.id=s.conn_id WHERE s.id=?", (skill_id,))
        if not r:
            raise SiteSkillError("Ko'nikma topilmadi")
        r["label"] = CAPS.get(r["capability"], {}).get("uz", r["capability"])
        return r

    def delete(self, skill_id: int) -> dict:
        self.get(skill_id)
        self.core.db.execute("DELETE FROM site_skills WHERE id=?", (skill_id,))
        return {"deleted": skill_id}

    # ---------------- Task Router ----------------
    def detect_task(self, text: str) -> str | None:
        for cap, spec in CAPS.items():
            if re.search(spec["intent"], text or ""):
                return cap
        return None

    @staticmethod
    def extract_prompt(text: str) -> str:
        t = (text or "").strip()
        m = re.match(r"(?s)^[^:\n]{0,80}:\s*(.+)$", t)
        if m:
            return m.group(1).strip()
        t = re.sub(r"(?i)\b(jarvis|iltimos|menga|mana|uchun|bitta|qilib ber(ing)?|yaratib ber(ing)?|chizib ber(ing)?|generatsiya|generate|create|"
                   r"yarat|chiz|ber|saytida|saytda|orqali|dan foydalanib)\b[,]?", " ", t)
        return re.sub(r"\s{2,}", " ", t).strip(" ,.") or (text or "").strip()

    def _agents(self, cap: str) -> list[dict]:
        c, out = self.core, []
        if cap == "image.generate":
            ig = c.imagegen.status()["generator"]
            out.append({"kind": "agent", "agent": "imagegen", "name": "JARVIS rasm agenti (mahalliy Stable Diffusion)", "available": bool(ig.get("available")),
                        "note": "" if ig.get("available") else ig.get("note", "sozlanmagan"), "approval": False})
        elif cap in ("text.generate", "translate"):
            ok = bool(c.ai.available()[0])
            out.append({"kind": "agent", "agent": "ai", "name": "JARVIS AI (chat)", "available": ok, "note": "" if ok else "AI ulanmagan", "approval": False})
        elif cap == "audio.generate":
            vp = c.voice_pro.tts_engine()
            ok = vp not in ("browser", "none")
            out.append({"kind": "agent", "agent": "tts", "name": f"JARVIS ovoz agenti (TTS: {vp})", "available": ok,
                        "note": "" if ok else "faqat brauzer ovozi — fayl yaratilmaydi", "approval": False})
        elif cap == "video.generate":
            out.append({"kind": "agent", "agent": "none", "name": "JARVIS o'zi video yarata olmaydi", "available": False,
                        "note": "Video Studio faqat montaj qiladi (FFmpeg). Video yaratish uchun Runway/Pika/Kling kabi saytni ulang.", "approval": False})
        return out

    def plan(self, text: str, capability: str | None = None) -> dict:
        if FINANCIAL.search(text or ""):
            return {"capability": None, "financial": True, "options": [],
                    "text": "Bu moliyaviy yozuv (savdo/to'lov/kirim/chiqim). Ular sayt orqali avtomatik kiritilmaydi — Ulanishlar → "
                            "'Tashqi tizimga yozish takliflari' orqali alohida tasdiq bilan bajariladi."}
        cap = capability or self.detect_task(text)
        if not cap:
            return {"capability": None, "options": [], "text": "Topshiriq turi aniqlanmadi"}
        prompt = self.extract_prompt(text)
        low = (text or "").lower()
        opts = []
        for s in self.list():
            if s["capability"] != cap or not s["enabled"]:
                continue
            c = self.core.integrations.get(s["conn_id"])
            dom = _host((c.get("config") or {}).get("base_url", ""))
            named = bool(dom and (dom.split(".")[0] in low or s["conn_name"].lower() in low))
            opts.append({"kind": "site", "skill_id": s["id"], "conn_id": s["conn_id"], "name": f"{s['conn_name']} ({dom})", "url": s["url"],
                         "available": s["conn_status"] == "connected", "verified": bool(s["verified"]), "named": named, "source": s["source"],
                         "note": ("" if s["conn_status"] == "connected" else f"ulanish holati: {s['conn_status']}")
                         + ("" if s["verified"] else " · hali sinalmagan (birinchi bajarishda tekshiriladi)"), "approval": True,
                         "_rank": (named, s["conn_status"] == "connected", bool(s["verified"]), s["confidence"])})
        opts.sort(key=lambda o: o["_rank"], reverse=True)
        for o in opts:
            o.pop("_rank")
        opts += self._agents(cap)
        choice = next((i for i, o in enumerate(opts) if o["available"]), None)
        spec = CAPS[cap]
        if choice is None:
            msg = (f"{spec['icon']} {spec['uz']}: hozir buni bajaradigan ulangan sayt ham, ishlaydigan JARVIS agenti ham yo'q. "
                   "Mos saytni (masalan, rasm uchun Leonardo/Ideogram) Ulanishlar → havola orqali ulang.")
        else:
            o = opts[choice]
            msg = (f"{spec['icon']} {spec['uz']} — {'ulangan sayt' if o['kind'] == 'site' else 'JARVIS agenti'}: {o['name']}. "
                   + ("Saytda bajarish sizning hisobingizdan bo'ladi — tasdiqlang." if o["approval"] else "Bajarish uchun tasdiqlang."))
        return {"capability": cap, "label": spec["uz"], "icon": spec["icon"], "result": spec["result"], "prompt": prompt, "options": opts,
                "choice": choice, "text": msg}

    # ---------------- bajarish ----------------
    def propose(self, skill_id: int, prompt: str, requested_by: str = "user") -> dict:
        s = self.get(skill_id)
        prompt = (prompt or "").strip()
        if not prompt:
            raise SiteSkillError("So'rov matni bo'sh")
        if len(prompt) > 4000:
            raise SiteSkillError("So'rov juda uzun (≤4000 belgi)")
        if contains_secret(prompt):
            raise SiteSkillError("So'rovda parol/token bor ko'rinadi — saytga yuborilmaydi")
        if int(self.core.settings.autonomy_level) <= 0:
            raise SiteSkillError("Avtonomlik Level 0 (faqat maslahat) — saytda amal bajarilmaydi")
        if s["conn_status"] != "connected":
            raise SiteSkillError(f"'{s['conn_name']}' ulanmagan (holat: {s['conn_status']}) — avval Ulanishlar'da 'Tekshirish'")
        payload = {"skill_id": s["id"], "conn_id": s["conn_id"], "capability": s["capability"], "url": s["url"], "prompt": prompt}
        appr = self.core.approvals.request(action_type="site_action", target=f"conn#{s['conn_id']}", level="D", payload=payload,
                                           summary=f"«{s['conn_name']}» saytida {s['label'].lower()}: «{prompt[:80]}»",
                                           requested_by=requested_by, purpose="Foydalanuvchi topshirig'i ulangan sayt orqali")
        return {"approval": appr, "skill": s}

    def execute(self, approval_id: int) -> dict:
        c = self.core
        appr = c.approvals.get(approval_id)
        if appr["action_type"] != "site_action":
            raise SiteSkillError("Bu tasdiq sayt amali emas")
        p = appr["payload"]
        c.approvals.authorize_execution(approval_id, p)
        if getattr(c, "automation_paused", False):
            raise SiteSkillError("Favqulodda to'xtatish yoqilgan")
        s = self.get(p["skill_id"])
        if s["url"] != p["url"]:
            raise SiteSkillError("Ko'nikma tasdiqdan keyin o'zgargan — qayta tasdiqlang")
        conn = c.integrations.get(p["conn_id"])
        out_dir = Path(c.settings.allowed_write_dirs[0]) / "exports" / "site"
        run_id = c.db.execute("INSERT INTO site_runs(skill_id, conn_id, approval_id, capability, prompt, status) VALUES (?,?,?,?,?, 'running')",
                              (s["id"], s["conn_id"], approval_id, s["capability"], redact(p["prompt"])[:500])).lastrowid
        from .integrations.base import ConnectorError
        try:
            res = c.integrations.connector(conn).perform(s | {"result": CAPS[s["capability"]]["result"]}, p["prompt"], out_dir, run_id)
            ok = bool(res.get("outputs") or res.get("text"))
            status = "ok" if ok else "no_result"
            err = None if ok else "Natija topilmadi (sayt javob bermadi yoki natija boshqa joyda) — skrinshotni ko'ring"
        except ConnectorError as e:
            res, status, err = {"outputs": [], "text": ""}, getattr(e, "status", "error"), str(e)
        except Exception as e:                               # noqa: BLE001 — brauzer xatosi ham halol yoziladi
            res, status, err = {"outputs": [], "text": ""}, "error", f"{type(e).__name__}: {str(e)[:200]}"
        c.approvals.mark_result(approval_id, "executed" if status in ("ok", "no_result") else "unknown")
        c.db.execute("UPDATE site_runs SET status=?, outputs=?, text=?, error=? WHERE id=?",
                     (status, json.dumps(res.get("outputs", []) + ([res["screenshot"]] if res.get("screenshot") else []), ensure_ascii=False),
                      (res.get("text") or "")[:8000], err, run_id))
        c.db.execute("UPDATE site_skills SET runs=runs+1, last_run=datetime('now'), last_status=?" + (", verified=1" if status == "ok" else "") + " WHERE id=?",
                     (status, s["id"]))
        c.audit.log("site_skills", f"Sayt amali: {s['conn_name']} → {s['capability']}: {status}", target=f"conn#{s['conn_id']}", risk="D",
                    approval_status="approved", result=status)
        ev = getattr(c, "events", None)
        if ev:
            ev.publish("site_action", conn=s["conn_name"], capability=s["capability"], status=status)
        return {"run_id": run_id, "status": status, "error": err, "outputs": res.get("outputs", []), "text": res.get("text", ""),
                "screenshot": res.get("screenshot"), "site": s["conn_name"], "verified": status == "ok",
                "note": "Natija saytdan olindi va JARVIS papkasiga saqlandi." if status == "ok" else ""}

    def run_agent(self, agent: str, capability: str, prompt: str) -> dict:
        """JARVIS'ning o'z agentlari bilan (sayt o'rniga)."""
        c = self.core
        if contains_secret(prompt or ""):
            raise SiteSkillError("So'rovda maxfiy ma'lumot bor")
        if agent == "imagegen" and capability == "image.generate":
            r = c.imagegen.generate(prompt)
            return {"status": "ok", "outputs": r["outputs"], "text": r.get("note", ""), "site": "JARVIS rasm agenti"}
        if agent == "ai" and capability in ("text.generate", "translate"):
            q = prompt if capability == "text.generate" else f"Quyidagi matnni tarjima qil (agar til ko'rsatilmagan bo'lsa — o'zbekchaga):\n{prompt}"
            r = c.chat(q)
            return {"status": "ok", "outputs": [], "text": r.get("text", ""), "site": "JARVIS AI"}
        if agent == "tts" and capability == "audio.generate":
            from datetime import datetime
            data, mime, eng = c.voice_pro.synth(prompt)
            d = Path(c.settings.allowed_write_dirs[0]) / "exports"
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"ovoz_{datetime.now():%Y%m%d_%H%M%S}.{'mp3' if 'mpeg' in mime else 'wav'}"
            f.write_bytes(data)
            return {"status": "ok", "outputs": [str(f)], "text": f"Ovoz: {eng}", "site": "JARVIS ovoz agenti"}
        raise SiteSkillError("Bu agent bu topshiriqni bajara olmaydi")

    def runs(self, limit: int = 50) -> list[dict]:
        rows = self.core.db.query("SELECT * FROM site_runs ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["outputs"] = json.loads(r["outputs"]) if r.get("outputs") else []
        return rows
