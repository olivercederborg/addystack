#!/usr/bin/env python3
"""Lists the casts and suppressions a diff adds, for verify-work's Slop check, with each
one's twins: the same cast or suppression already in the code at the base.

Usage: casts.py <base> <head>   (run inside the repo; reviews base...head)

What it lists, in TypeScript and JavaScript files, tests included:
- a cast `<operand> as <Type>`, other than `as const`, an import or export alias, and
  text inside a string or comment;
- a type suppression: `@ts-expect-error`, `@ts-ignore`, `@ts-nocheck`;
- a lint suppression: `eslint-disable*`, `oxlint-disable*`, `biome-ignore`.

What it leaves out:
- a moved or kept one: the diff removes the same cast or suppression elsewhere, in any
  file, so a move, a rename, a rewrite that keeps the cast, or a reason added to an
  existing disable isn't new.
- a shape text can't see: guards, fallbacks, swallowed errors, `!` non-null assertions.
  An audit of one team's merged history (Nov 2026) found text matching sees casts and
  suppressions, and 39% of its hits were moved or kept code, which this script leaves out.

A new one with a written reason is listed apart, since the reason is the call to judge:
a suppression's own description (`-- why`, `biome-ignore <rule>: why`, text after
`@ts-expect-error`), or for a cast a comment on its line or the line above that says why
it casts (it names the cast, a type, or an approval).

Twins group by shape: the operand's last name and the type for a cast (`sql as never`,
whether `sql` or `target.sql`), the directive and its rules for a suppression. Each group
counts its twins at the base in the same file, in the same folder, and elsewhere, from
`git grep`, so a cast written across lines isn't counted. A twin is the cause spreading,
not a precedent: in the same audit, `sql as never` grew from 0 to 99 casts across one
repo's check files in two weeks, excused each time because the file already used it."""
from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

CODE = ("*.ts", "*.tsx", "*.mts", "*.cts", "*.js", "*.jsx", "*.mjs", "*.cjs")
CAST = re.compile(r"(?:([\w$][\w$.]*)|[)\]}])\s*\bas\s+(?!const\b)(?=[\w$({\[<'\"`])")
ALIAS = re.compile(r"^\s*(import\b|export\s*(type\s*)?[{*])")
SUPPRESSION = re.compile(r"(@ts-(?:expect-error|ignore|nocheck))\b:?\s*(.*)|"
                         r"((?:eslint|oxlint)-disable(?:-next-line|-line)?)\b\s*(.*)|"
                         r"(biome-ignore(?:-all|-start)?)\s+([^:]*?)\s*(?::\s*(.*))?$")
# A comment says why a cast is there when it names the cast, a type, or an approval;
# a section heading above an assertion doesn't.
WHY = re.compile(r"\b(cast\w*|as (never|any|unknown)|assert\w*|approv\w*|types?|typed|typing|branded|"
                 r"generic|infer\w*)\b", re.I)


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    shape: str  # what twins share: `sql as never`, `eslint-disable-next-line no-console`
    reason: str  # the written reason, or ""


@dataclass
class Group:
    shape: str
    new: list[Hit] = field(default_factory=list)
    same_file: int = 0
    same_folder: Counter = field(default_factory=Counter)  # path -> twins
    elsewhere: int = 0


