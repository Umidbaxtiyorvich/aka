import os
import shutil
import subprocess

import pytest

from jarvis.studio import StudioError, build_srt

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg yo'q")


def _video(core, name="v.mp4", size="640x360", dur=4):
    p = f"{core.settings.allowed_read_dirs[0]}/{name}"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=25:duration={dur}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}", "-c:v", "libx264", "-c:a", "aac", "-shortest", p], check=True)
    return p


@needs_ffmpeg
def test_video_pipeline(core):
    src = _video(core)
    info = core.studio.probe(src)
    assert info["video"]["width"] == 640 and info["audio"]
    q = core.studio.quality_check(src, "reels")
    assert not q["ok"] and any("1080x1920" in i for i in q["issues"])
    trimmed = core.studio.trim(src, 0.5, 2.5)["output"]
    assert 1.8 < core.studio.probe(trimmed)["duration"] < 2.3
    vert = core.studio.to_vertical(src)["output"]
    v = core.studio.probe(vert)["video"]
    assert (v["width"], v["height"]) == (1080, 1920)
    both = core.studio.concat([src, trimmed])["output"]
    assert core.studio.probe(both)["duration"] > 5.5
    assert core.studio.convert(src, "mp3")["output"].endswith(".mp3")
    assert os.path.getsize(src) > 0      # asl fayl joyida


@needs_ffmpeg
def test_subtitles_and_slideshow(core):
    src = _video(core)
    r = core.studio.add_subtitles(src, [{"start": 0, "end": 1.5, "text": "Salom, dunyo"}], burn=False)
    assert "00:00:01,500" in open(r["output"], encoding="utf-8").read()
    try:
        burned = core.studio.add_subtitles(src, [{"start": 0, "end": 1.5, "text": "Salom"}])["output"]
        assert os.path.exists(burned)
    except StudioError as e:   # ba'zi FFmpeg build'larida libass yo'q
        assert "subtitles" in str(e).lower() or "filter" in str(e).lower()
    img = core.studio.make_logo("Jarvis AI")["output"]
    shutil.copy(img, core.settings.allowed_read_dirs[0] + "/l.png")
    show = core.studio.slideshow([core.settings.allowed_read_dirs[0] + "/l.png"] * 2, seconds=1)["output"]
    assert 1.8 < core.studio.probe(show)["duration"] < 2.3


def test_srt_validation():
    with pytest.raises(StudioError):
        build_srt([{"start": 2, "end": 1, "text": "x"}])


def test_image_tools(core):
    from PIL import Image
    p = f"{core.settings.allowed_read_dirs[0]}/rasm.png"
    Image.new("RGB", (1600, 900), (20, 40, 200)).save(p)
    a = core.studio.analyze_image(p)
    assert a["width"] == 1600 and a["dominant_colors"][0] == "#1428c8"
    r = core.studio.resize(p, "instagram_post", "crop")["output"]
    assert Image.open(r).size == (1080, 1080)
    t = core.studio.add_text(p, "Chegirma 20%")["output"]
    assert Image.open(t).size == (1600, 900)
    assert "aspect ratio 1080:1920" in core.studio.image_prompt("non mahsuloti", "story")["prompt"]
    with pytest.raises(Exception):
        core.studio.analyze_image("/etc/hostname")


def _chromium():
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    if os.path.exists("/opt/pw-browsers/chromium"):
        os.environ.setdefault("JARVIS_CHROMIUM_PATH", "/opt/pw-browsers/chromium")
    return True


def test_browser_domain_allowlist(core):
    from jarvis.browser import BrowserError, domain_allowed
    assert domain_allowed("https://pos.example.uz/x", ["example.uz"])
    assert not domain_allowed("https://evil-example.uz", ["example.uz"])
    with pytest.raises(BrowserError, match="ruxsat"):
        core.browser.inspect("https://example.com")


