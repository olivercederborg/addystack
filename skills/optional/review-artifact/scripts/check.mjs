#!/usr/bin/env node
// Checks a built review artifact against the format's bars, and screenshots it.
// Usage: node check.mjs <dir> [--repo <git checkout> --rev <sha> [--rev <sha> …]]
// Prints one `ok` or `FAIL` line per check and exits 1 on any FAIL. Screenshots go to
// <dir>/shots/: desktop.png (1280), mobile.png (375, 2x), desktop-dark.png, mobile-dark.png,
// tablet-dark.png (840, split panes stacked), and fold-desktop.png and fold-mobile.png (the fold open).
// With --repo and --rev, every name in <code>, <pre> and SVG .mono/.sub/.new text must occur at
// one of the revs (git grep -F), every path must exist there, and every short SHA must be a
// commit in the repo, so a misspelled or invented name fails.
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const PROSE_WORDS = 140;
const args = process.argv.slice(2);
const opt = (name) => args.flatMap((a, i) => (args[i - 1] === name ? [a] : []));
const dir = args.find((a, i) => !a.startsWith("--") && !["--repo", "--rev"].includes(args[i - 1]));
if (!dir || !existsSync(join(dir, "index.html"))) {
  console.error("usage: node check.mjs <dir> [--repo <checkout> --rev <sha>…]; run build.mjs <dir> first");
  process.exit(2);
}
const [repo] = opt("--repo");
const revs = opt("--rev");

let failed = false;
const report = (ok, what, detail = "") => {
  if (!ok) failed = true;
  console.log(`${ok ? "ok  " : "FAIL"} ${what}${detail ? `: ${detail}` : ""}`);
};

/** Playwright from the current project, else a pinned copy in ~/.cache/review-artifact. */
async function loadPlaywright() {
  const cache = join(process.env.XDG_CACHE_HOME ?? join(homedir(), ".cache"), "review-artifact");
  for (const base of [process.cwd(), cache]) {
    for (const pkg of ["playwright", "playwright-core"]) {
      try {
        return await import(pathToFileURL(createRequire(join(base, "noop.js")).resolve(pkg)).href);
      } catch {}
    }
  }
  console.error(`installing playwright-core@1.60.0 into ${cache}`);
  execFileSync("npm", ["install", "--silent", "--no-save", "--prefix", cache, "playwright-core@1.60.0"], { stdio: "inherit" });
  return import(pathToFileURL(createRequire(join(cache, "noop.js")).resolve("playwright-core")).href);
}

/** Launches Chromium, falling back to any browser already in Playwright's download cache. */
async function launch(chromium) {
  try {
    return await chromium.launch();
  } catch (error) {
    const root =
      process.env.PLAYWRIGHT_BROWSERS_PATH ??
      (process.platform === "darwin" ? join(homedir(), "Library", "Caches", "ms-playwright") : join(homedir(), ".cache", "ms-playwright"));
    // Linux, then macOS: the full browser (Chromium or Chrome for Testing), then the headless shell
    const binaries = [
      ["chrome-linux64", "chrome"],
      ...["chrome-mac-arm64", "chrome-mac-x64", "chrome-mac"].flatMap((d) => [
        [d, "Google Chrome for Testing.app", "Contents", "MacOS", "Google Chrome for Testing"],
        [d, "Chromium.app", "Contents", "MacOS", "Chromium"],
      ]),
      ...["chrome-headless-shell-mac-arm64", "chrome-headless-shell-mac-x64", "chrome-headless-shell-linux64"].map((d) => [d, "chrome-headless-shell"]),
    ];
    const found = existsSync(root)
      ? readdirSync(root)
          .filter((d) => d.startsWith("chromium"))
          .sort()
          .reverse()
          .flatMap((d) => binaries.map((b) => join(root, d, ...b)))
          .find(existsSync)
      : undefined;
    if (!found) throw new Error(`no Chromium found; run \`npx playwright install chromium\` (${error.message})`);
    return chromium.launch({ executablePath: found });
  }
}

