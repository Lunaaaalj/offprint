// LaTeX to PNG inside the page: MathJax lays out an SVG, and a canvas rasterises it.
// Loaded after tex-svg-full.js. Each call returns its result, or { error } with TeX's message.
"use strict";

window.offprint = (() => {
  const UNITS_PER_EM = 1000; // MathJax's viewBox unit.
  const PADDING_PX = 3; // Antialiasing can reach past a glyph's box.
  const SIDE_PADDING_PX = 15; // Ink overhangs MathJax's box sideways. Python crops this back.
  const MAX_SIDE_PX = 8000; // Past this a canvas can come back blank.
  // \subequations only groups numbers, and offprint keeps numbers in the IR.
  const BASE_DEFINITIONS = "\\newenvironment{subequations}{}{}";
  // MathJax's fonts have no blackboard digits, and the indicator function is everywhere. This is
  // the old TeX way of drawing one, and it doesn't depend on the machine's fonts.
  const BLACKBOARD_ONE = /\\math(?:bb|bbm|ds)\s*\{\s*1\s*\}/g;
  const DOUBLE_STRUCK_ONE = "\\mathrm{1\\!\\!1}";
  const DEFINITION_MAPS = new Set([
    "new-Command",
    "new-Environment",
    "new-Delimiter",
    "ams-declare-ops",
    "mathtools-paired-delims",
  ]);
  const HANDLER_KINDS = ["macro", "delimiter", "environment", "character"];

  const { handlers } = MathJax.startup.input[0].parseOptions;
  const definitionMaps = [
    ...new Set(
      HANDLER_KINDS.flatMap((kind) => [...handlers.get(kind)._configuration])
        .map(({ item }) => item)
        .filter((map) => DEFINITION_MAPS.has(map.name)),
    ),
  ];
  let saved = [];

  // A formula's \newcommand outlives it in MathJax. Left alone, a formula's meaning would depend
  // on which formulas ran before it, and so on what the cache already held.
  const saveDefinitions = () => {
    saved = definitionMaps.map((map) => new Map(map.map));
  };
  const restoreDefinitions = () => {
    definitionMaps.forEach((map, index) => {
      map.map = new Map(saved[index]);
    });
    MathJax.texReset();
  };

  const svgFor = (latex, display) => {
    const tex = latex.replace(BLACKBOARD_ONE, DOUBLE_STRUCK_ONE);
    const svg = MathJax.tex2svg(tex, { display }).querySelector("svg");
    if (!svg) throw new Error("MathJax produced no SVG");
    return svg;
  };

  // Snap the baseline to a pixel row, so the depth in pixels is exact.
  const fitToPixels = (svg, pxPerEm) => {
    // A tag MathJax set against the page's edge. The stage takes out the ones it can read.
    if (!svg.hasAttribute("viewBox")) throw new Error("the formula needs a page width");
    const [x, y, width, height] = svg.getAttribute("viewBox").split(" ").map(Number);
    const px = (units) => (units * pxPerEm) / UNITS_PER_EM;
    const units = (pixels) => (pixels * UNITS_PER_EM) / pxPerEm;
    const above = Math.ceil(px(-y)) + PADDING_PX;
    const depth = Math.ceil(px(y + height)) + PADDING_PX;
    const wide = Math.ceil(px(width)) + 2 * SIDE_PADDING_PX;
    const box = { width: wide, height: above + depth, depth };
    if (px(width) <= 0 || px(height) <= 0) throw new Error("the formula is empty");
    if (box.width > MAX_SIDE_PX || box.height > MAX_SIDE_PX) {
      throw new Error(`the formula is too large to rasterise (${box.width}x${box.height} px)`);
    }
    const viewBox = [x - units(SIDE_PADDING_PX), -units(above), units(wide), units(box.height)];
    svg.setAttribute("viewBox", viewBox.join(" "));
    svg.setAttribute("width", box.width);
    svg.setAttribute("height", box.height);
    svg.removeAttribute("style");
    return box;
  };

  const rasterise = async (svg, box) => {
    const image = new Image();
    // Rules in arrays and fractions take their stroke from this stylesheet.
    const style = document.createElementNS(svg.namespaceURI, "style");
    style.textContent = MathJax.svgStylesheet().textContent;
    svg.prepend(style);
    const markup = new XMLSerializer().serializeToString(svg);
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = box.width;
    canvas.height = box.height;
    canvas.getContext("2d").drawImage(image, 0, 0);
    return canvas.toDataURL("image/png").split(",")[1];
  };

  const guarded = async (work) => {
    try {
      return await work();
    } catch (error) {
      return { error: String(error.message || error) };
    } finally {
      restoreDefinitions();
    }
  };

  svgFor(BASE_DEFINITIONS, true);
  saveDefinitions();
  const base = saved;

  return {
    // Every later formula sees these definitions, and only these.
    setPreamble: (preamble) => {
      saved = base;
      restoreDefinitions();
      try {
        if (preamble) svgFor(preamble, true);
        saveDefinitions();
        return {};
      } catch (error) {
        restoreDefinitions();
        return { error: String(error.message || error) };
      }
    },

    render: (latex, display, pxPerEm) =>
      guarded(async () => {
        const svg = svgFor(latex, display);
        // No font of MathJax's has the glyph, so the machine's fonts draw it.
        const systemFont = svg.querySelector("text") !== null;
        const box = fitToPixels(svg, pxPerEm);
        return { ...box, systemFont, png: await rasterise(svg, box) };
      }),
  };
})();
