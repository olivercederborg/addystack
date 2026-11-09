"""A Bash command's own syntax, for bash-rewrite.py and no-foreground-waits.py: its quoted
text and heredoc bodies masked at the same offsets, and a time limit on each `until` or
`while` loop that sleeps.

no-foreground-waits denied 294 such loops from Oct 26 to Nov 9, 2026 ("no upper bound"),
and 88% passed on the retry, about 3 s later. bash-rewrite now puts a guard,
`[ "$SECONDS" -lt D ] || { echo …; exit 124; };`, in front of such a loop's condition, so the
loop runs as written, and the body sees the condition's status, once per pass, until the
command has run D seconds, and then the command ends with status 124 and a line on stderr.
$SECONDS counts from the start of the shell the Bash tool runs the command in, so one limit
covers every loop and the commands before them. D is the call's timeout (at most the
2-minute default) less 10 seconds and less the sleeps in one pass, so the last pass still
ends inside it.

It bounds only the forms it knows, and a command with any other sleeping loop keeps
no-foreground-waits' deny, all its loops unchanged. Each waiting loop must stand alone, with
nothing around it but `;`, `&&`, `||`, and redirects, since `exit` in a pipe, `$(…)`, a
subshell, a compound command, or the background ends only that part; hold no other loop;
and sleep only `sleep N`, N a plain number under a minute, leaving at least 20 seconds. The
command must not hide `sleep`, `while`, `until`, `select`, or `eval` in quoted text or a
heredoc, use backticks, `eval`, or a function, set SECONDS, run in the background, or name a
PR or CI tool, host, or API, whose waits watch_pull_request owns. Known limits: a condition
that hangs, such as a `curl` with no timeout, isn't cut short, nor is a loop in a script the
command runs, and CI polled through an API this module doesn't name runs bounded."""
import itertools, re

# Seconds before the Bash tool's timeout that a bounded loop gives up, and its 2-minute default.
MARGIN, DEFAULT_TIMEOUT = 10, 120
# The fewest seconds a bounded loop may get.
LEAST = 20
GUARD = '[ "$SECONDS" -lt '
GUARD_TEXT = re.compile(r'\[ "\$SECONDS" -lt (\d+) \] \|\| \{ echo "gave up waiting: the command ran \1s, the limit '
                        r'bash-rewrite\.py sets" >&2; exit 124; \};')
# A command that names a PR or CI tool, host, or API anywhere, whose waits watch_pull_request
# owns, or that sets the clock the guard reads, keeps its loops as written.
UNREADABLE = re.compile(r"(?<![\w.-])(?:gh|glab|hub)(?![\w.-])|\bgit\s+(?:ls-remote|fetch|pull)\b|github|gitlab"
                        r"|bitbucket|circleci|buildkite|jenkins|travis|dev\.azure|/api/v\d+/|check[-_](?:runs|suites)"
                        r"|/statuses/|/pulls?/|merge_requests|/pipelines\b|/actions/runs\b", re.I)
CLOCK = re.compile(r"\bSECONDS\b")
# A function definition, whose loop runs wherever it's called, maybe in a pipe, and `eval`.
FUNCTION = re.compile(r"\w\s*\(\s*\)\s*[{(]|\bfunction\s+\w")
EVAL = re.compile(r"(?<![\w$-])eval(?![\w-])")
WAIT = re.compile(r"(?<![\w$-])(?:until|while)(?![\w-])(?!\s+(?:IFS=\S*\s+)?read\b)")
# Any loop word, wherever it stands, so a loop the pairing can't see still counts.
LOOP_WORD = re.compile(r"(?<![\w$-])(?:for|select|while|until)(?![\w-])")
ANY_SLEEP = re.compile(r"(?<![\w$-])sleep(?![\w-])")
# `sleep N` with one plain number and nothing after it but the command's end: not `1.5m`, not `1 59`.
PLAIN_SLEEP = re.compile(r"(?<![\w$-])sleep\s+(\d+(?:\.\d+)?)(?=\s*(?:\Z|[;\n&|)]))")
# Words that, in quoted text or a heredoc, as `bash -c '…'` or `"$(…)"` runs it, could hide
# a loop or a sleep from the pass's count.
QUOTABLE = re.compile(r"(?<![\w$-])(?:sleep|while|until|select|eval)(?![\w-])")
# The words and braces that open and close a compound command, and parentheses, `$(` included.
TOKEN = re.compile(r"(?<![\w$-])(for|select|while|until|do|done|if|fi|case|esac)(?![\w-])|(?<!\$)[{}]|\(|\)")
LOOPS = ("for", "select", "while", "until")
CLOSES = {"done": LOOPS, "fi": ("if",), "esac": ("case",), "}": ("{",)}


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


