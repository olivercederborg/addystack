// Helpers for a review artifact's SVG figures, in the geometry the approved example uses:
// 1px strokes on half-pixel lines, 6px elbows, 5×3 arrowheads whose tip lands on the last
// point. Import them in a throwaway generator script and paste or write its output into
// body.html. Classes come from assets/page.css.
//   import { svg, edge, text, onLine, box, gate, pin, file, token, clip, mock } from "<skill>/scripts/figure.mjs"

const R = 6; // elbow radius
const AH = 5; // arrowhead length
const AW = 3; // arrowhead half-width

/** Escapes text for SVG. */
export const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** A figure: `variant` is "wide" (640 wide), "narrow" (≤ 358 wide), or "half" (≤ 358 wide, one pane of a split); `aria` says what it shows in words. */
export const svg = ({ width, height, variant, aria }, parts) =>
  `<svg class="dg ${variant}" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="${esc(aria).replace(/"/g, "&quot;")}">${parts.join("")}</svg>`;

/** An orthogonal connector through `points` ([x, y] pairs). Solid is the path taken today; `dashed` one behind a gate. */
export function edge(points, { dashed = false } = {}) {
  const sign = (a, b) => (b > a) - (b < a);
  const d = [`M${points[0][0]} ${points[0][1]}`];
  for (let i = 1; i < points.length - 1; i++) {
    const [[x0, y0], [x1, y1], [x2, y2]] = [points[i - 1], points[i], points[i + 1]];
    const [dx0, dy0, dx1, dy1] = [sign(x0, x1), sign(y0, y1), sign(x1, x2), sign(y1, y2)];
    d.push(`L${x1 - dx0 * R} ${y1 - dy0 * R}Q${x1} ${y1} ${x1 + dx1 * R} ${y1 + dy1 * R}`);
  }
  const [[xa, ya], [xb, yb]] = points.slice(-2);
  const [dx, dy] = [sign(xa, xb), sign(ya, yb)];
  d.push(`L${xb - dx * AH} ${yb - dy * AH}`);
  const [px, py] = [-dy, dx];
  const head = `M${xb} ${yb}L${xb - dx * AH + px * AW} ${yb - dy * AH + py * AW}L${xb - dx * AH - px * AW} ${yb - dy * AH - py * AW}Z`;
  return `<g class="edge${dashed ? " dashed" : ""}"><path class="l" d="${d.join("")}"/><path class="ah" d="${head}"/></g>`;
}

/** Text: kind is "sans" (words), "mono" (names, values), "sub" (a node's searchable name), "quiet" (captions, endpoints, heads, PR numbers), "tag" (a box's header row) or "new". */
export const text = (x, y, content, kind, { anchor } = {}) =>
  `<text class="${kind}" x="${x}" y="${y}"${anchor ? ` text-anchor="${anchor}"` : ""}>${content}</text>`;

/** A quiet mono label set on a line, centred at (cx, cy), knocking the line out behind it. */
export const onLine = (cx, cy, label, width) =>
  `<rect class="knock" x="${cx - width / 2}" y="${cy - 8}" width="${width}" height="16"/>${text(cx, cy + 4, esc(label), "quiet", { anchor: "middle" })}`;

/**
 * A node as a box with a 24px tag header row, top-left at (x, y): `tag` a quiet mono line
 * ("Adapter · Dinero"), `title` its plain label, `sub` its searchable name. `isNew` outlines
 * what this PR adds in the accent. Height 80 with a sub, 64 without.
 */
export function box(x, y, width, { tag, title, sub, isNew = false }) {
  const height = sub ? 80 : 64;
  return `<g class="box${isNew ? " added" : ""}"><rect class="bg" x="${x + 0.5}" y="${y + 0.5}" width="${width - 1}" height="${height - 1}" rx="5"/><path class="rule" d="M${x + 1} ${y + 24.5}H${x + width - 1}"/>${text(x + 12, y + 16, esc(tag), "tag")}${text(x + 12, y + 48, esc(title), "sans")}${sub ? text(x + 12, y + 66, esc(sub), "sub") : ""}</g>`;
}

/** A gate drawn as a switch, 28×16, top-left at (x, y): off by default, `on` in a split's after pane. */
export const gate = (x, y, { on = false } = {}) =>
  `<g class="switch${on ? " on" : ""}"><rect class="track" x="${x + 0.5}" y="${y + 0.5}" width="27" height="15" rx="7.5"/><circle class="knob" cx="${x + (on ? 19.5 : 8.5)}" cy="${y + 8}" r="5.5"/></g>`;

/**
 * A review pin, 16 across, centred at (cx, cy): an accent dot numbered `n`, set on the part
 * of a figure a reviewer should check. The fold heads the code behind it with the same
 * number as `<span class="pin">n</span>`.
 */
export const pin = (cx, cy, n) =>
  `<g class="pin"><circle cx="${cx}" cy="${cy}" r="8"/><text class="pin-n" x="${cx}" y="${cy + 4}" text-anchor="middle">${n}</text></g>`;

/** A file glyph, 13×17, top-left at (x, y). */
export const file = (x, y) =>
  `<g class="file"><path d="M${x + 0.5} ${y + 0.5}H${x + 8.5}L${x + 12.5} ${y + 4.5}V${y + 16.5}H${x + 0.5}Z"/><path d="M${x + 8.5} ${y + 0.5}V${y + 4.5}H${x + 12.5}"/></g>`;

/** A returned value outlined in the accent, such as an ID one call hands the next. */
export const token = (x, y, width, height = 20) => `<rect class="token" x="${x + 0.5}" y="${y + 0.5}" width="${width - 1}" height="${height}" rx="3"/>`;

/** A paperclip, 10×16, top-left at (x, y): an attachment on a mock row. */
export const clip = (x, y) =>
  `<path class="clip" transform="translate(${x} ${y})" d="M2.5 5v6a2.5 2.5 0 0 0 5 0V3.5a1.75 1.75 0 0 0-3.5 0V10a.75.75 0 0 0 1.5 0V5"/>`;

/** The frame of a mini mock of an external system's screen; `rows` are y offsets of its hairlines. */
export const mock = (x, y, width, height, rows = []) =>
  `<g class="mock"><rect x="${x + 0.5}" y="${y + 0.5}" width="${width - 1}" height="${height - 1}" rx="6"/>${rows.map((r) => `<path d="M${x + 0.5} ${y + r + 0.5}H${x + width - 0.5}"/>`).join("")}</g>`;
