#!/usr/bin/env bash
# PROTOTYPE end-to-end build: PDF -> HTML (convert.py) -> EPUB (pandoc).
# usage: prototype/build.sh path/to/paper.pdf [cover.png]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PDF="$1"; COVER="${2:-}"
OUT="${OUT:-build}"
rm -rf "$OUT" && python3 -I "$HERE/convert.py" "$PDF" "$OUT"
cd "$OUT"
python3 -I - <<'PY'
import re
h = open('book.html').read()
# shift headings so numbered sections become EPUB chapters (h2->h1, h3->h2, h4->h3)
for a, b in [('h4', 'h3x'), ('h3', 'h2x'), ('h2', 'h1x')]:
    h = re.sub(rf'<(/?){a}>', rf'<\g<1>{b}>', h)
h = h.replace('h3x', 'h3').replace('h2x', 'h2').replace('h1x', 'h1')
h = re.sub(r'(<div class="affil">.*?</div>\n)<p>', r'\1<div class="abstract-label"><p>Abstract</p></div>\n<p>', h, count=1)
h = h.replace('<div class="meta"><p>CITATION', '<div class="meta"><p><b>Citation:</b>')
h = h.replace('<div class="meta"><p>COPYRIGHT', '<div class="meta"><p><b>Copyright:</b>')
open('book2.html', 'w').write(h)
PY
# NOTE: metadata is hard-coded for the fixture paper; the real pipeline takes it from the IR.
pandoc book2.html -f html -t epub3 -o book.epub --css "$HERE/kindle.css" \
  --toc --toc-depth=2 --split-level=1 --epub-title-page=false \
  ${COVER:+--epub-cover-image="$COVER"} \
  --metadata title="Artificial intelligence techniques for classification of Alzheimer's disease using neuroimaging data: a review" \
  --metadata author="Y. Nibila" --metadata author="M. Sivagami" --metadata lang=en --metadata date=2026-05-18 \
  --metadata rights="CC BY 4.0 — © 2026 Nibila and Sivagami" --metadata publisher="Frontiers in Artificial Intelligence"
mkdir -p ep && (cd ep && unzip -qo ../book.epub)
for f in ep/EPUB/text/*.xhtml; do python3 -c "import sys,xml.dom.minidom as m; m.parse(sys.argv[1])" "$f" || echo "BAD XML $f"; done
echo "wrote $OUT/book.epub"
