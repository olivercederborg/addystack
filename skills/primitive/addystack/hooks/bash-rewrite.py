#!/usr/bin/env python3
"""PreToolUse on Bash: fixes shell mistakes in the command before it runs, through
`updatedInput`, where its two predecessors, pipefail-guard and zsh-colon-modifier, denied
the command and named the fix. Their 187 denials from Oct 20 to 30, 2026 all passed on the
retry, and 73 of the 76 zsh retries were exactly the fix. It's one hook because when two
hooks both return `updatedInput`, the last one wins and the other fix is lost (probed in a
T3 session on Oct 30, 2026).

- **Pipefail.** A `git` or `gh stack` command that changes something, piped into `tail`
  and then chained with `&&`, exits with tail's status, so a failed rebase or restack lets
  the rest of the chain run. Added after a `gh stack add … | tail -1 && cat > …` wrote files
  into another thread's paused rebase. The hook runs that pipeline as `(set -o pipefail;
  …)`, so the rest of the command keeps its own pipe statuses. Piped into `head`, it still
  denies: once head has its lines, the next write kills the git step with SIGPIPE, partway
  through. Reads such as `git log | head -1 && …` pass, and so does a command that sets
  pipefail first, `head` included, as before.
- **zsh history modifiers.** In zsh, an unbraced `$NAME:` before a modifier letter
  (`git show "$ref:apps/x"`) applies `:a`, even inside double quotes, so it reads a
  different path. The hook braces it as `${NAME}:`. No recorded command meant the modifier.
- **PR body check.** `gh pr create` or `gh pr edit` with `--body-file F` runs as
  `{ node …/open-pr/scripts/check-body.mjs F >&2 && gh pr …; }`, so a body whose Mermaid
  doesn't parse, or whose check line counts tests, isn't posted, and check-body's lines say
  why. It runs in the command, not in the hook, because a quarter of the 633 posts from
  Oct 20 to 30 wrote or patched F earlier in the same command; 16 of the 208 bodies posted
  then fail it, and 335 of 558 edits ran no check. `--body` text and `--body-file -` aren't
  checked.
- **Verifier builds and tests.** In a work-verifier fork, a build or test (BUILD_OR_TEST)
  runs with a 600000 ms timeout, the most Bash allows, and one asked to run with
  `run_in_background` or sent there with `&` is denied, unless the command `wait`s for it.
  Bash moves a command past its timeout (2 minutes by default) to the background, and a
  fork's background work stops when it hands back, so the build and the verdict waiting on
  it are lost. That cost tower-app three verdicts on Nov 7 to 8, 2026 (verify-102-2,
  verify-102-4, verify-105-1). pr_watch.py sends a T3 child back for it, but only after the
  fork's run is over, so verify-work starts again, and not at all when the fork's hand-back
  runs to 40 words, as verify-102-2's 56 did; a top-level session's forks get no check.
  Work past 10 minutes still moves, as verify-107-1's and verify-107-4's did, so each note
  says to split it.

In bypass permissions mode the fixed command is allowed; in any other mode it's asked, so
the hook never approves a command the permission rules would have asked about. A deny from
another hook still wins. A subagent's `record-verdict.sh` command, which verdict-stamp.py
rewrites, is denied with the fixes named instead, since only one rewrite would apply. Quoted text and heredoc bodies are data: single quotes and
quoted-delimiter heredocs for zsh, any quote or heredoc for pipefail. The hook nudges a
habit; it isn't a security boundary. Known limits: `|&`, a `\\` line break before the pipe,
git behind a wrapper such as `env` or `sudo`, `set -o pipefail` inside a group that ends
before the pipe, and positional parameters (`$1:a`)."""
import json, os, pathlib, re, shlex, sys

# open-pr's check, copied beside the kit (scripts/copies.txt), so it runs without open-pr installed.
CHECK_BODY = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "check-body.mjs"


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


# Only a command position counts: the start of a line, a list, a group, or a branch or
# loop body (`rg git src | head` searches for git; it doesn't run it).
LEAD = r"(?:^|[;&|({\n])\s*(?:(?:then|do|else|if|elif|while|until|!)\s+)?"
# Writes only, after git's global options, such as `--no-pager` and `-C <path>`.
GIT = (r"git\s+(?:(?:-P|--no-pager|--(?:git-dir|work-tree)=\S+|-[Cc]\s+\S+)\s+)*"
       r"(?:rebase|push|pull|merge|commit|add|rm|mv|reset|restore|checkout|switch"
       r"|cherry-pick|revert|am|fetch|apply|clean|stash(?![\w-])(?!\s+(?:list|show)\b)"
       r"|worktree\s+(?:add|remove|move)|branch(?=[^|;&\n]*\s-(?:[a-zA-Z]*[dDmM]|-(?:delete|move)\b)))(?![\w-])")
STACK = (r"gh\s+stack\s+(?:add|init|rebase|sync|push|submit|modify|merge|unstack|checkout"
         r"|up|down|top|bottom|trunk|switch)\b")
