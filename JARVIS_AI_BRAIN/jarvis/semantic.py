"""Semantik xotira — ma'no bo'yicha qidiruv (mahalliy embedding modeli, Ollama).

* Model: `nomic-embed-text` (~270 MB). JARVIS uni O'ZI YUKLAMAYDI: foydalanuvchi dashboard'da hajmni ko'rib, aniq tasdiqlaydi.
  Model bo'lmasa — oddiy kalit so'z (FTS) qidiruvi ishlaydi va bu holat ochiq ko'rsatiladi.
* Vektorlar JARVIS bazasida (`memory_vectors`) — AI provayderdan mustaqil; matn tashqariga chiqmaydi (faqat mahalliy Ollama).
* Gibrid qidiruv: FTS + vektor natijalari Reciprocal Rank Fusion bilan birlashtiriladi.
* 8 GB RAM: fon indekslash kichik partiyalarda; numpy bo'lsa tez, bo'lmasa sof Python (sekinroq, lekin ishlaydi).
"""
from __future__ import annotations

import hashlib
import math
import struct
import threading

from . import net

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_vectors (
    memory_id INTEGER PRIMARY KEY, model TEXT NOT NULL, dim INTEGER NOT NULL, vec BLOB NOT NULL, content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""
MODEL_SIZE_MB = 274


class SemanticError(Exception):
    pass


def _pack(v: list[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


def _unpack(b: bytes) -> list[float]:
    return list(struct.unpack(f"{len(b) // 4}f", b))


def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class SemanticMemory:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        self._lock = threading.Lock()
        self.state = {"indexing": False, "pulling": False, "last": None, "error": None}

    @property
    def model(self) -> str:
        return self.core.settings.embedding_model or ""

    @property
    def base(self) -> str:
        return self.core.settings.ollama_url.rstrip("/")

    def status(self) -> dict:
        installed, ollama = False, False
        try:
            tags = net.get_json(self.base + "/api/tags", timeout=3)
            ollama = True
            names = {m.get("name", "") for m in tags.get("models", [])}
            want = self.model or "nomic-embed-text"
            installed = any(n == want or n.split(":")[0] == want.split(":")[0] for n in names)
        except net.NetError:
            pass
        total = self.core.db.one("SELECT COUNT(*) n FROM memories")["n"]
        done = self.core.db.one("SELECT COUNT(*) n FROM memory_vectors WHERE model=?", (self.model,))["n"] if self.model else 0
        return {"enabled": bool(self.model), "model": self.model or None, "suggested_model": "nomic-embed-text", "size_mb": MODEL_SIZE_MB,
                "ollama": ollama, "installed": installed, "indexed": done, "total": total, "state": self.state,
                "mode": "gibrid (ma'no + kalit so'z)" if self.ready() else "faqat kalit so'z (semantik model yoqilmagan)"}

    def ready(self) -> bool:
        return bool(self.model) and self.core.db.one("SELECT 1 FROM memory_vectors WHERE model=? LIMIT 1", (self.model,)) is not None

    # ---------------- model ----------------
    def install(self, confirm: bool, model: str = "nomic-embed-text") -> dict:
        """Foydalanuvchi aniq tasdiqlagan holda modelni yuklaydi (fonda). confirm=False — faqat nima yuklanishini aytadi."""
        if not confirm:
            return {"needs_confirm": True, "model": model, "size_mb": MODEL_SIZE_MB,
                    "note": f"Mahalliy Ollama'ga ~{MODEL_SIZE_MB} MB model yuklanadi. Internet va diskdan joy kerak. Tasdiqlaysizmi?"}
        if self.state["pulling"]:
            raise SemanticError("Yuklash allaqachon ketmoqda")
        self.core.audit.log("user", f"Embedding modeli yuklashga ruxsat berildi: {model} (~{MODEL_SIZE_MB} MB)", target="ollama", risk="C",
                            approval_status="user_action")

        def run():
            self.state.update(pulling=True, error=None)
            try:
                net.post_json(self.base + "/api/pull", json_body={"model": model, "stream": False}, timeout=3600)
                self.core.settings.embedding_model = model
                self.core.settings.save()
                self.index()
            except net.NetError as e:
                self.state["error"] = f"Yuklab bo'lmadi: {e}"
            finally:
                self.state["pulling"] = False
        threading.Thread(target=run, daemon=True).start()
        return {"started": True, "model": model}

    def enable(self, model: str) -> dict:
        """Model allaqachon o'rnatilgan bo'lsa — faqat yoqish (yuklash yo'q)."""
        self.core.settings.embedding_model = model
        self.core.settings.save()
        return self.status()

    # ---------------- embedding ----------------
    def embed(self, text: str) -> list[float]:
        if not self.model:
            raise SemanticError("Semantik model yoqilmagan")
        try:
            r = net.post_json(self.base + "/api/embeddings", json_body={"model": self.model, "prompt": text[:4000]}, timeout=60)
        except net.NetError as e:
            raise SemanticError(f"Ollama embedding xatosi: {e}") from None
        v = r.get("embedding")
        if not v:
            raise SemanticError("Embedding qaytmadi")
        return _norm([float(x) for x in v])

    def index(self, batch: int = 16, limit: int = 5000) -> dict:
        if not self.model:
            raise SemanticError("Semantik model yoqilmagan")
        if not self._lock.acquire(blocking=False):
            return {"busy": True}
        self.state["indexing"] = True
        done = errors = 0
        try:
            rows = self.core.db.query("SELECT id, content FROM memories ORDER BY id DESC LIMIT ?", (limit,))
            have = {r["memory_id"]: r["content_hash"] for r in self.core.db.query("SELECT memory_id, content_hash FROM memory_vectors WHERE model=?", (self.model,))}
            for i, r in enumerate(rows):
                h = hashlib.sha256(r["content"].encode()).hexdigest()[:16]
                if have.get(r["id"]) == h:
                    continue
                try:
                    v = self.embed(r["content"])
                except SemanticError as e:
                    errors += 1
                    self.state["error"] = str(e)
                    if errors >= 3:
                        break
                    continue
                self.core.db.execute("INSERT OR REPLACE INTO memory_vectors(memory_id, model, dim, vec, content_hash) VALUES (?,?,?,?,?)",
                                     (r["id"], self.model, len(v), _pack(v), h))
                done += 1
            ids = {r["id"] for r in self.core.db.query("SELECT id FROM memories")}
            for mid in set(have) - ids:                                   # o'chirilgan xotiralar vektorlari ham o'chadi
                self.core.db.execute("DELETE FROM memory_vectors WHERE memory_id=?", (mid,))
            self.state["last"] = {"embedded": done, "errors": errors}
            return self.state["last"]
        finally:
            self.state["indexing"] = False
            self._lock.release()

    def _vectors(self) -> tuple[list[int], list]:
        rows = self.core.db.query("SELECT memory_id, vec FROM memory_vectors WHERE model=?", (self.model,))
        return [r["memory_id"] for r in rows], [r["vec"] for r in rows]

    def _scores(self, q: list[float], blobs: list) -> list[float]:
        try:
            import numpy as np
            if not blobs:
                return []
            m = np.frombuffer(b"".join(blobs), dtype=np.float32).reshape(len(blobs), -1)
            return (m @ np.asarray(q, dtype=np.float32)).tolist()
        except ImportError:
            return [sum(a * b for a, b in zip(q, _unpack(b))) for b in blobs]

    def search(self, query: str, k: int = 10, min_score: float = 0.35) -> list[dict]:
        q = self.embed(query)
        ids, blobs = self._vectors()
        scored = sorted(zip(ids, self._scores(q, blobs)), key=lambda x: -x[1])[:k]
        out = []
        for mid, sc in scored:
            if sc < min_score:
                continue
            m = self.core.db.one("SELECT * FROM memories WHERE id=?", (mid,))
            if m:
                out.append(m | {"score": round(sc, 3)})
        return out

    def hybrid(self, query: str, k: int = 5) -> list[dict]:
        """FTS + vektor (RRF). Semantik tayyor bo'lmasa — faqat FTS (halol rejim)."""
        fts = self.core.memory.search(query, limit=k * 2)
        if not self.ready():
            return [m | {"match": "kalit so'z"} for m in fts[:k]]
        try:
            vec = self.search(query, k * 2)
        except SemanticError:
            return [m | {"match": "kalit so'z"} for m in fts[:k]]
        score, rows = {}, {}
        for rank, m in enumerate(fts):
            score[m["id"]] = score.get(m["id"], 0) + 1 / (60 + rank)
            rows[m["id"]] = m | {"match": "kalit so'z"}
        for rank, m in enumerate(vec):
            score[m["id"]] = score.get(m["id"], 0) + 1 / (60 + rank)
            rows[m["id"]] = m | {"match": "ma'no" if m["id"] not in rows else "ma'no + kalit so'z"}
        return [rows[i] for i in sorted(score, key=lambda i: -score[i])[:k]]

    def similar(self, memory_id: int, threshold: float = 0.92) -> list[dict]:
        """Ma'no bo'yicha deyarli bir xil xotiralar (takror/qarama-qarshilik nomzodlari)."""
        r = self.core.db.one("SELECT vec FROM memory_vectors WHERE memory_id=? AND model=?", (memory_id, self.model))
        if not r:
            return []
        q = _unpack(r["vec"])
        ids, blobs = self._vectors()
        out = []
        for mid, sc in zip(ids, self._scores(q, blobs)):
            if mid != memory_id and sc >= threshold:
                m = self.core.db.one("SELECT id, content, kind FROM memories WHERE id=?", (mid,))
                if m:
                    out.append(m | {"score": round(sc, 3)})
        return sorted(out, key=lambda x: -x["score"])
