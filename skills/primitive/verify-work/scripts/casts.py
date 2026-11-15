#!/usr/bin/env python3
"""Lists the casts and suppressions a diff adds, for verify-work's Slop check, with each
one's twins: the same cast or suppression already in the code at the base.

Usage: casts.py <base> <head>   (run inside the repo; reviews base...head)

What it lists, in TypeScript and JavaScript files, tests included:
- a cast `<operand> as <Type>`, other than `as const`, an import or export alias, and
  text inside a string, template, regular expression, or comment (code inside a
  template's `${}` counts);
- a type suppression: `@ts-expect-error`, `@ts-ignore`, `@ts-nocheck`;
- a lint suppression: `eslint-disable*`, `oxlint-disable*`, `biome-ignore`;
  each only where it starts its comment, as the tools read it.

What it leaves out:
- a moved or kept one: the diff removes the same cast (the same operand and type) or
  suppression elsewhere, in any file, so a move, a rename, a rewrite that keeps the cast, or a reason added to an
  existing disable isn't new.
- a shape text can't see: guards, fallbacks, swallowed errors, `!` non-null assertions.
  An audit of one team's merged history (Nov 2026) found text matching sees casts and
  suppressions, and 39% of its hits were moved or kept code, which this script leaves out.

A new one with a written reason is listed apart, since the reason is the call to judge:
a suppression's own description (`-- why`, `biome-ignore <rule>: why`, text after
`@ts-expect-error`); for a cast, a comment on its line or the line above that says why it
casts (it names the cast, a type, or an approval), or the description of a type
suppression, or of a lint rule about casts or types, on its line or the line above.

Twins group by shape: the operand's last name and the type for a cast (`sql as never`,
whether `sql` or `target.sql`), the directive and its rules for a suppression. Each group
counts its twins at the base in the same file, in the same folder, and elsewhere, each
file read as the new ones are. A twin is the cause spreading,
not a precedent: in the same audit, `sql as never` grew from 0 to 99 casts across one
repo's check files in two weeks, excused each time because the file already used it."""
from __future__ import annotations

import codecs
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

CODE = ("*.ts", "*.tsx", "*.mts", "*.cts", "*.js", "*.jsx", "*.mjs", "*.cjs")
CAST = re.compile(r"(?:([\w$][\w$.]*)|[)\]}'\"`!])\s*\bas\s+(?!const\b)(?=[\w$({\[<'\"`])")
# An import or export clause, where `as` renames: `import { a as b }`, `import * as x`, `export { a as b }`.
ALIAS = re.compile(r"\b(?:import|export)\s+(?:type\s+)?(?:[\w$]+\s*,\s*)?(?:\{[^}]*\}|\*\s*as\s+[\w$]+)")
# The first line of an import or export list that goes on to the next lines.
OPEN_LIST = re.compile(r"^\s*(?:import|export)\s+(?:type\s+)?(?:[\w$]+\s*,\s*)?\{[^}]*$")
SUPPRESSION = re.compile(r"(@ts-(?:expect-error|ignore|nocheck))\b:?\s*(.*)|"
                         r"((?:eslint|oxlint)-disable(?:-next-line|-line)?)\b\s*(.*)|"
                         r"(biome-ignore(?:-all|-start)?)\s+([^:]*?)\s*(?::\s*(.*))?$")
# A comment says why a cast is there when it names the cast, a type, or an approval;
# a section heading above an assertion doesn't.
WHY = re.compile(r"\b(cast\w*|as (never|any|unknown)|assert\w*|approv\w*|types?|typed|typing|branded|"
                 r"generic|infer\w*)\b", re.I)
