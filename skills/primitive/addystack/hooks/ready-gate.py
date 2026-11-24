#!/usr/bin/env python3
"""PreToolUse on Bash: before `gh pr ready`, `gh stack submit --open`, or `gh pr create`
(or `gh pr new`) without `--draft`, check each PR the command would mark ready for
review, and deny it unless review-loop recorded a result for that PR's diff in
verify-work's store (verdicts.py `review`): the rounds it ran, or a skip with its reason.
A result matches on patch-id, as a verdict does, so a clean rebase keeps it and a new
commit needs another. A skip passes, and the user sees its reason.
In Nov 2026, R58 found no review-loop at all on three work-repo PRs a teammate later
caught bugs in, and on a doc stack it ran on one layer but not the ones the teammate
commented on. R59 found that review-loop's text catches those bugs when it runs at the
PR's real head.
The hook sees the command before any of it runs, so it denies a ready chained after a
command that can move a branch or a PR's base (a commit, push, rebase, `gh stack` sync,
`gh pr create`, or `gh pr edit --base`): run the ready on its own. It follows the shell's
directory through cd, pushd, and popd, and its GH_REPO, and denies a ready after one it
can't place: inside a subshell, pipeline, or block, after `||`, past the `&&` chain it ran
in, or to where only the shell knows (a variable, ~+, a dir-stack entry, CDPATH, a changed
HOME, zsh's AUTO_CD), and after a GH_REPO change it doesn't follow, such as `export -n`.
Fails closed: when a check can't run, or can't finish in time, it denies. Known limits, as
merge-gate.py's: a PR marked ready through `gh api` or GitHub's web page, `gh` run by its
path or through an alias from `gh alias set`, a command that runs only inside quotes or a
heredoc, a create or submit aimed at a repo other than `origin` (`-R`, `GH_REPO`, a fork's
`owner:branch` head, a push remote), and in Codex a command that reaches its repo only
through `workdir`, and a hook timeout, which Codex lets through. `gh stack submit` without
`--auto` in a terminal opens an editor whose new PRs default to ready; agents run it
without a terminal, which opens drafts."""
import json, os, re, shutil, signal, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
RECORD = os.path.join(HERE, "verdicts.py").replace(os.path.expanduser("~"), "~", 1)
# Under the manifest's 60 s, so a slow check still denies; tests shorten it.
SECONDS = int(os.environ.get("READY_GATE_SECONDS", "45"))

payload = json.load(sys.stdin)
command = (payload.get("tool_input") or {}).get("command", "")

# Heredoc bodies and quoted strings are data (PR bodies, grep patterns), not commands; a
# quoted single word ("12", 'feat/x') is an argument, so it keeps its value, unless it starts
# with #, which would then read as a comment.
code = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?.*?\n.*?\n\1\b", "", command, flags=re.S)
code = re.sub(r"'((?!#)[^'\s;&|<>$]*)'|\"((?!#)[^\"\s;&|<>\\$`]*|\$\{?[A-Za-z_]\w*\}?)\"",
              lambda m: m.group(1) or m.group(2) or "''", code)  # a quoted "$n" stays a variable
code = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", code)
code = re.sub(r"\d*(?:>>?|<)(?:&\d+-?|\s*[^\s;&|]+)", " ", code)  # redirections aren't arguments
# Nor are comments: a # that starts a word, so not after an escaped space.
code = re.sub(r"(?:(?<=[;&|(`])|(?<=(?<!\\)\s)|^)#[^\n]*", "", code, flags=re.M)
MOVES = re.compile(r"\bgit(?:\s+-[Cc]\s+\S+|\s+--?[\w-]+(?:=\S+)?)*\s+(?:commit|push|pull|rebase|reset|merge|cherry-pick|am|revert|checkout|switch)\b"
                   r"|\bgh\s+stack\s+(?:push|submit|rebase|sync|add|modify|checkout|switch|up|down|top|bottom|merge)\b")
