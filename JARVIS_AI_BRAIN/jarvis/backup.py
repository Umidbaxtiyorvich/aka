"""Backup & Disaster Recovery.

* Izchil nusxa: SQLite online backup API (server ishlab turganda ham to'liq, tranzaksiyaga mos).
* Arxiv: `JARVIS_HOME/backups/jarvis_<vaqt>.zip` — jarvis.db, settings.json, (ixtiyoriy) workspace, manifest.json.
* Manifest: har bir fayl SHA-256, DB integrity_check natijasi, jadvallardagi qatorlar soni.
* Tekshirish: zip CRC + SHA-256 + vaqtinchalik papkaga sinov-tiklash va integrity_check + qatorlar soni.
* Maxfiy kalitlar arxivga kirmaydi: ular Credential Manager'da; settings.json skanerlanadi.
* Tiklash — E darajali tasdiq; tiklashdan oldin joriy holatning xavfsizlik nusxasi olinadi.
* Tarix `backups/history.json` da (DB tiklansa ham yo'qolmasin).
GitHub bu nusxalarning o'rnini bosmaydi: kod tarixi ma'lumotlar bazasini saqlamaydi.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings, jarvis_home
from .security import contains_secret


class BackupError(Exception):
    pass


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _counts(conn: sqlite3.Connection) -> dict:
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                                        " AND name NOT LIKE '%_fts%'")]
    return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in sorted(names)}


class BackupManager:
    def __init__(self, core, directory: Path | None = None):
        self.core = core
        self.dir = Path(directory or jarvis_home() / "backups")
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._timer: threading.Thread | None = None
        self._stop = threading.Event()

    # --- tarix ---
    @property
    def history_file(self) -> Path:
        return self.dir / "history.json"

    def _history(self) -> list[dict]:
        try:
            return json.loads(self.history_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _log(self, entry: dict):
        h = self._history()
        h.append(entry | {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        self.history_file.write_text(json.dumps(h[-500:], ensure_ascii=False, indent=1), encoding="utf-8")

    # --- yaratish ---
    def create(self, label: str = "manual", include_workspace: bool | None = None) -> dict:
        include_workspace = self.core.settings.backup_include_workspace if include_workspace is None else include_workspace
        with self._lock:
            try:
                return self._create(label, include_workspace)
            except Exception as e:
                self._log({"action": "create", "ok": False, "label": label, "error": str(e)})
                self.core.notifier.notify("Zaxira nusxa xatosi", str(e), severity="critical", category="backup")
                raise BackupError(f"Zaxira nusxa yaratilmadi: {e}") from e

    def _create(self, label: str, include_workspace: bool) -> dict:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        tmp = Path(tempfile.mkdtemp(prefix="jarvis_bk_"))
        try:
            db_copy = tmp / "jarvis.db"
            dst = sqlite3.connect(db_copy)
            with self.core.db._lock:
                self.core.db.conn.backup(dst)
            integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
            counts = _counts(dst)
            dst.close()
            if integrity != "ok":
                raise BackupError(f"Joriy baza butun emas: {integrity}")
            files = {"jarvis.db": db_copy}
            sp = Settings.path()
            if sp.exists():
                text = sp.read_text(encoding="utf-8")
                if contains_secret(text):
                    raise BackupError("settings.json ichida maxfiy kalitga o'xshash qiymat bor — nusxaga kiritilmadi. Uni olib tashlang.")
                (tmp / "settings.json").write_text(text, encoding="utf-8")
                files["settings.json"] = tmp / "settings.json"
            name = f"jarvis_{stamp}.zip"
            out = self.dir / name
            manifest = {"format": 1, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "label": label,
                        "jarvis_version": __import__("jarvis").__version__, "db_integrity": integrity, "row_counts": counts,
                        "files": {k: {"sha256": _sha(v), "size": v.stat().st_size} for k, v in files.items()},
                        "secrets_included": False, "workspace_included": include_workspace}
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                for arc, p in files.items():
                    z.write(p, arc)
                if include_workspace:
                    ws = Path(self.core.settings.allowed_write_dirs[0])
                    for p in ws.rglob("*"):
                        if p.is_file() and p.stat().st_size < 50 * 2**20 and not contains_secret(p.name):
                            arc = "workspace/" + p.relative_to(ws).as_posix()
                            z.write(p, arc)
                            manifest["files"][arc] = {"sha256": _sha(p), "size": p.stat().st_size}
                z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        size = out.stat().st_size
        self._log({"action": "create", "ok": True, "name": name, "label": label, "size": size})
        self.core.audit.log("backup", f"Zaxira nusxa: {name}", target=name, risk="B", result=f"{size} bayt")
        pruned = self.prune()
        return {"name": name, "size": size, "manifest": manifest, "pruned": pruned}

    # --- tekshirish ---
    def verify(self, name: str) -> dict:
        p = self._path(name)
        res = {"name": name, "ok": False, "checks": []}

        def check(what, ok, note=""):
            res["checks"].append({"check": what, "ok": bool(ok), "note": note})
            return ok

        tmp = Path(tempfile.mkdtemp(prefix="jarvis_verify_"))
        try:
            with zipfile.ZipFile(p) as z:
                bad = z.testzip()
                if not check("zip CRC", bad is None, bad or ""):
                    return self._verified(res)
                manifest = json.loads(z.read("manifest.json"))
                extra = sorted(set(z.namelist()) - set(manifest["files"]) - {"manifest.json"})
                if not check("manifestda yo'q fayl yo'q", not extra, ", ".join(extra)):
                    return self._verified(res)
                z.extractall(tmp)
            for arc, meta in manifest["files"].items():
                f = tmp / arc
                if not check(f"sha256 {arc}", f.exists() and _sha(f) == meta["sha256"]):
                    return self._verified(res)
            conn = sqlite3.connect(tmp / "jarvis.db")
            integ = conn.execute("PRAGMA integrity_check").fetchone()[0]
            counts = _counts(conn)
            conn.close()
            check("sinov-tiklash: integrity_check", integ == "ok", integ)
            check("sinov-tiklash: qatorlar soni", counts == manifest["row_counts"],
                  "" if counts == manifest["row_counts"] else "farq bor")
            check("maxfiy kalitlar yo'q", not manifest.get("secrets_included") and
                  not contains_secret((tmp / "settings.json").read_text(encoding="utf-8") if (tmp / "settings.json").exists() else ""))
            res["ok"] = all(c["ok"] for c in res["checks"])
            res["manifest"] = manifest
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, sqlite3.DatabaseError) as e:
            check("arxivni o'qish", False, str(e))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return self._verified(res)

    def _verified(self, res: dict) -> dict:
        self._log({"action": "verify", "ok": res["ok"], "name": res["name"]})
        if not res["ok"]:
            self.core.notifier.notify("Zaxira nusxa tekshiruvdan o'tmadi", res["name"], severity="critical", category="backup")
        return res

    # --- ro'yxat / retention ---
    def _path(self, name: str) -> Path:
        p = (self.dir / Path(name).name)
        if not p.exists() or p.suffix != ".zip":
            raise BackupError("Zaxira nusxa topilmadi")
        return p

    def list(self) -> list[dict]:
        verified = {}
        for h in self._history():
            if h.get("action") == "verify":
                verified[h["name"]] = {"ok": h["ok"], "ts": h["ts"]}
        out = []
        for p in sorted(self.dir.glob("jarvis_*.zip"), reverse=True):
            try:
                with zipfile.ZipFile(p) as z:
                    m = json.loads(z.read("manifest.json"))
            except Exception:
                m = {"label": "?", "created": None}
            out.append({"name": p.name, "size": p.stat().st_size, "created": m.get("created"), "label": m.get("label"),
                        "last_verify": verified.get(p.name)})
        return out

    def prune(self) -> list[str]:
        s = self.core.settings
        items = sorted(self.dir.glob("jarvis_*.zip"), key=lambda p: p.name, reverse=True)
        keep, removed, total = max(1, s.backup_keep), [], 0
        for i, p in enumerate(items):
            total += p.stat().st_size
            if i >= keep or (i > 0 and total > s.backup_max_total_mb * 2**20):
                removed.append(p.name)
                p.unlink()
        if removed:
            self._log({"action": "prune", "ok": True, "removed": removed})
        return removed

    def status(self) -> dict:
        items = self.list()
        last_ok = next((h for h in reversed(self._history()) if h.get("action") == "create" and h["ok"]), None)
        last_fail = next((h for h in reversed(self._history()) if not h.get("ok")), None)
        age_h = None
        if last_ok:
            age_h = round((datetime.now(timezone.utc) - datetime.fromisoformat(last_ok["ts"])).total_seconds() / 3600, 1)
        return {"count": len(items), "total_mb": round(sum(i["size"] for i in items) / 2**20, 2), "last_success": last_ok,
                "last_failure": last_fail, "age_hours": age_h, "interval_hours": self.core.settings.backup_interval_hours,
                "overdue": age_h is None or age_h > self.core.settings.backup_interval_hours, "directory": str(self.dir),
                "auto_running": bool(self._timer and self._timer.is_alive())}

    # --- tiklash ---
    def request_restore(self, name: str) -> dict:
        v = self.verify(name)
        if not v["ok"]:
            raise BackupError("Nusxa tekshiruvdan o'tmadi — tiklash mumkin emas")
        p = self._path(name)
        return self.core.approvals.request(
            action_type="backup_restore", target="jarvis.db", level="E", requested_by="backup",
            payload={"name": name, "sha256": _sha(p)},
            summary=f"Ma'lumotlarni {name} ({v['manifest']['created']}) holatiga qaytarish. Undan keyingi o'zgarishlar yo'qoladi "
                    "(oldin joriy holatning xavfsizlik nusxasi olinadi).",
            purpose="Ma'lumotlarni tiklash")

    def restore(self, name: str, approval_id: int) -> dict:
        p = self._path(name)
        self.core.approvals.authorize_execution(approval_id, {"name": name, "sha256": _sha(p)})
        v = self.verify(name)
        if not v["ok"]:
            raise BackupError("Nusxa tekshiruvdan o'tmadi")
        safety = self.create(label=f"tiklashdan-oldin ({name})")
        self.core.approvals.mark_result(approval_id, "executed")
        tmp = Path(tempfile.mkdtemp(prefix="jarvis_restore_"))
        try:
            with zipfile.ZipFile(p) as z:
                z.extractall(tmp)
            src = sqlite3.connect(tmp / "jarvis.db")
            with self.core.db._lock:
                src.backup(self.core.db.conn)   # jonli ulanishga — server qayta ishga tushirilmasdan
            src.close()
            if (tmp / "settings.json").exists():
                data = json.loads((tmp / "settings.json").read_text(encoding="utf-8"))
                Settings.path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                for k, val in data.items():
                    if hasattr(self.core.settings, k):
                        setattr(self.core.settings, k, val)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self._log({"action": "restore", "ok": True, "name": name, "safety_backup": safety["name"]})
        self.core.audit.log("backup", f"Tiklandi: {name}", target="jarvis.db", risk="E", approval_status="approved",
                            result=f"xavfsizlik nusxasi: {safety['name']}", verified="integrity_ok")
        self.core.notifier.notify("Ma'lumotlar tiklandi", f"{name}. Oldingi holat: {safety['name']}", severity="warning", category="backup")
        return {"restored": name, "safety_backup": safety["name"]}

    # --- avtomatik jadval ---
    def tick(self) -> dict | None:
        st = self.status()
        if self.core.settings.backup_interval_hours > 0 and st["overdue"]:
            try:
                r = self.create(label="auto")
                self.verify(r["name"])
                return r
            except BackupError:
                return None
        return None

    def start_auto(self, check_every_sec: int = 600):
        if self._timer and self._timer.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.wait(5 if not self.list() else check_every_sec):
                self.tick()
        self._timer = threading.Thread(target=loop, daemon=True)
        self._timer.start()

    def stop_auto(self):
        self._stop.set()
