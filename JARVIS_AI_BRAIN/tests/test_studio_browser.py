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
