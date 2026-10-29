"""Computer Agent: buyruqni taklif qilish → tushuntirish → tasdiq → bajarish. Admin huquqi ishlatilmaydi."""
from __future__ import annotations

import subprocess

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
