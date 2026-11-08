#!/usr/bin/env python3
"""Fails when a Markdown link in the kit points at a file or heading that doesn't exist.

Each tracked .md file's relative links, `[text](path)` and `[text](path#heading)`, must
resolve from that file's folder, and a `#heading` must match a heading in the target, by
GitHub's anchor rules. Links with a scheme (https:, mailto:) and links inside fenced code
blocks or code spans are examples, not links, so they're skipped. A link that starts with
`{{kit}}/` resolves from the addystack skill's folder, where render.py points it. A file
that's only a copy source (scripts/copies.txt names it and it lives outside skills/) is
checked through its copies, since its links are written for where the copies live.

Files: git's tracked .md files in a checkout, otherwise every .md file under the kit.

Outside the check: docs/ (history and plans), evals/ fixtures, and shared/, whose files
are all sources written for where their copies or format pointers land.

Usage: scripts/check-links.py   # exit 1 naming each dead link
"""

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
KIT = "skills/primitive/addystack"
SKIPPED = ("docs/", "evals/", "shared/")
LISTS = ("scripts/copies.txt", "maintainer/copies.txt")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")


def tracked():
    """The kit's .md files: git's tracked ones in a checkout, else every one under the kit
    (Dagger loads only the kit's own folders, without .git)."""
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "*.md"], capture_output=True, text=True)
    if result.returncode == 0:
        names = result.stdout.split("\0")
    else:
        names = [str(path.relative_to(ROOT)) for path in ROOT.rglob("*.md")
                 if not {"node_modules", ".git", "sdk", ".venv"} & set(path.parts)]
    return [name for name in names if name and not name.startswith(SKIPPED)]


def copy_sources():
    """Copy sources outside skills/, whose links are written for their copies."""
    sources = set()
    for name in LISTS:
        path = ROOT / name
        if path.is_file():
            for line in path.read_text().splitlines():
                words = line.split("#", 1)[0].split()
                if len(words) == 2 and not words[0].startswith("skills/"):
                    sources.add(words[0])
    return sources


def prose(text, spans=False):
    """The text's lines outside fenced code blocks, with code spans blanked, or with spans
    kept as their text, as GitHub reads a heading for its anchor."""
    lines, fence = [], None
    for line in text.splitlines():
        match = FENCE.match(line)
        if fence:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence) \
                    and not line.strip()[len(match.group(1)):].strip():
                fence = None
            lines.append("")
            continue
        if match:
            fence = match.group(1)
            lines.append("")
            continue
        lines.append(re.sub(r"(`+)((?:(?!\1).)+?)\1", r"\2" if spans else "", line))
    return lines


def anchors(path):
    """GitHub's anchors for path's headings: lowercased, punctuation dropped, spaces to
    hyphens, and a -1, -2 suffix on repeats."""
    seen, found = {}, set()
    for line in prose(path.read_text(), spans=True):
        match = HEADING.match(line)
        if not match:
            continue
        slug = re.sub(r"[^\w\- ]", "", match.group(1).strip().lower()).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        found.add(slug if count == 0 else f"{slug}-{count}")
    found.update(re.findall(r'<a\s+(?:name|id)="([^"]+)"', path.read_text()))
    return found


def dead(name):
    """Each dead link in the tracked file name, as `file:line: link (why)`."""
    path, problems = ROOT / name, []
    for number, line in enumerate(prose(path.read_text()), 1):
        for link in LINK.findall(line):
            # Another placeholder, such as {{user}}, only resolves once rendered.
            if SCHEME.match(link) or "{{" in link.removeprefix("{{kit}}/"):
                continue
            target, _, heading = link.partition("#")
            if target.startswith("{{kit}}/"):
                resolved = ROOT / KIT / target[len("{{kit}}/"):]
            else:
                resolved = (path.parent / target) if target else path
            if not resolved.exists():
                problems.append(f"{name}:{number}: {link} (no such file)")
            elif heading and resolved.suffix == ".md" and heading not in anchors(resolved):
                problems.append(f"{name}:{number}: {link} (no such heading)")
    return problems


def main():
    sources = copy_sources()
    problems = [problem for name in tracked() if name not in sources for problem in dead(name)]
    if problems:
        print("Dead links; point each at a file and heading that exist:", *problems, sep="\n  ")
        return 1
    print("links resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
