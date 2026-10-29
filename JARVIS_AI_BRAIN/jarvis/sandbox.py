"""Sandbox — AI yaratgan kod va skriptlarni asosiy tizimdan ajratib sinash.

HALOL CHEKLOV: `process` backend OS darajasidagi izolyatsiya EMAS. U quyidagilarni beradi:
  1. Statik tekshiruv (AST): xavfli import/chaqiruvlar topiladi → bloklanadi yoki E-darajali tasdiq so'raladi.
  2. Alohida vaqtinchalik papka (cwd), tozalangan muhit o'zgaruvchilari (token/kalitlar o'tmaydi), `python -I`.
  3. Python audit-hook: papkadan tashqariga yozish, subprocess, ctypes, tarmoq (ruxsatsiz) — runtime'da bloklanadi.
  4. Limitlar: vaqt (wall-clock), xotira (POSIX: RLIMIT_AS; hamma OS: psutil monitoring + kill),
     fayl hajmi (POSIX), qayta urinishlar soni.
  Bu "best-effort" himoya: maqsadli zararli kod (masalan, C-kengaytma orqali) uni chetlab o'tishi mumkin.
  Kuchliroq izolyatsiya: `sandbox_backend = "docker"` (tarmoqsiz, read-only konteyner, memory/pids limit)
  yoki Windows Sandbox / alohida virtual mashina.
Testdan o'tmagan kod hech qachon asosiy loyihaga avtomatik qo'shilmaydi (improve.py tasdiq oqimi).
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .approval import ApprovalError
from .config import jarvis_home
from .security import classify_command, redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS sandbox_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL DEFAULT (datetime('now')), kind TEXT NOT NULL,
    code_sha256 TEXT NOT NULL, code TEXT NOT NULL, findings TEXT NOT NULL, status TEXT NOT NULL,
    exit_code INTEGER, stdout TEXT, stderr TEXT, duration_ms INTEGER, peak_mem_mb REAL, attempts INTEGER,
    limits TEXT NOT NULL, backend TEXT NOT NULL, isolation TEXT NOT NULL, approval_id INTEGER
);
"""
BLOCK_IMPORTS = {"subprocess", "ctypes", "multiprocessing", "socket", "winreg", "_winapi", "pty", "signal"}
NET_IMPORTS = {"urllib", "http", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "telnetlib", "ssl", "websocket"}
WARN_IMPORTS = {"os", "shutil", "pathlib", "importlib", "threading", "pickle", "marshal"}
BLOCK_CALLS = {"eval", "exec", "compile", "__import__", "breakpoint", "input"}
BLOCK_ATTRS = {"system", "popen", "remove", "unlink", "rmdir", "removedirs", "rmtree", "kill", "fork", "forkpty",
               "execv", "execve", "execl", "execlp", "execvp", "spawnl", "spawnv", "startfile", "chmod", "chown",
               "symlink", "link", "putenv", "setuid"}

RUNNER = r'''
import os, sys, runpy
ROOT = os.path.realpath(sys.argv[1]); ALLOW_NET = sys.argv[2] == "1"
READ_OK = [ROOT] + sorted({os.path.realpath(p) for p in (sys.prefix, sys.base_prefix, sys.exec_prefix, os.path.dirname(os.__file__))})
def inside(p, roots):
    p = os.path.normcase(os.path.realpath(p))
    return any(p == os.path.normcase(r) or p.startswith(os.path.normcase(r) + os.sep) for r in roots)
BLOCKED = {"subprocess.Popen", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.fork", "os.forkpty", "os.kill",
           "ctypes.dlopen", "ctypes.dlsym", "ctypes.call_function", "os.startfile", "winreg.OpenKey", "winreg.CreateKey",
           "os.putenv", "os.chmod", "os.chown", "os.symlink", "os.link", "sys.setprofile", "sys.settrace"}
NET = {"socket.connect", "socket.getaddrinfo", "socket.bind", "socket.sendto", "socket.gethostbyname"}
def hook(event, args):
    if event in BLOCKED:
        raise PermissionError("JARVIS sandbox: '%s' taqiqlangan" % event)
    if event in NET and not ALLOW_NET:
        raise PermissionError("JARVIS sandbox: tarmoq o'chirilgan")
    if event == "open":
        path = args[0]
        if isinstance(path, int) or path is None:
            return
        mode = args[1] if len(args) > 1 and isinstance(args[1], str) else "r"
        flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
        writing = any(c in mode for c in "wax+") or (flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND))
        roots = [ROOT] if writing else READ_OK
        if not inside(os.fsdecode(path), roots):
            raise PermissionError("JARVIS sandbox: papkadan tashqarida fayl ochish taqiqlangan: %s" % os.fsdecode(path))
    if event in ("os.remove", "os.rmdir", "os.rename", "os.mkdir", "shutil.rmtree", "os.truncate"):
        for a in args[:2]:
            if isinstance(a, (str, bytes, os.PathLike)) and not inside(os.fsdecode(a), [ROOT]):
                raise PermissionError("JARVIS sandbox: papkadan tashqarida o'zgartirish taqiqlangan")
sys.addaudithook(hook)
sys.argv = ["main.py"]
sys.path.insert(0, ROOT)
runpy.run_path(os.path.join(ROOT, "main.py"), run_name="__main__")
'''


