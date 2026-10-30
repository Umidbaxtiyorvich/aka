"""Shu kompyuterga mos mahalliy AI sozlamasi (Ollama). Hech narsa sizning roziligingizsiz yuklanmaydi.

  python scripts/setup_ai.py                 — tekshiradi va reja ko'rsatadi
  python scripts/setup_ai.py --apply         — settings.json ga ai_providers / vision_model yozadi
  python scripts/setup_ai.py --apply --pull  — + kerakli modellarni ollama pull bilan yuklaydi (hajmi oldin so'raladi)
  python scripts/setup_ai.py --vram 4        — VRAM'ni qo'lda ko'rsatish (nvidia-smi bo'lmasa)
"""
import argparse
import json
import shutil
import subprocess
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jarvis import system_info  # noqa: E402
from jarvis.ai_engine import MODEL_CATALOG  # noqa: E402
from jarvis.config import Settings  # noqa: E402

SIZE = {m["name"]: m["disk_gb"] for m in MODEL_CATALOG}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--vram", type=float, help="VRAM (GB), agar avtomatik aniqlanmasa")
    ap.add_argument("--yes", action="store_true", help="yuklashni so'ramasdan tasdiqlash")
    a = ap.parse_args()
    snap = system_info.snapshot(include_gpu=True)
    vram = a.vram if a.vram is not None else system_info.gpu_vram_gb()
    rec = system_info.recommend_setup(snap["ram_total_gb"], vram)
    print(f"RAM: {snap['ram_total_gb']} GB · VRAM: {vram if vram is not None else 'aniqlanmadi'} GB · bo'sh disk: {snap['disk_free_gb']} GB")
    print(f"GPU: {snap['gpu'].get('info') or snap['gpu'].get('how_to_check')}")
    models = [m for m in dict.fromkeys([rec["light"], rec["strong"], rec["vision"]]) if m]
    total = sum(SIZE.get(m, 0) for m in models)
    print("\nTavsiya:")
    print(f"  light (oddiy savollar):    {rec['light']}  (~{SIZE.get(rec['light'], '?')} GB)")
    print(f"  strong (kod, tahlil):      {rec['strong']}  (~{SIZE.get(rec['strong'], '?')} GB)")
    print(f"  vision (rasm mazmuni):     {rec['vision'] or '—'}")
    print(f"  Whisper (ovoz → matn):     {rec['whisper']}  (pip install faster-whisper)")
    print(f"  Rasm generatsiyasi:        {rec['image_gen']}")
    print(f"  Jami yuklanadigan modellar: ~{total:.1f} GB · {rec['note']}")
    if total > snap["disk_free_gb"] - 5:
        print("DIQQAT: diskda joy yetmasligi mumkin.")
    if not a.apply:
        print("\nQo'llash uchun: python scripts/setup_ai.py --apply [--pull]")
        return 0
    s = Settings.load()
    s.ai_provider = "ollama"
    s.ollama_model = rec["light"]
    s.ai_providers = [{"id": "light", "kind": "ollama", "model": rec["light"], "tier": "light", "enabled": True},
                      {"id": "strong", "kind": "ollama", "model": rec["strong"], "tier": "strong", "enabled": True}]
    s.vision_model = rec["vision"] or ""
    s.save()
    print(f"\nSaqlandi: {Settings.path()}")
    if a.pull:
        if not shutil.which("ollama"):
            print("Ollama topilmadi: https://ollama.com/download dan o'rnating, so'ng qayta ishga tushiring.")
            return 1
        if not a.yes and input(f"{', '.join(models)} (~{total:.1f} GB) yuklansinmi? [ha/yo'q]: ").strip().lower() not in ("ha", "h", "y", "yes"):
            print("Yuklash bekor qilindi.")
            return 0
        print("Eslatma: internet uzilsa foiz orqaga ketishi mumkin — Ollama uzilgan qismni qayta yuklaydi, "
              "tayyor qismlar saqlanadi. Xato bo'lsa, avtomatik qayta uriniladi.")
        for m in models:
            for attempt in range(1, 6):
                print(f"\n=== ollama pull {m} ({attempt}/5) ===")
                if subprocess.run(["ollama", "pull", m]).returncode == 0:
                    break
                print(f"{m} yuklash uzildi — 10 soniyadan keyin davom ettiriladi (tayyor qismlar saqlangan)...")
                time.sleep(10)
            else:
                print(f"{m} yuklanmadi. Internetni tekshirib, keyinroq shu buyruqni qayta ishga tushiring: ollama pull {m}")
                return 1
    print("Tayyor. JARVIS'ni qayta ishga tushiring: Dashboard → AI Router bo'limida modellar holati ko'rinadi.")
    print(json.dumps({"light": rec["light"], "strong": rec["strong"], "vision": rec["vision"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
