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
    # Pastki izoh 3D sahna yuklangandan keyin chiziladi (sekin CI'da badge'dan kechroq) — uni ham kutamiz
    page.wait_for_function("(document.querySelector('#foot') || {}).textContent && document.querySelector('#foot').textContent.includes('OFFLINE')", timeout=20000)
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


def test_connection_center_and_super_brain(server, page, core, tmp_path):
    ws = tmp_path / "pos_export"
    ws.mkdir()
    core.settings.allowed_read_dirs = [str(ws)]
    import datetime
    today = datetime.date.today().isoformat()
    (ws / "savdo.csv").write_text(f"Sana;Mahsulot;Soni;Summa;Do'kon\n{today};Non;2;6000;Chilonzor\n", encoding="utf-8")
    page.goto(server + "#connections")
    page.click(".tabs a[data-t=add]")
    page.wait_for_selector("#preset")
    page.select_option("#preset", "files")
    page.fill("#cname", "POS eksport")
    page.fill("#f_path", str(ws))
    page.click("#csave")
    page.wait_for_selector("#cmsg .pill.ok")
    conn = core.integrations.list()[0]
    assert conn["status"] == "connected" and conn["adapter"] == "files"
    page.wait_for_selector(f"button[data-a=discover][data-id='{conn['id']}']")
    page.click(f"button[data-a=discover][data-id='{conn['id']}']")
    page.wait_for_timeout(600)
    page.click(f"button[data-a=sync][data-id='{conn['id']}']")
    page.wait_for_function(f"document.querySelector('button[data-a=open][data-id=\"{conn['id']}\"]')")
    page.wait_for_timeout(600)
    assert core.integrations.get(conn["id"])["records"] == 1
    page.click(f"button[data-a=open][data-id='{conn['id']}']")
    page.wait_for_selector("#rgo")
    page.click("#rgo")
    page.wait_for_selector("#rres td:has-text('Non')")
    page.click(".tabs a[data-t=credentials]")
    page.wait_for_selector("text=Credential Vault")
    page.click(".tabs a[data-t=history]")
    page.wait_for_selector("text=Sinxronlash tarixi")
    page.goto(server + "#superbrain")
    page.wait_for_selector("#aq")
    page.fill("#aq", "Bugungi savdo qancha?")
    page.click("#ago")
    page.wait_for_selector("#ares:has-text('Manba')")
    model_id = page.eval_on_selector("[data-tr=pos]", "s => s.options[1].value")
    page.select_option("[data-tr=pos]", model_id)
    page.click("#trsave")
    page.wait_for_selector("#trmsg .ok")
    assert core.settings.ai_task_routes.get("pos") == model_id
    assert not page.errors, page.errors


def test_ai_provider_center_router_and_memory_import(server, page, core, tmp_path):
    import json
    import zipfile
    page.goto(server + "#aihub")
    page.click("[data-addp=lmstudio]")
    page.wait_for_selector("#hpsave")
    page.fill("#hpurl", "http://127.0.0.1:9/v1")            # hech narsa tinglamaydigan port — halol "ulanib bo'lmadi"
    page.fill("#hpmodel", "qwen2.5-7b-instruct")
    page.click("#hpsave")
    page.wait_for_selector("#hpmsg:has-text('Ulanib bo')")
    assert core.ai_hub.get("lmstudio")["status"] == "connection_failed"
    page.click("#hpdone")
    page.wait_for_selector("button[data-h=verify][data-id=lmstudio]")
    page.goto(server + "#smartrouter")
    page.wait_for_selector("#srs")
    page.select_option("#srs", "free_only")
    page.fill("#srreq", "0.05")
    page.click("#srsave")
    page.wait_for_selector("#srmsg .ok")
    assert core.settings.ai_strategy == "free_only" and core.settings.ai_max_request_cost == 0.05
    page.goto(server + "#models")
    page.wait_for_selector("#mcid")
    page.fill("#mcid", "deepseek-r1-distill")
    page.click("#mcadd")
    page.wait_for_selector("td:has-text('deepseek-r1-distill')")
    conv = {"id": "c1", "title": "Test", "create_time": 1735689600, "current_node": "n1", "mapping": {
        "n0": {"message": None, "parent": None, "children": ["n1"]},
        "n1": {"message": {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["Qaror qildim: bazaga SQLite ishlatamiz."]}, "create_time": 1735689600},
               "parent": "n0", "children": []}}}
    zp = tmp_path / "export.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("conversations.json", json.dumps([conv]))
    page.goto(server + "#memimport")
    page.set_input_files("#mif", str(zp))
    page.click("#miup")
    page.wait_for_selector("[data-mc=decisions]", timeout=15000)
    page.click("[data-mc=decisions]")
    page.wait_for_selector("#miall:not([disabled])")
    page.click("#miall")
    page.wait_for_selector("#mimsg2 .ok")
    assert any("SQLite" in m["content"] and m["source"] == "import:chatgpt" for m in core.memory.list("decision"))
    assert not page.errors, page.errors