class SandboxError(Exception):
    pass


def static_check(code: str, allow_network: bool = False) -> list[dict]:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [{"severity": "block", "line": e.lineno, "msg": f"Sintaksis xatosi: {e.msg}"}]
    out = []

    def add(sev, node, msg):
        out.append({"severity": sev, "line": getattr(node, "lineno", 0), "msg": msg})

    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
            for name in names:
                root = name.split(".")[0]
                if root in BLOCK_IMPORTS:
                    add("block", n, f"Xavfli modul: {root}")
                elif root in NET_IMPORTS:
                    add("warn" if allow_network else "block", n, f"Tarmoq moduli: {root}")
                elif root in WARN_IMPORTS:
                    add("warn", n, f"Diqqat talab qiladigan modul: {root}")
        elif isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id in BLOCK_CALLS:
                add("block", n, f"Xavfli chaqiruv: {f.id}()")
            elif isinstance(f, ast.Attribute) and f.attr in BLOCK_ATTRS:
                add("block", n, f"Xavfli chaqiruv: .{f.attr}()")
            elif isinstance(f, ast.Name) and f.id == "open" and n.args and isinstance(n.args[0], ast.Constant) \
                    and isinstance(n.args[0].value, str) and (os.path.isabs(n.args[0].value) or ".." in n.args[0].value):
                add("block", n, f"Sandbox tashqarisidagi fayl: {n.args[0].value}")
        elif isinstance(n, ast.Attribute) and n.attr in ("__globals__", "__subclasses__", "__builtins__", "__code__"):
            add("block", n, f"Introspeksiya orqali chetlab o'tish urinishi: {n.attr}")
    return out


def _clean_env(root: Path) -> dict:
    keep = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL") if k in os.environ}
    path_dirs = [os.path.dirname(sys.executable)] + (["/usr/bin", "/bin"] if os.name != "nt" else
                                                       [os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32")])
    return keep | {"PATH": os.pathsep.join(path_dirs), "HOME": str(root), "USERPROFILE": str(root), "TMP": str(root),
                   "TEMP": str(root), "TMPDIR": str(root), "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}


def _limits(mem_mb: int, cpu_sec: int):
    def apply():  # faqat POSIX
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 2**20, mem_mb * 2**20))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_sec, cpu_sec + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 2**20, 50 * 2**20))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        os.setsid()
    return apply


def _run_process(argv: list[str], cwd: Path, env: dict, timeout: int, mem_mb: int, stdin: str | None = None) -> dict:
    t0 = time.monotonic()
    kw = {"preexec_fn": _limits(mem_mb, timeout)} if os.name == "posix" else {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **kw)
    except OSError as e:
        return {"status": "error_infra", "exit_code": None, "stdout": "", "stderr": str(e), "duration_ms": 0, "peak_mem_mb": None}
    peak, killed = [0.0], [None]

    def monitor():
        try:
            import psutil
            ps = psutil.Process(proc.pid)
            while proc.poll() is None:
                rss = ps.memory_info().rss / 2**20
                for ch in ps.children(recursive=True):
                    try:
                        rss += ch.memory_info().rss / 2**20
                    except psutil.Error:
                        pass
                peak[0] = max(peak[0], rss)
                if rss > mem_mb:
                    killed[0] = "memory"
                    proc.kill()
                    return
                time.sleep(0.05)
        except Exception:  # psutil yo'q yoki jarayon tugadi
            return

    th = threading.Thread(target=monitor, daemon=True)
    th.start()
    try:
        out, err = proc.communicate(stdin, timeout=timeout)
        status = "ok" if proc.returncode == 0 else "error"
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        status = "timeout"
    th.join(1)
    if killed[0] == "memory":
        status = "memory_limit"
    elif os.name == "posix" and proc.returncode in (-9, -24) and status == "error":
        status = "cpu_limit" if proc.returncode == -24 else status
    if status == "error" and "MemoryError" in (err or ""):
        status = "memory_limit"
    return {"status": status, "exit_code": proc.returncode, "stdout": out or "", "stderr": err or "",
            "duration_ms": int((time.monotonic() - t0) * 1000), "peak_mem_mb": round(peak[0], 1) if peak[0] else None}


