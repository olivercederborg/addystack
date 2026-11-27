#!/usr/bin/env python3
"""The weekly trust scorecard: the six metrics of the suite-audit R26 design, each a
question about whether Oliver can trust his agents' output, computed for one or more
windows from his own data with no model call. Read-only throughout.

  1 Scope creep: not measured here; scope_judge.py measures it, with a Codex judge.
  2 Defects past the agent: on Oliver's franklin-next PRs merged in the window,
    CodeRabbit Major or Critical threads and teammate threads per PR. Post-merge fix PRs
    are not measured yet.
  3 Oliver's corrections per merged PR: his typed T3 messages (and Slack asks) that match
    the correction, scope, or quality-bar patterns of suite-audit R23a, over his PRs
    merged in any repo.
  4 Rework: the share of branches whose first verify-work verdict is Done, by repo, and
    the Not done verdicts' findings by severity. A verdict recorded without its branch
    joins the branch by patch-id or git history (lineages).
  5 Coverage: the share of Oliver's franklin-next squash merges into develop whose
    patch-id has a Done verdict.
  6 Kit cost: always-loaded words, SKILL.md words, and kit code lines at origin/main as
    of the window's end; PreToolUse denials per 100 Claude tool calls.

`dump START END` prints this machine's raw rows for a UTC window as JSON: Oliver's T3
messages, every verify-work verdict under ~/Developer, and the Claude tool calls and hook
denials in ~/.claude/projects. It runs on a remote host as `ssh HOST python3 - dump START
END < scorecard.py`, so its path is stdlib only and imports nothing from hooks/.

  scorecard.py 2026-10-19 2026-10-26 [--days 7] [--json] [--hosts devbox]

scores one window per start date, `--days` long, from local midnight (Europe/Copenhagen).
It needs gh and the franklin-next clone, and fetches that clone's develop branch first."""
from __future__ import annotations

import argparse, glob, io, json, re, sqlite3, subprocess, sys, tarfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

STATE_DB = "~/.t3/userdata/statev2.sqlite"
DEVELOPER = "~/Developer"
PROJECTS = "~/.claude/projects"
HOSTS = ("devbox",)
LOCAL = "mac"
ZONE = "Europe/Copenhagen"
LOGIN = "olivercederborg"
FRANKLIN = "hifranklin-tech/franklin-next"
FRANKLIN_CLONE = "~/Developer/work/franklin/franklin-next"
FRANKLIN_BASE = "develop"
KIT = Path(__file__).resolve().parent.parent

# --- dump: this machine's raw rows (stdlib only, Python 3.9) -------------------------------

# Oliver's typed messages, and agent-written prompts that carry his Slack ask. Imported
# threads replay native sessions and record every prompt as his, so they're skipped
# (correct/scripts/corrections.py).
MESSAGES = """
select m.created_at, m.thread_id, t.title, json_extract(m.payload_json, '$.createdBy'),
       json_extract(m.payload_json, '$.text')
from orchestration_v2_projection_messages m
join orchestration_v2_projection_threads t on t.thread_id = m.thread_id
where m.role = 'user' and m.created_at >= ? and m.created_at < ? and m.thread_id not like 'import:%'
  and (json_extract(m.payload_json, '$.createdBy') = 'user'
       or json_extract(m.payload_json, '$.text') like '%Oliver''s ask: %')
order by m.created_at"""
SLACK_ASK = re.compile(r"Oliver's ask: (.*)")
# verify-work writes a finding as "<n> · <Severity> · <text> · <where> → <action>".
SEVERITY_WORD = re.compile(r"\b(Blocker|Cleanup|Optional)\b")
TIMESTAMP = re.compile(r'"timestamp":"([^"]+)"')
TOOL_USE = re.compile(r'"type":"tool_use","id":"([^"]+)"')
DENIAL = re.compile(r'"content":"(?:Error: )?PreToolUse:\w+ hook (?:error|blocking error)(?:[^"\\]|\\.)*",'
                    r'"is_error":true,'
                    r'"tool_use_id":"([^"]+)"')


