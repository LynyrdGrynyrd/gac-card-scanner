"""axe-core (WCAG 2.0/2.1/2.2 A+AA tags) on every screen + keyboard-only walkthrough + XSS render check.
   GAC_BASE=http://localhost:8775 AXE=/workspace/axe/package/axe.min.js python audits/scripts/a11y_audit.py <admin> <pw> <xss_card_id>"""
import asyncio, os, sys, json
from playwright.async_api import async_playwright
B = os.environ.get("GAC_BASE", "http://localhost:8775"); AXE = open(os.environ.get("AXE", "/workspace/axe/package/axe.min.js")).read()
OUT = os.environ.get("OUT", "audits/raw/a11y.json"); ADM, PW, XSS = sys.argv[1], sys.argv[2], int(sys.argv[3])
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
async def axe(pg, name, res):
    await pg.evaluate(AXE)   # CDP evaluate: not subject to the page CSP
    r = await pg.evaluate("tags => axe.run(document, {runOnly: {type: 'tag', values: tags}, resultTypes: ['violations','incomplete']})", TAGS)
    v = [{"id": x["id"], "impact": x["impact"], "help": x["help"], "n": len(x["nodes"]), "targets": [n["target"] for n in x["nodes"]][:6],
          "summary": x["nodes"][0].get("failureSummary", "")[:300]} for x in r["violations"]]
    inc = [{"id": x["id"], "n": len(x["nodes"])} for x in r["incomplete"]]
    res[name] = {"violations": v, "needs_review": inc}; print(f"{name}: {len(v)} violation types {[(x['id'], x['n']) for x in v]}", flush=True)
async def tabwalk(pg, name, n=60):
    seq = []
    for _ in range(n):
        await pg.keyboard.press("Tab")
        el = await pg.evaluate("""() => { const e = document.activeElement; if (!e || e === document.body) return null; const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
          return {tag: e.tagName, id: e.id, text: (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().slice(0, 40), y: Math.round(r.top + scrollY), x: Math.round(r.left),
                  visible: r.width > 0 && r.height > 0, outline: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0 || cs.boxShadow !== 'none'} }""")
        if el is None: break
        if seq and el == seq[0]: break
        seq.append(el)
    return seq
async def main():
    res, kb = {}, {}
    async with async_playwright() as p:
        b = await p.chromium.launch(); ctx = await b.new_context(viewport={"width": 1280, "height": 860}); pg = await ctx.new_page()
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(B + "/login"); await pg.wait_for_timeout(600); await axe(pg, "login", res); kb["login"] = await tabwalk(pg, "login", 15)
        await pg.fill("#username", "x"); await pg.fill("#password", "wrong-password"); await pg.click("#go"); await pg.wait_for_timeout(500); await axe(pg, "login-error", res)
        await pg.goto(B + "/privacy"); await axe(pg, "privacy", res)
        await pg.goto(B + "/login"); await pg.wait_for_timeout(500); await pg.fill("#username", ADM); await pg.fill("#password", PW)
        await pg.keyboard.press("Enter"); await pg.wait_for_url("**/ui**"); await pg.wait_for_timeout(800)
        kb["login_by_enter"] = True
        for h in ("upload", "queue", f"review/{XSS}", "export", "admin"):
            await pg.goto(B + "/ui#" + h); await pg.reload(); await pg.wait_for_timeout(1500); await axe(pg, h.split("/")[0], res)
            await pg.evaluate("window.scrollTo(0,0); document.activeElement && document.activeElement.blur()"); kb[h.split("/")[0]] = await tabwalk(pg, h)
        xss = await pg.evaluate("window.__xss"); res["_xss_executed"] = bool(xss); print("XSS executed:", bool(xss))
        await pg.goto(B + f"/ui#review/{XSS}"); await pg.reload(); await pg.wait_for_timeout(1200)
        await pg.fill("#first_name", ""); await pg.fill("#emails", "a@b"); await pg.click("#bApprove"); await pg.wait_for_selector("#dlg[open]")
        await axe(pg, "dialog-approve-anyway", res)
        kb["dialog_focus_inside"] = await pg.evaluate("document.querySelector('#dlg').contains(document.activeElement)")
        await pg.keyboard.press("Escape"); await pg.wait_for_timeout(300); kb["dialog_escape_closes"] = not await pg.evaluate("document.querySelector('#dlg').open")
        await pg.wait_for_timeout(300); await axe(pg, "review-with-errors", res)
        # skip link
        await pg.goto(B + "/ui#queue"); await pg.reload(); await pg.wait_for_timeout(1000); await pg.keyboard.press("Tab")
        kb["first_tab_is_skip_link"] = await pg.evaluate("document.activeElement.className") == "skip"
        await pg.keyboard.press("Enter"); await pg.wait_for_timeout(600); kb["skip_link_keeps_view"] = await pg.evaluate("!document.querySelector('#v-queue').hidden"); kb["skip_link_hash"] = pg.url
        # keyboard-only review: J/K/A shortcuts present
        m = await b.new_context(viewport={"width": 360, "height": 780}, is_mobile=True, has_touch=True); mp = await m.new_page()
        await mp.goto(B + "/login"); await mp.wait_for_timeout(500); await mp.fill("#username", ADM); await mp.fill("#password", PW); await mp.click("#go"); await mp.wait_for_url("**/ui**")
        for h in ("upload", "queue", f"review/{XSS}"):
            await mp.goto(B + "/ui#" + h); await mp.reload(); await mp.wait_for_timeout(1200); await axe(mp, "mobile-" + h.split("/")[0], res)
        res["_page_errors"] = errs; await b.close()
    json.dump({"axe": res, "keyboard": kb}, open(OUT, "w"), indent=1); print("saved", OUT)
asyncio.run(main())
