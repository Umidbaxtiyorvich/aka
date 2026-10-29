"""Ma'lumotlar bazasining zaxira nusxasi (SQLite online backup). Tiklash: nusxani jarvis.db o'rniga qo'ying."""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jarvis.config import jarvis_home  # noqa: E402

src = jarvis_home() / "jarvis.db"
dst_dir = jarvis_home() / "backups"
dst_dir.mkdir(exist_ok=True)
dst = dst_dir / f"jarvis_{datetime.now():%Y%m%d_%H%M%S}.db"
with sqlite3.connect(src) as a, sqlite3.connect(dst) as b:
    a.backup(b)
print(f"Zaxira: {dst}")
