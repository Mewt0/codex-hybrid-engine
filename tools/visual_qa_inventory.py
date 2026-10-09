"""Phase 6 Browser/Visual/Functional QA driver for the demo_php inventory.

This drives the real page in a real Chrome through agent-browser (CDP), captures
the three mandated viewports, and records measured results — console errors,
overflow, contrast, touch targets — rather than visual impressions.

It is a *runner*, not a unit test: it starts a PHP dev server, exercises the UI,
and writes docs/visual-qa/visual_qa_result.json.

Usage:
    .venv\\Scripts\\python.exe tools\\visual_qa_inventory.py

Requires: PHP (found via hybrid.quality.checks.php_binary) and agent-browser.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from hybrid.quality.checks import php_binary  # noqa: E402

PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"
SESSION = "hybrid-qa-inventory"
OUT_DIR = REPO_ROOT / "docs" / "visual-qa"
VIEWPORTS = [(1440, 900, "desktop"), (768, 1024, "tablet"), (390, 844, "mobile")]

results: list[dict] = []


def record(name: str, status: str, evidence) -> None:
    if not isinstance(evidence, str):
        evidence = json.dumps(evidence, ensure_ascii=False, indent=2)
    results.append({"check": name, "status": status, "evidence": evidence})
    print(f"[{status:6}] {name}")
    for line in evidence.splitlines()[:12]:
        print(f"          {line}")


def ab(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run agent-browser.

    On Windows the npm shim is `agent-browser.CMD`, which CreateProcess cannot
    execute directly (WinError 2); it must go through cmd.exe.
    """
    env = dict(os.environ, AGENT_BROWSER_SESSION=SESSION)
    executable = shutil.which("agent-browser") or "agent-browser"
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        command = ["cmd", "/c", executable, *args]
    else:
        command = [executable, *args]
    return subprocess.run(
        command, cwd=REPO_ROOT, text=True,
        encoding="utf-8", errors="replace", capture_output=True,
        env=env, timeout=timeout, check=False,
    )


def js(expression: str) -> str:
    proc = ab("eval", expression)
    return (proc.stdout or "").strip()


def js_text(expression: str) -> str:
    """`get text`-style read for expressions returning a plain string.

    `eval` prints JSON, so a bare string comes back quoted and a non-JSON value
    can come back empty; unwrap defensively.
    """
    raw = js(expression)
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw[1:-1]
    return raw


def js_json(expression: str):
    raw = js(expression)
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        raw = json.loads(raw)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"_raw": raw[:800]}


