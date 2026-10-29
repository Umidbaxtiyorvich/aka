"""Computer Agent: buyruqni taklif qilish → tushuntirish → tasdiq → bajarish. Admin huquqi ishlatilmaydi."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .approval import ApprovalEngine, ApprovalError
from .audit import Audit
from .security import classify_command, redact

EXPLAIN = {
    "A": "Faqat o'qiydi, hech narsani o'zgartirmaydi.",
    "C": "Fayl yoki tizim holatini o'zgartirishi mumkin.",
    "E": "XAVFLI: o'chirish yoki qaytarib bo'lmaydigan o'zgarish bo'lishi mumkin.",
}


class ComputerAgent:
    def __init__(self, settings, approvals: ApprovalEngine, audit: Audit):
        self.settings, self.approvals, self.audit = settings, approvals, audit

    def propose(self, command: str, reason: str = "") -> dict:
        level = classify_command(command)
        cwd = self.settings.allowed_write_dirs[0]
        payload = {"command": command, "cwd": cwd}
        summary = f"Buyruq: {command} — {EXPLAIN[level]}" + (f" Sabab: {reason}" if reason else "")
        appr = self.approvals.request(action_type="shell_read" if level == "A" else "shell_command",
                                      target="local_computer", level=level, payload=payload, summary=summary,
                                      requested_by="computer_agent", command=command,
                                      purpose=reason or "Foydalanuvchi so'ragan buyruq")
        level = appr["level"]
        return {"approval": appr, "explanation": EXPLAIN[level], "risk": level}

    def execute(self, approval_id: int, payload: dict) -> dict:
        row = self.approvals.authorize_execution(approval_id, payload)
        if self.settings.read_only_mode and row["level"] != "A":
            raise ApprovalError("Faqat o'qish rejimi yoqilgan: o'zgartiruvchi buyruqlar bajarilmaydi.")
        try:
            proc = subprocess.run(payload["command"], shell=True, cwd=payload["cwd"], capture_output=True,
                                  text=True, timeout=30)
        except subprocess.TimeoutExpired:
            self.approvals.mark_result(approval_id, "unknown")
            self.audit.log("computer_agent", payload["command"], target="local_computer", risk=row["level"],
                           approval_status="approved", error_code="TIMEOUT", error_note="30 s dan oshdi")
            raise
        self.approvals.mark_result(approval_id, "executed")
        out = redact((proc.stdout or "") + (proc.stderr or ""))[-5000:]
        self.audit.log("computer_agent", payload["command"], target="local_computer", risk=row["level"],
                       approval_status="approved", result=f"exit={proc.returncode}",
                       error_code="" if proc.returncode == 0 else f"EXIT_{proc.returncode}", verified="exit_code")
        return {"exit_code": proc.returncode, "output": out}

    # --- dasturlarni ishga tushirish ---
    def apps(self) -> dict:
        return {name: " ".join(cmd) for name, cmd in self.settings.app_allowlist.items()}

    def propose_app(self, name: str, file: str | None = None, reason: str = "") -> dict:
        """Faqat app_allowlist'dagi dastur; ixtiyoriy fayl faqat ruxsat berilgan papkadan. Shell ishlatilmaydi."""
        from .security import is_within
        cmd = self.settings.app_allowlist.get(name)
        if not cmd:
            raise ApprovalError(f"'{name}' ruxsat berilgan dasturlar ro'yxatida yo'q (settings.json → app_allowlist)")
        argv = list(cmd)
        if file:
            fp = Path(file).resolve()
            if not is_within(fp, self.settings.allowed_read_dirs) or not fp.exists():
                raise ApprovalError("Fayl topilmadi yoki ruxsat berilgan papkada emas")
            argv.append(str(fp))
        appr = self.approvals.request(action_type="app_launch", target="local_computer", level="C",
                                      payload={"app": name, "argv": argv}, requested_by="computer_agent",
                                      summary=f"Dasturni ochish: {name}" + (f" ({Path(file).name})" if file else ""),
                                      purpose=reason or "Foydalanuvchi so'ragan dastur")
        return {"approval": appr}

    def launch_app(self, approval_id: int) -> dict:
        row = self.approvals.get(approval_id)
        if row["action_type"] != "app_launch":
            raise ApprovalError("Bu tasdiq dastur ochish uchun emas")
        payload = row["payload"]
        self.approvals.authorize_execution(approval_id, payload)
        if self.settings.app_allowlist.get(payload["app"]) != payload["argv"][:len(self.settings.app_allowlist.get(payload["app"]) or [])]:
            raise ApprovalError("Dastur ro'yxati tasdiqdan keyin o'zgargan")
        kw = {"creationflags": getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)} \
            if os.name == "nt" else {"start_new_session": True}
        try:
            proc = subprocess.Popen(payload["argv"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, **kw)
        except OSError as e:
            self.approvals.mark_result(approval_id, "executed")
            self.audit.log("computer_agent", f"Dastur ochilmadi: {payload['app']}", target="local_computer", risk="C",
                           approval_status="approved", error_code="LAUNCH_FAILED", error_note=str(e))
            raise ApprovalError(f"Dasturni ochib bo'lmadi: {e}") from None
        self.approvals.mark_result(approval_id, "executed")
        self.audit.log("computer_agent", f"Dastur ochildi: {payload['app']}", target="local_computer", risk="C",
                       approval_status="approved", result=f"pid={proc.pid}")
        return {"app": payload["app"], "pid": proc.pid}