def messages(db_path, start, end):
    """[created_at, thread_id, title, by, text]: `by` is "user" for a typed message and
    "slack" for an agent prompt quoting Oliver's Slack ask, whose text is the ask alone."""
    if not Path(db_path).expanduser().exists():
        return []
    uri = Path(db_path).expanduser().resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        rows = db.execute(MESSAGES, (start, end)).fetchall()
    finally:
        db.close()
    out = []
    for created_at, thread_id, title, by, text in rows:
        if by != "user":
            ask = SLACK_ASK.search(text or "")
            if not ask:
                continue
            by, text = "slack", ask.group(1).strip()
        out.append([created_at, thread_id, title or "", by, text or ""])
    return out


def verdicts(developer):
    """{repo folder name: [[patch-id, recorded_at, verdict, lineage, {severity: count}],
    ...]} from every verify-work store under `developer`, read as hooks/verdicts.py does: a
    v2 row is a Done, a v3 row carries its verdict, findings, and maybe its branch, and other
    rows don't count. Stores kept only Done verdicts, as v2 rows, before 2026-10-25, so a v2
    row's findings are None. `lineage` names the branch a verdict was on (see lineages and
    unproven)."""
    out = {}
    root = Path(developer).expanduser()
    for depth in range(1, 5):
        for store in sorted(glob.glob(str(root / ("*/" * depth) / ".git/verify-work/verdicts.tsv"))):
            parsed = []  # [patch-id, head, base, recorded_at, verdict, branch, severities]
            for line in Path(store).read_text(errors="replace").splitlines():
                row = line.split("\t")
                if len(row) < 8 or row[7] != "work-verifier":
                    continue
                if len(row) == 8 and row[4] == "v2":
                    parsed.append([*row[:4], "done", "", None])
                elif len(row) == 9 and row[4] == "v3":
                    try:
                        body = json.loads(row[8])
                        severities = {}
                        for finding in body["findings"]:
                            found = SEVERITY_WORD.search(finding)
                            name = found.group(1) if found else "unlabeled"
                            severities[name] = severities.get(name, 0) + 1
                        parsed.append([*row[:4], body["verdict"], body.get("branch") or "", severities])
                    except (ValueError, KeyError, TypeError, AttributeError):
                        continue
            repo = Path(store).parents[2]
            names = unproven(repo, parsed, lineages(repo, parsed))
            out.setdefault(repo.name, []).extend(
                [r[0], r[3], r[4], name, r[6]] for r, name in zip(parsed, names))
    return out


def unproven(repo, rows, names):
    """`names`, with "~" before each branch chain whose first verdict may not be the first
    on its commits, so metric 4 leaves it out: one whose first range git can't read; one
    holding a commit authored before the store's first branch-named verdict, since Not
    done verdicts went unstored before 2026-10-25 and unnamed ones can't be traced; and
    one sharing a commit's patch-id with an earlier verdict that names no branch, as when
    a layer verified at a detached HEAD is rewritten and then verified on its branch."""
    names_from = min((row[3] for row in rows if row[5]), default=None)
    first = {}
    for row, name in zip(rows, names):
        if not name.startswith("~") and (name not in first or row[3] < first[name][3]):
            first[name] = row

    def git(*args, stdin=None):
        done = subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True, text=True,
                              errors="replace")
        return done.stdout if done.returncode == 0 else None

    def commits(base, head):
        """(oldest author time in UTC, {per-commit patch-id}) for base..head, or None."""
        dates, diffs = git("log", "--format=%aI", f"{base}..{head}"), git("log", "-p", "--format=commit %H",
                                                                          f"{base}..{head}")
        ids = git("patch-id", "--stable", stdin=diffs) if diffs is not None else None
        if not dates or ids is None:
            return None
        oldest = min(datetime.fromisoformat(d).astimezone(timezone.utc) for d in dates.split())
        return oldest.strftime("%Y-%m-%dT%H:%M:%SZ"), {line.split()[0] for line in ids.splitlines()}

    unnamed = [(row[3], commits(row[2], row[1])) for row, name in zip(rows, names)
               if name.startswith("~") and names_from and row[3] >= names_from]
    early = set()
    for name, (_patch, head, base, recorded_at, *_rest) in first.items():
        found = commits(base, head)
        if found is None or found[0] < names_from or any(
                at < recorded_at and theirs and found[1] & theirs[1] for at, theirs in unnamed):
            early.add(name)
    return ["~" + name if name in early else name for name in names]


