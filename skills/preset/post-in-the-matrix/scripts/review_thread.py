#!/usr/bin/env python3
"""Print the T3 review thread that holds a PR, as one JSON line.

    review_thread.py <owner/repo> <number> [--project PATH] [--title-prefix TEXT ...]

Asks T3 each time (`t3 thread list --json`: every active top-level thread of the project,
with its open linked PRs), so nothing is cached. An archived review thread counts as none. Only review threads count: a thread whose
title starts with a review prefix ("Review #", "◎ #", plus any --title-prefix) and one or
more PR numbers ("◎ #5815+#5816", "◎ #3848 #5823"). One of them holds the PR when, in this
order:

1. "linked": it links the PR itself (not as a stack neighbour or a dismissed one);
2. "title": its title names the PR's number, and it links no other repo's PR by that number;
3. "stack": it links the PR as a stack neighbour of the PR it reviews.

Within a kind, an unsettled thread beats a settled one, then the newest. Subagent threads
never count. Run it from the PR's project checkout (or a T3 worktree of it), or pass
--project. Prints {"thread": null} when none holds it. Exits 2, with a message on stderr,
when T3 can't be read or a "none" answer can't be trusted, so the caller stops instead of
guessing.
"""
import argparse, json, re, subprocess, sys

DEFAULT_PREFIXES = ("Review #", "◎ #")
RANK = {"linked": 0, "title": 1, "stack": 2}
PAGE = 100  # the CLI reads the list in pages of this size, newest first


def read_list(project, list_json):
    if list_json:
        with open(list_json) as handle:
            items = json.load(handle)
    else:
        command = ["t3", "thread", "list", "--json"] + (["--project", project] if project else [])
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"t3 thread list failed: {result.stderr.strip()[:300]}")
        items = json.loads(result.stdout)
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError("t3 thread list did not return a list of threads")
    return items


def review_numbers(title, prefixes):
    """The PR numbers a review thread's title names; empty for any other thread."""
    for prefix in prefixes:
        found = re.match(re.escape(prefix) + r"(\d+(?:[ +,]+#\d+)*)(?![\w])", title or "")
        if found:
            return {int(number) for number in re.findall(r"\d+", found.group(1))}
    return set()


def links(thread, number):
    """(repository, source, watching) of each open link to a PR with this number."""
    return [((pr.get("repository") or "").lower(), pr.get("source") or "", bool(pr.get("watching")))
            for pr in thread.get("pullRequests") or [] if isinstance(pr, dict) and pr.get("number") == number]


def match(thread, repo, number, prefixes):
    """(kind, watching) when this review thread holds the PR, else None."""
    named = review_numbers(thread.get("title"), prefixes)
    if thread.get("relationshipToParent") == "subagent" or not named:
        return None
    own = links(thread, number)
    direct = [watching for linked_repo, source, watching in own
              if linked_repo == repo and source not in ("stack", "stack-dismissed")]
    if direct:
        return "linked", any(direct)
    other_repo = any(linked_repo != repo and source != "stack-dismissed" for linked_repo, source, _ in own)
    if number in named and not other_repo:
        return "title", False
    stacked = [watching for linked_repo, source, watching in own if linked_repo == repo and source == "stack"]
    return ("stack", any(stacked)) if stacked else None


def holder(items, repo, number, prefixes):
    found = []
    for thread in items:
        held = match(thread, repo, number, prefixes)
        if held:
            found.append((held, thread))
    found.sort(key=lambda pair: str(pair[1].get("updatedAt") or ""), reverse=True)
    found.sort(key=lambda pair: (RANK[pair[0][0]], bool(pair[1].get("settled"))))
    if not found:
        return None
    (kind, watching), thread = found[0]
    return {"threadId": thread.get("threadId"), "title": thread.get("title"), "match": kind,
            "watching": watching, "settled": bool(thread.get("settled")), "status": thread.get("status"),
            "link": thread.get("link")}


def hidden_links(items, prefixes):
    """Review threads whose list entry shows fewer open PRs than they link."""
    return [thread.get("threadId") for thread in items
            if review_numbers(thread.get("title"), prefixes)
            and (thread.get("openPullRequestCount") or 0) > len(thread.get("pullRequests") or [])]


def lookup(repo, number, prefixes, project=None, list_json=None):
    items = read_list(project, list_json)
    if len(items) >= PAGE and not list_json:
        # The CLI reads pages newest first, so a thread that turned active mid-read can fall
        # between two pages. A second read catches it; its entries replace the first's.
        items = list({thread.get("threadId"): thread for thread in items + read_list(project, None)}.values())
    thread = holder(items, repo, number, prefixes)
    if thread is None and (hidden := hidden_links(items, prefixes)):
        raise ValueError(f"can't rule out a holder: review threads {', '.join(map(str, hidden[:3]))} "
                         "link more open PRs than the list shows")
    return thread


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print the T3 review thread that holds a PR.")
    parser.add_argument("repo", help="owner/repo, such as octo/app")
    parser.add_argument("number", type=int)
    parser.add_argument("--project", help="T3 project id or a path inside it; default: this directory")
    parser.add_argument("--title-prefix", action="append", default=[], dest="prefixes",
                        help=f"another review thread title prefix, repeatable; always also: {', '.join(DEFAULT_PREFIXES)}")
    parser.add_argument("--list-json", help=argparse.SUPPRESS)  # a saved `t3 thread list --json`, for tests
    args = parser.parse_args(argv)
    repo = args.repo.lower()
    prefixes = tuple(dict.fromkeys([*DEFAULT_PREFIXES, *args.prefixes]))
    try:
        thread = lookup(repo, args.number, prefixes, args.project, args.list_json)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"review_thread: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"pr": f"{repo}#{args.number}", "thread": thread}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