# gh commands that move a PR's head or base, or the branch a bare `gh pr ready` reads; co is
# checkout's built-in alias. Aliases from `gh alias set` aren't read.
SHIFTS = {("pr", "checkout"), ("pr", "co"), ("pr", "update-branch"), ("pr", "merge")}
WORDS = {("pr", "ready"): "ready", ("pr", "create"): "create", ("pr", "new"): "create", ("stack", "submit"): "submit"}
# Commands that print or search their arguments, so a gh among them is text, not a command.
TEXT = {"echo", "printf", "print", ":", "true", "false", "test", "[", "[[", "grep", "egrep", "fgrep", "rg", "ag",
        "man", "which", "type", "whatis", "apropos"}
ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")


# The options that take a value, which is never a flag, in the commands the gate reads: gh pr
# create, ready, and edit, and gh stack submit, from gh 2.103's --help. Their short forms
# don't clash: each is valued in all four or in none.
VALUED = {"-R", "--repo", "-t", "--title", "-b", "--body", "-F", "--body-file", "-B", "--base", "-H", "--head",
          "-a", "--assignee", "-l", "--label", "-m", "--milestone", "-p", "--project", "-r", "--reviewer",
          "-T", "--template", "--recover", "--remote", "--attach",
          *(f"--{change}-{what}" for change in ("add", "remove")
            for what in ("assignee", "label", "project", "reviewer"))}


def options(args):
    """gh's flags in args as (name, value) pairs, value None for a bare switch, and its
    positional arguments, read as gh's pflag does: `-df` is `-d -f`, `-Bmain` and `-dB main`
    give -B its value, a valued flag takes the next word even when it starts with -, and `--`
    ends the flags."""
    pairs, positional, at = [], [], 0
    while at < len(args):
        arg, at = args[at], at + 1
        if arg == "--":
            return pairs, positional + args[at:]
        if arg.startswith("--"):
            name, equals, value = arg.partition("=")
            if not equals and name in VALUED and at < len(args):
                value, at, equals = args[at], at + 1, True
            pairs.append((name, value if equals else None))
        elif arg.startswith("-") and len(arg) > 1:
            letters = arg[1:]
            while letters:
                name, letters = "-" + letters[0], letters[1:]
                if letters.startswith("="):
                    pairs.append((name, letters[1:]))
                    break
                if name in VALUED:
                    if not letters and at < len(args):
                        letters, at = args[at], at + 1
                    pairs.append((name, letters))
                    break
                pairs.append((name, None))
        else:
            positional.append(arg)
    return pairs, positional


def flag(args, *names):
    """The value of the last of names in args (`-R x`, `--repo x`, `--repo=x`, `-Rx`), or None."""
    return next((value for name, value in reversed(options(args)[0]) if name in names), None)


def switch(args, *names):
    """Whether a boolean flag, under any of its names, is on: `--open`, `--open=true`, `-d`,
    or `-df`. gh reads a value with Go's strconv.ParseBool, so f, F, false, False, FALSE,
    and 0 are off."""
    value = next((value or "true" for name, value in reversed(options(args)[0]) if name in names), "false")
    return value.lower() not in ("false", "f", "0")


# Shell words that lead a command. A block opens at the first set and closes at CLOSES, and a
# cd or GH_REPO inside one may not run.
OPENS, CLOSES = {"if", "while", "until", "for", "select", "case", "{"}, {"fi", "done", "esac", "}"}
LEADS = OPENS | {"then", "else", "elif", "do", "!", "time", "builtin", "command"}  # builtin cd is cd


def unreadable(word):
    """Whether a path or value holds what only the shell can expand: a variable, a glob, or a
    quoted string with spaces, which reads as ''."""
    return word == "''" or bool(re.search(r"[$*?\[{]", word))


CDPATH = bool(os.environ.get("CDPATH") or re.search(r"(?<![\w$])CDPATH=", code))  # set in the session or command
HOME_SET = bool(re.search(r"(?<![\w$])HOME=", code))  # a cd home or to ~ then goes where the command says


