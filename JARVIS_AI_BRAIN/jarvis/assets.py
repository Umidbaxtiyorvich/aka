"""Digital Asset Manager — ruxsat berilgan papkalar indeksi, qidiruv, dublikatlar, tasnif va zaxira nusxa.

* Faqat `allowed_read_dirs` ichida; maxfiy nomli fayllar (.env, kalitlar) va yashirin papkalar o'tkaziladi, symlink'lar kuzatilmaydi.
* Hech narsa o'chirilmaydi yoki ko'chirilmaydi: dublikatlar faqat ko'rsatiladi, zaxira — JARVIS papkasiga NUSXA.
* Qidiruv hozircha kalit so'z (nom + matn parchasi) bo'yicha; vektor (semantik) qidiruv Memory Brain bosqichida qo'shiladi.
* 8 GB RAM: fayllar oqim bilan xeshlanadi, matn parchasi 2000 belgi, indeks cheklangan (20 000 fayl).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import jarvis_home
from .security import contains_secret, is_within

SCHEMA = """
CREATE TABLE IF NOT EXISTS file_index (
    path TEXT PRIMARY KEY, root TEXT NOT NULL, name TEXT NOT NULL, ext TEXT, size INTEGER NOT NULL, mtime REAL NOT NULL,
    sha256 TEXT, category TEXT NOT NULL, snippet TEXT, indexed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_file_sha ON file_index(sha256);
CREATE INDEX IF NOT EXISTS idx_file_cat ON file_index(category);
"""
CATS = {"document": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md"}, "spreadsheet": {".xls", ".xlsx", ".xlsm", ".ods", ".csv", ".tsv"},
        "presentation": {".ppt", ".pptx", ".odp"}, "image": {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".bmp", ".heic"},
        "audio": {".mp3", ".wav", ".m4a", ".ogg", ".flac"}, "video": {".mp4", ".mov", ".avi", ".mkv", ".webm"},
        "code": {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".java", ".c", ".cpp", ".php", ".sql", ".sh", ".ps1", ".go", ".rs", ".json", ".yaml", ".yml", ".toml", ".xml"},
        "archive": {".zip", ".7z", ".rar", ".tar", ".gz"}}
TEXTY = {".txt", ".md", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".xml", ".html", ".css", ".py", ".js", ".ts", ".sql", ".sh", ".ps1", ".go", ".rs", ".java", ".c", ".cpp", ".php"}
SKIP_NAMES = {".env", "id_rsa", "id_ed25519", "credentials", "passwords", "secrets", "jarvis.db"}
SKIP_EXT = {".key", ".pem", ".kdbx", ".pfx", ".p12"}
MAX_FILES = 20_000
HASH_MAX = 200 * 2**20


def category(ext: str) -> str:
    return next((c for c, exts in CATS.items() if ext in exts), "other")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class AssetError(Exception):
    pass


class AssetManager:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        self.state = {"running": False, "last": None}
        self._lock = threading.Lock()

    def index(self, background: bool = False) -> dict:
        if background:
            threading.Thread(target=self.index, daemon=True).start()
            return {"started": True}
        if not self._lock.acquire(blocking=False):
            raise AssetError("Indekslash allaqachon ishlamoqda")
        self.state["running"] = True
        stats = {"seen": 0, "new": 0, "updated": 0, "removed": 0, "skipped": 0, "limit_reached": False}
        try:
            db, seen = self.core.db, set()
            for root in self.core.settings.allowed_read_dirs:
                r = Path(root)
                if not r.is_dir():
                    continue
                for dirpath, dirnames, filenames in os.walk(r, followlinks=False):
                    dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("__pycache__", "node_modules", ".git")]
                    for fn in filenames:
                        p = Path(dirpath) / fn
                        if stats["seen"] >= MAX_FILES:
                            stats["limit_reached"] = True
                            break
                        if fn.lower() in SKIP_NAMES or p.suffix.lower() in SKIP_EXT or fn.startswith(".") or p.is_symlink():
                            stats["skipped"] += 1
                            continue
                        try:
                            st = p.stat()
                        except OSError:
                            continue
                        stats["seen"] += 1
                        key = str(p)
                        seen.add(key)
                        old = db.one("SELECT size, mtime FROM file_index WHERE path=?", (key,))
                        if old and old["size"] == st.st_size and abs(old["mtime"] - st.st_mtime) < 1e-6:
                            continue
                        ext = p.suffix.lower()
                        try:
                            digest = sha256_file(p) if st.st_size <= HASH_MAX else None
                        except OSError:
                            digest = None
                        snippet = None
                        if ext in TEXTY and st.st_size <= 2 * 2**20:
                            try:
                                snippet = p.read_text(encoding="utf-8", errors="replace")[:2000]
                            except OSError:
                                snippet = None
                            if snippet and contains_secret(snippet):
                                snippet = None                        # maxfiy ma'lumotli matn indeksga yozilmaydi
                        db.execute("INSERT INTO file_index(path, root, name, ext, size, mtime, sha256, category, snippet, indexed_at) VALUES (?,?,?,?,?,?,?,?,?,datetime('now')) "
                                   "ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime, sha256=excluded.sha256, category=excluded.category, "
                                   "snippet=excluded.snippet, indexed_at=excluded.indexed_at",
                                   (key, str(r), fn, ext, st.st_size, st.st_mtime, digest, category(ext), snippet))
                        stats["updated" if old else "new"] += 1
            for row in db.query("SELECT path, root FROM file_index"):
                if row["path"] not in seen and (not Path(row["path"]).exists() or not is_within(row["path"], self.core.settings.allowed_read_dirs)):
                    db.execute("DELETE FROM file_index WHERE path=?", (row["path"],))
                    stats["removed"] += 1
            self.state["last"] = {**stats, "at": datetime.now(timezone.utc).isoformat()}
            return self.state["last"]
        finally:
            self.state["running"] = False
            self._lock.release()

    def search(self, q: str = "", cat: str = "", limit: int = 100) -> list[dict]:
        terms = [t.lower() for t in q.split() if t.strip()][:6]
        sql, p = "SELECT path, name, ext, size, category, mtime, sha256, substr(snippet,1,300) snippet FROM file_index WHERE 1=1", []
        if cat:
            sql += " AND category=?"
            p.append(cat)
        for t in terms:
            sql += " AND (lower(name) LIKE ? OR lower(COALESCE(snippet,'')) LIKE ?)"
            p += [f"%{t}%", f"%{t}%"]
        rows = self.core.db.query(sql + " ORDER BY mtime DESC LIMIT ?", (*p, min(limit, 500)))
        for r in rows:
            r["score"] = sum((t in r["name"].lower()) * 2 + (t in (r["snippet"] or "").lower()) for t in terms)
        return sorted(rows, key=lambda r: -r["score"])

    def duplicates(self, limit: int = 100) -> dict:
        groups = []
        for g in self.core.db.query("SELECT sha256, COUNT(*) n, MAX(size) size FROM file_index WHERE sha256 IS NOT NULL AND size>0 GROUP BY sha256 HAVING n>1 "
                                    "ORDER BY size*(n-1) DESC LIMIT ?", (limit,)):
            files = [r["path"] for r in self.core.db.query("SELECT path FROM file_index WHERE sha256=? ORDER BY mtime", (g["sha256"],))]
            groups.append({"sha256": g["sha256"][:16], "count": g["n"], "size": g["size"], "wasted": g["size"] * (g["n"] - 1), "files": files})
        return {"groups": groups, "wasted_total": sum(x["wasted"] for x in groups),
                "note": "Hech narsa avtomatik o'chirilmaydi — qaysi nusxani saqlashni o'zingiz hal qilasiz."}

    def stats(self) -> dict:
        rows = self.core.db.query("SELECT category, COUNT(*) n, SUM(size) size FROM file_index GROUP BY category ORDER BY n DESC")
        return {"categories": rows, "total": sum(r["n"] for r in rows), "state": self.state, "roots": self.core.settings.allowed_read_dirs}

    def backup(self, path: str) -> dict:
        p = Path(path).resolve()
        if not is_within(p, self.core.settings.allowed_read_dirs) or not p.is_file():
            raise AssetError("Fayl ruxsat berilgan papkada emas yoki topilmadi")
        if p.stat().st_size > 500 * 2**20:
            raise AssetError("Fayl 500 MB dan katta")
        dest_dir = jarvis_home() / "asset_backups" / datetime.now().strftime("%Y%m%d")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest, n = dest_dir / p.name, 1
        while dest.exists():
            dest, n = dest_dir / f"{p.stem}_{n}{p.suffix}", n + 1
        shutil.copy2(p, dest)
        self.core.audit.log("assets", f"Zaxira nusxa: {p.name}", target=str(dest), risk="B", approval_status="auto")
        return {"source": str(p), "backup": str(dest), "size": dest.stat().st_size}
