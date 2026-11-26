#!/usr/bin/env python3
"""PreToolUse on Bash: before `gh stack push`, `gh stack submit`, `gh stack sync`, or `git
push`, find each open PR the command would move, and deny it when a reviewer's latest
review of one is APPROVED, since a repo that dismisses stale approvals on push, such as
a work repo's develop ruleset, then dismisses it. A PR counts only when its branch's
local tip differs from the PR's head, or a sync would rebase it: an unchanged branch
dismisses nothing. A reviewer's latest review is the last that isn't COMMENTED or
pending, so an approval already dismissed, or followed by a change request, isn't live.
The router lists "a push that would dismiss someone's approval" as a Stop, and the prose
rule failed twice on Nov 24, 2026, on a work repo's #6119; PushGate in test_hooks.py
replays both.

Only the user's latest prompt allows such a push (user_turn.py): a pick of a `stop:push`
option, in the reply it answers, or a typed request, either one at most 200 characters, a
request whose whole text is a push verb (push, force-push, restack, rebase, sync, or
submit) with its object and each PR (#N), or none for a lone approval, then the dismissal
set off by "(", a comma, or "and" ("yes: push #6119 (dismisses the … approval)"), which may
instead list each PR whose approval goes and only PRs the push moves ("… approvals on #6179
and #6213"), then only routine steps such as "post the reply" (AFTER), with no refusal,
condition, question, or modal in it (push_go.py), so "no: push the cleanup only", "pushing
#6091 dismisses the approval", or "push #6091 once the approval is dismissed" isn't one.
The same request typed without the dismissal is one right after a reply whose stop:push
option is: that reply told the user what goes. A pick of any other class, such as
the coordinator's `stop:post` "push the cleanup, post the reply, re-request <reviewer> on
#6119", gives no go, nor does a T3 delegated child, or, in T3, a state database it can't
read or a session no T3 thread owns.

The gate reads pushes outside quotes and heredocs, at the start of a command after `cd`,
`&&`, `;`, a pipe, or a subshell, and follows `git -C <path>` and each cd, pushd, and popd
as shell_dirs.Walk reads them for merge-gate.py, denying a push after one it can't read or
that may not run before it, such as a `cd` inside a subshell or after `||`. The tips are
read before the shell runs, so a commit, rebase, reset, or other branch move earlier in the
command (shell_dirs.BRANCH_MOVES, as ready-gate.py reads it) counts each PR the push
reaches as moved, and a branch or stack switch earlier denies. For gh stack, the
branches are the current stack's unmerged, unqueued ones from `gh stack view --json`,
pushed to the remote gh stack picks (stack_remote); a sync rebases a branch below which
anything moved, or whose parent as the remote has it, the trunk's tip for the lowest,
isn't in it. For git push, they are the branches `git push --dry-run --porcelain` says it
would update or delete, so push.default, refspecs, and `--all` read as git reads them, to
the GitHub repo of each push URL (`pushurl`, else `url`); a remote whose configured URLs
don't name github.com, such as another machine, moves no PR, and a push git refuses for
its refspec, or rejects as it stands, moves nothing, unless a fetch, pull, or rebase earlier
in the command can make git take it. Each branch's PRs are every open one GitHub lists with it as
the head, on its repo or a repo that repo forks, keyed by URL, so two repos' #N stay
apart. No `stack.sh` subcommand pushes, so it reads none.

Fails closed: when a check can't run, the push is denied. Codex runs it too, but a crash
or timeout there lets the push through, since Codex has no `onFailure: "block"`. Known
limits: a push through `gh api`, a git alias, a script, `gh` or `git` run by its path, a
command that runs only inside quotes or a heredoc (`bash -c '…'`), one a tool such as
`xargs` repeats, a GitHub remote behind an ssh
host alias, which reads as off GitHub, and in Codex a push reached only through
`workdir`, which is checked against the session's cwd. It assumes the repo dismisses
stale approvals, so in one that doesn't it denies a push that would dismiss nothing, and
an approval that lands between the check and the push isn't seen.

`push-gate.py --dry-run '<push command>' [--transcript PATH] [--session ID]` runs the
same checks from the current directory and prints each branch it would push, then each
reason or `would pass` (exit 1 or 0), reading the latest prompt as merge-gate.py's does."""
import json, os, re, subprocess, sys, urllib.parse

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