// Runs in the page: everything the bars need, measured at the current viewport.
function measure() {
  const visible = (el) => el.getClientRects().length > 0 && el.getBoundingClientRect().width > 0;
  const ownText = (el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
  const scale = (el) => {
    const svg = el.closest("svg");
    return svg ? svg.getBoundingClientRect().width / svg.viewBox.baseVal.width : 1;
  };
  const texts = [...document.querySelectorAll("body *")].filter((el) => visible(el) && ownText(el));
  const small = texts
    .filter((el) => parseFloat(getComputedStyle(el).fontSize) * scale(el) < 11.95)
    .map((el) => el.textContent.trim().slice(0, 30));
  const tracked = texts
    .filter((el) => {
      const s = getComputedStyle(el);
      return parseFloat(s.fontSize) * scale(el) <= 15 && s.letterSpacing !== "normal" && parseFloat(s.letterSpacing) !== 0;
    })
    .map((el) => el.textContent.trim().slice(0, 30));
  const clash = [];
  for (const svg of document.querySelectorAll("svg")) {
    if (!visible(svg)) continue;
    const vb = svg.viewBox.baseVal;
    const boxes = [...svg.querySelectorAll("text")].map((t) => [t.textContent, t.getBBox()]);
    for (const [s, b] of boxes) if (b.x < -0.5 || b.x + b.width > vb.width + 0.5 || b.y < -0.5 || b.y + b.height > vb.height + 0.5) clash.push(`outside: ${s}`);
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const [s, a] = boxes[i];
        const [t, c] = boxes[j];
        if (a.x < c.x + c.width + 4 && c.x < a.x + a.width + 4 && a.y < c.y + c.height && c.y < a.y + a.height) clash.push(`overlap: ${s} | ${t}`);
      }
  }
  // review pins: the figure pins this viewport shows (a wide/narrow pair counts once), the
  // fold's heading pins, and any pin elsewhere
  const numbers = (els) => [...els].map((el) => el.textContent.trim()).sort();
  const fold = document.querySelector("main > .fold");
  const allPins = [...document.querySelectorAll("main .pin-n, main span.pin")];
  const figurePins = allPins.filter((el) => el.closest("figure.frame > .frame-body"));
  // a fold pin heads its code: an h3 with words after the number
  const foldPins = fold ? [...fold.querySelectorAll("h3 > span.pin")].filter((p) => p.parentElement.textContent.replace(p.textContent, "").trim()) : [];
  return {
    pins: numbers(figurePins.filter((el) => visible(el) && el.checkVisibility({ visibilityProperty: true, opacityProperty: true }))),
    figures: document.querySelectorAll("main figure").length,
    foldPins: numbers(foldPins),
    strayPins: allPins.filter((el) => !figurePins.includes(el) && !foldPins.includes(el)).length,
    fonts: document.fonts.check('13px "Geist"') && document.fonts.check('12px "Geist Mono"'),
    overflow: document.documentElement.scrollWidth - innerWidth,
    height: document.documentElement.scrollHeight,
    small,
    tracked,
    clash,
  };
}

