"""File Intelligence: faqat ruxsat berilgan papkalarda qidirish/o'qish/tahlil. Yozish — tasdiq orqali."""
from __future__ import annotations

import csv
import io
from pathlib import Path

from .security import contains_secret, is_within

TEXT_EXT = {".txt", ".md", ".py", ".js", ".json", ".html", ".css", ".log", ".ini", ".yaml", ".yml", ".csv"}
SENSITIVE_NAMES = {".env", "id_rsa", "credentials", "passwords", "secrets"}
MAX_BYTES = 2_000_000


class FileAccessError(Exception):
    pass


class FileIntelligence:
    def __init__(self, settings):
        self.settings = settings

    def _check_read(self, path: str) -> Path:
        p = Path(path).resolve()
        if not is_within(p, self.settings.allowed_read_dirs):
            raise FileAccessError(f"Ruxsat berilmagan joy: {p}")
        if p.name.lower() in SENSITIVE_NAMES or p.suffix.lower() in {".key", ".pem", ".kdbx"}:
            raise FileAccessError("Maxfiy fayl — o'qilmaydi.")
        return p

    def list_dir(self, path: str | None = None) -> list[dict]:
        p = self._check_read(path or self.settings.allowed_read_dirs[0])
        if not p.is_dir():
            raise FileAccessError("Bu papka emas")
        return [{"name": c.name, "dir": c.is_dir(), "size": c.stat().st_size if c.is_file() else None}
                for c in sorted(p.iterdir())][:500]

    def search(self, pattern: str) -> list[str]:
        out = []
        for root in self.settings.allowed_read_dirs:
            r = Path(root)
            if r.exists():
                out += [str(x) for x in r.rglob(f"*{pattern}*")][:200]
        return out

    def read(self, path: str) -> dict:
        p = self._check_read(path)
        if not p.is_file():
            raise FileAccessError("Fayl topilmadi")
        if p.stat().st_size > MAX_BYTES:
            raise FileAccessError("Fayl juda katta (2 MB dan ortiq)")
        ext = p.suffix.lower()
        if ext == ".xlsx":
            text, kind = self._read_xlsx(p), "excel"
        elif ext == ".pdf":
            text, kind = self._read_pdf(p), "pdf"
        elif ext in TEXT_EXT:
            text, kind = p.read_text(encoding="utf-8", errors="replace"), "text"
        else:
            raise FileAccessError(f"Qo'llab-quvvatlanmaydigan format: {ext}")
        return {"path": str(p), "kind": kind, "text": text, "has_secret": contains_secret(text),
                "analysis": self.analyze(text, ext)}

    @staticmethod
    def analyze(text: str, ext: str) -> dict:
        info = {"chars": len(text), "lines": text.count("\n") + 1 if text else 0, "words": len(text.split())}
        if ext == ".csv":
            rows = list(csv.reader(io.StringIO(text)))
            info.update(rows=max(0, len(rows) - 1), columns=rows[0] if rows else [])
        return info

    @staticmethod
    def _read_xlsx(p: Path) -> str:
        try:
            import openpyxl
        except ImportError as e:
            raise FileAccessError("Excel uchun 'openpyxl' o'rnatilmagan") from e
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        lines = []
        for ws in wb.worksheets:
            lines.append(f"# {ws.title}")
            for row in ws.iter_rows(values_only=True):
                lines.append(",".join("" if v is None else str(v) for v in row))
        return "\n".join(lines)

    @staticmethod
    def _read_pdf(p: Path) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise FileAccessError("PDF uchun 'pypdf' o'rnatilmagan") from e
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(p)).pages)

    def write_target_allowed(self, path: str) -> Path:
        p = Path(path).resolve()
        if not is_within(p, self.settings.allowed_write_dirs):
            raise FileAccessError(f"Bu joyga yozish taqiqlangan: {p}")
        return p
