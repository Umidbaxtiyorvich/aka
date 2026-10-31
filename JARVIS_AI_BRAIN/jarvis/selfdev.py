"""Self-Dev — JARVIS o'zini o'zi rivojlantiradi: kamchilikni o'zi topadi, kodni o'zi yozadi, o'zi sinaydi, sizga tayyor
natijani ko'rsatadi; siz bitta "Qabul qilish" bilan rozilik berasiz → u o'zini yangilaydi, qayta ishga tushadi va
yangi versiyani kuzatadi (muammo bo'lsa — o'zi orqaga qaytaradi).

Oqim (har bir g'oya uchun):
  1. G'oya manbalari: "qila olmadim" degan javoblar (agent jurnali), takroriy xatolar (Self-healing), 👎 baholar,
     sizning so'rovingiz ("o'zingni rivojlantir: ..."), ofis xodimlari topgan kamchiliklar.
  2. Dasturchi agent (AI) patch yozadi — faqat ruxsat etilgan papkalarda, himoyalangan fayllar (xavfsizlik, tasdiq,
     maxfiylik, siyosat) O'ZGARTIRILMAYDI; test qo'shishi shart.
  3. Patch alohida nusxada (git worktree) TO'LIQ testdan o'tkaziladi. O'tmasa — xato matnini o'qib, yana 1 marta tuzatadi.
  4. O'tsa — "Ko'rib chiqishga tayyor": nima o'zgardi (fayllar, diff), testlar natijasi. Bildirishnoma + Telegram.
  5. Siz "Qabul qilish"ni bosasiz (yagona inson qarori): alohida branch'ga commit (C) → asosiy versiyaga o'tkazish (E,
     birlashgan holat yana testlanadi) → JARVIS qayta ishga tushadi.
  6. Kuzatuv (15 daqiqa): yangi versiyada xatolar keskin ko'paysa yoki o'z-o'zini tekshiruv o'tmasa — avtomatik
     `git revert` (tarix saqlanadi) va xabar. Orqaga qaytish — xavfsiz tomon, shuning uchun tasdiq so'ramaydi.

Avtomatik (sizdan so'ramay) faqat: g'oyalarni yig'ish, patch yozish va alohida nusxada sinash (asosiy kod o'zgarmaydi).
Asosiy kodga hech narsa sizning "Qabul qilish"ingizsiz kirmaydi. JARVIS bu qoidani o'zgartira olmaydi (selfdev.py va
improve.py — himoyalangan fayllar). Model o'zini qayta o'qitmaydi.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time

from .config import jarvis_home

SCHEMA = """
CREATE TABLE IF NOT EXISTS dev_ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), source TEXT NOT NULL, title TEXT NOT NULL,
    detail TEXT, fingerprint TEXT UNIQUE, status TEXT NOT NULL DEFAULT 'new', proposal_id INTEGER, attempts INTEGER NOT NULL DEFAULT 0,
    note TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), text TEXT, answer TEXT, steps INTEGER,
    errors INTEGER, unable INTEGER NOT NULL DEFAULT 0
);
"""
UNABLE = re.compile(r"(?i)qila olmayman|qila olmadim|imkonim yo'?q|bunday vosita yo'?q|vosita yo'?q|o'?rgatilmagan|qo'?llab-quvvatlanmaydi|"
                    r"hali yo'?q|ulanmagan|i can'?t|not supported|не могу")
WATCH_MIN = 15


class SelfDevError(Exception):
    pass


class SelfDev:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        self._busy = threading.Lock()

    # ---------------- jurnal (agentdan) ----------------
    def log_agent_run(self, text: str, answer: str, steps: list[dict]):
        from .security import redact
        unable = bool(UNABLE.search(answer or ""))
        self.core.db.execute("INSERT INTO agent_runs(text, answer, steps, errors, unable) VALUES (?,?,?,?,?)",
                             (redact(text)[:500], redact(answer or "")[:1000], len(steps), sum(1 for s in steps if s.get("status") == "error"), int(unable)))

    # ---------------- g'oyalar ----------------
    def _add(self, source: str, title: str, detail: str = "") -> int | None:
        fp = hashlib.sha256(re.sub(r"\W+", " ", title.lower()).strip().encode()).hexdigest()[:20]
        if self.core.db.one("SELECT 1 FROM dev_ideas WHERE fingerprint=?", (fp,)):
            return None
        return self.core.db.execute("INSERT INTO dev_ideas(source, title, detail, fingerprint) VALUES (?,?,?,?)",
                                    (source, title[:200], (detail or "")[:3000], fp)).lastrowid

    def request(self, description: str, source: str = "user") -> dict:
        d = (description or "").strip()
        if len(d) < 10:
            raise SelfDevError("Nimani o'rganishi/qo'shishi kerakligini batafsilroq yozing")
        iid = self._add(source, d[:120], d)
        if iid is None:
            raise SelfDevError("Bu g'oya allaqachon ro'yxatda")
        self.activity(f"Yangi rivojlanish g'oyasi: {d[:80]}")
        return self.get(iid)

    def collect(self) -> dict:
        """Kamchiliklarni yig'ish (faqat o'qish): qila olmagan topshiriqlar, takroriy xatolar, past baholar."""
        c, added = self.core, []
        for r in c.db.query("SELECT text, answer FROM agent_runs WHERE unable=1 AND ts >= datetime('now','-14 days') ORDER BY id DESC LIMIT 20"):
            i = self._add("agent_unable", f"Qila olmadim: {r['text'][:100]}",
                          f"Foydalanuvchi so'radi: {r['text']}\nJARVIS javobi: {r['answer']}\nShu turdagi topshiriqni bajara oladigan qil (yangi vosita yoki mavjudini kengaytir).")
            if i:
                added.append(i)
        try:
            for g in c.selfheal.error_groups(days=7):
                if g.get("count", 0) >= 3:
                    i = self._add("errors", f"Takroriy xato: {g.get('module', '')}: {str(g.get('message', ''))[:90]}",
                                  f"Oxirgi 7 kunda {g['count']} marta: {g.get('module')}: {g.get('message')}\nSababini top va tuzat, regressiya testi qo'sh.")
                    if i:
                        added.append(i)
        except Exception:                                   # noqa: BLE001 — manba ishlamasa ham qolganlari yig'iladi
            pass
        try:
            for r in c.db.query("SELECT u.purpose, COUNT(*) n FROM model_feedback f JOIN ai_usage u ON u.id=f.usage_id WHERE f.source='user' "
                                "AND f.score < 0 AND f.ts >= datetime('now','-14 days') GROUP BY u.purpose HAVING n >= 3"):
                i = self._add("feedback", f"Past baho: {r['purpose']} javoblari ({r['n']} ta 👎)",
                              f"'{r['purpose']}' vazifasida foydalanuvchi {r['n']} marta yomon baho berdi. Prompt yoki marshrutni yaxshila.")
                if i:
                    added.append(i)
        except Exception:                                   # noqa: BLE001
            pass
        if added:
            self.activity(f"{len(added)} ta yangi rivojlanish g'oyasi topildi")
        return {"added": len(added), "ideas": self.list()}

    def get(self, iid: int) -> dict:
        r = self.core.db.one("SELECT * FROM dev_ideas WHERE id=?", (iid,))
        if not r:
            raise SelfDevError("G'oya topilmadi")
        if r.get("proposal_id"):
            try:
                p = self.core.improver.get(r["proposal_id"])
                r["proposal"] = {k: p.get(k) for k in ("id", "title", "status", "test_output", "branch", "has_test")}
                r["proposal"]["diff"] = p["diff"][:20000]
                from .improve import diff_paths
                r["proposal"]["files"] = sorted(diff_paths(p["diff"]))
            except Exception:                               # noqa: BLE001
                r["proposal"] = None
        return r

    def list(self, status: str | None = None) -> list[dict]:
        return [self.get(r["id"]) for r in self.core.db.query(
            "SELECT id FROM dev_ideas" + (" WHERE status=?" if status else "") + " ORDER BY id DESC LIMIT 100", (status,) if status else ())]

    def _set(self, iid: int, status: str, note: str = "", **kw):
        cols = ", ".join(f"{k}=?" for k in kw)
        self.core.db.execute(f"UPDATE dev_ideas SET status=?, note=?, updated_at=datetime('now'){', ' + cols if cols else ''} WHERE id=?",
                             (status, note[:1500], *kw.values(), iid))

    def activity(self, text: str, kind: str = "info"):
        off = getattr(self.core, "office_live", None)
        if off:
            off.log("dasturchi", text, kind)

    def status(self) -> dict:
        g = self.core.improver.git_status()
        ai = any(p["kind"] != "offline" and p["available"] for p in self.core.ai.status())
        return {"git": g, "ai": ai, "ready": bool(g.get("ok")) and ai, "busy": self._busy.locked(),
                "note": "" if g.get("ok") and ai else ("AI modeli ulanmagan (kod yozish uchun kerak)" if not ai else g.get("note", "git tayyor emas")),
                "counts": {r["status"]: r["n"] for r in self.core.db.query("SELECT status, COUNT(*) n FROM dev_ideas GROUP BY status")},
                "watch": self._watch_state()}

    # ---------------- ishlab chiqish (avtomatik, asosiy kod o'zgarmaydi) ----------------
    def develop(self, iid: int, background: bool = True) -> dict:
        idea = self.get(iid)
        if idea["status"] not in ("new", "failed"):
            raise SelfDevError(f"Bu g'oya holati: {idea['status']}")
        st = self.status()
        if not st["ready"]:
            raise SelfDevError(st["note"])
        if not self._busy.acquire(blocking=False):
            raise SelfDevError("Dasturchi agent boshqa g'oya ustida ishlayapti — navbatda kuting")
        self._set(iid, "working", "Kod yozilmoqda…")
        self.activity(f"Ishga kirishdim: {idea['title'][:80]}", "work")

        def work():
            try:
                self._develop(idea)
            except Exception as e:                          # noqa: BLE001
                self._set(iid, "failed", f"Xato: {str(e)[:500]}")
                self.activity(f"Bajara olmadim: {idea['title'][:60]} — {str(e)[:120]}", "error")
            finally:
                self._busy.release()
        if background:
            threading.Thread(target=work, daemon=True, name=f"selfdev-{iid}").start()
        else:
            work()
        return self.get(iid)

    def _develop(self, idea: dict):
        imp, iid, feedback = self.core.improver, idea["id"], ""
        for attempt in (1, 2):
            desc = idea["detail"] or idea["title"]
            if feedback:
                desc += f"\n\nOldingi urinish testdan o'tmadi. Test natijasi (oxiri):\n{feedback[-2500:]}\nXatoni tuzatib, butun patch'ni qaytadan yoz."
            prop = imp.feature_request(desc)
            self.core.db.execute("UPDATE dev_ideas SET proposal_id=?, attempts=? WHERE id=?", (prop["id"], attempt, iid))
            self.activity(f"Patch yozildi ({', '.join(prop.get('files', []))}), testlar ishga tushdi…", "work")
            res = imp.test(prop["id"])
            if res["status"] == "tested_pass":
                self._set(iid, "ready", f"Testlar o'tdi ({attempt}-urinish). Ko'rib chiqing va qabul qiling.")
                self.activity(f"✅ Tayyor — ko'rib chiqing: {idea['title'][:80]}", "done")
                self.core.notifier.notify("JARVIS o'zini yaxshiladi — ko'rib chiqing",
                                          f"{idea['title'][:120]}\nTestlar o'tdi. Rivojlanish bo'limida 'Qabul qilish' yoki 'Rad etish'.", category="self_improve")
                return
            feedback = res.get("test_output") or ""
            self.activity(f"Testdan o'tmadi ({attempt}-urinish) — xatoni o'qib qayta yozyapman", "warn")
        self._set(iid, "failed", "2 urinishda ham testdan o'tmadi — asosiy kod o'zgarmadi. Test natijasi takliflar ro'yxatida.")

    def auto_tick(self) -> dict | None:
        """Ofis jadvali chaqiradi: g'oyalarni yig'adi va eng birinchisini ishlab chiqadi (faqat alohida nusxada)."""
        self.collect()
        if not self.status()["ready"] or self._busy.locked():
            return None
        if self.core.db.one("SELECT 1 FROM dev_ideas WHERE status IN ('working','ready')"):
            return None                                     # ko'rib chiqilmagan ish bor — ustma-ust yig'ilmaydi
        nxt = self.core.db.one("SELECT id FROM dev_ideas WHERE status='new' ORDER BY id LIMIT 1")
        return self.develop(nxt["id"]) if nxt else None

    # ---------------- qabul qilish (siz) ----------------
    def accept(self, iid: int, confirm: bool = False) -> dict:
        """Foydalanuvchining 'Qabul qilish' tugmasi: branch'ga commit (C) va asosiy versiyaga o'tkazish (E) — ikkala tasdiq ham
        aynan shu tugma bilan (foydalanuvchi nomidan, audit'da yozilgan), keyin qayta ishga tushish va kuzatuv."""
        if not confirm:
            raise SelfDevError("Tasdiqlash kerak (confirm=true)")
        idea = self.get(iid)
        if idea["status"] != "ready" or not idea.get("proposal_id"):
            raise SelfDevError("Faqat 'tayyor' g'oya qabul qilinadi")
        imp, ap, pid = self.core.improver, self.core.approvals, idea["proposal_id"]
        a1 = imp.request_apply(pid)
        if a1["status"] == "pending":
            ap.decide(a1["id"], True, a1["payload_hash"])
        imp.apply(pid)
        a2 = imp.request_merge(pid)
        if a2["status"] == "pending":
            ap.decide(a2["id"], True, a2["payload_hash"])
        res = imp.merge(pid)
        self.core.audit.log("user", f"Self-Dev qabul qilindi: {idea['title'][:80]}", target=f"proposal#{pid}", risk="E", approval_status="approved")
        self._set(iid, "accepted", "Asosiy versiyaga o'tkazildi. Qayta ishga tushirilmoqda; 15 daqiqa kuzatiladi.")
        self._write_watch(pid, iid)
        self.activity(f"Siz qabul qildingiz — yangilanmoqda: {idea['title'][:80]}", "done")
        return {"idea": self.get(iid), "merge": {k: res.get(k) for k in ("status", "merge_commit", "branch")}, "restart": self.restart()}

    def reject(self, iid: int, note: str = "") -> dict:
        idea = self.get(iid)
        if idea["status"] in ("accepted",):
            raise SelfDevError("Qabul qilingan — 'orqaga qaytarish'dan foydalaning")
        self._set(iid, "rejected", note or "Foydalanuvchi rad etdi")
        self.activity(f"Rad etildi: {idea['title'][:80]}")
        return self.get(iid)

    def rollback(self, iid: int) -> dict:
        idea = self.get(iid)
        if idea["status"] not in ("accepted", "done"):
            raise SelfDevError("Faqat qabul qilingan o'zgarish qaytariladi")
        self.core.improver.revert_merge(idea["proposal_id"])
        self._set(iid, "reverted", "Orqaga qaytarildi (git revert)")
        self._clear_watch()
        return {"idea": self.get(iid), "restart": self.restart()}

    # ---------------- qayta ishga tushish va kuzatuv ----------------
    def _watch_path(self):
        return jarvis_home() / "selfdev_watch.json"

    def _write_watch(self, pid: int, iid: int):
        base = self.core.db.one("SELECT COUNT(*) n FROM errors WHERE ts >= datetime('now','-60 minutes')")["n"] if self._has_errors() else 0
        self._watch_path().write_text(json.dumps({"proposal": pid, "idea": iid, "since": time.time(), "baseline_errors_per_hour": base}), encoding="utf-8")

    def _clear_watch(self):
        try:
            self._watch_path().unlink()
        except FileNotFoundError:
            pass

    def _watch_state(self) -> dict | None:
        try:
            return json.loads(self._watch_path().read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return None

    def _has_errors(self) -> bool:
        return bool(self.core.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='errors'"))

    def watch_tick(self) -> dict | None:
        """Yangi versiya kuzatuvi: o'z-o'zini tekshiruv yoki xatolar keskin ko'paysa — avtomatik qaytarish."""
        w = self._watch_state()
        if not w:
            return None
        elapsed = time.time() - w["since"]
        bad, why = False, ""
        try:                                                # asosiy qismlar ishlayaptimi (yangi kod ularni buzmaganmi)
            self.core.guardian.status()
            self.core.tools.catalog()
            self.core.db.one("SELECT 1 x")
        except Exception as e:                              # noqa: BLE001
            bad, why = True, f"asosiy qism ishlamayapti: {str(e)[:150]}"
        if not bad and self._has_errors():
            n = self.core.db.one("SELECT COUNT(*) n FROM errors WHERE ts >= datetime(?, 'unixepoch')", (int(w["since"]),))["n"]
            if n >= max(10, 3 * w.get("baseline_errors_per_hour", 0) + 5):
                bad, why = True, f"yangilanishdan keyin {n} ta xato"
        if bad:
            try:
                self.core.improver.revert_merge(w["proposal"])
                self._set(w["idea"], "reverted", f"Avtomatik qaytarildi: {why}")
            finally:
                self._clear_watch()
            self.core.notifier.notify("Yangilanish qaytarildi", f"Sabab: {why}. JARVIS oldingi holatga qaytdi.", severity="warning", category="self_improve")
            self.activity(f"⚠ Yangi versiyada muammo ({why}) — orqaga qaytardim", "error")
            return {"reverted": True, "why": why, "restart": self.restart()}
        if elapsed >= WATCH_MIN * 60:
            self._clear_watch()
            self._set(w["idea"], "done", f"{WATCH_MIN} daqiqa kuzatildi — muammo yo'q")
            self.activity("Yangi versiya barqaror ishlayapti ✅", "done")
            return {"stable": True}
        return {"watching": True, "elapsed_s": int(elapsed)}

    def restart(self) -> dict:
        """Serverni qayta ishga tushirish (yangi kodni yuklash). Testlarda (JARVIS_NO_RESTART) o'chiq."""
        if os.environ.get("JARVIS_NO_RESTART") or "pytest" in sys.modules:
            return {"restarting": False, "note": "Test muhitida qayta ishga tushirilmaydi"}
        port = str(getattr(self.core, "port", 8765))

        def go():
            time.sleep(1.5)
            kw = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
            subprocess.Popen([sys.executable, "-m", "jarvis.api", "--port", port, "--wait-port"], cwd=os.getcwd(), **kw)
            os._exit(0)
        threading.Thread(target=go, daemon=True).start()
        return {"restarting": True, "note": "JARVIS 5–15 soniyada qayta ishga tushadi — sahifani yangilang"}
