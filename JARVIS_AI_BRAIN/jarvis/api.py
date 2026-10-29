"""FastAPI: lokal API va dashboard. Standart holatda faqat 127.0.0.1 da ishlaydi."""
from __future__ import annotations

from pathlib import Path


from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, system_info
from .ai_engine import MODEL_CATALOG
from .approval import ApprovalError
from .config import LOCKED_KEYS, PROJECT_ROOT
from .core import CAPABILITIES, JarvisCore
from .backup import BackupError
from .bi import BIError
from .dag import DagError
from .decisions import DecisionError
from .browser import BrowserError
from .files import FileAccessError
from .improve import ImproveError
from .instagram import InstagramError, suggest_hashtags
from .kgraph import KGError
from .memory import MemoryError_
from .planner import PlannerError
from .plugins import PluginError
from .pos import POSError
from .research import ResearchError
from .sandbox import SandboxError
from .studio import StudioError
from .telegram_bot import TelegramError
from .telephony import TelephonyError
from .voice import VoiceError

USER_ERRORS = (ApprovalError, MemoryError_, FileAccessError, ValueError, KeyError, BIError, POSError, ResearchError,
               StudioError, InstagramError, TelegramError, TelephonyError, VoiceError, BrowserError, PlannerError, ImproveError,
               DecisionError, SandboxError, BackupError, DagError, KGError, PluginError)
# Sozlamalar API orqali o'zgartirilishi mumkin bo'lgan (xavfsizlikka oid bo'lmagan) kalitlar
EDITABLE = {"ai_provider", "ollama_url", "ollama_model", "internet_enabled", "browser_allowed_domains", "telegram_notify",
            "pos_site", "pos_connector", "low_stock_threshold", "save_voice_recordings",
            "ai_providers", "paid_ai_allowed", "currency", "daily_cost_limit", "monthly_cost_limit", "daily_request_limit",
            "cost_warn_percent", "medium_auto_actions", "sandbox_backend", "sandbox_timeout_sec", "sandbox_memory_mb",
            "sandbox_max_retries", "backup_interval_hours", "backup_keep", "backup_max_total_mb", "backup_include_workspace"}
PROVIDER_KINDS = {"ollama", "openai_compatible", "anthropic", "offline"}

DASHBOARD = PROJECT_ROOT / "dashboard"


class ChatIn(BaseModel):
    text: str

class MemoryIn(BaseModel):
    content: str
    kind: str = "long_term"
    project: str | None = None
    source: str = "user"
    confidence: float = 1.0
    info_type: str | None = None
    reference: str = ""
    observed_at: str | None = None

class VerifyIn(BaseModel):
    reference: str
    note: str = ""

class DecisionIn(BaseModel):
    problem: str
    options: list[str]
    chosen: str
    rationale: str
    sources: list[str] = []
    risks: str = ""
    expected_outcome: str = ""
    review_at: str = ""
    project: str = ""
    files: list[str] = []

class DecisionUpdateIn(BaseModel):
    actual_outcome: str | None = None
    review_at: str | None = None
    status: str | None = None
    note: str = ""

class DecisionReviseIn(BaseModel):
    reason: str
    changes: dict = {}

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
    internet_enabled: bool | None = None
    browser_allowed_domains: list[str] | None = None
    telegram_notify: bool | None = None
    pos_site: str | None = None
    pos_connector: str | None = None
    low_stock_threshold: float | None = None
    save_voice_recordings: bool | None = None
    ai_providers: list[dict] | None = None
    paid_ai_allowed: bool | None = None
    currency: str | None = None
    daily_cost_limit: float | None = None
    monthly_cost_limit: float | None = None
    daily_request_limit: int | None = None
    cost_warn_percent: int | None = None
    medium_auto_actions: list[str] | None = None
    sandbox_backend: str | None = None
    sandbox_timeout_sec: int | None = None
    sandbox_memory_mb: int | None = None
    sandbox_max_retries: int | None = None
    backup_interval_hours: float | None = None
    backup_keep: int | None = None
    backup_max_total_mb: int | None = None
    backup_include_workspace: bool | None = None

