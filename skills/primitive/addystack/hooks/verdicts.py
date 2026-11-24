#!/usr/bin/env python3
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
agent, and `{"rounds": N}`, with `"rating"` (1-10) and `"reason"` when the last round
rated the change, or `{"skipped": reason}`. Verdict readers skip them, since
they read only `work-verifier` rows. A result matches on patch-id, as a verdict does."""
from __future__ import annotations

import argparse
import fnmatch
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
# Files a review's size and review-loop's packet leave out, matched against "/<path>".
LEFT_OUT = (
    ("lockfile", [f"*/{name}" for name in (
        "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb",
        "Cargo.lock", "Gemfile.lock", "poetry.lock", "uv.lock", "Pipfile.lock", "composer.lock", "go.sum",
        "Podfile.lock", "Package.resolved", "flake.lock", "gradle.lockfile", "pubspec.lock", "mix.lock",
        "packages.lock.json", "deno.lock", "pdm.lock")]),
    ("vendored", ["*/vendor/*", "*/node_modules/*", "*/third_party/*"]),
    ("generated", ["*.min.js", "*.min.css", "*.map", "*.pb.go", "*_pb2.py", "*.generated.*"]),
)


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
    rating: int = 0  # the last round's 1-10 rating, or 0 when none was recorded
    reason: str = ""  # what cost the rating the most points


class VerdictError(Exception):
    pass


def _git(cwd: Path, *args: str, stdin: str | None = None, env: dict[str, str] | None = None) -> str:
    # Bytes in and out: text mode would turn \r\n into \n and hide a line-ending change.
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, env=env,
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
    return _git(cwd, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "--no-relative", "--full-index",
                f"{base}...{head}")


def classify(cwd: Path, base: str, head: str) -> dict[str, list[str]]:
    """evidence.classify, its errors as VerdictError."""
    import evidence  # here, so a broken evidence.py breaks only recording and classifying

    try:
        return evidence.classify(cwd, base, head)
    except evidence.EvidenceError as error:
        raise VerdictError(str(error))


def left_out(cwd: Path, numstat: bytes, sources: tuple[str, ...] = ()) -> list[tuple[str, str, str, str]]:
    """Each row of `git diff --numstat -z` as (added, deleted, path, why), where why is
    lockfile, vendored, generated, or binary for a file a review's size and packet leave
    out, or "" for one they keep. A renamed file's path is its new one. The attributes
    that mark a file are each source commit's, a mark in any counting, so a deleted file
    reads its base's; with none, the working tree's, as for working changes. Git before
    2.42 ignores GIT_ATTR_SOURCE and reads the working tree's."""
    rows, fields = [], iter(numstat.decode(errors="surrogateescape").split("\0"))
    for record in fields:
        if record:
            added, deleted, path = record.split("\t", 2)
            if not path:  # a rename: -z puts its old and new paths in the next two fields
                next(fields)
                path = next(fields)
            why = "binary" if added == "-" else next(
                (why for why, patterns in LEFT_OUT for pattern in patterns if fnmatch.fnmatchcase("/" + path, pattern)), "")
            rows.append((added, deleted, path, why))
    asked = [path for _, _, path, why in rows if not why]
    marked: dict[str, str] = {}
    root = Path(_git(cwd, "rev-parse", "--show-toplevel").strip())  # numstat's paths are from the root
    for source in (sources or (None,)) if asked else ():  # git's own attributes mark the rest, as linguist reads them
        env = {**os.environ, "GIT_ATTR_SOURCE": source} if source else None
        out = _git(root, "check-attr", "-z", "--stdin", "linguist-vendored", "linguist-generated",
                   stdin="\0".join(asked) + "\0", env=env).split("\0")
        marked |= {path: attribute[len("linguist-"):] for path, attribute, value in zip(out[0::3], out[1::3], out[2::3])
                   if value in ("set", "true")}
    return [(added, deleted, path, why or marked.get(path, "")) for added, deleted, path, why in rows]


