"""Security Engine: maxfiy ma'lumotni yashirish, yo'l ruxsatlari, buyruq xavfi, prompt-injection belgilari."""
from __future__ import annotations

import re
from pathlib import Path

SECRET_PATTERNS = [
    re.compile(r"(?i)\b(passw\w*|parol\w*|pwd|token\w*|api[_-]?key\w*|secret\w*|maxfiy[_ ]?kalit\w*)\s*[:=]\s*\S+"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),                 # Telegram bot token
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),                        # OpenAI/Anthropic uslubidagi kalit
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),                   # GitHub token
    re.compile(r"\bEAA[A-Za-z0-9]{30,}\b"),                          # Meta access token
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),                           # karta raqami
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

INJECTION_MARKERS = [
    r"ignore (all|previous|the above) instructions", r"disregard (your|the) (rules|instructions)",
    r"you are now", r"system prompt", r"oldingi ko'rsatmalarni (unut|e'tiborsiz)",
    r"xavfsizlik qoidalarini (o'chir|bekor)", r"approve automatically", r"tasdiqsiz bajar",
]

# Buyruq xavf darajalari: A — o'qish, C — o'zgartirish, E — o'chirish/qaytarib bo'lmaydigan
DANGEROUS_CMD = re.compile(
    r"(?i)\b(rm|del|erase|rmdir|rd|format|diskpart|shutdown|reg\s+(add|delete)|Remove-Item|"
    r"Set-ExecutionPolicy|bcdedit|cipher\s+/w|mkfs|dd\s+if=|takeown|icacls)\b|>\s*\S|Invoke-Expression|iex\b|curl[^|]*\|\s*(sh|bash)"
)
MODIFY_CMD = re.compile(r"(?i)\b(mv|move|copy|cp|ren|rename|mkdir|md|New-Item|Set-Content|Add-Content|pip\s+install|npm\s+install|git\s+(push|commit|reset)|winget|choco)\b")
READ_ONLY_CMD = re.compile(r"(?i)^\s*(dir|ls|type|cat|Get-ChildItem|Get-Content|git\s+(status|log|diff)|python\s+--version|systeminfo|whoami|echo)\b")


def contains_secret(text: str) -> bool:
    return any(p.search(text or "") for p in SECRET_PATTERNS)


# Vault'dan o'qilgan aniq maxfiy qiymatlar (parol, token) — har qanday matnda (log, xato, javob) yashiriladi
_KNOWN_SECRETS: set[str] = set()


def register_secret(value: str | None) -> None:
    if value and len(value) >= 4:
        _KNOWN_SECRETS.add(value)


def redact(text: str) -> str:
    out = text or ""
    for v in sorted(_KNOWN_SECRETS, key=len, reverse=True):
        if v in out:
            out = out.replace(v, "[MAXFIY-YASHIRILDI]")
    for p in SECRET_PATTERNS:
        out = p.sub("[MAXFIY-YASHIRILDI]", out)
    return out


def injection_score(text: str) -> list[str]:
    low = (text or "").lower()
    return [m for m in INJECTION_MARKERS if re.search(m, low)]


def wrap_untrusted(text: str, source: str) -> str:
    """Tashqi matnni (internet, fayl) buyruq emas, faqat ma'lumot sifatida belgilaydi."""
    flags = injection_score(text)
    warn = f" OGOHLANTIRISH: shubhali ko'rsatma topildi ({len(flags)})" if flags else ""
    return f"<untrusted source={source!r}{warn}>\n{text}\n</untrusted>"


ORDER = "ACE"


def classify_command(cmd: str) -> str:
    parts = [p for p in re.split(r"&&|\|\||[;&|\n]|\$\(|`", cmd) if p.strip()]
    if len(parts) > 1:  # zanjirlangan buyruq — eng xavfli qismi bo'yicha, kamida C
        return max((classify_command(p) for p in parts), key=ORDER.index, default="C").replace("A", "C")
    if DANGEROUS_CMD.search(cmd):
        return "E"
    if MODIFY_CMD.search(cmd):
        return "C"
    if READ_ONLY_CMD.search(cmd):
        return "A"
    return "C"  # noma'lum buyruq — ehtiyotkorlik bilan o'zgartirish darajasi


def is_within(path: str | Path, roots: list[str]) -> bool:
    p = Path(path).resolve()
    for r in roots:
        try:
            p.relative_to(Path(r).resolve())
            return True
        except ValueError:
            continue
    return False
