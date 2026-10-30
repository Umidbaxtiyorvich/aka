"""Memory Import Center — ChatGPT eksport ZIP faylidan JARVIS xotirasini yaratish (foydalanuvchi tasdig'i bilan).

Xavfsizlik va halollik:
* ZIP diskka ochilmaydi: a'zolar xotirada, hajm/soni/siqish nisbati cheklovlari bilan o'qiladi; mutlaq yo'l, `..`,
  symlink va zip-bomba rad etiladi. Yuklangan ZIP tahlildan keyin o'chiriladi (faqat nomzodlar qoladi).
* Tahlil to'liq MAHALLIY (qoidalar asosida) — shaxsiy suhbatlar hech qaysi tashqi AI provayderiga yuborilmaydi.
* Eski suhbatlardagi buyruqlar bajarilmaydi: ular faqat "tarixiy ma'lumot" sifatida nomzod bo'ladi va foydalanuvchi
  tasdiqlamaguncha xotiraga yozilmaydi. Faktlar faqat FOYDALANUVCHI xabarlaridan olinadi (assistent javoblaridan emas).
* Parol/token/kalit bor jumlalar o'tkazib yuboriladi. ChatGPT'ning ichki (yashirin) "Memory" funksiyasi eksportda
  bo'lmaydi — faqat suhbatlar asosida xotira yaratiladi.
"""
from __future__ import annotations

import difflib
import json
import re
import threading
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .config import jarvis_home
from .security import contains_secret, redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL DEFAULT 'chatgpt', filename TEXT, size INTEGER, status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0, stats TEXT, error TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS memory_import_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, import_id INTEGER NOT NULL, category TEXT NOT NULL, title TEXT, content TEXT NOT NULL,
    conv_id TEXT, conv_title TEXT, conv_date TEXT, confidence REAL NOT NULL DEFAULT 0.5, evidence INTEGER NOT NULL DEFAULT 1,
    info_type TEXT NOT NULL DEFAULT 'user_given', flags TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'pending',
    duplicate_of INTEGER, conflict_note TEXT, memory_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_mii_imp ON memory_import_items(import_id, category, status);