def size(cwd: Path, base: str, head: str) -> str:
    """`git diff base...head`'s size without the files `left_out` names, a move counting as
    its edits, as `+A −D in F files`; then the left-out files' size the same way, and the
    largest of them, each with its why and its own size. The diff reads head's attributes,
    and a file reads its old side's at the merge base."""
    numstat = _git(cwd, "diff", "--numstat", "-z", "-M", "--no-relative", f"{base}...{head}",
                   env={**os.environ, "GIT_ATTR_SOURCE": head})
    rows = left_out(cwd, numstat.encode(errors="surrogateescape"), (_git(cwd, "merge-base", base, head).strip(), head))
    lines = lambda added, deleted: (0, 0) if added == "-" else (int(added), int(deleted))  # binary
    total = lambda part: (f"+{sum(lines(a, d)[0] for a, d, *_ in part)} −{sum(lines(a, d)[1] for a, d, *_ in part)}"
                          f" in {len(part)} file{'' if len(part) == 1 else 's'}")
    left = sorted((row for row in rows if row[3]), key=lambda row: -sum(lines(*row[:2])))
    named = [f"{path} ({why})" if why == "binary" else f"{path} ({why}, +{added} −{deleted})"
             for added, deleted, path, why in left]
    return total([row for row in rows if not row[3]]) + (f", leaving out {total(left)}: {_shown(named)}" if left else "")


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
    gaps = [(kind, gap, required[kind]) for kind in required if (gap := kinds.done_gap(kind, evidence.get(kind, [])))]
    if "mutants" not in required and (survived := kinds.survivors(evidence.get("mutants", []))):
        gaps.append(("mutants", survived, ["supplied"]))  # a survivor the verifier found refuses Done on any path
    # A mutant log saved for this head, in a folder named by its SHA or a prefix of 7 or more,
    # and left out of a Done would hide its survivors. Only a Done reads them, so a Not done
    # still revokes one when the folder won't read.
    saved, left = _store(cwd).parent / "evidence", []
    try:
        try:
            folders = list(saved.iterdir()) if verdict == "done" else []
        except FileNotFoundError:  # no evidence saved yet; any other error could hide a log
            folders = []
        left = kinds.left_out_mutants([folder for folder in folders if len(folder.name) >= 7
                                       and head.startswith(folder.name)], evidence.get("mutants", []))
    except OSError as error:
        raise VerdictError(f"Done reads every mutant log in this head's evidence folder, and {error}")
    if left:
        survived = [mutant for _, mutants in left for mutant in mutants]
        gaps.append(("mutants", f"{_shown([Path(path).name for path, _ in left])} in this head's evidence folder "
                                "isn't passed, and a Done passes every mutant log"
                     + (f"; it shows {len(survived)} survived ({'; '.join(survived)}), so record Not done naming "
                        "each" if survived else ""), ["run here"]))
    if verdict == "done" and gaps:
        raise VerdictError("Done needs evidence: " + "; ".join(
            f"{kind} ({_shown(reasons)}){'' if gap == 'no evidence' else f': {gap}'}"
            f" → --evidence {kind}={kinds.PLACEHOLDER[kind]}" for kind, gap, reasons in gaps))
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


def record_review(cwd: Path, target: ReviewTarget, rounds: int = 0, skipped: str = "", rating: int = 0,
                  reason: str = "") -> Review:
    """Records review-loop's result for `git diff base...head`: the rounds it ran, with the
    last round's 1-10 rating and what cost it the most points, or a skip with its reason.
    Unlike a verdict, any session records one, from any checkout."""
    if (rounds > 0) == bool(skipped.strip()):
        raise VerdictError("give the rounds review-loop ran (1 or more), or a skip's reason")
    if (rating or reason.strip()) and not (rounds and 1 <= rating <= 10 and reason.strip()):
        raise VerdictError("a rating is 1 to 10, with the rounds and a reason")
    base, head = (_git(cwd, "rev-parse", "--verify", f"{ref}^{{commit}}").strip() for ref in (target.base, target.head))
    patch_id = _patch_id(cwd, diff(cwd, base, head))
    if not patch_id:
        raise VerdictError(f"{head[:12]} makes no change against {base[:12]}")
    review = Review(patch_id, ReviewTarget(base, head), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    rounds, skipped.strip(), rating, reason.strip())
    session = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CODEX_THREAD_ID") or "-"
    result = {"rounds": rounds, **({"rating": rating, "reason": review.reason} if rating else {})}
    body = json.dumps({"skipped": review.skipped} if review.skipped else result, separators=(",", ":"))
    store = _store(cwd)
    store.parent.mkdir(parents=True, exist_ok=True)
    with store.open("a") as f:
        f.write("\t".join([patch_id, head, base, review.recorded_at, "v3", session, "-", REVIEWER, body]) + "\n")
    return review


def find_review(cwd: Path, pr_diff: str) -> Review | None:
    """review-loop's latest result for a PR's `diff`, or None. Raises VerdictError when it
    can't read the store or the row, so the gate fails closed."""
    return _review(cwd, _patch_id(cwd, pr_diff))