def lineages(repo, rows):
    """For each row, the branch its verdict was on. Rows recorded before verdicts named the
    branch, and later ones at a detached HEAD, name none, so a row joins an earlier chain
    holding its patch-id (a clean rebase or a rerun), or one with the same base whose head
    its own head descends from (a fix on the branch), and takes the name any row of that
    chain carries. A chain with no name is named by its first base and head. A branch whose
    rebase changed its diff, or that merged its base in, starts a new chain."""
    chains = []  # {"name", "base", "heads", "patches", "first"}
    order = sorted(range(len(rows)), key=lambda i: rows[i][3])
    found = [None] * len(rows)

    def descends(old, new):
        return old == new or subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", old, new],
                                            capture_output=True).returncode == 0

    for i in order:
        patch, head, base, _at, _verdict, branch, _severities = rows[i]
        free = [c for c in chains if not branch or not c["name"]]
        chain = next((c for c in chains if branch and c["name"] == branch), None) or next(
            (c for c in free if patch in c["patches"]), None) or next(
            (c for c in free if c["base"] == base and any(descends(h, head) for h in reversed(c["heads"]))), None)
        if chain is None:
            chain = {"name": branch, "base": base, "heads": [], "patches": set(),
                     "first": f"~{base[:10]}..{head[:10]}"}
            chains.append(chain)
        chain["name"] = chain["name"] or branch
        chain["heads"].append(head)
        chain["patches"].add(patch)
        found[i] = chain
    return [c["name"] or c["first"] for c in found]


def tool_calls(projects, start, end):
    """{UTC hour "YYYY-MM-DDTHH": [tool calls, PreToolUse denials]} for Claude entries in
    the window, each tool-use id counted once, in the hour first seen, since a resumed or
    forked session copies earlier entries."""
    seen, hours = set(), {}
    floor = datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp()
    for path in Path(projects).expanduser().rglob("*.jsonl"):
        try:
            if path.stat().st_mtime < floor:
                continue
            with path.open(errors="replace") as lines:
                for line in lines:
                    uses, denial = '"type":"tool_use"' in line, "PreToolUse:" in line
                    if not (uses or denial):
                        continue
                    stamp = TIMESTAMP.search(line)
                    if not stamp or not start <= stamp.group(1) < end:
                        continue
                    for kind, ids in enumerate((TOOL_USE.findall(line), DENIAL.findall(line))):
                        for tool_id in ids:
                            if (kind, tool_id) not in seen:
                                seen.add((kind, tool_id))
                                hours.setdefault(stamp.group(1)[:13], [0, 0])[kind] += 1
        except OSError:
            continue
    return hours


def dump(start, end, home="~"):
    """This machine's raw rows for the UTC window [start, end)."""
    base = Path(home).expanduser()
    return {"messages": messages(base / STATE_DB.replace("~/", ""), start, end),
            "verdicts": verdicts(base / DEVELOPER.replace("~/", "")),
            "tools": tool_calls(base / PROJECTS.replace("~/", ""), start, end)}


# --- score: metrics per window -------------------------------------------------------------