def _top_level_loops(code):
    """{keyword start: `done` end} for each loop in masked code that stands alone: outside
    every parenthesis, `$(…)`, and compound command, with nothing piped into or out of it
    and not sent to the background, so `exit` in its condition ends the whole command."""
    found, stack, depth = {}, [], 0
    for match in TOKEN.finditer(code):
        text, word = match.group(), match.group(1) or match.group()
        if text in "()":
            depth += 1 if text == "(" else -1
        elif not _starts_command(code, match.start()):
            continue
        elif word in LOOPS + ("if", "case", "{"):
            stack.append({"word": word, "start": match.start(), "depth": depth, "do": False, "alone": not stack})
        elif word == "do":
            waiting = [f for f in stack if f["depth"] == depth and f["word"] in LOOPS and not f["do"]]
            if waiting:
                waiting[-1]["do"] = True
        else:
            ready = [f for f in stack if f["depth"] == depth and f["word"] in CLOSES[word] and (word != "done" or f["do"])]
            if ready:
                frame = ready[-1]
                del stack[stack.index(frame):]
                if word == "done" and frame["alone"] and frame["depth"] == 0:
                    found[frame["start"]] = match.end()
    return {start: end for start, end in found.items()
            if re.search(r"(?:\A|[;\n]|&&|\|\|)\s*(?:!\s*)?\Z", code[:start])
            and re.match(r"(?:\s*(?:(?<!\w)\d+)?(?:_>{1,2}|[<>]{1,3}_?)\s*[^\s;&|()<>]+)*\s*(?:\Z|[;\n]|&&|\|\|)",
                         code[end:])}


def _count(pattern, text):
    return len(re.findall(pattern, text))


def unguarded(text):
    """Whether text holds an `until` or `while` (not `while read`) that the guard doesn't
    directly follow, anywhere, quoted text included."""
    return any(not GUARD_TEXT.match(text[match.end():].lstrip()) for match in WAIT.finditer(text))


def bound_waits(command, timeout_ms=None):
    """(insertions, notes) putting the guard the module docstring describes before the
    condition of every `until` or `while` loop that sleeps, or none when any such loop
    falls outside the forms it knows; the hooks then deny the command as before."""
    code = shell_code(command)
    # A `)` that closes nothing, such as a `case` pattern's `a)`, can make a subshell's loop
    # look like it stands alone, as can `\)` or `${x%)}` with a `(` that makes up for it.
    depths = itertools.accumulate(1 if c == "(" else -1 for c in code if c in "()")
    if (UNREADABLE.search(command) or CLOCK.search(command) or "`" in code or FUNCTION.search(code)
            or EVAL.search(code) or _count(QUOTABLE, command) != _count(QUOTABLE, code)
            or min(depths, default=0) < 0 or re.search(r"\\[()]|\$\{[^}]*[()]", code)):
        return [], []
    limit = min(timeout_ms / 1000 if isinstance(timeout_ms, (int, float)) and not isinstance(timeout_ms, bool)
                and timeout_ms > 0 else DEFAULT_TIMEOUT, DEFAULT_TIMEOUT) - MARGIN
    alone, edits, notes = _top_level_loops(code), [], []
    for match in WAIT.finditer(code):
        start = match.start()
        end = alone.get(start)
        loop = code[start:end] if end else ""
        sleeps = [float(s) for s in PLAIN_SLEEP.findall(loop)]
        seconds = int(limit - -(-sum(sleeps) // 1))
        # Every waiting loop stands alone, holds no other loop, sleeps only for plain numbers
        # under a minute (so one pass's length is known), and runs no shell on quoted text.
        if (not sleeps or _count(LOOP_WORD, loop) != 1 or len(sleeps) != _count(ANY_SLEEP, loop)
                or max(sleeps) >= 60 or seconds < LEAST):
            return [], []
        keyword_end = start + len(match.group())
        edits.append((keyword_end, 0, f' {GUARD}{seconds} ] || {{ echo "gave up waiting: the command ran {seconds}s,'
                                      f' the limit bash-rewrite.py sets" >&2; exit 124; }};'))
        notes.append(f"gave the `{match.group()}` loop a guard that exits 124 once the command has run {seconds}s; "
                     "run a longer wait with run_in_background or Monitor")
    return edits, notes
