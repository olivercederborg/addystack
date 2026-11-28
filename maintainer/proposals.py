#!/usr/bin/env python3
"""The weekly audit's proposal contract (suite-audit R26 step 2): a change to Oliver's
workflow reaches him only when it names the metric it moves, at least 2 cited cases,
what it deletes or replaces, its rung, and its check. At most 3 a week.

  proposals.py check FILE [--calibration FILE]

FILE is a JSON list of proposals:

  {"title": "...", "metric": "3 corrections per merged PR",
   "cases": ["<cited occurrence>", "<another>"], "replaces": "...",
   "rung": "lint", "check": "..."}

- metric: one of the scorecard's metrics, by its number 1-6. Metric 1 counts only once
  the scope judge is calibrated: pass its calibration file as --calibration.
- cases: at least 2 different occurrences, each citing a URL, a T3 thread link, a
  path:line, a PR number (#12, two digits or more), or a commit SHA.
- replaces: the text, hook, or step the change deletes or replaces; "none" doesn't count.
- rung: architecture, type, lint, hook, test, or prose (encode-lessons-in-structure).
- check: how next week's scorecard or an eval shows it worked.

It prints {"passed": [...], "refused": [{"title", "reasons"}]} and exits 1 when it
refused any."""
from __future__ import annotations

import json, re, sys
from pathlib import Path

CAP = 3
RUNGS = ("architecture", "type", "lint", "hook", "test", "prose")
METRIC = re.compile(r"^\s*[1-6]\b")
# A SHA has a letter and a digit, so a date such as 20261030 isn't one.
CITATION = re.compile(r"https?://\S+|t3-thread://\S+|[\w./~-]+\.\w+:\d+|(?<!&)#\d{2,}\b"
                      r"|\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")
EMPTY = {"", "none", "nothing", "n/a", "na", "-"}


def filled(value):
    return isinstance(value, str) and value.strip().lower().rstrip(".") not in EMPTY


def reasons(proposal, scope_calibrated=False):
    """What the proposal lacks, empty when it meets the contract."""
    missing = []
    if not filled(proposal.get("title")):
        missing.append("no title")
    metric = proposal.get("metric") if isinstance(proposal.get("metric"), str) else ""
    if not METRIC.match(metric):
        missing.append("no metric: name one of the scorecard's metrics 1-6")
    elif metric.strip().startswith("1") and not scope_calibrated:
        missing.append("metric 1 is uncalibrated: the scope judge hasn't met its 8-of-10 bar")
    cases = proposal.get("cases") if isinstance(proposal.get("cases"), list) else []
    cited = {c.strip() for c in cases if isinstance(c, str) and CITATION.search(c)}
    if len(cited) < 2:
        missing.append(f"{len(cited)} cited cases: needs 2, each with a URL, thread link, path:line, #PR, or SHA")
    if not filled(proposal.get("replaces")):
        missing.append("doesn't say what it deletes or replaces")
    if str(proposal.get("rung", "")).strip().lower() not in RUNGS:
        missing.append(f"no rung: one of {', '.join(RUNGS)}")
    if not filled(proposal.get("check")):
        missing.append("no check")
    return missing


def check(proposals, scope_calibrated=False):
    passed, refused = [], []
    for proposal in proposals:
        found = reasons(proposal, scope_calibrated) if isinstance(proposal, dict) else ["not a JSON object"]
        if not found and len(passed) == CAP:
            found = [f"over the weekly cap of {CAP}"]
        if found:
            refused.append({"title": proposal.get("title", "") if isinstance(proposal, dict) else "",
                            "reasons": found})
        else:
            passed.append(proposal)
    return {"passed": passed, "refused": refused}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in (2, 4) or argv[0] != "check" or (len(argv) == 4 and argv[2] != "--calibration"):
        print(__doc__, file=sys.stderr)
        return 2
    scope_calibrated = False
    if len(argv) == 4:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import scope_judge
        scope_calibrated = scope_judge.calibrated(argv[3])[0] == "calibrated"
    proposals = json.loads(Path(argv[1]).read_text())
    if not isinstance(proposals, list):
        print("proposals.py: FILE must hold a JSON list", file=sys.stderr)
        return 2
    result = check(proposals, scope_calibrated)
    print(json.dumps(result, indent=1))
    return 1 if result["refused"] else 0


if __name__ == "__main__":
    sys.exit(main())
