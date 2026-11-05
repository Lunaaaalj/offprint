"""Draw the corpus through the real renderer and CSS.

Run `PYTHONPATH=tests uv run python tests/math_contact_sheet.py OUT`. Not a test: it's how
docs/equations-contact-sheet.png is made, at a 300 ppi type size, in two columns. Inline formulas
sit in a sentence with a red rule on the text baseline, so one that left the baseline would show.
"""

import base64
import sys
from importlib.resources import files
from pathlib import Path

from math_corpus import CORPUS

from offprint.browser import chromium_page
from offprint.equations import MathRequest, MathSettings, mathjax_session
from offprint.ir import MathBox, MathInline
from offprint.render.epub.xhtml import RenderContext, render_runs

FONT_PX = 50
PAGE = """<!DOCTYPE html><html><head><style>
{css}
body {{ margin: 0; background: white; color: black; font: {font}px/1.5 Georgia, serif; }}
main {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0 60px; padding: 40px; width: 2264px; }}
section {{ border-top: 1px solid #bbb; padding: 14px 0 6px; overflow: hidden; }}
h2 {{ font: 22px/1 sans-serif; color: #555; margin: 0 0 8px; }}
p.line {{ margin: 0; text-indent: 0; white-space: nowrap;
  background: linear-gradient(#c33, #c33) 0 var(--baseline, 0) / 100% 1px no-repeat; }}
</style></head><body><main>{body}</main></body></html>"""


def main(out: Path) -> None:
    settings = MathSettings()
    rendered = {}
    with mathjax_session(settings) as session:
        session.set_preamble("")
        for kind, latex in CORPUS:
            rendered[kind, latex] = session.render(MathRequest(latex, kind != "inline"))

    sections = []
    for index, ((kind, latex), image) in enumerate(rendered.items(), start=1):
        data = base64.b64encode(image.png).decode()
        src = f"data:image/png;base64,{data}"
        ctx = RenderContext(
            anchors={},
            cite_hrefs={},
            image_href=lambda _asset, _gray, src=src: src,
            math_boxes={"a": image.box},
        )
        inline = render_runs((MathInline("", latex, "a"),), ctx)
        if kind == "inline":
            content = f'<p class="line">Text <i>x</i> {inline} text.</p>'
        else:
            content = f'<div class="equation">{_display(src, latex, image.box)}</div>'
        sections.append(f"<section><h2>{index}. {kind}</h2>{content}</section>")

    css = (files("offprint.render.epub") / "kindle.css").read_text()
    page_html = PAGE.format(css=css, font=FONT_PX, body="".join(sections))
    with chromium_page(2344, 1000) as page:
        page.set_content(page_html)
        page.evaluate(
            """() => {
              for (const line of document.querySelectorAll('p.line')) {
                const probe = document.createElement('span');
                probe.style.cssText = 'display:inline-block;width:0;height:0';
                line.prepend(probe);
                const y = probe.getBoundingClientRect().bottom;
                line.style.setProperty('--baseline', `${y - line.getBoundingClientRect().top}px`);
                probe.remove();
              }
            }"""
        )
        out.write_bytes(page.screenshot(full_page=True))
    print(f"{len(rendered)} of {len(CORPUS)} formulas, {out}")


def _display(src: str, latex: str, box: MathBox) -> str:
    return f'<img class="math-display" src="{src}" alt="" style="width:{box.width:.3f}em"/>'


if __name__ == "__main__":
    main(Path(sys.argv[1]))