// Runs in the page once: the format's structure and the prose budget.
function structure() {
  const main = document.querySelector("main");
  const kids = [...main.children];
  const content = kids.filter((el) => !el.matches("footer.foot"));
  const hero = main.querySelector(":scope > .hero");
  const sections = kids.filter((el) => el.matches("section.sec"));
  const labels = sections.map((s) => s.querySelector(":scope > .sec-head > h2")?.textContent.trim() ?? "");
  const specItems = [...main.querySelectorAll(":scope > ul.specs > li")];
  const ruler = main.querySelector(":scope > ol.ruler");
  const stepItems = ruler ? [...ruler.children] : [];
  const filled = (el) => !!el?.textContent.trim();
  const specs = specItems.length;
  const steps = stepItems.length;
  // each spec is a number in <b> over a caption; each step names itself, and one is .now
  const specsFilled = specItems.every((li) => /\d/.test(li.querySelector(":scope > b")?.textContent ?? "") && li.textContent.trim() !== li.querySelector(":scope > b").textContent.trim());
  const rulerOk = !ruler || (steps >= 3 && steps <= 6 && stepItems.every((li) => li.matches("li") && filled(li)) && ruler.querySelectorAll(":scope > li.now").length === 1);
  // count prose outside the fold: figures (with their frame bars), the running head, the
  // specs' numbers and the ruler are glance data, not prose, so they're left out
  const holder = document.createElement("div");
  holder.style.cssText = `position:absolute;left:-9999px;inline-size:${main.getBoundingClientRect().width}px`;
  for (const el of content.filter((el) => !el.matches(".fold, .bar, ol.ruler"))) {
    const copy = el.cloneNode(true);
    copy.querySelectorAll("figure, .specs b").forEach((f) => f.remove());
    holder.append(copy);
  }
  document.body.append(holder);
  const prose = holder.innerText.split(/\s+/).filter(Boolean).length;
  holder.remove();
  const svgs = [...document.querySelectorAll("figure svg")];
  const decisions = sections.find((s, i) => labels[i] === "Decisions");
  return {
    header:
      !!kids[0]?.matches("header.bar") &&
      kids[1] === hero &&
      !!hero?.querySelector(":scope > h1") &&
      !!hero.querySelector(":scope > p.verdict > strong:first-child"),
    glance: specs >= 2 && specs <= 4 && specsFilled && kids[2]?.matches("ul.specs") && rulerOk && (!ruler || kids[3] === ruler),
    specs,
    steps,
    labels,
    figures: sections.map((s, i) => [labels[i], s.querySelectorAll("figure").length]),
    unlabelledSvg: svgs.filter((s) => s.getAttribute("role") !== "img" || !s.getAttribute("aria-label")).length,
    unframed: [
      ...[...main.querySelectorAll("figure")].filter((f) => !f.matches(".frame") || !f.querySelector(":scope > figcaption.frame-bar") || !f.querySelector(":scope > .frame-body")),
      ...[...main.querySelectorAll("svg")].filter((s) => !s.closest("figure.frame > .frame-body")),
    ].length,
    // a split's panes hold drawings no wider than a phone's 358px
    wideHalves: [...main.querySelectorAll(".frame-body.split svg")].filter((s) => s.viewBox.baseVal.width > 358).length,
    forks: !decisions || (decisions.querySelectorAll(":scope > ul.forks > li").length > 0 && [...decisions.querySelectorAll(":scope > ul.forks > li")].every((li) => filled(li.querySelector(":scope > .call")) && [".pick", ".over"].every((side) => filled(li.querySelector(`:scope > ${side} > .opt`)) && li.querySelector(`:scope > ${side}`).textContent.trim() !== li.querySelector(`:scope > ${side} > .opt`).textContent.trim()))),
    // Verified and Not verified each hold a spec table with at least one row
    tables: sections.filter((s, i) => ["Verified", "Not verified"].includes(labels[i])).map((s) => {
      // every row fills one cell per column head, and there are at least two heads
      const heads = s.querySelectorAll(":scope > table.spec thead th").length;
      const rows = [...s.querySelectorAll(":scope > table.spec tbody tr")];
      return heads >= 2 && rows.length && rows.every((tr) => tr.cells.length === heads && [...tr.cells].every(filled)) ? rows.length : 0;
    }),
    folds: document.querySelectorAll("details").length,
    foldLast: content.at(-1)?.matches(".fold") && !!content.at(-1).querySelector("details"),
    notice: !!document.querySelector("footer.foot .notice"),
    prose,
    names: [...document.querySelectorAll("code, pre, svg .mono, svg .sub, svg .new")].map((el) => el.textContent).join("\n"),
    shas: [...new Set(main.textContent.match(/\b[0-9a-f]{7,40}\b/g) ?? [])].filter((s) => /[a-f]/.test(s) && /\d/.test(s)),
  };
}

