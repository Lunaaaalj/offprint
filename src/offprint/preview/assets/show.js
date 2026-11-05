// Turn to a page and draw the status bar: time, pages left in the chapter, percent of the book.
({ page, stride, margin, clock, left, percent }) => {
  document.body.style.left = `${margin - page * stride}px`;
  for (const bar of document.querySelectorAll(".preview-bar")) bar.remove();

  const add = (css, text) => {
    const bar = document.createElement("div");
    bar.className = "preview-bar";
    bar.style.cssText = css;
    bar.textContent = text;
    document.documentElement.appendChild(bar);
  };
  add("top: 9px; left: 0; right: 0; text-align: center;", clock);
  add(`bottom: 9px; left: ${margin}px;`, `${left} ${left === 1 ? "page" : "pages"} left in chapter`);
  add(`bottom: 9px; right: ${margin}px;`, `${percent}%`);
};