PUSHY = re.compile(r"\bpush\b|\bsubmit\b|\bsync\b")
if not PUSHY.search(command):  # most commands: no parse, no gh
    passes(NO_PUSH)

# Heredoc bodies and quoted strings are data (PR bodies, grep patterns), not commands; a
# quoted single word ('feat/x') is an argument, so it keeps its value, unless it starts with
# #, which would then read as a comment.
code = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?.*?\n.*?\n\1\b", "", command, flags=re.S)
code = re.sub(r"'((?!#)[^'\s;&|<>]*)'|\"((?!#)[^\"\s;&|<>\\$`]*)\"", lambda m: m.group(1) or m.group(2) or "''", code)
code = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", code)
code = re.sub(r"\d*(?:>>?|<)(?:&\d+-?|\s*[^\s;&|]+)", " ", code)  # redirections aren't arguments
code = re.sub(r"(?:(?<=[;&|(`])|(?<=(?<!\\)\s)|^)#[^\n]*", "", code, flags=re.M)  # nor are comments

# What only the shell can expand: a variable, a glob, a quoted string with spaces (''), or ~+ and ~-.
UNREADABLE = re.compile(r"[$*?\[{`]|^''$|^~[+-]")
# git's global options that take the next word as their value.
GIT_VALUED = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--exec-path"}
# Words that run the command after them, past shell_dirs.LEADS, so `env git push` still pushes.
RUNS = {"env", "nohup", "exec"}


# Where each push runs, read as merge-gate.py and ready-gate.py read it (shell_dirs.Walk): a
# cd that may not run before the push, or whose directory the gate can't read, leaves its
# checkout unknown. A command substitution with no push in it, as in `d=$(cd x && pwd)`, runs
# in its own shell and moves nothing.
from shell_dirs import ASSIGNMENT, BRANCH_MOVES, Walk
walk = Walk(re.sub(r"\$\([^()`]*\)", lambda m: m.group(0) if PUSHY.search(m.group(0)) else "''", code), cwd)
# A commit, rebase, or other branch move earlier in the command runs after the gate reads the
# tips, so each push after one counts every PR it reaches as moved. A switch of branch or
# stack earlier changes which branches the push reads, so the gate can't tell them.
SWITCHES = re.compile(r"\bgit(?:\s+-[Cc]\s+\S+|\s+--?[\w-]+(?:=\S+)?)*\s+(?:checkout|switch)\b"
                      r"|\bgh\s+(?:pr\s+(?:checkout|co)|stack\s+(?:checkout|switch|up|down|top|bottom|add|init))\b")
