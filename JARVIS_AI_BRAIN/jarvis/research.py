"""Research Agent: internetdan qidirish, sahifani o'qish, manba/sana/ishonch bilan javob.

* Faqat `internet_enabled` yoqilganda ishlaydi (standart: o'chiq).
* Sahifa matni ISHONCHSIZ: <untrusted> bilan o'raladi, yashirin ko'rsatmalar aniqlanadi va bajarilmaydi.
* Lokal/ichki tarmoq manzillari bloklanadi (SSRF himoyasi).
* Xotiraga saqlash faqat foydalanuvchi bosganda (manba URL va ishonch bilan).
"""
from __future__ import annotations

import html
import ipaddress
import re
import socket
import urllib.parse
from datetime import datetime, timezone
from html.parser import HTMLParser

from . import net
from .security import injection_score, wrap_untrusted

SEARCH_URL = "https://html.duckduckgo.com/html/"
HIGH = ("gov", "edu", "gov.uz", "python.org", "microsoft.com", "mozilla.org", "github.com", "ollama.com",
        "developers.facebook.com", "core.telegram.org", "fastapi.tiangolo.com", "ffmpeg.org", "lex.uz")


class ResearchError(Exception):
    pass


def reliability(url: str) -> tuple[float, str]:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in HIGH) or host.startswith(("docs.", "developer.")):
        return 0.8, "rasmiy hujjat/organ (taxminiy)"
    if "wikipedia.org" in host:
        return 0.65, "ensiklopediya (tekshirish kerak)"
    if any(x in host for x in ("stackoverflow.com", "stackexchange.com", "reddit.com", "habr.com")):
        return 0.55, "hamjamiyat forumi"
    return 0.45, "noma'lum manba"


def check_public_url(url: str) -> str:
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ResearchError("Faqat http/https manzillar")
    try:
        infos = socket.getaddrinfo(u.hostname, None)
    except socket.gaierror as e:
        raise ResearchError(f"Domen topilmadi: {u.hostname}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ResearchError("Ichki/lokal tarmoq manziliga so'rov bloklandi")
    return url


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "template"}

    def __init__(self):
        super().__init__()
        self.parts, self.title, self._skip, self._in_title = [], "", 0, False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in ("p", "div", "li", "h1", "h2", "h3", "br", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(page: str) -> tuple[str, str]:
    p = _TextExtractor()
    p.feed(page)
    text = re.sub(r"[ \t]+", " ", "".join(p.parts))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return p.title.strip(), text


class _DDGParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results, self._cur, self._field = [], None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag == "a" and "result__a" in cls:
            self._cur = {"title": "", "url": a.get("href", ""), "snippet": ""}
            self.results.append(self._cur)
            self._field = "title"
        elif tag in ("a", "div") and "result__snippet" in cls and self._cur is not None:
            self._field = "snippet"

    def handle_endtag(self, tag):
        if tag in ("a", "div"):
            self._field = None

    def handle_data(self, data):
        if self._cur is not None and self._field:
            self._cur[self._field] += data


def _clean_ddg_url(href: str) -> str:
    if "uddg=" in href:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        return q.get("uddg", [href])[0]
    return "https:" + href if href.startswith("//") else href


class Research:
    def __init__(self, core):
        self.core = core

    def _require_internet(self):
        if not self.core.settings.internet_enabled:
            raise ResearchError("Internet o'chirilgan. Sozlamalar → Internet tadqiqoti ni yoqing. "
                                "Hozircha mahalliy xotira va fayllar bilan ishlayman.")

    def search(self, query: str, limit: int = 6) -> list[dict]:
        self._require_internet()
        if not query.strip():
            raise ResearchError("Bo'sh so'rov")
        try:
            status, body = net.request("POST", SEARCH_URL, form={"q": query}, timeout=15)
        except net.NetError as e:
            raise ResearchError(f"Qidiruv tizimiga ulanib bo'lmadi: {e}") from e
        if status >= 400:
            raise ResearchError(f"Qidiruv xatosi: HTTP {status}")
        p = _DDGParser()
        p.feed(body)
        out = []
        for r in p.results:
            url = _clean_ddg_url(html.unescape(r["url"]))
            if not url.startswith("http"):
                continue
            score, label = reliability(url)
            out.append({"title": r["title"].strip(), "url": url, "snippet": r["snippet"].strip(),
                        "domain": urllib.parse.urlparse(url).hostname, "reliability": score, "reliability_note": label})
            if len(out) >= limit:
                break
        self.core.audit.log("research_agent", f"Qidiruv: {query[:80]}", target="internet", risk="A", result=f"{len(out)} natija")
        return out

    def fetch(self, url: str, max_chars: int = 20000) -> dict:
        self._require_internet()
        check_public_url(url)
        try:
            status, body = net.request("GET", url, timeout=20)
        except net.NetError as e:
            raise ResearchError(f"Sahifani ochib bo'lmadi: {e}") from e
        if status >= 400:
            raise ResearchError(f"HTTP {status}: {url}")
        title, text = html_to_text(body)
        text = text[:max_chars]
        flags = injection_score(text)
        score, label = reliability(url)
        if flags:
            self.core.notifier.notify("Sahifada shubhali ko'rsatma", f"{url}: {len(flags)} ta belgi. Bajarilmadi.",
                                      severity="warning", category="security")
        return {"url": url, "title": title, "text": text, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "reliability": score, "reliability_note": label, "injection_flags": flags}

    def answer(self, query: str, pages: int = 3) -> dict:
        results = self.search(query)
        sources, errors = [], []
        for r in results[:pages]:
            try:
                sources.append(self.fetch(r["url"]) | {"snippet": r["snippet"]})
            except ResearchError as e:
                errors.append(f"{r['url']}: {e}")
        if not sources:
            return {"query": query, "answer": "Manbalarni o'qib bo'lmadi.", "sources": [], "errors": errors,
                    "search_results": results}
        if self.core.ai.name != "offline":
            ctx = "\n\n".join(f"[{i + 1}] {wrap_untrusted(s['text'][:3000], s['url'])}" for i, s in enumerate(sources))
            prompt = (f"Savol: {query}\nQuyidagi manbalar asosida o'zbek tilida qisqa javob ber, har bir fikrdan keyin "
                      f"[raqam] bilan manbani ko'rsat. Manbalar bir-biriga zid bo'lsa, buni ayt.\n{ctx}")
            try:
                text = self.core.ai.chat([{"role": "user", "content": prompt}])
            except Exception as e:
                text = f"AI xulosa chiqara olmadi ({e}). Quyida manbalardan parchalar."
        else:
            text = self._extractive(query, sources)
        return {"query": query, "answer": text, "errors": errors, "search_results": results,
                "sources": [{"n": i + 1, "title": s["title"], "url": s["url"], "fetched_at": s["fetched_at"],
                             "reliability": s["reliability"], "reliability_note": s["reliability_note"],
                             "injection_flags": s["injection_flags"]} for i, s in enumerate(sources)]}

    @staticmethod
    def _extractive(query: str, sources: list[dict]) -> str:
        terms = {t for t in re.findall(r"\w+", query.lower()) if len(t) > 2}
        lines = []
        for i, s in enumerate(sources, 1):
            sents = re.split(r"(?<=[.!?])\s+", s["text"].replace("\n", " "))
            best = sorted(sents, key=lambda x: -sum(t in x.lower() for t in terms))[:2]
            lines += [f"{b.strip()[:300]} [{i}]" for b in best if b.strip()]
        return "AI ulanmagan — manbalardan eng mos parchalar:\n" + "\n".join(lines)
