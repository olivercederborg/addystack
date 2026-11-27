"""Fetches the GitHub timeline events replay.py reads (merged, closed, reopened, ready,
draft, reviews) for every PR in OUT/pr_mentions.json, into OUT/timelines.json.
usage: timelines.py OUT"""
import concurrent.futures, json, subprocess, sys
from pathlib import Path

KEEP = {"merged", "closed", "reopened", "ready_for_review", "convert_to_draft", "reviewed", "review_dismissed"}


def fetch(pr):
    repo, n = pr
    done = subprocess.run(["gh", "api", "--paginate", f"repos/{repo}/issues/{n}/timeline", "--jq",
                           ".[] | {e: .event, t: (.created_at // .submitted_at), s: .state}"], capture_output=True, text=True)
    if done.returncode:
        return [repo, n, None]
    events = [json.loads(line) for line in done.stdout.splitlines() if line.strip()]
    return [repo, n, [e for e in events if e["e"] in KEEP]]


out = Path(sys.argv[1])
prs = sorted({(r, n) for _, r, n, _ in json.load(open(out / "pr_mentions.json"))})
with concurrent.futures.ThreadPoolExecutor(8) as pool:
    got = list(pool.map(fetch, prs))
json.dump(got, open(out / "timelines.json", "w"))
print(f"{len(got)} PRs, {sum(1 for g in got if g[2] is None)} unread")