const playwright = await loadPlaywright();
const chromium = playwright.chromium ?? playwright.default.chromium;
const browser = await launch(chromium);
const url = pathToFileURL(resolve(dir, "index.html")).href;
const shots = join(dir, "shots");
mkdirSync(shots, { recursive: true });
let facts;

for (const [name, width, scheme] of [
  ["desktop", 1280, "light"],
  ["mobile", 375, "light"],
  ["desktop-dark", 1280, "dark"],
  ["mobile-dark", 375, "dark"],
  // between phone and desktop: a split's panes stack, and a single frame pads out to its wide drawing
  ["tablet-dark", 840, "dark"],
]) {
  const page = await browser.newPage({ viewport: { width, height: 900 }, colorScheme: scheme, deviceScaleFactor: width < 640 ? 2 : 1 });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  await page.goto(url);
  await page.evaluate(() => document.fonts.ready);
  const m = await page.evaluate(measure);
  report(errors.length === 0, `${name}: no page errors`, errors.join("; "));
  report(m.fonts, `${name}: Geist and Geist Mono load`);
  report(m.overflow <= 0, `${name}: no sideways scroll`, m.overflow > 0 ? `${m.overflow}px too wide` : "");
  report(m.small.length === 0, `${name}: no text under 12px`, m.small.join(" | "));
  report(m.tracked.length === 0, `${name}: letter-spacing 0 at 15px and under`, m.tracked.join(" | "));
  report(m.clash.length === 0, `${name}: SVG text inside its figure, no overlaps`, m.clash.join(" | "));
  // a page with figures pins 1–4 risks on them; a page with none has no pins
  const pinsInOrder = (m.figures === 0 || m.pins.length >= 1) && m.pins.length <= 4 && m.pins.every((n, i) => n === String(i + 1));
  report(
    pinsInOrder && m.strayPins === 0 && m.pins.join() === m.foldPins.join(),
    `${name}: 1–4 review pins in figure bodies, numbered from 1, each heading its code in the fold`,
    `figures ${m.pins.join(",") || "none"} · fold headings ${m.foldPins.join(",") || "none"}${m.strayPins ? ` · ${m.strayPins} elsewhere` : ""}`,
  );
  if (name === "desktop") {
    facts = await page.evaluate(structure);
    console.log(`info desktop: page height ${m.height}px`);
  }
  await page.screenshot({ path: join(shots, `${name}.png`), fullPage: true });
  if (scheme === "light") {
    await page.evaluate(() => document.querySelectorAll("details").forEach((d) => (d.open = true)));
    const open = await page.evaluate(measure);
    report(open.overflow <= 0 && open.small.length === 0, `${name}: fold open, no sideways scroll or text under 12px`, [open.overflow > 0 ? `${open.overflow}px too wide` : "", ...open.small].filter(Boolean).join(" | "));
    await page.locator("details").last().screenshot({ path: join(shots, `fold-${name}.png`) });
  }
  await page.close();
}
await browser.close();

