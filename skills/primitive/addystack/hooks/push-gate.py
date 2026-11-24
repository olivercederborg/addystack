#!/usr/bin/env python3
"""PreToolUse on Bash: before `gh stack push`, `gh stack submit`, `gh stack sync`, or `git
push`, find each open PR the command would move, and deny it when a reviewer's latest
review of one is APPROVED, since a repo that dismisses stale approvals on push, such as
a work repo's develop ruleset, then dismisses it. A PR counts only when its branch's
local tip differs from the PR's head, or a sync would rebase it: an unchanged branch
dismisses nothing. A reviewer's latest review is the last that isn't COMMENTED or
pending, so an approval already dismissed, or followed by a change request, isn't live.
The router lists "a push that would dismiss someone's approval" as a Stop, and the prose
rule failed twice on Nov 24, 2026, both on a work repo's #6119: a delegated worker's
`gh stack push` dismissed a teammate's 11:25 approval because its brief said "no
approvals", and the coordinator ran `gh pr view 6119 --json reviews …; … gh stack push`
as one command, so the check printed the 12:12 re-approval only after the push ran and
dismissed it.

Only the user's latest prompt allows such a push (user_turn.py): a pick of a `stop:push`
option, in the reply it answers, or a short typed request, either one a request to push,
restack, sync, or submit that names each PR (#N) and says the push dismisses an approval
("dismiss"), with no refusal, condition, or question in it, so "no: push the cleanup
only" or "don't push #6091 yet, it would dismiss …" isn't one. A pick of any other class, such as the coordinator's `stop:post` "push the cleanup,
post the reply, re-request <reviewer> on #6119", gives no go, nor does a T3 delegated child,
or, in T3, a state database it can't read or a session no T3 thread owns.

The gate reads pushes outside quotes and heredocs, at the start of a command after `cd`,
`&&`, `;`, a pipe, or a subshell, and follows `cd <path>` and `git -C <path>`. For gh
stack, the branches are the current stack's unmerged, unqueued ones, with their PRs from
`gh stack view --json`; a sync rebases a branch below which anything moved, or whose
parent, the trunk's tip on the remote for the lowest, isn't in it. For git push, they are
its refspecs' destination branches, `--all`'s local branches, or the current branch's
push destination, with each branch's open same-repo PR found by name in the remote's
GitHub repo; a push to a remote whose configured URL doesn't name github.com, such as
another machine, moves no PR. No `stack.sh` subcommand pushes, so it reads none.

Fails closed: when a check can't run, the push is denied. Codex runs it too, but a crash
or timeout there lets the push through, since Codex has no `onFailure: "block"`. Known
limits: a push through `gh api`, a git alias, a script, `gh` or `git` run by its path, a
command that runs only inside quotes or a heredoc (`bash -c '…'`), one a tool such as
`xargs` repeats, a `cd` inside a subshell before a push outside it, a remote's
configured `push` refspecs, a GitHub remote behind an ssh host alias, which reads as off
GitHub, and in Codex a push reached only through `workdir`, which is checked
against the session's cwd. It assumes the repo dismisses stale approvals, so in one that
doesn't it denies a push that would dismiss nothing, and an approval that lands between
the check and the push isn't seen.

`push-gate.py --dry-run '<push command>' [--transcript PATH] [--session ID]` runs the
same checks from the current directory and prints each branch it would push, then each
reason or `would pass` (exit 1 or 0), reading the latest prompt as merge-gate.py's does."""
import json, os, re, subprocess, sys

DRY_RUN = sys.argv[1:2] == ["--dry-run"]
if DRY_RUN:
    import user_turn  # here, as below: a broken module then blocks only pushes
    payload = user_turn.dry_run_payload(sys.argv[2:], "push-gate.py")
else:
    payload = json.load(sys.stdin)
command = (payload.get("tool_input") or {}).get("command", "")
cwd = payload.get("cwd") or os.getcwd()


NO_PUSH = "no `gh stack push`, `submit`, or `sync`, or `git push`, outside quotes for the gate to check"


def passes(why):
    if DRY_RUN:
        print(f"would pass: {why}")
    sys.exit(0)


if not re.search(r"\bpush\b|\bsubmit\b|\bsync\b", command):  # most commands: no parse, no gh
    passes(NO_PUSH)

