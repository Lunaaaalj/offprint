"""The equation corpus (#12): LaTeX written for these tests, covering what papers really use.

A plain module, not a fixture directory, because no paper is reproduced here. Each entry is
`(kind, latex)`. `kind` groups the contact sheet, and `inline` entries render in text style.
"""

CORPUS: tuple[tuple[str, str], ...] = (
    # Fractions and roots.
    ("fraction", r"\frac{a+b}{c+d} = \frac{1}{2}"),
    ("fraction", r"\frac{1}{1 + \frac{1}{1 + \frac{1}{x}}}"),
    ("fraction", r"x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}"),
    ("fraction", r"\binom{n}{k} = \frac{n!}{k!\,(n-k)!}"),
    ("fraction", r"\sqrt[3]{\frac{x^3 + y^3}{\sqrt{z}}}"),
    # Sums, integrals and limits.
    ("sum", r"\sum_{i=1}^{n} i^2 = \frac{n(n+1)(2n+1)}{6}"),
    ("sum", r"\int_{-\infty}^{\infty} e^{-x^2}\,dx = \sqrt{\pi}"),
    ("sum", r"\prod_{p\ \mathrm{prime}} \frac{1}{1 - p^{-s}} = \zeta(s)"),
    ("sum", r"\lim_{n \to \infty} \left(1 + \frac{1}{n}\right)^{n} = e"),
    (
        "sum",
        r"\oint_{\partial\Omega} \mathbf{F} \cdot d\mathbf{S}"
        r" = \iiint_{\Omega} \nabla \cdot \mathbf{F}\,dV",
    ),
    ("sum", r"\mathbb{E}\left[\sum_{t=0}^{\infty} \gamma^{t} r_t \,\middle|\, s_0 = s\right]"),
    # Matrices.
    ("matrix", r"A = \begin{pmatrix} a_{11} & a_{12} \\ a_{21} & a_{22} \end{pmatrix}"),
    (
        "matrix",
        r"\det \begin{vmatrix} 1 & x & x^2 \\ 1 & y & y^2 \\ 1 & z & z^2 \end{vmatrix}"
        r" = (y-x)(z-x)(z-y)",
    ),
    (
        "matrix",
        r"\begin{bmatrix} \cos\theta & -\sin\theta \\ \sin\theta & \cos\theta \end{bmatrix}"
        r"\begin{bmatrix} x \\ y \end{bmatrix}",
    ),
    (
        "matrix",
        r"I_n = \begin{pmatrix} 1 & 0 & \cdots & 0 \\ 0 & 1 & \cdots & 0 \\"
        r" \vdots & \vdots & \ddots & \vdots \\ 0 & 0 & \cdots & 1 \end{pmatrix}",
    ),
    ("matrix", r"\left[\begin{array}{cc|c} 1 & 2 & 3 \\ 4 & 5 & 6 \end{array}\right]"),
    # Cases.
    ("cases", r"|x| = \begin{cases} x & \text{if } x \ge 0 \\ -x & \text{otherwise} \end{cases}"),
    (
        "cases",
        r"f(n) = \begin{cases} n/2 & n \equiv 0 \pmod 2 \\ 3n + 1 & n \equiv 1 \pmod 2"
        r" \end{cases}",
    ),
    (
        "cases",
        r"\mathbb{1}_{A}(x) = \left\{\begin{array}{ll} 1, & x \in A \\ 0, & x \notin A"
        r" \end{array}\right.",
    ),
    # Aligned systems.
    (
        "aligned",
        r"\begin{aligned} (a+b)^2 &= a^2 + 2ab + b^2 \\ (a-b)^2 &= a^2 - 2ab + b^2"
        r" \end{aligned}",
    ),
    (
        "aligned",
        r"\begin{align} \nabla \cdot \mathbf{E} &= \frac{\rho}{\varepsilon_0} \\"
        r" \nabla \times \mathbf{B} &= \mu_0 \mathbf{J} + \mu_0 \varepsilon_0"
        r" \frac{\partial \mathbf{E}}{\partial t} \end{align}",
    ),
    ("aligned", r"\begin{gather} x + y = 1 \\ x - y = 3 \end{gather}"),
    (
        "aligned",
        r"\begin{equation} \begin{split} L(\theta) &= \sum_i \log p(x_i \mid \theta) \\"
        r" &\quad - \lambda \lVert \theta \rVert_2^2 \end{split} \end{equation}",
    ),
    ("aligned", r"\begin{multline} a + b + c + d + e \\ = f + g + h \end{multline}"),
    # Symbols, accents and fonts that papers lean on.
    ("symbols", r"\hat{\beta} = \arg\min_{\beta} \|y - X\beta\|_2^2 + \lambda \|\beta\|_1"),
    (
        "symbols",
        r"\mathcal{L}(\tilde{x}, \bar{y}) \leq \mathfrak{g} \quad \forall x \in \mathbb{R}",
    ),
    ("symbols", r"\underbrace{a + \cdots + a}_{n\ \text{times}} = \overline{n a}"),
    ("symbols", r"X \sim \mathcal{N}(\mu, \sigma^2) \implies \Pr[X > \mu] = \tfrac{1}{2}"),
    ("symbols", r"\frac{\partial^2 u}{\partial t^2} = c^2 \nabla^2 u"),
    # Inline math, set in text style and aligned on the baseline.
    ("inline", r"x^2 + y^2 = z^2"),
    ("inline", r"\frac{a}{b}"),
    ("inline", r"\sum_{i=1}^n x_i"),
    ("inline", r"\int_0^1 f(x)\,dx"),
    ("inline", r"\sqrt{2}"),
    ("inline", r"y_{t+1} = g(y_t)"),
    ("inline", r"\mathbf{w}^\top \mathbf{x}"),
)

DISPLAY = tuple(latex for kind, latex in CORPUS if kind != "inline")
INLINE = tuple(latex for kind, latex in CORPUS if kind == "inline")
