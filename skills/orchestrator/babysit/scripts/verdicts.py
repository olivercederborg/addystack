#!/usr/bin/env python3
# Copy of skills/primitive/addystack/hooks/verdicts.py, written by scripts/sync-copies.py: edit the source, then run the script.
"""verify-work's verdicts (done, not-done, not-verified), in
`<git-common-dir>/verify-work/verdicts.tsv` so every worktree sees them. Only a fresh
`work-verifier` records one (pstack: no owner merges on its own verdict); merge-gate.py
reads them.

Row, tab-separated: patch-id head base time v3 session-id agent-id work-verifier, then
`{"verdict", "evidence": {kind: [ref, ...]}, "findings": [text, ...], "required": {kind:
[reason, ...]}, "branch"}` as compact JSON; rows recorded before `required` lack it, and
a row recorded before `branch`, or at a detached HEAD without `--branch`, has none.
Evidence kinds and what backs Done are evidence.py's: a Done is refused while a kind the
change's type or `--require` asks for has no ref that backs it, and a ref that proves
nothing is refused for every verdict. A verdict matches on `git patch-id --verbatim` alone: a clean
rebase keeps it, and a re-indent doesn't. The latest row for a patch-id decides, so a
later Not done revokes a Done. A `v2` row (8 columns, no JSON) is a Done; readers before
v3 take only those, so they never read a Not done as Done. Rows without `v2` or `v3`
predate verifiers and don't count. `last` finds a branch's newest verdict for
verify-work's quick re-check, and `known` says when that re-check can't change it; the
gate never reads the branch.

The store also keeps review-loop's results, which ready-gate.py reads: a v3 row whose
8th column is `review-loop`, with the recording session's ID (or `-`), `-` for the
agent, and `{"rounds": N}` or `{"skipped": reason}`. Verdict readers skip them, since
they read only `work-verifier` rows. A result matches on patch-id, as a verdict does."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, astuple, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

VERIFIER = "work-verifier"
REVIEWER = "review-loop"
HOOK_CONTEXT = "VERIFY_WORK_HOOK_CONTEXT"  # verdict-stamp.py puts the identity here, as JSON
VERDICTS = ("done", "not-done", "not-verified")


@dataclass(frozen=True)
class ReviewTarget:
    base: str  # commit SHAs
    head: str


@dataclass(frozen=True)
class VerifierIdentity:
    session_id: str
    agent_id: str
    agent_type: str


@dataclass(frozen=True)
class Receipt:
    patch_id: str
    reviewed: ReviewTarget
    recorded_at: str  # UTC ISO 8601
    verifier: VerifierIdentity
    verdict: str  # one of VERDICTS
    evidence: dict[str, list[str]] = field(default_factory=dict)  # kind -> refs
    findings: list[str] = field(default_factory=list)
    required: dict[str, list[str]] = field(default_factory=dict)  # kind -> reasons


@dataclass(frozen=True)
class Review:
    patch_id: str
    reviewed: ReviewTarget
    recorded_at: str  # UTC ISO 8601
    rounds: int  # 0 for a skip
    skipped: str  # the skip's reason, or ""


class VerdictError(Exception):
    pass


def _git(cwd: Path, *args: str, stdin: str | None = None) -> str:
    # Bytes in and out: text mode would turn \r\n into \n and hide a line-ending change.
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                            input=None if stdin is None else stdin.encode(errors="surrogateescape"))
    if result.returncode:
        raise VerdictError(f"`git {' '.join(args[:2])}` failed: {result.stderr.decode(errors='replace').strip()[:200]}")
    return result.stdout.decode(errors="surrogateescape")


def _patch_id(cwd: Path, diff: str) -> str:
    return _git(cwd, "patch-id", "--verbatim", stdin=diff).split(" ")[0]


def _store(cwd: Path) -> Path:
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(common) / "verify-work" / "verdicts.tsv"


def diff(cwd: Path, base: str, head: str) -> str:
    """`git diff base...head` as verdicts key it: raw (no color, external diff, or text
    conversion), with full blob ids so a binary change hashes the same in every clone."""
    return _git(cwd, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "--full-index", f"{base}...{head}")


def classify(cwd: Path, base: str, head: str) -> dict[str, list[str]]:
    """evidence.classify, its errors as VerdictError."""
    import evidence  # here, so a broken evidence.py breaks only recording and classifying

    try:
        return evidence.classify(cwd, base, head)
    except evidence.EvidenceError as error:
        raise VerdictError(str(error))


def _shown(reasons: list[str], limit: int = 3) -> str:
    return "; ".join(reasons[:limit]) + (f"; and {len(reasons) - limit} more" if len(reasons) > limit else "")


def record(cwd: Path, target: ReviewTarget, hook_context: str | None, verdict: str = "done",
           evidence: dict[str, list[str]] | None = None, findings: list[str] | None = None,
           require: list[str] | None = None, branch: str = "") -> Receipt:
    """Records a verdict for `git diff base...head`. HEAD must be `head`, with nothing
    uncommitted. A Not done or Not verified verdict names at least one finding. A Done
    needs evidence that backs each kind `classify` finds or `require` names. `branch`
    names the reviewed branch at a detached HEAD; HEAD's own branch must match it."""
    import evidence as kinds  # here, so a broken evidence.py can't break find_done or status

    try:
        verifier = VerifierIdentity(**json.loads(hook_context or ""))
    except (ValueError, TypeError):
        verifier = None
    if not verifier or verifier.agent_type != VERIFIER or not verifier.agent_id or not verifier.session_id:
        raise VerdictError(f"only a fresh {VERIFIER} records verdicts: run /verify-work, which forks one")
    evidence, findings = {kind: list(refs) for kind, refs in (evidence or {}).items()}, list(findings or [])
    if verdict not in VERDICTS:
        raise VerdictError(f"verdict {verdict!r} isn't one of {', '.join(VERDICTS)}")
    if verdict != "done" and not findings:
        raise VerdictError(f"a {verdict} verdict names at least one finding")
    if not all(text.strip() for text in [*findings, *(ref for refs in evidence.values() for ref in refs)]):
        raise VerdictError("an empty finding or evidence ref")
    problems = []
    for kind in [*evidence, *(kind for kind in require or [] if kind not in evidence)]:
        evidence[kind], found = kinds.check(kind, evidence.get(kind, []), cwd)
        problems += found
    if problems:
        raise VerdictError("; ".join(problems))
    evidence = {kind: refs for kind, refs in evidence.items() if refs}
    if _git(cwd, "status", "--porcelain", "--untracked-files=no"):
        raise VerdictError("uncommitted changes: verify the committed head")
    base, head = (_git(cwd, "rev-parse", "--verify", f"{ref}^{{commit}}").strip() for ref in (target.base, target.head))
    if _git(cwd, "rev-parse", "HEAD").strip() != head:
        raise VerdictError(f"HEAD isn't the reviewed head {head[:12]}")
    patch_id = _patch_id(cwd, diff(cwd, base, head))
    if not patch_id:
        raise VerdictError(f"{head[:12]} makes no change against {base[:12]}")
    required = classify(cwd, base, head)
    for kind in require or []:
        required.setdefault(kind, []).append("--require: the intent implies it")
    required = {kind: required[kind] for kind in kinds.KINDS if kind in required}
    gaps = [(kind, gap) for kind in required if (gap := kinds.done_gap(kind, evidence.get(kind, [])))]
    if "mutants" not in required and (survived := kinds.survivors(evidence.get("mutants", []))):
        gaps.append(("mutants", survived))  # a survivor the verifier found refuses Done on any path
    if verdict == "done" and gaps:
        raise VerdictError("Done needs evidence: " + "; ".join(
            f"{kind} ({_shown(required.get(kind, ['supplied']))}){'' if gap == 'no evidence' else f': {gap}'}"
            f" → --evidence {kind}={kinds.PLACEHOLDER[kind]}" for kind, gap in gaps))
    receipt = Receipt(patch_id, ReviewTarget(base, head), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      verifier, verdict, evidence, findings, required)
    store = _store(cwd)
    store.parent.mkdir(parents=True, exist_ok=True)
    # Compact JSON escapes tabs and newlines, so the row stays one line of 9 columns.
    body = {"verdict": verdict, "evidence": evidence, "findings": findings, "required": required}
    # HEAD is the reviewed head, so its branch is the one reviewed. The full ref, since
    # `--short` says heads/<name> when a tag shares the name.
    ref = subprocess.run(["git", "symbolic-ref", "--quiet", "HEAD"], cwd=cwd, capture_output=True,
                         text=True).stdout.strip()
    checked_out = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ""
    if branch and checked_out and branch != checked_out:
        raise VerdictError(f"--branch {branch} isn't the checked-out branch {checked_out}")
    branch = checked_out or branch
    body = json.dumps({**body, "branch": branch} if branch else body, separators=(",", ":"))
    with store.open("a") as f:
        f.write("\t".join([patch_id, head, base, receipt.recorded_at, "v3",
                           verifier.session_id, verifier.agent_id, VERIFIER, body]) + "\n")
    return receipt


