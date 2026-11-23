#!/usr/bin/env node
// Checks a PR body before it's shown or posted: every Mermaid block parses (through
// check-mermaid.mjs), its check lines name checks without counting tests, since a
// count ("✅ 56 package tests") goes stale after the next fix round, and every screenshot
// sits in a Before | After table row with both cells filled, so a reviewer can compare
// (a screen with no before writes italic text such as _new screen_). Code fences are skipped.
//
//   check-body.mjs FILE...     one line per problem; exit 1 when any is found
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const files = process.argv.slice(2);
if (files.length === 0) {
  console.error("usage: check-body.mjs FILE...");
  process.exit(2);
}

// A check line carries a check marker, opens with the Checks label, or sits under a
// template's Checks or Tests heading.
const checkLine = /✅|❌|⚠|^\s*[-*]?\s*\*\*Checks\*\*/;
const heading = /^(#{1,6})\s+(.*)/;
const checksHeading = /\b(checks?|tests?|testing)\b/i;
// "56 tests", "65 + 8 package tests", "5 new hook tests", "tests 11/12", "SnoopKit tests (93)",
// "server tests (179, 4 new)". A version ("Python 3.13 unit tests") or a parenthesized
// setting ("browser tests (3 browsers)") isn't a count.
const testCount =
  /(?<![\d.])\b\d[\d,]*(\s*\+\s*\d[\d,]*)?\s+([\w-]+\s+){0,2}tests?\b|\btests?\s+(\d+\/\d+|\(\d+(, \d+ new)?\))|\btests?\b[^·]*\(\d+, \d+ new\)/i;

// A screenshot is a Markdown image or an <img> tag outside inline code.
const screenshot = /!\[[^\]]*\]\([^)]*\)|<img\b/i;
const fence = /^\s*(```|~~~)/;
const tableRow = /^\s*\|/;
const separatorRow = /^\s*\|?(\s*:?-+:?\s*\|)+\s*:?-*:?\s*$/;
// A row's cells, split on unescaped pipes, without the outer pipes' empty ends.
const cells = (row) => row.trim().replace(/^\|/, "").replace(/(?<!\\)\|$/, "").split(/(?<!\\)\|/).map((c) => c.trim());
const label = (cell) => cell.replace(/[*_\s]/g, "").toLowerCase();

let counted = 0;
let misplaced = 0;
for (const file of files) {
  // The Checks heading's level while inside its section, which a subheading doesn't end.
  let checksLevel = 0;
  let inFence = false;
  // The current table's Before and After columns, null outside a table or in one without both.
  let table = undefined;
  const misplace = (i, problem) => {
    misplaced++;
    console.log(`${file}:${i + 1} ❌ ${problem}`);
  };
  readFileSync(file, "utf8")
    .split("\n")
    .forEach((text, i) => {
      if (fence.test(text)) inFence = !inFence;
      if (inFence || fence.test(text)) return;
      if (!tableRow.test(text)) table = undefined;
      else if (table === undefined) {
        const header = cells(text).map(label);
        const [before, after] = [header.indexOf("before"), header.indexOf("after")];
        table = before >= 0 && after >= 0 ? { before, after } : null;
      } else if (table && !separatorRow.test(text)) {
        const row = cells(text);
        if (!row[table.before] || !row[table.after]) {
          misplace(i, "Before | After row has an empty cell; write _new screen_ (or other italic text) where there's no image");
        }
      }
      if (!table && screenshot.test(text.replace(/`[^`]*`/g, ""))) {
        misplace(i, "screenshot outside a Before | After table; put it in a row beside its before");
      }
      const [, hashes, title] = text.match(heading) ?? [];
      if (hashes && (!checksLevel || hashes.length <= checksLevel)) {
        checksLevel = checksHeading.test(title) ? hashes.length : 0;
      }
      const match = (checksLevel || checkLine.test(text)) && text.match(testCount);
      if (!match) return;
      counted++;
      console.log(`${file}:${i + 1} ❌ counts tests ("${match[0]}"); name the check instead`);
    });
}

const mermaid = spawnSync(
  process.execPath,
  [join(dirname(fileURLToPath(import.meta.url)), "check-mermaid.mjs"), ...files],
  { stdio: "inherit" },
);
// A crash or a signal leaves status null: the diagrams went unchecked, which is a failure.
if (mermaid.status === null) console.log(`check-mermaid.mjs didn't finish: ${mermaid.error ?? mermaid.signal}`);
console.log(counted ? `Check lines: ${counted} count tests` : "Check lines: no test counts");
console.log(misplaced ? `Screenshots: ${misplaced} misplaced or missing a side` : "Screenshots: all compared side by side");
process.exit(counted || misplaced || mermaid.status !== 0 ? 1 : 0);
