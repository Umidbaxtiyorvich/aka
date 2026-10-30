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
            # Dasturiy WebGL (SwiftShader): GPU'siz CI'da ham 3D Brain / Graph Explorer sinaladi
            gl = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
            b = p.chromium.launch(executable_path=exe, args=gl) if exe else p.chromium.launch(args=gl)
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


def test_login_flow(server, page, core):
    core.settings.auth_enabled = True
    page.goto(server)
    page.wait_for_selector("#login")
    assert "PIN o'rnating" in page.text_content("#login")
    page.fill("#pin1", "jarvis-2026-uz")
    page.fill("#pin2", "jarvis-2026-uz")
    page.click("#pinok")
    page.wait_for_selector("#login", state="detached")
    page.wait_for_selector("text=AI HOLATI")
    page.wait_for_selector("#logout")
    page.click("#logout")
    page.wait_for_selector("#login")
    page.fill("#pin1", "notogri")
    page.click("#pinok")
    page.wait_for_selector("#pinmsg .bad")
    page.fill("#pin1", "jarvis-2026-uz")
    page.click("#pinok")
    page.wait_for_selector("#login", state="detached")
    errs = [e for e in page.errors if "401" not in e]      # kirishdan oldingi 401 javoblar kutilgan
    assert not errs, errs


def test_real_keyboard_typing_works_everywhere(server, page):
    """fill() klaviatura hodisalarini chetlab o'tadi — bu test haqiqiy tugma bosishlari bilan yozadi."""
    page.goto(server + "#chat")
    page.wait_for_selector("#msg")
    page.click("#msg")
    page.keyboard.type("salom JARVIS")
    assert page.input_value("#msg") == "salom JARVIS"
    page.keyboard.press("Enter")
    page.wait_for_selector(".msg.user >> text=salom JARVIS")
    # Har bir bo'limdagi birinchi matn maydoniga yozib ko'rish
    ids = page.evaluate("SECTIONS.map(s => s[0])")
    blocked = []
    for sid in ids:
        page.goto(server + "#" + sid)
        page.wait_for_timeout(250)
        inp = page.locator("#view input[type=text]:visible, #view input:not([type]):visible, #view textarea:visible").first
        if inp.count() == 0:
            continue
        inp.click()
        inp.press("Control+End")
        before = inp.input_value()
        page.keyboard.type("ab")
        if inp.input_value() != before + "ab":
            blocked.append(sid)
    assert not blocked, f"Yozib bo'lmaydigan bo'limlar: {blocked}"


def test_guides_and_secret_form(server, page):
    page.goto(server + "#telegram")
    page.wait_for_selector(".guide[open] .gsec input[type=password]")
    assert "BotFather" in page.text_content(".guide")
    page.goto(server + "#pos")
    page.wait_for_selector(".guide >> text=YesPOS")


# ---------------- 3D Brain / Graph Explorer / Memory Explorer ----------------
def _seed(core):
    for i, t in enumerate(["Mango Market narxlari dushanba yangilanadi", "YesPOS hisoboti har kuni soat 9 da",
                           "Instagram Reels rejasi: chegirma haftaligi", "Python API xatosi: timeout 30 s"]):
        core.connector.ingest(t, project="mango" if i < 2 else None)
    core.audit.error("pos", "timeout")
    core.kgraph.rebuild()


def test_brain_mode_live_and_regions(server, page, core):
    _seed(core)
    page.goto(server + "#brain")
    page.wait_for_selector("#stage canvas", timeout=20000)
    page.wait_for_selector(".reg[data-reg=memory]")
    assert page.text_content(".live-badge").strip() in ("● LIVE", "● ulanmoqda…")
    page.wait_for_function("document.querySelector('.live-badge').textContent.includes('LIVE')", timeout=10000)
    # Hududni bosish — haqiqiy modul ma'lumoti
    page.click(".reg[data-reg=memory]")
    page.wait_for_selector("#ingraph")
    assert "Memory Center" in page.text_content("#side") and "xotiralar" in page.text_content("#side")
    # Haqiqiy backend hodisasi Neural Activity jurnaliga yetib boradi
    core.memory.add("E2E jonli hodisa sinovi xotirasi", "long_term")
    page.goto(server + "#neural")
    page.wait_for_selector("#nlog")
    page.wait_for_function("document.querySelector('#nlog').textContent.includes('Yangi xotira saqlandi')", timeout=10000)
    assert not page.errors, page.errors


