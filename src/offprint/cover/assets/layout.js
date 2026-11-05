// Fit every text element to its box, then report what was rendered.
// An element's size range comes from --fit-max and --fit-min in cover.css.
async () => {
  await document.fonts.ready;

  const texts = [...document.querySelectorAll("[data-text]")];

  const inkOf = (element) => {
    const ink = element.firstElementChild;
    const range = document.createRange();
    range.selectNodeContents(ink);
    const lines = range.getBoundingClientRect();
    const block = ink.getBoundingClientRect();
    // The block gives line boxes vertically; the range gives text that sticks out sideways.
    return { left: lines.left, top: block.top, right: lines.right, bottom: block.bottom };
  };

  const fits = (element) => {
    const box = element.getBoundingClientRect();
    const ink = inkOf(element);
    return (
      ink.left >= box.left && ink.right <= box.right &&
      ink.top >= box.top && ink.bottom <= box.bottom
    );
  };

  for (const element of texts) {
    const style = getComputedStyle(element);
    const largest = parseFloat(style.getPropertyValue("--fit-max"));
    const smallest = parseFloat(style.getPropertyValue("--fit-min"));
    for (let size = largest; size >= smallest; size -= 1) {
      element.style.fontSize = `${size}px`;
      if (fits(element)) break;
    }
  }

  return texts.map((element) => {
    const box = element.getBoundingClientRect();
    const ink = inkOf(element);
    return {
      name: element.dataset.text,
      box: [box.left, box.top, box.right, box.bottom],
      ink: [ink.left, ink.top, ink.right, ink.bottom],
      colour: getComputedStyle(element).color.match(/\d+/g).slice(0, 3).map(Number),
    };
  });
}
