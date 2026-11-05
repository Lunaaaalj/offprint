"""Turn the IR's LaTeX into images and text (#12). See docs/equations.md."""

from offprint.equations.latex import clean_latex
from offprint.equations.mathjax import engine_fingerprint, mathjax_session
from offprint.equations.model import (
    MathRenderError,
    MathRequest,
    MathSettings,
    RenderedMath,
    TypesetResult,
)
from offprint.equations.simple import simple_math
from offprint.equations.stage import apply_rendered, asset_id, collect_requests, typeset_math

__all__ = [
    "MathRenderError",
    "MathRequest",
    "MathSettings",
    "RenderedMath",
    "TypesetResult",
    "apply_rendered",
    "asset_id",
    "clean_latex",
    "collect_requests",
    "engine_fingerprint",
    "mathjax_session",
    "simple_math",
    "typeset_math",
]
