#!/usr/bin/env bash
# Renders the --pr rows of a show-me-your-work decision log.
#
#   decisions-table.sh <log> <base>   the PR's Decisions table, Read in code, and Skim, for the
#                                     diff base...HEAD of the repo you run it in: at most 5 rows,
#                                     agent rows first, "+N more in log" for the rest. A row whose
#                                     path or commit isn't in the diff is left out, with a warning.
#   decisions-table.sh --calls <log>  every agent row, one bullet each, for a worker's report.
#
# A plan's D<n>. labels are their table numbers; every other decision is numbered above the
# highest label, in log order. A later row with the same D<n>. or the same text replaces that
# decision in place, so a re-import or a corrected call keeps its number. A label a revised
# plan adds can push an agent row up one.
# Prints nothing when no row is left. Exits 1 on a malformed log (another header, a row whose
# column count differs from the header's, or a ts that isn't a real YYYY-MM-DDTHH:MM:SSZ), and 2
# on usage or a base git can't diff.
set -euo pipefail

usage() { grep -v '^# Copy of ' "$0" | sed -n '4,8p' | sed 's/^# \{0,1\}//' >&2; exit 2; }
if [ "${1:-}" = --calls ]; then
  [ "$#" -eq 2 ] || usage
  mode=calls log="$2" base=""
else
  [ "$#" -eq 2 ] || usage
  mode=table log="$1" base="$2"
fi
[ -f "$log" ] || { echo "decisions-table.sh: no log at $log" >&2; exit 2; }

python3 -I - "$mode" "$log" "$base" <<'PY'
import datetime, re, subprocess, sys, urllib.parse

mode, log, base = sys.argv[1:4]
HEADER = ["ts", "phase", "decision", "why", "evidence", "result"]
CAP = 5


def fail(line, message):
    print(f"decisions-table.sh: {log}:{line}: {message}; write rows with log.sh", file=sys.stderr)
    sys.exit(1)


def real_ts(ts):
    try:
        return re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", ts) and datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False


lines = open(log, encoding="utf-8").read().splitlines()
if not lines:
    fail(1, "empty log")
header = lines[0].split("\t")
if header not in (HEADER, HEADER + ["pr"]):
    fail(1, f"header is not log.sh's ({lines[0]!r})")
rows = []
for number, line in enumerate(lines[1:], start=2):
    cells = line.split("\t")
    if len(cells) != len(header):
        fail(number, f"{len(cells)} columns, header has {len(header)}")
    if not real_ts(cells[0]):
        fail(number, f"ts {cells[0]!r} is not a real YYYY-MM-DDTHH:MM:SSZ")
    row = dict(zip(header, (re.sub(r"^'(?=[=+\-@])", "", cell) for cell in cells)))
    if row.get("pr") in ("you", "agent"):
        rows.append(row)


def decision(row):
    return re.sub(r"^D\d+\.\s*", "", row["decision"])


# One entry per decision, so D<n> means the same call in the plan, the brief, and the table. A
# row joins the entry with its D<n>. or its text and replaces that entry's row, unless it
# re-imports a plan row over a built one.
LABEL = re.compile(r"D(\d+)\.")
labels = {int(m.group(1)) for row in rows if row["phase"] == "plan" and (m := LABEL.match(row["decision"]))}
entries, by_number, by_text, last = [], {}, {}, max(labels, default=0)
for row in rows:
    m = LABEL.match(row["decision"])
    label = int(m.group(1)) if m else None
    text = " ".join(decision(row).lower().split())
    entry = by_number.get(label) or by_text.get(text)
    if entry is None:
        if label not in labels:
            last += 1
        number = label if label in labels else last
        entry = by_number[number] = [number, row]
        entries.append(entry)
    elif not (row["phase"] == "plan" and entry[1]["phase"] != "plan"):
        entry[1] = row
    by_text[text] = entry
# Agent rows first: no human has seen them yet.
entries.sort(key=lambda entry: (entry[1]["pr"] != "agent", entry[0]))

if mode == "calls":
    for _, row in (entry for entry in entries if entry[1]["pr"] == "agent"):
        print(f"- {decision(row)} · {row['why']} · {row['evidence']}")
    sys.exit(0)


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


diff = git("diff", "-z", "--name-only", f"{base}...HEAD")
if diff.returncode:
    print(f"decisions-table.sh: can't diff {base}...HEAD: {diff.stderr.strip()}", file=sys.stderr)
    sys.exit(2)
