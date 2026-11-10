#!/usr/bin/env python3
"""PreToolUse on Bash: before `gh pr merge` or `gh stack merge`, check every open PR the
command would merge, and deny it unless
- the PR's own checks ran and passed, or, in a repo with no workflows in
  `.github/workflows`, or whose workflows' path and branch filters skip the PR
  (workflow_triggers.py), the user's latest prompt asks for the merge (`merge on go` in
  shared/workflow.md); a checkout whose trust is `gate` (resolved.py) needs no go for a
  merge line of the form `stack.sh where` prints (BOUND) when no workflow exists at the
  PR's base, head, or default branch, since the fresh Done below is enough,
- the repo's default branch is green: its latest checks passed, or it has none,
- a fresh work-verifier's latest verdict for that exact diff is Done (verdicts.py),
- the PR's base branch gained no commits since the PR branched that touch files the PR
  changes: its checks and verdict ran against the older base, GitHub can't require
  up-to-date branches here, and owner threads build and merge PRs in parallel.
GitHub can't require checks on these private repos on a free plan (branch protection and
rulesets return HTTP 403), so nothing on GitHub's side stops a red merge. On Oct 11, 2026
a Strict stack merged 11 minutes after main went red, and a noyer PR merged with no CI,
no review, and no verify-work run on its final commit. The go never stands in for the
verdict or for failing checks. A command that writes out more than one merge is denied, since the
checks read one. A go is a short literal merge request (merge_go.py), or a
pick of the reply's stop:merge option whose text is itself one (turn_block.py) and names the
PR or none; a T3 delegated child, a question, or a "don't merge" gives none. A pick answers
the last reply before it, past messages T3 says another agent sent that landed in the same
turn, such as a worker's result that arrived as they typed, whose own turn blocks never
count; a denial says what a pick picked and why it isn't a go. Messages another thread sent
are dropped (transcripts.py); in T3, a state database it can't read, or a session no T3
thread owns, gives no go.
The user merging from their own terminal isn't affected. Fails closed: when a check can't
run, the merge is denied. Codex runs it too, but a crash or timeout there lets the merge
through, since Codex has no `onFailure: "block"`. Known limits: merges through `gh api`
or a push to the base branch, `gh` run by its path, a command that runs only inside
quotes or a heredoc, one merge a tool such as `xargs` repeats, and in Codex a merge
reached only through `workdir`, which is checked against the session's cwd.

`merge-gate.py --dry-run '<merge command>' [--transcript PATH] [--session ID]` runs the same
checks from the current directory and prints the PRs it resolves, then each reason or
`would pass` (exit 1 or 0). It reads the latest prompt from this session's transcript
(CLAUDE_CODE_SESSION_ID in Claude Code, CODEX_THREAD_ID in Codex), so ask it in the turn
that would merge."""
import contextlib, glob, json, os, re, subprocess, sys

DRY_RUN = sys.argv[1:2] == ["--dry-run"]
# Where the deny reasons send an agent that merged from the wrong checkout.
STACK_SH = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "scripts",
                                         "stack.sh")).replace(os.path.expanduser("~"), "~", 1)

def dry_run_payload(argv):
    if not argv or argv[0].startswith("-") or len(argv) % 2 == 0:
        sys.exit("usage: merge-gate.py --dry-run '<merge command>' [--transcript PATH] [--session ID]")
    flags = dict(zip(argv[1::2], argv[2::2]))
    if set(flags) - {"--transcript", "--session"}:
        sys.exit(f"merge-gate.py --dry-run: unknown flag {sorted(set(flags) - {'--transcript', '--session'})[0]}")
    session = flags.get("--session") or os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CODEX_THREAD_ID")
    import hook_parity  # here: only a dry run looks the transcript up
    claude, codex = hook_parity.config.claude_home(), os.environ.get("CODEX_HOME") or "~/.codex"
    transcripts = sorted(glob.glob(f"{claude}/projects/*/{session}.jsonl")
                         + glob.glob(os.path.expanduser(f"{codex}/sessions/*/*/*/rollout-*-{session}.jsonl")),
                         key=os.path.getmtime) if session else []
    return {"tool_input": {"command": argv[0]}, "cwd": os.getcwd(), "session_id": session,
            "transcript_path": flags.get("--transcript") or (transcripts[-1] if transcripts else None)}