@pytest.mark.skipif(not _chromium(), reason="playwright o'rnatilmagan")
def test_browser_reads_local_site(core, tmp_path):
    import http.server
    import threading
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "index.html").write_text(
        "<title>Demo POS</title><a href='/kirim'>Kirim</a><a href='/ombor'>Ombor</a>"
        "<form action='/login' method='post'><input name='login'><input type='password' name='parol'></form>"
        "<table><tr><th>Mahsulot</th><th>Qoldiq</th></tr></table>", encoding="utf-8")
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp_path / "site"), **k)  # noqa: E731
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    core.settings.browser_allowed_domains = ["127.0.0.1"]
    try:
        m = core.browser.site_map(f"http://127.0.0.1:{srv.server_address[1]}/")
    finally:
        srv.shutdown()
    assert m["title"] == "Demo POS" and {s["text"] for s in m["sections"]} == {"Kirim", "Ombor"}
    assert m["forms"][0]["fields"] == ["login", "parol"] and m["tables"] == [["Mahsulot", "Qoldiq"]]
    assert any("parol kiritmaydi" in n for n in m["notes"]) and os.path.exists(m["screenshot"])


needs_espeak = pytest.mark.skipif(not (shutil.which("espeak-ng") or shutil.which("espeak")), reason="espeak-ng yo'q")


@needs_espeak
@needs_ffmpeg
def test_uzbek_tts_and_voiceover(core):
    r = core.voice.synthesize("Assalomu alaykum! Bugungi savdo hisoboti tayyor.")
    assert r["engine"] == "espeak-ng (uz)" and os.path.getsize(r["output"]) > 10000
    shutil.copy(r["output"], core.settings.allowed_read_dirs[0] + "/ovoz.wav")
    info = core.studio.probe(core.settings.allowed_read_dirs[0] + "/ovoz.wav")
    assert info["audio"] and info["duration"] > 1
    src = _video(core, dur=3)
    out = core.studio.voiceover(src, "Yangi mahsulot keldi")["output"]
    assert core.studio.probe(out)["audio"]


def test_tts_validation(core):
    from jarvis.voice import VoiceError
    with pytest.raises(VoiceError):
        core.voice.synthesize("   ")


class _Seg:
    def __init__(self, s, e, t):
        self.start, self.end, self.text = s, e, t


class _Info:
    language, language_probability = "uz", 0.91


class _FakeWhisper:
    def transcribe(self, path, language="uz", vad_filter=True):
        assert os.path.exists(path)
        return iter([_Seg(0.0, 1.2, " Salom "), _Seg(1.3, 2.8, "Bugun chegirma"), _Seg(2.9, 3.0, "  ")]), _Info()


@needs_ffmpeg
def test_auto_subtitles_with_whisper(core):
    from jarvis.voice import VoiceError
    src = _video(core, dur=3)
    with pytest.raises(VoiceError, match="yuklanmagan"):
        core.studio.auto_subtitles(src)
    core.voice._model, core.voice._model_name = _FakeWhisper(), "small"
    r = core.studio.auto_subtitles(src, burn=False)
    srt = open(r["output"], encoding="utf-8").read()
    assert r["segments"] == 2 and "00:00:01,300 --> 00:00:02,800" in srt and "Bugun chegirma" in srt
    assert not [f for f in os.listdir(core.studio.exports) if f.endswith(".wav") and "_audio" in f]   # vaqtinchalik audio o'chirildi


@pytest.mark.skipif(not _chromium(), reason="playwright o'rnatilmagan")
def test_session_browser_reads_tables_after_user_login(core, tmp_path):
    """Login talab qiladigan sayt: sessiyasiz — login_required; sessiya bilan — jadvallar CSV'ga."""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            logged = "sess=ok" in (self.headers.get("Cookie") or "")
            if self.path == "/login-ok":        # foydalanuvchi o'zi kirgandek
                self.send_response(200)
                self.send_header("Set-Cookie", "sess=ok; Path=/; Max-Age=3600")
                self.end_headers()
                self.wfile.write(b"ok")
                return
            body = ("<title>Hisobotlar</title><table><tr><th>Kod</th><th>Nomi</th><th>Qoldiq</th></tr>"
                    "<tr><td>A1</td><td>Non</td><td>3</td></tr><tr><td>B2</td><td>Sut</td><td>20</td></tr></table>") if logged else \
                   "<title>Kirish</title><form><input name=login><input type=password name=p></form>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    core.settings.browser_allowed_domains = ["127.0.0.1"]
    sb = core.session_browser
    try:
        assert sb.extract_tables(base + "/reports", wait_ms=100)["status"] == "login_required"
        sb.extract_tables(base + "/login-ok", wait_ms=100)          # profilga cookie yoziladi (login o'rniga)
        r = sb.extract_tables(base + "/reports", wait_ms=100)
    finally:
        srv.shutdown()
    assert r["status"] == "ok" and r["tables"][0]["columns"] == ["Kod", "Nomi", "Qoldiq"] and r["tables"][0]["rows"] == 2
    imp = core.bi.import_file(r["tables"][0]["path"], "products")
    assert imp["rows_ok"] == 2                                      # BI'ga to'g'ridan-to'g'ri import bo'ladi
    assert sb.forget()["status"] == "forgotten"
    from jarvis.browser import BrowserError
    with pytest.raises(BrowserError):
        sb.extract_tables("http://example.com/x")


