"""Reflow a two-column Frontiers PDF into clean HTML for EPUB/Kindle.

PROTOTYPE. This is the throwaway script that produced the first EPUB. It mixes
layout heuristics for the Frontiers template with generic cleanup steps.
offprint's job is to pull these apart (see ../README.md and the GitHub issues).

usage: python -I convert.py paper.pdf OUTDIR   ->  OUTDIR/book.html + OUTDIR/img/
"""
import re, sys, html, os
import pymupdf as fitz

SRC, OUT = sys.argv[1], sys.argv[2]
os.makedirs(os.path.join(OUT, "img"), exist_ok=True)
doc = fitz.open(SRC)

LIG = {"¸S": "Ş", "¸s": "ş", "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}
MIDX = 297.5
COLS = {"L": (49, 291), "R": (305, 546.5), "F": (49, 546.5)}
TOP, BOT = 50, 795

def clean(t):
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffe\uffff]", "", t)
    for a, b in LIG.items():
        t = t.replace(a, b)
    return t

def col_of(r):
    if r[0] < MIDX - 20 and r[2] > MIDX + 20:
        return "F"
    return "L" if (r[0] + r[2]) / 2 < MIDX else "R"

def spans_html(lines):
    """Lines (list of span lists) -> inline HTML with dehyphenation."""
    out = ""
    for i, spans in enumerate(lines):
        seg = ""
        for s in spans:
            t = clean(s["text"])
            t = re.sub(r"\s+", " ", t)
            if not t:
                continue
            e = html.escape(t, quote=False)
            f = s["font"]
            if s["flags"] & 1 and t.strip():
                e = f"<sup>{e.strip()}</sup>"
            elif ("It" in f or "Italic" in f) and t.strip():
                e = f"<i>{e}</i>"
            elif "Bold" in f and t.strip():
                e = f"<b>{e}</b>"
            seg += e
        seg = seg.strip()
        if not seg:
            continue
        if out.endswith("-") and re.match(r"[a-z]", re.sub(r"<[^>]+>", "", seg)[:1] or "") \
                and not out.endswith(" -"):
            out = out[:-1] + seg
        else:
            out = (out + " " + seg) if out else seg
    out = out.replace("</i> <i>", " ").replace("</i><i>", "").replace("</b> <b>", " ")
    return re.sub(r"\s{2,}", " ", out).strip()

def plain(h):
    return html.unescape(re.sub(r"<[^>]+>", "", h))

def render(page, rect, name, zoom=4, gray=False):
    pix = page.get_pixmap(clip=rect, matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY if gray else fitz.csRGB)
    path = f"img/{name}.png"
    pix.save(os.path.join(OUT, path))
    return path

items = []          # stream of (kind, payload)
pending_table = None
eqn = 0

def flush_table():
    global pending_table
    if pending_table:
        items.append(("table", pending_table))
        pending_table = None

