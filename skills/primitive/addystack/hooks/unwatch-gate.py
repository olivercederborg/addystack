#!/usr/bin/env python3
"""PreToolUse on T3's `unwatch_pull_request`: denies dropping the watch on an open, ready
(non-draft) PR the user wrote, unless the user's latest prompt asks to stop watching. Such
a PR waits on reviewers, and the watch is what wakes the thread when one reviews,
comments, or a check fails. To hand the thread back while it waits, the agent re-watches
with `until: "checks"`, which returns the thread to the user's inbox once checks finish and
keeps waking it on reviews. babysit's old Done step unwatched every PR once checks passed
and threads were handled, reviews or not: on Nov 25, 2026 it dropped the watch on a work
repo's #6226 at hand-back while two review requests were pending, after the user had asked
for the same PR's sibling, #6215, to be watched. Claude transcripts from Oct 17 to
Nov 25, 2026 hold 771 unwatch calls; 283 of them, on 86 PRs in 36 sessions, dropped the
watch on an open, ready PR the user wrote, read against each PR's ready and draft events,
and none followed a prompt of the user's that asked to stop watching.

The PR comes from `url`, or `number` with `repository` (and `host`), and its state, draft
flag, and author from `gh pr view`; the user is `gh api user`. A merged or closed PR, a
draft, or another author's PR passes, as does a T3 delegated child, whose watches are its
own: the thread it reports to keeps the user's. A go is the user's own latest prompt
(user_turn.py) that asks to stop watching or unwatch, typed or as the text of the option
its key picks, with no refusal such as "don't unwatch" or "keep watching". Fails closed:
when a check can't run, such as `gh` failing or a call that names no PR, the unwatch is
denied, which leaves a watch on and costs a wake at most.

`unwatch-gate.py --dry-run '<PR url>' [--transcript PATH] [--session ID]` runs the same
checks and prints each reason or `would pass` (exit 1 or 0)."""
import json, pathlib, re, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

DRY_RUN = sys.argv[1:2] == ["--dry-run"]
if DRY_RUN:
    import user_turn
    payload = user_turn.dry_run_payload(sys.argv[2:], "unwatch-gate.py")
    payload["tool_input"] = {"url": payload["tool_input"]["command"]}
else:
    payload = json.load(sys.stdin)
tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}

# A request to stop watching, and the refusals that read like one.
STOP = re.compile(r"\bun-?watch\b|\bstop (?:watching|babysitting)\b|\b(?:no need to|don'?t|do not) (?:keep )?(?:watch|babysit)", re.I)
REFUSAL = re.compile(r"\b(?:no need to|don'?t|do not|never|without) (?:un-?watch|stop (?:watching|babysitting))|\bkeep (?:watching|the watch|it watched)", re.I)
ASK = 'call `watch_pull_request` with `until: "checks"` instead: the thread then returns to the user\'s inbox once checks finish, and the watch still wakes it on reviews, comments, and failed checks'


def passes(why):
    if DRY_RUN:
        print(f"would pass: {why}")
    sys.exit(0)


def deny(*reasons):
    if DRY_RUN:
        print("".join(f"- {reason}\n" for reason in reasons) + "would deny")
        sys.exit(1)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"Unwatch gate: {'; '.join(reasons)}.",
    }}))
    sys.exit(0)


def gh(*args):
    run = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=20)
    if run.returncode:
        lines = (run.stderr or run.stdout).strip().splitlines()
        raise RuntimeError(lines[-1] if lines else f"gh exited {run.returncode}")
    return run.stdout.strip()


def target():
    """(gh pr view's PR argument and flags, host) for the PR the call names, or None."""
    url, number, repo = tool_input.get("url"), tool_input.get("number"), tool_input.get("repository")
    if isinstance(url, str) and (found := re.match(r"https?://([^/]+)/[^/]+/[^/]+/pull/\d+", url)):
        return [url], found.group(1)
    if isinstance(number, int) and isinstance(repo, str) and repo.count("/") >= 1:
        host = tool_input.get("host") if isinstance(tool_input.get("host"), str) else "github.com"
        return [str(number), "-R", repo if repo.count("/") == 2 else f"{host}/{repo}"], host
    return None


def asks_to_stop(text):
    return isinstance(text, str) and bool(STOP.search(text)) and not REFUSAL.search(text)


def user_go():
    """Whether the user's latest prompt, typed or a key's picked option, asks to stop watching."""
    try:
        import turn_block, user_turn
        found = user_turn.exchanges(payload)
        if not found:
            return False
        prompt = found[-1].prompt
        if asks_to_stop(prompt):
            return True
        if not turn_block.PICK.fullmatch(prompt or ""):
            return False
        option = turn_block.picked(user_turn.answered(found), prompt)
        return option is not None and asks_to_stop(option.text)
    except Exception:
        return False


import t3_child  # noqa: E402

if t3_child.delegated_brief(payload.get("session_id")) is not None:
    passes("a delegated child's watch is its own; the thread it reports to keeps the user's")
pr_ref = target()
if pr_ref is None:
    deny("the call names no PR the gate can check; pass its `url`")
args, host = pr_ref
try:
    pr = json.loads(gh("pr", "view", *args, "--json", "number,url,state,isDraft,author"))
    me = gh("api", "user", "--hostname", host, "--jq", ".login")
except Exception as error:  # noqa: BLE001: any failure leaves the watch on
    deny(f"the gate couldn't read the PR's state ({error}), so the watch stays on")
if pr.get("state") != "OPEN":
    passes(f"#{pr.get('number')} is {str(pr.get('state')).lower()}")
if pr.get("isDraft"):
    passes(f"#{pr['number']} is a draft, which waits on no reviewer")
if (pr.get("author") or {}).get("login") != me:
    passes(f"#{pr['number']} is {(pr.get('author') or {}).get('login')}'s, not {me}'s")
if user_go():
    passes("the user's latest prompt asks to stop watching")
deny(f"#{pr['number']} is open and ready for review, so its watch stays on until it merges or closes",
     f"to hand the thread back while it waits, {ASK}",
     "unwatch it only when the user's latest message asks to stop watching it")
