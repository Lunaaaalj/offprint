"""Create labels, milestones and issues on GitHub from the drafts in this folder.

usage: python issues/publish.py OWNER/REPO [--apply]
Uses `gh api` (REST only). Dry run by default. Skips issues whose title already exists.
"""
import json, pathlib, re, subprocess, sys

repo = sys.argv[1]
apply = "--apply" in sys.argv
here = pathlib.Path(__file__).parent

LABELS = {
    "enhancement": ("a2eeef", "New feature or request"),
    "area:infra": ("ededed", "Packaging, CLI, CI"),
    "area:ir": ("5319e7", "Document intermediate representation"),
    "area:pdf": ("d93f0b", "PDF adapter, profiles and cleanup steps"),
    "area:sources": ("0e8a16", "Source resolver, JATS and LaTeX adapters"),
    "area:render": ("1d76db", "EPUB, cover and equation rendering"),
    "area:qa": ("fbca04", "QA gate, previews, review queue"),
    "area:delivery": ("c5def5", "Send to Kindle, Zotero, editor integrations"),
}
MILESTONES = {
    "M1: Package the prototype": "Port the prototype into a tested package: IR, PDF adapter + profiles, EPUB, QA gate.",
    "M2: Better sources": "Avoid PDF parsing when possible: resolver, JATS, arXiv LaTeX, equation rendering.",
    "M3: Automation": "Hands-off delivery: Send to Kindle, Zotero, editor integration, ML fallback, repair loop.",
}


def gh(*args, data=None):
    cmd = ["gh", "api", *args]
    if data is not None:
        cmd += ["--input", "-"]
    r = subprocess.run(cmd, input=json.dumps(data) if data is not None else None,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"gh api {' '.join(args)} failed: {r.stderr or r.stdout}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def parse(path):
    lines = path.read_text().splitlines()
    title = lines[0].removeprefix("# ").strip()
    meta, i = {}, 1
    while i < len(lines) and (not lines[i].strip() or re.match(r"^(Labels|Milestone|Depends on):", lines[i])):
        if ":" in lines[i]:
            k, v = lines[i].split(":", 1)
            meta[k.strip()] = v.strip()
        i += 1
    body = "\n".join(lines[i:]).strip()
    if "Depends on" in meta:
        body = f"**Depends on:** {meta['Depends on']}\n\n" + body
    body += f"\n\n---\n_Draft: `issues/{path.name}`_"
    labels = [x.strip() for x in meta.get("Labels", "").split(",") if x.strip()]
    return title, labels, meta.get("Milestone"), body


drafts = sorted(p for p in here.glob("[0-9][0-9]-*.md"))
print(f"{len(drafts)} drafts → {repo} ({'APPLY' if apply else 'dry run'})")
if not apply:
    for p in drafts:
        t, l, m, _ = parse(p)
        print(f"  {p.name}: {t}  [{', '.join(l)}]  ({m})")
    raise SystemExit(0)

have = {x["name"] for x in gh(f"repos/{repo}/labels?per_page=100")}
for name, (color, desc) in LABELS.items():
    if name not in have:
        gh(f"repos/{repo}/labels", data={"name": name, "color": color, "description": desc})
ms = {x["title"]: x["number"] for x in gh(f"repos/{repo}/milestones?state=all&per_page=100")}
for title, desc in MILESTONES.items():
    if title not in ms:
        ms[title] = gh(f"repos/{repo}/milestones", data={"title": title, "description": desc})["number"]
existing = {x["title"] for x in gh(f"repos/{repo}/issues?state=all&per_page=100") if "pull_request" not in x}
for p in drafts:
    t, l, m, body = parse(p)
    if t in existing:
        print(f"  skip (exists): {t}")
        continue
    data = {"title": t, "body": body, "labels": l}
    if m:
        data["milestone"] = ms[m]
    r = gh(f"repos/{repo}/issues", data=data)
    print(f"  #{r['number']}: {t}")
