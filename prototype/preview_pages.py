"""Render Kindle-sized page screenshots of an unpacked EPUB chapter (prototype).

usage: EPUB_TEXT_DIR=build/ep/EPUB/text FONT_DIR=node_modules/@fontsource/literata/files \
       python preview_pages.py '[["ch005.xhtml", "div.eq", 3, "k2.png"]]'
Each target is [chapter, css selector or null, nth match (or page index if selector is null), output png].
"""
import os, sys, json, pathlib
from playwright.sync_api import sync_playwright

EP = pathlib.Path(os.environ.get("EPUB_TEXT_DIR", "build/ep/EPUB/text")).resolve()
FONT = str(pathlib.Path(os.environ.get("FONT_DIR", "node_modules/@fontsource/literata/files")).resolve()) + "/literata-latin-{w}-{s}.woff2"
W, H = 412, 549            # CSS px; x3 = 1236x1647 (Kindle Paperwhite 6.8")
TOPBAR, BOTBAR = 30, 30

css = "".join(
    f"@font-face{{font-family:'Bookerly';src:url('file://{FONT.format(w=w, s=s)}');font-weight:{w};font-style:{s};}}"
    for w in (400, 700) for s in ("normal", "italic"))
css += f"""
html{{margin:0;padding:0;background:#fff;}}
body{{font-family:'Bookerly',serif !important;font-size:15.5px;color:#000;
     margin:0 !important;padding:0;height:{H - TOPBAR - BOTBAR}px;
     column-width:{W - 44}px;column-gap:44px;column-fill:auto;
     position:absolute;top:{TOPBAR}px;left:22px;width:{W - 44}px;}}
img{{max-height:{H - TOPBAR - BOTBAR - 60}px;}}
"""

# (chapter, how to choose the page, label)
targets = json.loads(sys.argv[1])
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROME")) if os.environ.get("CHROME") else p.chromium.launch()
    pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=3)
    for ch, selector, nth, out in targets:
        pg.goto(f"file://{EP / ch}")
        pg.add_style_tag(content=css)
        pg.wait_for_timeout(600)
        pages = pg.evaluate("Math.ceil(document.body.scrollWidth / (document.body.clientWidth + 44))")
        if selector:
            idx = pg.evaluate("""([sel, n, w]) => {
                const e = document.querySelectorAll(sel)[n];
                return Math.floor((e.getBoundingClientRect().left - 22 + 5) / (w + 44)); }""",
                              [selector, nth, W - 44])
        else:
            idx = nth
        pg.evaluate(f"document.body.style.left = (22 - {idx} * {W}) + 'px'")
        pg.evaluate("""([W]) => { document.body.style.columnWidth = (W-44)+'px'; }""", [W])
        left = pages - idx - 1
        pct = {"ch001.xhtml": 1, "ch002.xhtml": 4}.get(ch, int(ch[2:5]) * 5)
        pg.evaluate("""([left, pct]) => {
          const mk = (css, txt) => { const d = document.createElement('div'); d.textContent = txt;
            d.style.cssText = 'position:fixed;font:11px Bookerly,serif;color:#444;' + css; document.documentElement.appendChild(d); };
          mk('top:9px;left:0;right:0;text-align:center;', '1:52');
          mk('bottom:9px;left:22px;', left + (left === 1 ? ' page' : ' pages') + ' left in chapter');
          mk('bottom:9px;right:22px;', pct + '%');
        }""", [left, pct])
        pg.wait_for_timeout(200)
        pg.screenshot(path=out)
        print(out, ch, "page", idx + 1, "of", pages)
    b.close()
