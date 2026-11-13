#!/usr/bin/env python3
"""Print the T3 thread that holds a PR's review, as one JSON line.

    review_thread.py <owner/repo> <number> [--project PATH] [--title-prefix TEXT ...]

Asks T3 each time (`t3 thread list --json`, every top-level thread of the project in
one call), so nothing is cached. A thread holds the PR when, in this order:

1. "linked": it links the PR itself (any source but a stack neighbour or a dismissed one);
2. "title": its title starts with a review prefix and the PR number, so #57 isn't #5739;
3. "stack": it links the PR as a stack neighbour of the PR it reviews.

Within a kind, an unsettled thread beats a settled one, then the newest. Subagent
threads never count. Prints {"thread": null} when none holds it, and exits 2 with a
message on stderr when T3 can't be read, so the caller stops instead of guessing.
"""
import argparse, json, re, subprocess, sys

DEFAULT_PREFIXES = ("Review #", "◎ #")
RANK = {"linked": 0, "title": 1, "stack": 2}


def threads(project, list_json):
    if list_json:
        with open(list_json) as handle:
            return json.load(handle)
    command = ["t3", "thread", "list", "--json"] + (["--project", project] if project else [])
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"t3 thread list failed: {result.stderr.strip()[:300]}")
    return json.loads(result.stdout)


def match(thread, repo, number, prefixes):
    """How thread holds the PR, or None."""
    sources = {(pr.get("source") or "") for pr in thread.get("pullRequests") or []
               if (pr.get("repository") or "").lower() == repo and pr.get("number") == number}
    if sources - {"stack", "stack-dismissed"}:
        return "linked"
    title = thread.get("title") or ""
    if any(re.match(re.escape(prefix) + str(number) + r"(?!\d)", title) for prefix in prefixes):
        return "title"
    return "stack" if "stack" in sources else None


def holder(items, repo, number, prefixes):
    found = []
    for thread in items:
        if thread.get("parentThreadId") or thread.get("relationshipToParent"):
            continue
        kind = match(thread, repo, number, prefixes)
        if kind:
            found.append((kind, thread))
    found.sort(key=lambda pair: str(pair[1].get("updatedAt") or ""), reverse=True)
    found.sort(key=lambda pair: (RANK[pair[0]], bool(pair[1].get("settled"))))
    if not found:
        return None
    kind, thread = found[0]
    return {"threadId": thread.get("threadId"), "title": thread.get("title"), "match": kind,
            "settled": bool(thread.get("settled")), "status": thread.get("status"),
            "link": thread.get("link")}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print the T3 thread that holds a PR's review.")
    parser.add_argument("repo", help="owner/repo, such as hifranklin-tech/franklin-next")
    parser.add_argument("number", type=int)
    parser.add_argument("--project", help="T3 project id or a path inside it; default: this directory")
    parser.add_argument("--title-prefix", action="append", dest="prefixes",
                        help=f"review thread title prefix, repeatable; default: {', '.join(DEFAULT_PREFIXES)}")
    parser.add_argument("--list-json", help=argparse.SUPPRESS)  # a saved `t3 thread list --json`, for tests
    args = parser.parse_args(argv)
    repo = args.repo.lower()
    try:
        items = threads(args.project, args.list_json)
        if not isinstance(items, list):
            raise ValueError("t3 thread list did not return a list")
        thread = holder(items, repo, args.number, tuple(args.prefixes or DEFAULT_PREFIXES))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"review_thread: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"pr": f"{repo}#{args.number}", "thread": thread}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
