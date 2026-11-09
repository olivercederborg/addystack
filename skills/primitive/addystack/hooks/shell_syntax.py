"""A Bash command's own syntax, for bash-rewrite.py and no-foreground-waits.py: its quoted
text and heredoc bodies masked at the same offsets, and a time limit on each `until` or
`while` loop that sleeps.

no-foreground-waits denied 294 such loops from Oct 26 to Nov 9, 2026 ("no upper bound"),
and 88% passed on the retry, about 3 s later. bash-rewrite now runs each as
`{ _wait_end1=$((SECONDS + D)); until …; do <guard>; …; done; }`, where the guard ends the
command with status 124 and a line on stderr once D seconds pass, so the loop and its
condition run as written, once per pass, until then. D is 110 seconds less the sleeps in
one pass, so the last pass still ends inside the Bash tool's 2-minute timeout.
no-foreground-waits still denies a loop that has no guard: one that polls a PR or CI
(`gh pr`, `gh run`, `gh api`), whose waits watch_pull_request owns; one whose pass sleeps
a minute or more, or more than 80 seconds in all; and one in quoted text, a heredoc, or a
script the command runs, which this module doesn't read."""
import re

# Seconds a bounded loop may run, under the Bash tool's 120-second default timeout.
CAP = 110
# The most one pass may sleep, so a loop gets at least 30 seconds.
MOST_PER_PASS = 80
GUARD_NAME = "_wait_end"
POLLS_PR = re.compile(r"\bgh\s+(?:pr|run|api|workflow|stack)\b|\bgit\s+ls-remote\b|github\.com")
SLEEP = re.compile(r"\bsleep\s+(\d+(?:\.\d+)?)\b")
# A loop keyword where a command starts; `while read` paces a list, so it's left alone.
LOOP = re.compile(r"(?:^|(?<=[;&|({\n]))\s*(?:(?:then|do|else|!)\s+)?((?:until|while)\b)"
                  r"(?!\s+(?:IFS=\S*\s+)?read\b)")
DO_DONE = re.compile(r"(?<![\w$-])(do|done)(?![\w-])")


def blank(text):
    """text as that many `x`s, newlines too, so a masked copy keeps every offset of the
    original and a quoted line break doesn't read as a new command."""
    return "x" * len(text)


def mask_heredocs(command, quoted_only):
    """command with each heredoc's body masked, through the line that is its delimiter
    alone (after tabs, for `<<-`), as the shell ends it; `EOF remains` is still body."""
    pattern = r"<<-?\s*(['\"])(\w+)\1" if quoted_only else r"<<-?\s*(['\"]?)(\w+)\1"
    return re.sub(pattern + r"([^\n]*\n)((?:[^\n]*\n)*?\t*\2)(?=\n|$)",
                  lambda m: m.group(0)[:m.start(4) - m.start(0)] + blank(m.group(4)), command, flags=re.S)


def shell_code(command):
    """command with heredoc bodies and quoted text masked, and `&` in redirects too, so
    what's left is the shell's own syntax, at the same offsets."""
    code = mask_heredocs(command, quoted_only=False)
    code = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", lambda m: "'" + blank(m.group()[1:-1]) + "'", code)
    # A comment ends its command, and what it says is text; `$#` and `${#a}` aren't comments.
    code = re.sub(r"(?:(?<=[\s;&|(])|^)#[^\n]*", lambda m: ";" * len(m.group()), code, flags=re.M)
    # `2>&1` and `&>` redirect; they don't end a command.
    return re.sub(r"\d?>&\d?|&>", lambda m: m.group().replace("&", "_"), code)


def apply(command, edits):
    """command with each (offset, order, text) insertion made; at one offset, lower order first."""
    for at, _, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        command = command[:at] + text + command[at:]
    return command


def _starts_command(code, at):
    """Whether a word at offset `at` stands where a command starts."""
    before = code[:at].rstrip(" \t")
    return not before or before[-1] in ";\n&|(){}" or re.search(r"(?<![\w-])(?:then|else|do|done|fi|esac)\Z", before)


def _body(code, start):
    """(end of the loop's `do`, start of its `done`, end of it) for the loop whose keyword
    ends at start, or None when its `do` or matching `done` isn't found."""
    depth, do_end = 0, None
    for match in DO_DONE.finditer(code, start):
        if not _starts_command(code, match.start()):
            continue
        if match.group(1) == "do":
            depth += 1
            do_end = do_end or match.end()
        else:
            depth -= 1
            if depth == 0 and do_end:
                return do_end, match.start(), match.end()
    return None


def bound_waits(command):
    """(insertions, notes) giving each `until` or `while` loop that sleeps a time limit, as
    the module docstring says; a loop it leaves alone gets none."""
    code = shell_code(command)
    edits, notes = [], []
    for match in LOOP.finditer(code):
        found = _body(code, match.end(1))
        if not found:
            continue
        do_end, done_start, done_end = found
        sleeps = [float(s) for s in SLEEP.findall(code[do_end:done_start])]
        if not sleeps or max(sleeps) >= 60 or sum(sleeps) > MOST_PER_PASS:
            continue
        if POLLS_PR.search(command[match.start(1):done_end]):
            continue
        name, seconds = f"{GUARD_NAME}{len(notes) + 1}", CAP - int(-(-sum(sleeps) // 1))
        guard = (f' [ "$SECONDS" -lt "${name}" ] || {{ echo "gave up waiting after {seconds}s, the limit'
                 f' bash-rewrite.py set" >&2; exit 124; }};')
        edits += [(match.start(1), 0, f"{{ {name}=$((SECONDS + {seconds})); "), (do_end, 0, guard),
                  (done_end, 0, "; }")]
        notes.append(f"gave the `{match.group(1)}` loop a {seconds}-second limit, after which the command "
                     "exits 124; run a longer wait with run_in_background or Monitor")
    return edits, notes
