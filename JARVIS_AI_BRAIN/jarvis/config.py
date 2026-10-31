"""Sozlamalar. Hech qanday lokal disk yo'li (masalan D:\\) majburiy emas.

Ma'lumotlar papkasi JARVIS_HOME muhit o'zgaruvchisi orqali belgilanadi;
berilmasa, loyiha ichidagi ``data/`` ishlatiladi (u .gitignore'da).
Maxfiy kalitlar bu yerda SAQLANMAYDI — ular secrets.py orqali olinadi.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Foydalanuvchi o'zgartira olmaydigan (va JARVIS o'zi o'zgartira olmaydigan) kalitlar.
LOCKED_KEYS = {"read_only_mode", "require_approval", "allowed_read_dirs", "allowed_write_dirs",
               "telegram_allowed_ids", "protected_paths", "command_allowlist", "forbidden_actions", "app_allowlist",
               "auth_enabled", "allowed_hosts", "telegram_approval_max_level", "approval_ttl_hours"}


def jarvis_home() -> Path:
    home = Path(os.environ.get("JARVIS_HOME", PROJECT_ROOT / "data")).resolve()
    home.mkdir(parents=True, exist_ok=True)
    return home


@dataclass
class Settings:
    ai_provider: str = "offline"          # offline | ollama
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:1.5b"    # 8 GB RAM uchun yengil boshlang'ich tanlov
    ai_timeout_sec: int = 60
    language: str = "uz"
    read_only_mode: bool = True           # boshida faqat o'qish/demo
    require_approval: bool = True
    allowed_read_dirs: list[str] = field(default_factory=list)
    allowed_write_dirs: list[str] = field(default_factory=list)
    # Internet va integratsiyalar (maxfiy kalitlar bu yerda emas — secrets.py)
    internet_enabled: bool = False        # internet tadqiqoti faqat siz yoqqanda
    browser_allowed_domains: list[str] = field(default_factory=list)
    telegram_allowed_ids: list[int] = field(default_factory=list)   # qulflangan: faqat settings.json orqali
    telegram_notify: bool = True
    telegram_owner_phone: str = ""        # ixtiyoriy: kontakt orqali tekshiriladigan egasining raqami
    telegram_events: list[str] = field(default_factory=lambda: ["startup", "error", "api", "instagram", "telegram", "task",
                                                                "approval", "resources", "backup", "security", "code", "pos", "integration"])
    telegram_voice_alerts: bool = False   # muhim ogohlantirishlarni ovozli xabar sifatida ham yuborish
    telegram_approvals: bool = True       # tasdiq so'rovlarini tugmalar bilan Telegram'ga yuborish
    telegram_approval_ttl_min: int = 30   # Telegram tugmasi amal qilish muddati
    telegram_approval_max_level: str = "D"   # qulflangan: E-darajali amallar faqat dashboardda tasdiqlanadi
    telegram_autostart: bool = True       # server yonganda bot ham yonsin (sozlangan bo'lsa)
    telegram_execute_after_approval: bool = True   # Telegram'da tasdiqlangan ma'lum amallarni darhol bajarish
    instagram_mcp_url: str = ""           # Instagram MCP Connector manzili (token: instagram_mcp_token)
    meta_app_id: str = ""                 # Meta App ID (App Secret: meta_app_secret, maxfiy)
    instagram_accounts: list[dict] = field(default_factory=list)    # [{"name":..., "ig_user_id":...}] — tokensiz
    pos_site: str = ""                    # POS manzili (keyin beriladi)
    pos_connector: str = "file_export"    # file_export | api | browser
    pos_api: dict = field(default_factory=dict)   # RestApiConnector sozlamasi (tokensiz)
    pos_sync: dict = field(default_factory=dict)  # avtomatik o'qish: {"enabled", "interval_hours", "sources": [...]}
    low_stock_threshold: float = 5
    save_voice_recordings: bool = False
    voice_tts_engine: str = "auto"        # auto | azure | espeak | browser
    voice_stt_engine: str = "auto"        # auto | azure | whisper | browser
    voice_gender: str = "female"          # female (Madina) | male (Sardor) — Azure neyron ovozlari
    voice_rate: int = 0                   # -50..+50 (%)
    voice_volume: int = 100               # 0..100
    voice_stt_language: str = "uz"        # uz | auto (o'zbek/rus/ingliz aralash) | ru-RU | en-US
    voice_silence_ms: int = 900           # gap tugadi deb hisoblash uchun sukunat
    voice_mic_sensitivity: int = 50       # 0..100 (yuqori — sezgirroq)
    azure_speech_region: str = ""         # masalan: westeurope (kalit: azure_speech_key)
    telephony_provider: str = ""          # bo'sh = o'chirilgan
    telephony_cost_per_min: float = 0.0
    telephony_from: str = ""
    telephony_account_sid: str = ""
    telephony_voice_language: str = "ru-RU"
    telephony_rules: list[dict] = field(default_factory=list)
    # Adaptive AI Router: [{"id","kind","model","base_url","tier","local","paid","price_in_per_1k","price_out_per_1k","enabled"}]
    ai_providers: list[dict] = field(default_factory=list)
    ai_task_routes: dict = field(default_factory=dict)       # {"code": "claude", "pos": "local", ...} — vazifa turi bo'yicha afzal model
    ai_custom_catalog: dict = field(default_factory=dict)    # yangi provayder turlari: {"myai": {"title","kind","base_url","model"}}
    ai_strategy: str = "balanced"                            # balanced | cheapest | quality | speed | free_only
    ai_allowed_providers: list[str] = field(default_factory=list)   # bo'sh = hammasi
    ai_confirm_paid: bool = False                            # pullik modeldan oldin foydalanuvchi tasdig'i
    approval_ttl_hours: int = 72                             # C–E tasdiqlar muddati (qulflangan: faqat settings.json)
    embedding_model: str = ""                                # semantik xotira (masalan nomic-embed-text) — foydalanuvchi yoqadi
    autonomy_level: int = 2                                  # 0 maslahat · 1 reja+tasdiq · 2 xavfsiz amallar · 3 agentlar · 4 to'liq sikl
    mission_auto_resume: bool = True                         # qayta ishga tushganda uzilgan missiyalarni checkpointdan davom ettirish
    ai_max_request_cost: float = 0.0                         # bir so'rov uchun maksimal xarajat (0 = cheklanmagan, kunlik/oylik limit baribir)
    # Resource & Cost Guard (pullik AI standart holatda o'chiq)
    paid_ai_allowed: bool = False
    currency: str = "USD"
    daily_cost_limit: float = 0.0
    monthly_cost_limit: float = 0.0
    daily_request_limit: int = 1000
    cost_warn_percent: int = 80
    # Policy Engine: foydalanuvchi avtomatik ruxsat bergan medium-risk amallar
    medium_auto_actions: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)   # qo'shimcha taqiqlar (qulflangan)
    # Sandbox
    command_allowlist: list[str] = field(default_factory=lambda: [
        "dir", "ls", "type", "cat", "echo", "git", "python", "py", "pip", "ffmpeg", "ffprobe", "ollama",
        "whoami", "systeminfo", "Get-ChildItem", "Get-Content", "mkdir", "md", "findstr", "grep", "sort", "more",
        "head", "tail", "wc", "pytest", "node", "npm"])
    # Ruxsat berilgan dasturlar: nom -> buyruq (shell'siz). Faqat settings.json orqali o'zgartiriladi.
    app_allowlist: dict = field(default_factory=lambda: (
        {"bloknot": ["notepad.exe"], "kalkulyator": ["calc.exe"], "paint": ["mspaint.exe"], "explorer": ["explorer.exe"]}
        if os.name == "nt" else {}))
    # Mahalliy rasm generatori va vision (ixtiyoriy)
    image_gen_url: str = ""               # masalan http://127.0.0.1:7860 (Stable Diffusion WebUI --api)
    vision_model: str = ""                # masalan moondream (Ollama)
    planner_use_ai: bool = True           # AI mavjud bo'lsa, maqsadni bosqichlarga AI ajratadi
    # Dashboard himoyasi
    auth_enabled: bool = True             # PIN talab qilinadi (birinchi kirishda o'rnatiladi)
    session_hours: float = 12
    allowed_hosts: list[str] = field(default_factory=lambda: ["127.0.0.1", "localhost"])
    sandbox_backend: str = "process"      # process | docker
    sandbox_timeout_sec: int = 30
    sandbox_memory_mb: int = 256
    sandbox_max_retries: int = 1
    # Backup
    backup_interval_hours: float = 24
    backup_keep: int = 10
    backup_max_total_mb: int = 1000
    backup_include_workspace: bool = False
    # Self-improvement o'zgartira olmaydigan fayllar
    protected_paths: list[str] = field(default_factory=lambda: [
        "jarvis/security.py", "jarvis/approval.py", "jarvis/config.py", "jarvis/secrets.py", "jarvis/improve.py",
        "jarvis/policy.py", "jarvis/sandbox.py", "jarvis/plugins.py", "jarvis/resource_guard.py", "jarvis/backup.py"])

    @classmethod
    def path(cls) -> Path:
        return jarvis_home() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        p = cls.path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        if not s.allowed_read_dirs:
            s.allowed_read_dirs = [str(jarvis_home() / "workspace")]
        if not s.allowed_write_dirs:
            s.allowed_write_dirs = [str(jarvis_home() / "workspace")]
        for d in s.allowed_write_dirs:
            Path(d).mkdir(parents=True, exist_ok=True)
        return s

    def save(self) -> None:
        self.path().write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    def public(self) -> dict:
        return asdict(self)