# A fetch moves no branch, but it updates what a push's lease, or git's fast-forward check, compares with.
FETCHES = re.compile(r"\bgit(?:\s+-[Cc]\s+\S+|\s+--?[\w-]+(?:=\S+)?)*\s+fetch\b")
pushes, earlier, switched = [], False, None  # (kind, args, checkout, why it can't tell the checkout or None, earlier)
for piece, words, lead in walk:
    words = words[lead:]
    while words and (words[0] in RUNS or ASSIGNMENT.match(words[0])):
        words = words[1:]
    where, unknown = walk.cwd, walk.unknown.get("dir") or switched
    found = None
    if words[:3] in (["gh", "stack", "push"], ["gh", "stack", "submit"], ["gh", "stack", "sync"]):
        if not {"-h", "--help"} & set(words[3:]):
            found = (words[2], words[3:], where, unknown, earlier)
    elif words[:1] == ["git"]:
        at = 1
        while at < len(words) and words[at].startswith("-"):
            if words[at] == "-C" and at + 1 < len(words):
                if UNREADABLE.search(words[at + 1]):
                    unknown = unknown or f"runs `git -C {words[at + 1]}`, whose directory it can't read"
                where = os.path.normpath(os.path.join(where, os.path.expanduser(words[at + 1])))
            at += 2 if words[at] in GIT_VALUED else 1
        if words[at:at + 1] == ["push"] and not {"-h", "--help", "-n", "--dry-run"} & set(words[at + 1:]):
            options = [word for i, word in enumerate(words[1:at], 1) if "-C" not in (word, words[i - 1])]
            found = ("git", (options, words[at + 1:]), where, unknown, earlier)
    pushes += [found] if found else []
    # A push moves no local branch, so of the pushes only a sync's rebase counts for those after it.
    text = walk.pieces[piece]
    earlier = earlier or bool(BRANCH_MOVES.search(text) or FETCHES.search(text)) and not (found and found[0] != "sync")
    switch = SWITCHES.search(text)
    switched = switched or switch and f"runs `{switch.group(0)}` before it pushes, which changes the branches the push reads"
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


def github_repo(url):
    """owner/name of the GitHub repo a URL points at, or None for one off github.com."""
    found = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url)
    return f"{found.group(1)}/{found.group(2)}" if found else None


def github_repos(where, remote):
    """The GitHub repos a push to remote, by name or URL, reaches: its push URLs, or else its
    URL, as configured, before any insteadOf rewrite."""
    urls = (run(where, "git", "config", "--get-all", f"remote.{remote}.pushurl", check=False).split()
            or [run(where, "git", "config", "--get", f"remote.{remote}.url", check=False) or remote])
    return sorted({repo for repo in map(github_repo, urls) if repo})


