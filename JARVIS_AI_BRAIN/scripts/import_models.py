"""Kompyuterdagi tayyor modellarni topib, Ollama'ga ulaydi (qayta yuklamasdan).

  python scripts/import_models.py "C:\\...\\modellar"          — topadi, nima qilinishini ko'rsatadi
  python scripts/import_models.py "C:\\...\\modellar" --apply  — Ollama'ga ulaydi (har biridan oldin so'raydi)

Taniydi:
  *.gguf fayl                          → `ollama create` (Modelfile: FROM <fayl>)
  config.json + *.safetensors papka    → `ollama create` (Ollama qo'llaydigan arxitekturalar uchun)
  model_index.json (diffusers, masalan sd-turbo) → rasm generatsiyasi; Ollama'ga ulanmaydi, faqat ma'lumot beriladi
Ollama'da shu nomli model allaqachon bo'lsa — o'tkazib yuboriladi. Asl fayllar o'chirilmaydi va o'zgartirilmaydi.
Eslatma: `ollama create` faylni o'z papkasiga nusxalaydi — diskda model hajmicha qo'shimcha joy kerak.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jarvis.config import Settings  # noqa: E402

SKIP_GGUF = re.compile(r"(?i)(mmproj|vocab|tokenizer)")


def installed_models() -> set[str]:
    try:
        p = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {ln.split()[0] for ln in p.stdout.splitlines()[1:] if ln.strip()}


def ollama_name(s: str) -> str:
    s = re.sub(r"(?i)\.gguf$", "", s).lower()
    s = re.sub(r"[^a-z0-9._-]+", "-", s).strip("-.")
    return s or "mahalliy-model"


def scan(root: Path) -> list[dict]:
    """Papkani ko'rib chiqadi va har bir topilgan narsa uchun nima qilish mumkinligini qaytaradi."""
    found, seen_dirs = [], set()
    for f in sorted(root.rglob("*.gguf")):
        if SKIP_GGUF.search(f.name):
            continue
        siblings = [g for g in f.parent.glob("*.gguf") if not SKIP_GGUF.search(g.name)]
        name = ollama_name(f.parent.name if f.parent != root and len(siblings) == 1 else f.name)
        found.append({"kind": "gguf", "path": f, "name": name, "mb": f.stat().st_size // 2**20})
        seen_dirs.add(f.parent)
    for cfg in sorted(root.rglob("config.json")):
        d = cfg.parent
        if d in seen_dirs or not list(d.glob("*.safetensors")):
            continue
        if any((p / "model_index.json").exists() for p in [d, *d.parents]):   # diffusers (rasm) modelining qismi
            continue
        if any(p in seen_dirs for p in d.parents):
            continue
        mb = sum(x.stat().st_size for x in d.glob("*.safetensors")) // 2**20
        found.append({"kind": "safetensors", "path": d, "name": ollama_name(d.name), "mb": mb})
        seen_dirs.add(d)
    for idx in sorted(root.rglob("model_index.json")):
        found.append({"kind": "diffusers", "path": idx.parent, "name": idx.parent.name, "mb": None})
    return found


def describe_other(root: Path, found: list[dict]) -> list[str]:
    used = {f["path"] if f["path"].is_dir() else f["path"].parent for f in found}
    notes = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if any(d == u or d in u.parents for u in used):
            continue
        if d.name.lower().startswith("llama.cpp") or list(d.rglob("llama-server*")):
            notes.append(f"{d.name}: llama.cpp dasturi — JARVIS uchun shart emas (Ollama yetarli).")
        else:
            notes.append(f"{d.name}: tanish model formati topilmadi — JARVIS hozircha ishlatmaydi.")
    return notes


def create(item: dict) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        mf = Path(tmp) / "Modelfile"
        mf.write_text(f'FROM "{item["path"]}"\n', encoding="utf-8")
        return subprocess.run(["ollama", "create", item["name"], "-f", str(mf)]).returncode == 0


def ask(q: str, yes: bool) -> bool:
    return yes or input(f"{q} [H/y]: ").strip().lower() in ("", "h", "ha", "y", "yes")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.folder).expanduser()
    if not root.is_dir():
        print(f"Papka topilmadi: {root}")
        return 1
    found = scan(root)
    have = installed_models() if shutil.which("ollama") else set()
    print(f"Papka: {root}\n")
    llm = [f for f in found if f["kind"] in ("gguf", "safetensors")]
    for f in found:
        size = f" (~{f['mb']} MB)" if f["mb"] else ""
        if f["kind"] == "diffusers":
            print(f"  [rasm]  {f['name']}: Stable Diffusion (diffusers) — Ollama'ga ulanmaydi. JARVIS rasm generatsiyasi "
                  "Stable Diffusion WebUI orqali ishlaydi (Sozlamalar → image_gen_url).")
        else:
            status = "allaqachon Ollama'da" if f["name"] in have or f"{f['name']}:latest" in have else "ulash mumkin"
            print(f"  [AI]    {f['name']}{size}: {f['path'].name} — {status}")
    for n in describe_other(root, found):
        print(f"  [—]     {n}")
    if not llm:
        print("\nOllama'ga ulanadigan til modeli (.gguf yoki safetensors) topilmadi.")
        return 0
    if not a.apply:
        print(f'\nUlash uchun: python scripts\\import_models.py "{root}" --apply')
        return 0
    if not shutil.which("ollama"):
        print("Ollama topilmadi — avval o'rnatuvchidan Ollama'ni o'rnating.")
        return 1
    imported = []
    for f in llm:
        if f["name"] in have or f"{f['name']}:latest" in have:
            print(f"\n=== {f['name']}: allaqachon bor — o'tkazib yuborildi ===")
            imported.append(f["name"])
            continue
        if not ask(f"\n{f['name']} (~{f['mb']} MB) Ollama'ga ulansinmi? (diskda shuncha qo'shimcha joy kerak)", a.yes):
            continue
        print(f"=== ollama create {f['name']} ===")
        if create(f):
            imported.append(f["name"])
        else:
            print(f"{f['name']} ulanmadi (Ollama bu formatni qo'llamasligi mumkin). Muqobil: rasmiy modelni 'ollama pull' bilan yuklash.")
    if imported:
        s = Settings.load()
        light = next((p for p in s.ai_providers if p.get("tier") == "light"), None)
        pick = imported[0]
        if ask(f"\nJARVIS oddiy savollar uchun '{pick}' modelidan foydalansinmi? (hozir: {light['model'] if light else s.ollama_model})", a.yes):
            if light:
                light["model"] = pick
            else:
                s.ai_providers.append({"id": "light", "kind": "ollama", "model": pick, "tier": "light", "enabled": True})
            s.ai_provider, s.ollama_model = "ollama", pick
            s.save()
            print(f"Saqlandi: {Settings.path()} — JARVIS'ni qayta ishga tushiring.")
    print("\nTayyor. Tekshirish: ollama list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
