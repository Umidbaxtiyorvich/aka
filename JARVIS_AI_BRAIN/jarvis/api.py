"""FastAPI: lokal API va dashboard. Standart holatda faqat 127.0.0.1 da ishlaydi."""
from __future__ import annotations


from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, system_info
from .ai_engine import MODEL_CATALOG
from .approval import ApprovalError
from .config import LOCKED_KEYS, PROJECT_ROOT
from .core import CAPABILITIES, JarvisCore
from .files import FileAccessError
from .memory import MemoryError_

DASHBOARD = PROJECT_ROOT / "dashboard"


class ChatIn(BaseModel):
    text: str

class MemoryIn(BaseModel):
    content: str
    kind: str = "long_term"
    project: str | None = None
    source: str = "user"
    confidence: float = 1.0

class MemoryUpdate(BaseModel):
    content: str

class DecideIn(BaseModel):
    approve: bool
    confirm_hash: str

class CommandIn(BaseModel):
    command: str
    reason: str = ""

class TaskIn(BaseModel):
    agent: str
    title: str
    payload: dict = {}

class SettingsIn(BaseModel):
    ai_provider: str | None = None
    ollama_url: str | None = None
    ollama_model: str | None = None


def create_app(core: JarvisCore | None = None) -> FastAPI:
    app = FastAPI(title="JARVIS AI BRAIN", version=__version__)
    app.state.core = core or JarvisCore()
    C = lambda: app.state.core  # noqa: E731

    def guard(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except (ApprovalError, MemoryError_, FileAccessError, ValueError, KeyError) as e:
            raise HTTPException(400, str(e).strip("'"))

    @app.get("/api/status")
    def status():
        c = C()
        ok, note = c.ai.available()
        return {"version": __version__, "system": system_info.snapshot(),
                "ai": {"provider": c.ai.name, "model": getattr(c.ai, "model", None), "available": ok, "note": note},
                "agents": [a.public() for a in c.agents.agents.values()],
                "pending_approvals": len(c.approvals.list("pending")),
                "recent_errors": c.audit.recent_errors(5), "recent_actions": c.audit.recent(8),
                "current_tasks": [t for t in c.agents.tasks(20) if t["status"] in ("queued", "running")],
                "integrations": {"internet": "hali ulanmagan", "pos": "hali ulanmagan",
                                 "telegram": "hali ulanmagan", "instagram": "hali ulanmagan"},
                "settings": {"read_only_mode": c.settings.read_only_mode}, "capabilities": CAPABILITIES}

    @app.get("/api/system")
    def system():
        s = system_info.snapshot(include_gpu=True)
        s["recommended_model"] = system_info.recommend_model(s["ram_total_gb"])
        s["model_catalog"] = MODEL_CATALOG
        return s

    @app.post("/api/chat")
    def chat(body: ChatIn):
        if not body.text.strip():
            raise HTTPException(400, "Bo'sh xabar")
        return C().chat(body.text)

    @app.get("/api/chat/history")
    def history(limit: int = 50):
        return C().db.query("SELECT * FROM conversations ORDER BY id DESC LIMIT ?", (limit,))[::-1]

    # Xotira
    @app.get("/api/memory")
    def mem_list(kind: str | None = None, q: str | None = None):
        return C().memory.search(q) if q else C().memory.list(kind)

    @app.post("/api/memory")
    def mem_add(body: MemoryIn):
        return guard(C().memory.add, body.content, body.kind, project=body.project, source=body.source,
                     confidence=body.confidence)

    @app.put("/api/memory/{mid}")
    def mem_update(mid: int, body: MemoryUpdate):
        return guard(C().memory.update, mid, body.content)

    @app.delete("/api/memory/{mid}")
    def mem_delete(mid: int):
        guard(C().memory.delete, mid)
        return {"deleted": mid}

    @app.get("/api/memory/export", response_class=PlainTextResponse)
    def mem_export():
        return C().memory.export()

    # Tasdiqlar
    @app.get("/api/approvals")
    def appr_list(status: str | None = None):
        return C().approvals.list(status)

    @app.post("/api/approvals/{aid}/decide")
    def appr_decide(aid: int, body: DecideIn):
        return guard(C().approvals.decide, aid, body.approve, body.confirm_hash)

    @app.post("/api/approvals/{aid}/execute")
    def appr_execute(aid: int):
        c = C()
        row = guard(c.approvals.get, aid)
        if row["action_type"] != "shell_command":
            raise HTTPException(400, "Bu turdagi amal uchun ijrochi hali yo'q")
        return guard(c.computer.execute, aid, row["payload"])

    # Kompyuter / agentlar / vazifalar
    @app.post("/api/computer/propose")
    def propose(body: CommandIn):
        return C().computer.propose(body.command, body.reason)

    @app.get("/api/agents")
    def agents():
        return [a.public() for a in C().agents.agents.values()]

    @app.post("/api/tasks")
    def task_submit(body: TaskIn):
        return guard(C().agents.submit, body.agent, body.title, body.payload)

    @app.get("/api/tasks")
    def tasks(limit: int = 50):
        return C().agents.tasks(limit)

    @app.get("/api/tasks/{tid}")
    def task(tid: int):
        t = C().agents.task(tid)
        if not t:
            raise HTTPException(404, "Topilmadi")
        return t

    # Fayllar
    @app.get("/api/files")
    def files(path: str | None = None):
        return {"root": C().settings.allowed_read_dirs, "items": guard(C().files.list_dir, path)}

    @app.get("/api/files/read")
    def file_read(path: str):
        r = guard(C().files.read, path)
        r["text"] = r["text"][:20000]
        return r

    # Audit / xatolar
    @app.get("/api/audit")
    def audit(limit: int = 100):
        return C().audit.recent(limit)

    @app.get("/api/errors")
    def errors(limit: int = 50):
        return C().audit.recent_errors(limit)

    # Sozlamalar — xavfsizlik kalitlari API orqali o'zgartirilmaydi
    @app.get("/api/settings")
    def settings_get():
        return C().settings.public() | {"locked_keys": sorted(LOCKED_KEYS)}

    @app.post("/api/settings")
    def settings_set(body: SettingsIn):
        c = C()
        data = body.model_dump(exclude_none=True)
        if "ai_provider" in data and data["ai_provider"] not in ("offline", "ollama"):
            raise HTTPException(400, "ai_provider: offline yoki ollama")
        for k, v in data.items():
            setattr(c.settings, k, v)
        c.settings.save()
        c.reload_ai()
        c.audit.log("user", f"Sozlamalar o'zgartirildi: {sorted(data)}", target="settings", risk="C",
                    approval_status="user_action")
        return c.settings.public()

    @app.get("/")
    def index():
        return FileResponse(DASHBOARD / "index.html")

    app.mount("/static", StaticFiles(directory=DASHBOARD), name="static")
    return app


def main():
    import argparse
    import uvicorn
    ap = argparse.ArgumentParser(description="JARVIS AI BRAIN serveri")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    if a.host not in ("127.0.0.1", "localhost"):
        print("OGOHLANTIRISH: server tarmoqqa ochilmoqda. Autentifikatsiya hali yo'q — faqat ishonchli tarmoqda!")
    uvicorn.run(create_app(), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