changed = [path for path in diff.stdout.split("\0") if path]
commits = git("rev-list", f"{base}..HEAD").stdout.split()
head = git("rev-parse", "HEAD").stdout.strip()
merge_base = git("merge-base", base, "HEAD").stdout.strip()
top = git("rev-parse", "--show-toplevel").stdout.strip()
remote = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", git("remote", "get-url", "origin").stdout.strip())


def link(label, url):
    return f"[{label}](https://github.com/{remote.group(1)}/{url})" if remote else label


def code(row):
    """The row's Code cell and its path, or None and what isn't in the diff."""
    if row["phase"] == "plan" and row["evidence"].startswith(("/", "~")) and not row["evidence"].startswith(top + "/"):
        return "plan", None
    # Repo paths relative to the root, and no timestamps, whose HH:MM reads like path:line.
    evidence = re.sub(r"\d{4}-\d\d-\d\dT[\d:.]+Z?", "", row["evidence"].replace(top + "/", ""))
    for path in sorted(changed, key=len, reverse=True):
        if m := re.search(r"(?<![^\s(`'\"])" + re.escape(path) + r":(\d+)", evidence):
            name, line, quoted = path.rsplit("/", 1)[-1], m.group(1), urllib.parse.quote(path)
            if git("cat-file", "-e", f"HEAD:{path}").returncode == 0:
                return link(f"`{name}:{line}`", f"blob/{head}/{quoted}#L{line}"), path
            return link(f"`{name}:{line}` (deleted)", f"blob/{merge_base}/{quoted}#L{line}"), path
    shas = re.findall(r"(?<![0-9a-zA-Z])([0-9a-f]{7,40})(?![0-9a-zA-Z])", evidence)
    sha = shas[0] if shas else None
    full = next((commit for candidate in shas for commit in commits if commit.startswith(candidate)), None)
    if full:
        return link(f"`{full[:7]}`", f"commit/{full}"), None
    if pointer := re.search(r"([^\s:,;`]*[A-Za-z_][^\s:,;`]*):\d+", evidence):
        return None, pointer.group(1).lstrip("(")
    return (None, f"commit {sha}") if sha else ("—", None)


def part(row, prefix):
    for piece in row["why"].split(";"):
        piece = piece.strip()
        if piece.lower().startswith(prefix):
            return piece[len(prefix):].strip() or "—"
    return "—"


def cell(text):
    return text.replace("|", "\\|")


shown = []
for number, row in entries:
    label, path = code(row)
    if label is None:
        print(f"decisions-table.sh: warning: {path} isn't in {base}...HEAD, so D{number} is left out "
              f"(stale?): {decision(row)}", file=sys.stderr)
        continue
    shown.append((number, row, label, path))
if not shown:
    print(f"decisions-table.sh: no --pr rows to show from {log}", file=sys.stderr)
    sys.exit(0)

more = len(shown) - CAP
shown = shown[:CAP]
numbers = sorted(number for number, *_ in shown)
if numbers == list(range(numbers[0], numbers[-1] + 1)):
    ids = f"D{numbers[0]}–D{numbers[-1]}" if len(numbers) > 1 else f"D{numbers[0]}"
else:
    ids = ", ".join(f"D{number}" for number in numbers)
print(f"**Decisions.** Approving means you agree with {ids}. To push back, comment with the number.")
print()
print("| # | Decision | Decided by | Instead of | Assumes | Code |")
print("|---|---|---|---|---|---|")
for number, row, label, _ in shown:
    by = ("🤖 agent" if row["pr"] == "agent" else "🧑 human") + f" · {row['phase']}"
    print(f"| D{number} | {cell(decision(row))} | {by} | {cell(part(row, 'instead of'))} | "
          f"{cell(part(row, 'assumes'))} | {label} |")
if more > 0:
    print()
    print(f"+{more} more in log.")
read = list(dict.fromkeys(path for *_, path in shown if path))
if read:
    print()
    print("**Read in code:** " + ", ".join(f"`{path}`" for path in read))
skim = [path for path in changed if path not in read]
if skim:
    names = ", ".join(f"`{path}`" for path in skim[:8])
    rest = f", +{len(skim) - 8} more" if len(skim) > 8 else ""
    print()
    print(f"**Skim:** {len(skim)} file{'' if len(skim) == 1 else 's'}: {names}{rest}")
PY