def resolve(command, args, cwd, previous, pushed):
    """Where cd, pushd, or popd leaves the shell, or None when the gate can't read it. cd
    -P resolves symlinks first, as `..` then leaves the link's target."""
    physical = False
    while command == "cd" and args[:1] and re.fullmatch(r"-[LPe@]+", args[0]):
        for letter in args.pop(0)[1:]:
            physical = {"L": False, "P": True}.get(letter, physical)
    if command == "cd" and args == ["-"]:
        return previous
    if command == "popd":
        return pushed.pop() if pushed and not args else None
    path = args[0] if args else "~"
    # A dir-stack entry (+1, -2), a ~ form other than a home (~+, ~-), or a name CDPATH may
    # find elsewhere is where only the shell knows.
    if (len(args) > 1 or (command == "pushd" and not args) or unreadable(path) or path[:1] in "+-"
            or path.startswith("~") and (HOME_SET or os.path.expanduser(path) == path)
            or CDPATH and not re.match(r"(?:/|~|\.\.?(?:/|$))", path)):
        return None
    if command == "pushd":
        pushed.append(cwd)
    target = os.path.join(cwd, os.path.expanduser(path))
    return os.path.realpath(target) if physical else os.path.normpath(target)


def unsure(key, said):
    """Whether a cd or GH_REPO in the current command may not run before what follows, noting
    why in unknown; one that runs only while an && chain holds goes to pending."""
    if depth or ors or "|" in (before, after) or after == "&":
        unknown.setdefault(key, f"{said} inside a subshell, pipeline, or block, or after `||`")
        return True
    if before == "&&":
        pending[key] = f"{said} only if the command before it succeeds"
    return False


# Where the shell is and which repo GH_REPO names as it runs each command; unknown says why the
# gate can't tell from there on, and pending holds what an && chain set, which stands only
# while the chain does.
cwd, previous, pushed = payload.get("cwd") or os.getcwd(), None, []
repo, exported = os.environ.get("GH_REPO") or None, "GH_REPO" in os.environ  # the shell's, from this session's
allexport = False
unknown, pending, depth, cases, tick, ors, moved, readies = {}, {}, 0, 0, False, False, False, []
loops = []  # (name, its words or None when the shell makes them, depth) for each `for` the command is in
if re.search(r"\$\{GH_REPO:?=", command):  # an expansion that assigns, even inside quotes
    unknown["repo"] = "assigns GH_REPO in a `${GH_REPO:=…}` expansion"
