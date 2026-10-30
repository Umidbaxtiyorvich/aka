"""Self-Healing: xatolarni aniqlash, sababini guruhlash va XAVFSIZ tuzatish variantini tayyorlash.

Tsikl (har biri qo'lda yoki jadval bo'yicha, cheklangan):
  1. Diagnostika (backend, frontend fayllari va JS sintaksisi, BD, agentlar, navbat) — tashqi tarmoqsiz.
  2. Xatolar jurnalidan takrorlanuvchi xatolarni imzo bo'yicha guruhlash (raqam, yo'l, id'lar normallashtiriladi).
  3. Ixtiyoriy: testlarni ALOHIDA git worktree'da ishga tushirish (asosiy papka o'zgarmaydi).
  4. Ixtiyoriy: eng ko'p takrorlangan xato uchun AI patch TAKLIFI (regressiya testi bilan) — faqat taklif.
     Kvota: kuniga 3 ta, bitta xato imzosi uchun 24 soatda 1 ta. Qo'llash/merge odatdagidek tasdiq bilan.
  5. Git holati (joriy versiya, saqlanmagan o'zgarishlar) va har bir ochiq taklif uchun qaytarish rejasi.
Hech narsa avtomatik qo'llanmaydi va asosiy versiyaga o'tkazilmaydi.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil

SCHEMA = """
CREATE TABLE IF NOT EXISTS selfheal_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), report TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS selfheal_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), signature TEXT NOT NULL,
    proposal_id INTEGER, error_id INTEGER
);
"""
DAILY_PROPOSALS = 3
RECURRING = 3


def signature(module: str, message: str) -> str:
    m = (message or "").lower()
    m = re.sub(r"(?:[a-z]:)?[\\/][\w\-. \\/]+", "<yo'l>", m)       # fayl yo'llari
    m = re.sub(r"0x[0-9a-f]+|\b[0-9a-f]{8,}\b", "<id>", m)
    m = re.sub(r"\d+", "#", m)
    m = re.sub(r"'[^']*'|\"[^\"]*\"", "<q>", m)
    m = re.sub(r"\s+", " ", m).strip()[:160]
    return f"{module}|{m}"


class SelfHealer:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)

    def error_groups(self, days: int = 7) -> list[dict]:
        rows = self.core.db.query("SELECT id, ts, module, message FROM errors WHERE ts >= datetime('now', ?) ORDER BY id",
                                  (f"-{int(days)} days",))
        groups: dict[str, dict] = {}
        for r in rows:
            sig = signature(r["module"], r["message"])
            g = groups.setdefault(sig, {"signature": sig, "module": r["module"], "sample": r["message"][:200], "count": 0,
                                        "first_seen": r["ts"], "last_seen": r["ts"], "last_error_id": r["id"]})
            g["count"] += 1
            g["last_seen"], g["last_error_id"] = r["ts"], r["id"]
        out = sorted(groups.values(), key=lambda g: -g["count"])
        for g in out:
            g["recurring"] = g["count"] >= RECURRING
            g["key"] = hashlib.sha1(g["signature"].encode()).hexdigest()[:12]
        return out

    def _git_state(self) -> dict:
        imp = self.core.improver
        st = imp.git_status()
        if not st.get("ok"):
            return st
        try:
            top, _ = imp._repo()
            st["diff_stat"] = imp._git("diff", "--stat", cwd=top, check=False).stdout.strip()[-1500:]
        except Exception as e:  # git bo'lmasa ham hisobot chiqadi
            st["diff_stat"] = f"aniqlanmadi: {e}"
        return st

    def _rollback_plans(self) -> list[dict]:
        plans = []
        for p in self.core.improver.list():
            if p["status"] == "applied":
                plans.append({"proposal": p["id"], "title": p["title"], "plan": f"Asosiy versiya o'zgarmagan. Bekor qilish: branch {p['branch']} ni o'chirish ('bekor qilish' tugmasi)."})
            elif p["status"] == "merged":
                plans.append({"proposal": p["id"], "title": p["title"], "plan": "Asosiy versiyada. Qaytarish: 'orqaga qaytarish' (git revert, tarix saqlanadi), keyin JARVIS'ni qayta ishga tushirish."})
        return plans

    def _run_tests(self) -> dict:
        imp = self.core.improver
        if not shutil.which("git"):
            return {"ran": False, "note": "git yo'q — testlar alohida muhitda ishga tushirilmadi (asosiy papkada ishga tushirilmaydi)."}
        try:
            top, wt, rel = imp._worktree()
        except Exception as e:
            return {"ran": False, "note": f"Alohida nusxa yaratilmadi: {e}"}
        try:
            ok, output = imp._run_tests(wt / rel if rel else wt)
        finally:
            imp._git("worktree", "remove", "--force", str(wt), cwd=top, check=False)
        last = (output.strip().splitlines() or [""])[-1]
        if hasattr(self.core, "kgraph"):
            from datetime import datetime, timezone
            self.core.kgraph.on_test_run(f"selfheal-{datetime.now(timezone.utc):%Y%m%d%H%M%S%f}", "passed" if ok else "failed",
                                         summary=last, source="selfheal:pytest")
        return {"ran": True, "passed": ok, "summary": last, "output": output}

    def _quota_left(self) -> int:
        n = self.core.db.one("SELECT COUNT(*) n FROM selfheal_proposals WHERE ts >= datetime('now','-1 day')")["n"]
        return max(0, DAILY_PROPOSALS - n)

    def _propose(self, groups: list[dict]) -> dict:
        if self.core.ai.name == "offline":
            return {"created": None, "note": "AI modeli ulanmagan — tuzatish taklifi yaratilmadi (diagnostika baribir tayyor)."}
        if self._quota_left() <= 0:
            return {"created": None, "note": f"Kunlik limit ({DAILY_PROPOSALS} ta taklif) tugadi."}
        for g in groups:
            if not g["recurring"]:
                continue
            if self.core.db.one("SELECT 1 FROM selfheal_proposals WHERE signature=? AND ts >= datetime('now','-1 day')", (g["signature"],)):
                continue
            try:
                prop = self.core.improver.suggest_patch(g["last_error_id"],
                                                        description=f"Bu xato oxirgi 7 kunda {g['count']} marta takrorlandi.")
            except Exception as e:
                self.core.db.execute("INSERT INTO selfheal_proposals(signature, error_id) VALUES (?,?)", (g["signature"], g["last_error_id"]))
                return {"created": None, "note": f"Taklif yaratilmadi: {e}"}
            self.core.db.execute("INSERT INTO selfheal_proposals(signature, proposal_id, error_id) VALUES (?,?,?)",
                                 (g["signature"], prop["id"], g["last_error_id"]))
            return {"created": prop["id"], "title": prop["title"], "has_regression_test": prop.get("has_test", False),
                    "note": "Taklif yaratildi. Keyingi qadam: 'Testlar va yaxshilash' → test → tasdiq."}
        return {"created": None, "note": "Takrorlanuvchi, hali taklif berilmagan xato yo'q."}

    def run(self, *, run_tests: bool = False, propose: bool = False) -> dict:
        diag = self.core.diagnostics.run(external=False)
        problems = [c for c in diag["components"] if c["status"] in ("error", "warning")]
        groups = self.error_groups()
        report = {"overall": diag["overall"], "problems": problems, "error_groups": groups[:20],
                  "recurring": [g for g in groups if g["recurring"]], "git": self._git_state(),
                  "rollback_plans": self._rollback_plans(), "tests": None, "proposal": None,
                  "quota_left": self._quota_left(),
                  "note": "Hech narsa avtomatik qo'llanmadi. Takliflar test → tasdiq → branch → (alohida tasdiq bilan) merge yo'lidan o'tadi."}
        if run_tests:
            report["tests"] = self._run_tests()
        if propose:
            report["proposal"] = self._propose(groups)
        slim = {k: v for k, v in report.items() if k != "tests"} | {"tests": {k: v for k, v in (report["tests"] or {}).items() if k != "output"}}
        self.core.db.execute("INSERT INTO selfheal_runs(report) VALUES (?)", (json.dumps(slim, ensure_ascii=False, default=str)[:200000],))
        self.core.audit.log("selfheal", f"Self-healing tekshiruvi: {diag['overall']}, takrorlanuvchi xatolar {len(report['recurring'])}",
                            target="system", risk="A")
        if report["recurring"]:
            self.core.notifier.notify("Takrorlanuvchi xatolar aniqlandi", "; ".join(f"{g['module']} ×{g['count']}" for g in report["recurring"][:5]),
                                      severity="warning", category="error")
        return report

    def history(self, limit: int = 20) -> list[dict]:
        return [{"id": r["id"], "ts": r["ts"], **json.loads(r["report"])}
                for r in self.core.db.query("SELECT * FROM selfheal_runs ORDER BY id DESC LIMIT ?", (limit,))]