payload = dry_run_payload(sys.argv[2:]) if DRY_RUN else json.load(sys.stdin)
command = (payload.get("tool_input") or {}).get("command", "")
cwd = payload.get("cwd") or os.getcwd()

# Heredoc bodies and quoted strings are data (PR bodies, grep patterns), not commands.
code = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?.*?\n.*?\n\1\b", "", command, flags=re.S)
code = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", code)
# Redirections aren't arguments: `gh stack merge --yes 2>&1` merges the current stack.
code = re.sub(r"\d*(?:>>?|<)(?:&\d+-?|\s*[^\s;&|]+)", " ", code)
# Every merge the command would run: --help only prints, and --disable-auto only turns auto-merge off.
merges = [found for found in re.finditer(r"\bgh\s+(pr|stack)\s+merge\b([^;&|\n]*)", code)
          if not {"-h", "--help", "--disable-auto"} & set(found.group(2).split())]
match = merges[0] if merges else None
kind, args = (match.group(1), match.group(2).split()) if match else (None, [])
if not match:
    if DRY_RUN:
        print("would pass: no `gh pr merge` or `gh stack merge` outside quotes for the gate to check")
    sys.exit(0)

cds = re.findall(r"\bcd\s+(\S+)", code[:match.start()])
if cds:
    cwd = os.path.normpath(os.path.join(cwd, os.path.expanduser(cds[-1])))
# The merge lines gate's no-go merge trusts, as `stack.sh where` prints them: the whole command
# is at most one cd, an optional `gh pr ready N`, and one merge of a PR by number, or of this
# checkout's stack, with no flag that can name another repo. Any other shell, such as a
# subshell or -R, could merge something the checks below never saw, so it needs the go.
BOUND = re.compile(r"\s*(?:cd\s+[^\s;&|()<>`$'\"]+\s*&&\s*)?(?:gh\s+pr\s+ready\s+\d+\s*&&\s*)?"
                   r"gh\s+(?:pr\s+merge\s+\d+|stack\s+merge(?:\s+\d+)?)"
                   r"(?:\s+(?:--merge|--squash|--rebase|--delete-branch|--auto|--yes|-[msrd]))*\s*")
bound = bool(BOUND.fullmatch(command)) and not os.environ.get("GH_REPO")

def deny(*reasons):
    if DRY_RUN:
        print("".join(f"- {reason}\n" for reason in reasons) + "would deny")
        sys.exit(1)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"Merge gate: {'; '.join(reasons)}. Fix what's listed and merge again, "
                                    "or ask the user to merge it themselves. Don't route around "
                                    "the gate with `gh api` or a push to the base branch.",
    }}))
    sys.exit(0)

# The checks below read one merge, so a second would merge on the first one's go and verdict.
if len(merges) > 1:
    deny(f"this command runs {len(merges)} merges and the gate checks one: run each merge as its own command")

def run(*cmd):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=40)
    if result.returncode:
        raise RuntimeError(f"`{' '.join(cmd[:4])}` failed: {result.stderr.decode(errors='replace').strip()[:200]}")
    return result.stdout.decode(errors="surrogateescape")

# A PR an option names, read word by word in merge_go's REF forms: 12, #12, skills#12,
# owner/skills#12, skills #12 read as skills#12, and 10-14 or #10-#14. Two joined by
# "through", "to", or "-" are a range. "the 2 PRs" is a count, and "v2" a name, not a PR;
# a bare "the 13" reads as #13.
PART = r"(?:(?:([\w.-]+)/)?([\w.-]+)#|#)?(\d+)"
WORD = re.compile(rf"{PART}(?:-{PART})?")
COUNT = re.compile(r"\bthe \d+ prs?\b", re.I)