class OpIn(BaseModel):
    """Umumiy so'rov: modul amali va parametrlari."""
    op: str
    params: dict = {}

class ImportIn(BaseModel):
    path: str
    kind: str

class PosDraftIn(BaseModel):
    doc_type: str
    party: str
    items: list[dict]
    note: str = ""
    account: str = ""

class PosUpdateIn(BaseModel):
    items: list[dict]
    party: str | None = None
    note: str | None = None

class IgDraftIn(BaseModel):
    account: str
    kind: str = "post"
    caption: str
    media_url: str = ""
    scheduled_at: str = ""
    hashtags: list[str] | None = None

class IgReplyIn(BaseModel):
    account: str
    comment_id: str
    comment_text: str
    reply: str = ""

class TextIn(BaseModel):
    text: str

class UrlIn(BaseModel):
    url: str

class ProposalIn(BaseModel):
    title: str
    diff: str
    description: str = ""

class SandboxIn(BaseModel):
    code: str
    allow_network: bool = False
    stdin: str | None = None
    approval_id: int | None = None

class BackupIn(BaseModel):
    label: str = "manual"
    include_workspace: bool | None = None

class RestoreIn(BaseModel):
    approval_id: int

class DagIn(BaseModel):
    goal: str
    nodes: list[dict] | None = None

class DagRunIn(BaseModel):
    max_parallel: int | None = None

class KGLinkIn(BaseModel):
    src_type: str
    src_ref: str
    rel: str
    dst_type: str
    dst_ref: str

class PluginRunIn(BaseModel):
    input: dict = {}

class PluginStatusIn(BaseModel):
    status: str

class CallIn(BaseModel):
    phone: str
    message: str
    reason: str
    est_minutes: float = 1.0


