"""A Bash command's own syntax, for bash-rewrite.py and no-foreground-waits.py: its quoted
text and heredoc bodies masked at the same offsets, and a time limit on each `until` or
`while` loop that sleeps.

no-foreground-waits denied 294 such loops from Oct 26 to Nov 9, 2026 ("no upper bound"),
and 88% passed on the retry, about 3 s later. bash-rewrite now starts each pass of such a
loop with a guard, `[ "$SECONDS" -lt D ] || { echo …; exit 124; }`, so the loop and its
condition run as written, once per pass, until the command has run D seconds, and then the
command ends with status 124 and a line on stderr. $SECONDS counts from the start of the
shell the Bash tool runs the command in, so one limit covers every loop and the commands
before them. D is the call's timeout (at most the 2-minute default) less 10 seconds and
less the sleeps in one pass, so the last pass still ends inside it.

A loop keeps no-foreground-waits' deny when the guard can't hold: in a pipe, `$(…)`, a
subshell, or the background, where `exit` ends only that part (any lone `|` or `&` outside
the loop counts); in quoted text, a heredoc, or a script the command runs; when it runs
`gh` or polls GitHub, whose waits watch_pull_request owns; when one pass sleeps a minute or
more, or leaves under 20 seconds; and in a call sent to the background. Known limit: a
condition that hangs, such as a `curl` with no timeout, isn't cut short."""
import re

# Seconds before the Bash tool's timeout that a bounded loop gives up, and its 2-minute default.
MARGIN, DEFAULT_TIMEOUT = 10, 120
# The fewest seconds a bounded loop may get.
LEAST = 20
GUARD = '[ "$SECONDS" -lt '
POLLS_GITHUB = re.compile(r"(?<![\w.-])gh(?![\w.-])|\bgit\s+ls-remote\b|github\.com")
SLEEP = re.compile(r"\bsleep\s+(\d+(?:\.\d+)?)\b")
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


def loops(code):
    """(keyword, keyword start, `do` end, `done` start, in main shell) for each loop in masked
    code, each keyword paired with its own `do` and `done` at its own paren depth. A loop is
    in the main shell when it isn't in parentheses or `$(…)`, and the outermost compound
    command holding it (itself, a loop, `if`, `case`, or `{ … }`) is neither piped nor sent to
    the background, since `exit` then ends only that part."""
    found, stack, depth = [], [], 0
    for match in TOKEN.finditer(code):
        text, word = match.group(), match.group(1) or match.group()
        if text in "()":
            depth += 1 if text == "(" else -1
        elif not _starts_command(code, match.start()):
            continue
        elif word in LOOPS + ("if", "case", "{"):
            stack.append({"word": word, "start": match.start(), "depth": depth, "do": None, "end": None,
                          "outer": stack[0] if stack else None})
        elif word == "do":
            waiting = [f for f in stack if f["depth"] == depth and f["word"] in LOOPS and f["do"] is None]
            if waiting:
                waiting[-1]["do"] = match.end()
        else:
            ready = [f for f in stack if f["depth"] == depth and f["word"] in CLOSES[word] and (word != "done" or f["do"])]
            if ready:
                frame = ready[-1]
                del stack[stack.index(frame):]
                frame.update(end=match.end(), close=match.start())
                if word == "done":
                    found.append(frame)
    result = []
    for frame in found:
        outer = frame["outer"] or frame
        main = (frame["depth"] == 0 and outer["end"] is not None
                and not re.search(r"(?:^|[^|])\|&?\s*\Z", code[:outer["start"]])
                and not re.match(r"(?:\s*\d*[<>_]{1,3}\s*[^\s;&|()<>]+)*\s*(?:\|(?!\|)|&(?!&))", code[outer["end"]:]))
        result.append((frame["word"], frame["start"], frame["do"], frame["close"], main))
    return result


def unguarded(text):
    """Whether text holds a sleeping `until` or `while` loop whose body doesn't start with
    the guard. Any such word counts, in double quotes too, with the `do` and `done` that pair
    with it, where a command starts, past loops nested in its condition or body; one with
    neither is skipped."""
    for keyword in re.finditer(r"(?<![\w$-])(?:until|while)(?![\w-])(?!\s+(?:IFS=\S*\s+)?read\b)", text):
        nested, do_end = 0, None
        for word in re.finditer(r"(?<![\w$-])(for|select|while|until|do|done)(?![\w-])", text):
            if word.start() < keyword.end() or not _starts_command(text, word.start()):
                continue
            if word.group(1) in LOOPS:
                nested += 1
            elif word.group(1) == "do" and not nested and do_end is None:
                do_end = word.end()
            elif word.group(1) == "done" and nested:
                nested -= 1
            elif word.group(1) == "done" and do_end is not None:
                if SLEEP.search(text[do_end:word.start()]) and not text[do_end:].lstrip().startswith(GUARD):
                    return True
                break
    return False


def bound_waits(command, timeout_ms=None):
    """(insertions, notes) putting the guard the module docstring describes at the start of
    each pass of every sleeping `until` or `while` loop it can bound."""
    code = shell_code(command)
    limit = min(timeout_ms / 1000 if isinstance(timeout_ms, (int, float)) and not isinstance(timeout_ms, bool)
                and timeout_ms > 0 else DEFAULT_TIMEOUT, DEFAULT_TIMEOUT) - MARGIN
    edits, notes = [], []
    for keyword, start, do_end, done_start, main in loops(code):
        if keyword not in ("until", "while") or re.match(r"(?:until|while)\s+(?:IFS=\S*\s+)?read\b", code[start:]):
            continue
        body_sleeps = [float(s) for s in SLEEP.findall(code[do_end:done_start])]
        sleeps = [float(s) for s in SLEEP.findall(code[start:done_start])]
        seconds = int(limit - -(-sum(sleeps) // 1))
        if not main or not body_sleeps or max(sleeps) >= 60 or seconds < LEAST:
            continue
        if POLLS_GITHUB.search(command[start:done_start]):
            continue
        edits.append((do_end, 0, f' {GUARD}{seconds} ] || {{ echo "gave up waiting: the command ran {seconds}s,'
                                  f' the limit bash-rewrite.py sets" >&2; exit 124; }};'))
        notes.append(f"gave the `{keyword}` loop a guard that exits 124 once the command has run {seconds}s; "
                     "run a longer wait with run_in_background or Monitor")
    return edits, notes
