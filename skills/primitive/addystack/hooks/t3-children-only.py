#!/usr/bin/env python3
"""PreToolUse on Bash: deny `claude -p` / `claude --print` and `codex exec`, and point at a
T3 child task instead. The user runs other models and fresh sessions through T3 Code, which
tracks, shows, and cancels them; a shell-spawned agent is invisible to it. Added after
184 such commands in 48 sessions, counted with `transcript.py scan --hook` (to Oct 8, 2026).

The hook nudges a habit; it isn't a security boundary. Known limits, which no real call in
those sessions used: a quoted command word (`"claude" -p`), a substitution nested inside a
quoted substitution, a substitution inside an unquoted heredoc body, and `claude -p` behind
more than 8 wrappers or a wrapper with more than 8 options. It also denies
`env -S echo claude -p` and `sudo -l codex exec`, though neither runs the agent."""
import json, os, re, sys
from pathlib import Path

# Outside T3 Code there is no delegate_task to point at.
if not os.environ.get("T3CODE_CLI_PATH"):
    sys.exit(0)

payload = json.load(sys.stdin)
command = (payload.get("tool_input") or {}).get("command", "")

# Heredoc bodies and quoted strings are data (prompts, grep patterns). A heredoc's opener
# line is still code (`cat <<EOF | codex exec -`), and so is a command substitution
# inside double quotes (`out="$(claude -p x)"`), which runs as its own command.
code = command.replace("\\\n", " ")
code = re.sub(r"([^\n]*<<-?\s*['\"]?(\w+)['\"]?[^\n]*)\n.*?\n\2\b", r"\1", code, flags=re.S)
substitutions = []

def blank(match):
    if match.group(0).startswith('"'):
        substitutions.extend(re.findall(r"(?<!\\)\$\(([^()]*)\)|(?<!\\)`([^`]*?)(?<!\\)`", match.group(0)))
    return "''"

code = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", blank, code)
code = "\n".join([code] + [a or b for a, b in substitutions])

# Only a command position counts: the start of a line or pipeline segment, a
# substitution, or a loop or branch body, after any wrappers such as `env` or `timeout`,
# with their options and an optional path. Repeats stop at 8, so a longer chain isn't
# caught: an assignment can be an env option or its own wrapper, and without a cap that
# ambiguity backtracks exponentially.
wrapper = "|".join([
    r"\w+=\S*", "command", "exec", "nohup", r"time(?:\s+-p)?",
    r"env(?:\s+(?:-[uCSP]\s*\S+|--(?:unset|chdir|split-string)=\S+|-[iv0]*|--ignore-environment|\w+=\S*)){0,8}",
    r"sudo(?:\s+(?:-[ug]\s+\S+|-\S+)){0,8}",
    r"nice(?:\s+(?:-n\s*\S+|--adjustment=\S+|-\d+)){0,8}",
    r"caffeinate(?:\s+(?:-[tw]\s*\S+|-[dimsu]+)){0,8}",
    r"(?:npx|bunx|xargs)(?:\s+-\S+){0,8}", r"timeout(?:\s+-\S+){0,8}\s+\S+",
])
wrappers = rf"(?:(?:\S*/)?(?:{wrapper})\s+){{0,8}}"
start = r"(?:^|[;&|(`{\n]|\$\()\s*(?:(?:then|do|else)\s+)?" + wrappers + r"(?:\S*/)?"
claude = r"claude(?:-code)?(?=\s)(?=(?:(?!\s--\s)[^;&|\n])*\s(?:-p|--print)(?:[\s=]|$))"
codex = r"codex(?:\s+-\S+(?:\s+[^-\s;&|]\S*)?)*\s+(?:exec|e)(?=[\s;&|)]|$)"
match = re.search(start + f"({claude}|{codex})", code, re.M)
if not match:
    sys.exit(0)

used = "codex exec" if match.group(1).startswith("codex") else "claude -p"
# The guide the denial names; the hook never reads it.
kit = Path(__file__).resolve().parent.parent
guide = kit / "references" / "t3-delegation.md"
try:
    guide = "~/" + str(guide.relative_to(Path.home()))
except ValueError:
    pass
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": f"`{used}` is blocked: run other models and fresh sessions as a T3 "
                                f"child task with the t3-code MCP server's `delegate_task`, per {guide}.",
}}))
