#!/usr/bin/env python3
"""PreToolUse on Bash: deny a command that points HOME at another folder and runs something
that writes to the macOS keychain: `claude`, `gh`, `security`, `yadm`, a bootstrap script it runs,
or a git fetch, pull, push, clone, or ls-remote. Under a fake HOME macOS can't find the login
keychain, so each write pops a "Keychain Not Found" dialog on the user's screen, and its
"Reset To Defaults" button would set their real keychain aside. Added after a verifier ran
dotfiles bootstrap step 45 and `claude mcp list` under `HOME=$(mktemp -d)` on Oct 26, 2026.

Hook tests that only read files under a fake HOME still pass. Known limits: a script that
runs one of these commands without naming it (`HOME=/tmp/h ./setup.sh`), behind a shell function
(`y() { env HOME=$H "$@"; }; y yadm`), or in a script a shell gets as a string or a pipe
(`bash -c '...'`, `cat <<EOS | bash`) passes; a `bash -n` syntax
check of a bootstrap script is denied; and a fake HOME set for one command
(`HOME=/tmp/h python3 x && gh pr view`) also denies a writer later in the line."""
import json, re, sys

if sys.platform != "darwin":
    sys.exit(0)

payload = json.load(sys.stdin)
command = (payload.get("tool_input") or {}).get("command", "")

# Heredoc bodies are data (prompts, `python3 -` programs), unless a shell reads them as
# its script (`bash <<'EOS'`). One scan then drops comments and blanks single-quoted
# strings, so an apostrophe in a comment or a double-quoted string can't pair with a
# quote on another line. Double-quoted strings stay, since a quoted path still runs.
def heredoc(match):
    return match[0] if re.search(r"(?:^|[\s;&|(])(?:bash|sh|zsh)(?:\s+-\w+)*\s*<<", match[1]) else match[1]

code = command.replace("\\\n", " ")
code = re.sub(r"([^\n]*<<-?\s*['\"]?(\w+)['\"]?[^\n]*)\n.*?\n\2\b", heredoc, code, flags=re.S)
code = re.sub(
    r"\"(?:\\.|[^\"\\])*\"|'[^']*'|(?:^|(?<=[\s;&|(]))#[^\n]*",
    lambda m: m[0] if m[0][0] == '"' else "''" if m[0][0] == "'" else "",
    code,
    flags=re.M,
)

# HOME=$HOME and HOME=~ keep the real home.
fake_home = re.search(r"(?:^|[\s;&|(])(?:export\s+)?HOME=(?![\"']?(?:\$HOME|\$\{HOME\}|~)(?:[\s;&|)\"']|$))", code)
if not fake_home:
    sys.exit(0)
# Only a command position counts: a segment's start, after any assignments (including
# `$(...)` and quoted values), wrappers such as `env`, or a `$WRAPPER` variable, so a
# folder named `yadm`, a quoted `git fetch`, or a variable holding a bootstrap path doesn't.
start = r"(?:^|[;&|(`]|\$\(|\b(?:then|do|exec|command|env|xargs|time|sudo|bash|sh|zsh)\s)\s*"
start += r"(?:(?:-\w+|\w+=(?:\$\([^()]*\)|\"(?:\\.|[^\"\\])*\"|\\.|[^\s;&|()\"$\\]|\$(?!\())*|\$\{?\w+\}?)\s+)*[\"']?(?:[^\s;&|()\"'=]*/)?"
# A variable the command sets to a bootstrap path counts when it runs (`bash $STEP`).
step_vars = re.findall(r"(?:^|[\s;&|(])(\w+)=[\"']?[^\s;&|()]*bootstrap", code, re.M)
step_var = rf"|\$\{{?(?:{'|'.join(step_vars)})\}}?(?=$|[\s;&|)\"'])" if step_vars else ""
keychain_user = re.search(
    start + r"(?:(?:claude|gh|security|yadm)(?=$|[\s;&|)\"'])|[^\s;&|()\"'=]*bootstrap[^\s;&|()]*"
    r"|git\b[^;&|\n]*\s(?:fetch|pull|push|clone|ls-remote)\b" + step_var + ")",
    code,
    re.M,
)
if not keychain_user:
    sys.exit(0)

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": (
        f"Don't run `{keychain_user.group(0).strip()}` under a fake HOME: macOS can't find the "
        "login keychain there and shows the user a 'Keychain Not Found' dialog for each keychain "
        "write. Keep HOME. Isolate Claude Code's config with CLAUDE_CONFIG_DIR=<temp dir>, and "
        "test a bootstrap step with DRY_RUN=1 or by extracting the part under test."
    ),
}}))
