"""Task Dependency Graph — bog'liq vazifalarni boshqarish.

* Vazifalar va bog'liqliklar (depends_on); sikl va yo'q bog'liqlik yaratishda tekshiriladi.
* Mustaqil vazifalar parallel bajariladi, lekin faqat xavfsiz bo'lsa:
  - bir agent bir vaqtda bitta vazifa (agent holati umumiy);
  - AI ishlatadigan "og'ir" agentlar bir vaqtda faqat bittadan (8 GB RAM);
  - parallel darajasi bo'sh RAM va CPU bo'yicha cheklanadi.
* Takrorni kamaytirish: bir run ichidagi bir xil vazifa (agent+payload) bir marta bajariladi; idempotent
  (faqat o'qiydigan) agentlarning yaqinda bajarilgan natijasi qayta ishlatiladi.
* Xato: unga bog'liq vazifalar 'blocked' bo'ladi, mustaqil tarmoqlar davom etadi.
* Bekor qilish: yangi vazifalar boshlanmaydi; ishlayotganlar tugaydi, lekin ularga bog'liqlar boshlanmaydi.
* Tasdiq kutayotgan vazifa: bog'liqlari kutadi; tasdiq bajarilgach run davom ettiriladi.
* Ishonchlilik (Mission Engine uchun): natija tekshiruvi (verifier), qayta urinish (faqat idempotent agentlar —
  tashqi ta'sirli amal ikki marta bajarilmaydi), urinishlar tugasa — dead-letter; pauza; har tugagan vazifa —
  checkpoint (bazada). Qayta ishga tushganda: 'running' qolgan idempotent vazifalar qaytadan, qolganlari dead-letter.
"""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS dag_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, goal TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    max_parallel INTEGER, created_at TEXT NOT NULL DEFAULT (datetime('now')), finished_at TEXT
);
CREATE TABLE IF NOT EXISTS dag_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, key TEXT NOT NULL, title TEXT NOT NULL,
    agent TEXT NOT NULL, payload TEXT NOT NULL, depends_on TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|running|done|reused|failed|blocked|cancelled|waiting_approval
    result TEXT, error TEXT, task_id INTEGER, cache_key TEXT, reused_from INTEGER, approval_id INTEGER,
    started_at TEXT, finished_at TEXT, UNIQUE(run_id, key)
);
"""
HEAVY = {"manager", "research"}            # AI modeli ishlatishi mumkin
IDEMPOTENT = {"file_analysis", "security", "developer", "bi", "research", "browser"}
DONE = {"done", "reused"}
FAILED = {"failed", "blocked", "cancelled"}
PARALLEL_SPLIT = re.compile(r"\s+hamda\s+|\s*&\s*|\s+parallel\s+", re.I)


class DagError(Exception):
    pass


def cache_key(agent: str, payload: dict) -> str:
    return hashlib.sha256((agent + json.dumps(payload, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


def topo_levels(nodes: list[dict]) -> dict[str, int]:
    keys = {n["key"] for n in nodes}
    deps = {n["key"]: list(n.get("depends_on") or []) for n in nodes}
    for k, ds in deps.items():
        missing = [d for d in ds if d not in keys]
        if missing:
            raise DagError(f"'{k}' mavjud bo'lmagan vazifaga bog'liq: {missing}")
        if k in ds:
            raise DagError(f"'{k}' o'ziga bog'liq bo'lolmaydi")
    level, remaining = {}, dict(deps)
    while remaining:
        ready = [k for k, ds in remaining.items() if all(d in level for d in ds)]
        if not ready:
            raise DagError(f"Bog'liqliklarda sikl bor: {sorted(remaining)}")
        for k in ready:
            level[k] = 1 + max((level[d] for d in remaining[k]), default=-1)
            del remaining[k]
    return level


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


NODE_COLUMNS = {"attempts": "INTEGER NOT NULL DEFAULT 0", "max_attempts": "INTEGER NOT NULL DEFAULT 2", "verified": "INTEGER",
                "verify_note": "TEXT", "dead_letter": "INTEGER NOT NULL DEFAULT 0"}


class TaskGraph:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)
        core.db.ensure_columns("dag_nodes", NODE_COLUMNS)
        core.db.ensure_columns("dag_runs", {"stop_reason": "TEXT"})
        self.verifier = None          # callable(node, task) -> (ok: bool, note: str); Mission Engine o'rnatadi

    # --- yaratish ---
    def create(self, goal: str, nodes: list[dict]) -> dict:
        if not nodes:
            raise DagError("Vazifalar ro'yxati bo'sh")
        if len({n["key"] for n in nodes}) != len(nodes):
            raise DagError("Vazifa kalitlari takrorlanmasligi kerak")
        for n in nodes:
            a = self.core.agents.agents.get(n["agent"])
            if a is None or a.handler is None:
                raise DagError(f"Agent topilmadi: {n['agent']}")
        topo_levels(nodes)
        cur = self.core.db.execute("INSERT INTO dag_runs(goal) VALUES (?)", (goal,))
        rid = cur.lastrowid
        for n in nodes:
            payload = n.get("payload") or {}
            self.core.db.execute(
                "INSERT INTO dag_nodes(run_id, key, title, agent, payload, depends_on, cache_key) VALUES (?,?,?,?,?,?,?)",
                (rid, n["key"], n.get("title") or n["key"], n["agent"], json.dumps(payload, ensure_ascii=False),
                 json.dumps(n.get("depends_on") or []), cache_key(n["agent"], payload)))
        self.core.audit.log("dag", f"Vazifalar grafi: {goal[:80]} ({len(nodes)} vazifa)", target=f"dag#{rid}", risk="B")
        if hasattr(self.core, "kgraph"):
            self.core.kgraph.link(("dag", rid, goal[:80]), "has_goal", ("goal", goal[:200], goal[:80]))
        return self.get(rid)

    def from_text(self, goal: str) -> dict:
        """'keyin' — ketma-ket bosqich; 'hamda' yoki '&' — bir bosqich ichidagi parallel vazifalar."""
        from .planner import split_goal, step_for
        nodes, prev = [], []
        for si, stage in enumerate(split_goal(goal)):
            cur = []
            for pi, part in enumerate(p.strip() for p in PARALLEL_SPLIT.split(stage) if p.strip()):
                st = step_for(part)
                key = f"s{si + 1}_{pi + 1}"
                nodes.append({"key": key, "title": part, "agent": st["agent"], "payload": st["payload"], "depends_on": list(prev)})
                cur.append(key)
            prev = cur
        return self.create(goal, nodes)

    # --- o'qish ---
    def _node(self, r: dict) -> dict:
        r["payload"], r["depends_on"] = json.loads(r["payload"]), json.loads(r["depends_on"])
        return r

    def nodes(self, rid: int) -> list[dict]:
        return [self._node(r) for r in self.core.db.query("SELECT * FROM dag_nodes WHERE run_id=? ORDER BY id", (rid,))]

    def get(self, rid: int) -> dict:
        run = self.core.db.one("SELECT * FROM dag_runs WHERE id=?", (rid,))
        if not run:
            raise DagError("Graf topilmadi")
        nodes = self.nodes(rid)
        levels = topo_levels(nodes)
        for n in nodes:
            n["level"] = levels[n["key"]]
        edges = [{"from": d, "to": n["key"]} for n in nodes for d in n["depends_on"]]
        counts: dict[str, int] = {}
        for n in nodes:
            counts[n["status"]] = counts.get(n["status"], 0) + 1
        return run | {"nodes": nodes, "edges": edges, "counts": counts}

    def list(self) -> list[dict]:
        return [self.get(r["id"]) for r in self.core.db.query("SELECT id FROM dag_runs ORDER BY id DESC LIMIT 30")]

    # --- boshqaruv ---
    def cancel(self, rid: int) -> dict:
        self.get(rid)
        self.core.db.execute("UPDATE dag_runs SET status='cancelled', finished_at=? WHERE id=?", (_now(), rid))
        self.core.db.execute("UPDATE dag_nodes SET status='cancelled', error='run bekor qilindi' WHERE run_id=? AND status='pending'", (rid,))
        self.core.audit.log("user", f"Vazifalar grafi bekor qilindi: dag#{rid}", target=f"dag#{rid}", risk="B", approval_status="user_action")
        return self.get(rid)

    def pause(self, rid: int, reason: str = "foydalanuvchi to'xtatdi") -> dict:
        self.get(rid)
        self.core.db.execute("UPDATE dag_runs SET status='paused', stop_reason=? WHERE id=? AND status IN ('pending','running')", (reason, rid))
        return self.get(rid)

    def retry_node(self, rid: int, key: str) -> dict:
        """Dead-letter yoki xato vazifani foydalanuvchi qo'lda qayta navbatga qo'yadi (bog'liqlari ham qayta ochiladi)."""
        n = self.core.db.one("SELECT * FROM dag_nodes WHERE run_id=? AND key=?", (rid, key))
        if not n or n["status"] not in ("failed", "blocked", "cancelled"):
            raise DagError("Faqat bajarilmagan vazifani qayta urinish mumkin")
        self._set(n["id"], status="pending", error=None, dead_letter=0, attempts=0, finished_at=None)
        self.core.db.execute("UPDATE dag_nodes SET status='pending', error=NULL WHERE run_id=? AND status IN ('blocked','cancelled')", (rid,))
        self.core.db.execute("UPDATE dag_runs SET status='pending', stop_reason=NULL, finished_at=NULL WHERE id=?", (rid,))
        self.core.audit.log("user", f"Vazifa qayta navbatga: dag#{rid}/{key}", target=f"dag#{rid}", risk="B", approval_status="user_action")
        return self.get(rid)

    def recover(self) -> list[int]:
        """Qayta ishga tushgandan keyin: uzilib qolgan run'lar 'paused', vazifalar xavfsiz holatga qaytariladi."""
        out = []
        for r in self.core.db.query("SELECT id FROM dag_runs WHERE status='running'"):
            for n in self.nodes(r["id"]):
                if n["status"] != "running":
                    continue
                if n["agent"] in IDEMPOTENT:
                    self._set(n["id"], status="pending", error="qayta ishga tushirishda uzilgan — qayta bajariladi")
                else:
                    self._set(n["id"], status="failed", dead_letter=1, finished_at=_now(),
                              error="Uzilib qoldi. Tashqi ta'sir ikki marta bo'lmasligi uchun avtomatik takrorlanmadi — tekshirib, qo'lda qayta urining.")
            self.core.db.execute("UPDATE dag_runs SET status='paused', stop_reason='JARVIS qayta ishga tushdi' WHERE id=?", (r["id"],))
            out.append(r["id"])
        return out

    def safe_parallel(self, requested: int | None = None) -> int:
        try:
            import psutil
            free_gb = psutil.virtual_memory().available / 2**30
            cores = psutil.cpu_count(logical=False) or psutil.cpu_count() or 1
        except Exception:
            return 1
        if free_gb < 1.5:
            return 1
        return max(1, min(requested or 3, max(1, cores // 2), 4))

    def _set(self, nid: int, **f):
        cols = ", ".join(f"{k}=?" for k in f)
        self.core.db.execute(f"UPDATE dag_nodes SET {cols} WHERE id=?", (*f.values(), nid))

    def _refresh_waiting(self, rid: int):
        for n in self.nodes(rid):
            if n["status"] != "waiting_approval" or not n["approval_id"]:
                continue
            st = self.core.approvals.get(n["approval_id"])["status"]
            if st == "executed":
                self._set(n["id"], status="done", finished_at=_now())
            elif st in ("rejected", "invalidated", "expired"):
                self._set(n["id"], status="failed", error=f"tasdiq holati: {st}", finished_at=_now())

    def _try_reuse(self, rid: int, n: dict, nodes: list[dict]) -> bool:
        twin = next((m for m in nodes if m["id"] != n["id"] and m["cache_key"] == n["cache_key"] and m["status"] in DONE), None)
        if twin is None and n["agent"] in IDEMPOTENT:
            twin = self.core.db.one(
                "SELECT * FROM dag_nodes WHERE cache_key=? AND status='done' AND run_id<>? AND"
                " julianday('now') - julianday(finished_at) < 10.0/1440 ORDER BY id DESC LIMIT 1", (n["cache_key"], rid))
        if twin:
            self._set(n["id"], status="reused", result=twin["result"], reused_from=twin["id"], finished_at=_now())
            return True
        return False

    def _execute(self, n: dict) -> dict:
        t = self.core.agents.submit(n["agent"], f"Graf #{n['run_id']}: {n['title']}", n["payload"], run_now=True)
        if hasattr(self.core, "kgraph"):
            self.core.kgraph.link(("dag", n["run_id"], None), "has_task", ("task", t["id"], t["title"]))
        return t

    def run(self, rid: int, max_parallel: int | None = None, stop_check=None) -> dict:
        """stop_check() -> sabab | None: masalan vaqt yoki xarajat limiti (Mission Engine) — run pauzaga o'tadi."""
        run = self.get(rid)
        if run["status"] == "cancelled":
            raise DagError("Graf bekor qilingan")
        par = self.safe_parallel(max_parallel)
        self.core.db.execute("UPDATE dag_runs SET status='running', max_parallel=?, stop_reason=NULL WHERE id=?", (par, rid))
        self._refresh_waiting(rid)
        running: dict = {}
        with ThreadPoolExecutor(max_workers=par) as pool:
            while True:
                rstat = self.core.db.one("SELECT status FROM dag_runs WHERE id=?", (rid,))["status"]
                if rstat == "running" and stop_check:
                    why = stop_check()
                    if why:
                        self.core.db.execute("UPDATE dag_runs SET status='paused', stop_reason=? WHERE id=?", (why, rid))
                        rstat = "paused"
                cancelled = rstat in ("cancelled", "paused")      # pauza: yangi vazifa boshlanmaydi, ishlayotganlari tugaydi
                nodes = self.nodes(rid)
                by_key = {n["key"]: n for n in nodes}
                started = False
                if not cancelled:
                    busy_agents = {n["agent"] for n in nodes if n["status"] == "running"}
                    heavy_busy = any(a in HEAVY for a in busy_agents)
                    for n in nodes:
                        if n["status"] != "pending":
                            continue
                        dep_states = [by_key[d]["status"] for d in n["depends_on"]]
                        if any(s in FAILED for s in dep_states):
                            bad = [d for d in n["depends_on"] if by_key[d]["status"] in FAILED]
                            self._set(n["id"], status="blocked", error=f"bog'liq vazifa bajarilmadi: {bad}", finished_at=_now())
                            started = True
                            continue
                        if not all(s in DONE for s in dep_states):
                            continue
                        if any(m["cache_key"] == n["cache_key"] and m["status"] == "running" for m in nodes):
                            continue   # egizagi ishlayapti — natijasini kutamiz
                        if self._try_reuse(rid, n, nodes):
                            started = True
                            continue
                        if len(running) >= par or n["agent"] in busy_agents or (n["agent"] in HEAVY and heavy_busy):
                            continue
                        self._set(n["id"], status="running", started_at=_now())
                        n["status"] = "running"
                        busy_agents.add(n["agent"])
                        heavy_busy = heavy_busy or n["agent"] in HEAVY
                        running[pool.submit(self._execute, n)] = n
                        started = True
                if not running:
                    if started:
                        continue
                    break
                done, _ = wait(list(running), return_when=FIRST_COMPLETED)
                for f in done:
                    n = running.pop(f)
                    attempts = (n.get("attempts") or 0) + 1
                    try:
                        t = f.result()
                    except Exception as e:
                        t = {"id": None, "status": "failed", "result": None, "error": f"{type(e).__name__}: {e}"[:500]}
                    if t["status"] == "done" and self.verifier:
                        try:
                            ok, note = self.verifier(n, t)
                        except Exception as e:
                            ok, note = False, f"tekshiruv xatosi: {e}"
                        self._set(n["id"], verified=int(ok), verify_note=note[:300])
                        if not ok:
                            t = t | {"status": "failed", "error": f"Natija tekshiruvdan o'tmadi: {note}"}
                    if t["status"] == "failed":
                        can_retry = attempts < (n.get("max_attempts") or 1) and n["agent"] in IDEMPOTENT
                        if can_retry:
                            self._set(n["id"], status="pending", attempts=attempts, error=f"{attempts}-urinish: {(t.get('error') or '')[:300]} — qayta urinilmoqda",
                                      task_id=t["id"])
                            continue
                        self._set(n["id"], status="failed", attempts=attempts, dead_letter=1, result=t.get("result"), error=(t.get("error") or "xato")[:500],
                                  task_id=t["id"], finished_at=_now())
                        continue
                    approval_id = None
                    if t["status"] == "waiting_approval":
                        try:
                            approval_id = json.loads(t["result"]).get("approval", {}).get("id")
                        except (TypeError, ValueError, AttributeError):
                            approval_id = None
                    self._set(n["id"], status={"done": "done", "failed": "failed", "waiting_approval": "waiting_approval"}.get(t["status"], "failed"),
                              result=t["result"], error=t["error"], task_id=t["id"], approval_id=approval_id, attempts=attempts,
                              finished_at=_now() if t["status"] != "waiting_approval" else None)
        nodes = self.nodes(rid)
        sts = {n["status"] for n in nodes}
        rstat = self.core.db.one("SELECT status FROM dag_runs WHERE id=?", (rid,))["status"]
        if rstat == "cancelled":
            final = "cancelled"
        elif rstat == "paused" and "pending" in sts:
            final = "paused"
        elif sts <= DONE:
            final = "done"
        elif "waiting_approval" in sts:
            final = "waiting_approval"
        elif sts & DONE:
            final = "partial"
        else:
            final = "failed"
        self.core.db.execute("UPDATE dag_runs SET status=?, finished_at=? WHERE id=?",
                             (final, _now() if final not in ("waiting_approval", "paused") else None, rid))
        if final in ("failed", "partial"):
            self.core.notifier.notify(f"Vazifalar grafi #{rid}: {final}", run["goal"][:150], severity="warning", category="task")
        return self.get(rid)