def names(text, pr, owner, repo, merging=()):
    """Whether an option's text names pr in owner/repo, alone or in a range of this repo's
    PRs, or names no PR at all ("merge them"). A PR with its repo, "dotfiles #36" or
    dotfiles#36, is in that repo. A bare one, "#55", is in any repo, unless another PR in the
    text names this repo, so "#55" beside "dotfiles #36" isn't a dotfiles PR, and a range's
    bare end is in its other end's repo. A text that places a PR the merge holds (pr and
    merging) in another repo names none: the word before it may be a refusal or a step
    NOT_REPO misses, as in "merge #10-#14, exclude #12", and so does a text that names a repo
    and names one PR twice. A word that starts like a PR, with a
    digit or holding a #, but doesn't read as one, names something it can't place, so it
    isn't pr."""
    import merge_go
    same = lambda part, want: not part or part.lower() == want.lower()
    here = lambda found, at: same(found.group(at), owner) and same(found.group(at + 1), repo)
    text = merge_go.REPO_REF.sub(r"\1", text)  # "dotfiles #36" reads as dotfiles#36
    text = re.sub(r"\s*-\s*", "-", COUNT.sub(" ", text)).replace(",", " ").replace("&", " ")  # merge_go's REFS joins
    words = [word.strip("()").rstrip(".!?;:") for word in text.split()]
    refs = []
    for at, word in enumerate(words):
        if not (word[:1].isdigit() or "#" in word):
            continue
        found = WORD.fullmatch(word)
        if not found:
            return False
        refs.append((at, found))
    # Each end: whether its repo is this one, or None when it names no repo.
    end = lambda found, at: (here(found, at) if found.group(at + 1) else None, int(found.group(at + 2)))
    spans, last = [], None  # last: the previous PR word's index and its high end
    for at, found in refs:
        low = end(found, 1)
        high = end(found, 4) if found.group(6) else low
        if last and last[0] == at - 2 and words[at - 1].lower() in ("through", "to", "-"):
            spans[-1] = (spans[-1][0], high)  # "#10 through #14" is one range, not three
        else:
            spans.append((low, high))
        last = (at, high)
    bare = not any(here_ for span in spans for here_, _ in span)
    side = lambda one, other: one if one is not None else other if other is not None else bare
    placed = [(side(a[0], b[0]) and side(b[0], a[0]), a[1], b[1]) for a, b in spans]
    held = lambda low, high: any(min(low, high) <= n <= max(low, high) for n in {pr, *merging})  # "#14-#12" too
    if any(not ours and held(low, high) for ours, low, high in placed):
        return False
    # A text that names a repo and names a PR twice may refuse it the second time, even
    # with this repo's name: "merge exclude #10-#14, exclude #12" in a repo named exclude.
    spread = [(min(low, high), max(low, high)) for _, low, high in placed]
    if any(point[0] is not None for span in spans for point in span) and any(
            max(a[0], b[0]) <= min(a[1], b[1]) for i, a in enumerate(spread) for b in spread[i + 1:]):
        return False
    return not spans or any(ours and low <= pr <= high for ours, low, high in placed)

def answered(found):
    """The reply the latest prompt answers: the last one before it, past messages T3 says
    another agent sent (Exchange.agent) that landed in the same turn, such as a worker's
    result that arrived as the user typed. Those messages' own turn blocks never count. Any
    other message in between that got no reply, typed or not, gives None."""
    at = len(found) - 1
    while found[at].reply is None and at and found[at - 1].agent:
        at -= 1
    return found[at].reply

def letter_miss(reply, key):
    """Why the key picks no option of the reply."""
    import turn_block
    if reply is None:
        return "no reply of yours came before it"
    try:
        turn = turn_block.parse(reply)
    except turn_block.Malformed as error:
        return f"your reply before it has no valid turn block ({error})"
    if all(option.key != key for option in turn.options):
        return f"your reply before it offers no option {key}"
    return ("the gate can't be sure your reply's turn block was hidden: it has raw HTML other than "
            "fold lines and autolinks, or a fence line it can't place")

