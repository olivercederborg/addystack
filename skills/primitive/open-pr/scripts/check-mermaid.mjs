#!/usr/bin/env node
// Copy of shared/scripts/check-mermaid.mjs, written by scripts/sync-copies.py: edit the source, then run the script.
// Parses every ```mermaid block in Markdown files with the Mermaid version GitHub renders
// with, so a PR body or comment with a broken diagram fails before it's posted.
//
//   check-mermaid.mjs FILE...     one line per block; exit 1 when any block doesn't parse
//
// GitHub's docs say to check its Mermaid version with an `info` block. This reads the
// same version from GitHub's renderer bundle, and falls back to FALLBACK offline.
// Mermaid and jsdom install once into ~/.cache/skills-mermaid/<version>-jsdom<JSDOM>, and
// each install removes the folders there no run has used for 30 days.
import { execFileSync } from "node:child_process";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  utimesSync,
} from "node:fs";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

const FALLBACK = "12.1.0"; // GitHub's version on 2026-10-12
const JSDOM = "30.1.2";
const VIEWER = "https://viewscreen.githubusercontent.com";
const UNUSED_DAYS = 30;
const DAY = 24 * 60 * 60 * 1000;

const files = process.argv.slice(2);
if (files.length === 0) {
  console.error("usage: check-mermaid.mjs FILE...");
  process.exit(2);
}

async function githubVersion() {
  try {
    const page = await (await fetch(`${VIEWER}/markdown/mermaid`)).text();
    const bundle = page.match(/\/static\/assets\/mermaidMarkdown-[\w-]+\.js/)?.[0];
    const code = bundle && (await (await fetch(VIEWER + bundle)).text());
    const version = code?.match(/renderer\.draw\(\w+,\w+,"(\d+\.\d+\.\d+)"/)?.[1];
    if (version) return version;
  } catch {}
  console.error(`couldn't read GitHub's Mermaid version; checking with ${FALLBACK}`);
  return FALLBACK;
}

// npm installs into a fresh sibling folder that is renamed to `dir` only once npm succeeds,
// so `dir` exists only when complete: an interrupted install leaves just the sibling, and
// when another run renames its install into place first, that one is used.
function install(dir, version) {
  mkdirSync(dirname(dir), { recursive: true });
  const partial = mkdtempSync(`${dir}.partial-`);
  try {
    execFileSync("npm", ["install", "--prefix", partial, "--no-save", "--silent", `mermaid@${version}`, `jsdom@${JSDOM}`], {
      stdio: ["ignore", "ignore", "inherit"],
    });
    renameSync(partial, dir);
  } catch (error) {
    if (!existsSync(dir)) throw error;
  } finally {
    rmSync(partial, { recursive: true, force: true });
  }
  prune(dir);
}

// Each folder is ~200 MB and a new Mermaid or jsdom version makes a new one, so after an
// install this removes siblings no run has used for UNUSED_DAYS (each run refreshes its
// folder's mtime) and partials older than a day, which only a killed install leaves.
// Offline runs use FALLBACK and online runs GitHub's version, so more than one stays in use.
// A fresh partial may be another run's install in progress. Cleanup never fails the check.
function prune(dir) {
  const now = Date.now();
  const parent = dirname(dir);
  let names = [];
  try {
    names = readdirSync(parent);
  } catch {}
  for (const name of names) {
    const path = join(parent, name);
    if (path === dir) continue;
    try {
      // Only real folders: a link's own mtime doesn't change when a run refreshes its target.
      const stat = lstatSync(path);
      const days = name.includes(".partial-") ? 1 : UNUSED_DAYS;
      if (stat.isDirectory() && now - stat.mtimeMs >= days * DAY) rmSync(path, { recursive: true, force: true });
    } catch {}
  }
}

async function loadMermaid(version) {
  // The jsdom suffix skips the `<version>` folders older runs could leave half installed.
  const dir = join(process.env.XDG_CACHE_HOME ?? join(homedir(), ".cache"), "skills-mermaid", `${version}-jsdom${JSDOM}`);
  const require = createRequire(join(dir, "package.json"));
  if (existsSync(dir)) {
    try {
      const now = new Date();
      utimesSync(dir, now, now);
    } catch {}
  } else install(dir, version);
  // Mermaid sanitizes labels with DOMPurify, which needs a window even to parse.
  const { window } = new (require("jsdom").JSDOM)("");
  globalThis.window = window;
  globalThis.document = window.document;
  return (await import(pathToFileURL(require.resolve("mermaid")).href)).default;
}

// Yields { line, source } for each ```mermaid (or ~~~mermaid) fence, also inside an
// outer four-backtick example fence.
function* mermaidBlocks(text) {
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const open = lines[i].match(/^(\s*)(`{3,}|~{3,})\s*mermaid\s*$/);
    if (!open) continue;
    const [, indent, fence] = open;
    const body = [];
    let j = i + 1;
    while (j < lines.length && !new RegExp(`^\\s*${fence[0]}{${fence.length},}\\s*$`).test(lines[j])) {
      body.push(lines[j].startsWith(indent) ? lines[j].slice(indent.length) : lines[j]);
      j++;
    }
    yield { line: i + 1, source: body.join("\n") };
    i = j;
  }
}

const version = await githubVersion();
const mermaid = await loadMermaid(version);
let failed = 0;
let checked = 0;
for (const file of files) {
  for (const { line, source } of mermaidBlocks(readFileSync(file, "utf8"))) {
    checked++;
    try {
      const { diagramType } = await mermaid.parse(source);
      console.log(`${file}:${line} ✅ ${diagramType}`);
    } catch (error) {
      failed++;
      console.log(`${file}:${line} ❌ ${String(error.message ?? error).replace(/\s*\n\s*/g, " | ")}`);
    }
  }
}
console.log(`Mermaid ${version} (GitHub): ${checked - failed}/${checked} blocks parse`);
process.exit(failed ? 1 : 0);