def test_graph_mode_switch_keeps_selection(server, page, core):
    _seed(core)
    page.goto(server + "#graph")
    page.wait_for_function("document.querySelector('#gcount') && document.querySelector('#gcount').textContent.includes(\"Ko'rsatilmoqda\")", timeout=20000)
    total = int(page.evaluate("document.querySelector('#gcount b').textContent"))
    assert total >= 4
    # Tugunni dasturiy tanlash (WebGL'da sichqoncha nuqtasini taxmin qilmaslik uchun) — batafsil panel ochiladi
    nid = page.evaluate("[...window.JARVIS_VIZ.items].find(v => v.select && v.nodes && v.nodes.length).nodes.find(n => n.type==='memory').id")
    page.evaluate(f"[...window.JARVIS_VIZ.items].find(v => v.select && v.nodes).select({nid})")
    page.wait_for_selector("#gdetail .detail")
    assert "Aloqalar" in page.text_content("#gdetail")
    # 3D rejimga o'tish va qaytish — tanlangan tugun saqlanadi
    page.click("#to3d")
    page.wait_for_selector("#ingraph", timeout=20000)                      # 3D'da tegishli hudud (Memory Center) ochildi
    assert "Memory Center" in page.text_content("#side")
    page.click("[data-mode=graph]")
    page.wait_for_selector("#gdetail .detail", timeout=20000)
    assert page.evaluate("BrainState.selected.id") == nid
    # Filtr: faqat projects
    page.evaluate("document.querySelectorAll('[data-cat]').forEach(x => x.checked = x.dataset.cat === 'projects')")
    page.click("#gapply")
    page.wait_for_function("document.querySelector('#gcount').textContent.includes(\"Ko'rsatilmoqda\")")
    cats = page.evaluate("[...new Set([...window.JARVIS_VIZ.items].find(v => v.nodes).nodes.map(n => n.cat))]")
    assert cats == ["projects"]
    svg = page.evaluate("[...window.JARVIS_VIZ.items].find(v => v.exportSVG).exportSVG()")
    assert svg.startswith("<svg") and "<circle" in svg
    assert not page.errors, page.errors


def test_offline_badge_and_low_quality(server, page, core):
    page.route("**/api/events/stream**", lambda r: r.abort())
    page.goto(server + "#brain")
    page.wait_for_function("document.querySelector('.live-badge').textContent.includes('OFFLINE')", timeout=15000)
    assert "OFFLINE" in page.text_content("#foot")
    page.select_option("#qual", "low")
    page.wait_for_selector("#stage canvas", timeout=20000)
    assert page.evaluate("BrainState.quality") == "low"
    page.errors[:] = [e for e in page.errors if "events/stream" not in e and "ERR_FAILED" not in e]
    assert not page.errors, page.errors


def test_memory_explorer_edit_and_ingest(server, page, core):
    m = core.memory.add("Ish vaqti 9:00-18:00", "working", title="Ish vaqti")
    page.goto(server + "#memx")
    page.wait_for_selector("[data-k=working]")
    page.click("[data-k=working]")
    page.wait_for_selector(f"tr[data-m='{m['id']}']")
    page.click(f"tr[data-m='{m['id']}']")
    page.wait_for_selector("#ec")
    page.fill("#et", "Yangi ish vaqti")
    page.click("#esv")
    page.wait_for_selector("#emsg .ok")
    assert core.memory.get(m["id"])["title"] == "Yangi ish vaqti"
    page.click("summary:has-text('Yangi ma')")
    page.fill("#nc", "Ish vaqti 9:00-18:00")
    page.click("#nan")
    page.wait_for_selector("#nres .small")
    page.fill("#nc", "Ombor har shanba soat 10 da ochiladi")
    page.click("#nsv")
    page.wait_for_selector("#nres .ok")
    assert not page.errors, page.errors