pieces = re.split(r"(&&|\|\||[;|&\n()`])", code)  # `$(…)` and backticks run their command
for at in range(0, len(pieces), 2):
    before, after = pieces[at - 1] if at else "", pieces[at + 1] if at + 1 < len(pieces) else ""
    if before in (";", "\n", "&", "||"):
        unknown, pending = {**pending, **unknown}, {}
        ors = before == "||"
    # Inside a case block, a pattern's ) closes no subshell; the block itself keeps depth up.
    depth += {"(": 0 if cases else 1, ")": 0 if cases else -1, "`": -1 if tick else 1}.get(before, 0)
    tick ^= before == "`"
    words = pieces[at].split()
    lead = 0
    while lead < len(words) and (words[lead] in LEADS or ASSIGNMENT.match(words[lead])):
        depth, cases = depth + (words[lead] in OPENS), cases + (words[lead] == "case")
        lead += 1
    if lead and words[lead - 1] == "for" and lead < len(words):
        name = words[lead]
        listed = words[lead + 2:] if words[lead + 1:lead + 2] == ["in"] else None  # bare `for n` reads "$@"
        # A word the shell rewrites (an escape, a quote) isn't the value, and a name the command
        # sets anywhere but a for header (n=13, read n, ((n++))) may not hold it when the ready runs.
        if listed is not None and any(unreadable(word) or re.search(r"[\\'\"`]", word) for word in listed):
            listed = None
        loops.append([name, listed, depth, at])
    # A word that is a loop's name (read n, printf -v n, an inner for n) or sets it (n=13,
    # n+=1, n++, ${n:=13}) may change it before a ready in that loop, which then can't read it.
    for loop in loops:
        n = re.escape(loop[0])
        if any((re.fullmatch(rf"(?:\+\+|--)?{n}(?:\[.*|\+?=.*|\+\+|--)?", word) or re.search(rf"\$\{{{n}:?[=?+-]", word))
               and not (at == loop[3] and word == loop[0] and words.index(word) == lead) for word in words):
            loop[1] = None
    depth, cases = depth - bool(words[:1] and words[0] in CLOSES), cases - (words[:1] == ["esac"])
    loops = [loop for loop in loops if loop[2] <= depth]
    command = words[lead] if lead < len(words) else None
    if command in TEXT:
        continue
    if command and command not in ("cd", "pushd", "popd") and not shutil.which(command) and os.path.isdir(
            os.path.join(cwd, os.path.expanduser(command))):
        unknown.setdefault("dir", f"names the directory `{command}`, which zsh's AUTO_CD enters")
    if command in ("cd", "pushd", "popd") and not unsure("dir", f"runs `{command}`"):
        target = resolve(command, words[lead + 1:], cwd, previous, pushed)
        if target is None:
            unknown.setdefault("dir", f"runs `{' '.join(words[lead:])}`, whose directory it can't read")
        else:
            previous, cwd = cwd, target
    # gh sees GH_REPO only once it's exported: by export, declare -x, set -a, or the session.
    # Any other way a command touches GH_REPO (export -n, typeset +x, env -u) it doesn't follow.
    shell_options = [word for word in (words[lead + 1:] if command in ("export", "declare", "typeset", "unset") else [])
                     if word[:1] in "-+"]
    if command == "set":  # its options run up to `-`, `--`, or the first positional parameter
        given, turned = words[lead + 1:], None
        while given and given[0][:1] in "-+" and given[0] not in ("-", "--"):
            option = given.pop(0)
            if "a" in option[1:] or option.endswith("o") and given[:1] == ["allexport"]:
                turned = option[0] == "-"
            if option.endswith("o"):
                given = given[1:]
        if turned is not None and not unsure("repo", "runs `set`"):
            allexport = turned
    followed = (shell_options in ([], ["-x"]) and command in (None, "export", "declare", "typeset", "unset")
                or "gh" in words and all(ASSIGNMENT.match(word) or word in ("env", *LEADS)
                                         for word in words[:words.index("gh")]))
    if any("GH_REPO" in word for word in words) and not followed:
        unknown.setdefault("repo", f"runs `{' '.join(words[lead:lead + 2])}` on GH_REPO in a way it doesn't follow")
    exports = command == "export" or command in ("declare", "typeset") and shell_options == ["-x"] or allexport
    sets = words if command is None else words[lead + 1:] if command in ("export", "declare", "typeset") else []
    for word in sets:
        name, equals, value = word.partition("=")
        if name == "GH_REPO" and not unsure("repo", "sets GH_REPO"):
            repo, exported = (value or None) if equals else repo, exported or exports
    if command == "unset" and "GH_REPO" in words and not unsure("repo", "unsets GH_REPO"):
        repo, exported = None, False
    if "gh" in words:
        rest = words[words.index("gh") + 1:]
        named = [word[len("GH_REPO="):] for word in words[:words.index("gh")] if word.startswith("GH_REPO=")]
        # gh takes the repo (-R repo, -Rrepo, --repo=repo) before or between its command words.
        globals_, names, at_word = [], [], 0
        while at_word < len(rest) and len(names) < 2:
            word = rest[at_word]
            taken = 2 if word in ("-R", "--repo") else 1
            if word.startswith("-R") or word.startswith("--repo"):
                globals_ += rest[at_word:at_word + taken]
            else:
                names.append(word)
            at_word += taken
        kind, args = WORDS.get(tuple(names)), globals_ + rest[at_word:]
        moved = moved or tuple(names) in SHIFTS or bool(names == ["pr", "edit"] and flag(args, "-B", "--base"))
        if kind and not (switch(args, "-h", "--help") or (kind == "ready" and switch(args, "--undo"))
                         or (kind == "create" and (switch(args, "-d", "--draft") or switch(args, "--dry-run")
                                                   or switch(args, "-w", "--web")))
                         or (kind == "submit" and not switch(args, "--open"))):
            reasons = [f"this command {unknown['dir']}, so the gate can't tell which checkout the ready runs in: "
                       "`cd <checkout> && gh pr ready <N>` on its own"] if "dir" in unknown else []
            # gh takes -R over GH_REPO, and GH_REPO before the command over the shell's.
            value = None
            if not flag(args, "-R", "--repo"):
                value = named[-1] if named else repo if exported else None
                wrapped = [word for word in words[:words.index("gh")] if word[:1] == "-"]  # env -u, env -i
                said = (f"sets GH_REPO to `{value}`, which it can't read" if value and unreadable(value)
                        else f"runs gh after `{' '.join(wrapped)}`, which may change its GH_REPO" if wrapped
                        else None if named else unknown.get("repo"))
                if said:
                    reasons.append(f"this command {said}, so the gate can't tell which repo the ready reads: "
                                   "name it with `-R <owner>/<repo>`")
            # A literal loop's ready runs once per word, as `for n in 12 13; do gh pr ready $n; done`.
            runs, bound = [args], set()
            for name, listed, *_ in reversed(loops):  # the innermost loop's binding of a name wins
                if name in bound:
                    continue
                bound.add(name)
                here = re.compile(rf"\${name}\b|\${{{name}}}")
                if listed and any(here.search(arg) for arg in args):
                    runs = [[here.sub(lambda _, word=word: word, arg) for arg in one] for one in runs for word in listed]
            if kind == "ready" and any("$" in arg for one in runs for arg in one):
                reasons.append(f"its `gh pr ready {' '.join(options(args)[1])}` reads a shell variable the gate "
                               "can't expand: write each PR out, as `gh pr ready 12 && gh pr ready 13`")
            readies += [(kind, one, cwd, value, moved, reasons) for one in runs]
    # A create, even a draft or a dry run, may push its branch first, so it moves a later ready's head.
    moved = moved or bool(MOVES.search(pieces[at])) or "gh" in words and names in (["pr", "create"], ["pr", "new"])
