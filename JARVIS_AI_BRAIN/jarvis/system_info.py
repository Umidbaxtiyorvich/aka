"""Diagnostika: CPU, RAM, disk, GPU (aniqlansa), dasturlar. GPU taxmin qilinmaydi."""
from __future__ import annotations

import platform
import shutil
import subprocess

import psutil

from .config import jarvis_home


def _gpu() -> dict:
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
            if out:
                return {"detected": True, "source": "nvidia-smi", "info": out}
        except (OSError, subprocess.SubprocessError):
            pass
    if platform.system() == "Windows":
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json"],
                                 capture_output=True, text=True, timeout=10).stdout.strip()
            if out:
                return {"detected": True, "source": "Win32_VideoController",
                        "info": out, "note": "AdapterRAM 4 GB dan katta VRAM'ni noto'g'ri ko'rsatishi mumkin"}
        except (OSError, subprocess.SubprocessError):
            pass
    return {"detected": False, "info": None,
            "how_to_check": "Windows: Win+R → dxdiag → 'Display' yorlig'i (Name va Display Memory). "
                            "Yoki Task Manager → Performance → GPU."}


def snapshot(include_gpu: bool = False) -> dict:
    vm = psutil.virtual_memory()
    du = shutil.disk_usage(jarvis_home())
    data = {
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "cpu": platform.processor() or platform.machine(),
        "cpu_cores": psutil.cpu_count(logical=True),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_total_gb": round(vm.total / 2**30, 1),
        "ram_used_percent": vm.percent,
        "disk_free_gb": round(du.free / 2**30, 1),
        "tools": {t: bool(shutil.which(t)) for t in ("git", "ollama", "ffmpeg")},
    }
    if include_gpu:
        data["gpu"] = _gpu()
    return data


def recommend_model(ram_total_gb: float) -> str:
    if ram_total_gb < 6:
        return "qwen2.5:0.5b"
    if ram_total_gb < 12:
        return "qwen2.5:1.5b"
    return "llama3.2:3b"