def user_go(numbers, owner, repo):
    """(go, note): whether the user's latest prompt in this session asks to merge the last
    of numbers, pr, and, for a key that doesn't, what it picked and why that isn't a go. A
    go is a literal go (merge_go.py), held to the PRs it names when it names one as
    "dotfiles #36", or a key that picks an option of the reply it answered (answered,
    turn_block.picked) that is a stop:merge, is itself a literal go, and names pr or no PR,
    and no PR of numbers in another repo (names).
    stop:merge also covers marking ready, so "mark #17 ready, but don't merge" isn't one. A
    pick needs that reply's turn block, so an earlier reply's option, a reply without one,
    or a block in a message another agent sent gives no go."""
    pr = numbers[-1]
    try:
        import sqlite3, t3_child, transcripts, turn_block
        from merge_go import literal_go, REPO_REF
        in_t3 = bool(os.environ.get("T3CODE_CLI_PATH"))  # where only T3's database tells another agent from the user
        try:
            with contextlib.closing(t3_child.connect()) as db:
                owners = t3_child.threads(db, payload.get("session_id"))
        except sqlite3.Error:
            if in_t3:
                return False, None
            owners = []
        if any(str(thread).startswith("thread:delegated-task:") for thread, in owners):
            return False, None
        if in_t3 and not owners:  # T3 can't tell its agents' messages from the user's in a session it doesn't own
            return False, None
        # The latest prompt itself: when the user didn't type it, an earlier go doesn't count.
        found = transcripts.exchanges(payload.get("transcript_path"), strict=in_t3)
        prompt = found[-1].prompt if found else ""
        said = f'the user\'s "{prompt.strip()}"'
        if literal_go(prompt):
            # A word before " #N" may be a step or a refusal NOT_REPO misses ("skip #12"), so a
            # typed go that names a PR that way is held to its PRs, as a pick is.
            if not REPO_REF.search(prompt) or names(prompt, pr, owner, repo, numbers):
                return True, None
            return False, f"{said} isn't a merge of #{pr}"
        key = turn_block.PICK.fullmatch(prompt)
        if not key:
            return False, None
        reply = answered(found)
        option = turn_block.picked(reply, prompt)
        if option is None:
            return False, f"{said} picks nothing: {letter_miss(reply, key.group(1).lower())}"
        if option.cls != "stop:merge" or not literal_go(option.text):
            return False, f'{said} picks "{option.text}" from your reply before it, which isn\'t a merge go'
        if not names(option.text, pr, owner, repo, numbers):
            return False, (f'{said} picks "{option.text}" from your reply before it, not a merge of #{pr}; '
                           "a turn block in a message you didn't write, such as a worker's result, never counts")
        return True, None
    except Exception:
        return False, None

def base_overlap(pull):
    """Paths both the PR and its base branch changed since the PR branched, against the
    fetched base tip: GitHub's baseRefOid stays where the PR last synced."""
    tip = run("git", "rev-parse", "--verify", f"refs/remotes/origin/{pull['baseRefName']}^{{commit}}").strip()
    fork = run("git", "merge-base", tip, pull["headRefOid"]).strip()
    if fork == tip:
        return []
    changed = lambda oid: set(filter(None, run("git", "diff", "-z", "--name-only", "--no-renames", fork, oid).split("\0")))
    return sorted(changed(pull["headRefOid"]) & changed(tip))

def ci_skips(n, pull, default):
    """Whether every workflow at the PR's base, head, merge commit, and the default branch
    skips it by its path or branch filters. Any failure, such as a conflicting PR's missing
    merge commit, or a workflow it can't read, counts as CI."""
    try:
        import workflow_triggers
        merge_oid = pull["potentialMergeCommit"]["oid"]  # null while conflicting or being made
        run("git", "fetch", "--quiet", "--no-tags", "origin", f"pull/{n}/merge", default["name"])
        return workflow_triggers.skipped(cwd, pull["baseRefName"], pull["baseRefOid"], pull["headRefOid"],
                                         merge_oid, default["target"]["oid"])
    except Exception:
        return False