if not readies:
    sys.exit(0)


def deny(*reasons):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"Ready gate: {'; '.join(reasons)}. Run review-loop on each to its end, which "
                                    f"records it, or record a skip with its reason: `python3 {RECORD} review <base> "
                                    "<head> --skip '<reason>'`. Don't route around the gate with `gh api` or the web.",
    }}))
    sys.exit(0)


for *_, reasons in readies:
    if reasons:
        deny(*reasons)
if any(moved for *_, moved, _ in readies):
    deny("this command can move a branch before it marks a PR ready, and the gate checks the heads before "
         "anything runs: push first, then run the ready as its own command")


def out_of_time(*_):
    raise TimeoutError(f"took over {SECONDS} s")


def run(cwd, *cmd):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"`{' '.join(cmd[:4])}` failed: {result.stderr.decode(errors='replace').strip()[:200]}")
    return result.stdout.decode(errors="surrogateescape").strip()


def same_repo(one, other):
    """Whether two remote URLs or paths name the same repo: the same host, port, and path, so
    `git@github.com:o/r.git` and `https://github.com/o/r` match, or the same local path. A
    default port (22, 80, 443) counts as none."""
    def place(url):
        url = url.strip().rstrip("/").removesuffix(".git")
        found = re.fullmatch(r"(?:[a-z][\w+.-]*://)?(?:[^@/]+@)?([^/:]+)(?::(\d+))?[:/](.+)", url)
        if not found:
            return None, None, os.path.normpath(url)
        host, port, path = found.groups()
        return host.lower(), None if port in (None, "22", "80", "443") else port, path.lower()
    return place(one) == place(other)


def origin(cwd):
    """The checkout's origin URL, or "" outside a checkout or without one."""
    return subprocess.run(["git", "remote", "get-url", "origin"], cwd=cwd, capture_output=True, text=True).stdout


