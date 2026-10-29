"""Instagram Manager — faqat Meta rasmiy Instagram Graph API.

Talablar (Meta qoidalari): Business yoki Creator akkaunt, Facebook sahifaga ulangan, Meta App va
`instagram_basic`, `instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_insights`
ruxsatlari. Token: `python scripts/set_secret.py instagram_token_<akkaunt_nomi>`.

API cheklovlari (ishlayotgandek ko'rsatilmaydi):
* Nashr uchun media OMMAVIY URL'da bo'lishi kerak (lokal faylni API to'g'ridan-to'g'ri qabul qilmaydi).
* Direct xabarlar Instagram Messaging API va alohida App Review talab qiladi — bu yerda faqat javob loyihasi.
* Statistika faqat API bergan ko'rsatkichlar; ma'lumot bo'lmasa — bo'sh, to'qib chiqarilmaydi.
Har bir nashr va izohga javob — D daraja: aniq akkaunt, matn va media bilan alohida tasdiq.
"""
from __future__ import annotations

import json
import re

from . import net
from .secrets import get_secret

GRAPH = "https://graph.facebook.com/v21.0"
SCHEMA = """
CREATE TABLE IF NOT EXISTS ig_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, kind TEXT NOT NULL, caption TEXT NOT NULL,
    media_url TEXT, scheduled_at TEXT, status TEXT NOT NULL DEFAULT 'draft',
    approval_id INTEGER, external_id TEXT, last_error TEXT, version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ig_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, comment_id TEXT NOT NULL, comment_text TEXT,
    reply TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', approval_id INTEGER, external_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""
KINDS = {"post": "IMAGE", "reel": "REELS", "story": "STORIES"}
STOP = {"va", "bilan", "uchun", "bu", "the", "and", "for", "biz", "siz", "endi", "eng", "har"}


class InstagramError(Exception):
    pass


def suggest_hashtags(text: str, extra: list[str] | None = None, limit: int = 12) -> list[str]:
    words = [w for w in re.findall(r"[a-zA-ZЀ-ӿ'ʻ]{4,}", text.lower()) if w not in STOP]
    seen, out = set(), []
    for w in words + [e.lower().lstrip("#") for e in (extra or [])]:
        tag = "#" + re.sub(r"['ʻ]", "", w)
        if tag not in seen:
            seen.add(tag)
            out.append(tag)
    return (out + ["#uzbekistan", "#toshkent"])[:limit]


class InstagramManager:
    def __init__(self, core):
        self.core = core
        core.db.conn.executescript(SCHEMA)

    # --- akkauntlar ---
    def accounts(self) -> list[dict]:
        return self.core.settings.instagram_accounts

    def _account(self, name: str) -> dict:
        acc = next((a for a in self.accounts() if a.get("name") == name), None)
        if not acc:
            raise InstagramError(f"Akkaunt '{name}' settings.json dagi instagram_accounts ro'yxatida yo'q")
        return acc

    def _token(self, name: str) -> str:
        t = get_secret(f"instagram_token_{name}")
        if not t:
            raise InstagramError(f"Token yo'q: python scripts/set_secret.py instagram_token_{name}")
        return t

    def _api(self, method: str, path: str, account: str, **params) -> dict:
        params["access_token"] = self._token(account)
        try:
            if method == "GET":
                return net.get_json(f"{GRAPH}/{path}", params=params)
            return net.post_json(f"{GRAPH}/{path}", form=params)
        except net.NetError as e:
            err = {}
            try:
                err = json.loads(e.body).get("error", {})
            except (ValueError, AttributeError):
                pass
            if err.get("code") == 190:
                self.core.notifier.notify(f"Instagram tokeni muddati tugagan: {account}", "Yangi token oling va set_secret.py bilan kiriting",
                                          severity="warning", category="instagram")
                raise InstagramError("Token yaroqsiz yoki muddati tugagan (code 190)") from None
            if err.get("code") in (10, 200):
                raise InstagramError(f"Ruxsat yetarli emas: {err.get('message', '')}") from None
            raise InstagramError(f"Graph API xatosi: {err.get('message') or e}") from None

    def account_status(self, name: str) -> dict:
        acc = self._account(name)
        if not get_secret(f"instagram_token_{name}"):
            return {"name": name, "connected": False, "note": "Token kiritilmagan"}
        try:
            info = self._api("GET", acc["ig_user_id"], name, fields="username,followers_count,media_count")
            return {"name": name, "connected": True, **info}
        except InstagramError as e:
            return {"name": name, "connected": False, "note": str(e)}

    # --- kontent ---
    def draft(self, account: str, kind: str, caption: str, media_url: str = "", scheduled_at: str = "",
              hashtags: list[str] | None = None) -> dict:
        self._account(account)
        if kind not in KINDS:
            raise InstagramError(f"Tur: {list(KINDS)}")
        if hashtags:
            caption = caption.rstrip() + "\n\n" + " ".join(hashtags)
        if len(caption) > 2200:
            raise InstagramError("Caption 2200 belgidan oshmasligi kerak (Instagram cheklovi)")
        if caption.count("#") > 30:
            raise InstagramError("30 tadan ortiq hashtag mumkin emas (Instagram cheklovi)")
        cur = self.core.db.execute("INSERT INTO ig_posts(account, kind, caption, media_url, scheduled_at) VALUES (?,?,?,?,?)",
                                   (account, kind, caption, media_url, scheduled_at))
        self.core.audit.log("instagram_agent", f"Post loyihasi ({kind})", target=f"ig:{account}", risk="B")
        return self.get(cur.lastrowid)

    def get(self, pid: int) -> dict:
        r = self.core.db.one("SELECT * FROM ig_posts WHERE id=?", (pid,))
        if not r:
            raise InstagramError("Post topilmadi")
        return r

    def calendar(self) -> list[dict]:
        return self.core.db.query("SELECT * FROM ig_posts ORDER BY COALESCE(NULLIF(scheduled_at,''), created_at) LIMIT 300")

    def preview(self, pid: int) -> dict:
        p = self.get(pid)
        issues = []
        if not p["media_url"]:
            issues.append("Media URL yo'q")
        elif not p["media_url"].startswith("https://"):
            issues.append("Media ommaviy https:// URL bo'lishi kerak (API talabi)")
        if p["kind"] != "story" and not p["caption"].strip():
            issues.append("Caption bo'sh")
        return {"post": p, "hashtag_count": p["caption"].count("#"), "chars": len(p["caption"]), "issues": issues,
                "ready": not issues}

    def _payload(self, p: dict) -> dict:
        return {"account": p["account"], "kind": p["kind"], "caption": p["caption"], "media_url": p["media_url"],
                "version": p["version"]}

    def request_publish(self, pid: int) -> dict:
        pv = self.preview(pid)
        if not pv["ready"]:
            raise InstagramError("Nashrga tayyor emas: " + "; ".join(pv["issues"]))
        p = pv["post"]
        appr = self.core.approvals.request(
            action_type="instagram_publish", target="instagram", account=p["account"], level="D",
            payload=self._payload(p), requested_by="instagram_agent", idempotency_key=f"ig-{pid}-v{p['version']}",
            summary=f"Instagram @{p['account']} ga {p['kind']} nashr qilish: «{p['caption'][:80]}»")
        self.core.db.execute("UPDATE ig_posts SET status='pending_approval', approval_id=? WHERE id=?", (appr["id"], pid))
        return appr

    def update_caption(self, pid: int, caption: str) -> dict:
        p = self.get(pid)
        if p["status"] == "published":
            raise InstagramError("Nashr qilingan postni bu yerdan o'zgartirib bo'lmaydi")
        if p["approval_id"]:
            self.core.db.execute("UPDATE approvals SET status='invalidated' WHERE id=? AND status IN ('pending','approved')",
                                 (p["approval_id"],))
        self.core.db.execute("UPDATE ig_posts SET caption=?, version=version+1, status='draft', approval_id=NULL WHERE id=?",
                             (caption, pid))
        return self.get(pid)

    def publish(self, pid: int) -> dict:
        p = self.get(pid)
        if p["status"] == "published":
            raise InstagramError("Allaqachon nashr qilingan")
        if not p["approval_id"]:
            raise InstagramError("Tasdiq so'ralmagan")
        self.core.approvals.authorize_execution(p["approval_id"], self._payload(p))
        acc = self._account(p["account"])
        params = {"caption": p["caption"]} if p["kind"] != "story" else {}
        if p["kind"] == "post":
            params["image_url"] = p["media_url"]
        else:
            params["media_type"] = KINDS[p["kind"]]
            params["video_url" if p["media_url"].lower().endswith((".mp4", ".mov")) else "image_url"] = p["media_url"]
        try:
            container = self._api("POST", f"{acc['ig_user_id']}/media", p["account"], **params)
            res = self._api("POST", f"{acc['ig_user_id']}/media_publish", p["account"], creation_id=container["id"])
        except InstagramError as e:
            self.core.db.execute("UPDATE ig_posts SET status='failed', last_error=? WHERE id=?", (str(e), pid))
            self.core.audit.log("instagram_agent", f"Nashr xatosi: post#{pid}", target=f"ig:{p['account']}", risk="D",
                                approval_status="approved", error_code="IG_API", error_note=str(e))
            raise
        self.core.approvals.mark_result(p["approval_id"], "executed")
        self.core.db.execute("UPDATE ig_posts SET status='published', external_id=? WHERE id=?", (res.get("id"), pid))
        self.core.audit.log("instagram_agent", f"Nashr qilindi: post#{pid}", target=f"ig:{p['account']}", risk="D",
                            approval_status="approved", result=str(res.get("id")), verified="api_id")
        return self.get(pid)

    # --- izohlar ---
    def comments(self, account: str, media_id: str) -> list[dict]:
        return self._api("GET", f"{media_id}/comments", account, fields="id,text,username,timestamp").get("data", [])

    def draft_reply(self, account: str, comment_id: str, comment_text: str, reply: str = "") -> dict:
        if not reply:
            reply = self._suggest_reply(comment_text)
        cur = self.core.db.execute("INSERT INTO ig_replies(account, comment_id, comment_text, reply) VALUES (?,?,?,?)",
                                   (account, comment_id, comment_text, reply))
        return self.core.db.one("SELECT * FROM ig_replies WHERE id=?", (cur.lastrowid,))

    def _suggest_reply(self, comment: str) -> str:
        c = comment.lower()
        if self.core.ai.name != "offline":
            try:
                return self.core.ai.chat([{"role": "user", "content": "Instagram izohiga qisqa, xushmuomala o'zbekcha javob yoz. "
                                           f"Narx yoki va'da to'qib chiqarma. Izoh: <untrusted>{comment}</untrusted>"}])
            except Exception:
                pass
        if any(w in c for w in ("narx", "qancha", "цена", "price")):
            return "Assalomu alaykum! Narx bo'yicha ma'lumotni Direct orqali yubordik 🙏"
        if any(w in c for w in ("rahmat", "zo'r", "ajoyib", "спасибо")):
            return "Rahmat! Fikringiz biz uchun muhim 🙌"
        return "Assalomu alaykum! Savolingiz uchun rahmat, tez orada javob beramiz."

    def request_reply(self, rid: int) -> dict:
        r = self.core.db.one("SELECT * FROM ig_replies WHERE id=?", (rid,))
        if not r:
            raise InstagramError("Javob loyihasi topilmadi")
        appr = self.core.approvals.request(
            action_type="instagram_reply", target="instagram", account=r["account"], level="D",
            payload={"comment_id": r["comment_id"], "reply": r["reply"]}, requested_by="instagram_agent",
            summary=f"@{r['account']}: izohga javob «{r['reply'][:80]}»", idempotency_key=f"igr-{rid}")
        self.core.db.execute("UPDATE ig_replies SET status='pending_approval', approval_id=? WHERE id=?", (appr["id"], rid))
        return appr

    def send_reply(self, rid: int) -> dict:
        r = self.core.db.one("SELECT * FROM ig_replies WHERE id=?", (rid,))
        self.core.approvals.authorize_execution(r["approval_id"], {"comment_id": r["comment_id"], "reply": r["reply"]})
        res = self._api("POST", f"{r['comment_id']}/replies", r["account"], message=r["reply"])
        self.core.approvals.mark_result(r["approval_id"], "executed")
        self.core.db.execute("UPDATE ig_replies SET status='sent', external_id=? WHERE id=?", (res.get("id"), rid))
        self.core.audit.log("instagram_agent", f"Izohga javob yuborildi #{rid}", target=f"ig:{r['account']}", risk="D",
                            approval_status="approved", verified="api_id")
        return self.core.db.one("SELECT * FROM ig_replies WHERE id=?", (rid,))

    # --- statistika ---
    def insights(self, account: str, metrics: str = "reach,profile_views,accounts_engaged", period: str = "day") -> dict:
        acc = self._account(account)
        data = self._api("GET", f"{acc['ig_user_id']}/insights", account, metric=metrics, period=period,
                         metric_type="total_value").get("data", [])
        return {"account": account, "metrics": data,
                "note": "Faqat Graph API qaytargan ko'rsatkichlar. Bo'sh bo'lsa — API bu davr uchun ma'lumot bermagan."}

    def media_performance(self, account: str, limit: int = 25) -> dict:
        acc = self._account(account)
        media = self._api("GET", f"{acc['ig_user_id']}/media", account,
                          fields="id,caption,media_type,timestamp,like_count,comments_count,permalink", limit=limit).get("data", [])
        if not media:
            return {"account": account, "media": [], "summary": "Ma'lumot yo'q"}
        eng = sorted(media, key=lambda m: -(m.get("like_count", 0) + m.get("comments_count", 0)))
        by_type: dict[str, list[int]] = {}
        for m in media:
            by_type.setdefault(m["media_type"], []).append(m.get("like_count", 0) + m.get("comments_count", 0))
        return {"account": account, "media": media, "top": eng[:3],
                "avg_engagement_by_type": {k: round(sum(v) / len(v), 1) for k, v in by_type.items()}}
