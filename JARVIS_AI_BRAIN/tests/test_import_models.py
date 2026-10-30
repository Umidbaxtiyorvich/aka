import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import import_models  # noqa: E402


def _tree(root: Path):
    (root / "qwen3-1.7b").mkdir(parents=True)
    (root / "qwen3-1.7b" / "Qwen3-1.7B-Q4_K_M.gguf").write_bytes(b"GGUF" + b"0" * 10)
    (root / "qwen3-1.7b" / "mmproj-f16.gguf").write_bytes(b"GGUF")
    (root / "sd-turbo" / "unet").mkdir(parents=True)
    (root / "sd-turbo" / "model_index.json").write_text("{}")
    (root / "sd-turbo" / "unet" / "config.json").write_text("{}")
    (root / "sd-turbo" / "unet" / "x.safetensors").write_bytes(b"0")
    (root / "llama.cpp").mkdir()
    (root / "llama.cpp" / "llama-server.exe").write_bytes(b"0")
    (root / "depth").mkdir()


def test_scan_finds_llm_and_skips_diffusers(tmp_path):
    _tree(tmp_path)
    found = import_models.scan(tmp_path)
    kinds = {(f["kind"], f["name"]) for f in found}
    assert ("gguf", "qwen3-1.7b") in kinds and ("diffusers", "sd-turbo") in kinds
    assert not [f for f in found if "mmproj" in str(f["path"])]
    assert not [f for f in found if f["kind"] == "safetensors"]          # sd-turbo/unet til modeli emas
    notes = " ".join(import_models.describe_other(tmp_path, found))
    assert "llama.cpp dasturi" in notes and "depth" in notes


def test_apply_creates_and_skips_existing(tmp_path, monkeypatch):
    _tree(tmp_path / "m")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    calls = []

    class P:
        returncode, stdout = 0, "NAME ID SIZE MODIFIED\n"

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return P()
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(import_models.shutil, "which", lambda x: "ollama")
    assert import_models.main([str(tmp_path / "m"), "--apply", "--yes"]) == 0
    assert ["ollama", "create", "qwen3-1.7b"] == calls[-1][:3]
    from jarvis.config import Settings
    assert Settings.load().ollama_model == "qwen3-1.7b"
    P.stdout = "NAME ID SIZE MODIFIED\nqwen3-1.7b:latest a 1GB now\n"
    calls.clear()
    import_models.main([str(tmp_path / "m"), "--apply", "--yes"])
    assert not [c for c in calls if c[:2] == ["ollama", "create"]]


def test_setup_ai_prefers_installed_models():
    import setup_ai
    sizes = {"qwen3:4b-instruct": 2.5, "umid-ai:latest": 4.9, "llama3.2:latest": 2.0, "llama3.1:8b": 4.9, "nomic-embed-text": 0.3}
    assert setup_ai.pick_installed(sizes, 7.7, 4.0) == {"light": "llama3.2:latest", "strong": "qwen3:4b-instruct"}
    assert setup_ai.pick_installed({"llama3:latest": 4.7}, 7.7, 4.0) is None      # 8 GB RAM uchun katta
