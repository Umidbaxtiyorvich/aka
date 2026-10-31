"""FastAPI: lokal API va dashboard. Standart holatda faqat 127.0.0.1 da ishlaydi."""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path


from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, system_info
from .ai_engine import MODEL_CATALOG, AIError
from .approval import ApprovalError
from .config import LOCKED_KEYS, PROJECT_ROOT
from .core import CAPABILITIES, JarvisCore
from .auth import AuthError
from .backup import BackupError
from .bi import BIError
from .dag import DagError
from .decisions import DecisionError
from .browser import BrowserError
from .files import FileAccessError
from .imagegen import ImageGenError
from .improve import ImproveError
from .instagram import InstagramError, suggest_hashtags
from .instagram_mcp import MCPError
from .integrations import IntegrationError
from .integrations.vault import VaultError
from .ai_hub import HubError
from .mission import MissionError
from .assets import AssetError
from .simlab import SimError
from .workspace import WorkspaceError
from .tools import ToolError
from .swarm import SwarmError
from .semantic import SemanticError
from .documents import DocError
from .computer_use import ComputerUseError
from .site_actions import SiteSkillError
from .integrations.base import ConnectorError
from .memory_import import MAX_UPLOAD as MI_MAX, ImportError_ as MIError
from .voice_pro import VoiceProError
from .kgraph import KGError
from .memory import MemoryError_
from .planner import PlannerError
from .plugins import PluginError
from .pos import POSError
from .pos_sync import POSSyncError
from .research import ResearchError
from .sandbox import SandboxError
from .studio import StudioError
from .telegram_bot import TelegramError
from .telephony import TelephonyError
from .voice import VoiceError

USER_ERRORS = (ApprovalError, MemoryError_, FileAccessError, ValueError, KeyError, BIError, POSError, ResearchError,
               StudioError, InstagramError, TelegramError, TelephonyError, VoiceError, BrowserError, PlannerError, ImproveError,
               DecisionError, SandboxError, BackupError, DagError, KGError, PluginError, ImageGenError, POSSyncError, MCPError, AIError, IntegrationError, VaultError, VoiceProError, HubError, MIError, MissionError, AssetError, SimError, WorkspaceError, ToolError, SwarmError, SemanticError, DocError, ComputerUseError, ConnectorError, SiteSkillError)
# Sozlamalar API orqali o'zgartirilishi mumkin bo'lgan (xavfsizlikka oid bo'lmagan) kalitlar
EDITABLE = {"ai_provider", "ollama_url", "ollama_model", "internet_enabled", "browser_allowed_domains", "telegram_notify",
            "pos_site", "pos_connector", "low_stock_threshold", "save_voice_recordings",
            "ai_providers", "ai_task_routes", "paid_ai_allowed", "ai_strategy", "ai_allowed_providers", "ai_confirm_paid", "ai_max_request_cost", "mission_auto_resume", "autonomy_level",
            "ai_custom_catalog", "voice_tts_engine", "voice_stt_engine", "voice_gender", "voice_rate",
            "voice_volume", "voice_stt_language", "voice_silence_ms", "voice_mic_sensitivity", "azure_speech_region", "currency", "daily_cost_limit", "monthly_cost_limit", "daily_request_limit",
            "cost_warn_percent", "medium_auto_actions", "sandbox_backend", "sandbox_timeout_sec", "sandbox_memory_mb",
            "sandbox_max_retries", "backup_interval_hours", "backup_keep", "backup_max_total_mb", "backup_include_workspace",
            "image_gen_url", "vision_model", "planner_use_ai", "session_hours", "pos_api", "pos_sync",
            "instagram_accounts", "telephony_provider", "telephony_from", "telephony_account_sid", "telephony_cost_per_min",
            "telegram_owner_phone", "telegram_events", "telegram_voice_alerts", "telegram_approvals", "telegram_approval_ttl_min",
            "telegram_autostart", "telegram_execute_after_approval", "instagram_mcp_url", "meta_app_id"}
PROVIDER_KINDS = {"ollama", "openai_compatible", "anthropic", "offline", "azure_openai"}

DASHBOARD = PROJECT_ROOT / "dashboard"
SESSION_COOKIE = "jarvis_session"


class ChatIn(BaseModel):
    text: str
    allow_paid: bool = False

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
    title: str | None = None
    kind: str | None = None


class IngestIn(BaseModel):
    text: str
    kind: str | None = None
    project: str | None = None
    title: str | None = None
    source: str = "user"
    allow_duplicate: bool = False


class SuggestDecideIn(BaseModel):
    accept: bool

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
    ai_task_routes: dict | None = None
    ai_strategy: str | None = None
    ai_allowed_providers: list[str] | None = None
    ai_confirm_paid: bool | None = None
    ai_max_request_cost: float | None = None
    mission_auto_resume: bool | None = None
    autonomy_level: int | None = None
    ai_custom_catalog: dict | None = None
    voice_tts_engine: str | None = None
    voice_stt_engine: str | None = None
    voice_gender: str | None = None
    voice_rate: int | None = None
    voice_volume: int | None = None
    voice_stt_language: str | None = None
    voice_silence_ms: int | None = None
    voice_mic_sensitivity: int | None = None
    azure_speech_region: str | None = None
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
    image_gen_url: str | None = None
    vision_model: str | None = None
    planner_use_ai: bool | None = None
    session_hours: float | None = None
    instagram_accounts: list[dict] | None = None
    telephony_provider: str | None = None
    telephony_from: str | None = None
    telephony_account_sid: str | None = None
    telephony_cost_per_min: float | None = None
    telegram_owner_phone: str | None = None
    telegram_events: list[str] | None = None
    telegram_voice_alerts: bool | None = None
    telegram_approvals: bool | None = None
    telegram_approval_ttl_min: int | None = None
    telegram_autostart: bool | None = None
    telegram_execute_after_approval: bool | None = None
    instagram_mcp_url: str | None = None
    meta_app_id: str | None = None
    pos_api: dict | None = None
    pos_sync: dict | None = None

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

class IgDmIn(BaseModel):
    account: str
    conversation_id: str
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

class PinIn(BaseModel):
    pin: str

class PinChangeIn(BaseModel):
    current: str
    new: str

class AppIn(BaseModel):
    name: str
    file: str | None = None
    reason: str = ""

class ConnIn(BaseModel):
    name: str
    system_type: str = ""
    adapter: str = ""
    preset: str = ""
    store: str = ""
    mode: str = "read_only"
    config: dict = {}
    secrets: dict = {}
    sync_interval_min: int = 0


class ConnUpdateIn(BaseModel):
    name: str | None = None
    store: str | None = None
    config: dict | None = None
    secrets: dict | None = None
    sync_interval_min: int | None = None
    enabled: bool | None = None


class MappingIn(BaseModel):
    source_entity: str
    entity: str | None = None
    fields: dict = {}


class WriteIn(BaseModel):
    entity: str
    operation: str
    payload: dict = {}
    summary: str = ""


class SiteSkillIn(BaseModel):
    conn_id: int
    capability: str
    url: str = ""
    title: str = ""
    prompt_selector: str = ""
    submit_selector: str = ""
    result_selector: str = ""
    skill_id: int | None = None


class DoIn(BaseModel):
    text: str = ""
    prompt: str = ""
    capability: str = ""
    skill_id: int | None = None
    agent: str = ""


class DetectIn(BaseModel):
    url: str = ""
    host: str = ""
    port: int | None = None


class QueryIn(BaseModel):
    sql: str
    params: list = []


class ProviderIn(BaseModel):
    catalog_id: str
    pid: str = ""
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    api_type: str = ""
    params: dict = {}
    price_in: float = 0.0
    price_out: float = 0.0
    tier: str = ""
    verify: bool = True


class ProviderUpdateIn(BaseModel):
    model: str | None = None
    base_url: str | None = None
    tier: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    price_in_per_1k: float | None = None
    price_out_per_1k: float | None = None
    params: dict | None = None