VALUE_FLAGS = {"-R", "--repo", "-b", "--body", "-F", "--body-file", "-t", "--subject",
               "-A", "--author-email", "--match-head-commit", "--method"}
repo, positional, skip = None, [], False
for i, arg in enumerate(args):
    if skip:
        skip = False
    elif arg in ("-R", "--repo"):
        repo, skip = (args[i + 1] if i + 1 < len(args) else None), True
    elif arg in VALUE_FLAGS:
        skip = True
    elif not arg.startswith("-"):
        positional.append(arg)
target = positional[0] if positional else None
repo_args = ["-R", repo] if repo else []
# A merge the gate can't place in its checkout gets pointed at the locator.
WHERE = (f"`{STACK_SH} where {'#' + target if target and target.isdigit() else '<branch|#PR>'}`, run in a "
         "checkout of the repo, prints the checkout to merge from and the merge line to run there")

numbers = None
try:
    if kind == "pr":
        numbers = [int(run("gh", "pr", "view", *([target] if target else []), *repo_args,
                           "--json", "number", "--jq", ".number"))]
    else:
        stack = json.loads(run("gh", "stack", "view", "--json"))
        numbers = [b["pr"]["number"] for b in stack["branches"]
                   if b.get("pr") and not b.get("isMerged") and b["pr"].get("state") == "OPEN"]
        if target:
            if not target.isdigit() or int(target) not in numbers:
                deny(f"can't tell which PRs `gh stack merge {target}` merges from this checkout's "
                     f"stack (open PRs: {numbers}); pass one of those PR numbers", WHERE)
            numbers = numbers[:numbers.index(int(target)) + 1]
        if not numbers:
            deny("this checkout's stack has no open PRs to check", WHERE)
    if DRY_RUN:
        print(f"PRs: {', '.join(f'#{n}' for n in numbers)} (from {cwd})")

    owner, name = run("gh", "repo", "view", *([repo] if repo else []), "--json", "owner,name",
                      "--jq", '"\\(.owner.login) \\(.name)"').split()
    prs = " ".join(f"p{n}: pullRequest(number: {n}) {{ number state baseRefName baseRefOid headRefOid "
                   "potentialMergeCommit { oid } stack { number } "
                   "commits(last: 1) { nodes { commit { oid statusCheckRollup { state } } } } }"
                   for n in numbers)
    query = (f"query {{ repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ "
             "defaultBranchRef { name target { ... on Commit { oid statusCheckRollup { state } } } } "
             f"{prs} }} }}")
    data = json.loads(run("gh", "api", "graphql", "-f", f"query={query}"))["data"]["repository"]

    import resolved, verdicts  # here, so a broken module blocks only merges
    # An unresolved policy can still read gate, when every rule is gate, so it never counts.
    policy = resolved.policy(cwd)
    gate = bound and policy.trust == "gate" and "unresolved" not in policy.matched
    default = data["defaultBranchRef"]
    # Diff locally, as the recorder does: `gh pr diff` shortens blob ids its own way and fails
    # past 300 files or 20,000 lines.
    pulls = [data[f"p{n}"] for n in numbers]
    # Each base into its remote-tracking ref, even where the clone's fetch refspec doesn't map it,
    # and in a gate repo the default branch too, for no_ci.
    branches = {p["baseRefName"] for p in pulls} | ({default["name"]} if gate else set())
    run("git", "fetch", "--quiet", "--no-tags", "origin",
        *(f"+refs/heads/{branch}:refs/remotes/origin/{branch}" for branch in branches),
        *(f"pull/{n}/head" for n in numbers))
    done = {n: verdicts.find_done(cwd, verdicts.diff(cwd, p["baseRefOid"], p["headRefOid"]))
            for n, p in zip(numbers, pulls)}
    workflows = lambda oid: bool(run("git", "ls-tree", "-r", "--name-only", oid, "--", ".github/workflows").strip())
    # No checks in a repo with workflows means CI hasn't registered on the head yet, unless
    # every workflow's path and branch filters skip the PR.
    has_ci = {n: workflows(p["baseRefOid"]) for n, p in zip(numbers, pulls)}
    # A gate repo skips the go only where no workflow can run on the PR: none at its base, its
    # head, or the default branch, whose pull_request_target workflows run on every PR. A PR
    # its workflows skip still needs the go, since workflow_triggers reads no push triggers.
    no_ci = {n: gate and not has_ci[n] and not workflows(p["headRefOid"]) and not workflows(default["target"]["oid"])
             for n, p in zip(numbers, pulls)}
    skipped = {n: has_ci[n] and ci_skips(n, p, data["defaultBranchRef"]) for n, p in zip(numbers, pulls)}
    overlap = {n: base_overlap(p) for n, p in zip(numbers, pulls)}
