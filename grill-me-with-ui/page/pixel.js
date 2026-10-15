// Turns ASCII art into a crisp SVG. Each character maps to a palette color; "." is transparent.
window.pixelSprite = function (art, palette, opts = {}) {
  const rows = art.trim().split("\n").map((r) => r.trim());
  const w = Math.max(...rows.map((r) => r.length));
  const h = rows.length;
  const scale = opts.scale || 4;
  let rects = "";
  rows.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      const ch = row[x];
      let run = 1;
      while (row[x + run] === ch) run++;
      if (ch !== "." && palette[ch]) {
        rects += `<rect x="${x}" y="${y}" width="${run}" height="1" fill="${palette[ch]}"/>`;
      }
      x += run;
    }
  });
  const cls = opts.className ? ` class="${opts.className}"` : "";
  const label = opts.label ? ` role="img" aria-label="${opts.label}"` : ` aria-hidden="true"`;
  return `<svg${cls}${label} width="${w * scale}" height="${h * scale}" viewBox="0 0 ${w} ${h}" shape-rendering="crispEdges">${rects}</svg>`;
};