# Heredoc bodies and quoted strings are data (PR bodies, grep patterns), not commands; a
# quoted single word ('feat/x') is an argument, so it keeps its value, unless it starts with
# #, which would then read as a comment.
code = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?.*?\n.*?\n\1\b", "", command, flags=re.S)
code = re.sub(r"'((?!#)[^'\s;&|<>]*)'|\"((?!#)[^\"\s;&|<>\\$`]*)\"", lambda m: m.group(1) or m.group(2) or "''", code)
code = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", code)
code = re.sub(r"\d*(?:>>?|<)(?:&\d+-?|\s*[^\s;&|]+)", " ", code)  # redirections aren't arguments
code = re.sub(r"(?:(?<=[;&|(`])|(?<=(?<!\\)\s)|^)#[^\n]*", "", code, flags=re.M)  # nor are comments

# Words that may lead a command, so `time git push` and `if gh stack push; then` still push.
LEADS = {"if", "while", "until", "then", "else", "elif", "do", "!", "{", "time", "builtin", "command", "env",
         "nohup", "exec"}
ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
# What only the shell can expand: a variable, a glob, a quoted string with spaces (''), or ~+ and ~-.
UNREADABLE = re.compile(r"[$*?\[{`]|^''$|^~[+-]")
# git's global options that take the next word as their value.
GIT_VALUED = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--exec-path"}


def place(where, path):
    """Where `cd path` leaves the shell, or None when only the shell knows."""
    if where is None or UNREADABLE.search(path) or path == "-":
        return None
    return os.path.normpath(os.path.join(where, os.path.expanduser(path)))


pushes, here = [], cwd  # pushes: (kind, args, checkout or None)
for piece in re.split(r"&&|\|\||[;|&\n()`]", code):
    words = piece.split()
    while words and (words[0] in LEADS or ASSIGNMENT.match(words[0])):
        words = words[1:]
    if not words:
        continue
    if words[0] == "cd":
        here = place(here, words[1] if len(words) > 1 else "~")
    elif words[:3] in (["gh", "stack", "push"], ["gh", "stack", "submit"], ["gh", "stack", "sync"]):
        if not {"-h", "--help"} & set(words[3:]):
            pushes.append((words[2], words[3:], here))
    elif words[0] == "git":
        at, where = 1, here
        while at < len(words) and words[at].startswith("-"):
            if words[at] == "-C" and at + 1 < len(words):
                where = place(where, words[at + 1])
            at += 2 if words[at] in GIT_VALUED else 1
        if words[at:at + 1] == ["push"] and not {"-h", "--help", "-n", "--dry-run"} & set(words[at + 1:]):
            pushes.append(("git", words[at + 1:], where))
if not pushes:
    passes(NO_PUSH)


def deny(*reasons):
    if DRY_RUN:
        print("".join(f"- {reason}\n" for reason in reasons) + "would deny")
        sys.exit(1)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"Push gate: {'; '.join(reasons)}. Don't route around the gate with `gh api`, "
                                    "another push path, or a check chained before the push in the same command.",
    }}))
    sys.exit(0)


def run(where, *cmd, check=True):
    result = subprocess.run(cmd, cwd=where, capture_output=True, timeout=40)
    if result.returncode and check:
        raise RuntimeError(f"`{' '.join(cmd[:4])}` failed: {result.stderr.decode(errors='replace').strip()[:200]}")
    return result.stdout.decode(errors="surrogateescape").strip()


def tip(where, ref):
    """The commit ref names in the checkout, or None when there's none."""
    return run(where, "git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False) or None


def contains(where, ancestor, commit):
    """Whether commit holds ancestor; an unknown commit holds nothing."""
    return bool(ancestor and commit) and subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, commit], cwd=where, capture_output=True,
        timeout=40).returncode == 0


def value(args, *names):
    """The value of the last of names in args (`--remote x`, `--remote=x`), or None."""
    found = None
    for at, arg in enumerate(args):
        name, equals, given = arg.partition("=")
        if name in names:
            found = given if equals else (args[at + 1] if at + 1 < len(args) else None)
    return found


def github_repo(where, remote):
    """owner/name of the GitHub repo a remote, by name or URL, points at, or None for a
    remote off github.com. The configured URL, before any insteadOf rewrite."""
    url = run(where, "git", "config", "--get", f"remote.{remote}.url", check=False) or remote
    found = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url)
    return f"{found.group(1)}/{found.group(2)}" if found else None


