#!/usr/bin/env python3
"""Checks the example replies in every SKILL.md against reply-shape's layout rules.

Agents copy a skill's example replies more readily than its rules, so an example that
still shows an old shape brings that shape back. An example reply is a block fenced
with four or more backticks. Inside one, this fails on:

- a Needs you item that opens a plain sentence with a bold label (`**Review** the …`)
  instead of a list item (`- **Review**: …`);
- a fold summary that is only "Details", which says nothing about what's inside;
- a `**Next**` or `**Done**` ending without the closing rule (a blank line, `---`, and a
  blank line) above it;
- a `---` directly under a line of text, which Markdown turns into a heading;
- an idioms check that doesn't name its lenses, as in `✅ idioms (typescript-style)`;
- a Next, Needs you, or Done line citing a number without its name, as in "keep item 48",
  which `hooks/bare_references.py` also sends back in live replies;
- a reply whose headline and notes reach 60 words, where reply-shape keeps them under 60, as `hooks/reply_budget.py`
  counts them in live replies; only a block that opens with a status marker is a reply;
- a turn block that doesn't parse (`hooks/turn_block.py`), when the example carries one.
  An example without one passes, and so does one shown in code;
- a third Next option, `c`, where replies.md allows two, as `hooks/routine_stop.py` logs
  in live replies;
- a decision card whose Pick cites no source, as `hooks/reply_budget.py` sends back in live
  replies.
- a fact table past reply-shape's limits, as `hooks/reply_budget.py` logs in live
  replies, with each value held to the 20-word target;
- a merge option whose text isn't the plain request merge-gate takes as a go, or names a
  PR merge-gate places in no repo, as `hooks/reply_budget.py` sends back in live replies.

It checks every SKILL.md, plus `replies.md` and reply-shape's references.

Usage: scripts/check_examples.py [SKILL.md ...]   # exit 1 on any problem
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "skills" / "primitive" / "addystack" / "hooks"))
import bare_references, reply_budget, turn_block  # noqa: E402

LABEL_SENTENCE = re.compile(r"^\*\*(Decide|Review|Do)\*\* ")
ENDING = re.compile(r"^\*\*(Next|Done)\*\*")
BARE_IDIOMS = re.compile(r"✅ idioms(?! \()")
THIRD_OPTION = re.compile(r"^- (?:\*\*)?`c` →")
MARKER = re.compile(r"\s*[✅🟡🔴⏳]")


def example_blocks(lines):
    """Yields (first line number, lines) for each block fenced with 4+ backticks."""
    fence, start, block = None, 0, []
    for number, line in enumerate(lines, 1):
        match = re.match(r"^(`{4,})", line)
        if fence is None and match:
            fence, start, block = match.group(1), number + 1, []
        elif fence is not None and line.startswith(fence) and not line.strip("`"):
            yield start, block
            fence = None
        elif fence is not None:
            block.append(line)


def check_block(start, block):
    problems = []
    in_code = False
    for offset, line in enumerate(block):
        number = start + offset
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if LABEL_SENTENCE.match(line):
            problems.append((number, "Needs you item should be a list item, as in `- **Review**: …`"))
        if "<summary>Details</summary>" in line:
            problems.append((number, "fold summary should name what's inside, not just Details"))
        if ENDING.match(line) and offset > 0:
            above = block[max(0, offset - 3):offset]
            if above != ["", "---", ""]:
                problems.append((number, "Next or Done needs the closing rule above it: blank, ---, blank"))
        if BARE_IDIOMS.search(line):
            problems.append((number, "idioms check should name its lenses, as in `✅ idioms (typescript-style)`"))
        if THIRD_OPTION.match(line):
            problems.append((number, "Next offers a third option; replies.md allows `a` and `b`"))
        if line == "---" and offset > 0 and block[offset - 1].strip():
            problems.append((number, "--- right under text makes that text a heading; add a blank line"))
    names = {}
    carried = [offset for offset, (line, fenced) in enumerate(zip(block, turn_block.in_fence(block)))
               if not fenced and turn_block.carriers(line)]
    if carried:
        try:
            names = {need.id: need.name for need in turn_block.parse("\n".join(block)).items}
        except turn_block.Malformed as error:
            problems.append((start + carried[0], f"turn block: {error}"))
    text = "\n".join(block)
    if MARKER.match(text) and reply_budget.over(reply_budget.words(text)):
        problems.append((start, f"headline and notes run {reply_budget.words(text)} words; "
                                f"reply-shape keeps them under {reply_budget.BUDGET}"))
    for clause in reply_budget.fact_problems(text, reply_budget.FACT_WORDS):
        problems.append((start, f"the fact table: {clause}"))
    if reply_budget.unsourced(text):
        problems.append((start, "the decision card's Pick cites no source; add a **Source** line"))
    for option in reply_budget.unplain(text):
        problems.append((start, f"merge option `{option.key}` isn't the plain request merge-gate takes as a go"))
    for option, refs in reply_budget.unplaced(text):
        problems.append((start, f"merge option `{option.key}` names a PR merge-gate places in no repo: "
                                + " · ".join(f"{ref} {why}" for ref, why in refs)))
    for problem in bare_references.problems(text, names):
        # The cited line ends the problem; the longest match, in case one line ends another.
        offset = max((i for i, line in enumerate(block) if line.strip() and problem.endswith(f" in: {line.strip()}")),
                     key=lambda i: len(block[i].strip()))
        ref = problem[:-len(f" in: {block[offset].strip()}")]
        problems.append((start + offset, f"{ref} needs its short name beside it, as in \"48 (optional email variables)\""))
    return problems


def check(path):
    lines = path.read_text().split("\n")
    return [
        (number, message)
        for start, block in example_blocks(lines)
        for number, message in check_block(start, block)
    ]


def main(argv):
    root = pathlib.Path(__file__).resolve().parent.parent
    # The checkout's replies.md is the maintainer's, so only the workshop has one.
    paths = [pathlib.Path(arg) for arg in argv] or [
        *sorted(root.glob("skills/*/*/SKILL.md")), *[path for path in [root / "replies.md"] if path.is_file()],
        *sorted(root.glob("skills/optional/reply-shape/references/*.md"))]
    failed = False
    for path in paths:
        for number, message in check(path):
            failed = True
            where = path.relative_to(root) if path.is_relative_to(root) else path
            print(f"{where}:{number}: {message}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