# A suppression explains the casts it allows when it's a type suppression or its rule is about them.
COVERS_CASTS = re.compile(r"^@ts-|assert|cast|type(?!script)|\bany\b", re.I)
# A `/` after one of these opens a regular expression; after a name, number or closer it divides.
REGEX_AFTER = set("(,=:[!&|?{};+-*%~^") | {""}
REGEX_KEYWORDS = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw", "yield",
                  "await", "instanceof"}


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    shape: str  # what twins share: `sql as never`, `eslint-disable-next-line no-console`
    key: str  # what a move keeps: the whole operand for a cast (`target.sql as never`), else the shape
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
    """Each line of a file as (code, comment): code with strings, template text, regular
    expressions and comments blanked, so columns stay put, and the line's comment text.
    Code inside a template's `${}` stays code. Templates and block comments may span lines."""
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    out = []
    stack: list[str] = []  # inside a template's `${`: "{" for its own brace, "{{" for one in its code
    state = ""  # "", "'", '"', "`", "/*", "re", "re["
    last = ""  # the last code token, which tells a regular expression's `/` from a division
    for line in lines:
        code, comment, i = [], [], 0
        while i < len(line):
            char, pair = line[i], line[i:i + 2]
            if state == "/*":
                if pair == "*/":
                    state = ""
                    code.append("  ")
                    i += 2
                    continue
                comment.append(char)
                code.append(" ")
            elif state in ("'", '"', "`", "re", "re["):
                if char == "\\":
                    code.append(" " * len(line[i:i + 2]))
                    i += 2
                    continue
                if state == "`" and pair == "${":
                    stack.append("{")
                    state, last = "", "{"
                    code.append(pair)
                    i += 2
                    continue
                if state == "re" and char == "[":
                    state = "re["
                elif state == "re[" and char == "]":
                    state = "re"
                elif char == state or (state == "re" and char == "/"):
                    state, last = "", char
                    code.append(char)
                    i += 1
                    continue
                code.append(" ")
            elif pair == "//":
                comment.append(line[i + 2:])
                code.append(" " * (len(line) - i))
                break
            elif pair == "/*":
                state = "/*"
                code.append("  ")
                i += 2
                continue
            elif char in "'\"`":
                state = char
                code.append(char)
            elif char == "/" and (last in REGEX_AFTER or last in REGEX_KEYWORDS):
                state = "re"
                code.append(char)
            elif char == "}" and stack and stack[-1] == "{":
                stack.pop()
                state, last = "`", "`"
                code.append(" ")
            else:
                if char == "{" and stack:
                    stack.append("{{")
                elif char == "}" and stack:
                    stack.pop()
                if word := re.match(r"[\w$]+", line[i:]):
                    last = word.group(0)
                    code.append(last)
                    i += len(last)
                    continue
                code.append(char)
                if not char.isspace():
                    last = char
            i += 1
        if state in ("'", '"', "re", "re["):
            state = ""  # these end with their line
        out.append(("".join(code), "".join(comment).strip()))
    return out


def _type_end(text: str) -> int:
    """Where a cast's target type ends in text that starts with it: brackets balance, and a
    closer with no opener, or `;`, `,`, `=`, `?`, `:`, `||`, `&&`, or arithmetic outside
    brackets, ends it."""
    depth, i = 0, 0
    while i < len(text):
        char = text[i]
        if text.startswith("=>", i):
            i += 2
            continue
        if char in "(<[{":
            depth += 1
        elif char in ")>]}":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and (char in ";,=?:+-*/%" or text.startswith(("||", "&&"), i)):
            break
        i += 1
    return i


def _operand_start(code: str, end: int) -> int:
    """Where the operand that ends at `end` starts: a name chain with its calls, indexes,
    `?.` and `!`, or a bracketed or quoted expression."""
    i = end
    while True:
        start = i
        while i and code[i - 1] == "!":
            i -= 1
        if i and code[i - 1] in "'\"`":
            i = max(code.rfind(code[i - 1], 0, i - 1), 0)
        elif i and code[i - 1] in ")]}":
            closer, opener, depth = code[i - 1], {")": "(", "]": "[", "}": "{"}[code[i - 1]], 0
            for i in range(i - 1, -1, -1):
                depth += (code[i] == closer) - (code[i] == opener)
                if depth == 0:
                    break
        while i and (code[i - 1].isalnum() or code[i - 1] in "_$." or code[i - 2:i] == "?."):
            i -= 2 if code[i - 2:i] == "?." else 1
        if i == start:
            return i