for pno, page in enumerate(doc):
    W = page.rect.width
    d = page.get_text("dict", flags=fitz.TEXTFLAGS_DICT | fitz.TEXT_IGNORE_ACTUALTEXT)
    blocks = [b for b in d["blocks"] if b["type"] == 0 and b["lines"] and b["lines"][0]["spans"]]
    elems = []   # dicts with col, y0, y1, kind, html/...

    # merge fragmented caption blocks (MuseoSans-700 pieces that touch each other)
    capb = [b for b in blocks if b["lines"][0]["spans"][0]["font"].startswith(("MuseoSans-700", "MuseoSans-300"))
            and b["lines"][0]["spans"][0]["size"] < 8 and pno > 0]
    def regroup(a):
        spans = [s for l in a["lines"] for s in l["spans"]]
        spans.sort(key=lambda s: (s["bbox"][1] + s["bbox"][3]) / 2)
        lines, cur = [], []
        for sp in spans:
            if cur and abs((sp["bbox"][1] + sp["bbox"][3]) / 2 - (cur[0]["bbox"][1] + cur[0]["bbox"][3]) / 2) > 2.5:
                lines.append(cur); cur = []
            cur.append(sp)
        lines.append(cur)
        a["lines"] = [dict(spans=sorted(l, key=lambda s: s["bbox"][0]), bbox=fitz.Rect(l[0]["bbox"]) | l[-1]["bbox"]) for l in lines]
    for a in capb:
        regroup(a)
    merged = True
    while merged:
        merged = False
        for a in capb:
            for c in capb:
                if a is not c and (fitz.Rect(a["bbox"]) + (-2, -2, 2, 2)).intersects(fitz.Rect(c["bbox"])):
                    spans = [s for l in a["lines"] + c["lines"] for s in l["spans"]]
                    spans.sort(key=lambda s: (s["bbox"][1] + s["bbox"][3]) / 2)
                    lines, cur = [], []
                    for sp in spans:
                        if cur and abs((sp["bbox"][1] + sp["bbox"][3]) / 2 - (cur[0]["bbox"][1] + cur[0]["bbox"][3]) / 2) > 2.5:
                            lines.append(cur); cur = []
                        cur.append(sp)
                    lines.append(cur)
                    lines = [sorted(l, key=lambda s: s["bbox"][0]) for l in lines]
                    a["lines"] = [dict(spans=l, bbox=fitz.Rect(l[0]["bbox"]) | l[-1]["bbox"]) for l in lines]
                    a["bbox"] = tuple(fitz.Rect(a["bbox"]) | c["bbox"])
                    capb.remove(c); blocks.remove(c)
                    merged = True
                    break
            if merged:
                break

    # --- tables
    tabs = []
    body9 = [fitz.Rect(b["bbox"]) for b in blocks
             if b["lines"][0]["spans"][0]["font"].startswith("MinionPro") and b["lines"][0]["spans"][0]["size"] >= 8.5
             and len(b["lines"]) >= 3]
    class _Row:
        def __init__(self, cells): self.cells = cells
    class _Tab:
        def __init__(self, bbox, rows): self.bbox, self.rows = bbox, rows
    for t in page.find_tables().tables:
        tr = fitz.Rect(t.bbox)
        if tr.width > 300 and any((tr & br).get_area() > 0.6 * br.get_area() for br in body9):
            # detection swallowed the neighbouring text column: keep only the side without body text
            left_has_text = any((tr & br).get_area() > 0.6 * br.get_area() and br.x1 < MIDX for br in body9)
            keep = (lambda c: c[0] >= MIDX - 5) if left_has_text else (lambda c: c[2] <= MIDX + 5)
            rows = [_Row([c if (c is not None and keep(c)) else None for c in row.cells]) for row in t.rows]
            xs = [c for row in rows for c in row.cells if c]
            if xs:
                bb = fitz.Rect(min(c[0] for c in xs), tr.y0, max(c[2] for c in xs), tr.y1)
                tabs.append(_Tab(tuple(bb), rows))
        else:
            tabs.append(t)
    tab_rects = [fitz.Rect(t.bbox) for t in tabs]

    # --- captions
    caps = []
    for b in blocks:
        ls = ["".join(s["text"] for s in l["spans"] if s["font"].startswith("MuseoSans")) for l in b["lines"]]
        txt = re.sub(r"\s+", " ", clean(" ".join(x for x in ls if x.strip()))).strip()
        txt = re.sub(r"^F\s*I\s*G\s*U\s*R\s*E", "FIGURE", txt)
        if re.match(r"(FIGURE|TABLE)\s+\d+", txt):
            caps.append((b, txt))

    used = set()
    # figures: caption below the figure
    body_like = []
    for b in blocks:
        f0 = b["lines"][0]["spans"][0]
        if f0["font"].startswith(("MinionPro", "MuseoSans-500", "MuseoSans-300")) and b["bbox"][1] > TOP and b["bbox"][3] < BOT:
            if not any(fitz.Rect(b["bbox"]).intersects(tr) for tr in tab_rects):
                body_like.append(b)
    for b, txt in caps:
        used.add(id(b))
        r = fitz.Rect(b["bbox"])
        if txt.startswith("TABLE"):
            # attach to table below
            below = [t for t in tabs if t.bbox[1] >= r.y1 - 2 and t.bbox[0] <= r.x0 + 20 and t.bbox[2] > r.x0 + 20]
            below.sort(key=lambda t: t.bbox[1] - r.y1)
            m = re.match(r"TABLE\s+(\d+)\s*(.*)", txt)
            elems.append(dict(col=col_of(below[0].bbox) if below else col_of(r), y0=r.y0, y1=r.y1,
                              kind="tcap", num=m.group(1), text=m.group(2)))
            continue
        # FIGURE: region above caption
        drawings = [fitz.Rect(x["rect"]) for x in page.get_drawings()]
        imgs = [fitz.Rect(x["bbox"]) for x in page.get_image_info()]
        graph = [g for g in drawings + imgs if g.y1 <= r.y0 + 1 and g.y0 >= TOP and g.width < W]
        # bound above by nearest body block in same horizontal span
        ccol = col_of(r)
        prev = [bb for bb in body_like if bb["bbox"][3] <= r.y0 - 3 and id(bb) not in used
                and (ccol == "F" or col_of(bb["bbox"]) in (ccol, "F"))]
        capsabove = [fitz.Rect(cb["bbox"]).y1 for cb, _ in caps if cb is not b and cb["bbox"][3] <= r.y0
                     and (ccol == "F" or col_of(cb["bbox"]) in (ccol, "F") or True)
                     and not (cb["bbox"][2] < r.x0 or cb["bbox"][0] > r.x0 + 230)]
        ytop = max([bb["bbox"][3] for bb in prev] + capsabove, default=TOP)
        g2 = [g for g in graph if g.y0 >= ytop - 1 and g.width > 3 and g.height > 3]
        full = any(g.x0 < MIDX - 10 and g.x1 > MIDX + 10 for g in g2)
        if full:
            prev = [bb for bb in body_like if bb["bbox"][3] <= r.y0 - 3]
            ytop = max([bb["bbox"][3] for bb in prev] + capsabove, default=TOP)
            g2 = [g for g in graph if g.y0 >= ytop - 1 and g.width > 3 and g.height > 3]
        col = "F" if full else ccol
        if g2:
            gr = fitz.Rect(g2[0])
            for g in g2[1:]:
                gr |= g
            rect = fitz.Rect(gr.x0 - 2, gr.y0 - 2, gr.x1 + 2, gr.y1 + 2) & page.rect
        else:
            x0, x1 = COLS[col]
            rect = fitz.Rect(x0, ytop + 4, x1, r.y0 - 2)
        m = re.match(r"FIGURE\s+(\d+)\s*(.*)", txt)
        path = render(page, rect, f"fig{m.group(1)}")
        elems.append(dict(col=col, y0=rect.y0, y1=r.y1, kind="fig", num=m.group(1),
                          text=m.group(2), src=path, rect=rect))

    fig_rects = [e["rect"] for e in elems if e["kind"] == "fig"]

    allspans = [s for b in blocks for l in b["lines"] for s in l["spans"] if s["text"].strip()]
    def cell_text(bb):
        if bb is None:
            return "", False
        r = fitz.Rect(bb)
        sp = [s for s in allspans if r.contains(fitz.Point((s["bbox"][0] + s["bbox"][2]) / 2, (s["bbox"][1] + s["bbox"][3]) / 2))]
        if not sp:
            return "", False
        sp.sort(key=lambda s: ((s["bbox"][1] + s["bbox"][3]) / 2, s["bbox"][0]))
        lines, cur = [], []
        for x in sp:
            if cur and abs((x["bbox"][1] + x["bbox"][3]) / 2 - (cur[0]["bbox"][1] + cur[0]["bbox"][3]) / 2) > 2.5:
                lines.append(sorted(cur, key=lambda s: s["bbox"][0])); cur = []
            cur.append(x)
        lines.append(sorted(cur, key=lambda s: s["bbox"][0]))
        return spans_html(lines), all(x["font"].startswith("MuseoSans") for x in sp)
    for t in tabs:
        rows, hdr = [], None
        for row in t.rows:
            cells = [cell_text(c) for c in row.cells]
            texts = [c[0] for c in cells]
            if not any(texts):
                continue
            is_head = all(c[1] for c in cells if c[0])
            if is_head:
                hdr = texts if hdr is None else [(a + " " + b).strip() for a, b in zip(hdr, texts)]
                continue
            refs_tab = hdr is not None and plain(hdr[0]).strip() == "References"
            if rows and (not texts[0] or (refs_tab and not re.search(r"\d{4}[a-z]?\)?\s*$", plain(rows[-1][0])))):
                rows[-1] = [(a + " " + b).strip() for a, b in zip(rows[-1], texts)]
            else:
                rows.append(texts)
        if hdr:
            j = 0
            while j < len(hdr):
                if hdr[j] == "" and len(hdr) > 1:
                    cand = [k for k in (j - 1, j + 1) if 0 <= k < len(hdr) and hdr[k]]
                    if cand:
                        k = min(cand, key=lambda k: sum(1 for r in rows if r[j] and r[k]))
                        for r in rows:
                            r[k] = (r[k] + " " + r[j]).strip() if k < j else (r[j] + " " + r[k]).strip()
                            del r[j]
                        del hdr[j]
                        continue
                j += 1
        elems.append(dict(col=col_of(t.bbox), y0=t.bbox[1], y1=t.bbox[3], kind="tab", rows=rows, header=hdr))

    # --- text blocks
    for b in blocks:
        if id(b) in used:
            continue
        r = fitz.Rect(b["bbox"])
        if r.y1 < TOP or r.y0 > BOT:
            continue
        if any(r.intersects(tr) for tr in tab_rects) or any(r.intersects(fr) for fr in fig_rects):
            continue
        spans = [s for l in b["lines"] for s in l["spans"] if s["text"].strip()]
        if not spans:
            continue
        f0 = spans[0]
        if f0["font"].startswith("Calibri"):
            continue
        if pno == 0 and r.x1 < 200:      # first-page sidebar
            if re.match(r"(CITATION|COPYRIGHT)", clean(f0["text"])):
                elems.append(dict(col="F", y0=900 + r.y0, y1=900 + r.y1, kind="meta",
                                  html=spans_html([l["spans"] for l in b["lines"]])))
            continue
        if pno == 0 and f0["size"] < 6 and not clean(" ".join(s["text"] for s in spans)).startswith("KEYWORDS"):
            continue
        lines = [l["spans"] for l in b["lines"]]
        h = spans_html(lines)
        col = col_of(r)
        font, size = f0["font"], f0["size"]
        kind = "p"
        if font.startswith("MuseoSans-500") and size > 20:
            kind = "h1"
        elif font.startswith("MuseoSans-500") and size >= 13:
            kind = "h2"
        elif font.startswith("MuseoSans-500") and size >= 11.5:
            kind = "h3"
        elif font.startswith("MuseoSans-500") and size >= 10:
            kind = "h4" if pno > 0 else "authors"
        elif font.startswith("MuseoSans-500") and size >= 8.5:
            kind = "h4"
        elif pno == 0 and font.startswith("MuseoSans-300") and size < 8:
            kind = "affil"
        elif pno == 0 and h.startswith("KEYWORDS"):
            kind = "keywords"
        else:
            cx0, cx1 = COLS[col if col != "F" else "L"]
            txt = plain(h)
            has_eqnum = any(re.fullmatch(r"\(\d{1,2}\)", clean(s["text"]).strip()) or
                            re.search(r"\(\d{1,2}\)\s*$", clean("".join(x["text"] for x in l["spans"])))
                            and l["bbox"][2] > cx1 - 4 for l in b["lines"] for s in l["spans"])
            mathfont = any(s["font"].startswith(("MTEX",)) for s in spans)
            centered = r.x0 > cx0 + 12 and len(lines) <= 3 and not txt.startswith("•")
            if txt.strip() == "(Continued)":
                continue
            if (has_eqnum and len(lines) <= 5) or mathfont or (centered and size >= 6.5 and "=" in txt):
                kind = "disp"
        elems.append(dict(col=col, y0=r.y0, y1=r.y1, kind=kind, html=h, size=f0["size"], rect=r))

    # merge display fragments into equation images
    disp = sorted([e for e in elems if e["kind"] == "disp"], key=lambda e: (e["col"], e["y0"]))
    groups = []
    for e in disp:
        if groups and groups[-1][-1]["col"] == e["col"] and e["y0"] - max(x["y1"] for x in groups[-1]) < 8:
            groups[-1].append(e)
        else:
            groups.append([e])
    elems = [e for e in elems if e["kind"] != "disp"]
    for g in groups:
        col = g[0]["col"]
        x0, x1 = COLS[col]
        rect = fitz.Rect(x0, min(e["y0"] for e in g) - 3, x1, max(e["y1"] for e in g) + 3)
        eqn += 1
        elems.append(dict(col=col, y0=rect.y0, y1=rect.y1, kind="eq",
                          src=render(page, rect, f"eq{eqn:03d}", zoom=5, gray=True),
                          alt=plain(" ".join(e["html"] for e in g))))

    # --- reading order: bands separated by full-width elements
    full = sorted([e for e in elems if e["col"] == "F"], key=lambda e: e["y0"])
    cols = [e for e in elems if e["col"] != "F"]
    order, last = [], -1
    for fe in full + [dict(y0=1e9, y1=1e9, sentinel=True)]:
        band = [e for e in cols if last <= (e["y0"] + e["y1"]) / 2 < fe["y0"]]
        order += sorted([e for e in band if e["col"] == "L"], key=lambda e: e["y0"])
        order += sorted([e for e in band if e["col"] == "R"], key=lambda e: e["y0"])
        if not fe.get("sentinel"):
            order.append(fe)
        last = fe["y1"]
    for e in order:
        items.append((e["kind"], e))