# Theme patterns from suite-audit R23a's themes.py, kept verbatim so the baseline holds.
THEMES = {
    "correction": r"\bagain\b|i (already|told)|already did|dont make that mistake|not what i meant|wrong|"
                  r"still (not|seeing|showing|doesn|doesnt|being)|\bstop\b|\bfuck|shit|what the hell|\?\?\?|"
                  r"come on|STOP|so what is the issue|doesnt work|isnt working|not working",
    "scope": r"follow-?up|out of scope|\bscope\b|minimal|simplif|same pr|this pr|new pr|separate pr|stack (it )?on|"
             r"as a new pr|in the current pr|bigger than",
    "quality-bar": r"(best|cleanest|most|correct|right|final|idiomatic|minimal).{0,40}\?|"
                   r"best (long[- ]?term|practice|approach|fix|solution)|long[- ]?term (fix|solution|approach)|"
                   r"idiomatic|effect[- ](native|idiomatic)",
}
THEME_PATTERNS = {name: re.compile(pattern, re.I) for name, pattern in THEMES.items()}
# A bare letter pick ("a", "b and c") or a resume says nothing about the work.
BARE = re.compile(r"^\s*[a-z](\s*(,|and|then|\+)\s*[a-z])*\s*[.!]?\s*$", re.I)
SKIPPED = ("/compact", "continue where you left off")
# CodeRabbit writes a thread's severity as "<icon></picture> Major**" or "**🟠 Major**".
SEVERITY = re.compile(r"(?:</picture>|\*\*\W*)\s*(Critical|Major|Minor|Trivial|Nitpick)\*\*")
SCOPE, FIXES = "1 scope creep", "2 post-merge fix PRs"
NOT_MEASURED = {
    SCOPE: "needs a model; scope_judge.py measures it",
    # On 10-17..31, 3 PRs had a fix title and named no PR; 7 PRs named an earlier Oliver PR,
    # and about half of those were follow-ups, not fixes.
    FIXES: "no deterministic link from a fix to the PR it fixes: a PR naming an earlier one is "
                          "as often a follow-up; needs the step-2 judge or a trailer naming the fixed PR",
}
NO_BRANCHES = ("no branch chain whose first verdict is known starts in this window: verdicts name their branch "
               "from 2026-10-26 (franklin-next), and a chain begun before that is left out")
DONE_ONLY = ("the window starts before {}, when the stores began keeping Not done verdicts, so a count would cover "
             "only part of it")
# measure.py's always-loaded set (suite-audit footprint): what every Claude session reads,
# with reply-shape where the kit kept it before and after skills moved to skills/<layer>/.
ALWAYS_LOADED = ("global/built/claude-code.md", "router.md", "principles/index.md", "replies.md",
                 "reply-shape/SKILL.md", "skills/optional/reply-shape/SKILL.md")
# The instruction files of that set. A kit without them, as addystack builds them from
# core/ and the user's config, gives no count.
INSTRUCTIONS = ALWAYS_LOADED[:4]
NO_INSTRUCTIONS = ("the kit at this commit has no instruction files to count: addystack builds them from core/ "
                   "and the user's config")

PR_FIELDS = "number mergedAt mergeCommit { oid }"
SEARCH = """query($q: String!, $after: String) { search(query: $q, type: ISSUE, first: 50, after: $after) {
  issueCount pageInfo { hasNextPage endCursor }
  nodes { ... on PullRequest { %s } } } }"""
THREADS = "reviewThreads(first: 100) { nodes { comments(first: 1) { nodes { author { login __typename } body } } } }"


def run(cmd, stdin=None, timeout=600):
    """The one way the scorecard runs ssh, gh, and git, so tests can fake it."""
    done = subprocess.run(cmd, input=stdin, capture_output=True, text=True, errors="replace", timeout=timeout)
    if done.returncode:
        raise RuntimeError(f"{' '.join(cmd[:3])} exited {done.returncode}: {done.stderr.strip()[:300]}")
    return done.stdout