def _review(cwd: Path, patch_id: str) -> Review | None:
    store = _store(cwd)
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
            rating, reason = body.get("rating", 0), body.get("reason", "")
            if not (isinstance(rounds, int) and isinstance(skipped, str) and (rounds > 0) != bool(skipped)
                    and isinstance(rating, int) and isinstance(reason, str)
                    and (rating == 0 and not reason or rating in range(1, 11) and bool(reason))):
                raise ValueError("unexpected shape")
        except (ValueError, AttributeError) as error:
            raise VerdictError(f"can't read the review result recorded at {row[3]} for this diff: {error}")
        return Review(row[0], ReviewTarget(row[2], row[1]), row[3], rounds, skipped, rating, reason)
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
    can find something new: a Not verified waits on the real run it names; a Done stands
    while the diff is the one it checked, on any base, though a new base can still break
    it, so the reason names the checks and trial merge to rerun; and a Not done waits on
    a commit for each finding it marked fix while the diff and its merge base are the
    ones it checked, since a restack onto a parent can bring the fix in. A diff that
    won't read gives "", so the re-check runs."""
    if receipt.verdict == "not-verified":
        return "not verified until it runs: " + "; ".join(receipt.findings)
    fixes = [text for text in receipt.findings if re.search(r"→ fix\b", text)]
    if receipt.verdict == "not-done" and not fixes:
        return ""
    try:
        same = (_patch_id(cwd, diff(cwd, base, head)) == receipt.patch_id
                and (receipt.verdict == "done"
                     or _git(cwd, "merge-base", base, head) == _git(cwd, "merge-base", *astuple(receipt.reviewed))))
    except VerdictError:
        return ""
    if not same:
        return ""
    if receipt.verdict == "done":
        return (f"same diff as {receipt.reviewed.head[:12]}, Done stands; rerun the layer's checks and a trial merge"
                " at the new head")
    return f"same diff as {receipt.reviewed.head[:12]}, so still open: " + "; ".join(fixes)


def status(cwd: Path, base: str, head: str) -> str:
    """The patch-id of `diff(base, head)` and whether a Done verdict covers it, as the gate
    reads it, then for the ship-gate card the diff's size, review-loop's result with its
    rating, and an `idiom:` line per pattern the Done's idiom refs ground."""
    patch_id = _patch_id(cwd, diff(cwd, base, head))
    receipt = _latest(cwd, patch_id)
    done = receipt if receipt and receipt.verdict == "done" else None
    try:  # a review row that won't read blocks readying, not this card
        review = _review(cwd, patch_id)
        rounds = review and f"{review.rounds} round{'' if review.rounds == 1 else 's'}"
        reviewed = ("none" if not review else f"skipped: {review.skipped}" if review.skipped
                    else f"{rounds}, rated {review.rating}/10: {review.reason}" if review.rating
                    else f"{rounds}, no rating")
    except VerdictError as error:
        reviewed = f"unreadable: {error}"
    lines = [f"patch-id: {patch_id or 'none (no change)'}",
             f"done: yes ({done.recorded_at}, head {done.reviewed.head[:12]}, {done.verifier.agent_id})"
             if done else "done: no",
             f"size: {size(cwd, base, head)}", f"review: {reviewed}"]
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
    the patch-id, whether it's done, the size, review-loop's result, and a Done's idiom sources; `numstat
    [--source REV]...` reads `git diff --numstat -z --no-renames` and writes each row as
    `why<TAB>added<TAB>deleted<TAB>path` and a NUL, with `kept` for why when `left_out` keeps it; `classify <base> <head>` prints each kind of
    evidence the diff needs, one `kind: reason; reason` line each, or `none`; `last
    <branch> [<base> <head>]` prints the branch's newest verdict as JSON, or `last: none`;
    given the diff to re-check, the JSON adds `known`, `known(...)`'s reason, when it isn't
    empty; `review <base> <head> (--rounds N [--rating 1-10 --reason TEXT] | --skip REASON)`
    records review-loop's result and prints it as JSON. Exits 2 on a usage error and 1 on a
    VerdictError."""
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
    reviewing.add_argument("--rating", type=int, default=0, metavar="N")
    reviewing.add_argument("--reason", default="", metavar="TEXT")
    commands.add_parser("numstat").add_argument("--source", action="append", default=[], metavar="REV")
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
            review = record_review(Path.cwd(), ReviewTarget(args.base, args.head), args.rounds or 0, args.skip or "",
                                   args.rating, args.reason)
            print(json.dumps(asdict(review)))
            return 0
        if args.command == "numstat":
            for added, deleted, path, why in left_out(Path.cwd(), sys.stdin.buffer.read(), tuple(args.source)):
                sys.stdout.buffer.write(f"{why or 'kept'}\t{added}\t{deleted}\t{path}\0".encode(errors="surrogateescape"))
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