const labels = facts.labels;
report(facts.header, "head: header.bar, then .hero with <h1> and a verdict sentence that opens with <strong>");
report(facts.glance, "ul.specs with 2–4 numbers (each with a digit) and captions after the hero, then an optional ol.ruler of 3–6 steps with one .now", `${facts.specs} specs, ${facts.steps} steps`);
const verified = labels.indexOf("Verified");
const notVerified = labels.indexOf("Not verified");
const decisions = labels.indexOf("Decisions");
const behaviors = labels.slice(0, [decisions, verified].find((i) => i >= 0) ?? labels.length);
report(behaviors.length > 0 && behaviors.every(Boolean), "a labelled section for each changed behavior before the rows", `${behaviors.join(", ") || "none"}`);
report(verified >= 0 && notVerified === verified + 1 && (decisions < 0 || decisions === verified - 1) && notVerified === labels.length - 1, "rows in order: Decisions, Verified, Not verified, last", labels.join(" → "));
const crowded = facts.figures.filter(([, n]) => n > 1);
report(crowded.length === 0, "at most one figure per section", crowded.map(([l, n]) => `${l} has ${n}`).join(", "));
report(facts.unlabelledSvg === 0, "every figure SVG has role=img and an aria-label", facts.unlabelledSvg ? `${facts.unlabelledSvg} without` : "");
report(facts.unframed === 0, "every figure is a figure.frame with a figcaption.frame-bar and a .frame-body, and every SVG sits in one", facts.unframed ? `${facts.unframed} outside` : "");
report(facts.folds === 1 && facts.foldLast, "one fold, at the end", `${facts.folds} <details>`);
report(facts.wideHalves === 0, "every drawing in a split is at most 358 wide", facts.wideHalves ? `${facts.wideHalves} wider` : "");
report(facts.forks, "Decisions is a ul.forks: each row a .call, a .pick and an .over, each an .opt and what it means");
report(facts.tables.length === 2 && facts.tables.every((n) => n > 0), "Verified and Not verified each hold a table.spec with column heads, every row filling each column", facts.tables.join(", "));
report(facts.notice, "font notice in the footer");
report(facts.prose <= PROSE_WORDS, `prose outside the fold ≤ ${PROSE_WORDS} words`, `${facts.prose}`);

const css = existsSync(join(dir, "extra.css")) ? readFileSync(join(dir, "extra.css"), "utf8") : "";
const banned = css.match(/#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab|lab|lch|color)\(|shadow|gradient|letter-spacing/gi) ?? [];
report(banned.length === 0, "extra.css adds no colors, shadows, gradients, or tracking", [...new Set(banned)].join(", "));

const md = readFileSync(join(dir, "llms.md"), "utf8");
const missing = [
  ...labels.filter((l) => !new RegExp(`^##\\s+${l.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`, "m").test(md)).map((l) => `## ${l}`),
  ...facts.shas.filter((s) => !md.includes(s)),
];
report(missing.length === 0, "llms.md has every section heading and every SHA the page shows", missing.join(", "));

if (repo && revs.length) {
  const git = (...a) => {
    try {
      return execFileSync("git", ["-C", repo, ...a], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], maxBuffer: 1 << 28 });
    } catch {
      return null;
    }
  };
  const paths = revs.flatMap((rev) => (git("ls-tree", "-r", "--name-only", rev) ?? "").split("\n"));
  const grep = (name) => revs.some((rev) => git("grep", "-q", "-F", "-e", name, rev, "--") !== null);
  const tokens = [...new Set(facts.names.split(/[\s,;()[\]{}<>"'`=]+|(?<=\w):(?=\s|$)/).filter(Boolean))];
  const unresolved = [];
  let checked = 0;
  for (const token of tokens) {
    if (/^[0-9a-f]{7,40}$/.test(token) && /[a-f]/.test(token) && /\d/.test(token)) {
      checked++;
      if (git("rev-parse", "-q", "--verify", `${token}^{commit}`) === null) unresolved.push(`${token} (no such commit)`);
    } else if (/[\w)]\/[\w(]|\.(?:ts|tsx|js|mjs|json|md|sql|css|py|sh)(?::[\d-]+)?$/.test(token)) {
      checked++;
      const path = token.replace(/:[\d-]+$/, "");
      // a model id or MIME type also has a slash: accept it when the text itself occurs
      if (!paths.some((p) => p.includes(path)) && !grep(token)) unresolved.push(`${token} (no such path or text)`);
    } else {
      for (const name of token.match(/[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*/g) ?? []) {
        if (name.length < 3) continue;
        checked++;
        if (!grep(name) && !name.split(".").every((part) => part.length < 3 || grep(part))) unresolved.push(name);
      }
    }
  }
  report(unresolved.length === 0, `every code name, path and SHA resolves at ${revs.join(" or ")} (${checked} checked)`, [...new Set(unresolved)].join(", "));
} else {
  console.log("skip names: pass --repo <checkout> --rev <head sha> to check every code name against the PR");
}
console.log(`shots in ${resolve(shots)}`);
process.exit(failed ? 1 : 0);
