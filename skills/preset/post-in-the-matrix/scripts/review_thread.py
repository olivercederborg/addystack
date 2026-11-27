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
--project. Prints {"thread": null} when none holds it.

The list shows at most five open PRs per thread, and only an agent can read the rest, with
T3's `list_thread_pull_requests` tool. So when a review thread hides links and a hidden
link could make it the holder, the script exits 3 and prints {"needLinks": [threadId, ...]}.
The caller saves each listed thread's tool result, read with states ["open"], as one JSON
object keyed by thread id, and runs the script again with --links FILE. A saved list stands
in for a thread that still hides links, and must hold every PR its fresh entry shows. A link
swapped for another in the seconds between the two reads can't be seen.

Exits 2, with a message on stderr, when T3 can't be read or the links file leaves out an
open PR of a thread that could hold the PR, so the caller stops instead of guessing.
"""
import argparse, json, re, subprocess, sys

DEFAULT_PREFIXES = ("Review #", "◎ #")
RANK = {"linked": 0, "title": 1, "stack": 2}
PAGE = 100  # the CLI reads the list in pages of this size, newest first
NEEDS_LINKS = 3


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


def best(items, repo, number, prefixes):
    """((kind, watching), thread) for the thread that holds the PR, or None."""
    found = [(held, thread) for thread in items if (held := match(thread, repo, number, prefixes))]
    found.sort(key=lambda pair: str(pair[1].get("updatedAt") or ""), reverse=True)
    found.sort(key=lambda pair: (RANK[pair[0][0]], bool(pair[1].get("settled"))))
    return found[0] if found else None


def ahead(thread, other):
    """Whether this thread can win over the other within one kind: unsettled first, then newest."""
    if bool(thread.get("settled")) != bool(other.get("settled")):
        return not thread.get("settled")
    return str(thread.get("updatedAt") or "") >= str(other.get("updatedAt") or "")  # a tie keeps list order


def hidden_links(items, prefixes):
    """Review threads whose list entry shows fewer open PRs than they link."""
    return [thread for thread in items
            if review_numbers(thread.get("title"), prefixes)
            and (thread.get("openPullRequestCount") or 0) > len(thread.get("pullRequests") or [])]


def could_outrank(thread, found):
    """Whether this thread would hold the PR ahead of `found` if a hidden link were to it."""
    if found is None or found[0][0] != "linked":
        return True  # a hidden link would make it a linked or stack holder
    return thread is not found[1] and ahead(thread, found[1])


def key(pr):
    return (pr.get("repository") or "").lower(), pr.get("number")


def read_links(path):
    """Each thread's full open PR list, from saved `list_thread_pull_requests` results."""
    with open(path) as handle:
        results = json.load(handle)
    if not isinstance(results, dict):
        raise ValueError("--links must hold one object keyed by thread id")
    links = {}
    for thread_id, result in results.items():
        pulls = result.get("pullRequests") if isinstance(result, dict) else None
        if (not isinstance(pulls, list) or result.get("nextCursor")
                or not all(isinstance(pr, dict) and isinstance(pr.get("repository"), str)
                           and isinstance(pr.get("number"), int) and isinstance(pr.get("source"), str)
                           and isinstance(pr.get("watching"), bool)
                           and (pr.get("state") is None or isinstance(pr.get("state"), str)) for pr in pulls)
                or len({key(pr) for pr in pulls}) != len(pulls)):
            raise ValueError(f"--links for {thread_id} is not one thread's full list_thread_pull_requests "
                             "result, every page combined")
        links[thread_id] = pulls
    return links


def with_links(thread, pulls):
    """The thread with its saved full list, which must hold every PR the fresh list shows."""
    if missing := {key(pr) for pr in thread.get("pullRequests") or []} - {key(pr) for pr in pulls}:
        raise ValueError(f"--links for {thread.get('threadId')} misses #{', #'.join(str(n) for _, n in sorted(missing))}, "
                         "which the thread links now; read its list again")
    return {**thread, "pullRequests": pulls}


class NeedsLinks(Exception):
    def __init__(self, thread_ids):
        super().__init__()
        self.thread_ids = thread_ids


def lookup(repo, number, prefixes, project=None, list_json=None, links_json=None):
    items = read_list(project, list_json)
    if len(items) >= PAGE and not list_json:
        # The CLI reads pages newest first, so a thread that turned active mid-read can fall
        # between two pages. A second read catches it unless it moves again during that read;
        # the second read's entries replace the first's.
        items = list({thread.get("threadId"): thread for thread in items + read_list(project, None)}.values())
    if links_json:
        links = read_links(links_json)
        hiding = {thread.get("threadId") for thread in hidden_links(items, prefixes)}
        items = [with_links(thread, links[thread.get("threadId")])
                 if thread.get("threadId") in links and thread.get("threadId") in hiding else thread
                 for thread in items]
    found = best(items, repo, number, prefixes)
    if needed := [thread.get("threadId") for thread in hidden_links(items, prefixes) if could_outrank(thread, found)]:
        if links_json:
            raise ValueError(f"--links doesn't hold every open PR of review threads {', '.join(map(str, needed))}")
        raise NeedsLinks(needed)
    if found is None:
        return None
    (kind, watching), thread = found
    return {"threadId": thread.get("threadId"), "title": thread.get("title"), "match": kind,
            "watching": watching, "settled": bool(thread.get("settled")), "status": thread.get("status"),
            "link": thread.get("link")}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print the T3 review thread that holds a PR.")
    parser.add_argument("repo", help="owner/repo, such as octo/app")
    parser.add_argument("number", type=int)
    parser.add_argument("--project", help="T3 project id or a path inside it; default: this directory")
    parser.add_argument("--title-prefix", action="append", default=[], dest="prefixes",
                        help=f"another review thread title prefix, repeatable; always also: {', '.join(DEFAULT_PREFIXES)}")
    parser.add_argument("--links", dest="links_json",
                        help="saved list_thread_pull_requests results keyed by thread id, after exit 3")
    parser.add_argument("--list-json", help=argparse.SUPPRESS)  # a saved `t3 thread list --json`, for tests
    args = parser.parse_args(argv)
    repo = args.repo.lower()
    prefixes = tuple(dict.fromkeys([*DEFAULT_PREFIXES, *args.prefixes]))
    try:
        thread = lookup(repo, args.number, prefixes, args.project, args.list_json, args.links_json)
    except NeedsLinks as needed:
        print(json.dumps({"pr": f"{repo}#{args.number}", "needLinks": needed.thread_ids}))
        return NEEDS_LINKS
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"review_thread: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"pr": f"{repo}#{args.number}", "thread": thread}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