def record_review(cwd: Path, target: ReviewTarget, rounds: int = 0, skipped: str = "") -> Review:
    """Records review-loop's result for `git diff base...head`: the rounds it ran, or a
    skip with its reason. Unlike a verdict, any session records one, from any checkout."""
    if (rounds > 0) == bool(skipped.strip()):
        raise VerdictError("give the rounds review-loop ran (1 or more), or a skip's reason")
    base, head = (_git(cwd, "rev-parse", "--verify", f"{ref}^{{commit}}").strip() for ref in (target.base, target.head))
    patch_id = _patch_id(cwd, diff(cwd, base, head))
    if not patch_id:
        raise VerdictError(f"{head[:12]} makes no change against {base[:12]}")
    review = Review(patch_id, ReviewTarget(base, head), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    rounds, skipped.strip())
    session = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CODEX_THREAD_ID") or "-"
    body = json.dumps({"skipped": review.skipped} if review.skipped else {"rounds": rounds}, separators=(",", ":"))
    store = _store(cwd)
    store.parent.mkdir(parents=True, exist_ok=True)
    with store.open("a") as f:
        f.write("\t".join([patch_id, head, base, review.recorded_at, "v3", session, "-", REVIEWER, body]) + "\n")
    return review


def find_review(cwd: Path, pr_diff: str) -> Review | None:
    """review-loop's latest result for a PR's `diff`, or None. Raises VerdictError when it
    can't read the store or the row, so the gate fails closed."""
    patch_id, store = _patch_id(cwd, pr_diff), _store(cwd)
    if not patch_id or not store.exists():
        return None
    try:
        rows = [line.split("\t") for line in store.read_text().splitlines()]
    except (OSError, UnicodeDecodeError) as error:
        raise VerdictError(f"can't read {store}: {error}")
    for row in reversed(rows):
        if row[0] != patch_id or len(row) < 8 or row[7] != REVIEWER:
            continue
        try:  # the latest result decides: one that won't read denies, never an older one
            if len(row) != 9 or row[4] != "v3":
                raise ValueError(f"{len(row)} columns, version {row[4]!r}")
            body = json.loads(row[8])
            rounds, skipped = body.get("rounds", 0), body.get("skipped", "")
            if not (isinstance(rounds, int) and isinstance(skipped, str) and (rounds > 0) != bool(skipped)):
                raise ValueError("unexpected shape")
        except (ValueError, AttributeError) as error:
            raise VerdictError(f"can't read the review result recorded at {row[3]} for this diff: {error}")
        return Review(row[0], ReviewTarget(row[2], row[1]), row[3], rounds, skipped)
    return None