def shapes(code: str, comment: str, raw: str = "") -> list[tuple[str, str, str]]:
    """Each cast and suppression on one line, from split() and the line as written, as
    (shape, key, the reason the line itself gives)."""
    found = []
    if match := SUPPRESSION.match(comment.lstrip("*! \t")):  # a tool reads a directive only at the start
        if match.group(1):
            found.append((match.group(1), match.group(1), match.group(2).strip()))
        elif match.group(3):
            rules, _, why = match.group(4).partition("--")
            rules = ", ".join(sorted(rule.strip() for rule in rules.split(",") if rule.strip()))
            shape = f"{match.group(3)} {rules}".strip()
            found.append((shape, shape, why.strip()))
        else:
            shape = f"{match.group(5)} {match.group(6)}".strip()
            found.append((shape, shape, (match.group(7) or "").strip()))
    code = ALIAS.sub(lambda clause: " " * len(clause.group(0)), code)
    if found:  # a suppression on the line
        reason = found[0][2] if COVERS_CASTS.search(found[0][0]) else ""
    else:
        reason = comment if comment and WHY.search(comment) else ""
    raw, at = raw or code, 0
    while match := CAST.search(code, at):
        end = match.end() + _type_end(code[match.end():])
        end = match.end() + len(code[match.end():end].rstrip())  # a trailing comment is blanked in code, not raw
        at = max(end, match.end())  # `x as unknown as T` is one cast
        if target := re.sub(r"\s+", " ", raw[match.end():end]).strip():
            name = (match.group(1) or "…").rsplit(".", 1)[-1]
            operand_end = match.end(1) if match.group(1) else match.start() + 1
            operand = re.sub(r"\s+", " ", raw[_operand_start(code, operand_end):operand_end])
            found.append((f"{name} as {target}", f"{operand} as {target}", reason))
    return found


def _import_lines(lines: list[tuple[str, str]]) -> set[int]:
    """Line numbers inside a multi-line `import {` or `export {` list, where `a as b` is an alias."""
    inside, found = False, set()
    for number, (code, _) in enumerate(lines, 1):
        if OPEN_LIST.match(code):
            inside = True
        elif inside:
            found.add(number)
            inside = "}" not in code
    return found


def _path(header: str) -> str:
    """The path in a `--- a/…` or `+++ b/…` line's rest: Git ends a path that has a space
    with a tab, and quotes one with a quote, backslash, or control character in it."""
    header = header.rstrip("\t")
    if header.startswith('"') and header.endswith('"'):
        header = codecs.escape_decode(header[1:-1].encode())[0].decode(errors="replace")
    return header[2:] if header[:2] in ("a/", "b/") else ""


def _diff_lines(base: str, head: str):
    """(path, side, line number) for each added (+) and removed (-) line."""
    # Pin what a user's diff settings could change: prefixes, context between hunks, relative paths.
    patch = _git("diff", "--no-color", "--no-ext-diff", "--no-relative", "--src-prefix=a/", "--dst-prefix=b/", "-M",
                 "-U0", "--inter-hunk-context=0", f"{base}...{head}", "--", *CODE)
    old_path = new_path = ""
    old_line = new_line = 0
    for raw in patch.splitlines():
        if raw.startswith("--- "):
            old_path = _path(raw[4:])
        elif raw.startswith("+++ "):
            new_path = _path(raw[4:])
        elif raw.startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", raw)
            old_line, new_line = int(match.group(1)), int(match.group(2))
        elif raw.startswith("+") and new_path:
            yield new_path, "+", new_line
            new_line += 1
        elif raw.startswith("-") and old_path:
            yield old_path, "-", old_line
            old_line += 1
        elif raw.startswith(" "):
            old_line, new_line = old_line + 1, new_line + 1


