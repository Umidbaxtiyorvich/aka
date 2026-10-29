"""Self-Improvement Engine (1-bosqich): modullarni tekshiradi, testlarni ishga tushiradi, hisobot beradi.
Kod o'zgartirmaydi va xavfsizlik sozlamalariga tega olmaydi; patchlar faqat taklif sifatida."""
from __future__ import annotations

import subprocess
import sys

from .config import PROJECT_ROOT


def health(core) -> list[dict]:
    checks = []

    def add(name, fn):
        try:
            ok, note = fn()
        except Exception as e:  # tekshiruvning o'zi xato bersa ham hisobotga tushadi
            ok, note = False, f"{type(e).__name__}: {e}"
        checks.append({"check": name, "ok": ok, "note": note})

    add("database", lambda: (core.db.one("SELECT 1 AS x")["x"] == 1, str(core.db.path.name)))
    add("memory_fts", lambda: (isinstance(core.memory.search("test"), list), "FTS5 qidiruv"))
    add("ai_provider", lambda: core.ai.available())
    add("approval_engine", lambda: (len(core.approvals.list("pending")) >= 0, "ishlayapti"))
    add("read_only_mode", lambda: (True, "yoqilgan" if core.settings.read_only_mode else "O'CHIRILGAN"))
    return checks


def run_tests(timeout: int = 300) -> dict:
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
                          cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout)
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-15:]
    return {"passed": proc.returncode == 0, "exit_code": proc.returncode, "summary": "\n".join(tail)}
