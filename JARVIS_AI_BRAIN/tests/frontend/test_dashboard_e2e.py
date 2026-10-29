"""Dashboard end-to-end: haqiqiy server + Chromium. Playwright yo'q bo'lsa — SKIP (release gate buni 'bajarilmadi' deb ko'rsatadi)."""
import os
import socket
import threading
import time

import pytest

from jarvis.config import PROJECT_ROOT

pw = pytest.importorskip("playwright.sync_api")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server(core):
    import uvicorn
    from jarvis.api import create_app
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(create_app(core), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/"
    srv.should_exit = True
    th.join(5)


@pytest.fixture
def page():
    exe = os.environ.get("JARVIS_CHROMIUM_PATH") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        except pw.Error as e:
            pytest.skip(f"Chromium ishga tushmadi: {str(e).splitlines()[0]}")
        pg = b.new_page(viewport={"width": 1400, "height": 1000})
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(f"pageerror: {e} | {(e.stack or '')[:300]}"))
        pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and pg.errors.append(f"console: {m.text}"))
        pg.on("response", lambda r: r.status >= 400 and pg.errors.append(f"HTTP {r.status}: {r.request.method} {r.url}"))
        pg.on("dialog", lambda d: d.accept())
        yield pg
        b.close()


def test_every_section_renders_without_errors(server, page):
    page.goto(server)
    page.wait_for_selector("#menu a")
    ids = page.evaluate("SECTIONS.map(s => s[0])")
    assert len(ids) >= 30
    bad = []
    for sid in ids:
        page.goto(server + "#" + sid)
        page.wait_for_timeout(350)
        text = page.text_content("#view") or ""
        if text.strip().startswith("Xato:"):
            bad.append(f"{sid}: {text[:150]}")
    assert not bad, bad
    assert not page.errors, page.errors


def test_core_user_flows(server, page, core):
    page.goto(server + "#chat")
    page.fill("#msg", "Eslab qol: release gate sinovi")
    page.press("#msg", "Enter")
    page.wait_for_selector("text=Eslab qoldim")
    page.goto(server + "#bi")
    page.wait_for_selector("#f")
    page.set_input_files("#f", str(PROJECT_ROOT / "sample_data" / "demo_mahsulotlar.csv"))
    page.click("#up")
    page.wait_for_selector("#o:has-text('rows_ok')")
    assert core.bi.imports()
    page.goto(server + "#dag")
    page.fill("#goal", "xavfsizlikni tekshir hamda fayllarni ko'rsat")
    page.click("#mk")
    page.wait_for_selector("[data-run]")
    page.click("[data-run]")
    page.wait_for_selector("svg[aria-label='vazifalar grafi']")
    page.wait_for_timeout(800)
    assert core.dag.list()[0]["status"] == "done"
    page.goto(server + "#sandbox")
    page.wait_for_selector("#run")
    page.click("#run")
    page.wait_for_selector("#o:has-text('holat: ok')")
    assert "Salom, sandbox!" in page.text_content("#o")
    page.goto(server + "#approvals")
    page.wait_for_timeout(300)
    assert not page.errors, page.errors