def window(day, days):
    """The UTC bounds of `days` local days from `day`, as ISO strings with a Z."""
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(ZONE)
    start = datetime.combine(day, time(), zone)
    end = datetime.combine(day + timedelta(days=days), time(), zone)
    return tuple(t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") for t in (start, end))


def search(query, fields, runner=run):
    """Every pull request a GitHub search finds, through gh's GraphQL API."""
    nodes, after = [], None
    while True:
        args = ["gh", "api", "graphql", "-f", f"query={SEARCH % fields}", "-F", f"q={query}"]
        if after:
            args += ["-F", f"after={after}"]
        found = json.loads(runner(args))["data"]["search"]
        nodes += [node for node in found["nodes"] if node]
        if not found["pageInfo"]["hasNextPage"]:
            return nodes
        after = found["pageInfo"]["endCursor"]


def ratio(num, den, places=2, per=1):
    """num/den, times `per` (100 for a rate per 100), with both counts kept."""
    return {"value": round(per * num / den, places) if den else None, "num": num, "den": den}


def defects(prs):
    """Metric 2 from Oliver's franklin-next PRs merged in the window, with their review
    threads: a thread counts by its first comment's author."""
    severe = teammate = 0
    for pr in prs:
        for thread in pr["reviewThreads"]["nodes"]:
            first = (thread["comments"]["nodes"] or [{}])[0]
            author = first.get("author") or {}
            if author.get("__typename") == "Bot":
                found = SEVERITY.search(first.get("body") or "")
                severe += bool(author["login"].startswith("coderabbit") and found
                               and found.group(1) in ("Major", "Critical"))
            elif author.get("login") not in (None, LOGIN):
                teammate += 1
    return {"2 CodeRabbit Major or Critical per PR": ratio(severe, len(prs)),
            "2 teammate threads per PR": ratio(teammate, len(prs)),
            FIXES: {"value": None, "not measured": NOT_MEASURED[FIXES]}}


def corrections(rows, merged_prs, start, end):
    """Metric 3: Oliver's messages in the window matching a theme, per PR he merged. A
    message sent the same minute with the same words on two machines counts once."""
    import transcripts  # hooks/, put on the path by main()

    seen, counts, any_theme = set(), {name: 0 for name in THEMES}, 0
    for created_at, _thread, _title, by, text in rows:
        if not start <= created_at < end:
            continue
        said = (text if by == "slack" else transcripts.typed(text)).strip()
        if not said or BARE.match(said) or said.lower().startswith(SKIPPED) or (said, created_at[:16]) in seen:
            continue
        seen.add((said, created_at[:16]))
        hits = [name for name, pattern in THEME_PATTERNS.items() if pattern.search(said)]
        for name in hits:
            counts[name] += 1
        any_theme += bool(hits)
    return {"3 corrections per merged PR": {**ratio(any_theme, merged_prs),
                                            "detail": {**counts, "messages": len(seen)}}}


def rework(stores, start, end):
    """Metric 4: per repo, the named branches whose first verdict ever falls in the window,
    and how many of those first verdicts are Done; and the Not done verdicts' findings in
    the window, by severity. Machines' stores for one repo are joined by branch name. A
    chain whose first verdict can't be known ("~": unnamed, so maybe a restacked layer, or
    begun before its store named branches) is left out and counted in the detail."""
    first, severities, full_from = {}, {}, None
    for repo, rows in stores.items():
        for _patch, recorded_at, verdict, lineage, found in rows:
            first[(repo, lineage)] = min(first.get((repo, lineage), (recorded_at, verdict)), (recorded_at, verdict))
            if found is None:
                continue
            full_from = min(full_from or recorded_at, recorded_at)
            if verdict == "not-done" and start <= recorded_at < end:
                for name, count in found.items():
                    severities[name] = severities.get(name, 0) + count
    by_repo, left_out = {}, 0
    for (repo, lineage), (recorded_at, verdict) in first.items():
        if start <= recorded_at < end:
            if lineage.startswith("~"):
                left_out += 1
                continue
            tally = by_repo.setdefault(repo, [0, 0])
            tally[0] += verdict == "done"
            tally[1] += 1
    total = [sum(t[0] for t in by_repo.values()), sum(t[1] for t in by_repo.values())]
    detail = {**{repo: f"{done}/{n}" for repo, (done, n) in sorted(by_repo.items())}, "left out": left_out}
    findings = sum(severities.values())

    def first_pass(done, branches):
        return ratio(done, branches) if branches else {"value": None, "not measured": NO_BRANCHES}

    # A window that starts before the stores kept Not done verdicts would count part of
    # itself and read as growth next to a full week.
    partial = full_from is None or start < full_from
    return {"4 first-pass Done: franklin-next": first_pass(*by_repo.get("franklin-next", [0, 0])),
            "4 first-pass Done: all repos": {**first_pass(*total), "detail": detail},
            "4 Not done findings, all repos": (
                {"value": None, "not measured": DONE_ONLY.format(full_from[:10] if full_from else "2026-10-25")}
                if partial else {"value": findings, "num": findings, "den": None,
                                 "detail": dict(sorted(severities.items()))})}


def patch_id(clone, oid, runner=run):
    """The verbatim patch-id of a squash merge's own diff, as hooks/verdicts.py keys a verdict."""
    diff = runner(["git", "-C", clone, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "--full-index",
                   f"{oid}^", oid])
    return (runner(["git", "-C", clone, "patch-id", "--verbatim"], stdin=diff).split(" ") or [""])[0]


def on_base(clone, oid, runner=run):
    """Whether a commit is on origin/develop; RuntimeError when the clone lacks it."""
    runner(["git", "-C", clone, "cat-file", "-e", f"{oid}^{{commit}}"])
    try:
        runner(["git", "-C", clone, "merge-base", "--is-ancestor", oid, f"origin/{FRANKLIN_BASE}"])
        return True
    except RuntimeError:
        return False


def coverage(prs, rows, clone, runner=run):
    """Metric 5: of Oliver's PRs squash-merged into develop, those whose merged diff's
    patch-id has a Done as its latest verdict."""
    latest = {}
    for patch, recorded_at, verdict, _lineage, _findings in rows:
        if patch not in latest or recorded_at >= latest[patch][0]:
            latest[patch] = (recorded_at, verdict)
    done, unread, none, merges = 0, [], [], []
    for pr in prs:
        # A stacked PR merges into the branch below it, and its squash reaches develop with
        # the stack, so a merge counts when its commit is on develop, whatever its base.
        oid = (pr.get("mergeCommit") or {}).get("oid")
        try:
            if not oid or not on_base(clone, oid, runner):
                continue
            merges.append(pr)
            verdict = latest.get(patch_id(clone, oid, runner), (None, None))[1]
        except RuntimeError:
            unread.append(pr["number"])
            continue
        done += verdict == "done"
        if verdict is None:
            none.append(pr["number"])
    return {"5 Done on merged develop diff": {**ratio(done, len(merges)),
                                    "detail": {"no verdict": none, "commit not in clone": unread}}}


def words(text):
    return len(text.split())


def kit_cost(rev, files, tools):
    """Metric 6 from the kit's files at `rev` ({path: text}) and the window's Claude
    [tool calls, denials]."""
    def body(text):
        return text.split("\n---\n", 1)[1] if text.startswith("---\n") and "\n---\n" in text[4:] else text

    always = sum(words(body(files[p]) if p.endswith("SKILL.md") else files[p]) for p in ALWAYS_LOADED if p in files)
    measured = any(p in files for p in INSTRUCTIONS)
    skills = sum(words(t) for p, t in files.items() if re.fullmatch(r"(?:skills/[^/]+/)?[^/]+/SKILL\.md", p))
    code = sum(t.count("\n") for p, t in files.items()
               if p.endswith((".py", ".sh")) and not Path(p).name.startswith("test_"))
    return {"6 always-loaded words (Claude)": ({"value": always, "num": always, "den": None, "detail": f"kit at {rev[:10]}"}
                                               if measured else {"value": None, "not measured": NO_INSTRUCTIONS}),
            "6 SKILL.md words": {"value": skills, "num": skills, "den": None},
            "6 kit code lines (no tests)": {"value": code, "num": code, "den": None},
            "6 hook denials per 100 tool calls": {**ratio(tools[1], tools[0], per=100),
                                                  "detail": f"{tools[1]} denials in {tools[0]} Claude tool calls"}}


def kit_rev(end, kit, runner=run):
    """The repo holding the kit at `end` and its last origin/main commit before then: the
    addystack checkout once it has one (plan D18), else this workshop, which held the kit
    before the split. kit is the addystack checkout, or None when there isn't one."""
    if kit is not None:
        rev = runner(["git", "-C", str(kit), "rev-list", "-1", f"--before={end}", "origin/main"]).strip()
        if rev:
            return kit, rev
    return KIT, runner(["git", "-C", str(KIT), "rev-list", "-1", f"--before={end}", "origin/main"]).strip()


def kit_files(end, runner=run):
    """The kit's tracked files at the last origin/main commit before `end`."""
    import kit_path
    try:
        kit = kit_path.repo()
    except SystemExit:
        kit = None
    repo, rev = kit_rev(end, kit, runner)
    archive = subprocess.run(["git", "-C", str(repo), "archive", rev], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        return rev, {m.name: tar.extractfile(m).read().decode("utf8", "replace") for m in tar.getmembers() if m.isfile()}


def gather(start, end, hosts, runner=run, home="~"):
    """Every machine's dump for [start, end), as {machine: dump}, and the hosts that failed."""
    found, failed = {LOCAL: dump(start, end, home)}, []
    for host in hosts:
        try:
            found[host] = json.loads(runner(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
                                             "python3", "-I", "-", "dump", start, end],
                                            stdin=Path(__file__).read_text()))
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            failed.append(f"{host}: {error}")
    return found, failed


def score(start, end, machines, github, rev_files, clone, runner=run):
    """One window's metrics. `github` holds the window's PR searches; `rev_files` the kit
    at its end."""
    rows = [row for m in machines.values() for row in m["messages"]]
    stores = {}
    for m in machines.values():
        for repo, verdict_rows in m["verdicts"].items():
            stores.setdefault(repo, []).extend(verdict_rows)
    tools = [sum(counts[kind] for m in machines.values() for hour, counts in m["tools"].items()
                 if start[:13] <= hour < end[:13]) for kind in (0, 1)]
    metrics = {SCOPE: {"value": None, "not measured": NOT_MEASURED[SCOPE]}}
    metrics.update(defects(github["franklin"]))
    metrics.update(corrections(rows, github["merged"], start, end))
    metrics.update(rework(stores, start, end))
    metrics.update(coverage(github["franklin"], stores.get("franklin-next", []), clone, runner))
    metrics.update(kit_cost(rev_files[0], rev_files[1], tools))
    return metrics


def fetch_github(start, end, runner=run):
    """The PR searches one window needs: Oliver's franklin-next merges with their review
    threads, and how many PRs he merged in any repo."""
    merged = f"merged:{start}..{end}"

    def inside(prs):
        return [pr for pr in prs if pr.get("mergedAt") and start <= pr["mergedAt"] < end]

    return {"franklin": inside(search(f"repo:{FRANKLIN} is:pr is:merged author:{LOGIN} {merged}",
                                      f"{PR_FIELDS} {THREADS}", runner)),
            "merged": len(inside(search(f"is:pr is:merged author:{LOGIN} {merged}", "number mergedAt", runner)))}


def cell(metric):
    if metric.get("not measured"):
        return "not measured"
    value, num, den = metric["value"], metric["num"], metric["den"]
    if den is None:
        return f"{value:,}" if isinstance(value, int) else str(value)
    return "n/a (0)" if value is None else f"{value:.2f} ({num:,}/{den:,})"


def table(results):
    names = list(results[0]["metrics"])
    head = "| Metric | " + " | ".join(f"{r['label']}" for r in results) + " |"
    lines = [head, "|---|" + "---|" * len(results)]
    for name in names:
        lines.append(f"| {name} | " + " | ".join(cell(r["metrics"][name]) for r in results) + " |")
    notes = []
    for name in names:
        reasons = {r["label"]: r["metrics"][name]["not measured"] for r in results
                   if r["metrics"][name].get("not measured")}
        if reasons and len(set(reasons.values())) == 1 and len(reasons) == len(results):
            notes.append(f"- **{name}**: not measured: {next(iter(reasons.values()))}.")
        else:
            notes += [f"- **{name}**, {label}: not measured: {why}." for label, why in reasons.items()]
    notes += [f"- **{name}**, {r['label']}: {r['metrics'][name]['detail']}"
              for name in names for r in results if r["metrics"][name].get("detail")]
    notes += [f"- **Unread machine**: {failed}" for failed in results[0]["failed"]]
    return "\n".join(lines + [""] + notes)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["dump"]:
        print(json.dumps(dump(argv[1], argv[2])))
        return 0
    parser = argparse.ArgumentParser(prog="scorecard.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("starts", nargs="+", type=date.fromisoformat, metavar="YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--hosts", nargs="*", default=list(HOSTS))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import kit_path
    sys.path.insert(0, str(kit_path.tool() / "hooks"))
    clone = str(Path(FRANKLIN_CLONE).expanduser())
    run(["git", "-C", clone, "fetch", "--quiet", "origin", FRANKLIN_BASE])
    windows = [window(day, args.days) for day in args.starts]
    machines, failed = gather(min(w[0] for w in windows), max(w[1] for w in windows), args.hosts)
    results = []
    for day, (start, end) in zip(args.starts, windows):
        label = f"{day} +{args.days}d"
        results.append({"label": label, "start": start, "end": end, "failed": failed,
                        "metrics": score(start, end, machines, fetch_github(start, end), kit_files(end), clone)})
    print(json.dumps(results, indent=1) if args.json else table(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