class CapsIn(BaseModel):
    model_id: str
    caps: list[str] = []


class ImportDecideIn(BaseModel):
    action: str
    ids: list[int] = []
    category: str = ""


class ImportEditIn(BaseModel):
    content: str | None = None
    category: str | None = None


class MissionIn(BaseModel):
    goal: str
    use_ai: bool | None = None
    max_minutes: int = 60
    max_cost: float = 0.0
    max_attempts: int = 2
    auto_start: bool = False
    due_at: str | None = None


class MissionAnswerIn(BaseModel):
    text: str = ""


class TwinEditIn(BaseModel):
    content: str


class SimSqlIn(BaseModel):
    target: str = "jarvis"
    statements: list[str]


class SimWriteIn(BaseModel):
    conn_id: int
    entity: str
    operation: str = "update"
    payload: dict = {}
    record_id: str = ""


class SimTextIn(BaseModel):
    text: str


class SkillIn(BaseModel):
    name: str
    description: str
    permissions: list[str] = []
    use_ai: bool = False


class ToolInvokeIn(BaseModel):
    args: dict = {}


class DelegateIn(BaseModel):
    from_agent: str
    to_agent: str
    tool: str
    args: dict = {}


class DocIn(BaseModel):
    path: str = ""
    query: str = ""
    ai: bool = False
    fmt: str = "md"
    b: str = ""
    replacements: dict = {}
    title: str = ""
    text: str = ""
    slides: list[dict] = []


class CUIn(BaseModel):
    actions: list[dict] = []
    reason: str = ""
    title: str = ""
    name: str = ""


class AskIn(BaseModel):
    question: str


class FeedbackIn(BaseModel):
    usage_id: int
    good: bool
    note: str = ""


class MCPCallIn(BaseModel):
    tool: str
    arguments: dict = {}


class SecretIn(BaseModel):
    name: str
    value: str = ""


class FeatureIn(BaseModel):
    description: str
    files: list[str] = []


class SuggestIn(BaseModel):
    error_id: int | None = None
    description: str = ""
    file: str = ""

class CallIn(BaseModel):
    phone: str
    message: str
    reason: str
    est_minutes: float = 1.0