def find_done(cwd: Path, pr_diff: str) -> Receipt | None:
    """The Done verdict for a PR's `diff`, or None when its latest verdict isn't Done.
    Raises VerdictError when it can't read, so the gate fails closed."""
    receipt = _latest(cwd, _patch_id(cwd, pr_diff))
    return receipt if receipt and receipt.verdict == "done" else None


def _latest(cwd: Path, patch_id: str) -> Receipt | None:
    store = _store(cwd)
    if not patch_id or not store.exists():
        return None
    try:
        rows = [line.split("\t") for line in store.read_text().splitlines()]
    except OSError as error:
        raise VerdictError(f"can't read {store}: {error}")
    for row in reversed(rows):
        if row[0] != patch_id or len(row) < 8 or row[7] != VERIFIER:
            continue
        reviewed, verifier = ReviewTarget(row[2], row[1]), VerifierIdentity(row[5], row[6], row[7])
        if len(row) == 8 and row[4] == "v2":
            return Receipt(row[0], reviewed, row[3], verifier, "done")
        if row[4] == "v3":
            return Receipt(row[0], reviewed, row[3], verifier, **_body(row))
    return None


def _body(row: list[str]) -> dict:
    """A v3 row's verdict, evidence, findings, and required kinds (empty before they were
    recorded); VerdictError for one that won't read."""
    try:
        if len(row) != 9:
            raise ValueError(f"{len(row)} columns")
        body = json.loads(row[8])
        verdict, evidence, findings = body["verdict"], body["evidence"], body["findings"]
        required = body.get("required", {})
        if not (verdict in VERDICTS and isinstance(evidence, dict) and isinstance(required, dict) and all(
                isinstance(texts, list) and all(isinstance(text, str) for text in texts)
                for texts in [findings, *evidence.values(), *required.values()])):
            raise ValueError("unexpected shape")
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise VerdictError(f"can't read the verdict recorded at {row[3]} for this diff: {error}")
    return {"verdict": verdict, "evidence": evidence, "findings": findings, "required": required}