def wait_for_server(deadline: float = 20.0) -> bool:
    end = time.time() + deadline
    while time.time() < end:
        try:
            with urllib.request.urlopen(BASE + "/", timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


def main() -> int:
    php = php_binary()
    if not php:
        record("PHP available", "SKIP", "php_binary() returned None")
        return 1
    record("PHP available", "PASS", php)

    if shutil.which("agent-browser") is None:
        record("agent-browser available", "SKIP", "not on PATH")
        return 1
    record("agent-browser available", "PASS", shutil.which("agent-browser"))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Start from a clean fixture state so quantities are the documented defaults.
    for stale in Path(os.environ.get("TEMP", "/tmp")).glob("codex-hybrid-engine-demo-*"):
        shutil.rmtree(stale, ignore_errors=True)

    server = subprocess.Popen(
        [php, "-S", f"127.0.0.1:{PORT}", "-t", "demo_php"],
        cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_for_server():
            record("PHP dev server", "FAIL", f"{BASE} did not answer within 20s")
            return 1
        record("PHP dev server", "PASS", BASE)

        ab("open", BASE + "/")
        time.sleep(2)
        cards = js_json("document.querySelectorAll('#grid > *').length")
        record("inventory renders item cards", "PASS" if cards == 4 else "FAIL",
               {"cards": cards, "expected": 4})

        # --- three mandated viewports -------------------------------------
        for width, height, label in VIEWPORTS:
            ab("set", "viewport", str(width), str(height))
            time.sleep(0.6)
            shot = OUT_DIR / f"inventory-{label}.png"
            ab("screenshot", str(shot))
            overflow = js_json(
                "JSON.stringify({w:innerWidth,sw:document.documentElement.scrollWidth,"
                "overflow:document.documentElement.scrollWidth>innerWidth+1,"
                "overflowing:[...document.querySelectorAll('body *')]"
                ".filter(e=>e.getBoundingClientRect().right>innerWidth+1).length})"
            )
            ok = shot.exists() and shot.stat().st_size > 0 and not overflow.get("overflow", True)
            record(f"viewport {label} {width}x{height}", "PASS" if ok else "FAIL",
                   {"screenshot": shot.name, "bytes": shot.stat().st_size if shot.exists() else 0, **overflow})

        # --- console and network health -----------------------------------
        errors = (ab("errors").stdout or "").strip()
        console = (ab("console").stdout or "").strip()
        record("no page errors", "PASS" if not errors else "FAIL", errors or "(none)")
        record("console clean", "PASS" if not console else "FAIL", console or "(none)")

        # --- functional: filters ------------------------------------------
        ab("set", "viewport", "1440", "900")
        js("(()=>{const s=document.getElementById('rarity');s.value='epic';"
           "s.dispatchEvent(new Event('change',{bubbles:true}));"
           "document.getElementById('refresh').click();return 'ok'})()")
        time.sleep(1.5)
        epic = js_json("JSON.stringify({cards:document.querySelectorAll('#grid > *').length,"
                       "count:(document.getElementById('item-count')||{}).textContent})")
        record("rarity filter narrows the list", "PASS" if epic.get("cards") == 1 else "FAIL", epic)

        js("(()=>{const s=document.getElementById('rarity');s.value='';"
           "s.dispatchEvent(new Event('change',{bubbles:true}));"
           "const q=document.getElementById('search');q.value='щит';"
           "q.dispatchEvent(new Event('input',{bubbles:true}));"
           "document.getElementById('refresh').click();return 'ok'})()")
        time.sleep(1.5)
        search = js_json("JSON.stringify({cards:document.querySelectorAll('#grid > *').length,"
                         "names:[...document.querySelectorAll('#grid h3,#grid strong,#grid .item-name')]"
                         ".map(e=>e.textContent.trim())})")
        record("search filter narrows the list", "PASS" if search.get("cards") == 1 else "FAIL", search)

        js("(()=>{const q=document.getElementById('search');q.value='zzz-nope';"
           "q.dispatchEvent(new Event('input',{bubbles:true}));"
           "document.getElementById('refresh').click();return 'ok'})()")
        time.sleep(2.5)
        empty_text = js_text("document.getElementById('grid').textContent.trim().slice(0,120)")
        empty_count = js_text("(document.getElementById('item-count')||{}).textContent")
        ab("screenshot", str(OUT_DIR / "inventory-empty-state.png"))
        has_empty_text = "не найдено" in empty_text.lower()
        record("empty state is explicit, not a blank grid", "PASS" if has_empty_text else "FAIL",
               {"grid": empty_text, "count": empty_count})

        # --- functional: equip persists server-side ------------------------
        ab("open", BASE + "/")
        time.sleep(2)
        js("(()=>{const b=[...document.querySelectorAll('#grid button')]"
           ".find(x=>/экипировать/i.test(x.textContent));b.click();return 'clicked'})()")
        time.sleep(2)
        equipped = js_json(
            "fetch('ajax/inventory.php?action=list',{credentials:'same-origin'})"
            ".then(r=>r.json()).then(d=>JSON.stringify({weapon:d.items.find(i=>i.type==='weapon'),"
            "badge:[...document.querySelectorAll('#grid *')].some(e=>/^Экипировано$/.test(e.textContent.trim()))}))"
        )
        weapon = equipped.get("weapon") or {}
        ok = weapon.get("equipped") is True and equipped.get("badge") is True
        ab("screenshot", str(OUT_DIR / "inventory-desktop-equipped.png"))
        record("equip persists to PHP and shows in the UI", "PASS" if ok else "FAIL", equipped)

        # --- idempotency on a fresh consumable ----------------------------
        for stale in Path(os.environ.get("TEMP", "/tmp")).glob("codex-hybrid-engine-demo-*"):
            shutil.rmtree(stale, ignore_errors=True)
        ab("open", BASE + "/")
        time.sleep(2)
        idem = js_json(
            "(async()=>{const csrf=document.querySelector('meta[name=inventory-csrf]').content;"
            "const key=crypto.randomUUID();"
            "const post=async()=>{const b=new URLSearchParams({action:'use',id:'4',request_key:key,csrf:csrf});"
            "const r=await fetch('ajax/inventory.php',{method:'POST',body:b,credentials:'same-origin'});"
            "return {s:r.status,j:await r.json()}};"
            "const a=await post();const c=await post();"
            "return JSON.stringify({first:{s:a.s,replayed:a.j.replayed},"
            "second:{s:c.s,replayed:c.j.replayed},secondMsg:c.j.message})})()"
        )
        ok = (
            idem.get("first", {}).get("replayed") is False
            and idem.get("second", {}).get("replayed") is True
            and idem.get("second", {}).get("s") == 200
        )
        record("replayed request_key is idempotent", "PASS" if ok else "FAIL", idem)

        # --- negative cases ------------------------------------------------
        negatives = js_json(
            "(async()=>{const csrf=document.querySelector('meta[name=inventory-csrf]').content;"
            "const post=async(f)=>{const b=new URLSearchParams(f);"
            "const r=await fetch('ajax/inventory.php',{method:'POST',body:b,credentials:'same-origin'});"
            "return r.status};"
            "return JSON.stringify({"
            "badCsrf:await post({action:'use',id:'4',request_key:'a'.repeat(24),csrf:'wrong'}),"
            "missingItem:await post({action:'use',id:'999',request_key:'b'.repeat(24),csrf}),"
            "useNonConsumable:await post({action:'use',id:'1',request_key:'c'.repeat(24),csrf}),"
            "equipNonEquippable:await post({action:'equip',id:'4',request_key:'d'.repeat(24),csrf})})})()"
        )
        expected = {"badCsrf": 400, "missingItem": 404, "useNonConsumable": 409, "equipNonEquippable": 409}
        ok = all(negatives.get(k) == v for k, v in expected.items())
        record("negative cases return the documented status codes", "PASS" if ok else "FAIL",
               {"observed": negatives, "expected": expected})

        # --- accessibility / design conformance ----------------------------
        ab("set", "viewport", "1440", "900")
        design = js_json(
            "(()=>{const lum=c=>{const m=c.match(/\\d+/g).map(Number).map(v=>{v/=255;"
            "return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)});"
            "return 0.2126*m[0]+0.7152*m[1]+0.0722*m[2]};"
            "const ratio=(a,b)=>{const l1=lum(a),l2=lum(b);"
            "return +((Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05)).toFixed(2)};"
            "const body=getComputedStyle(document.body);"
            "const btn=document.querySelector('#grid button');const bs=getComputedStyle(btn);"
            "const card=document.querySelector('#grid > *');const cs=getComputedStyle(card);"
            "const r=btn.getBoundingClientRect();"
            "const all=[...document.styleSheets].map(ss=>{try{return [...ss.cssRules].map(x=>x.cssText).join(' ')}"
            "catch(e){return ''}}).join(' ');"
            "return JSON.stringify({bodyContrast:ratio(body.color,body.backgroundColor),"
            "buttonContrast:ratio(bs.color,bs.backgroundColor),"
            "touchTarget:{w:Math.round(r.width),h:Math.round(r.height)},"
            "focusVisible:all.includes('focus-visible'),"
            "reducedMotion:all.includes('prefers-reduced-motion'),"
            "bodyBg:body.backgroundColor})})()"
        )
        ok = (
            design.get("bodyContrast", 0) >= 4.5
            and design.get("buttonContrast", 0) >= 4.5
            and design.get("touchTarget", {}).get("h", 0) >= 44
            and design.get("focusVisible") is True
            and design.get("reducedMotion") is True
        )
        record("design/MASTER.md conformance (contrast, 44px, focus, motion)", "PASS" if ok else "FAIL", design)

        ab("close")
    finally:
        server.send_signal(signal.SIGTERM)
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    print(f"\n=== {passed} PASS / {failed} FAIL / {skipped} SKIP / {len(results)} total ===")
    out = OUT_DIR / "visual_qa_result.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"evidence written: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
