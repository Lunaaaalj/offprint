"""Generate a 1600x2560 Kindle cover from a paper's metadata and one hero image (prototype).

usage: FONT_DIR=node_modules/@fontsource/literata/files python cover.py hero.png cover.png

What it does (hard-coded for the fixture paper; the real stage reads the IR):
  1. Duotone the hero image (navy -> pale teal) and fade it into the background
     with an elliptical vignette.
  2. Scatter a seeded "network" of nodes/edges around it (the ML motif).
  3. Lay out title / authors / citation in HTML and screenshot it with Chromium.
Publisher logos and branding are deliberately left off.
"""
import math, os, pathlib, random, sys
import numpy as np
from PIL import Image, ImageFilter, ImageOps
from playwright.sync_api import sync_playwright

HERO, OUT = sys.argv[1], sys.argv[2]
FONT_DIR = pathlib.Path(os.environ.get("FONT_DIR", "node_modules/@fontsource/literata/files")).resolve()
W, H = 1600, 2560
BG = np.array([15, 27, 45])          # navy
HI = np.array([214, 236, 232])       # pale teal
META = dict(
    kicker="A REVIEW",
    title="Artificial intelligence techniques for classification of Alzheimer’s disease using neuroimaging data",
    authors="Y. Nibila &amp; M. Sivagami",
    left="Front. Artif. Intell. 9:1748985",
    right="2026 · CC BY 4.0",
)
work = pathlib.Path(OUT).resolve().parent

# 1. duotone + vignette
im = ImageOps.autocontrast(Image.open(HERO).convert("L"), cutoff=0.5)
scale = 1300 / im.width
im = im.resize((1300, int(im.height * scale)), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.0))
a = np.asarray(im, float) / 255
rgb = BG + (HI - BG) * a[..., None] ** 1.15
h, w = a.shape
yy, xx = np.mgrid[0:h, 0:w]
r = np.sqrt(((xx - w / 2) / (w * 0.5)) ** 2 + ((yy - h * 0.47) / (h * 0.52)) ** 2)
m = np.clip((1.0 - r) / 0.28, 0, 1) ** 1.4
Image.fromarray((BG + (rgb - BG) * m[..., None]).astype(np.uint8)).save(work / "_hero.png")

# 2. network motif
random.seed(7)
cx, cy, nodes = 800, 960, []
for _ in range(70):
    ang = random.uniform(0, 2 * math.pi)
    rad = random.uniform(560, 760) if random.random() < 0.75 else random.uniform(380, 560)
    x, y = cx + rad * math.cos(ang) * 0.95, cy + rad * math.sin(ang) * 1.05
    if 60 < x < W - 60 and 230 < y < 1560:
        nodes.append((x, y))
lines = []
for i, (x1, y1) in enumerate(nodes):
    for dist, j in sorted((math.hypot(x1 - x2, y1 - y2), j) for j, (x2, y2) in enumerate(nodes) if j != i)[:2]:
        if dist < 260:
            x2, y2 = nodes[j]
            lines.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}"/>')
dots = []
for k, (x, y) in enumerate(nodes):
    accent = k % 9 == 0
    dots.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{9 if accent else random.choice([4, 5, 6])}" '
                f'fill="{"#E9A23B" if accent else "#9FD3C7"}" opacity="{0.95 if accent else 0.55}"/>')
svg = (f'<svg width="{W}" height="{H}" style="position:absolute;left:0;top:0">'
       f'<g stroke="#9FD3C7" stroke-width="1.6" opacity="0.28">{"".join(lines)}</g>{"".join(dots)}</svg>')

# 3. typography
fonts = "".join(
    f"@font-face{{font-family:L;src:url('file://{FONT_DIR}/literata-latin-{wt}-{st}.woff2');font-weight:{wt};font-style:{st}}}"
    for wt in (400, 700) for st in ("normal", "italic"))
html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{fonts}
html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden;background:#0F1B2D}}
.hero{{position:absolute;left:150px;top:250px;width:1300px}}
.kicker{{position:absolute;top:120px;left:0;right:0;text-align:center;font:600 34px/1 sans-serif;letter-spacing:.32em;color:#E9A23B}}
.rule{{position:absolute;top:178px;left:740px;width:120px;height:3px;background:#E9A23B;opacity:.8}}
h1{{position:absolute;left:130px;right:130px;top:1640px;margin:0;font:700 96px/1.12 L,serif;color:#F4EFE3}}
.authors{{position:absolute;left:130px;right:130px;top:2265px;font:400 50px/1.2 L,serif;color:#F4EFE3}}
.foot{{position:absolute;left:130px;right:130px;bottom:120px;display:flex;justify-content:space-between;
  font:400 30px/1 sans-serif;letter-spacing:.06em;color:#8EA3B5;border-top:2px solid #2B3C52;padding-top:36px}}
</style></head><body><img class="hero" src="_hero.png">{svg}
<div class="kicker">{META['kicker']}</div><div class="rule"></div><h1>{META['title']}</h1>
<div class="authors">{META['authors']}</div><div class="foot"><span>{META['left']}</span><span>{META['right']}</span></div>
</body></html>"""
(work / "_cover.html").write_text(html)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ["CHROME"]) if os.environ.get("CHROME") else p.chromium.launch()
    pg = b.new_page(viewport={"width": W, "height": H})
    pg.goto(f"file://{work / '_cover.html'}")
    pg.wait_for_timeout(800)
    pg.screenshot(path=OUT)
    b.close()
print("wrote", OUT)
