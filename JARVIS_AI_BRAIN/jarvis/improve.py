"""Self-Improvement Engine (nazorat ostida).

Oqim: taklif (diff) → himoyalangan fayllar tekshiruvi → alohida git worktree'da testlar →
C-darajali tasdiq → alohida branch'ga commit (asosiy branch va ishchi papka O'ZGARMAYDI).
Asosiy versiyaga o'tkazish (merge) — siz qilasiz. Rollback: branch'ni o'chirish yoki `git revert`.
JARVIS xavfsizlik/tasdiqlash/maxfiylik fayllarini (protected_paths) o'zgartiradigan patch'ni rad etadi.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from .config import PROJECT_ROOT

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT, diff TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed', test_output TEXT, branch TEXT, approval_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class ImproveError(Exception):
    pass


def diff_paths(diff: str) -> set[str]:
    paths = set()
    for m in re.finditer(r"^(?:\+\+\+|---) (?:[ab]/)?(\S+)", diff, re.M):
        if m.group(1) != "/dev/null":
            paths.add(m.group(1))
    for m in re.finditer(r"^diff --git a/(\S+) b/(\S+)", diff, re.M):
        paths.update(m.groups())
    return paths


class Improver:
    def __init__(self, core, project_root: Path | None = None):
        self.core = core
        self.project = Path(project_root or PROJECT_ROOT).resolve()
        core.db.conn.executescript(SCHEMA)

    def _git(self, *args, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
        if not shutil.which("git"):
            raise ImproveError("git topilmadi")
        p = subprocess.run(["git", "-c", "user.name=JARVIS", "-c", "user.email=jarvis@localhost", *args],
                           cwd=cwd or self.project, capture_output=True, text=True, timeout=120)
        if check and p.returncode != 0:
            raise ImproveError(f"git {args[0]}: {p.stderr.strip()[-300:]}")
        return p

    def _repo(self) -> tuple[Path, str]:
        top = Path(self._git("rev-parse", "--show-toplevel").stdout.strip()).resolve()
        rel = self.project.relative_to(top).as_posix()
        return top, ("" if rel == "." else rel)

    # --- tahlil ---
    def suggestions(self) -> list[dict]:
        out = []
        errs = Counter(e["module"] for e in self.core.audit.recent_errors(200))
        for mod, n in errs.most_common(5):
            out.append({"source": "xatolar jurnali", "text": f"'{mod}' modulida {n} ta xato. Sababini Xatolar bo'limida ko'ring."})
        from .selfcheck import health
        for h in health(self.core):
            if not h["ok"]:
                out.append({"source": "health check", "text": f"{h['check']}: {h['note']}"})
        failed = self.core.db.query("SELECT agent, COUNT(*) n FROM tasks WHERE status='failed' GROUP BY agent")
        out += [{"source": "vazifalar", "text": f"{f['agent']} agentida {f['n']} ta muvaffaqiyatsiz vazifa"} for f in failed]
        if shutil.which("ruff"):
            p = subprocess.run(["ruff", "check", "jarvis", "--select", "E,F,W,B", "--ignore", "E501,E701,E702,E731",
                                "--output-format", "concise"], cwd=self.project, capture_output=True, text=True, timeout=60)
            for line in p.stdout.splitlines()[:15]:
                if ":" in line:
                    out.append({"source": "ruff", "text": line})
        return out or [{"source": "tekshiruv", "text": "Hozircha aniq muammo topilmadi."}]

    # --- takliflar ---
    def create(self, title: str, diff: str, description: str = "") -> dict:
        if not diff.strip():
            raise ImproveError("Diff bo'sh")
        paths = diff_paths(diff)
        if not paths:
            raise ImproveError("Diff'da fayl yo'llari topilmadi (unified diff kerak)")
        protected = set(self.core.settings.protected_paths)
        bad = sorted(p for p in paths if p in protected or p.startswith((".github/", "../")) or ".." in Path(p).parts)
        if bad:
            raise ImproveError(f"Himoyalangan fayllarni o'zgartirish taqiqlangan: {bad}")
        if re.search(r"^deleted file mode", diff, re.M) and any(p.startswith("tests/") for p in paths):
            raise ImproveError("Testlarni o'chiruvchi patch qabul qilinmaydi")
        cur = self.core.db.execute("INSERT INTO proposals(title, description, diff) VALUES (?,?,?)", (title, description, diff))
        self.core.audit.log("self_improve", f"Taklif: {title}", target=f"proposal#{cur.lastrowid}", risk="B")
        return self.get(cur.lastrowid)

    def get(self, pid: int) -> dict:
        r = self.core.db.one("SELECT * FROM proposals WHERE id=?", (pid,))
        if not r:
            raise ImproveError("Taklif topilmadi")
        return r

    def list(self) -> list[dict]:
        return self.core.db.query("SELECT * FROM proposals ORDER BY id DESC LIMIT 100")

    def _worktree(self) -> tuple[Path, Path, str]:
        top, rel = self._repo()
        wt = Path(tempfile.mkdtemp(prefix="jarvis_wt_"))
        shutil.rmtree(wt)
        self._git("worktree", "add", "--detach", str(wt), "HEAD", cwd=top)
        return top, wt, rel

    def _apply(self, wt: Path, rel: str, diff: str):
        patch = wt / ".jarvis.patch"
        patch.write_text(diff if diff.endswith("\n") else diff + "\n", encoding="utf-8")
        args = ["apply", "--whitespace=nowarn"] + ([f"--directory={rel}"] if rel else []) + [str(patch)]
        self._git(*args, cwd=wt)
        patch.unlink()

    def test(self, pid: int, timeout: int = 600) -> dict:
        prop = self.get(pid)
        top, wt, rel = self._worktree()
        try:
            self._apply(wt, rel, prop["diff"])
            proj = wt / rel if rel else wt
            env = os.environ | {"JARVIS_HOME": tempfile.mkdtemp(prefix="jarvis_test_home_")}
            p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=proj, env=env,
                               capture_output=True, text=True, timeout=timeout)
            ok = p.returncode == 0
            output = "\n".join((p.stdout + p.stderr).strip().splitlines()[-25:])
        except ImproveError as e:
            ok, output = False, f"Patch qo'llanmadi: {e}"
        finally:
            self._git("worktree", "remove", "--force", str(wt), cwd=top, check=False)
        status = "tested_pass" if ok else "tested_fail"
        self.core.db.execute("UPDATE proposals SET status=?, test_output=? WHERE id=?", (status, output, pid))
        self.core.audit.log("self_improve", f"Taklif testi: {status}", target=f"proposal#{pid}", risk="A", result=status)
        return self.get(pid)

    def _payload(self, prop: dict) -> dict:
        return {"proposal": prop["id"], "title": prop["title"], "diff_sha256": hashlib.sha256(prop["diff"].encode()).hexdigest()}

    def request_apply(self, pid: int) -> dict:
        prop = self.get(pid)
        if prop["status"] != "tested_pass":
            raise ImproveError("Faqat testdan o'tgan taklif tasdiqqa yuboriladi")
        appr = self.core.approvals.request(action_type="code_change", target="git_branch", level="C",
                                           payload=self._payload(prop), requested_by="self_improve",
                                           summary=f"Kod o'zgarishi alohida branch'ga: {prop['title']}",
                                           idempotency_key=f"proposal-{pid}")
        self.core.db.execute("UPDATE proposals SET approval_id=? WHERE id=?", (appr["id"], pid))
        return appr

    def apply(self, pid: int) -> dict:
        prop = self.get(pid)
        if not prop["approval_id"]:
            raise ImproveError("Tasdiq so'ralmagan")
        self.core.approvals.authorize_execution(prop["approval_id"], self._payload(prop))
        top, wt, rel = self._worktree()
        branch = f"jarvis/proposal-{pid}"
        try:
            self._git("switch", "-c", branch, cwd=wt)
            self._apply(wt, rel, prop["diff"])
            self._git("add", "-A", cwd=wt)
            self._git("commit", "-m", f"JARVIS taklifi #{pid}: {prop['title']}", cwd=wt)
        finally:
            self._git("worktree", "remove", "--force", str(wt), cwd=top, check=False)
        self.core.approvals.mark_result(prop["approval_id"], "executed")
        self.core.db.execute("UPDATE proposals SET status='applied', branch=? WHERE id=?", (branch, pid))
        self.core.audit.log("self_improve", f"Branch yaratildi: {branch}", target="git", risk="C", approval_status="approved")
        return self.get(pid) | {"next": f"Ko'rib chiqing: git diff HEAD...{branch}. Birlashtirish (o'zingiz): git merge {branch}. "
                                        f"Bekor qilish: git branch -D {branch}"}

    def rollback(self, pid: int) -> dict:
        prop = self.get(pid)
        if prop["status"] != "applied" or not prop["branch"]:
            raise ImproveError("Faqat qo'llangan (branch yaratilgan) taklif bekor qilinadi")
        top, _ = self._repo()
        cur = self._git("rev-parse", "--abbrev-ref", "HEAD", cwd=top).stdout.strip()
        if cur == prop["branch"]:
            raise ImproveError("Siz hozir shu branch'dasiz — avval boshqa branch'ga o'ting")
        merged = prop["branch"] in self._git("branch", "--merged", "HEAD", cwd=top).stdout
        if merged:
            raise ImproveError("Branch allaqachon birlashtirilgan. Qaytarish: git revert <commit> (o'zingiz, tekshirib)")
        self._git("branch", "-D", prop["branch"], cwd=top)
        self.core.db.execute("UPDATE proposals SET status='rolled_back' WHERE id=?", (pid,))
        self.core.audit.log("self_improve", f"Branch o'chirildi: {prop['branch']}", target="git", risk="E", approval_status="user_action")
        return self.get(pid)