def stack_remote(where, args):
    """The remote gh stack pushes to, picked as gh-stack v0.2.1's pickRemote does
    (cmd/utils.go, and ResolveRemote in internal/git/gitops.go, at github/gh-stack@80b6d6e):
    --remote, the current branch's pushRemote, remote.pushDefault, its remote, gh-stack.remote,
    then the only remote. With several and none set, gh stack asks, so the gate can't tell."""
    given = value(args, "--remote")
    if given:
        return given
    current = run(where, "git", "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    keys = [f"branch.{current}.pushRemote", "remote.pushDefault", f"branch.{current}.remote", "gh-stack.remote"]
    for key in keys if current else keys[1:2] + keys[3:]:
        found = run(where, "git", "config", "--get", key, check=False)
        if found:
            return found
    remotes = run(where, "git", "remote").split()
    if len(remotes) != 1:
        raise RuntimeError("gh stack can't pick a remote here without asking: pass `--remote <name>`")
    return remotes[0]


def stack_targets(kind, args, where):
    """(branch, local tip or None when a sync rebases it, how or None) for each branch gh stack
    pushes, the stack's unmerged, unqueued ones, bottom first, and the GitHub repos its
    remote reaches. A sync fetches first, then rebases each branch onto the one below as the
    remote has it: the trunk's tip, and a branch the remote moved ahead of its local tip
    fast-forwards, so each branch above it rebases."""
    stack = json.loads(run(where, "gh", "stack", "view", "--json"))
    remote = stack_remote(where, args)
    parent, moved, found, heads = None, False, [], {}
    if kind == "sync":
        for line in run(where, "git", "ls-remote", "--heads", remote).splitlines():
            commit, ref = line.split("\t")
            heads[ref[len("refs/heads/"):]] = commit
        if stack["trunk"] not in heads:
            raise RuntimeError(f"`{remote}` has no branch `{stack['trunk']}`")
        parent = heads[stack["trunk"]]
    for branch in stack["branches"]:
        if branch.get("isMerged") or branch.get("isQueued"):
            continue
        local = tip(where, f"refs/heads/{branch['name']}")
        if kind == "sync":
            moved = moved or bool(branch.get("needsRebase")) or not contains(where, parent, local)
            ahead = heads.get(branch["name"])
            parent = local if not ahead or contains(where, ahead, local) else ahead
        found.append((branch["name"], None if moved else local, "a rebased tip" if moved else None))
    return found, github_repos(where, remote)


def git_targets(argv, where, earlier):
    """(branch, local tip or None, how it moves or None) for each branch git push would
    update, as `git push --dry-run --porcelain` lists them, so push.default, refspecs,
    --all, and deletions read as git reads them, and the GitHub repos it pushes to. After an
    earlier branch move in the command, a branch up to date now counts too."""
    options, args = argv
    positional, at = [], 0
    while at < len(args):
        arg, at = args[at], at + 1
        if arg == "--":
            positional += args[at:]
            break
        if arg in ("--repo", "-o", "--push-option", "--receive-pack", "--exec"):
            at += 1
        elif not arg.startswith("-"):
            positional.append(arg)
    for word in positional:
        if UNREADABLE.search(word):
            raise RuntimeError(f"can't tell which remote or refspec `{word}` names")
    current = run(where, "git", "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    # With no remote named, git pushes to the current branch's push remote.
    remote = positional[0] if positional else value(args, "--repo") or current and run(
        where, "git", "for-each-ref", "--format=%(push:remotename)", f"refs/heads/{current}") or "origin"
    repos = github_repos(where, remote)
    if not repos:
        return [], []
    loud = [arg for arg in args if arg not in ("-q", "--quiet")]  # --quiet drops the porcelain lines
    result = subprocess.run(["git", *options, "push", "--dry-run", "--porcelain", "--no-verify", *loud], cwd=where,
                            capture_output=True, timeout=40)
    out, err = result.stdout.decode(errors="surrogateescape"), result.stderr.decode(errors="replace").strip()
    if not re.search(r"^To ", out, re.M):
        # A refspec git refuses before it reaches the remote fails the push too, so it moves nothing.
        if result.returncode and re.search(r"src refspec .* does not match any|invalid refspec|not currently on a "
                                           r"branch|has no upstream branch|remote ref does not exist", err):
            return [], repos
        raise RuntimeError(f"`git push --dry-run` failed: {err[:200]}")
    found = []
    # Each line is "<flag>\t<from>:<to>\t<summary>": = is up to date and ! rejected, so neither moves,
    # unless a fetch or branch move earlier in the command changes what git compares.
    for flag, source, destination in re.findall(r"^([ +*!=-])\t([^\t]*):([^\t]+)\t", out, re.M):
        if flag in "=!" and not earlier or not destination.startswith("refs/heads/"):
            continue  # a tag or another namespace moves no PR
        branch = destination[len("refs/heads/"):]
        found.append((branch, None, "a deletion") if flag == "-" else (branch, tip(where, source), None))
    return found, repos


FIELDS = "number,url,state,headRefOid,reviews"
FORKED = {}  # repo: the repos it forks, which take PRs from it


def pull_requests(where, branch, repo):
    """Every open PR whose head is branch in repo, opened on repo or on a repo it forks (its
    parent and source), each found from GitHub, never from gh stack's best-effort view. The
    REST list's `head=<owner>:<branch>` filter is exact, where `gh pr list --head` matches the
    name in every fork and stops at its first 30."""
    if repo not in FORKED:
        FORKED[repo] = run(where, "gh", "api", f"repos/{repo}", "--jq",
                           '[.parent.full_name, .source.full_name] | map(select(. != null)) | unique | join(" ")').split()
    owner, head = repo.split("/")[0], urllib.parse.quote(branch, safe="/")
    found = []
    for base in [repo, *(fork for fork in FORKED[repo] if fork != repo)]:
        listed = run(where, "gh", "api", "--paginate", f"repos/{base}/pulls?head={owner}:{head}&state=open&per_page=100",
                     "--jq", ".[] | .number").split()
        found += [json.loads(run(where, "gh", "pr", "view", n, "-R", base, "--json", FIELDS)) for n in listed]
    return [pr for pr in found if pr.get("state") == "OPEN"]


def approvals(pr):
    """(login, submittedAt) for each reviewer whose latest review that isn't COMMENTED or
    pending is APPROVED."""
    latest = {}
    for review in sorted(pr.get("reviews") or [], key=lambda review: review.get("submittedAt") or ""):
        if review.get("submittedAt") and review.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[(review.get("author") or {}).get("login") or "a reviewer"] = review
    return [(login, review["submittedAt"]) for login, review in latest.items() if review["state"] == "APPROVED"]


try:
    live, moved = {}, {}  # PR URL: (pr, branch, where it moves to, approvals); PR URL: each PR the push moves
    for kind, args, where, unknown, earlier in pushes:
        if unknown:
            raise RuntimeError(f"this command {unknown}, so the gate can't tell what it pushes: run the push "
                               "as its own command, or as `cd <checkout> && …` on a literal path")
        targets, repos = git_targets(args, where, earlier) if kind == "git" else stack_targets(kind, args, where)
        for branch, local, how in targets:
            if earlier:
                local, how = None, "a tip an earlier command in this one makes"
            prs = [pr for repo in repos for pr in pull_requests(where, branch, repo)]
            if DRY_RUN and not prs:
                print(f"{branch}: no open PR (from {where})")
            for pr in prs:
                changed = how is not None or local != pr["headRefOid"]
                if DRY_RUN:
                    print(f"{branch}: #{pr['number']}, " + ("unchanged" if not changed else
                          f"{pr['headRefOid'][:10]} → {local[:10] if local else how}") + f" (from {where})")
                moved.update({pr["url"]: pr} if changed else {})
                approved = approvals(pr) if changed else []
                if approved:
                    live[pr["url"]] = (pr, branch, local[:10] if local else how, approved)
except Exception as error:
    deny(f"couldn't check what this push would move ({error})")
if not live:
    passes("no PR this push moves has a live approval")

# A go's grammar: push_go.py.
import merge_go
from push_go import BASE, COUNTED, Go, literal_go, plain_go


def slug(pr):
    """(owner, name) of the repo pr is on."""
    return re.search(r"github\.com/([^/]+)/([^/]+)/pull/", pr["url"]).groups()


def label(pr):
    """#N, or "<repo> #N" when the PRs the push moves sit in more than one repo, so a go names
    each with its repo."""
    return f"{slug(pr)[1]} #{pr['number']}" if len({slug(each) for each, *_ in live.values()}) > 1 else f"#{pr['number']}"


def unnamed(go):
    """The PRs of live that a Go doesn't name, as "#N" words: merge_go.names. A dismissal
    that lists PRs says which approvals go, so it names each live one. Otherwise the push
    steps do, and a push that names no PR, such as "push it", names the one PR with a live
    approval, as merge-gate.py takes a go that names none, but not two. The steps after it
    (AFTER), whose approval (WHOSE), a count such as "all 5 PRs", and a base it goes onto
    name no PR."""
    pushed = re.sub(COUNTED, "", re.sub(BASE, "", go.push, flags=re.I), flags=re.I)  # a base isn't pushed
    read, _ = merge_go.spans(pushed)
    numbers = sorted({pr["number"] for pr, *_ in live.values()})
    shared = [pr["number"] for pr, *_ in live.values()]  # a bare "#42" can't tell two repos' #42 apart
    named = lambda text, pr: merge_go.names(text, pr["number"], *slug(pr), numbers) and (
        shared.count(pr["number"]) == 1 or bool(merge_go.REPO_NAMED.search(text)))
    missing = [label(pr) for pr, *_ in live.values() if (not named(go.dismissed, pr) if go.dismissed
               else not read and len(live) > 1 or not named(pushed, pr))]
    return " and ".join(missing)


def strays(go):
    """The PRs a Go's dismissal names that this push doesn't move, as its words, so a go
    can't claim a dismissal somewhere else."""
    read, unread = merge_go.spans(go.dismissed)
    if unread:
        return unread[0]
    here = lambda end, pr: end[0] is None or end[0][1].lower() == slug(pr)[1].lower() and (
        not end[0][0] or end[0][0].lower() == slug(pr)[0].lower())
    return " and ".join(f"#{low[1]}" for low, _ in read
                        if not any(pr["number"] == low[1] and here(low, pr) for pr in moved.values()))


def unmet(go):
    """Why a Go isn't one for every live approval, or None when it is."""
    missing, stray = unnamed(go), strays(go)
    return f"doesn't name {missing}" if missing else f"names {stray} in its dismissal, which this push doesn't move" \
        if stray else None


def offered(reply):
    """The reply's stop:push options that are a go for every live approval, or ()."""
    import turn_block  # here, as user_turn: a broken module then gives no go, not a crash
    turn = turn_block.certain(reply) if isinstance(reply, str) else None
    if turn is None or turn != turn_block.certain(reply.strip(turn_block.JS_SPACE)):
        return ()
    return tuple(option for option in turn.options if option.cls == "stop:push"
                 and (go := literal_go(option.text)) and not unmet(go))


def user_go():
    """(go, note): whether the user's latest prompt allows dismissing every live approval,
    and, for one that doesn't, why. A go is literal_go naming each PR, a key that picks a
    stop:push option of the reply it answered whose text is one, or plain_go naming each
    PR, typed right after a reply with such an option: that reply told the user what the
    push dismisses."""
    try:
        import turn_block, user_turn
        found = user_turn.exchanges(payload)
        if found is None:
            return False, None
        prompt = found[-1].prompt if found else ""
        said = f'the user\'s "{prompt.strip()}"'
        go = literal_go(prompt)
        if go:
            why = unmet(go)
            return (True, None) if not why else (False, f"{said} {why}")
        plain = plain_go(prompt)
        if plain:
            why = unmet(Go(plain, ""))
            if why:
                return False, f"{said} {why}"
            if offered(user_turn.answered(found)):
                return True, None
            return False, (f"{said} doesn't say it dismisses an approval, and your reply before it offers no "
                           "stop:push option that does")
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
        go = literal_go(option.text)  # as a typed go: a push, the dismissal, and no refusal or condition
        if not go:
            return False, f"{picks}, which isn't a plain request to push that says it dismisses an approval"
        why = unmet(go)
        return (True, None) if not why else (False, f"{picks}, which {why}")
    except Exception:
        return False, None


go, note = user_go()
if DRY_RUN:
    print(f"go: {'yes' if go else 'no'}, from {payload.get('transcript_path') or 'no transcript; pass --transcript'}")
if go:
    passes("the user's latest prompt names each dismissal")
reasons = []
for pr, branch, to, found in sorted(live.values(), key=lambda each: each[0]["url"]):
    who = " and ".join(f"{login}'s approval (submitted {when[:10]} {when[11:16]} UTC)" for login, when in found)
    reasons.append(f"pushing `{branch}` moves {label(pr)} from {pr['headRefOid'][:10]} to {to}, which dismisses {who}")
reasons.extend([note] if note else [])
refs = " and ".join(sorted(label(pr) for pr, *_ in live.values()))
approvers = " and ".join(sorted({login for *_, found in live.values() for login, _ in found}))
numbers = [pr["number"] for pr, *_ in live.values()]
reasons.append(("two of these PRs share a number, so push each in its own command, and for each "
                if len(set(numbers)) < len(numbers) else "") + f"ask the user first with a `stop:push` option that names {refs} and the dismissal, such as "
               f'"push {refs} (dismisses {approvers}\'s approval)", or have them type that request; '
               "a delegated child reports the push back to its owner instead")
deny(*reasons)