@pytest.mark.skipif(not _chromium(), reason="playwright o'rnatilmagan")
def test_pos_sync_replaces_snapshots_and_alerts(core):
    import http.server
    import threading
    state = {"logged": True, "sales": [("S-1", "A1", 2, 4000)], "stock": 3}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if not state["logged"]:
                body = "<form><input type=password></form>"
            elif self.path.startswith("/sales"):
                rows = "".join(f"<tr><td>{d}</td><td>sotuv</td><td>2026-10-30</td><td>Mijoz</td><td>{k}</td><td>{q}</td><td>{p}</td><td>{q * p}</td></tr>"
                               for d, k, q, p in state["sales"])
                body = ("<table><tr><th>Hujjat raqami</th><th>Turi</th><th>Sana</th><th>Kontragent</th><th>Kod</th><th>Miqdor</th>"
                        f"<th>Narx</th><th>Summa</th></tr>{rows}</table>")
            else:
                body = ("<table><tr><th>Kod</th><th>Nomi</th><th>Tannarx</th><th>Sotish narxi</th><th>Qoldiq</th><th>Minimal</th></tr>"
                        f"<tr><td>A1</td><td>Non</td><td>3000</td><td>4000</td><td>{state['stock']}</td><td>5</td></tr></table>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    core.settings.browser_allowed_domains = ["127.0.0.1"]
    core.settings.pos_sync = {"enabled": True, "sources": [{"name": "savdo", "url": base + "/sales", "wait_ms": 50},
                                                           {"name": "qoldiq", "url": base + "/stock", "wait_ms": 50}]}
    try:
        r1 = core.pos_sync.run()
        assert r1["status"] == "ok" and r1["imported"] == 2
        assert core.bi.profit()["revenue"] == 8000
        assert any("Kam qolgan" in n["title"] for n in core.notifier.list())          # qoldiq 3 < minimal 5
        r2 = core.pos_sync.run()                                                       # o'zgarmagan
        assert core.bi.profit()["revenue"] == 8000 and all("o'zgarmagan" in x for x in r2["notes"])
        state["sales"].append(("S-2", "A1", 1, 4000))                                  # yangi savdo
        core.pos_sync.run()
        assert core.bi.profit()["revenue"] == 12000                                    # ikki marta hisoblanmadi
        assert len(core.db.query("SELECT * FROM bi_movements")) == 2
        state["logged"] = False
        r4 = core.pos_sync.run()
        assert r4["status"] == "login_required"
        assert any("qayta kiring" in (n["body"] or "") for n in core.notifier.list())
        assert core.bi.profit()["revenue"] == 12000                                    # eski ma'lumot saqlandi
    finally:
        srv.shutdown()
        core.session_browser.forget()


def test_detect_kind():
    from jarvis.bi import BIError, BusinessIntelligence
    assert BusinessIntelligence.detect_kind(["Kod", "Turi", "Miqdor"]) == "movements"
    assert BusinessIntelligence.detect_kind(["Артикул", "Наименование", "Остаток"]) == "products"
    assert BusinessIntelligence.detect_kind(["Sana", "Kontragent", "Summa"]) == "payments"
    with pytest.raises(BIError):
        BusinessIntelligence.detect_kind(["x", "y"])
