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


def gpu_vram_gb() -> float | None:
    """NVIDIA bo'lsa nvidia-smi orqali aniq VRAM (GB); aniqlab bo'lmasa None — taxmin qilinmaydi."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
        return round(max(float(x) for x in out) / 1024, 1) if out else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def recommend_setup(ram_gb: float, vram_gb: float | None) -> dict:
    """RAM va VRAM bo'yicha mahalliy AI tavsiyasi. VRAM noma'lum bo'lsa — CPU uchun ehtiyotkor tanlov."""
    if vram_gb is not None and vram_gb >= 6 and ram_gb >= 12:
        light, strong = "qwen2.5:3b", "qwen2.5:7b"
    elif vram_gb is not None and vram_gb >= 3.5:
        light, strong = "qwen2.5:1.5b", "qwen2.5:3b"          # masalan GTX 1650 4 GB + 8 GB RAM
    elif ram_gb >= 6:
        light, strong = "qwen2.5:1.5b", "qwen2.5:3b"          # CPU'da ishlaydi, strong sekinroq
    else:
        light, strong = "qwen2.5:0.5b", "qwen2.5:1.5b"
    gpu = vram_gb is not None and vram_gb >= 3.5
    return {
        "light": light, "strong": strong, "vision": "moondream" if (gpu or ram_gb >= 8) else None,
        "whisper": "small" if ram_gb >= 8 else "base",
        "image_gen": ("Stable Diffusion 1.5, --medvram (GTX 16xx uchun --precision full --no-half), 512×512 ≈ 30–60 s"
                      if gpu and vram_gb < 6 else "SDXL mumkin" if gpu else "Tavsiya etilmaydi (GPU yo'q/noma'lum — juda sekin)"),
        "vram_gb": vram_gb, "ram_gb": ram_gb,
        "note": "8 GB RAM'da bir vaqtda faqat bitta model yuklansin (Ollama standart holatda shunday qiladi)."}


def recommend_model(ram_total_gb: float) -> str:
    if ram_total_gb < 6:
        return "qwen2.5:0.5b"
    if ram_total_gb < 12:
        return "qwen2.5:1.5b"
    return "llama3.2:3b"