def create_app(core: JarvisCore | None = None) -> FastAPI:
    app = FastAPI(title="JARVIS AI BRAIN", version=__version__)
    app.state.core = core or JarvisCore()
    C = lambda: app.state.core  # noqa: E731

    from fastapi.responses import JSONResponse
    from urllib.parse import urlparse

    @app.middleware("http")
    async def security(request: Request, call_next):
        """1) Host tekshiruvi — DNS rebinding'dan himoya. 2) Begona Origin'dan o'zgartiruvchi so'rovlar rad etiladi.
        3) PIN sessiyasi (auth_enabled)."""
        c = app.state.core
        allowed = set(c.settings.allowed_hosts)
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if host not in allowed:
            return JSONResponse({"detail": "Ruxsat etilmagan Host sarlavhasi"}, status_code=400)
        origin = request.headers.get("origin")
        if origin and request.method not in ("GET", "HEAD", "OPTIONS"):
            if (urlparse(origin).hostname or "").lower() not in allowed:
                return JSONResponse({"detail": "Begona saytdan so'rov rad etildi"}, status_code=403)
        path = request.url.path
        # Webhook — o'z tokeni bilan (X-JARVIS-Token) tekshiriladi va faqat sinxronlashni ishga tushiradi
        is_webhook = request.method == "POST" and re.fullmatch(r"/api/integrations/\d+/webhook", path)
        if c.settings.auth_enabled and path.startswith("/api/") and not path.startswith("/api/auth/") and not is_webhook:
            if not c.auth.check(request.cookies.get(SESSION_COOKIE)):
                return JSONResponse({"detail": "auth_required", "pin_set": c.auth.has_pin()}, status_code=401)
        return await call_next(request)

    @app.middleware("http")
    async def timing(request: Request, call_next):
        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            path = getattr(route, "path", None) or ("/static" if request.url.path.startswith("/static") else "other")
            app.state.core.diagnostics.metrics.add(request.method, path, status, (time.perf_counter() - t0) * 1000)

    def guard(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except USER_ERRORS as e:
            raise HTTPException(400, str(e).strip("'"))

    # Auth
    from fastapi.responses import JSONResponse as _J

    def _with_cookie(token: str) -> _J:
        r = _J({"ok": True})
        r.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", max_age=int(C().settings.session_hours * 3600), path="/")
        return r

    def _auth(fn, *a):
        try:
            return fn(*a)
        except AuthError as e:
            raise HTTPException(e.status, str(e))

    @app.get("/api/auth/status")
    def auth_status(request: Request):
        return C().auth.status(request.cookies.get(SESSION_COOKIE))

    @app.post("/api/auth/setup")
    def auth_setup(body: PinIn, request: Request):
        return _with_cookie(_auth(C().auth.setup, body.pin, request.client.host if request.client else ""))

    @app.post("/api/auth/login")
    def auth_login(body: PinIn, request: Request):
        return _with_cookie(_auth(C().auth.login, body.pin, request.client.host if request.client else ""))

    @app.post("/api/auth/change")
    def auth_change(body: PinChangeIn, request: Request):
        if C().settings.auth_enabled and not C().auth.check(request.cookies.get(SESSION_COOKIE)):
            raise HTTPException(401, "auth_required")
        return _with_cookie(_auth(C().auth.change, body.current, body.new, request.client.host if request.client else ""))

    @app.post("/api/auth/logout")
    def auth_logout(request: Request):
        C().auth.logout(request.cookies.get(SESSION_COOKIE))
        r = _J({"ok": True})
        r.delete_cookie(SESSION_COOKIE, path="/")
        return r

    # Dasturlar
    @app.get("/api/apps")
    def apps():
        return C().computer.apps()

    @app.post("/api/apps/propose")
    def app_propose(body: AppIn):
        return guard(C().computer.propose_app, body.name, body.file, body.reason)

    @app.post("/api/apps/launch/{aid}")
    def app_launch(aid: int):
        return guard(C().computer.launch_app, aid)

    @app.get("/api/status")
    def status():
        c = C()
        ok, note = c.ai.available()
        return {"version": __version__, "system": system_info.snapshot(),
                "ai": {"provider": c.ai.name, "model": getattr(c.ai, "model", None), "available": ok, "note": note},
                "agents": [a.public() for a in c.agents.agents.values()],
                "pending_approvals": len(c.approvals.list("pending")),
                "memory_count": c.db.one("SELECT COUNT(*) n FROM memories")["n"],
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
        s["recommended_setup"] = system_info.recommend_setup(s["ram_total_gb"], system_info.gpu_vram_gb())
        s["model_catalog"] = MODEL_CATALOG
        return s

    @app.post("/api/chat")
    def chat(body: ChatIn):
        if not body.text.strip():
            raise HTTPException(400, "Bo'sh xabar")
        return C().chat(body.text, allow_paid=body.allow_paid)

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
        return guard(C().memory.update, mid, body.content, title=body.title, kind=body.kind)

    # Memory Explorer + Memory Connection Engine
    @app.get("/api/memory/categories")
    def mem_categories():
        from .memory import CATEGORY_LABELS
        counts = {r["kind"]: r["n"] for r in C().db.query("SELECT kind, COUNT(*) n FROM memories GROUP BY kind")}
        return [{"kind": k, "label": v, "count": counts.get(k, 0)} for k, v in CATEGORY_LABELS.items()]

    @app.get("/api/memory/explore")
    def mem_explore(kind: str = "", q: str = "", status: str = "", limit: int = 200):
        c = C()
        rows = c.memory.search(q, limit=min(limit, 500)) if q else c.memory.list(kind or None, limit=min(limit, 1000))
        if kind and q:
            rows = [r for r in rows if r["kind"] == kind]
        if status:
            rows = [r for r in rows if r["status"] == status]
        from .memory import CATEGORY_LABELS, label as info_label
        return [r | {"category": CATEGORY_LABELS.get(r["kind"], r["kind"]), "reliability": info_label(r),
                     "name": r.get("title") or r["content"].split("\n")[0][:60]} for r in rows]

    @app.get("/api/memory/{mid}/related")
    def mem_related(mid: int):
        return guard(C().connector.related, mid)

    @app.post("/api/memory/analyze")
    def mem_analyze(body: IngestIn):
        return C().connector.analyze(body.text, body.project)

    @app.post("/api/memory/ingest")
    def mem_ingest(body: IngestIn):
        return guard(C().connector.ingest, body.text, kind=body.kind, project=body.project, source=body.source,
                     allow_duplicate=body.allow_duplicate, title=body.title)

    @app.get("/api/memory/suggestions")
    def mem_suggestions(status: str = "pending"):
        return C().connector.suggestions(status)

    @app.post("/api/memory/suggestions/{sid}")
    def mem_suggestion_decide(sid: int, body: SuggestDecideIn):
        return guard(C().connector.decide, sid, body.accept)

    @app.get("/api/memory/duplicates")
    def mem_duplicates():
        return C().connector.duplicates()

    # Universal Integration Engine (maxfiy qiymatlar hech qachon qaytmaydi — faqat qaysi maydonlar kiritilgani)
    @app.get("/api/integrations/catalog")
    def integ_catalog():
        return C().integrations.catalog()

    @app.get("/api/integrations")
    def integ_list(system_type: str = ""):
        return C().integrations.list(system_type)

    @app.post("/api/integrations")
    def integ_create(body: ConnIn):
        return guard(C().integrations.create, **body.model_dump())

    @app.post("/api/integrations/detect")
    def integ_detect(body: DetectIn):
        return C().integrations.detect(url=body.url, host=body.host, port=body.port)

    # Site Skills / Task Router — ulangan saytlardan topshiriq bajarish
    @app.get("/api/site-skills")
    def ss_list(conn_id: int | None = None):
        c = C()
        return {"skills": c.site_skills.list(conn_id), "catalog": c.site_skills.catalog(), "runs": c.site_skills.runs(30)}

    @app.post("/api/site-skills")
    def ss_save(body: SiteSkillIn):
        return guard(C().site_skills.save, body.conn_id, body.capability, body.url, body.title, body.prompt_selector,
                     body.submit_selector, body.result_selector, body.skill_id)

    @app.delete("/api/site-skills/{sid}")
    def ss_delete(sid: int):
        return guard(C().site_skills.delete, sid)

    @app.post("/api/integrations/{cid}/skills/detect")
    def ss_detect(cid: int):
        c = C()
        conn = guard(c.integrations.get, cid)
        pages = [{"url": e.get("source"), "title": e.get("name"), "prompts": [], "buttons": []} for e in conn.get("entities") or []]
        return guard(c.site_skills.detect, cid, pages)

    @app.post("/api/do/plan")
    def do_plan(body: DoIn):
        return guard(C().site_skills.plan, body.text, body.capability or None)

    @app.post("/api/do/run")
    def do_run(body: DoIn):
        c = C()
        if body.skill_id:
            return guard(c.site_skills.propose, body.skill_id, body.prompt or body.text)
        return guard(c.site_skills.run_agent, body.agent, body.capability, body.prompt or body.text)

    @app.post("/api/site-skills/execute/{aid}")
    def ss_execute(aid: int):
        return guard(C().site_skills.execute, aid)

    @app.post("/api/integrations/probe-login")
    def integ_probe_login(body: DetectIn):
        return guard(C().integrations.probe_login, body.url)

    @app.get("/api/integrations/health")
    def integ_health():
        return C().integrations.health()

    @app.get("/api/integrations/sync-history")
    def integ_sync_hist(cid: int | None = None):
        return C().integrations.sync_history(cid)

    @app.get("/api/integrations/proposals")
    def integ_props(cid: int | None = None):
        return C().integrations.proposals(cid)

    @app.post("/api/integrations/desktop-scan")
    def integ_desktop():
        from .integrations.mcp_db_files import DesktopConnector
        c = C()
        return DesktopConnector({"id": None, "config": {}}, lambda f: None, c).discover()

    @app.get("/api/integrations/{cid}")
    def integ_get(cid: int):
        return guard(C().integrations.get, cid)

    @app.post("/api/integrations/{cid}")
    def integ_update(cid: int, body: ConnUpdateIn):
        return guard(C().integrations.update, cid, **body.model_dump())

    @app.delete("/api/integrations/{cid}")
    def integ_delete(cid: int):
        return guard(C().integrations.delete, cid)

    @app.post("/api/integrations/{cid}/test")
    def integ_test(cid: int):
        return guard(C().integrations.test, cid)

    @app.post("/api/integrations/{cid}/discover")
    def integ_discover(cid: int):
        return guard(C().integrations.discover, cid)

    @app.post("/api/integrations/{cid}/mapping")
    def integ_mapping(cid: int, body: MappingIn):
        return guard(C().integrations.confirm_mapping, cid, body.source_entity, body.entity, body.fields)

    @app.post("/api/integrations/{cid}/sync")
    def integ_sync(cid: int, mode: str = "incremental"):
        return guard(C().integrations.sync, cid, mode)

    @app.post("/api/integrations/{cid}/mode")
    def integ_mode(cid: int, mode: str):
        return guard(C().integrations.set_mode, cid, mode)

    @app.post("/api/integrations/{cid}/disconnect")
    def integ_disconnect(cid: int):
        return guard(C().integrations.disconnect, cid)

    @app.post("/api/integrations/{cid}/login-window")
    def integ_login_window(cid: int):
        import threading
        c = C()
        conn = guard(c.integrations.get, cid)
        if conn["adapter"] != "website":
            raise HTTPException(400, "Faqat veb-sayt ulanishlari uchun")
        threading.Thread(target=lambda: c.integrations.connector(conn).interactive_login(), daemon=True).start()
        return {"status": "opened", "note": "Brauzer oynasida CAPTCHA/MFA'ni o'zingiz o'ting, keyin oynani yoping va 'Tekshirish' ni bosing."}

    @app.get("/api/integrations/{cid}/records")
    def integ_records(cid: int, entity: str = "", limit: int = 200, offset: int = 0):
        return C().integrations.records(cid, entity, limit, offset)

    @app.post("/api/integrations/{cid}/query")
    def integ_query(cid: int, body: QueryIn):
        c = C()
        conn = guard(c.integrations.get, cid)
        if conn["adapter"] != "database":
            raise HTTPException(400, "Faqat ma'lumotlar bazasi ulanishlari uchun")
        from .integrations.base import ConnectorError as _CE
        try:
            return c.integrations.connector(conn).query(body.sql, body.params)
        except _CE as e:
            raise HTTPException(400, str(e))

    @app.post("/api/integrations/{cid}/write")
    def integ_write(cid: int, body: WriteIn):
        return guard(C().integrations.request_write, cid, body.entity, body.operation, body.payload, body.summary)

    @app.post("/api/integrations/{cid}/webhook")
    async def integ_webhook(cid: int, request: Request):
        """Webhook Sync: tashqi tizim xabar beradi → JARVIS o'zi incremental sinxronlaydi (kelgan ma'lumot to'g'ridan-to'g'ri yozilmaydi)."""
        import hmac
        c = C()
        secret = c.integrations.vault.get(cid, "webhook_secret")
        if not secret or not hmac.compare_digest(request.headers.get("X-JARVIS-Token", ""), secret):
            raise HTTPException(403, "Webhook tokeni noto'g'ri")
        return guard(c.integrations.sync, cid, "incremental", "webhook")

    @app.get("/api/brain-core/status")
    def brain_core_status():
        return C().brain_core.status()

    @app.post("/api/analyst/ask")
    def analyst_ask(body: AskIn):
        return C().analyst.answer(body.question)

    # 3D Brain + jonli hodisalar (Server-Sent Events)
    @app.get("/api/brain/state")
    def brain_state():
        return C().brain.state()

    @app.get("/api/brain/region/{rid}")
    def brain_region(rid: str):
        return guard(C().brain.region_state, rid)

    @app.get("/api/events/recent")
    def events_recent(since: int = 0):
        c = C()
        return {"events": c.events.since(since), **c.events.snapshot()}

    @app.get("/api/events/stream")
    async def events_stream(request: Request, since: int = -1, once: bool = False):
        import asyncio
        import json as _json
        from fastapi.responses import StreamingResponse
        bus = C().events
        start = bus.seq if since < 0 else since

        async def gen():
            seq = start
            yield f"event: hello\ndata: {_json.dumps(bus.snapshot())}\n\n"
            idle = 0.0
            while True:
                evs = bus.since(seq)
                for e in evs:
                    seq = e["seq"]
                    yield f"id: {e['seq']}\nevent: jarvis\ndata: {_json.dumps(e, ensure_ascii=False, default=str)}\n\n"
                if once:
                    return
                if evs:
                    idle = 0.0
                if await request.is_disconnected():
                    return
                await asyncio.sleep(0.4)
                idle += 0.4
                if idle >= 15:
                    idle = 0.0
                    yield f"event: ping\ndata: {_json.dumps(bus.snapshot())}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/kg/graph")
    def kg_graph(categories: str = "", since: str = "", until: str = "", source: str = "", q: str = "",
                 limit: int = 3000, offset: int = 0):
        cats = [x for x in categories.split(",") if x]
        return C().kgraph.graph(categories=cats, since=since, until=until, source=source, q=q, limit=limit, offset=offset)

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
            if prov["kind"] in ("openai_compatible", "anthropic", "azure_openai"):
                from .ai_hub import LOCAL_HOST
                url = str(prov.get("base_url", ""))
                is_local = prov["kind"] != "anthropic" and bool(LOCAL_HOST.match(url))
                prov["paid"], prov["local"] = not is_local, is_local
                if prov["kind"] != "anthropic" and not (url.startswith("https://") or is_local):
                    raise HTTPException(400, "Tashqi provayder uchun https:// base_url kerak (mahalliy server: http://localhost)")
        if "medium_auto_actions" in data:
            from .policy import ACTIONS
            bad = [a for a in data["medium_auto_actions"] if ACTIONS.get(a, ("high",))[0] != "medium"]
            if bad:
                raise HTTPException(400, f"Faqat o'rta xavfli amallar avtomatik qilinadi. Mumkin emas: {bad}")
        if "pos_sync" in data:
            ps = data["pos_sync"]
            for src in ps.get("sources", []):
                if not str(src.get("url", "")).startswith("https://"):
                    raise HTTPException(400, "Har bir hisobot manbasi https:// manzil bo'lishi kerak")
                if src.get("kind", "auto") not in ("auto", "products", "movements", "payments"):
                    raise HTTPException(400, "kind: auto, products, movements yoki payments")
            if float(ps.get("interval_hours", 6)) < 0.5:
                raise HTTPException(400, "Oraliq kamida 0.5 soat")
        if "instagram_accounts" in data:
            import re as _re
            for acc in data["instagram_accounts"]:
                if not _re.fullmatch(r"[a-z0-9_]{1,40}", str(acc.get("name", ""))) or not _re.fullmatch(r"\d{5,25}", str(acc.get("ig_user_id", ""))):
                    raise HTTPException(400, "Instagram akkaunti: name (kichik lotin harflar, raqam, _) va ig_user_id (faqat raqam) kerak")
            data["instagram_accounts"] = [{"name": a["name"], "ig_user_id": str(a["ig_user_id"])} for a in data["instagram_accounts"]]
        if "telegram_events" in data:
            from .telegram_bot import EVENTS
            data["telegram_events"] = [e for e in data["telegram_events"] if e in EVENTS]
        if "telegram_approval_ttl_min" in data and not 1 <= int(data["telegram_approval_ttl_min"]) <= 1440:
            raise HTTPException(400, "Tasdiq muddati 1–1440 daqiqa")
        if data.get("instagram_mcp_url"):
            from .instagram_mcp import check_url
            try:
                check_url(data["instagram_mcp_url"])
            except MCPError as e:
                raise HTTPException(400, str(e))
        if "meta_app_id" in data and data["meta_app_id"] and not str(data["meta_app_id"]).isdigit():
            raise HTTPException(400, "Meta App ID faqat raqamlardan iborat")
        if "telegram_owner_phone" in data and data["telegram_owner_phone"] and len(re.sub(r"\D", "", data["telegram_owner_phone"])) < 9:
            raise HTTPException(400, "Telefon raqami to'liq emas")
        vchk = {"voice_tts_engine": ("auto", "azure", "espeak", "browser"), "voice_stt_engine": ("auto", "azure", "whisper", "browser"),
                "voice_gender": ("female", "male"), "voice_stt_language": ("uz", "auto", "ru-RU", "en-US")}
        for k, ok in vchk.items():
            if k in data and data[k] not in ok:
                raise HTTPException(400, f"{k}: {', '.join(ok)}")
        for k, lo, hi in (("voice_rate", -50, 50), ("voice_volume", 0, 100), ("voice_silence_ms", 300, 3000), ("voice_mic_sensitivity", 0, 100)):
            if k in data and not lo <= int(data[k]) <= hi:
                raise HTTPException(400, f"{k}: {lo}..{hi}")
        if data.get("azure_speech_region") and not re.fullmatch(r"[a-z0-9]{3,30}", data["azure_speech_region"]):
            raise HTTPException(400, "Azure mintaqasi, masalan: westeurope")
        if data.get("telephony_provider") not in (None, "", "twilio"):
            raise HTTPException(400, "telephony_provider: bo'sh yoki twilio")
        if "ai_strategy" in data:
            from .router import STRATEGIES
            if data["ai_strategy"] not in STRATEGIES:
                raise HTTPException(400, f"ai_strategy: {', '.join(STRATEGIES)}")
        if "autonomy_level" in data and not 0 <= int(data["autonomy_level"]) <= 4:
            raise HTTPException(400, "autonomy_level: 0..4")
        if "ai_max_request_cost" in data and float(data["ai_max_request_cost"]) < 0:
            raise HTTPException(400, "ai_max_request_cost manfiy bo'lmaydi")
        for k, v in (data.get("ai_custom_catalog") or {}).items():
            if not re.fullmatch(r"[a-z0-9_-]{2,40}", k) or not isinstance(v, dict) or v.get("kind") not in ("openai_compatible", "anthropic", "ollama", "azure_openai") \
                    or not str(v.get("base_url", "")).startswith(("https://", "http://localhost", "http://127.0.0.1")):
                raise HTTPException(400, "ai_custom_catalog: {id: {title, kind, base_url (https:// yoki localhost), model}}")
        if "sandbox_backend" in data and data["sandbox_backend"] not in ("process", "docker"):
            raise HTTPException(400, "sandbox_backend: process yoki docker")
        if "ai_provider" in data and data["ai_provider"] not in ("offline", "ollama"):
            raise HTTPException(400, "ai_provider: offline yoki ollama")
        for k, v in data.items():
            setattr(c.settings, k, v)
        c.settings.save()
        c.reload_ai()
        if "pos_connector" in data or "pos_api" in data:
            from .pos import make_connector
            c.pos.connector = make_connector(c.settings)
        c.audit.log("user", f"Sozlamalar o'zgartirildi: {sorted(data)}", target="settings", risk="C",
                    approval_status="user_action")
        return c.settings.public()

    # AI Router / Resource Guard / Policy
    @app.get("/api/ai/router")
    def ai_router():
        c = C()
        return {"providers": c.ai.status(), "last_route": c.ai.last_route, "metrics": c.guard.providers()}

    # AI Provider Hub (kalit qiymatlari hech qachon qaytmaydi)
    @app.get("/api/ai/hub/catalog")
    def hub_catalog():
        return C().ai_hub.catalog()

    @app.get("/api/ai/hub/overview")
    def hub_overview():
        return C().ai_hub.overview()

    @app.get("/api/ai/hub/providers")
    def hub_list():
        return C().ai_hub.list()

    @app.post("/api/ai/hub/providers")
    def hub_add(body: ProviderIn):
        c = C()
        d = body.model_dump()
        do_verify = d.pop("verify")
        p = guard(c.ai_hub.add, **d)
        return p | {"verification": guard(c.ai_hub.verify, p["id"]) if do_verify else None}

    @app.post("/api/ai/hub/providers/{pid}")
    def hub_update(pid: str, body: ProviderUpdateIn):
        c = C()
        d = body.model_dump()
        p = guard(c.ai_hub.update, pid, **d)
        return p | {"verification": guard(c.ai_hub.verify, pid) if d.get("api_key") else None}   # kalit kiritilsa — avtomatik tekshiruv

    @app.delete("/api/ai/hub/providers/{pid}")
    def hub_remove(pid: str):
        return guard(C().ai_hub.remove, pid)

    @app.post("/api/ai/hub/providers/{pid}/verify")
    def hub_verify(pid: str, test_model: bool = True):
        return guard(C().ai_hub.verify, pid, test_model)

    @app.post("/api/ai/hub/providers/{pid}/default")
    def hub_default(pid: str, task: str = "chat"):
        return guard(C().ai_hub.set_default, pid, task)

    @app.post("/api/ai/hub/providers/{pid}/models")
    def hub_add_model(pid: str, body: CapsIn):
        return guard(C().ai_hub.add_model, pid, body.model_id)

    @app.post("/api/ai/hub/providers/{pid}/caps")
    def hub_caps(pid: str, body: CapsIn):
        return guard(C().ai_hub.set_caps, pid, body.model_id, body.caps)

    @app.get("/api/ai/hub/models")
    def hub_models(provider: str | None = None):
        return C().ai_hub.models(provider)

    @app.get("/api/ai/hub/capabilities")
    def hub_capmap():
        return C().ai_hub.capability_map()

    @app.get("/api/ai/live")
    def ai_live():
        from .router import STRATEGIES
        c = C()
        cur = c.ai.current
        return {"current": cur and (cur | {"elapsed_ms": int((time.time() - cur["started"]) * 1000)}), "last": c.ai.last_route,
                "strategy": c.settings.ai_strategy, "strategies": STRATEGIES}

    @app.get("/api/ai/log")
    def ai_log(limit: int = 100):
        return C().db.query("SELECT id, ts, provider, model, purpose, tokens_in, tokens_out, tokens_measured, cost, duration_ms, ok, error, fallback_from "
                            "FROM ai_usage ORDER BY id DESC LIMIT ?", (min(limit, 500),))

    # Memory Import Center (ChatGPT eksporti) — tahlil mahalliy, import faqat tasdiq bilan
    @app.post("/api/memory-import/upload")
    async def mi_upload(file: UploadFile):
        data = await file.read(MI_MAX + 1)
        if len(data) > MI_MAX:
            raise HTTPException(400, "ZIP 512 MB dan katta")
        return guard(C().memory_import.start, file.filename or "export.zip", data)

    @app.get("/api/memory-import")
    def mi_list():
        return {"imports": C().memory_import.list(), "categories": C().memory_import.categories()}

    @app.get("/api/memory-import/{iid}")
    def mi_get(iid: int):
        return guard(C().memory_import.get, iid)

    @app.get("/api/memory-import/{iid}/items")
    def mi_items(iid: int, category: str = "", status: str = "", q: str = "", limit: int = 200, offset: int = 0):
        return C().memory_import.items(iid, category, status, q, limit, offset)

    @app.post("/api/memory-import/{iid}/decide")
    def mi_decide(iid: int, body: ImportDecideIn):
        return guard(C().memory_import.decide, iid, body.action, body.ids, body.category)

    @app.post("/api/memory-import/items/{item_id}")
    def mi_edit(item_id: int, body: ImportEditIn):
        return guard(C().memory_import.edit, item_id, body.content, body.category)

    @app.delete("/api/memory-import/{iid}")
    def mi_delete(iid: int, purge: bool = False):
        return guard(C().memory_import.delete, iid, purge)

    # Mission Engine (markaziy avtonom miya) va Permission Manager
    @app.post("/api/missions")
    def mission_create(body: MissionIn):
        return guard(C().missions.create, body.goal, use_ai=body.use_ai, max_minutes=body.max_minutes, max_cost=body.max_cost,
                     max_attempts=body.max_attempts, auto_start=body.auto_start, due_at=body.due_at)

    @app.get("/api/missions")
    def mission_list():
        return C().missions.list()

    @app.get("/api/missions/lessons")
    def mission_lessons(status: str = "pending"):
        return C().missions.lessons(status)

    @app.post("/api/missions/lessons/{lid}")
    def mission_lesson_decide(lid: int, accept: bool):
        return guard(C().missions.decide_lesson, lid, accept)

    @app.get("/api/missions/{mid}")
    def mission_get(mid: int):
        return guard(C().missions.get, mid)

    @app.post("/api/missions/{mid}/{action}")
    def mission_action(mid: int, action: str, key: str = "", body: MissionAnswerIn | None = None):
        m = C().missions
        acts = {"start": lambda: m.start(mid), "pause": lambda: m.pause(mid), "cancel": lambda: m.cancel(mid),
                "retry": lambda: m.retry_step(mid, key), "answer": lambda: m.answer(mid, body.text if body else "")}
        if action not in acts:
            raise HTTPException(404, "Noma'lum amal")
        return guard(acts[action])

    # JARVIS 3.0: Digital Twin, Proactive, Guardian, Assets, Simulation Lab, Office, Researcher, Business, Creative, Skills, Devices
    @app.get("/api/twin")
    def twin_get():
        c = C()
        return {"profile": c.twin.profile(), "suggestions": c.twin.suggestions()}

    @app.post("/api/twin/{mid}")
    def twin_edit(mid: int, body: TwinEditIn):
        return guard(C().twin.edit, mid, body.content)

    @app.delete("/api/twin/{mid}")
    def twin_delete(mid: int):
        return guard(C().twin.delete, mid)

    @app.get("/api/proactive")
    def proactive_get():
        c = C()
        return {"items": c.proactive.scan(), "reports": c.proactive.reports(10)}

    @app.post("/api/proactive/report")
    def proactive_report(kind: str = "daily"):
        if kind not in ("daily", "weekly"):
            raise HTTPException(400, "kind: daily yoki weekly")
        return C().proactive.report(kind)

    @app.get("/api/guardian")
    def guardian_get():
        return C().guardian.status()

    @app.post("/api/guardian/{action}")
    def guardian_run(action: str):
        try:
            return C().guardian.run(action)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/assets")
    def assets_stats():
        return C().assets.stats()

    @app.post("/api/assets/index")
    def assets_index(background: bool = True):
        return guard(C().assets.index, background)

    @app.get("/api/assets/search")
    def assets_search(q: str = "", category: str = ""):
        return C().assets.search(q, category)

    @app.get("/api/assets/duplicates")
    def assets_dups():
        return C().assets.duplicates()

    @app.post("/api/assets/backup")
    def assets_backup(body: SimTextIn):
        return guard(C().assets.backup, body.text)

    @app.post("/api/simlab/sql")
    def sim_sql(body: SimSqlIn):
        return guard(C().simlab.sql, body.target, body.statements)

    @app.post("/api/simlab/write")
    def sim_write(body: SimWriteIn):
        return guard(C().simlab.write_preview, body.conn_id, body.entity, body.operation, body.payload, body.record_id)

    @app.post("/api/simlab/mission")
    def sim_mission(body: SimTextIn):
        return guard(C().simlab.mission, body.text)

    @app.post("/api/simlab/code")
    def sim_code(body: SimTextIn):
        return guard(C().simlab.code, body.text)

    @app.get("/api/simlab/history")
    def sim_history():
        return C().simlab.history()

    @app.get("/api/office/rooms")
    def office_rooms():
        c = C()
        return {"rooms": c.office.rooms(), "collaborations": c.office.collaborations()}

    @app.get("/api/office/rooms/{key}")
    def office_room(key: str):
        return guard(C().office.room, key)

    @app.post("/api/researcher/investigate")
    def researcher_go(body: SimTextIn):
        return guard(C().researcher.investigate, body.text)

    @app.get("/api/researcher/findings")
    def researcher_findings(status: str = "pending"):
        return C().researcher.findings(status)

    @app.post("/api/researcher/findings/{fid}")
    def researcher_decide(fid: int, accept: bool):
        return guard(C().researcher.decide, fid, accept)

    @app.get("/api/business/overview")
    def business_overview():
        return C().business.overview()

    @app.get("/api/business/forecast")
    def business_forecast(days: int = 7):
        c = C()
        return {"daily": c.business.daily_sales(), "forecast": c.business.forecast(max(1, min(days, 30))), "anomalies": c.business.anomalies()}

    @app.get("/api/creative/capabilities")
    def creative_caps():
        return C().creative.capabilities()

    @app.post("/api/skills")
    def skill_create(body: SkillIn):
        return guard(C().plugins.scaffold, body.name, body.description, body.permissions, body.use_ai)

    @app.post("/api/skills/{name}/test")
    def skill_test(name: str):
        return guard(C().plugins.test, name)

    @app.get("/api/skills/{name}/versions")
    def skill_versions(name: str):
        return guard(C().plugins.versions, name)

    @app.post("/api/skills/{name}/rollback/{vid}")
    def skill_rollback(name: str, vid: int):
        return guard(C().plugins.rollback, name, vid)

    @app.get("/api/devices")
    def devices(request: Request):
        c = C()
        return {"sessions": c.auth.sessions(request.cookies.get(SESSION_COOKIE)), "auth_enabled": c.settings.auth_enabled,
                "hosts": c.settings.allowed_hosts, "note": "Telefon/boshqa qurilma: bir xil Wi-Fi tarmog'ida http://<kompyuter IP>:8765 (PIN bilan). "
                "HTTPS hali yo'q — faqat ishonchli tarmoqda. Xotira, missiya va bildirishnomalar bitta bazada — barcha qurilmalarda bir xil."}

    @app.post("/api/devices/{sid}/revoke")
    def device_revoke(sid: str):
        if not C().auth.revoke(sid):
            raise HTTPException(404, "Sessiya topilmadi")
        return {"ok": True}

    # Tool Registry va Command Center
    @app.get("/api/tools")
    def tools_catalog(agent: str | None = None):
        return C().tools.catalog(agent)

    @app.get("/api/tools/calls")
    def tools_calls(tool: str | None = None, limit: int = 100):
        return C().tools.calls(min(limit, 500), tool)

    @app.post("/api/tools/{tool_id}/invoke")
    def tools_invoke(tool_id: str, body: ToolInvokeIn):
        return guard(C().tools.invoke, tool_id, body.args, "user")

    @app.get("/api/search")
    def global_search(q: str = ""):
        return C().command.search(q)

    @app.post("/api/command")
    def command(body: SimTextIn):
        try:
            return C().command.run(body.text)
        except ValueError as e:
            raise HTTPException(400, str(e))

    # Agent Swarm
    @app.get("/api/swarm")
    def swarm_info(limit: int = 100):
        c = C()
        return {"history": c.swarm.history(min(limit, 500)), "routes": c.swarm.routes()}

    @app.post("/api/swarm/delegate")
    def swarm_delegate(body: DelegateIn):
        return guard(C().swarm.delegate, body.from_agent, body.to_agent, body.tool, body.args)

    # Semantik xotira (model faqat aniq tasdiq bilan yuklanadi)
    @app.get("/api/semantic")
    def semantic_status():
        return C().semantic.status()

    @app.post("/api/semantic/install")
    def semantic_install(confirm: bool = False, model: str = "nomic-embed-text"):
        if not re.fullmatch(r"[\w.:/-]{2,80}", model):
            raise HTTPException(400, "Model nomi noto'g'ri")
        return guard(C().semantic.install, confirm, model)

    @app.post("/api/semantic/enable")
    def semantic_enable(model: str):
        if not re.fullmatch(r"[\w.:/-]{2,80}", model):
            raise HTTPException(400, "Model nomi noto'g'ri")
        return C().semantic.enable(model)

    @app.post("/api/semantic/index")
    def semantic_index():
        return guard(C().semantic.index)

    @app.get("/api/semantic/search")
    def semantic_search(q: str):
        return C().semantic.hybrid(q, 10)

    # File Intelligence
    @app.get("/api/docs/formats")
    def docs_formats():
        return C().documents.formats()

    @app.post("/api/docs/{op}")
    def docs_op(op: str, body: DocIn):
        d = C().documents
        ops = {"extract": lambda: d.extract(body.path), "find": lambda: d.find(body.path, body.query), "summary": lambda: d.summary(body.path, body.ai),
               "compare": lambda: d.compare(body.path, body.b), "export": lambda: d.export_text(body.path, body.fmt),
               "docx-replace": lambda: d.docx_replace(body.path, body.replacements), "create-docx": lambda: d.create_docx(body.title, body.text),
               "create-pptx": lambda: d.create_pptx(body.title, body.slides)}
        if op not in ops:
            raise HTTPException(404, "Noma'lum amal")
        return guard(ops[op])

    @app.post("/api/docs-upload")
    async def docs_upload(file: UploadFile):
        c = C()
        name = Path(file.filename or "fayl").name[:120]
        from .documents import SUPPORTED
        if Path(name).suffix.lower() not in SUPPORTED:
            raise HTTPException(400, f"Bu format qo'llab-quvvatlanmaydi: {Path(name).suffix or '?'}")
        data = await file.read(25 * 2**20 + 1)
        if len(data) > 25 * 2**20:
            raise HTTPException(400, "Fayl 25 MB dan katta")
        dest_dir = Path(c.settings.allowed_write_dirs[0]) / "uploads"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest, n = dest_dir / name, 1
        while dest.exists():
            dest, n = dest_dir / f"{Path(name).stem}_{n}{Path(name).suffix}", n + 1
        dest.write_bytes(data)
        return guard(c.documents.extract, str(dest))

    # Computer Use (har sichqoncha/klaviatura ketma-ketligi — tasdiq bilan)
    @app.get("/api/computer-use")
    def cu_status():
        c = C()
        return c.computer_use.status() | {"macros": c.computer_use.macros(), "log": c.computer_use.log(30)}

    @app.get("/api/computer-use/windows")
    def cu_windows():
        return guard(C().computer_use.windows)

    @app.post("/api/computer-use/screenshot")
    def cu_screenshot(analyze: bool = False):
        return guard(C().computer_use.screenshot, analyze)

    @app.post("/api/computer-use/ui-tree")
    def cu_tree(body: CUIn):
        return guard(C().computer_use.ui_tree, body.title)

    @app.post("/api/computer-use/propose")
    def cu_propose(body: CUIn):
        return guard(C().computer_use.propose, body.actions, body.reason)

    @app.post("/api/computer-use/execute/{approval_id}")
    def cu_execute(approval_id: int):
        return guard(C().computer_use.execute, approval_id)

    @app.post("/api/computer-use/macros")
    def cu_save_macro(body: CUIn):
        return guard(C().computer_use.save_macro, body.name, body.actions)

    @app.post("/api/computer-use/macros/{name}/replay")
    def cu_replay(name: str):
        return guard(C().computer_use.replay, name)

    # Yangilash oynasini ochish (faqat shu kompyuterdan, faqat Windows): yorliq bloklangan holatlar uchun zaxira yo'l
    @app.post("/api/system/update")
    def system_update(request: Request):
        import subprocess
        from .config import PROJECT_ROOT
        if (request.client.host if request.client else "") not in ("127.0.0.1", "::1", "localhost", "testclient"):
            raise HTTPException(403, "Yangilashni faqat shu kompyuterning o'zidan boshlash mumkin")
        if sys.platform != "win32":
            raise HTTPException(400, "Yangilash oynasi faqat Windows'da ochiladi (bu muhit: " + sys.platform + ")")
        script = PROJECT_ROOT / "scripts" / "update.ps1"
        if not script.exists():
            raise HTTPException(400, "scripts\\update.ps1 topilmadi")
        ps = Path(__import__("os").environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        subprocess.Popen([str(ps), "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", str(script)], cwd=str(PROJECT_ROOT),
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        C().audit.log("user", "Yangilash oynasi ochildi (dashboard)", target="update", risk="C", approval_status="user_action")
        return {"started": True, "note": "Yangilash oynasi ochildi. JARVIS bir necha daqiqaga to'xtaydi va yangi versiya bilan qayta ochiladi."}

    @app.get("/api/permissions/agents")
    def perm_agents():
        return C().permissions.profiles()

    @app.get("/api/ai/presets")
    def ai_presets():
        from .router import PROVIDER_PRESETS, TASK_TYPES
        return {"presets": PROVIDER_PRESETS, "task_types": TASK_TYPES, "routes": C().settings.ai_task_routes}

    @app.get("/api/ai/quality")
    def ai_quality():
        return C().ai.quality()

    @app.post("/api/ai/feedback")
    def ai_feedback(body: FeedbackIn):
        return guard(C().ai.feedback, body.usage_id, body.good, body.note)

    @app.post("/api/ai/evaluate/{pid}")
    def ai_evaluate(pid: str):
        return guard(C().ai.evaluate, pid)

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
    # Self-healing
    @app.post("/api/selfheal/run")
    def selfheal_run(tests: bool = False, propose: bool = False):
        return C().selfheal.run(run_tests=tests, propose=propose)

    @app.get("/api/selfheal/history")
    def selfheal_history():
        return C().selfheal.history()

    @app.get("/api/kg")
    def kg_stats():
        return C().kgraph.stats()

    @app.get("/api/kg/search")
    def kg_search(q: str = "", type: str = ""):
        return C().kgraph.search(q, type)

    @app.get("/api/kg/node/{nid}")
    def kg_node(nid: int, depth: int = 1):
        return C().kgraph.neighbors(nid, depth)

    @app.get("/api/kg/find")
    def kg_find(type: str, ref: str):
        return guard(C().kgraph.find, type, ref)

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

    # Release gate
    @app.get("/api/release/last")
    def release_last():
        import json as _json
        from .config import jarvis_home
        p = jarvis_home() / "release" / "last.json"
        if not p.exists():
            return {"verdict": None, "note": "Release gate hali ishga tushirilmagan (python scripts/release_gate.py)"}
        return _json.loads(p.read_text(encoding="utf-8"))

    @app.post("/api/release/run")
    def release_run():
        return guard(C().agents.submit, "qa", "Release gate", {"release_gate": True})

    # Observability
    @app.get("/api/diagnostics")
    def diag(external: bool = True):
        return C().diagnostics.run(external)

    @app.get("/api/diagnostics/export")
    def diag_export(external: bool = True):
        from fastapi.responses import Response
        name = f"jarvis_diagnostika_{time.strftime('%Y%m%d_%H%M%S')}.json"
        return Response(C().diagnostics.export(external), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

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

    @app.post("/api/plans/rules")
    def plan_create_rules(body: TextIn):
        return guard(C().planner.create, body.text, False)

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

    @app.get("/api/bi/export.xlsx")
    def bi_export():
        from fastapi.responses import Response
        data = guard(C().bi.export_xlsx)
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="jarvis_bi_{time.strftime("%Y%m%d")}.xlsx"'})

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

    @app.get("/api/browser/session")
    def br_sess():
        return C().session_browser.status()

    @app.post("/api/browser/session/login")
    def br_login(body: UrlIn):
        return guard(C().session_browser.open_login, body.url)

    @app.post("/api/browser/session/tables")
    def br_tables(body: UrlIn):
        return guard(C().session_browser.extract_tables, body.url)

    @app.post("/api/browser/session/forget")
    def br_forget():
        return guard(C().session_browser.forget)

    @app.get("/api/pos/sync")
    def pos_sync_status():
        c = C()
        return c.pos_sync.status() | {"history": c.pos_sync.history()}

    @app.post("/api/pos/sync/run")
    def pos_sync_run():
        return guard(C().pos_sync.run)

    @app.post("/api/pos/preset/yespos")
    def pos_yespos():
        """YesPOS uchun tayyor sozlama: sayt manzili va brauzer ruxsati (faqat o'qish)."""
        c = C()
        c.settings.pos_site = "https://app.yespos.uz"
        if not (c.settings.pos_sync or {}).get("sources"):
            c.settings.pos_sync = {"enabled": False, "interval_hours": 6,
                                   "sources": [{"name": "hisobotlar", "url": "https://app.yespos.uz/reports", "kind": "auto"}]}
        if "app.yespos.uz" not in c.settings.browser_allowed_domains:
            c.settings.browser_allowed_domains = list(c.settings.browser_allowed_domains) + ["app.yespos.uz"]
        c.settings.save()
        c.audit.log("user", "YesPOS sozlamasi qo'llandi", target="settings", risk="C", approval_status="user_action")
        return {"pos_site": c.settings.pos_site, "browser_allowed_domains": c.settings.browser_allowed_domains,
                "reports_url": "https://app.yespos.uz/reports"}

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

    @app.get("/api/studio/imagegen")
    def st_imagegen():
        return C().imagegen.status()

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

    @app.post("/api/instagram/posts/{pid}/check")
    def ig_check(pid: int):
        return guard(C().instagram.check_unknown, pid)

    @app.post("/api/instagram/scheduled/run")
    def ig_sched():
        return C().instagram.due_scheduled()

    @app.get("/api/instagram/{account}/conversations")
    def ig_convs(account: str):
        return guard(C().instagram.conversations, account)

    @app.get("/api/instagram/{account}/conversations/{cid}")
    def ig_msgs(account: str, cid: str):
        return guard(C().instagram.messages, account, cid)

    @app.get("/api/instagram/dm")
    def ig_dms():
        return C().instagram.dm_drafts()

    @app.post("/api/instagram/dm")
    def ig_dm_draft(body: IgDmIn):
        return guard(C().instagram.draft_dm, body.account, body.conversation_id, body.reply)

    @app.post("/api/instagram/dm/{did}/request")
    def ig_dm_req(did: int):
        return guard(C().instagram.request_dm, did)

    @app.post("/api/instagram/dm/{did}/send")
    def ig_dm_send(did: int):
        return guard(C().instagram.send_dm, did)

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

    @app.get("/api/telegram/history")
    def tg_history(limit: int = 100):
        return C().telegram.history(min(limit, 500))

    @app.post("/api/telegram/start")
    def tg_start():
        return guard(C().telegram.start)

    @app.post("/api/telegram/stop")
    def tg_stop():
        return C().telegram.stop()

    @app.post("/api/telegram/pair")
    def tg_pair():
        return guard(C().telegram.pairing_start)

    @app.post("/api/telegram/revoke")
    def tg_revoke():
        return C().telegram.revoke()

    @app.post("/api/telegram/test")
    def tg_test():
        tg = C().telegram
        if not tg.configured():
            raise HTTPException(400, "Telegram egasi ulanmagan (token → 'Akkauntni ulash')")
        try:
            tg.send_owner("✅ JARVIS: test xabari. Ulanish ishlayapti.")
        except TelegramError as e:
            raise HTTPException(400, str(e))
        return {"sent_to": 1}

    @app.post("/api/telegram/test-voice")
    def tg_test_voice():
        return {"result": str(guard(C().telegram.send_voice, "JARVIS ovozli xabar sinovi. Ulanish ishlayapti."))[:200]}

    @app.post("/api/automation/resume")
    def automation_resume():
        C().resume_automation()
        return {"paused": False}

    # Instagram MCP Connector
    @app.get("/api/instagram/mcp")
    def ig_mcp_status():
        return C().instagram_mcp.status()

    @app.post("/api/instagram/mcp/connect")
    def ig_mcp_connect():
        return guard(C().instagram_mcp.connect)

    @app.post("/api/instagram/mcp/call")
    def ig_mcp_call(body: MCPCallIn):
        return guard(C().instagram_mcp.call, body.tool, body.arguments)

    @app.post("/api/instagram/mcp/request")
    def ig_mcp_request(body: MCPCallIn):
        return guard(C().instagram_mcp.request_call, body.tool, body.arguments)

    @app.post("/api/instagram/mcp/execute/{aid}")
    def ig_mcp_execute(aid: int):
        return guard(C().instagram_mcp.execute_approval, aid)

    @app.get("/api/instagram/token-info/{name}")
    def ig_token_info(name: str):
        return guard(C().instagram.token_info, name)

    # Ovoz
    @app.get("/api/voice/status")
    def v_status():
        return C().voice.status()

    @app.post("/api/voice/whisper/load")
    def v_load(body: TextIn):
        return guard(C().voice.load_whisper, body.text or "small")

    @app.post("/api/voice/tts")
    def v_tts(body: TextIn):
        from fastapi.responses import Response
        data, mime, engine = guard(C().voice_pro.synth, body.text)
        return Response(data, media_type=mime, headers={"X-TTS-Engine": engine.encode("ascii", "ignore").decode(), "Cache-Control": "no-store"})

    @app.post("/api/voice/prepare")
    def v_prepare(body: TextIn):
        return C().voice_pro.prepare(body.text)

    @app.get("/api/voice/pro")
    def v_pro():
        return C().voice_pro.status()

    @app.post("/api/voice/transcribe")
    async def v_transcribe(file: UploadFile):
        c = C()
        d = Path(c.settings.allowed_write_dirs[0]) / "voice"
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f"_stt_{int(time.time() * 1000)}{Path(file.filename or 'a.webm').suffix or '.webm'}"
        tmp.write_bytes(await file.read())
        try:
            return guard(c.voice_pro.transcribe, str(tmp))
        finally:
            if not c.settings.save_voice_recordings:
                tmp.unlink(missing_ok=True)

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

    # Maxfiy kalitlar: faqat yozish/o'chirish; qiymat hech qachon qaytarilmaydi va logga tushmaydi
    @app.get("/api/secrets")
    def secrets_status():
        from .secrets import has_secret
        c = C()
        names = ["telegram_bot_token", "pos_api_token", "twilio_auth_token", "meta_app_secret", "instagram_mcp_token", "azure_speech_key"]
        names += [f"instagram_token_{a['name']}" for a in c.settings.instagram_accounts if a.get("name")]
        names += [f"ai_key_{p['id']}" for p in c.settings.ai_providers if p.get("kind") not in ("ollama", None)]
        return [{"name": n, "set": has_secret(n)} for n in names]

    @app.post("/api/secrets")
    def secrets_set(body: SecretIn):
        from .secrets import set_secret
        guard(set_secret, body.name, body.value)
        if body.name == "telegram_bot_token":
            C().telegram.on_token_changed()          # eski egalik va tugmalar bekor bo'ladi
        C().audit.log("secrets", f"Maxfiy kalit kiritildi: {body.name}", target=body.name, risk="C", approval_status="user_action")
        return {"ok": True, "name": body.name}

    @app.post("/api/secrets/delete")
    def secrets_delete(body: SecretIn):
        from .secrets import delete_secret
        guard(delete_secret, body.name)
        if body.name == "telegram_bot_token":
            C().telegram.on_token_changed()
        C().audit.log("secrets", f"Maxfiy kalit o'chirildi: {body.name}", target=body.name, risk="C", approval_status="user_action")
        return {"ok": True}

    @app.get("/api/telephony/status")
    def tel_status():
        return C().telephony.status()

    @app.post("/api/telephony/call/{aid}")
    def tel_call(aid: int):
        return guard(C().telephony.call, aid)

    @app.post("/api/telephony/plan")
    def tel_plan(body: CallIn):
        return guard(C().telephony.plan_call, body.phone, body.message, body.reason, body.est_minutes)

    # Self-improvement
    @app.get("/api/improve/suggestions")
    def imp_sugg():
        return C().improver.suggestions()

    @app.post("/api/improve/suggest")
    def imp_suggest(body: SuggestIn):
        return guard(C().improver.suggest_patch, body.error_id, body.description, body.file)

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

    @app.post("/api/improve/feature")
    def imp_feature(body: FeatureIn):
        return guard(C().improver.feature_request, body.description, body.files)

    @app.post("/api/improve/proposals/{pid}/request-merge")
    def imp_req_merge(pid: int):
        return guard(C().improver.request_merge, pid)

    @app.post("/api/improve/proposals/{pid}/merge")
    def imp_merge(pid: int):
        return guard(C().improver.merge, pid)

    @app.post("/api/improve/proposals/{pid}/revert")
    def imp_revert(pid: int):
        return guard(C().improver.revert_merge, pid)

    @app.get("/api/improve/git")
    def imp_git():
        return C().improver.git_status()

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        from fastapi.responses import Response
        ico = DASHBOARD / "jarvis.ico"
        return FileResponse(ico, media_type="image/x-icon") if ico.exists() else Response(status_code=204)

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
    if sys.stdout is None or sys.stderr is None:
        # pythonw.exe (oynasiz) ostida stdout/stderr yo'q — uvicorn yiqilmasligi va xatolar ko'rinishi uchun log faylga yo'naltiriladi
        from .config import jarvis_home
        log_dir = jarvis_home() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stream = open(log_dir / "server.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    if a.host not in ("127.0.0.1", "localhost"):
        print("OGOHLANTIRISH: server tarmoqqa ochilmoqda. PIN himoyasi bor, lekin HTTPS yo'q — faqat ishonchli tarmoqda!"
              " allowed_hosts ga kompyuter IP manzilini settings.json orqali qo'shing.")
    app = create_app()
    app.state.core.backup.start_auto()        # jadval bo'yicha avtomatik zaxira (backup_interval_hours)
    app.state.core.start_scheduler()          # rejalashtirilgan Instagram postlari → tasdiq so'rovi
    app.state.core.pos_sync.start()           # POS hisobotlarini jadval bo'yicha o'qish (yoqilgan bo'lsa)
    app.state.core.missions.recover(resume=app.state.core.settings.mission_auto_resume)   # uzilgan missiyalar — checkpointdan
    core = app.state.core
    if core.settings.telegram_autostart and core.telegram.token():
        try:
            core.telegram.start()
        except Exception as e:  # Telegram bo'lmasa ham dashboard ishlaydi
            core.audit.error("telegram_agent", f"autostart: {e}")
    active = sum(1 for a in core.agents.agents.values() if getattr(a, "implemented", True))
    core.notifier.notify("Tizim ishga tushdi", f"Holat: Online\nAgentlar: {active} ta faol\nAI: {core.ai.name}", category="startup")
    uvicorn.run(app, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