class Sandbox:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)

    @property
    def base(self) -> Path:
        p = jarvis_home() / "sandbox"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def isolation_info(self) -> dict:
        backend = self.core.settings.sandbox_backend
        docker = bool(shutil.which("docker"))
        info = {"backend": backend, "docker_available": docker,
                "limits": {"timeout_sec": self.core.settings.sandbox_timeout_sec, "memory_mb": self.core.settings.sandbox_memory_mb,
                           "max_retries": self.core.settings.sandbox_max_retries}}
        if backend == "docker":
            return info | {"level": "container", "guarantees": ["tarmoqsiz (--network none)", "read-only root", "memory/pids/cpu limit",
                                                                 "faqat sandbox papkasi ulanadi"],
                           "not_guaranteed": ["Docker o'zi o'rnatilgan va ishlayotgan bo'lishi kerak"]}
        return info | {"level": "process (best-effort, OS izolyatsiyasi emas)",
                       "guarantees": ["statik AST tekshiruvi", "alohida papka va tozalangan env (kalitlar o'tmaydi)",
                                      "audit-hook: tashqariga yozish, subprocess, ctypes, ruxsatsiz tarmoq bloklanadi",
                                      "vaqt va xotira limiti" + (" (RLIMIT + monitoring)" if os.name == "posix" else " (monitoring + kill)")],
                       "not_guaranteed": ["C-kengaytma yoki interpreter zaifligi orqali chetlab o'tish",
                                          "shell buyruqlarida tarmoqni bloklash", "CPU vaqti limiti Windows'da"],
                       "recommendation": "Ishonchsiz kod uchun Docker backend yoki Windows Sandbox ishlating."}

    def _record(self, kind, code, findings, res, limits, backend, isolation, attempts, approval_id=None) -> dict:
        cur = self.core.db.execute(
            "INSERT INTO sandbox_runs(kind, code_sha256, code, findings, status, exit_code, stdout, stderr, duration_ms,"
            " peak_mem_mb, attempts, limits, backend, isolation, approval_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (kind, hashlib.sha256(code.encode()).hexdigest(), code[:20000], json.dumps(findings, ensure_ascii=False),
             res["status"], res.get("exit_code"), redact(res.get("stdout", ""))[-8000:], redact(res.get("stderr", ""))[-8000:],
             res.get("duration_ms"), res.get("peak_mem_mb"), attempts, json.dumps(limits), backend, isolation, approval_id))
        self.core.audit.log("sandbox", f"Sandbox {kind}: {res['status']}", target=f"sandbox_run#{cur.lastrowid}", risk="B",
                            result=f"exit={res.get('exit_code')}", error_code="" if res["status"] == "ok" else res["status"].upper())
        return self.get(cur.lastrowid)

    def get(self, rid: int) -> dict:
        r = self.core.db.one("SELECT * FROM sandbox_runs WHERE id=?", (rid,))
        if not r:
            raise SandboxError("Sandbox natijasi topilmadi")
        r["findings"], r["limits"] = json.loads(r["findings"]), json.loads(r["limits"])
        return r

    def history(self, limit: int = 50) -> list[dict]:
        return [self.get(r["id"]) for r in self.core.db.query("SELECT id FROM sandbox_runs ORDER BY id DESC LIMIT ?", (limit,))]

    def run_python(self, code: str, *, allow_network: bool = False, stdin: str | None = None, timeout: int | None = None,
                   memory_mb: int | None = None, approval_id: int | None = None, files: dict[str, str] | None = None) -> dict:
        s = self.core.settings
        timeout = min(timeout or s.sandbox_timeout_sec, 300)
        memory_mb = min(memory_mb or s.sandbox_memory_mb, 2048)
        findings = static_check(code, allow_network)
        blocked = [f for f in findings if f["severity"] == "block"]
        payload = {"code_sha256": hashlib.sha256(code.encode()).hexdigest(), "allow_network": allow_network}
        if blocked or allow_network:
            if approval_id is None:
                appr = self.core.approvals.request(
                    action_type="sandbox_unsafe_run", target="sandbox", level="E", payload=payload, requested_by="sandbox",
                    summary="Sandbox: " + ("; ".join(f["msg"] for f in blocked[:3]) or "tarmoqqa ruxsat so'raldi"),
                    purpose="Xavfli deb topilgan kodni cheklangan muhitda sinash")
                return {"status": "needs_approval", "findings": findings, "approval": appr}
            self.core.approvals.authorize_execution(approval_id, payload)
        limits = {"timeout_sec": timeout, "memory_mb": memory_mb, "network": allow_network}
        backend = s.sandbox_backend
        if backend == "docker" and not shutil.which("docker"):
            raise SandboxError("sandbox_backend=docker, lekin Docker topilmadi")
        attempts, res = 0, None
        max_attempts = 1 + max(0, min(s.sandbox_max_retries, 3))
        while attempts < max_attempts:
            attempts += 1
            root = Path(tempfile.mkdtemp(prefix="run_", dir=self.base))
            try:
                (root / "main.py").write_text(code, encoding="utf-8")
                for name, content in (files or {}).items():
                    target = (root / name).resolve()
                    if root.resolve() not in target.parents:
                        raise SandboxError(f"Fayl nomi sandbox'dan tashqariga chiqadi: {name}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                if backend == "docker":
                    argv = ["docker", "run", "--rm", "-i", "--network", "bridge" if allow_network else "none",
                            "--memory", f"{memory_mb}m", "--pids-limit", "64", "--cpus", "1", "--read-only",
                            "--tmpfs", "/tmp", "-v", f"{root}:/work", "-w", "/work", "python:3.12-slim", "python", "main.py"]
                    res = _run_process(argv, root, os.environ.copy(), timeout + 10, memory_mb + 512, stdin)
                else:
                    (root / "_jarvis_runner.py").write_text(RUNNER, encoding="utf-8")
                    argv = [sys.executable, "-I", str(root / "_jarvis_runner.py"), str(root), "1" if allow_network else "0"]
                    res = _run_process(argv, root, _clean_env(root), timeout, memory_mb, stdin)
                res["files"] = sorted(str(p.relative_to(root)) for p in root.rglob("*")
                                      if p.is_file() and p.name not in ("main.py", "_jarvis_runner.py"))[:50]
            finally:
                shutil.rmtree(root, ignore_errors=True)
            if res["status"] not in ("timeout", "error_infra"):
                break
        info = self.isolation_info()
        out = self._record("python", code, findings, res, limits, backend, info["level"], attempts, approval_id)
        return out | {"created_files": res.get("files", [])}

    def run_command(self, command: str, *, timeout: int | None = None) -> dict:
        """Shell buyrug'ini sandbox papkasida, tozalangan env va limitlar bilan ishga tushirish.
        Tarmoqni bloklab bo'lmaydi — bu natijada ko'rsatiladi."""
        s = self.core.settings
        level = classify_command(command)
        d = self.core.policy.evaluate("shell_read" if level == "A" else "shell_command", level, command=command)
        if d.risk == "forbidden":
            raise ApprovalError(f"Taqiqlangan: {d.reason}")
        if d.requires_approval:
            raise ApprovalError("Bu buyruq o'zgartirish kiritadi — Kompyuter boshqaruvi orqali tasdiq bilan bajaring")
        timeout = min(timeout or s.sandbox_timeout_sec, 120)
        root = Path(tempfile.mkdtemp(prefix="cmd_", dir=self.base))
        try:
            argv = ["cmd", "/c", command] if os.name == "nt" else ["/bin/sh", "-c", command]
            res = _run_process(argv, root, _clean_env(root), timeout, s.sandbox_memory_mb)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        return self._record("command", command, [], res, {"timeout_sec": timeout, "memory_mb": s.sandbox_memory_mb},
                            "process", "process (tarmoq cheklanmagan)", 1)