# The pipeline, after any `NAME=value` assignments, up to the `&&` that chains on; a `)`
# that closes an outer group or `$(…)` ends it.
PIPED = re.compile(LEAD + rf"((?:\w+=\S*\s+)*(?:\S*/)?(?:{GIT}|{STACK})[^|;&\n]*\|\s*(tail|head)\b[^;&\n)]*?)\s*(?=\)*\s*&&)")
PIPEFAIL_ON = re.compile(LEAD + r"(?:set\s+-[a-z]*o\s+pipefail|setopt\s+pipe_?fail)\b")
MODIFIER = re.compile(r"(?<![\\$])\$([A-Za-z_][A-Za-z0-9_]*):(?=[aAcehlPqQrstu&])")


def shell_code(command):
    """command with heredoc bodies and quoted text masked, and `&` in redirects too, so
    what's left is the shell's own syntax, at the same offsets."""
    code = mask_heredocs(command, quoted_only=False)
    code = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", lambda m: "'" + blank(m.group()[1:-1]) + "'", code)
    # A comment ends its command, and what it says is text; `$#` and `${#a}` aren't comments.
    code = re.sub(r"(?:(?<=[\s;&|(])|^)#[^\n]*", lambda m: ";" * len(m.group()), code, flags=re.M)
    # `2>&1` and `&>` redirect; they don't end a command.
    return re.sub(r"\d?>&\d?|&>", lambda m: m.group().replace("&", "_"), code)


def pipefail_fixes(command):
    """(insertions, notes, head pipelines) for each piped git write that chains on."""
    code = shell_code(command)
    edits, notes, heads = [], [], []
    for match in PIPED.finditer(code):
        # Pipefail turned on before the pipe, as its own command, protects it; a branch
        # named `fix/pipefail` doesn't.
        if PIPEFAIL_ON.search(code[:match.start(1)]):
            continue
        shown = re.sub(r"\s+", " ", command[match.start(1):match.end(1)])
        if match.group(2) == "head":
            heads.append(shown)
            continue
        opener = " (" if command[:match.start(1)].endswith("(") else "("
        edits += [(match.start(1), 0, opener + "set -o pipefail; "), (match.end(1), 1, ")")]
        notes.append(f"ran `{shown}` under pipefail, so a failure stops the `&&` chain")
    return edits, notes, heads


# `gh pr create|edit … --body-file F` (or `-F F`), after any `NAME=value` assignments, up
# to the end of its command; a `)` that closes an outer group or `$(…)` ends it.
POSTS_BODY = re.compile(LEAD + r"((?:\w+=\S*\s+)*gh\s+pr\s+(?:create|edit)\b(?:\\\n|[^;&|\n)])*?"
                        r"(?:--body-file(?:=|\s+)|-F\s+)([^\s;&|)]+)(?:\\\n|[^;&|\n)])*?)\s*(?=$|[;&|\n)])")


def tool_shell():
    """The shell Claude Code runs the Bash tool in: CLAUDE_CODE_SHELL when set, else SHELL."""
    return os.environ.get("CLAUDE_CODE_SHELL") or os.environ.get("SHELL", "")


def body_check_fixes(command):
    """(insertions, notes) running check-body.mjs on each body file just before it's posted."""
    if not CHECK_BODY.is_file():
        return [], []
    edits, notes = [], []
    for match in POSTS_BODY.finditer(shell_code(command)):
        body = command[match.start(2):match.end(2)]
        if body.strip("'\"") in ("-", "/dev/stdin"):
            continue
        if tool_shell().endswith("zsh") and not body.startswith("'"):
            body = MODIFIER.sub(r"${\1}:", body)  # as modifier_fixes braces the original
        opener = " {" if command[:match.start(1)].endswith(("{", "(")) else "{"
        edits += [(match.start(1), 0, f"{opener} node {shlex.quote(str(CHECK_BODY))} {body} >&2 && "),
                  (match.end(1), 1, "; }")]
        notes.append(f"ran check-body.mjs on {body} before posting it, so a body it rejects isn't posted; "
                     "fix each line it prints and post again")
    return edits, notes


def modifier_fixes(command):
    """(insertions, notes) bracing each `$NAME:` zsh would read as a history modifier."""
    if not tool_shell().endswith("zsh"):
        return [], []
    code = mask_heredocs(command, quoted_only=True)
    code = re.sub(r"'[^']*'", lambda m: "'" + blank(m.group()[1:-1]) + "'", code)
    edits, notes = [], {}
    for match in MODIFIER.finditer(code):
        name = match.group(1)
        edits += [(match.start(1), 0, "{"), (match.end(1), 0, "}")]
        notes.setdefault(name, f"braced `${name}:` as `${{{name}}}:`, since zsh reads "
                               f"`:{command[match.end()]}` as a history modifier")
    return edits, list(notes.values())


