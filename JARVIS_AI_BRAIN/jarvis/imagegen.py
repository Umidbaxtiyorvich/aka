"""Rasm generatsiyasi va vision tahlil — faqat MAHALLIY, bepul vositalar orqali (ixtiyoriy).

* Generatsiya: Stable Diffusion WebUI (AUTOMATIC1111 / Forge) API — `image_gen_url` (masalan http://127.0.0.1:7860,
  `--api` bilan ishga tushirilgan). Talab: NVIDIA GPU ~4+ GB VRAM (SD 1.5), 6–8 GB (SDXL). CPU'da juda sekin.
  Model fayllari 2–7 GB — o'zingiz yuklaysiz; JARVIS avtomatik yuklamaydi.
* Vision: Ollama vision modeli — `vision_model` (masalan `moondream` ≈1.7 GB, `llava:7b` ≈4.7 GB, `qwen2.5vl:3b`).
  Rasm tashqariga yuborilmaydi (faqat mahalliy Ollama).
Natijalar `workspace/exports/` ga yangi fayl sifatida yoziladi (B daraja — mahalliy draft).
"""
from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path

from . import net


class ImageGenError(Exception):
    pass


class ImageGen:
    def __init__(self, core):
        self.core = core

    @property
    def s(self):
        return self.core.settings

    def status(self) -> dict:
        out = {"generator_url": self.s.image_gen_url or None, "vision_model": self.s.vision_model or None}
        if self.s.image_gen_url:
            try:
                models = net.get_json(self.s.image_gen_url.rstrip("/") + "/sdapi/v1/sd-models", timeout=3)
                out["generator"] = {"available": True, "models": [m.get("model_name") for m in models][:20]}
            except net.NetError as e:
                out["generator"] = {"available": False, "note": f"Stable Diffusion WebUI javob bermadi: {e}"}
        else:
            out["generator"] = {"available": False, "note": "Sozlanmagan (image_gen_url). GPU va Stable Diffusion WebUI kerak."}
        out["vision"] = {"available": bool(self.s.vision_model), "note": "" if self.s.vision_model else "vision_model sozlanmagan"}
        return out

    def _save(self, b64: str, stem: str) -> str:
        d = Path(self.s.allowed_write_dirs[0]) / "exports"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{stem}_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
        p.write_bytes(base64.b64decode(b64.split(",", 1)[-1]))
        return str(p)

    def _post(self, path: str, body: dict, timeout: int = 600) -> dict:
        if not self.s.image_gen_url:
            raise ImageGenError("Rasm generatori sozlanmagan: Sozlamalar → image_gen_url (Stable Diffusion WebUI, --api)")
        try:
            return net.post_json(self.s.image_gen_url.rstrip("/") + path, json_body=body, timeout=timeout)
        except net.NetError as e:
            raise ImageGenError(f"Generator xatosi: {e}") from None

    def generate(self, prompt: str, *, negative: str = "", width: int = 1024, height: int = 1024, steps: int = 25,
                 seed: int = -1, count: int = 1) -> dict:
        if not prompt.strip():
            raise ImageGenError("Prompt bo'sh")
        width, height = (max(256, min(int(x) // 8 * 8, 2048)) for x in (width, height))
        r = self._post("/sdapi/v1/txt2img", {"prompt": prompt, "negative_prompt": negative, "width": width, "height": height,
                                              "steps": max(1, min(steps, 80)), "seed": seed, "batch_size": max(1, min(count, 4))})
        files = [self._save(b, "generatsiya") for b in r.get("images", [])]
        if not files:
            raise ImageGenError("Generator rasm qaytarmadi")
        info = r.get("info")
        meta = json.loads(info) if isinstance(info, str) else (info or {})
        self.core.audit.log("image_agent", f"Rasm yaratildi ({len(files)})", target="local_sd", risk="B", result=prompt[:100])
        return {"outputs": files, "seed": meta.get("seed"), "prompt": prompt,
                "note": "AI yaratgan rasm. Real odam, brend yoki mualliflik huquqi bilan himoyalangan obrazlarni ruxsatsiz ishlatmang."}

    def edit(self, path: str, prompt: str, *, strength: float = 0.5, negative: str = "") -> dict:
        src = self.core.files._check_read(path)
        b64 = base64.b64encode(src.read_bytes()).decode()
        r = self._post("/sdapi/v1/img2img", {"init_images": [b64], "prompt": prompt, "negative_prompt": negative,
                                              "denoising_strength": max(0.05, min(float(strength), 0.95))})
        files = [self._save(b, src.stem + "_tahrir") for b in r.get("images", [])]
        if not files:
            raise ImageGenError("Generator rasm qaytarmadi")
        self.core.audit.log("image_agent", f"Rasm tahrirlandi: {src.name}", target="local_sd", risk="B")
        return {"outputs": files, "source": str(src)}

    def describe(self, path: str, question: str = "Bu rasmda nima tasvirlangan? O'zbek tilida qisqa tasvirlab ber.") -> dict:
        """Mahalliy vision model bilan rasm mazmunini tahlil qilish (rasm tashqariga chiqmaydi)."""
        if not self.s.vision_model:
            raise ImageGenError("Vision model sozlanmagan (masalan: ollama pull moondream, so'ng vision_model=moondream)")
        src = self.core.files._check_read(path)
        if src.stat().st_size > 15 * 2**20:
            raise ImageGenError("Rasm 15 MB dan katta")
        body = {"model": self.s.vision_model, "stream": False,
                "messages": [{"role": "user", "content": question, "images": [base64.b64encode(src.read_bytes()).decode()]}]}
        try:
            r = net.post_json(self.s.ollama_url.rstrip("/") + "/api/chat", json_body=body, timeout=self.s.ai_timeout_sec * 3)
        except net.NetError as e:
            raise ImageGenError(f"Ollama vision xatosi: {e}") from None
        text = (r.get("message") or {}).get("content", "").strip()
        if not text:
            raise ImageGenError("Vision model bo'sh javob qaytardi")
        self.core.guard.record(provider="ollama-vision", model=self.s.vision_model, purpose="vision", tokens_in=r.get("prompt_eval_count"),
                               tokens_out=r.get("eval_count"), tokens_measured=r.get("eval_count") is not None, ok=True)
        return {"file": src.name, "model": self.s.vision_model, "description": text,
                "info_type": "model_inference", "note": "Model xulosasi — tekshirilmagan fakt sifatida qabul qilinmaydi."}