def last(cwd: Path, branch: str) -> Receipt | None:
    """The newest v3 verdict recorded on `branch`, or None when there's none or the store
    can't be read, so a caller falls back to a full pass. A row that won't read is skipped."""
    try:
        rows = [line.split("\t") for line in _store(cwd).read_text().splitlines()]
    except (OSError, UnicodeDecodeError, VerdictError):
        return None
    for row in reversed(rows):
        if not branch or len(row) != 9 or row[4] != "v3" or row[7] != VERIFIER:
            continue
        try:
            if json.loads(row[8]).get("branch") != branch:
                continue
            return Receipt(row[0], ReviewTarget(row[2], row[1]), row[3], VerifierIdentity(row[5], row[6], row[7]),
                           **_body(row))
        except (ValueError, AttributeError, VerdictError):
            continue
    return None


def known(cwd: Path, receipt: Receipt, base: str, head: str) -> str:
    """Why a re-check of `base...head` after `receipt` can only repeat it, or "" when it
    can find something new: a Not verified waits on the real run it names, and a Not
    done waits on a commit for each finding it marked fix while the diff and its merge
    base are the ones it checked, since a restack onto a parent can bring the fix in. A
    diff that won't read gives "", so the re-check runs."""
    if receipt.verdict == "not-verified":
        return "not verified until it runs: " + "; ".join(receipt.findings)
    fixes = [text for text in receipt.findings if re.search(r"→ fix\b", text)]
    if receipt.verdict != "not-done" or not fixes:
        return ""
    try:
        same = (_patch_id(cwd, diff(cwd, base, head)) == receipt.patch_id
                and _git(cwd, "merge-base", base, head) == _git(cwd, "merge-base", *astuple(receipt.reviewed)))
    except VerdictError:
        return ""
    return f"same diff as {receipt.reviewed.head[:12]}, so still open: " + "; ".join(fixes) if same else ""


def status(cwd: Path, base: str, head: str) -> str:
    """The patch-id of `diff(base, head)` and whether a Done verdict covers it, as the gate
    reads it, then an `idiom:` line per pattern its idiom refs ground, for the ship-gate card."""
    patch_id = _patch_id(cwd, diff(cwd, base, head))
    receipt = _latest(cwd, patch_id)
    done = receipt if receipt and receipt.verdict == "done" else None
    lines = [f"patch-id: {patch_id or 'none (no change)'}",
             f"done: yes ({done.recorded_at}, head {done.reviewed.head[:12]}, {done.verifier.agent_id})"
             if done else "done: no"]
    # A not-run: ref grounds nothing. A ref is a path read now, as for every kind.
    for ref in [ref for ref in done.evidence.get("idiom", []) if not ref.startswith("not-run:")] if done else []:
        try:
            lines += [f"idiom: {line.strip()}" for line in Path(ref).read_text(errors="replace").splitlines()
                      if line.strip()]
        except OSError:
            lines.append(f"idiom: missing: {ref}")
    return "\n".join(lines)