# A build or test runner in command position, after any `NAME=value` assignments or a wrapper
# that runs it, such as `taskpolicy -b` or `time`. A repo's own script counts when it's named
# by a relative scripts/ path and its name says build, test, or bench. A path after the
# runner's word (`bun test/server.ts`) runs a file, not the runner.
RUNNER = (r"(?:swift\s+(?:build|test)|xcodebuild|make|(?:\./)?gradlew|gradle|mvn|bazel\s+(?:build|test)"
          r"|(?:cargo|go|dotnet)\s+(?:build|test)|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:test|build)"
          r"|(?:npx\s+|bunx\s+|bun\s+x\s+)?(?:vitest|jest|playwright\s+test|pytest|tsc)"
          r"|python3?\s+(?:-\w+\s+)*-m\s+(?:pytest|unittest)|dagger\s+call"
          r"|(?:(?:ba|z)?sh\s+)?(?:\./)?[Ss]cripts/[\w./-]*(?:build|test|bench)[\w.-]*)(?![\w./-])")
WRAPPER = r"(?:(?:\w+=\S*|taskpolicy\s+-\w+|nice(?:\s+-n\s*-?\d+)?|(?:/usr/bin/)?time(?:\s+-p)?|env|nohup|caffeinate(?:\s+-\w+)*)\s+)*"
BUILD_OR_TEST = re.compile(LEAD + WRAPPER + RUNNER)
VERIFIER = "work-verifier"
# Bash's most; a command past it moves to the background however long its timeout.
LONG = 600000
LOST = ("A work-verifier fork's background work stops when the fork hands back, so this build or test "
        "and the verdict waiting on it would be lost. ")
SPLIT = ("If it could take longer than 10 minutes, split it into batches that each finish under that, "
         "such as by test filter, since Bash moves a longer command to the background too.")


def backgrounded(code):
    """(text, end) for each command in code that a lone `&` sends to the background, its
    group's or pipeline's whole text included, and end the `&`'s offset."""
    starts, found, i = [0], [], 0
    while i < len(code):
        char = code[i]
        if char in "({":
            starts.append(i + 1)
        elif char in ")}" and len(starts) > 1:
            starts.pop()
        elif char in ";\n" or code.startswith("||", i) or code.startswith("&&", i):
            i += 1 if char in ";\n" else 2
            starts[-1] = i
            continue
        elif char == "&":
            found.append((code[starts[-1]:i], i))
            starts[-1] = i + 1
        i += 1
    return found


def verifier_fix(payload, tool_input, command):
    """(deny reason, None) when a work-verifier fork would background a build or test,
    (None, note) when its build or test needs the long timeout, else (None, None)."""
    if payload.get("agent_type") != VERIFIER:
        return None, None
    code = shell_code(command)
    if not BUILD_OR_TEST.search(code):
        return None, None
    if tool_input.get("run_in_background"):
        return f"{LOST}Run it in the foreground with `timeout: {LONG}`. {SPLIT}", None
    # A `wait` after the `&` finishes the job inside the call.
    waits = [match.end() for match in re.finditer(LEAD + r"wait\b", code)]
    if any(BUILD_OR_TEST.search(part) and not any(at > end for at in waits) for part, end in backgrounded(code)):
        return f"`&` puts this build or test in the background. {LOST}Drop the `&`, or `wait` for it in the same command. {SPLIT}", None
    timeout = tool_input.get("timeout")
    if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout >= LONG:
        return None, None
    return None, (f"raised the timeout to {LONG} ms, since Bash moves a build or test past its timeout to the "
                  "background, and a work-verifier fork's background work stops when it hands back. " + SPLIT)


def apply(command, edits):
    for at, _, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        command = command[:at] + text + command[at:]
    return command


def main():
    try:
        payload = json.load(sys.stdin)
        tool_input = payload["tool_input"]
        command = tool_input["command"]
    except (ValueError, KeyError, TypeError):
        return
    if not isinstance(command, str):
        return
    pipe_edits, pipe_notes, heads = pipefail_fixes(command)
    zsh_edits, zsh_notes = modifier_fixes(command)
    body_edits, body_notes = body_check_fixes(command)
    refused, timeout_note = verifier_fix(payload, tool_input, command)
    if heads:
        refused = (f"`{heads[0]}` can stop the git step partway: once head has its lines, the next write "
                   "kills it with SIGPIPE, and the `&&` chain runs on with head's status. Pipe it into "
                   "`tail` instead, or run the git step on its own.")
    if refused:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": refused}}))
        return
    if not pipe_edits and not zsh_edits and not body_edits and not timeout_note:
        return
    notes = "; ".join(pipe_notes + zsh_notes + body_notes + ([timeout_note] if timeout_note else []))
    if "record-verdict.sh" in command and payload.get("agent_id"):
        # verdict-stamp.py rewrites a subagent's recording too, and only the last rewrite applies.
        reason = f"verdict-stamp.py also rewrites this command, and only one rewrite applies, so fix it yourself: {notes}."
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))
        return
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow" if payload.get("permission_mode") == "bypassPermissions" else "ask",
        "permissionDecisionReason": f"bash-rewrite.py {notes}.",
        "updatedInput": {**tool_input, "command": apply(command, pipe_edits + zsh_edits + body_edits),
                         **({"timeout": LONG} if timeout_note else {})},
        "additionalContext": f"bash-rewrite.py changed the command before it ran: it {notes}. Write it that way next time.",
    }}))


main()