"""

CATEGORIES = {"profile": ("User Profile", "semantic"), "communication": ("Communication Preferences", "preference"),
              "projects": ("Projects", "project"), "work": ("Work & Business", "knowledge"), "technical": ("Technical Knowledge", "technical"),
              "devices": ("Devices & Environment", "technical"), "goals": ("Goals", "long_term"), "conversations": ("Past Conversations", "conversation"),
              "decisions": ("Decisions", "decision"), "skills": ("Skills", "semantic"), "instructions": ("Important Instructions", "preference"),
              "long_term": ("Long-term Memory", "long_term")}

MAX_UPLOAD = 512 * 2**20
MAX_MEMBERS = 50_000
MAX_MEMBER = 400 * 2**20
MAX_TOTAL = 2 * 2**30
MAX_RATIO = 200

TECH = ["python", "fastapi", "django", "flask", "javascript", "typescript", "react", "vue", "next.js", "node", "html", "css", "sql", "sqlite",
        "postgresql", "mysql", "mongodb", "redis", "docker", "kubernetes", "git", "github", "linux", "windows", "powershell", "excel", "1c",
        "telegram", "instagram", "ollama", "openai", "claude", "gemini", "whisper", "ffmpeg", "playwright", "pandas", "pytorch", "tensorflow",
        "java", "kotlin", "swift", "flutter", "c#", "c++", "php", "laravel", "go", "rust", "aws", "azure", "figma", "wordpress", "pos"]
STOP = set("va bilan uchun haqida qanday nima qilish yordam men menga bu shu the and for how what with to of in a an on is are my как что для это "
           "new chat yangi suhbat".split())

P = {  # (kategoriya, regex) — faqat foydalanuvchi jumlalariga
    "profile": re.compile(r"(?i)\b(mening ismim|ismim\s+\w+|my name is|меня зовут|men\s+\w+\s+yoshdaman|i am \d+ years|мне \d+ лет|yashayman|i live in|я живу)"),
    "devices": re.compile(r"(?i)\b(windows\s?\d+|macos|macbook|ubuntu|linux|\d+\s?gb\s?(ram|озу)|gtx\s?\d{3,4}|rtx\s?\d{3,4}|ryzen|intel core|core i[3579]|iphone|android|"
                          r"noutbuk|laptop|kompyuterim|my (pc|computer)|мой (компьютер|ноутбук)|ssd|vram)"),
    "communication": re.compile(r"(?i)(o'?zbek tilida|ruscha|in english|на русском|qisqa(roq)? (javob|yoz)|batafsil (yoz|tushuntir)|step[- ]by[- ]step|"
                                r"bosqichma-bosqich|oddiy tilda|javobni .* (yoz|ber)|answer (in|briefly|short)|respond in|отвечай|пиши (кратко|подробно))"),
    "instructions": re.compile(r"(?i)\b(har doim|doimo|hech qachon|always|never|всегда|никогда|majburiy|shart emas|qat'iy|unutma|don't forget|не забудь)\b"),
    "goals": re.compile(r"(?i)\b(maqsadim|rejam|xohlayman|istayman|niyatim|i want to|my goal|i plan to|хочу|моя цель|планирую)\b"),
    "decisions": re.compile(r"(?i)\b(qaror qildim|qaror qildik|tanladim|tanladik|hal qildim|decided|we will use|i chose|решил|решили|выбрал)\b"),
    "skills": re.compile(r"(?i)\b(bilaman|tajribam bor|men dasturchiman|i know how|i'm experienced|i am a developer|умею|я знаю|я разработчик)\b"),
    "work": re.compile(r"(?i)\b(do'?konim|do'?konimiz|biznesim|biznesimiz|kompaniyam|firmam|ishxonam|mijozlarim|my (shop|store|business|company)|"
                       r"our (shop|store|business|company)|мой (магазин|бизнес)|наш (магазин|бизнес)|ishlayman|i work (at|as)|работаю)\b"),
    "projects": re.compile(r"(?i)(loyiham|loyihamiz|loyiha ustida|my project|our project|мой проект|github\.com/[\w.-]+/[\w.-]+|repo(sitory)?\b)"),
}
SLOTS = {"name": re.compile(r"(?i)(?:mening ismim|my name is|меня зовут)\s+([A-ZА-ЯЁa-zа-яё][\w'’-]{1,30})"),
         "city": re.compile(r"(?i)(?:([A-ZА-Я][\w'’-]{2,30})(?:da|de) yashayman|i live in ([A-Z][\w-]{2,30})|я живу в ([А-ЯA-Z][\w-]{2,30}))"),
         "ram": re.compile(r"(?i)\b(\d{1,3})\s?gb\s?(?:ram|озу)"),
         "gpu": re.compile(r"(?i)\b((?:gtx|rtx)\s?\d{3,4}(?:\s?ti)?)"),
         "os": re.compile(r"(?i)\b(windows\s?(?:7|8|10|11)|macos|ubuntu)")}
UNFINISHED = re.compile(r"(?i)\b(davom et|keyin|keyinroq|ertaga|tugatamiz|continue|later|tomorrow|продолж|потом|todo)\b")


class ImportError_(Exception):
    pass


def _norm(s: str) -> str:
    return re.sub(r"[^\w\s]", "", s.lower()).strip()


def _date(ts) -> str | None:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return None


def safe_members(z: zipfile.ZipFile) -> tuple[list[zipfile.ZipInfo], list[str]]:
    """Xavfli a'zolarni rad etadi. Qaytaradi: (xavfsiz a'zolar, ogohlantirishlar)."""
    infos, warn, total = z.infolist(), [], 0
    if len(infos) > MAX_MEMBERS:
        raise ImportError_(f"Arxivda juda ko'p fayl ({len(infos)} > {MAX_MEMBERS})")
    ok = []
    for i in infos:
        name = i.filename.replace("\\", "/")
        pp = PurePosixPath(name)
        if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in pp.parts:
            warn.append(f"rad etildi (xavfli yo'l): {name[:80]}")
            continue
        if (i.external_attr >> 16) & 0o170000 == 0o120000:
            warn.append(f"rad etildi (symlink): {name[:80]}")
            continue
        if i.is_dir():
            continue
        if i.file_size > MAX_MEMBER:
            warn.append(f"o'tkazib yuborildi (juda katta): {name[:80]}")
            continue
        if i.file_size > 10 * 2**20 and i.compress_size and i.file_size / i.compress_size > MAX_RATIO:
            warn.append(f"rad etildi (zip-bomba belgisi): {name[:80]}")
            continue
        total += i.file_size
        if total > MAX_TOTAL:
            raise ImportError_("Arxiv ochilgandagi umumiy hajm 2 GB dan oshadi")
        ok.append(i)
    return ok, warn


def _read(z: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    with z.open(info) as f:                         # e'lon qilingan hajmga ishonmasdan, o'qishni ham cheklaymiz
        data = f.read(MAX_MEMBER + 1)
    if len(data) > MAX_MEMBER:
        raise ImportError_(f"{info.filename}: juda katta")
    return data


def thread_messages(conv: dict) -> list[dict]:
    """ChatGPT `mapping` daraxtidan asosiy tarmoq (current_node → ildiz) bo'yicha xabarlar."""
    mapping = conv.get("mapping") or {}
    node, seen, chain = conv.get("current_node"), set(), []
    if not node or node not in mapping:                          # current_node yo'q — eng uzun yo'l emas, vaqt bo'yicha
        msgs = [n.get("message") for n in mapping.values() if n.get("message")]
        msgs.sort(key=lambda m: m.get("create_time") or 0)
    else:
        while node and node in mapping and node not in seen:
            seen.add(node)
            chain.append(mapping[node].get("message"))
            node = mapping[node].get("parent")
        msgs = [m for m in reversed(chain) if m]
    out = []
    for m in msgs:
        role = ((m.get("author") or {}).get("role")) or ""
        if role not in ("user", "assistant"):
            continue
        meta = m.get("metadata") or {}
        if meta.get("is_visually_hidden_from_conversation"):
            continue
        parts = (m.get("content") or {}).get("parts") or []
        text = "\n".join(p for p in parts if isinstance(p, str)).strip()
        if (m.get("content") or {}).get("content_type") == "code" and not text:
            text = (m.get("content") or {}).get("text", "")
        if text:
            out.append({"role": role, "text": text, "date": _date(m.get("create_time"))})
    return out


