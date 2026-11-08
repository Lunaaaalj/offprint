// Measure a paginated chapter: how many pages it has and where things are on them.
({ fragments, stride }) => {
  const body = document.body;
  const origin = body.getBoundingClientRect().left;
  const pageOf = (element) => {
    const box = element.getClientRects()[0] ?? element.getBoundingClientRect();
    return Math.max(0, Math.floor((box.left - origin + 1) / stride));
  };
  const firstPage = (selector) => {
    const element = document.querySelector(selector);
    return element ? pageOf(element) : null;
  };

  return {
    pages: Math.max(1, Math.ceil(body.scrollWidth / stride)),
    cover: body.classList.contains("cover"),
    figure: firstPage("figure"),
    equation: firstPage("div.equation"),
    table: firstPage("table"),
    overflowing_tables: [...document.querySelectorAll("div.table")]
      .filter((box) => {
        const table = box.querySelector("table");
        return table && table.getBoundingClientRect().width > box.getBoundingClientRect().width + 1;
      })
      .map((box) => box.id),
    anchors: Object.fromEntries(
      fragments.flatMap((id) => {
        const element = document.getElementById(id);
        return element ? [[id, pageOf(element)]] : [];
      }),
    ),
  };
};