def create_app(core: JarvisCore | None = None) -> FastAPI:
    app = FastAPI(title="JARVIS AI BRAIN", version=__version__)
    app.state.core = core or JarvisCore()
    C = lambda: app.state.core  # noqa: E731

    def guard(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except USER_ERRORS as e:
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
                "integrations": {
                    "internet": "yoqilgan" if c.settings.internet_enabled else "o'chirilgan",
                    "pos": (c.settings.pos_site or "manzil berilmagan") + f" · {c.pos.connector.name}",
                    "telegram": "ishlayapti" if c.telegram.status()["running"] else ("sozlangan" if c.telegram.configured() else "sozlanmagan"),
                    "instagram": f"{len(c.settings.instagram_accounts)} akkaunt",
                    "telefon": "sozlangan" if c.settings.telephony_provider else "o'chirilgan"},
                "unread_notifications": len(c.notifier.list(unread_only=True)),
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
                     confidence=body.confidence, info_type=body.info_type, reference=body.reference,
                     observed_at=body.observed_at)

    @app.put("/api/memory/{mid}")
    def mem_update(mid: int, body: MemoryUpdate):
        return guard(C().memory.update, mid, body.content)

    @app.delete("/api/memory/{mid}")
    def mem_delete(mid: int):
        guard(C().memory.delete, mid)
        return {"deleted": mid}

    @app.get("/api/memory/{mid}/provenance")
    def mem_prov(mid: int):
        return guard(C().memory.provenance, mid)

    @app.post("/api/memory/{mid}/verify")
    def mem_verify(mid: int, body: VerifyIn):
        return guard(C().memory.verify, mid, body.reference, body.note)

    @app.get("/api/knowledge/compare")
    def mem_compare(q: str):
        return C().memory.compare(q)

    @app.get("/api/knowledge/stale")
    def mem_stale():
        return C().memory.stale_items()

    # Decision Journal
    @app.get("/api/decisions")
    def dec_list(q: str = "", status: str = ""):
        return C().decisions.list(q, status)

    @app.get("/api/decisions/due")
    def dec_due():
        return C().decisions.due_for_review()

    @app.post("/api/decisions")
    def dec_create(body: DecisionIn):
        return guard(C().decisions.create, **body.model_dump())

    @app.get("/api/decisions/compare")
    def dec_compare(a: int, b: int):
        return guard(C().decisions.compare, a, b)

    @app.get("/api/decisions/{did}")
    def dec_get(did: int):
        return guard(C().decisions.get, did) | {"chain": C().decisions.history(did)}

    @app.post("/api/decisions/{did}/update")
    def dec_update(did: int, body: DecisionUpdateIn):
        fields = {k: v for k, v in body.model_dump(exclude={"note"}).items() if v is not None}
        return guard(C().decisions.update, did, note=body.note, **fields)

    @app.post("/api/decisions/{did}/revise")
    def dec_revise(did: int, body: DecisionReviseIn):
        return guard(C().decisions.revise, did, reason=body.reason, **body.changes)

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
        if row["action_type"] not in ("shell_command", "shell_read"):
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
        data = {k: v for k, v in body.model_dump(exclude_none=True).items() if k in EDITABLE}
        if "pos_connector" in data and data["pos_connector"] not in ("file_export", "api", "browser"):
            raise HTTPException(400, "pos_connector: file_export, api yoki browser")
        for prov in data.get("ai_providers") or []:
            if not isinstance(prov, dict) or not prov.get("id") or prov.get("kind") not in PROVIDER_KINDS or not prov.get("model"):
                raise HTTPException(400, f"Provayder noto'g'ri: id, kind ({sorted(PROVIDER_KINDS)}), model kerak")
            if prov["kind"] in ("openai_compatible", "anthropic"):
                prov["paid"], prov["local"] = True, False
                if prov["kind"] == "openai_compatible" and not str(prov.get("base_url", "")).startswith("https://"):
                    raise HTTPException(400, "Tashqi provayder uchun https:// base_url kerak")
        if "medium_auto_actions" in data:
            from .policy import ACTIONS
            bad = [a for a in data["medium_auto_actions"] if ACTIONS.get(a, ("high",))[0] != "medium"]
            if bad:
                raise HTTPException(400, f"Faqat o'rta xavfli amallar avtomatik qilinadi. Mumkin emas: {bad}")
        if "sandbox_backend" in data and data["sandbox_backend"] not in ("process", "docker"):
            raise HTTPException(400, "sandbox_backend: process yoki docker")
        if "ai_provider" in data and data["ai_provider"] not in ("offline", "ollama"):
            raise HTTPException(400, "ai_provider: offline yoki ollama")
        for k, v in data.items():
            setattr(c.settings, k, v)
        c.settings.save()
        c.reload_ai()
        if "pos_connector" in data:
            from .pos import FileExportConnector, NotConfiguredConnector
            c.pos.connector = FileExportConnector() if data["pos_connector"] == "file_export" else NotConfiguredConnector(data["pos_connector"])
        c.audit.log("user", f"Sozlamalar o'zgartirildi: {sorted(data)}", target="settings", risk="C",
                    approval_status="user_action")
        return c.settings.public()

    # AI Router / Resource Guard / Policy
    @app.get("/api/ai/router")
    def ai_router():
        c = C()
        return {"providers": c.ai.status(), "last_route": c.ai.last_route, "metrics": c.guard.providers()}

    @app.post("/api/ai/route-preview")
    def ai_preview(body: TextIn):
        p = C().ai.plan([{"role": "user", "content": body.text}])
        return {"complexity": p["complexity"], "private": p["private"], "skipped": p["skipped"],
                "order": [x["id"] for x in p["candidates"]]}

    @app.get("/api/guard")
    def guard_summary():
        c = C()
        return c.guard.summary() | {"local_model": c.guard.local_model_resources()}

    @app.get("/api/policy")
    def policy_table():
        return C().policy.table()

    @app.post("/api/policy/evaluate")
    def policy_eval(body: OpIn):
        return C().policy.evaluate(body.op, body.params.get("level"), command=body.params.get("command")).public()

    # Backup & recovery
    @app.get("/api/backups")
    def bk_list():
        c = C()
        return {"status": c.backup.status(), "items": c.backup.list(), "history": c.backup._history()[-30:][::-1]}

    @app.post("/api/backups")
    def bk_create(body: BackupIn):
        return guard(C().backup.create, body.label, body.include_workspace)

    @app.post("/api/backups/{name}/verify")
    def bk_verify(name: str):
        return guard(C().backup.verify, name)

    @app.post("/api/backups/{name}/request-restore")
    def bk_req(name: str):
        return guard(C().backup.request_restore, name)

    @app.post("/api/backups/{name}/restore")
    def bk_restore(name: str, body: RestoreIn):
        return guard(C().backup.restore, name, body.approval_id)

    # Task Dependency Graph
    @app.get("/api/dag")
    def dag_list():
        return C().dag.list()

    @app.post("/api/dag")
    def dag_create(body: DagIn):
        c = C()
        return guard(c.dag.create, body.goal, body.nodes) if body.nodes else guard(c.dag.from_text, body.goal)

    @app.get("/api/dag/{rid}")
    def dag_get(rid: int):
        return guard(C().dag.get, rid)

    @app.post("/api/dag/{rid}/run")
    def dag_run(rid: int, body: DagRunIn):
        return guard(C().dag.run, rid, body.max_parallel)

    @app.post("/api/dag/{rid}/cancel")
    def dag_cancel(rid: int):
        return guard(C().dag.cancel, rid)

    # Knowledge Graph
    @app.get("/api/kg")
    def kg_stats():
        return C().kgraph.stats()

    @app.get("/api/kg/search")
    def kg_search(q: str = "", type: str = ""):
        return C().kgraph.search(q, type)

    @app.get("/api/kg/node/{nid}")
    def kg_node(nid: int, depth: int = 1):
        return C().kgraph.neighbors(nid, depth)

    @app.get("/api/kg/path")
    def kg_path(a: int, b: int):
        return C().kgraph.path(a, b)

    @app.post("/api/kg/link")
    def kg_link(body: KGLinkIn):
        return guard(C().kgraph.link, (body.src_type, body.src_ref, None), body.rel, (body.dst_type, body.dst_ref, None))

    @app.post("/api/kg/rebuild")
    def kg_rebuild():
        return C().kgraph.rebuild()

    # Plugins
    @app.get("/api/plugins")
    def pl_list():
        return C().plugins.discover()

    @app.post("/api/plugins/{name}/request-enable")
    def pl_req(name: str):
        return guard(C().plugins.request_enable, name)

    @app.post("/api/plugins/{name}/enable")
    def pl_enable(name: str, body: RestoreIn):
        return guard(C().plugins.enable, name, body.approval_id)

    @app.post("/api/plugins/{name}/status")
    def pl_status(name: str, body: PluginStatusIn):
        return guard(C().plugins.set_status, name, body.status)

    @app.post("/api/plugins/{name}/config")
    def pl_config(name: str, body: dict):
        return guard(C().plugins.configure, name, body)

    @app.post("/api/plugins/{name}/run")
    def pl_run(name: str, body: PluginRunIn):
        return guard(C().plugins.run, name, body.input)

    @app.get("/api/plugins/{name}/logs")
    def pl_logs(name: str):
        return C().plugins.logs(name)

    # Sandbox
    @app.get("/api/sandbox")
    def sb_info():
        c = C()
        return {"isolation": c.sandbox.isolation_info(), "history": c.sandbox.history(30)}

    @app.post("/api/sandbox/python")
    def sb_python(body: SandboxIn):
        return guard(C().sandbox.run_python, body.code, allow_network=body.allow_network, stdin=body.stdin,
                     approval_id=body.approval_id)

    @app.post("/api/sandbox/command")
    def sb_cmd(body: TextIn):
        return guard(C().sandbox.run_command, body.text)

    # Planner
    @app.post("/api/plans")
    def plan_create(body: TextIn):
        return guard(C().planner.create, body.text)

    @app.get("/api/plans")
    def plans():
        return C().planner.list()

    @app.post("/api/plans/{pid}/run")
    def plan_run(pid: int):
        return guard(C().planner.run, pid)

    # Business Intelligence
    @app.post("/api/bi/import")
    def bi_import(body: ImportIn):
        return guard(C().bi.import_file, body.path, body.kind)

    @app.post("/api/bi/upload")
    async def bi_upload(file: UploadFile, kind: str):
        c = C()
        name = Path(file.filename or "import.csv").name
        if Path(name).suffix.lower() not in (".csv", ".xlsx"):
            raise HTTPException(400, "Faqat .csv yoki .xlsx")
        dest_dir = Path(c.settings.allowed_write_dirs[0]) / "imports"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / name
        n = 1
        while dest.exists():
            dest, n = dest_dir / f"{Path(name).stem}_{n}{Path(name).suffix}", n + 1
        data = await file.read()
        if len(data) > 20_000_000:
            raise HTTPException(400, "Fayl 20 MB dan katta")
        dest.write_bytes(data)
        return guard(c.bi.import_file, str(dest), kind)

    @app.get("/api/bi/report")
    def bi_report():
        return C().bi.report()

    @app.get("/api/bi/stock")
    def bi_stock():
        return C().bi.stock()

    # POS
    @app.get("/api/pos/status")
    def pos_status():
        return C().pos.status()

    @app.get("/api/pos/documents")
    def pos_docs():
        return C().pos.list()

    @app.post("/api/pos/documents")
    def pos_create(body: PosDraftIn):
        return guard(C().pos.create_draft, body.doc_type, body.party, body.items, body.note, body.account)

    @app.put("/api/pos/documents/{did}")
    def pos_update(did: int, body: PosUpdateIn):
        return guard(C().pos.update_draft, did, body.items, body.party, body.note)

    @app.post("/api/pos/documents/{did}/request-approval")
    def pos_req(did: int):
        return guard(C().pos.request_approval, did)

    @app.post("/api/pos/documents/{did}/submit")
    def pos_submit(did: int):
        return guard(C().pos.submit, did)

    @app.post("/api/pos/documents/{did}/check")
    def pos_check(did: int):
        return guard(C().pos.check_unknown, did)

    # Internet tadqiqoti
    @app.post("/api/research/search")
    def r_search(body: TextIn):
        return guard(C().research.search, body.text)

    @app.post("/api/research/answer")
    def r_answer(body: TextIn):
        return guard(C().research.answer, body.text)

    @app.post("/api/research/fetch")
    def r_fetch(body: UrlIn):
        return guard(C().research.fetch, body.url)

    # Brauzer
    @app.get("/api/browser/status")
    def br_status():
        return C().browser.status()

    @app.post("/api/browser/inspect")
    def br_inspect(body: UrlIn):
        r = guard(C().browser.inspect, body.url)
        r["text"] = r["text"][:8000]
        return r

    @app.post("/api/browser/site-map")
    def br_map(body: UrlIn):
        return guard(C().browser.site_map, body.url)

    # Studio
    @app.get("/api/studio/tools")
    def st_tools():
        return C().studio.tools()

    @app.post("/api/studio/image")
    def st_image(body: OpIn):
        return guard(C().agents._h_image, {"op": body.op, **body.params})

    @app.post("/api/studio/video")
    def st_video(body: OpIn):
        return guard(C().agents._h_video, {"op": body.op, **body.params})

    @app.get("/api/studio/exports")
    def st_exports():
        d = C().studio.exports
        return [{"name": f.name, "path": str(f), "size": f.stat().st_size} for f in sorted(d.iterdir(), reverse=True)][:200]

    @app.get("/api/studio/file")
    def st_file(path: str):
        p = guard(C().files._check_read, path)
        if not p.is_file():
            raise HTTPException(404, "Topilmadi")
        return FileResponse(p)

    # Instagram
    @app.get("/api/instagram/accounts")
    def ig_accounts():
        ig = C().instagram
        return [ig.account_status(a["name"]) for a in ig.accounts()]

    @app.get("/api/instagram/posts")
    def ig_posts():
        return C().instagram.calendar()

    @app.post("/api/instagram/posts")
    def ig_draft(body: IgDraftIn):
        return guard(C().instagram.draft, body.account, body.kind, body.caption, body.media_url, body.scheduled_at, body.hashtags)

    @app.put("/api/instagram/posts/{pid}")
    def ig_update(pid: int, body: TextIn):
        return guard(C().instagram.update_caption, pid, body.text)

    @app.get("/api/instagram/posts/{pid}/preview")
    def ig_preview(pid: int):
        return guard(C().instagram.preview, pid)

    @app.post("/api/instagram/posts/{pid}/request-publish")
    def ig_req(pid: int):
        return guard(C().instagram.request_publish, pid)

    @app.post("/api/instagram/posts/{pid}/publish")
    def ig_publish(pid: int):
        return guard(C().instagram.publish, pid)

    @app.post("/api/instagram/hashtags")
    def ig_tags(body: TextIn):
        return {"hashtags": suggest_hashtags(body.text)}

    @app.post("/api/instagram/replies")
    def ig_reply(body: IgReplyIn):
        return guard(C().instagram.draft_reply, body.account, body.comment_id, body.comment_text, body.reply)

    @app.post("/api/instagram/replies/{rid}/request")
    def ig_reply_req(rid: int):
        return guard(C().instagram.request_reply, rid)

    @app.post("/api/instagram/replies/{rid}/send")
    def ig_reply_send(rid: int):
        return guard(C().instagram.send_reply, rid)

    @app.get("/api/instagram/{account}/insights")
    def ig_insights(account: str):
        return guard(C().instagram.insights, account)

    @app.get("/api/instagram/{account}/media")
    def ig_media(account: str):
        return guard(C().instagram.media_performance, account)

    # Telegram
    @app.get("/api/telegram/status")
    def tg_status():
        return C().telegram.status()

    @app.post("/api/telegram/start")
    def tg_start():
        return guard(C().telegram.start)

    @app.post("/api/telegram/stop")
    def tg_stop():
        return C().telegram.stop()

    @app.post("/api/telegram/test")
    def tg_test():
        tg = C().telegram
        if not tg.configured():
            raise HTTPException(400, "Telegram sozlanmagan (token va telegram_allowed_ids)")
        return {"sent_to": tg.broadcast("✅ JARVIS: test bildirishnomasi")}

    # Ovoz
    @app.get("/api/voice/status")
    def v_status():
        return C().voice.status()

    @app.post("/api/voice/whisper/load")
    def v_load(body: TextIn):
        return guard(C().voice.load_whisper, body.text or "small")

    @app.post("/api/voice/recordings")
    async def v_save(request: Request):
        data = await request.body()
        if not data or len(data) > 25_000_000:
            raise HTTPException(400, "Bo'sh yoki juda katta yozuv")
        return {"saved": guard(C().voice.save_recording, data)}

    # Bildirishnomalar va telefon
    @app.get("/api/notifications")
    def notes(unread: bool = False):
        return C().notifier.list(unread)

    @app.post("/api/notifications/read")
    def notes_read():
        C().notifier.mark_read()
        return {"ok": True}

    @app.get("/api/telephony/status")
    def tel_status():
        return C().telephony.status()

    @app.post("/api/telephony/plan")
    def tel_plan(body: CallIn):
        return guard(C().telephony.plan_call, body.phone, body.message, body.reason, body.est_minutes)

    # Self-improvement
    @app.get("/api/improve/suggestions")
    def imp_sugg():
        return C().improver.suggestions()

    @app.get("/api/improve/proposals")
    def imp_list():
        return C().improver.list()

    @app.post("/api/improve/proposals")
    def imp_create(body: ProposalIn):
        return guard(C().improver.create, body.title, body.diff, body.description)

    @app.post("/api/improve/proposals/{pid}/test")
    def imp_test(pid: int):
        return guard(C().improver.test, pid)

    @app.post("/api/improve/proposals/{pid}/request-apply")
    def imp_req(pid: int):
        return guard(C().improver.request_apply, pid)

    @app.post("/api/improve/proposals/{pid}/apply")
    def imp_apply(pid: int):
        return guard(C().improver.apply, pid)

    @app.post("/api/improve/proposals/{pid}/rollback")
    def imp_rb(pid: int):
        return guard(C().improver.rollback, pid)

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
    app = create_app()
    app.state.core.backup.start_auto()        # jadval bo'yicha avtomatik zaxira (backup_interval_hours)
    uvicorn.run(app, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