class _Files:
    """Each file at a revision, split() once."""

    def __init__(self, rev: str):
        self.rev, self.cache = rev, {}

    def lines(self, path: str) -> list[tuple[str, str]]:
        if path not in self.cache:
            text = _git("cat-file", "-p", f"{self.rev}:{path}")
            split_lines = split(text)
            self.cache[path] = (split_lines, _import_lines(split_lines), text.split("\n"))
        return self.cache[path][0]

    def _suppressed(self, path: str, number: int, shape: str) -> str:
        """A suppression's move key: the directive and the code it covers, so moving it keeps
        it and putting it over different code doesn't."""
        directive = shape.split()[0]
        if directive in ("@ts-nocheck", "biome-ignore-all", "biome-ignore-start") or directive.endswith("-disable"):
            return shape  # it covers the file or a range
        line = number if directive.endswith("disable-line") else number + 1
        raws = self.cache[path][2]
        return f"{shape} → {' '.join(raws[line - 1].split()) if line <= len(raws) else ''}"

    def hits(self, path: str, number: int) -> list[tuple[str, str, str]]:
        lines = self.lines(path)
        if not 0 < number <= len(lines):
            return []
        code, comment = lines[number - 1]
        raw = self.cache[path][2][number - 1]
        if re.search(r"\bas\s*$", code) and number < len(lines):  # the type starts on the next line
            after = lines[number][0]
            lead = len(after) - len(after.lstrip())
            cut = lead + _type_end(after[lead:])
            code, raw = f"{code} {after[:cut]}", f"{raw} {self.cache[path][2][number][:cut]}"
        found = [(shape, self._suppressed(path, number, shape) if SUPPRESSION.match(shape) else key, reason)
                 for shape, key, reason in shapes(code, comment, raw)
                 if not (" as " in shape and number in self.cache[path][1])]
        above = lines[number - 2] if number >= 2 else ("", "")
        if not above[0].strip() and above[1]:
            suppression = shapes("", above[1])
            if suppression:  # its reason covers a cast it allows
                why = suppression[0][2] if COVERS_CASTS.search(suppression[0][0]) else ""
            else:
                why = above[1] if WHY.search(above[1]) else ""
            # A suppression's reason is only its own description.
            found = [(shape, key, reason or ("" if SUPPRESSION.match(shape) else why)) for shape, key, reason in found]
        return found


def scan(base: str, head: str) -> tuple[list[Group], list[Hit], int]:
    """(groups of new casts and suppressions without a reason, new ones with a reason,
    how many added ones a removal matched as moved or kept)."""
    base_sha = _git("merge-base", base, head).strip()
    old, new_files = _Files(base_sha), _Files(head)
    added, removed = [], Counter()
    for path, side, number in _diff_lines(base, head):
        if side == "-":
            removed.update(key for _, key, _ in old.hits(path, number))
        else:
            added += [Hit(path, number, *hit) for hit in new_files.hits(path, number)]
    moved, new = 0, []
    for hit in added:
        if removed[hit.key]:
            removed[hit.key] -= 1
            moved += 1
        else:
            new.append(hit)
    groups: dict[str, Group] = {}
    for hit in new:
        if not hit.reason:
            groups.setdefault(hit.shape, Group(hit.shape)).new.append(hit)
    _count_twins(old, groups)
    order = sorted(groups.values(), key=lambda g: (-(len(g.new) + g.same_file + sum(g.same_folder.values())
                                                     + g.elsewhere), g.shape))
    return order, [hit for hit in new if hit.reason], moved


def _count_twins(base: _Files, groups: dict[str, Group]) -> None:
    """Each group's twins at the base: same file, same folder, elsewhere. `git grep` picks
    the files that could hold one, and each is read whole, as the new ones are."""
    if not groups:
        return
    patterns = {r"(^|[^[:alnum:]_$])as[[:space:]]*$"}  # a cast whose type is on the next line
    for shape in groups:
        if SUPPRESSION.match(shape):
            patterns.add(_ere(shape.split()[0]))
        else:  # the type's first word, after any space
            patterns.add(r"as[[:space:]]+" + _ere(re.match(r"[\w$]+|.", shape.split(" as ", 1)[1]).group(0)))
    listed = _git("grep", "-l", "-z", "-I", "-E", "|".join(sorted(patterns)), base.rev, "--", *CODE, check=False)
    for entry in filter(None, listed.split("\0")):
        path = entry.removeprefix(f"{base.rev}:")
        for number in range(1, len(base.lines(path)) + 1):
            for shape, _, _ in base.hits(path, number):
                if (group := groups.get(shape)) is None:
                    continue
                files = {hit.path for hit in group.new}
                if path in files:
                    group.same_file += 1
                elif str(PurePosixPath(path).parent) in {str(PurePosixPath(p).parent) for p in files}:
                    group.same_folder[path] += 1
                else:
                    group.elsewhere += 1


def _ere(text: str) -> str:
    return re.sub(r"([.\[\](){}*+?|^$\\])", r"\\\1", text)


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