# --- post-process stream: tables (captions + continuation), paragraph merging
out = []
i = 0
TERM = re.compile(r"[.:?!]\)?”?$|\.\)$")
def last_para_idx():
    j = len(out) - 1
    while j >= 0 and out[j][0] in ("fig", "table"):
        j -= 1
    return j

cur_table = None
for kind, e in items:
    if kind == "tcap" and e["text"].startswith("(Continued)") and cur_table is not None:
        continue
    if kind == "tcap":
        cur_table = dict(num=e["num"], cap=e["text"], rows=[], header=None)
        out.append(("table", cur_table))
        continue
    if kind == "tab":
        rows = e["rows"]
        hdr = e["header"]
        if cur_table is not None and cur_table["rows"] and hdr and cur_table["header"] == hdr:
            cur_table["rows"] += rows      # continuation with repeated header
        elif cur_table is not None and not cur_table["rows"]:
            cur_table["header"] = hdr
            cur_table["rows"] = rows
        elif cur_table is not None:
            cur_table["rows"] += rows
        else:
            out.append(("table", dict(num="?", cap="", rows=rows, header=hdr)))
        continue
    if kind == "p":
        txt = plain(e["html"])
        if txt.strip() in ("(Continued)",):
            continue
        j = last_para_idx()
        if j >= 0 and out[j][0] == "p":
            prev = plain(out[j][1]["html"])
            first = txt[:1]
            if not TERM.search(prev.strip()) and not txt.startswith("•") and \
                    (first.islower() or (e["size"] >= 8.5 and first not in "•")):
                if prev.endswith("-") and first.islower():
                    out[j][1]["html"] = out[j][1]["html"][:-1] + e["html"]
                else:
                    out[j][1]["html"] += " " + e["html"]
                continue
    out.append((kind, e))