def test_mission_control_end_to_end(server, page, core):
    page.goto(server + "#mission")
    page.fill("#mgoal", "fayllarni ko'rsat keyin test")
    page.click("#mgo")
    page.wait_for_selector("#mdet .pill.ok:has-text('Bajarildi')", timeout=30000)
    m = core.missions.list()[0]
    assert m["status"] == "completed" and m["progress"] == 100
    page.wait_for_selector("#mdet:has-text('Hisobot')")
    page.fill("#mgoal", "papkada bajar `mkdir hisobot`")
    page.click("#mgo")
    page.wait_for_selector("#mdet [data-ma=start]")
    page.click("#mdet [data-ma=start]")
    page.wait_for_selector("#mdet:has-text('Tasdiq kutmoqda')", timeout=30000)
    assert core.approvals.list("pending")
    page.goto(server + "#agentcmd")
    page.wait_for_selector("td:has-text('computer')")
    assert not page.errors, page.errors


def test_jarvis3_pages_guardian_simlab_skills(server, page, core):
    page.goto(server + "#guardian")
    page.wait_for_selector("#alsave")
    page.check("[name=alvl][value='1']")
    page.click("#alsave")
    page.wait_for_selector("#almsg .ok")
    assert core.settings.autonomy_level == 1
    page.click("[data-ga=emergency_stop] >> nth=0")
    page.wait_for_function("() => document.querySelector('#gmsg') && document.querySelector('#gmsg').textContent.length > 0")
    assert core.automation_paused
    core.resume_automation()
    page.goto(server + "#simlab")
    page.fill("#ssql", "DELETE FROM audit_log")
    page.click("#sgo")
    page.wait_for_selector("#sres:has-text('production bazasi o')")
    assert core.db.one("SELECT COUNT(*) n FROM audit_log")["n"] > 0
    page.goto(server + "#skills")
    page.fill("#skn", "sozlar_soni")
    page.fill("#skd", "So'zlarni sanaydi")
    page.click("#skgo")
    page.wait_for_selector("[data-skt=sozlar_soni]")
    page.click("[data-skt=sozlar_soni]")
    page.wait_for_selector("#skx_sozlar_soni:has-text('testlar o')")
    page.goto(server + "#office")
    page.wait_for_selector("[data-room=qa]")
    page.click("[data-room=qa]")
    page.wait_for_selector("#odet:has-text('xonasi')")
    assert not page.errors, page.errors


def test_delayed_rerender_does_not_wipe_other_section(server, page, core):
    """Regressiya: BI importidan keyingi kechiktirilgan qayta chizish boshqa bo'limda yozilgan matnni o'chirmasligi kerak."""
    page.goto(server + "#bi")
    page.wait_for_selector("#f")
    page.set_input_files("#f", str(PROJECT_ROOT / "sample_data" / "demo_mahsulotlar.csv"))
    page.click("#up")
    page.wait_for_selector("#o:has-text('rows_ok')")
    page.goto(server + "#dag")
    page.fill("#goal", "fayllarni ko'rsat")
    page.wait_for_timeout(2000)                       # BI'ning 1.5 s dagi qayta chizishi o'tib ketsin
    assert page.input_value("#goal") == "fayllarni ko'rsat"
    assert not page.errors, page.errors


def test_global_command_bar_and_tools_page(server, page, core):
    core.memory.add("Chilonzor filiali soat 9 da ochiladi", "knowledge", source="user")
    page.goto(server + "#settings")
    page.fill("#gcmd", "chilonzor")
    page.wait_for_selector("#gres .gi:has-text('Chilonzor')")
    page.fill("#gcmd", "/holat")
    page.press("#gcmd", "Enter")
    page.wait_for_selector("#gres:has-text('avtonomlik Level')")
    page.goto(server + "#tools")
    page.wait_for_selector("summary:has-text('Tizim holati')")
    page.click("summary:has-text('Tizim holati')")
    page.click("[data-tr='guardian.status']")
    page.wait_for_selector("#to_guardian_status:has-text('checks')")
    assert core.tools.calls()[0]["tool"] == "guardian.status"
    assert not page.errors, page.errors


def test_v13_pages_docs_swarm_computer(server, page, core, tmp_path):
    f = tmp_path / "eslatma.txt"
    f.write_text("JARVIS uchun sinov hujjati. Ombor shanba yopiq.", encoding="utf-8")
    page.goto(server + "#docintel")
    page.set_input_files("#dfile", str(f))
    page.click("#dup")
    page.wait_for_selector("#dres:has-text('So\\'z / bo\\'lak')")
    page.fill("#dq", "ombor")
    page.click("#dfind")
    page.wait_for_selector("#dout:has-text('Ombor')")
    core.memory.add("Ombor kaliti qo'riqchida", "knowledge", source="user")
    page.goto(server + "#swarm")
    page.wait_for_selector("#sgo")
    page.click("#sgo")
    page.wait_for_selector("#sout:has-text('supervisor')")
    assert core.swarm.history()[0]["to_agent"] == "memory_agent"
    page.goto(server + "#computeruse")
    page.wait_for_selector("#cprop")
    page.click("#cprop")
    page.wait_for_selector("#cpmsg:has-text('Tasdiq #')")
    assert core.approvals.list("pending")[0]["action_type"] == "computer_use"
    page.goto(server + "#semantic")
    page.wait_for_selector("text=Semantik xotira")
    assert not page.errors, page.errors
