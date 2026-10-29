"""Image & Video Studio — mahalliy, bepul vositalar: FFmpeg (video) va Pillow (rasm).

* Kirish fayllari faqat ruxsat berilgan papkalardan o'qiladi, asl fayl o'zgartirilmaydi.
* Natija har doim yangi fayl: <workspace>/exports/ (ustidan yozilmaydi) — B daraja (mahalliy draft).
* AI bilan rasm generatsiyasi bu yerda YO'Q: u GPU (≈4+ GB VRAM, Stable Diffusion) yoki ixtiyoriy onlayn
  adapter talab qiladi. Hozir generator uchun prompt tayyorlanadi.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

SIZES = {"instagram_post": (1080, 1080), "instagram_portrait": (1080, 1350), "story": (1080, 1920),
         "reels": (1080, 1920), "avatar": (512, 512), "youtube_thumb": (1280, 720), "telegram_post": (1280, 720)}


class StudioError(Exception):
    pass


def _srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def build_srt(lines: list[dict]) -> str:
    """lines: [{"start": 0, "end": 2.5, "text": "Salom"}]"""
    out = []
    for i, ln in enumerate(lines, 1):
        if ln["end"] <= ln["start"]:
            raise StudioError(f"{i}-subtitr: tugash vaqti boshlanishdan keyin bo'lishi kerak")
        out.append(f"{i}\n{_srt_time(ln['start'])} --> {_srt_time(ln['end'])}\n{ln['text'].strip()}\n")
    return "\n".join(out)


class Studio:
    def __init__(self, core):
        self.core = core

    # --- umumiy ---
    @property
    def exports(self) -> Path:
        p = Path(self.core.settings.allowed_write_dirs[0]) / "exports"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _out(self, stem: str, ext: str) -> Path:
        name = f"{stem}_{datetime.now():%Y%m%d_%H%M%S_%f}{ext}"
        return self.exports / name

    def _in(self, path: str) -> Path:
        p = self.core.files._check_read(path)
        if not p.is_file():
            raise StudioError(f"Fayl topilmadi: {p.name}")
        return p

    def tools(self) -> dict:
        try:
            import PIL
            pil = PIL.__version__
        except ImportError:
            pil = None
        return {"ffmpeg": bool(shutil.which("ffmpeg")), "ffprobe": bool(shutil.which("ffprobe")), "pillow": pil,
                "image_generation": "yo'q — GPU modeli yoki onlayn adapter kerak (ixtiyoriy, pullik bo'lishi mumkin)"}

    def _log(self, action: str, out: Path):
        self.core.audit.log("studio_agent", action, target=str(out.name), risk="B", result="yangi fayl yaratildi")

    # --- video ---
    def _ffmpeg(self, args: list[str], out: Path) -> Path:
        if not shutil.which("ffmpeg"):
            raise StudioError("FFmpeg topilmadi. Windows: winget install Gyan.FFmpeg (o'zingiz o'rnatasiz)")
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-n", *args, str(out)],
                              capture_output=True, text=True, timeout=900)
        if proc.returncode != 0 or not out.exists():
            raise StudioError(f"FFmpeg xatosi: {proc.stderr.strip()[-500:]}")
        return out

    def probe(self, path: str) -> dict:
        p = self._in(path)
        if not shutil.which("ffprobe"):
            raise StudioError("ffprobe topilmadi")
        proc = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(p)],
                              capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise StudioError(f"Video o'qilmadi: {proc.stderr.strip()[-300:]}")
        data = json.loads(proc.stdout)
        v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
        a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
        return {"file": p.name, "duration": float(data["format"].get("duration", 0)),
                "size_mb": round(int(data["format"].get("size", 0)) / 2**20, 2),
                "bitrate_kbps": int(int(data["format"].get("bit_rate", 0)) / 1000),
                "video": {"codec": v["codec_name"], "width": v["width"], "height": v["height"],
                          "fps": v.get("r_frame_rate")} if v else None,
                "audio": {"codec": a["codec_name"], "channels": a.get("channels")} if a else None}

    def quality_check(self, path: str, target: str = "reels") -> dict:
        info = self.probe(path)
        issues = []
        v = info["video"]
        if not v:
            issues.append("Video oqimi yo'q")
        else:
            tw, th = SIZES.get(target, (None, None))
            if tw and (v["width"], v["height"]) != (tw, th):
                issues.append(f"O'lcham {v['width']}x{v['height']}, {target} uchun {tw}x{th} kerak")
            if v["width"] < 720:
                issues.append("Sifat past (kenglik < 720)")
        if not info["audio"]:
            issues.append("Ovoz yo'q")
        if target == "reels" and not (3 <= info["duration"] <= 90):
            issues.append("Reels uchun davomiylik 3–90 soniya bo'lishi tavsiya etiladi")
        if info["bitrate_kbps"] and info["bitrate_kbps"] < 1000 and v and v["width"] >= 1080:
            issues.append("Bitreyt past (<1000 kbps)")
        return info | {"target": target, "ok": not issues, "issues": issues}

    def trim(self, path: str, start: float, end: float) -> dict:
        p = self._in(path)
        if end <= start or start < 0:
            raise StudioError("Vaqt oralig'i noto'g'ri")
        out = self._ffmpeg(["-ss", str(start), "-to", str(end), "-i", str(p), "-c:v", "libx264", "-preset", "veryfast",
                            "-c:a", "aac"], self._out(p.stem + "_kesilgan", ".mp4"))
        self._log(f"Video kesildi {start}-{end}s: {p.name}", out)
        return {"output": str(out)}

    def concat(self, paths: list[str]) -> dict:
        if len(paths) < 2:
            raise StudioError("Kamida 2 ta video kerak")
        ins = [self._in(x) for x in paths]
        args, filt = [], ""
        for i, p in enumerate(ins):
            args += ["-i", str(p)]
            filt += (f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
                     f"setsar=1,fps=30[v{i}];[{i}:a]aresample=44100[a{i}];")
        filt += "".join(f"[v{i}][a{i}]" for i in range(len(ins))) + f"concat=n={len(ins)}:v=1:a=1[v][a]"
        out = self._ffmpeg([*args, "-filter_complex", filt, "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                            "-preset", "veryfast", "-c:a", "aac"], self._out("birlashtirilgan", ".mp4"))
        self._log(f"{len(ins)} ta video birlashtirildi", out)
        return {"output": str(out), "note": "Har bir video ovozli bo'lishi kerak; natija 1080x1920."}

    def to_vertical(self, path: str, mode: str = "pad") -> dict:
        """Reels/Stories 9:16 (1080x1920). mode=pad — qora chiziq bilan to'liq; crop — markazdan kesish."""
        p = self._in(path)
        vf = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" if mode == "crop" else
              "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black")
        out = self._ffmpeg(["-i", str(p), "-vf", vf + ",setsar=1", "-c:v", "libx264", "-preset", "veryfast",
                            "-c:a", "aac"], self._out(p.stem + "_9x16", ".mp4"))
        self._log(f"9:16 formatga o'tkazildi ({mode}): {p.name}", out)
        return {"output": str(out)}

    def convert(self, path: str, fmt: str) -> dict:
        if fmt not in ("mp4", "webm", "mov", "mp3", "gif"):
            raise StudioError("Format: mp4, webm, mov, mp3, gif")
        p = self._in(path)
        extra = {"mp3": ["-vn"], "gif": ["-vf", "fps=10,scale=480:-1"]}.get(fmt, [])
        out = self._ffmpeg(["-i", str(p), *extra], self._out(p.stem, "." + fmt))
        self._log(f"Format o'zgartirildi → {fmt}: {p.name}", out)
        return {"output": str(out)}

    def add_subtitles(self, path: str, lines: list[dict], burn: bool = True) -> dict:
        p = self._in(path)
        srt = self._out(p.stem + "_subtitr", ".srt")
        srt.write_text(build_srt(lines), encoding="utf-8")
        if not burn:
            return {"output": str(srt), "note": "Faqat .srt fayl yaratildi"}
        esc = str(srt).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        out = self._ffmpeg(["-i", str(p), "-vf", f"subtitles='{esc}':force_style='FontSize=14,Outline=2'",
                            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "copy"], self._out(p.stem + "_sub", ".mp4"))
        self._log(f"Subtitr qo'shildi: {p.name}", out)
        return {"output": str(out), "srt": str(srt)}

    def add_audio(self, video: str, audio: str, mix: bool = False) -> dict:
        v, a = self._in(video), self._in(audio)
        if mix:
            args = ["-i", str(v), "-i", str(a), "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac"]
        else:
            args = ["-i", str(v), "-i", str(a), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest"]
        out = self._ffmpeg(args, self._out(v.stem + "_ovoz", ".mp4"))
        self._log(f"Ovoz qo'shildi: {v.name} + {a.name}", out)
        return {"output": str(out)}

    def slideshow(self, images: list[str], seconds: float = 3.0, audio: str | None = None) -> dict:
        """Kontent rejasidan video: rasmlar → 9:16 slayd-shou (ixtiyoriy fon ovozi)."""
        if not images:
            raise StudioError("Rasm yo'q")
        ins = [self._in(x) for x in images]
        args, filt = [], ""
        for i, p in enumerate(ins):
            args += ["-loop", "1", "-t", str(seconds), "-i", str(p)]
            filt += (f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
                     f"setsar=1,fps=30,format=yuv420p[v{i}];")
        filt += "".join(f"[v{i}]" for i in range(len(ins))) + f"concat=n={len(ins)}:v=1:a=0[v]"
        maps = ["-map", "[v]"]
        if audio:
            args += ["-i", str(self._in(audio))]
            maps += ["-map", f"{len(ins)}:a", "-shortest", "-c:a", "aac"]
        out = self._ffmpeg([*args, "-filter_complex", filt, *maps, "-c:v", "libx264", "-preset", "veryfast"],
                           self._out("slayd", ".mp4"))
        self._log(f"Slayd-shou: {len(ins)} rasm", out)
        return {"output": str(out)}

    # --- rasm ---
    def _pil(self):
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageStat
        except ImportError as e:
            raise StudioError("Rasm uchun 'Pillow' o'rnatilmagan (pip install Pillow)") from e
        return Image, ImageDraw, ImageFont, ImageStat

    def _font(self, size: int):
        _, _, ImageFont, _ = self._pil()
        for f in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
        return ImageFont.load_default(size=size)

    def analyze_image(self, path: str) -> dict:
        Image, _, _, ImageStat = self._pil()
        p = self._in(path)
        with Image.open(p) as im:
            rgb = im.convert("RGB")
            small = rgb.resize((64, 64))
            colors = sorted(small.getcolors(64 * 64), reverse=True)[:5]
            bright = sum(ImageStat.Stat(rgb.convert("L")).mean) / 255
            w, h = im.size
            ratio = w / h
            fits = [k for k, (sw, sh) in SIZES.items() if abs(sw / sh - ratio) < 0.02]
            return {"file": p.name, "format": im.format, "width": w, "height": h, "mode": im.mode,
                    "aspect": round(ratio, 3), "brightness": round(bright, 2),
                    "brightness_note": "qorong'i" if bright < 0.3 else "yorug'" if bright > 0.75 else "o'rtacha",
                    "dominant_colors": ["#%02x%02x%02x" % c[1] for c in colors], "fits_formats": fits,
                    "note": "Bu piksel tahlili. Rasm mazmunini (nima tasvirlangan) tushunish uchun vision model kerak."}

    def resize(self, path: str, preset: str, mode: str = "fit") -> dict:
        Image, _, _, _ = self._pil()
        if preset not in SIZES:
            raise StudioError(f"Preset: {sorted(SIZES)}")
        tw, th = SIZES[preset]
        p = self._in(path)
        with Image.open(p) as im:
            im = im.convert("RGB")
            if mode == "crop":
                scale = max(tw / im.width, th / im.height)
                im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
                left, top = (im.width - tw) // 2, (im.height - th) // 2
                res = im.crop((left, top, left + tw, top + th))
            else:
                im.thumbnail((tw, th), Image.LANCZOS)
                res = Image.new("RGB", (tw, th), (0, 0, 0))
                res.paste(im, ((tw - im.width) // 2, (th - im.height) // 2))
        out = self._out(f"{p.stem}_{preset}", ".jpg")
        res.save(out, quality=92)
        self._log(f"Rasm o'lchami: {preset} ({mode})", out)
        return {"output": str(out), "size": [tw, th]}

    def add_text(self, path: str, text: str, position: str = "bottom", color: str = "#ffffff",
                 band: str = "#000000aa", size: int = 0) -> dict:
        Image, ImageDraw, _, _ = self._pil()
        p = self._in(path)
        with Image.open(p) as im:
            im = im.convert("RGBA")
            size = size or max(18, im.width // 18)
            font = self._font(size)
            layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            box = d.multiline_textbbox((0, 0), text, font=font)
            tw, th = box[2] - box[0], box[3] - box[1]
            pad = size // 2
            y = {"top": pad, "center": (im.height - th) // 2}.get(position, im.height - th - pad * 3)
            d.rectangle((0, y - pad, im.width, y + th + pad * 2), fill=band)
            d.multiline_text(((im.width - tw) // 2, y), text, font=font, fill=color, align="center")
            res = Image.alpha_composite(im, layer).convert("RGB")
        out = self._out(p.stem + "_matn", ".jpg")
        res.save(out, quality=92)
        self._log(f"Rasmga matn qo'shildi: {p.name}", out)
        return {"output": str(out)}

    def make_logo(self, text: str, bg: str = "#06101f", fg: str = "#3cf2ff", shape: str = "circle", size: int = 1024) -> dict:
        """Mahalliy tipografik logo/avatar (bosh harflar). AI generatsiya emas."""
        Image, ImageDraw, _, _ = self._pil()
        initials = "".join(w[0] for w in text.split()[:3]).upper() or "J"
        im = Image.new("RGB", (size, size), bg)
        d = ImageDraw.Draw(im)
        m = size // 12
        if shape == "circle":
            d.ellipse((m, m, size - m, size - m), outline=fg, width=size // 40)
        else:
            d.rounded_rectangle((m, m, size - m, size - m), radius=size // 6, outline=fg, width=size // 40)
        font = self._font(size // (2 + len(initials) // 2))
        box = d.textbbox((0, 0), initials, font=font)
        d.text(((size - (box[2] - box[0])) // 2 - box[0], (size - (box[3] - box[1])) // 2 - box[1]), initials, font=font, fill=fg)
        out = self._out("logo_" + initials, ".png")
        im.save(out)
        self._log(f"Logo yaratildi: {initials}", out)
        return {"output": str(out)}

    @staticmethod
    def image_prompt(subject: str, purpose: str = "instagram_post", style: str = "zamonaviy, toza",
                     brand_colors: str = "", text_on_image: str = "") -> dict:
        """Tashqi rasm generatori uchun aniq prompt (inglizcha — ko'p generatorlar uchun yaxshiroq)."""
        w, h = SIZES.get(purpose, (1080, 1080))
        parts = [f"{subject}", f"style: {style}", f"aspect ratio {w}:{h}", "high detail, professional lighting"]
        if brand_colors:
            parts.append(f"brand colors {brand_colors}")
        if text_on_image:
            parts.append(f'clean space for text "{text_on_image}" (add text later in JARVIS for correct Uzbek spelling)')
        return {"prompt": ", ".join(parts), "negative_prompt": "blurry, watermark, distorted text, extra fingers, low quality",
                "size": [w, h], "note": "Real odamlar, brendlar va mualliflik huquqi bilan himoyalangan obrazlardan ruxsatsiz foydalanmang."}
