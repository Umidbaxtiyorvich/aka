"""Release Gate — yangi kod release'ga tayyormi?

Tekshiruvlar:
  1. lint (ruff)                     — majburiy
  2. dashboard JS sintaksisi (node)  — majburiy, agar --require-frontend; aks holda bajarilmasa INCOMPLETE emas
  3. pytest: butun to'plam (regressiya) + toifalar: unit, integration, api, permissions, errors, frontend
Natija:
  PASS       — hamma majburiy tekshiruv bajarildi va o'tdi
  FAIL       — biror tekshiruv yoki test muvaffaqiyatsiz
  INCOMPLETE — majburiy tekshiruv bajarilmadi (vosita yo'q / testlar skip bo'ldi). Bu PASS EMAS.
Chiqish kodi: 0 PASS, 1 FAIL, 2 INCOMPLETE.

  python scripts/release_gate.py [--require-frontend] [--json-out path]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANDATORY_CATEGORIES = ["unit", "integration", "api", "permissions", "errors"]
ALL_CATEGORIES = MANDATORY_CATEGORIES + ["frontend"]


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def check_lint() -> dict:
    ruff = shutil.which("ruff")
    if not ruff:
        p = run([sys.executable, "-m", "ruff", "--version"])
        if p.returncode != 0:
            return {"name": "lint", "status": "not_run", "detail": "ruff o'rnatilmagan (pip install ruff)"}
        ruff_cmd = [sys.executable, "-m", "ruff"]
    else:
        ruff_cmd = [ruff]
    p = run(ruff_cmd + ["check", "jarvis", "tests", "scripts", "plugins", "--select", "E,F,W", "--ignore", "E501,E701,E702,E731"])
    return {"name": "lint", "status": "passed" if p.returncode == 0 else "failed",
            "detail": (p.stdout + p.stderr).strip()[-2000:] or "toza"}


def check_js() -> dict:
    node = shutil.which("node")
    if not node:
        return {"name": "js_syntax", "status": "not_run", "detail": "Node.js topilmadi"}
    bad = []
    for f in sorted((ROOT / "dashboard").glob("*.js")):
        p = run([node, "--check", str(f)])
        if p.returncode != 0:
            bad.append(f"{f.name}: {p.stderr.strip()[:300]}")
    return {"name": "js_syntax", "status": "failed" if bad else "passed", "detail": "; ".join(bad) or "barcha JS fayllar to'g'ri"}


def run_tests() -> dict:
    junit = Path(tempfile.mkdtemp()) / "junit.xml"
    t0 = time.monotonic()
    p = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}", "-o", "junit_family=xunit1"])
    dur = round(time.monotonic() - t0, 1)
    if not junit.exists():
        return {"name": "tests", "status": "failed", "detail": "pytest natija fayli yaratilmadi: " + (p.stdout + p.stderr)[-1500:],
                "categories": {}, "failures": []}
    cats = {c: {"passed": 0, "failed": 0, "skipped": 0} for c in ALL_CATEGORIES}
    totals = {"passed": 0, "failed": 0, "skipped": 0}
    failures, skips = [], []
    for tc in ET.parse(junit).getroot().iter("testcase"):
        props = {pp.get("name"): pp.get("value") for pp in tc.iter("property")}
        tcats = [c for c in (props.get("categories") or "unit").split(",") if c in cats]
        name = f"{tc.get('classname')}::{tc.get('name')}"
        if tc.find("failure") is not None or tc.find("error") is not None:
            outcome = "failed"
            el = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
            failures.append({"test": name, "message": (el.get("message") or "")[:300]})
        elif tc.find("skipped") is not None:
            outcome = "skipped"
            skips.append({"test": name, "reason": (tc.find("skipped").get("message") or "")[:200]})
        else:
            outcome = "passed"
        totals[outcome] += 1
        for c in tcats:
            cats[c][outcome] += 1
    status = "failed" if totals["failed"] or p.returncode not in (0, 5) else "passed"
    return {"name": "tests", "status": status, "duration_s": dur, "totals": totals, "categories": cats,
            "failures": failures, "skipped": skips, "summary": (p.stdout.strip().splitlines() or [""])[-1]}


def git_info() -> dict:
    if not shutil.which("git"):
        return {}
    sha = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    dirty = bool(run(["git", "status", "--porcelain", "--", "."]).stdout.strip())
    return {"commit": sha, "uncommitted_changes": dirty}


def evaluate(checks: list[dict], tests: dict, require_frontend: bool) -> tuple[str, list[str]]:
    reasons = []
    for c in checks:
        if c["status"] == "failed":
            reasons.append(f"{c['name']}: muvaffaqiyatsiz")
    if tests["status"] == "failed":
        reasons.append(f"testlar: {tests.get('totals', {}).get('failed', '?')} ta muvaffaqiyatsiz")
    if reasons:
        return "FAIL", reasons
    incomplete = []
    for c in checks:
        if c["status"] == "not_run" and (c["name"] == "lint" or require_frontend):
            incomplete.append(f"{c['name']}: bajarilmadi — {c['detail']}")
    needed = MANDATORY_CATEGORIES + (["frontend"] if require_frontend else [])
    for cat in needed:
        if tests["categories"].get(cat, {}).get("passed", 0) == 0:
            incomplete.append(f"'{cat}' toifasida bajarilgan test yo'q")
    return ("INCOMPLETE", incomplete) if incomplete else ("PASS", [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--require-frontend", action="store_true", help="frontend testlari va JS tekshiruvi majburiy")
    ap.add_argument("--json-out", help="hisobot fayli (standart: JARVIS_HOME/release/last.json)")
    a = ap.parse_args()
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    checks = [check_lint(), check_js()]
    tests = run_tests()
    verdict, reasons = evaluate(checks, tests, a.require_frontend)
    report = {"verdict": verdict, "reasons": reasons, "started_at": started,
              "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "require_frontend": a.require_frontend,
              "python": sys.version.split()[0], "platform": sys.platform, "git": git_info(), "checks": checks, "tests": tests}
    if a.json_out:
        out = Path(a.json_out)
    else:
        sys.path.insert(0, str(ROOT))
        from jarvis.config import jarvis_home
        out = jarvis_home() / "release" / "last.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n=== RELEASE GATE: {verdict} ===")
    for c in checks:
        print(f"  [{c['status']:>8}] {c['name']}: {c['detail'].splitlines()[0] if c['detail'] else ''}")
    t = tests.get("totals", {})
    print(f"  [{tests['status']:>8}] testlar: o'tdi {t.get('passed', 0)}, xato {t.get('failed', 0)}, o'tkazib yuborildi {t.get('skipped', 0)}")
    for cat in ALL_CATEGORIES:
        c = tests["categories"].get(cat, {})
        print(f"             {cat:<12} o'tdi {c.get('passed', 0):>3}  xato {c.get('failed', 0):>3}  skip {c.get('skipped', 0):>3}")
    for f in tests.get("failures", [])[:20]:
        print(f"  XATO: {f['test']} — {f['message']}")
    for r in reasons:
        print(f"  SABAB: {r}")
    print(f"Hisobot: {out}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"## Release gate: {verdict}\n\n| Toifa | O'tdi | Xato | Skip |\n|---|---|---|---|\n")
            for cat in ALL_CATEGORIES:
                c = tests["categories"].get(cat, {})
                f.write(f"| {cat} | {c.get('passed', 0)} | {c.get('failed', 0)} | {c.get('skipped', 0)} |\n")
            f.write("\n" + "\n".join(f"- {r}" for r in reasons) + "\n")
    return {"PASS": 0, "FAIL": 1, "INCOMPLETE": 2}[verdict]


if __name__ == "__main__":
    sys.exit(main())
