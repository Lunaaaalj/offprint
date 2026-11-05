"""The first chapter: title, authors, affiliations, abstract, keywords, citation and license."""

from collections.abc import Sequence

from offprint.ir import Block, Meta, Paragraph
from offprint.render.epub.xhtml import RenderContext, doi_url, esc, render_blocks, render_runs


def citation_markup(meta: Meta) -> str:
    """Return the citation line built from `meta`, or "" if there's nothing to cite."""
    parts = [esc(meta.journal or "")]
    if meta.year is not None:
        parts.append(f"({meta.year})")
    parts.append(esc(":".join(part for part in (meta.volume, meta.article_id) if part)))
    if meta.doi:
        parts.append(f'doi:<a href="{esc(doi_url(meta.doi))}">{esc(meta.doi)}</a>')
    if meta.arxiv_id:
        parts.append(f"arXiv:{esc(meta.arxiv_id)}")
    return " ".join(part for part in parts if part)


def license_text(meta: Meta) -> str:
    """Return the license statement used in the front matter and in `dc:rights`."""
    if meta.license is None:
        return ""
    holder = f"© {meta.license.holder}. " if meta.license.holder else ""
    return f"{holder}Licensed under {meta.license.spdx}."


def render_front_matter(
    meta: Meta,
    title: str,
    leading: Sequence[Block],
    all_blocks: Sequence[Block],
    ctx: RenderContext,
) -> str:
    """Render the front matter from `meta` and the `leading` blocks before the first section.

    Text the adapter also wrote as blocks wins over `meta`, so nothing appears twice: abstract
    paragraphs replace `meta.abstract`, and a `meta` paragraph replaces the citation line.
    """
    abstract_blocks = [block for block in leading if _has_role(block, "abstract")]
    other_blocks = [block for block in leading if not _has_role(block, "abstract")]
    use_meta_abstract = meta.abstract and not any(_has_role(b, "abstract") for b in all_blocks)

    parts = [f'<h1 class="title">{esc(title)}</h1>']
    if meta.authors:
        names = ", ".join(author.name for author in meta.authors)
        parts.append(f'<p class="authors">{esc(names)}</p>')
    affiliations = dict.fromkeys(a.affiliation for a in meta.authors if a.affiliation)
    parts.extend(f'<p class="affiliation">{esc(text)}</p>' for text in affiliations)

    if abstract_blocks or use_meta_abstract:
        parts.append('<h2 class="abstract-label">Abstract</h2>')
    if abstract_blocks:
        parts.append(render_blocks(abstract_blocks, ctx))
    elif use_meta_abstract:
        parts.append(f'<p class="abstract">{render_runs(meta.abstract, ctx)}</p>')

    if meta.keywords:
        parts.append(f'<p class="keywords"><b>Keywords:</b> {esc(", ".join(meta.keywords))}</p>')
    if other_blocks:
        parts.append(render_blocks(other_blocks, ctx))

    citation = citation_markup(meta)
    if citation and not any(_has_role(block, "meta") for block in leading):
        parts.append(f'<p class="citation">{citation}</p>')
    if meta.license is not None:
        parts.append(f'<p class="license">{esc(license_text(meta))}</p>')
    return "\n".join(parts)


def _has_role(block: Block, role: str) -> bool:
    return isinstance(block, Paragraph) and block.role == role