def _git(*args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-c", "core.quotePath=false", *args], capture_output=True)
    if result.returncode and check:
        raise SystemExit(f"git {' '.join(args[:2])} failed: {result.stderr.decode(errors='replace').strip()[:200]}")
    return result.stdout.decode(errors="replace")


def split(text: str) -> list[tuple[str, str]]:
    """Each line of a file as (code, comment): code with string and template contents and
    comments blanked, so columns stay put, and the line's comment text. Strings and
    comments may span lines; `${}` inside a template counts as template text."""
    lines, code, comment = [], [], []
    state = ""  # "", "'", '"', "`", "//", "/*"
    i = 0
    while i <= len(text):
        char = text[i] if i < len(text) else "\n"
        pair = text[i:i + 2]
        if char == "\n":
            lines.append(("".join(code), "".join(comment).strip()))
            code, comment = [], []
            if state in ("//", "'", '"'):
                state = ""
            i += 1
            continue
        if state == "":
            if pair in ("//", "/*"):
                state = pair
                code.append("  ")
                i += 2
                continue
            if char in "'\"`":
                state = char
            code.append(char)
        elif state in ("//", "/*"):
            if state == "/*" and pair == "*/":
                state = ""
                code.append("  ")
                i += 2
                continue
            comment.append(char)
            code.append(" ")
        else:  # inside a string
            if char == "\\":
                code.append("  ")
                i += 2
                continue
            if char == state:
                state = ""
                code.append(char)
            else:
                code.append(" ")
        i += 1
    return lines[:-1] if text.endswith("\n") else lines


def _type(text: str) -> str:
    """A cast's target type, cut where its expression ends: brackets balance, and a
    closer with no opener, or `;`, `,`, `=`, `?`, `:`, `||`, `&&` outside brackets, ends it."""
    depth, out, i = 0, [], 0
    while i < len(text):
        char = text[i]
        if text.startswith("=>", i):
            out.append("=>")
            i += 2
            continue
        if char in "(<[{":
            depth += 1
        elif char in ")>]}":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and (char in ";,=?:" or text.startswith(("||", "&&"), i)):
            break
        out.append(char)
        i += 1
    return re.sub(r"\s+", " ", "".join(out)).strip()


def shapes(code: str, comment: str) -> list[tuple[str, str]]:
    """Each cast and suppression on one line, from split(), as (shape, the reason the
    line itself gives)."""
    found = []
    if match := SUPPRESSION.search(comment):
        if match.group(1):
            found.append((match.group(1), match.group(2).strip()))
        elif match.group(3):
            rules, _, why = match.group(4).partition("--")
            rules = ", ".join(sorted(rule.strip() for rule in rules.split(",") if rule.strip()))
            found.append((f"{match.group(3)} {rules}".strip(), why.strip()))
        else:
            found.append((f"{match.group(5)} {match.group(6)}".strip(), (match.group(7) or "").strip()))
    if ALIAS.match(code):
        return found
    reason = comment if comment and WHY.search(comment) and not found else ""
    for match in CAST.finditer(code):
        target = _type(code[match.end():])
        if target:
            operand = (match.group(1) or "…").rsplit(".", 1)[-1]
            found.append((f"{operand} as {target}", reason))
    return found


def _import_lines(lines: list[tuple[str, str]]) -> set[int]:
    """Line numbers inside a multi-line `import {` or `export {` list, where `a as b` is an alias."""
    inside, found = False, set()
    for number, (code, _) in enumerate(lines, 1):
        if re.match(r"\s*(import|export)\b[^;]*\{[^}]*$", code):
            inside = True
        elif inside:
            found.add(number)
            inside = "}" not in code
    return found


def _diff_lines(base: str, head: str):
    """(path, side, line number) for each added (+) and removed (-) line."""
    patch = _git("diff", "--no-color", "--no-ext-diff", "-M", "-U0", f"{base}...{head}", "--", *CODE)
    old_path = new_path = ""
    old_line = new_line = 0
    for raw in patch.splitlines():
        if raw.startswith("--- "):
            old_path = raw[6:] if raw.startswith("--- a/") else ""
        elif raw.startswith("+++ "):
            new_path = raw[6:] if raw.startswith("+++ b/") else ""
        elif raw.startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", raw)
            old_line, new_line = int(match.group(1)), int(match.group(2))
        elif raw.startswith("+") and new_path:
            yield new_path, "+", new_line
            new_line += 1
        elif raw.startswith("-") and old_path:
            yield old_path, "-", old_line
            old_line += 1


class _Files:
    """Each file at a revision, split() once."""

    def __init__(self, rev: str):
        self.rev, self.cache = rev, {}

    def lines(self, path: str) -> list[tuple[str, str]]:
        if path not in self.cache:
            text = _git("cat-file", "-p", f"{self.rev}:{path}", check=False)
            split_lines = split(text)
            self.cache[path] = (split_lines, _import_lines(split_lines))
        return self.cache[path][0]

    def hits(self, path: str, number: int) -> list[tuple[str, str]]:
        lines = self.lines(path)
        if not 0 < number <= len(lines):
            return []
        code, comment = lines[number - 1]
        found = [(shape, reason) for shape, reason in shapes(code, comment)
                 if not (" as " in shape and number in self.cache[path][1])]
        above = lines[number - 2] if number >= 2 else ("", "")
        if not above[0].strip() and above[1]:
            suppression = shapes("", above[1])
            # A suppression above with its own reason covers the cast it allows.
            why = suppression[0][1] if suppression else above[1] if WHY.search(above[1]) else ""
            found = [(shape, reason or why) for shape, reason in found]
        return found


def scan(base: str, head: str) -> tuple[list[Group], list[Hit], int]:
    """(groups of new casts and suppressions without a reason, new ones with a reason,
    how many added ones a removal matched as moved or kept)."""
    base_sha = _git("merge-base", base, head).strip()
    old, new_files = _Files(base_sha), _Files(head)
    added, removed = [], Counter()
    for path, side, number in _diff_lines(base, head):
        if side == "-":
            removed.update(shape for shape, _ in old.hits(path, number))
        else:
            added += [Hit(path, number, shape, reason) for shape, reason in new_files.hits(path, number)]
    moved, new = 0, []
    for hit in added:
        if removed[hit.shape]:
            removed[hit.shape] -= 1
            moved += 1
        else:
            new.append(hit)
    groups: dict[str, Group] = {}
    for hit in new:
        if not hit.reason:
            groups.setdefault(hit.shape, Group(hit.shape)).new.append(hit)
    _count_twins(base_sha, groups)
    order = sorted(groups.values(), key=lambda g: (-(len(g.new) + g.same_file + sum(g.same_folder.values())
                                                     + g.elsewhere), g.shape))
    return order, [hit for hit in new if hit.reason], moved


def _count_twins(base: str, groups: dict[str, Group]) -> None:
    """Each group's twins at the base: same file, same folder, elsewhere."""
    if not groups:
        return
    found = _git("grep", "-n", "-I", "-e", " as ", "-e", "@ts-", "-e", "eslint-disable", "-e", "oxlint-disable",
                 "-e", "biome-ignore", base, "--", *CODE, check=False)
    for row in found.splitlines():
        parts = row.split(":", 3)
        if len(parts) < 4:
            continue
        path, text = parts[1], parts[3]
        (code, comment), = split(text) or [("", "")]
        if re.match(r"\s*\*", text):
            continue  # a JSDoc line
        for shape, _ in shapes(code, comment):
            if (group := groups.get(shape)) is None:
                continue
            files = {hit.path for hit in group.new}
            if path in files:
                group.same_file += 1
            elif str(PurePosixPath(path).parent) in {str(PurePosixPath(p).parent) for p in files}:
                group.same_folder[path] += 1
            else:
                group.elsewhere += 1


def _sites(hits: list[Hit]) -> str:
    by_file: dict[str, list[int]] = defaultdict(list)
    for hit in hits:
        by_file[hit.path].append(hit.line)
    return "; ".join(f"{path}:{','.join(map(str, lines))}" for path, lines in by_file.items())


def report(base: str, head: str) -> str:
    groups, reasoned, moved = scan(base, head)
    lines = [f"New casts and suppressions in {base}...{head}, with `as const`, aliases, and {moved} moved or kept "
             "left out:"]
    if not groups and not reasoned:
        lines.append("none")
    for group in groups:
        folder = sum(group.same_folder.values())
        twins = group.same_file + folder + group.elsewhere
        near = ", ".join(f"{PurePosixPath(p).name} {n}" for p, n in group.same_folder.most_common(4))
        lines.append(f"- `{group.shape}` · {len(group.new)} new at {_sites(group.new)} · twins at base: "
                     f"{group.same_file} in the same file, {folder} in the same folder{f' ({near})' if near else ''}, "
                     f"{group.elsewhere} elsewhere")
        if len(group.new) + twins > 1:
            lines.append(f"  → {len(group.new) + twins} copies, one cause: one finding whose fix is that cause, such "
                         "as the type where the value is made")
    if reasoned:
        lines.append("With a written reason (a finding only if the reason doesn't hold):")
        lines += [f"- `{hit.shape}` · {hit.path}:{hit.line} · reason: {hit.reason[:120]}" for hit in reasoned]
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: casts.py <base> <head>")
    print(report(sys.argv[1], sys.argv[2]))