def html_conversations(html: str) -> list[dict]:
    """Yangi eksportlarda chat.html ichida `jsonData = [...]` bo'ladi — shuni o'qiymiz (HTML'ni bajarmasdan)."""
    i = html.find("jsonData")
    if i < 0:
        return []
    j = html.find("[", i)
    try:
        data, _ = json.JSONDecoder().raw_decode(html[j:])
        return data if isinstance(data, list) else []
    except (ValueError, IndexError):
        return []


def sentences(text: str) -> list[str]:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)          # kod bloklari fakt emas
    text = re.sub(r"`[^`]*`", " ", text)
    out = []
    for s in re.split(r"(?<=[.!?])\s+|\n+", text):
        s = s.strip(" -*•\t")
        if 12 <= len(s) <= 300:
            out.append(s)
    return out


class MemoryImporter:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    @property
    def dir(self) -> Path:
        d = jarvis_home() / "imports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---------------- qabul qilish ----------------
    def start(self, filename: str, data: bytes, background: bool = True) -> dict:
        name = Path(filename or "chatgpt_export.zip").name[:120]
        if not name.lower().endswith(".zip"):
            raise ImportError_("Faqat .zip fayl (ChatGPT → Settings → Data controls → Export data)")
        if len(data) > MAX_UPLOAD:
            raise ImportError_("ZIP 512 MB dan katta")
        cur = self.core.db.execute("INSERT INTO memory_imports(filename, size, status) VALUES (?,?,?)", (name, len(data), "analyzing"))
        iid = cur.lastrowid
        path = self.dir / f"import_{iid}.zip"
        path.write_bytes(data)
        self.core.audit.log("memory_import", f"ChatGPT eksporti yuklandi: {name} ({len(data)} bayt)", target=f"import#{iid}", risk="B", approval_status="user_action")
        if background:
            threading.Thread(target=self._run, args=(iid, path), daemon=True).start()
        else:
            self._run(iid, path)
        return self.get(iid)

    def _run(self, iid: int, path: Path):
        try:
            stats = self.analyze(iid, path)
            self.core.db.execute("UPDATE memory_imports SET status='ready', progress=100, stats=? WHERE id=?", (json.dumps(stats, ensure_ascii=False), iid))
        except (ImportError_, zipfile.BadZipFile, ValueError, KeyError, OSError) as e:
            self.core.db.execute("UPDATE memory_imports SET status='failed', error=? WHERE id=?", (redact(str(e))[:300], iid))
        finally:
            try:
                path.unlink()                                    # shaxsiy arxiv saqlanmaydi
            except OSError:
                pass

    def _progress(self, iid: int, pct: int):
        self.core.db.execute("UPDATE memory_imports SET progress=? WHERE id=?", (pct, iid))

    # ---------------- tahlil ----------------
    def analyze(self, iid: int, path: Path) -> dict:
        with zipfile.ZipFile(path) as z:
            members, warnings = safe_members(z)
            listing = [{"name": m.filename, "size": m.file_size} for m in members[:500]]
            by_name = {PurePosixPath(m.filename).name.lower(): m for m in members}
            convs, fmt = [], None
            if "conversations.json" in by_name:
                convs, fmt = json.loads(_read(z, by_name["conversations.json"]).decode("utf-8", "replace")), "conversations.json"
            elif "chat.html" in by_name:
                convs, fmt = html_conversations(_read(z, by_name["chat.html"]).decode("utf-8", "replace")), "chat.html (jsonData)"
            if not isinstance(convs, list) or (not convs and not fmt):
                raise ImportError_("Bu ChatGPT eksporti emas: conversations.json yoki chat.html topilmadi")
            other = sorted(n for n in by_name if n.endswith(".json") and n != "conversations.json")
        self._progress(iid, 10)
        cands: dict[str, list[dict]] = defaultdict(list)
        slots: dict[str, list[tuple[str, str, int]]] = defaultdict(list)       # slot → [(qiymat, sana, cand index)]
        tech, words, skipped_secret, total_msgs, user_msgs = Counter(), Counter(), 0, 0, 0
        convs = sorted((c for c in convs if isinstance(c, dict)), key=lambda c: c.get("create_time") or 0)
        n = len(convs)

        def add(cat, content, conv, date, info_type="user_given", flags=(), title=None, conf=0.55):
            if contains_secret(content):
                return None
            key = _norm(content)
            for c in cands[cat][-300:]:
                if c["_key"] == key or (abs(len(c["_key"]) - len(key)) < 40 and difflib.SequenceMatcher(None, c["_key"], key).ratio() >= 0.88):
                    c["evidence"] += 1
                    c["confidence"] = min(0.95, c["confidence"] + 0.1)
                    if date and (not c["conv_date"] or date > c["conv_date"]):
                        c["conv_date"] = date
                    return c
            c = {"_key": key, "category": cat, "content": content, "title": title, "conv_id": conv.get("id") or conv.get("conversation_id"),
                 "conv_title": (conv.get("title") or "")[:120], "conv_date": date, "confidence": conf, "evidence": 1, "info_type": info_type,
                 "flags": list(flags)}
            cands[cat].append(c)
            return c

        for k, conv in enumerate(convs):
            msgs = thread_messages(conv)
            total_msgs += len(msgs)
            title = (conv.get("title") or "Nomsiz suhbat").strip()
            cdate = _date(conv.get("create_time"))
            users = [m for m in msgs if m["role"] == "user"]
            user_msgs += len(users)
            for w in re.findall(r"[^\W\d_][\w'’+#.-]{2,}", title.lower()):
                if w not in STOP:
                    words[w] += 1
            if users:
                first = re.sub(r"\s+", " ", redact(users[0]["text"]))[:160]
                unfinished = bool(msgs and msgs[-1]["role"] == "user") or bool(UNFINISHED.search(users[-1]["text"][-200:]))
                add("conversations", f"Suhbat «{title[:80]}» ({cdate or 'sana yo‘q'}, {len(msgs)} xabar): {first}", conv, cdate,
                    flags=["unfinished"] if unfinished else [], title=f"Suhbat: {title[:60]}", conf=0.7)
            for m in users:
                low = m["text"].lower()
                for t in TECH:
                    if re.search(rf"(?<![\w]){re.escape(t)}(?![\w])", low):
                        tech[t] += 1
                for s in sentences(m["text"]):
                    if contains_secret(s):
                        skipped_secret += 1
                        continue
                    for cat, rx in P.items():
                        if rx.search(s):
                            flags = ["historical_instruction"] if cat in ("instructions", "communication") else []
                            c = add(cat, s, conv, m["date"] or cdate, flags=flags, title=f"{CATEGORIES[cat][0]}: {s[:50]}")
                            if c is not None:
                                for slot, srx in SLOTS.items():
                                    mm = srx.search(s)
                                    if mm:
                                        val = next(g for g in mm.groups() if g).strip().lower()
                                        slots[slot].append((val, m["date"] or cdate or "", id(c)))
                            break
            if n and k % max(1, n // 20) == 0:
                self._progress(iid, 10 + int(70 * k / n))
        # Loyihalar: ko'p uchraydigan sarlavha so'zlari (taxmin)
        for w, cnt in words.most_common(15):
            if cnt >= 3:
                add("projects", f"Ko'p muhokama qilingan mavzu: «{w}» ({cnt} ta suhbat sarlavhasida)", {}, None, info_type="assumption",
                    title=f"Mavzu: {w}", conf=min(0.8, 0.4 + cnt * 0.05))
        if tech:
            add("technical", "Suhbatlarda ko'p tilga olingan texnologiyalar: " + ", ".join(f"{t} ({c})" for t, c in tech.most_common(15)), {}, None,
                info_type="assumption", title="Texnologiyalar", conf=0.7)
        # Qarama-qarshiliklar: bitta "slot" uchun turli qiymatlar
        conflicts = {}
        by_id = {id(c): c for lst in cands.values() for c in lst}
        for slot, vals in slots.items():
            distinct = {v for v, _, _ in vals}
            if len(distinct) > 1:
                newest = max(vals, key=lambda x: x[1])
                conflicts[slot] = sorted(distinct)
                for v, d, cid in vals:
                    c = by_id[cid]
                    c["flags"] = sorted(set(c["flags"]) | {"conflict"})
                    c["conflict_note"] = f"{slot}: turli qiymatlar {sorted(distinct)}; eng yangisi «{newest[0]}» ({newest[1] or '?'})" + ("" if v == newest[0] else " — bu eski bo'lishi mumkin")
        self._progress(iid, 85)
        # Mavjud JARVIS xotirasi bilan takror
        db, dup = self.core.db, 0
        for cat, lst in cands.items():
            for c in lst[:3000]:
                status, dup_of = "pending", None
                try:
                    hits = self.core.memory.search(" OR ".join(sorted({w for w in re.findall(r"\w{4,}", c["content"].lower())})[:6]) or c["content"][:20], limit=5)
                except Exception:
                    hits = []
                for h in hits:
                    if difflib.SequenceMatcher(None, _norm(h["content"]), c["_key"]).ratio() >= 0.9:
                        status, dup_of = "duplicate", h["id"]
                        dup += 1
                        break
                db.execute("INSERT INTO memory_import_items(import_id, category, title, content, conv_id, conv_title, conv_date, confidence, evidence, info_type, flags, "
                           "status, duplicate_of, conflict_note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (iid, cat, c["title"], c["content"], c["conv_id"], c["conv_title"], c["conv_date"], round(c["confidence"], 2), c["evidence"],
                            c["info_type"], json.dumps(c["flags"]), status, dup_of, c.get("conflict_note")))
        dates = [d for d in (_date(c.get("create_time")) for c in convs) if d]
        return {"format": fmt, "conversations": n, "messages": total_msgs, "user_messages": user_msgs, "files_in_zip": len(members),
                "listing": listing, "other_json": other[:30], "warnings": warnings[:50], "period": [min(dates), max(dates)] if dates else None,
                "topics": [w for w, _ in words.most_common(20)], "technologies": dict(tech.most_common(20)),
                "candidates": {k: len(v) for k, v in cands.items()}, "duplicates_existing": dup, "conflicts": conflicts,
                "skipped_secret_sentences": skipped_secret,
                "note": "Tahlil mahalliy (tashqi AI'ga yuborilmadi). ChatGPT'ning ichki 'Memory' funksiyasi eksportda yo'q — xotira suhbatlardan tuzildi. "
                        "user.json kabi shaxsiy fayllar avtomatik import qilinmaydi."}

    # ---------------- ko'rish / tasdiqlash ----------------
    def get(self, iid: int) -> dict:
        r = self.core.db.one("SELECT * FROM memory_imports WHERE id=?", (iid,))
        if not r:
            raise ImportError_("Import topilmadi")
        r["stats"] = json.loads(r["stats"]) if r["stats"] else None
        r["counts"] = {x["status"]: x["n"] for x in self.core.db.query("SELECT status, COUNT(*) n FROM memory_import_items WHERE import_id=? GROUP BY status", (iid,))}
        return r

    def list(self) -> list[dict]:
        return [self.get(r["id"]) for r in self.core.db.query("SELECT id FROM memory_imports WHERE status<>'deleted' ORDER BY id DESC LIMIT 50")]

    def items(self, iid: int, category: str = "", status: str = "", q: str = "", limit: int = 200, offset: int = 0) -> list[dict]:
        sql, p = "SELECT * FROM memory_import_items WHERE import_id=?", [iid]
        for col, v in (("category", category), ("status", status)):
            if v:
                sql += f" AND {col}=?"
                p.append(v)
        if q:
            sql += " AND content LIKE ?"
            p.append(f"%{q}%")
        rows = self.core.db.query(sql + " ORDER BY conv_date DESC, id LIMIT ? OFFSET ?", (*p, min(limit, 1000), offset))
        for r in rows:
            r["flags"] = json.loads(r["flags"])
            r["category_label"] = CATEGORIES[r["category"]][0]
        return rows

    def edit(self, item_id: int, content: str | None = None, category: str | None = None) -> dict:
        it = self.core.db.one("SELECT * FROM memory_import_items WHERE id=?", (item_id,))
        if not it or it["status"] == "imported":
            raise ImportError_("Nomzod topilmadi yoki allaqachon import qilingan")
        if category and category not in CATEGORIES:
            raise ImportError_("Noma'lum kategoriya")
        if content is not None:
            if not content.strip() or contains_secret(content):
                raise ImportError_("Bo'sh yoki maxfiy ma'lumotli matn")
        self.core.db.execute("UPDATE memory_import_items SET content=COALESCE(?, content), category=COALESCE(?, category) WHERE id=?",
                             (content.strip() if content else None, category, item_id))
        return {"ok": True}

    def decide(self, iid: int, action: str, ids: list[int] | None = None, category: str = "") -> dict:
        """action: import (tasdiqlab xotiraga yozish) | reject."""
        if action not in ("import", "reject"):
            raise ImportError_("action: import yoki reject")
        sql, p = "SELECT * FROM memory_import_items WHERE import_id=? AND status IN ('pending','duplicate')", [iid]
        if ids:
            sql += f" AND id IN ({','.join('?' * len(ids))})"
            p += [int(i) for i in ids]
        elif category:
            sql += " AND category=? AND status='pending'"
            p.append(category)
        else:
            raise ImportError_("Qaysi nomzodlar: ids yoki category kerak")
        rows = self.core.db.query(sql, tuple(p))
        done, errors = 0, []
        with self._lock:
            for r in rows:
                if action == "reject":
                    self.core.db.execute("UPDATE memory_import_items SET status='rejected' WHERE id=?", (r["id"],))
                    done += 1
                    continue
                label, kind = CATEGORIES[r["category"]]
                content = r["content"] if r["category"] != "instructions" else f"[Tarixiy ko'rsatma, siz tasdiqlagansiz] {r['content']}"
                try:
                    m = self.core.memory.add(content, kind, source="import:chatgpt", confidence=r["confidence"], info_type=r["info_type"],
                                             reference=f"chatgpt:{r['conv_id'] or 'summary'}", observed_at=r["conv_date"],
                                             title=(r["title"] or label)[:120], project=None)
                    self.core.db.execute("UPDATE memory_import_items SET status='imported', memory_id=? WHERE id=?", (m["id"], r["id"]))
                    done += 1
                except Exception as e:
                    errors.append(f"#{r['id']}: {e}")
        self.core.audit.log("memory_import", f"Import #{iid}: {action} {done} ta nomzod", target=f"import#{iid}", risk="B", approval_status="user_action")
        if action == "import" and done:
            self.core.db.execute("UPDATE memory_imports SET status='imported' WHERE id=?", (iid,))
        return {"done": done, "errors": errors[:20]}

    def delete(self, iid: int, purge_memories: bool = False) -> dict:
        self.get(iid)
        purged = 0
        if purge_memories:
            for r in self.core.db.query("SELECT memory_id FROM memory_import_items WHERE import_id=? AND memory_id IS NOT NULL", (iid,)):
                try:
                    self.core.memory.delete(r["memory_id"])
                    purged += 1
                except Exception:
                    pass
        self.core.db.execute("DELETE FROM memory_import_items WHERE import_id=?", (iid,))
        self.core.db.execute("UPDATE memory_imports SET status='deleted', stats=NULL WHERE id=?", (iid,))
        try:
            (self.dir / f"import_{iid}.zip").unlink()
        except OSError:
            pass
        self.core.audit.log("memory_import", f"Import #{iid} o'chirildi (xotiradan ham: {purged})", target=f"import#{iid}", risk="C", approval_status="user_action")
        return {"ok": True, "purged_memories": purged}

    @staticmethod
    def categories() -> dict:
        return {k: v[0] for k, v in CATEGORIES.items()}