def targets(kind, args, cwd):
    """The checkout to check in, and (label, base, head) for each PR the command marks ready,
    as refs or SHAs."""
    repo = flag(args, "-R", "--repo")
    if kind == "ready":
        positional = options(args)[1]
        pr = json.loads(run(cwd, "gh", "pr", "view", *positional[:1], *(["-R", repo] if repo else []),
                            "--json", "number,url,baseRefName,baseRefOid,headRefOid"))
        # A PR another repo holds (-R, GH_REPO, its URL, or gh's pick in a fork's clone) is fetched from it.
        home = re.sub(r"/pull/\d+/?$", "", pr["url"])
        # A ready that names its repo (-R, GH_REPO) and runs outside any checkout, as `cd ~ && gh
        # pr ready 12 -R o/r`, is checked in the session's own checkout when that's a clone of
        # the PR's repo: the gate needs only its git objects and verdict store.
        session = payload.get("cwd") or os.getcwd()
        inside = lambda path: subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path, capture_output=True,
                                             text=True).stdout.strip() == "true"  # a bare repo prints false
        named = bool(repo or os.environ.get("GH_REPO"))
        if named and not inside(cwd) and cwd != session and inside(session) and same_repo(origin(session), home):
            cwd = session
        elif named and not inside(cwd):
            raise RuntimeError(f"`{cwd}` isn't a checkout of {home}, so its verdicts can't be read: run it from one, "
                               f"as `cd <checkout of {home}> && gh pr ready {pr['number']}`")
        source = "origin" if origin(cwd).strip() and same_repo(origin(cwd), home) else home + ".git"
        run(cwd, "git", "fetch", "--quiet", "--no-tags", source, pr["baseRefName"], f"pull/{pr['number']}/head")
        return cwd, [(f"#{pr['number']}", pr["baseRefOid"], pr["headRefOid"])]
    if kind == "create":
        # gh's own picks: --head names a pushed branch it won't push; the base is --base,
        # then the branch's gh-merge-base config, then the default branch.
        named = flag(args, "-H", "--head")
        branch = named or run(cwd, "git", "branch", "--show-current")
        config = subprocess.run(["git", "config", f"branch.{branch}.gh-merge-base"], cwd=cwd, capture_output=True,
                                text=True).stdout.strip()
        base = flag(args, "-B", "--base") or config or run(
            cwd, "gh", "repo", "view", *([repo] if repo else []), "--json", "defaultBranchRef",
            "--jq", ".defaultBranchRef.name")
        refs = [base] + ([branch] if named else [])
        run(cwd, "git", "fetch", "--quiet", "--no-tags", "origin",
            *(f"+refs/heads/{ref}:refs/remotes/origin/{ref}" for ref in refs))
        return cwd, [(f"the new PR from {branch}", f"refs/remotes/origin/{base}",
                      f"refs/remotes/origin/{branch}" if named else branch)]
    remote = flag(args, "--remote") or "origin"
    stack = json.loads(run(cwd, "gh", "stack", "view", "--json"))
    trunk = stack["trunk"]
    run(cwd, "git", "fetch", "--quiet", "--no-tags", remote, f"+refs/heads/{trunk}:refs/remotes/{remote}/{trunk}")
    found, parent = [], f"refs/remotes/{remote}/{trunk}"
    for branch in stack["branches"]:  # bottom first; submit pushes each local branch first
        if branch.get("isMerged") or branch.get("isQueued"):
            continue
        pr = branch.get("pr") or {}
        found.append((f"#{pr['number']}" if pr.get("number") else branch["name"], parent, branch["name"]))
        parent = branch["name"]
    return cwd, found


missing, skips = [], []
signal.signal(signal.SIGALRM, out_of_time)
signal.alarm(SECONDS)
try:
    import verdicts  # here, so a broken verdicts.py blocks only readying, and denies
    for kind, args, cwd, repo, *_ in readies:
        # The gate's gh calls see the GH_REPO this ready's gh would; -R in args still wins.
        os.environ.pop("GH_REPO", None)
        os.environ.update({"GH_REPO": repo} if repo else {})
        cwd, found = targets(kind, args, cwd)
        for label, base, head in found:
            base, head = (run(cwd, "git", "rev-parse", "--verify", f"{ref}^{{commit}}") for ref in (base, head))
            review = verdicts.find_review(cwd, verdicts.diff(cwd, base, head))
            if not review:
                missing.append(f"{label} has no review-loop result for its diff at head {head[:12]} "
                               f"(base {base[:12]})")
            elif review.skipped:
                skips.append(f"{label} skipped review-loop: {review.skipped}")
except Exception as error:
    signal.alarm(0)
    deny(f"couldn't check the PRs this marks ready ({error})")
signal.alarm(0)
if missing:
    deny(*missing)
if skips:
    said = "Ready gate: " + "; ".join(skips)  # the user sees systemMessage; the agent, additionalContext
    print(json.dumps({"systemMessage": said, "hookSpecificOutput": {
        "hookEventName": "PreToolUse", "additionalContext": f"{said}. Name the skip in the PR's checks line."}}))