def _evidence(text: str) -> tuple[str, str]:
    kind, equals, ref = text.partition("=")
    if not equals or not ref:
        raise argparse.ArgumentTypeError(f"{text!r} isn't KIND=REF")
    return kind, ref


def main(argv: list[str]) -> int:
    """`record <base-sha> <reviewed-head> [--verdict V] [--evidence KIND=REF]... [--require
    KIND]... [--finding TEXT]... [--branch B]` prints the receipt as JSON; `status <base> <head>` prints
    the patch-id, whether it's done, and a Done's idiom sources; `classify <base> <head>` prints each kind of
    evidence the diff needs, one `kind: reason; reason` line each, or `none`; `last
    <branch> [<base> <head>]` prints the branch's newest verdict as JSON, or `last: none`;
    given the diff to re-check, the JSON adds `known`, `known(...)`'s reason, when it isn't
    empty; `review <base> <head> (--rounds N | --skip REASON)` records review-loop's result
    and prints it as JSON. Exits 2 on a usage error and 1 on a VerdictError."""
    parser = argparse.ArgumentParser(prog="verdicts.py", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    recording = commands.add_parser("record", allow_abbrev=False)
    recording.add_argument("base", metavar="base-sha")
    recording.add_argument("head", metavar="reviewed-head")
    recording.add_argument("--verdict", choices=VERDICTS, default="done")
    recording.add_argument("--evidence", type=_evidence, action="append", default=[], metavar="KIND=REF")
    recording.add_argument("--require", action="append", default=[], metavar="KIND")
    recording.add_argument("--finding", action="append", default=[], metavar="TEXT")
    recording.add_argument("--branch", default="", metavar="B")
    for name in ("status", "classify"):
        checking = commands.add_parser(name)
        checking.add_argument("base")
        checking.add_argument("head")
    reviewing = commands.add_parser("review", allow_abbrev=False)
    reviewing.add_argument("base")
    reviewing.add_argument("head")
    result = reviewing.add_mutually_exclusive_group(required=True)
    result.add_argument("--rounds", type=int, metavar="N")
    result.add_argument("--skip", metavar="REASON")
    latest = commands.add_parser("last")
    latest.add_argument("branch")
    latest.add_argument("diff", nargs="*", metavar="base head")
    args = parser.parse_args(argv)
    if args.command == "last":
        if len(args.diff) not in (0, 2):
            latest.error("give both <base> and <head>, or neither")
        receipt = last(Path.cwd(), args.branch)
        reason = receipt and args.diff and known(Path.cwd(), receipt, *args.diff)
        print(json.dumps({**asdict(receipt), **({"known": reason} if reason else {})}) if receipt else "last: none")
        return 0
    try:
        if args.command == "status":
            print(status(Path.cwd(), args.base, args.head))
            return 0
        if args.command == "review":
            review = record_review(Path.cwd(), ReviewTarget(args.base, args.head), args.rounds or 0, args.skip or "")
            print(json.dumps(asdict(review)))
            return 0
        if args.command == "classify":
            needed = classify(Path.cwd(), args.base, args.head)
            print("\n".join(f"{kind}: {'; '.join(reasons)}" for kind, reasons in needed.items()) or "none")
            return 0
        evidence: dict[str, list[str]] = {}
        for kind, ref in args.evidence:
            evidence.setdefault(kind, []).append(ref)
        receipt = record(Path.cwd(), ReviewTarget(args.base, args.head), os.environ.get(HOOK_CONTEXT),
                         args.verdict, evidence, args.finding, args.require, args.branch)
    except VerdictError as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(asdict(receipt)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
