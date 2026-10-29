"""O'zbek tilidagi buyruqlarni tushunish: kirill→lotin, apostrof normallashtirish, xatoga chidamli moslash."""
from __future__ import annotations

import difflib
import re

CYR = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
       "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
       "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ы": "i", "ь": "",
       "э": "e", "ю": "yu", "я": "ya", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h"}

# intent -> kalit so'zlar (o'zbekcha, ruscha texnik atamalar, inglizcha)
INTENTS = {
    "greeting": ["salom", "assalomu", "hayrli", "privet", "hello"],
    "memory_save": ["eslab", "esla", "yodda", "saqla", "zapomni", "remember"],
    "memory_search": ["eslaysanmi", "xotira", "xotiradan", "nima dedim", "eslat"],
    "task_create": ["vazifa", "qilish kerak", "zadacha", "task"],
    "file_read": ["fayl", "o'qi", "ochib", "papka", "hujjat", "fail", "file"],
    "status": ["holat", "status", "ahvol", "qanday ishlayapsan", "tizim", "resurs"],
    "help": ["yordam", "nima qila olasan", "imkoniyat", "pomosh", "help"],
    "run_tests": ["test", "tekshir", "sinov", "proverka"],
    "command": ["buyruq", "bajar", "ishga tushir", "zapusti", "komanda", "run"],
    "research": ["internetdan", "internetda", "qidir", "izla", "google", "найди", "search"],
    "bi_report": ["savdo", "ombor", "qoldiq", "foyda", "hisobot", "продажи", "остаток", "sklad"],
    "plan": ["rejala", "reja tuz", "bosqichma", "plan"],
}


def normalize(text: str) -> str:
    t = text.lower().strip()
    t = "".join(CYR.get(ch, ch) for ch in t)
    t = re.sub(r"[`ʻʼ’‘´]", "'", t)
    t = re.sub(r"\s+", " ", t)
    return t


def detect(text: str) -> tuple[str, float]:
    """(intent, ishonch) qaytaradi. Ishonch past bo'lsa — 'unknown', JARVIS aniqlashtiruvchi savol beradi.
    "buyruq: mazmun" ko'rinishida ikki nuqtadan oldingi qism ustuvor (mazmundagi so'zlar chalg'itmasin)."""
    if ":" in text:
        head = _detect(text.split(":", 1)[0])
        if head[0] != "unknown":
            return head
    return _detect(text)


def _detect(text: str) -> tuple[str, float]:
    norm = normalize(text)
    words = re.findall(r"[\w']+", norm)
    best, score = "unknown", 0.0
    for intent, keys in INTENTS.items():
        for k in keys:
            if " " in k:
                s = 1.0 if k in norm else 0.0
            else:
                s = max((difflib.SequenceMatcher(None, k, w).ratio() for w in words), default=0.0)
                if any(w.startswith(k) for w in words):
                    s = max(s, 0.95)
            if s > score:
                best, score = intent, s
    return (best, round(score, 2)) if score >= 0.78 else ("unknown", round(score, 2))