except Exception as error:
    misplaced = numbers is None or isinstance(error, OSError) or "not a git repository" in str(error)
    deny(f"couldn't check the merge ({error})", *([WHERE] if misplaced else []))

reasons, go = [], None
base = data["defaultBranchRef"]
base_state = ((base["target"] or {}).get("statusCheckRollup") or {}).get("state")
if base_state in ("FAILURE", "ERROR"):
    reasons.append(f"`{base['name']}` is red at {base['target']['oid'][:8]}: get it green first")
elif base_state in ("PENDING", "EXPECTED"):
    reasons.append(f"`{base['name']}` checks are still running at {base['target']['oid'][:8]}")
for n in numbers:
    pr = data[f"p{n}"]
    # GitHub links a stack only once it has two PRs, and gh stack merge refuses a lone one.
    if kind == "stack" and "stack" in pr and pr["stack"] is None:
        reasons.append(f"#{n} is in no stack on GitHub, so `gh stack merge` can't merge it: "
                       f"use `gh pr merge {n}`")
    commit = pr["commits"]["nodes"][0]["commit"]
    state = (commit.get("statusCheckRollup") or {}).get("state")
    if state is None and has_ci[n] and not skipped[n]:
        reasons.append(f"#{n} has no checks yet at {commit['oid'][:8]}: wait for CI to register")
    elif state is None and not no_ci[n]:  # a gate repo with no CI needs only the Done checked below
        if go is None:
            go, note = user_go(numbers, owner, name)
        if not go:
            why = ("this repo's CI skips it by its path or branch filters" if skipped[n]
                   else "this repo runs no CI on PRs")
            reasons.append(f"#{n} has no checks: {why}, so it merges only when the user's latest prompt "
                           "asks for the merge")
    elif state not in (None, "SUCCESS"):
        reasons.append(f"#{n} checks are {state.lower()} at {commit['oid'][:8]}")
    if not done[n]:
        reasons.append(f"#{n} has no Done verdict from a fresh work-verifier for its current "
                       "diff: run /verify-work")
    if overlap[n]:
        paths = ", ".join(f"`{path}`" for path in overlap[n][:3])
        more = f", and {len(overlap[n]) - 3} more" if len(overlap[n]) > 3 else ""
        reasons.append(f"#{n}'s base `{pr['baseRefName']}` gained commits since it branched that touch "
                       f"files it changes ({paths}{more}): restack it onto `{pr['baseRefName']}` with "
                       f"`{STACK_SH} restack`, push, and wait for green")
if go is not None and DRY_RUN:
    print(f"go: {'yes' if go else 'no'}, from {payload['transcript_path'] or 'no transcript; pass --transcript'}")
if go is False:
    from merge_go import literal_go
    refs = [f"#{n}" for n in numbers]
    ask = "merge " + " and ".join([", ".join(refs[:-1]), refs[-1]] if len(refs) > 1 else refs)
    reasons.extend([note] if note else [])
    reasons.append(f'ask the user for "{ask if literal_go(ask) else "merge the stack"}"')
if reasons:
    deny(*reasons)
if DRY_RUN:
    print("would pass")
