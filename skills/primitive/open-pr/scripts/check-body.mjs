#!/usr/bin/env node
// Checks a PR body before it's shown or posted: every Mermaid block parses (through
// check-mermaid.mjs), and its check lines name checks without counting tests, since a
// count ("✅ 56 package tests") goes stale after the next fix round.
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

let counted = 0;
for (const file of files) {
  // The Checks heading's level while inside its section, which a subheading doesn't end.
  let checksLevel = 0;
  readFileSync(file, "utf8")
    .split("\n")
    .forEach((text, i) => {
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
process.exit(counted || mermaid.status !== 0 ? 1 : 0);