def stack_targets(kind, args, where):
    """(branch, local tip or None when a sync rebases it, PR URL or None) for each branch
    gh stack pushes: the stack's unmerged, unqueued branches, bottom first."""
    stack = json.loads(run(where, "gh", "stack", "view", "--json"))
    remote = value(args, "--remote") or "origin"
    parent, moved, found = None, False, []
    if kind == "sync":  # it fetches first, so the trunk it rebases onto is the remote's
        listed = run(where, "git", "ls-remote", remote, f"refs/heads/{stack['trunk']}").split()
        if not listed:
            raise RuntimeError(f"`{remote}` has no branch `{stack['trunk']}`")
        parent = listed[0]
    for branch in stack["branches"]:
        if branch.get("isMerged") or branch.get("isQueued"):
            continue
        local = tip(where, f"refs/heads/{branch['name']}")
        if kind == "sync":
            moved = moved or bool(branch.get("needsRebase")) or not contains(where, parent, local)
            parent = local
        pr = branch.get("pr") or {}
        found.append((branch["name"], None if moved else local, pr.get("url") or pr.get("number")))
    return found


def git_targets(args, where):
    """(branch, local tip, None) for each branch on a GitHub remote that git push updates,
    and that remote's owner/name."""
    flags, positional, at = [], [], 0
    while at < len(args):
        arg, at = args[at], at + 1
        if arg == "--":
            positional += args[at:]
            break
        if arg in ("--repo", "-o", "--push-option", "--receive-pack", "--exec"):
            at += 1
        elif arg.startswith("-"):
            flags.append(arg.split("=")[0])
        else:
            positional.append(arg)
    if {"-d", "--delete", "--prune"} & set(flags):
        raise RuntimeError("the gate doesn't read a push that deletes branches: run the deletion as its own push")
    current = run(where, "git", "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    # With no remote named, git pushes to the current branch's push remote.
    remote = positional[0] if positional else value(args, "--repo") or current and run(
        where, "git", "for-each-ref", "--format=%(push:remotename)", f"refs/heads/{current}") or "origin"
    if UNREADABLE.search(remote):
        raise RuntimeError(f"can't tell which remote `{remote}` is")
    repo = github_repo(where, remote)
    if repo is None:
        return [], None
    specs = positional[1:]
    if {"--all", "--branches", "--mirror"} & set(flags):
        specs += run(where, "git", "for-each-ref", "--format=%(refname:short)", "refs/heads").split()
    elif not specs and "--tags" not in flags:
        if not current:
            return [], repo  # detached: git push names nothing to push
        destination = run(where, "git", "for-each-ref", "--format=%(push:remoteref)", f"refs/heads/{current}")
        specs = [f"{current}:{destination or current}"]
    found = []
    for spec in specs:
        if UNREADABLE.search(spec):
            raise RuntimeError(f"can't tell which branch the refspec `{spec}` pushes")
        source, colon, destination = spec.lstrip("+").partition(":")
        if colon and not source:
            raise RuntimeError(f"the gate doesn't read a push that deletes branches (`{spec}`): run it on its own")
        destination = destination if colon else (current if source == "HEAD" else source)
        if destination in ("HEAD", "@"):
            destination = current
        if destination.startswith("refs/"):
            if not destination.startswith("refs/heads/"):
                continue  # a tag or another namespace moves no PR
            destination = destination[len("refs/heads/"):]
        if destination:
            found.append((destination, tip(where, source), None))
    return found, repo


FIELDS = "number,url,state,headRefName,headRefOid,isCrossRepository,reviews"


def pull_request(where, branch, pr, repo):
    """The open PR a branch heads: pr, a URL or number gh stack knows, or else the
    same-repo PR whose head is branch in repo. None when there's none."""
    if pr:
        found = json.loads(run(where, "gh", "pr", "view", str(pr), "--json", FIELDS))
        return found if found.get("state") == "OPEN" else None
    listed = json.loads(run(where, "gh", "pr", "list", "--head", branch, "--state", "open",
                            *(["-R", repo] if repo else []), "--json", FIELDS))
    return next((found for found in listed if not found.get("isCrossRepository")), None)


def approvals(pr):
    """(login, submittedAt) for each reviewer whose latest review that isn't COMMENTED or
    pending is APPROVED."""
    latest = {}
    for review in sorted(pr.get("reviews") or [], key=lambda review: review.get("submittedAt") or ""):
        if review.get("submittedAt") and review.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[(review.get("author") or {}).get("login") or "a reviewer"] = review
    return [(login, review["submittedAt"]) for login, review in latest.items() if review["state"] == "APPROVED"]


try:
    live = {}  # PR number: (pr, branch, local tip, approvals)
    for kind, args, where in pushes:
        if where is None:
            raise RuntimeError("this command `cd`s where only the shell knows, so the gate can't tell which checkout "
                               "pushes: run the push as `cd <checkout> && …` on a literal path")
        targets, repo = (stack_targets(kind, args, where), None) if kind != "git" else git_targets(args, where)
        for branch, local, known in targets:
            if kind != "git" and not known:
                if DRY_RUN:
                    print(f"{branch}: no PR (from {where})")
                continue
            pr = pull_request(where, branch, known, repo)
            changed = pr is not None and local != pr["headRefOid"]
            if DRY_RUN:
                said = ("no open PR" if pr is None else f"#{pr['number']}, " + (
                    "unchanged" if not changed else f"{pr['headRefOid'][:10]} → {local[:10] if local else 'a rebased tip'}"))
                print(f"{branch}: {said} (from {where})")
            approved = approvals(pr) if changed else []
            if approved:
                live[pr["number"]] = (pr, branch, local, approved)
except Exception as error:
    deny(f"couldn't check what this push would move ({error})")
if not live:
    passes("no PR this push moves has a live approval")

PUSH_WORD = re.compile(r"\b(?:force-?push|push|restack|re-stack|rebase|sync|submit)", re.I)
DISMISS = re.compile(r"\bdismiss", re.I)
# A typed request with any of these may refuse, wait, or ask, so it's no go.
REFUSAL = re.compile(r"\?|\b(?:\w+n't|dont|wont|cant|shouldnt|do not|never|not|no|without|avoid|unless|if|until|"
                     r"wait|hold|stop)\b", re.I)


def literal_go(text):
    """Whether text is a short typed request to push that says it dismisses an approval."""
    text = text.strip().replace("’", "'")
    return (len(text) <= 200 and bool(PUSH_WORD.search(text)) and bool(DISMISS.search(text))
            and not REFUSAL.search(text))


def unnamed(text):
    """The PRs of live that text doesn't name, as "#N" words: merge_go.names, held to a
    text that names a PR, so "push it" names none."""
    import merge_go
    read, _ = merge_go.spans(text)
    numbers = sorted(live)
    missing = []
    for n, (pr, *_) in sorted(live.items()):
        owner, repo = re.search(r"github\.com/([^/]+)/([^/]+)/pull/", pr["url"]).groups()
        if not read or not merge_go.names(text, n, owner, repo, numbers):
            missing.append(f"#{n}")
    return " and ".join(missing)


def user_go():
    """(go, note): whether the user's latest prompt allows dismissing every live approval,
    and, for one that doesn't, why. A go is literal_go naming each PR, or a key that picks a
    stop:push option of the reply it answered whose text is one."""
    try:
        import turn_block, user_turn
        found = user_turn.exchanges(payload)
        if found is None:
            return False, None
        prompt = found[-1].prompt if found else ""
        said = f'the user\'s "{prompt.strip()}"'
        if literal_go(prompt):
            missing = unnamed(prompt)
            return (True, None) if not missing else (False, f"{said} doesn't name {missing}")
        key = turn_block.PICK.fullmatch(prompt)
        if not key:
            return False, None
        reply = user_turn.answered(found)
        option = turn_block.picked(reply, prompt)
        if option is None:
            return False, f"{said} picks nothing: {user_turn.letter_miss(reply, key.group(1).lower())}"
        picks = f'{said} picks "{option.text}", a {option.cls} option of your reply before it'
        if option.cls != "stop:push":
            return False, f"{picks}, and only a stop:push option allows a push that dismisses an approval"
        if not literal_go(option.text):  # as a typed go: a push, the dismissal, and no refusal or condition
            return False, f"{picks}, which isn't a plain request to push that says it dismisses an approval"
        missing = unnamed(option.text)
        return (True, None) if not missing else (False, f"{picks}, which doesn't name {missing}")
    except Exception:
        return False, None


go, note = user_go()
if DRY_RUN:
    print(f"go: {'yes' if go else 'no'}, from {payload.get('transcript_path') or 'no transcript; pass --transcript'}")
if go:
    passes("the user's latest prompt names each dismissal")
reasons = []
for n, (pr, branch, local, found) in sorted(live.items()):
    who = " and ".join(f"{login}'s approval (submitted {when[:10]} {when[11:16]} UTC)" for login, when in found)
    moves = f"{pr['headRefOid'][:10]} to {local[:10]}" if local else f"{pr['headRefOid'][:10]} to a rebased tip"
    reasons.append(f"pushing `{branch}` moves #{n} from {moves}, which dismisses {who}")
reasons.extend([note] if note else [])
refs = " and ".join(f"#{n}" for n in sorted(live))
approvers = " and ".join(sorted({login for *_, found in live.values() for login, _ in found}))
reasons.append(f"ask the user first with a `stop:push` option that names {refs} and the dismissal, such as "
               f'"push {refs} (dismisses {approvers}\'s approval)", or have them type that request; '
               "a delegated child reports the push back to its owner instead")
deny(*reasons)