# --- emit HTML
meta = doc.metadata
H = ['<?xml version="1.0" encoding="utf-8"?>', "<!DOCTYPE html>",
     '<html xmlns="http://www.w3.org/1999/xhtml" lang="en"><head><meta charset="utf-8"/>',
     f"<title>{html.escape(meta['title'])}</title>", "</head><body>"]
in_refs = False
for kind, e in out:
    if kind == "h1":
        H.append(f'<h1 class="title">{e["html"]}</h1>')
    elif kind == "authors":
        H.append(f'<div class="authors"><p>{e["html"]}</p></div>')
    elif kind == "affil":
        H.append(f'<div class="affil"><p>{e["html"]}</p></div>')
    elif kind == "keywords":
        H.append(f'<div class="keywords"><p><b>Keywords:</b> {e["html"][8:].strip()}</p></div>')
    elif kind == "meta":
        H.append(f'<div class="meta"><p>{e["html"]}</p></div>')
    elif kind in ("h2", "h3", "h4"):
        in_refs = plain(e["html"]).strip() == "References"
        H.append(f"<{kind}>{e['html']}</{kind}>")
    elif kind == "p":
        t = e["html"]
        cls = ""
        if plain(t).startswith("•"):
            cls = ' class="bullet"'
        elif in_refs:
            cls = ' class="ref"'
        elif e.get("size", 9) < 8:
            cls = ' class="small"'
        H.append(f'<div{cls}><p>{t}</p></div>' if cls else f"<p>{t}</p>")
    elif kind == "eq":
        H.append(f'<div class="eq"><img src="{e["src"]}" alt="{html.escape(e["alt"])}"/></div>')
    elif kind == "fig":
        H.append(f'<div class="figure"><img src="{e["src"]}" alt="Figure {e["num"]}"/>'
                 f'<div class="caption"><p><b>Figure {e["num"]}.</b> {html.escape(e["text"])}</p></div></div>')
    elif kind == "table":
        t = e
        H.append(f'<div class="table"><div class="caption"><p><b>Table {t["num"]}.</b> {html.escape(t["cap"])}</p></div><table>')
        if t["header"]:
            H.append("<thead><tr>" + "".join(f"<th>{c}</th>" for c in t["header"]) + "</tr></thead>")
        H.append("<tbody>")
        for r in t["rows"]:
            if t["header"] and r == t["header"]:
                continue
            if not any(r):
                continue
            H.append("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>")
        H.append("</tbody></table></div>")
H.append("</body></html>")
open(os.path.join(OUT, "book.html"), "w").write("\n".join(H))
print("items:", len(out), "equations:", eqn)
