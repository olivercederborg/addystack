# Copy of skills/primitive/addystack/hooks/evidence.py, written by scripts/sync-copies.py: edit the source, then run the script.
"""The evidence a change needs before verify-work can record Done, by change type, and
whether a ref backs it. verdicts.py imports it only to record or classify, so a broken
copy can't break the merge gate's reads.

- ui: a capture (image or video) of the changed states.
- parity: a log or diff comparing outcomes on base and head.
- contract: a diff of the schema or exported declarations.
- mutants: a log of `killed: <mutant>` / `survived: <mutant>` lines, at least 3.
- deploy: the live URL, or a file showing what serves the change.
- toolchain: a log of dev-server runs at base and head, one `base:` or `head:` line per
  run with `peak_rss_mb=` and `procs=`, as `dev-cost.py` prints them. Done is refused
  while either mean grew by GROWTH or more, unless an `accepted: <why>` line names it.
- idiom: for code added or edited outside tests, a file with one line per non-trivial
  pattern the change introduces, each naming the upstream doc or source URL that shows
  it's the library's intended use, or a single `none: <why>` line for a change with none.

A ref `not-run:<reason>` names a check that couldn't run here: it's allowed for any kind,
but never backs Done. A Done also passes every mutant log the head's evidence folder holds
(left_out_mutants), so a survivor in one refuses it whether or not the kind was required.

Known limits: classify is a text heuristic and a floor, not a parser, and the verifier
adds the kinds it misses with `--require`. Contract reads `-U0` hunk headers, so it
misses, for example, a repo whose own `diff=` funcname driver covers TypeScript, member
changes inside exported classes and functions, and exports in languages other than
JS and TS."""
from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

KINDS = ("ui", "parity", "contract", "mutants", "deploy", "idiom", "toolchain")
NOT_RUN = "not-run:"
PLACEHOLDER = {"ui": "<capture>", "parity": "<log>", "contract": "<diff>", "mutants": "<log>", "deploy": "<url>",
               "idiom": "<sources>", "toolchain": "<log>"}

UI_FILE = re.compile(r"\.(tsx|jsx|vue|svelte|css|scss|sass|less|html|storyboard|xib)$")
# A .tsx or .jsx file renders only when it has JSX: a closing or self-closing tag, or a
# fragment. A generic such as `Set<Item>()` has neither.
JSX_FILE = re.compile(r"\.(tsx|jsx)$")
JSX = re.compile(r"</[A-Za-z>]|/>|<>")
UI_SWIFT = re.compile(r"^\s*import\s+(SwiftUI|UIKit)\b", re.M)
SCHEMA_FILE = re.compile(r"(^|/)(openapi|swagger)[^/]*$|\.schema\.json$|\.(proto|graphql|gql)$|\.d\.ts$")
EXPORTING_FILE = re.compile(r"\.(ts|tsx|js|jsx|mjs|cjs|mts|cts)$")
# A literal value: changing `export const version = 19` to 20 keeps the declaration.
LITERAL_VALUE = re.compile(r"""\s*=\s*(-?[\d.]+|"[^"]*"|'[^']*'|`[^`$]*`|true|false|null)\s*;?$|\s*[{;]$""")
# With -U0, a hunk header ends with the top-level line above the hunk (git's default
# funcname: a line starting with a letter, `_`, or `$`), so a member line removed under
# one of these is part of an exported type. Function and class bodies aren't.
EXPORTED_TYPE = re.compile(r"export\s+(default\s+)?(declare|(const\s+)?(interface|type|enum))\b")
TOP_LEVEL = re.compile(r"[A-Za-z_$]")
CODE_FILE = re.compile(r"\.(ts|tsx|js|jsx|mjs|cjs|mts|cts|py|go|rb|swift|kt|java|rs|php|cs|ex|exs)$")
# No `session`: apps name domain sessions (a training session) as often as logins.
RISKY_WORDS = {"payment", "billing", "invoice", "charge", "refund", "payout", "ledger", "money", "price", "pricing",
               "currency", "wallet", "stripe", "subscription", "auth", "authentication", "authorization", "login",
               "logout", "password", "permission", "rbac", "acl", "oauth", "jwt", "migration"}
DEPLOY_FILE = re.compile(r"(^|/)(Dockerfile[^/]*|docker-compose[^/]*|fly\.toml|vercel\.json|netlify\.toml"
                         r"|railway\.(json|toml)|render\.yaml|Procfile|eas\.json|[^/]+\.tf)$|(^|/)(k8s|helm|charts)/")
# Config a dev server or bundler loads: a plugin or loader added here runs on every module
# in local dev, which CI's production build never exercises.
TOOLCHAIN_FILE = re.compile(r"(^|/)((next|vite|webpack|rspack|rsbuild|metro|babel|postcss|tailwind|astro|nuxt|svelte"
                            r"|react-router)\.config\.[cm]?[jt]s|\.babelrc(\.[a-z]+)?)$")
DEV_RUN = re.compile(r"^(base|head):.*?\bpeak_rss_mb=(\d+(?:\.\d+)?)\b.*?\bprocs=(\d+)\b", re.M)
ACCEPTED = re.compile(r"^accepted:\s*\S", re.M)
GROWTH = 0.2
WORKFLOW = re.compile(r"^\.github/workflows/[^/]+$")
DEPLOYS = re.compile(r"deploy|release", re.I)
TEST_FILE = re.compile(r"(^|/)(__tests__|tests?|e2e)/|\.(test|spec|jest)\.[^/]+$|Tests\.swift$|(^|/)test_[^/]+\.py$"
                       r"|_test\.(py|go)$")
# Parity: any message that claims it, or a branch whose every subject is a refactor or
# migration. One refactor commit inside a feature branch doesn't make the branch one.
# Not a bare "parity": "add the parity test" or "ui, parity, contract" claims nothing.
PARITY_CLAIM = re.compile(r"\b(no behaviou?r(al)? changes?|behaviou?r[- ]preserving|(behaviou?r(al)?|logic) parity)\b",
                          re.I)
PARITY_SUBJECT = re.compile(r"\b(refactor\w*|migrat(e|es|ed|ing)|port(s|ed|ing)? to|rewr(ite|ites|ote|itten)"
                            r"|upgrad(e|es|ed|ing))\b", re.I)
# A deploy claim names where it went. "Ship the fix" as a subject's verb claims nothing.
DEPLOY_CLAIM = re.compile(r"\b(deploy|release|ship)\w* to (prod|production|staging|live)\b", re.I)
# A quoted phrase is a mention, not a claim: 'Stop reading "parity" as one' claims nothing.
# A single quote opens and closes only outside a word, so "don't" and "it's" don't pair up.
QUOTED = re.compile(r"\"[^\"\n]*\"|`[^`\n]*`|(?<!\w)'[^'\n]*'(?!\w)")
# Each capture type and the first bytes it starts with, so a renamed text file isn't one.
MEDIA = {suffix: re.compile(magic, re.S) for suffixes, magic in [
    ((".png",), rb"\x89PNG\r\n\x1a\n"), ((".jpg", ".jpeg"), rb"\xff\xd8\xff"), ((".gif",), rb"GIF8"),
    ((".webp",), rb"RIFF.{4}WEBP"), ((".mp4", ".mov"), rb".{4}ftyp"), ((".webm",), rb"\x1a\x45\xdf\xa3")]
    for suffix in suffixes}
MUTANT_LINE = re.compile(r"^(killed|survived):[ \t]*(\S.*)$", re.M)  # `\s*` would take the next line as the mutant
MUTANT_LOG = re.compile(r"mutant|mutation", re.I)  # a file name; a test log can quote `survived:` too
SOURCE_URL = re.compile(r"https?://[^\s<>()\[\]]+")
NO_PATTERN = re.compile(r"none:\s*\S")


class EvidenceError(Exception):
    pass


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=cwd, capture_output=True)
    if result.returncode:
        raise EvidenceError(f"`git {' '.join(args[:2])}` failed: {result.stderr.decode(errors='replace').strip()[:200]}")
    return result.stdout.decode(errors="replace")


def _content(cwd: Path, base: str, head: str, path: str) -> str:
    """The file at head, or at base when the change deleted it."""
    for rev in (head, base):
        result = subprocess.run(["git", "cat-file", "-p", f"{rev}:{path}"], cwd=cwd, capture_output=True)
        if not result.returncode:
            return result.stdout.decode(errors="replace")
    return ""


def _first_bytes(path: Path, size: int = 12) -> bytes:
    with path.open("rb") as f:
        return f.read(size)


def _words(path: str) -> list[str]:
    """Path segments split on `/ _ - .` and camelCase, lowercased, plural `s` dropped."""
    words = (word.lower() for part in re.split(r"[/_.\-]+", path)
             for word in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", part))
    return [word[:-1] if word.endswith("s") and word[:-1] in RISKY_WORDS else word for word in words]


def _removed_exports(patch: str) -> dict[str, list[str]]:
    """Each file's `export` lines, and member lines of an exported interface, type, or
    enum, that the diff removes without adding the same line back, ignoring a literal
    value and a trailing `{`, `;`, or `,`. A member comes back only inside the same
    declaration: one moved to another exported type is still removed from the first."""
    removed: dict[str, list[tuple[str, tuple[str, str]]]] = {}  # path -> [(shown, (owner, compared))]
    added: dict[str, set[tuple[str, str]]] = {}
    declaration = lambda line: LITERAL_VALUE.sub("", line[1:].strip())
    member = lambda line: line[1:].strip().rstrip(";,")
    owner = lambda text: text[:80].rstrip()  # git cuts a hunk header's top-level line at 80 bytes
    path, in_header, enclosing, added_enclosing = "", False, "", ""
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            in_header = True
        elif in_header and line.startswith("--- "):
            path = line[6:].rstrip("\t") if line.startswith("--- a/") else ""
        elif in_header and line.startswith("+++ ") and not path:
            path = line[6:].rstrip("\t")
        elif line.startswith("@@"):
            in_header, enclosing = False, line.split("@@", 2)[-1].strip()
            added_enclosing = enclosing
        elif in_header:
            continue
        elif line.startswith("-export "):
            removed.setdefault(path, []).append((line[1:].strip(), ("", declaration(line))))
            enclosing = line[1:].strip()
        elif line.startswith("+export "):
            added.setdefault(path, set()).add(("", declaration(line)))
            added_enclosing = line[1:].strip()
        elif line.startswith("+"):
            added.setdefault(path, set()).add((owner(added_enclosing), member(line)))
            if TOP_LEVEL.match(line[1:]) or line.startswith("+}"):
                added_enclosing = line[1:].strip()
        elif line.startswith("-") and (TOP_LEVEL.match(line[1:]) or line.startswith("-}")):
            enclosing = line[1:].strip()  # a hunk's removed lines run in order, so it encloses the next ones
        elif line.startswith("-") and EXPORTED_TYPE.match(enclosing) and not re.match(r"$|//|/?\*|}", member(line)):
            removed.setdefault(path, []).append((f"{enclosing} … {member(line)}", (owner(enclosing), member(line))))
    return {path: kept for path, lines in removed.items()
            if (kept := [shown for shown, key in lines if key not in added.get(path, set())])}


def classify(cwd: Path, base: str, head: str) -> dict[str, list[str]]:
    """Each kind of evidence `base...head` needs, with the reasons, in KINDS order; a kind
    with no reason is left out."""
    files = [path for path in _git(cwd, "diff", "--name-only", "-z", f"{base}...{head}").split("\0") if path]
    # A deleted file has no code left to mutate; its removed exports still count as contract.
    deleted = set(_git(cwd, "diff", "--name-only", "--diff-filter=D", "-z", f"{base}...{head}").split("\0"))
    reasons: dict[str, list[str]] = {kind: [] for kind in KINDS}
    for path in files:
        name, is_test = PurePosixPath(path).name, bool(TEST_FILE.search(path))
        if not is_test and UI_FILE.search(path) and (not JSX_FILE.search(path)
                                                     or JSX.search(_content(cwd, base, head, path))):
            reasons["ui"].append(f"{path}: UI file")
        elif not is_test and path.endswith(".swift") and (ui := UI_SWIFT.search(_content(cwd, base, head, path))):
            reasons["ui"].append(f"{path}: imports {ui.group(1)}")
        if not is_test and SCHEMA_FILE.search(path):
            reasons["contract"].append(f"{path}: API schema")
        if (not is_test and path not in deleted and CODE_FILE.search(path)
                and (word := next((w for w in _words(path) if w in RISKY_WORDS), None))):
            reasons["mutants"].append(f"{path}: {word} path")
        elif not is_test and (path.endswith(".sql") or name == "schema.prisma"):
            reasons["mutants"].append(f"{path}: {'SQL' if path.endswith('.sql') else 'Prisma schema'}")
        if TOOLCHAIN_FILE.search(path):
            reasons["toolchain"].append(f"{path}: dev toolchain config")
        if DEPLOY_FILE.search(path):
            reasons["deploy"].append(f"{path}: deploy config")
        elif WORKFLOW.match(path) and DEPLOYS.search(name + _content(cwd, base, head, path)):
            reasons["deploy"].append(f"{path}: deploy workflow")
    # A file the change only deletes introduces no pattern.
    kept = _git(cwd, "diff", "--name-only", "--diff-filter=d", "-z", f"{base}...{head}").split("\0")
    reasons["idiom"] = [f"{path}: code" for path in kept if CODE_FILE.search(path) and not TEST_FILE.search(path)]
    code = [path for path in files if EXPORTING_FILE.search(path) and not TEST_FILE.search(path)]
    if code:
        patch = _git(cwd, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "-U0", f"{base}...{head}", "--", *code)
        for path, lines in _removed_exports(patch).items():
            more = f" and {len(lines) - 1} more" if len(lines) > 1 else ""
            reasons["contract"].append(f"{path}: changes or removes `{lines[0][:80]}`{more}")
    log = _git(cwd, "log", "--no-merges", "--format=%h%x00%s%x00%B%x1e", f"{base}..{head}")
    commits = [commit.strip("\n").split("\0", 2) for commit in log.split("\x1e") if commit.strip()]
    every_subject_refactors = bool(commits) and all(PARITY_SUBJECT.search(subject) for _, subject, _ in commits)
    for sha, subject, message in commits:
        said = lambda match: f"commit {sha} '{subject}': says \"{match.group(0)}\""
        message = QUOTED.sub("", message)
        if claim := PARITY_CLAIM.search(message) or (every_subject_refactors and PARITY_SUBJECT.search(subject)):
            reasons["parity"].append(said(claim))
        if claim := DEPLOY_CLAIM.search(message):
            reasons["deploy"].append(said(claim))
    return {kind: found for kind, found in reasons.items() if found}


def check(kind: str, refs: list[str], cwd: Path) -> tuple[list[str], list[str]]:
    """The refs as stored, file paths made absolute, and each problem with them."""
    if kind not in KINDS:
        return refs, [f"evidence kind {kind!r} isn't one of {', '.join(KINDS)}"]
    stored, problems, nones = [], [], []
    for ref in refs:
        if ref.startswith(NOT_RUN):
            stored.append(ref)
            if not ref[len(NOT_RUN):].strip():
                problems.append(f"{kind}={ref} names no reason")
            continue
        if kind == "deploy" and re.match(r"https?://\S+$", ref):
            stored.append(ref)
            continue
        path = (cwd / Path(ref).expanduser()).resolve()
        stored.append(str(path))
        if not path.is_file():
            problems.append(f"{kind}={ref}: no such file")
        elif not path.stat().st_size:
            problems.append(f"{kind}={ref}: the file is empty")
        elif kind == "ui" and path.suffix.lower() not in MEDIA:
            problems.append(f"{kind}={ref}: not an image or video ({' '.join(MEDIA)})")
        elif kind == "ui" and not MEDIA[path.suffix.lower()].match(_first_bytes(path)):
            problems.append(f"{kind}={ref}: its bytes aren't a {path.suffix.lower()[1:]} file")
        elif kind == "mutants" and len(MUTANT_LINE.findall(path.read_text(errors="replace"))) < 3:
            problems.append(f"{kind}={ref}: fewer than 3 `killed:` or `survived:` lines")
        elif kind == "toolchain" and len({run[0] for run in DEV_RUN.findall(path.read_text(errors="replace"))}) < 2:
            problems.append(f"{kind}={ref}: needs a `base:` and a `head:` line, each with `peak_rss_mb=` and `procs=`")
        elif kind == "idiom":
            text = path.read_text(errors="replace")
            if problem := _unsourced(text):
                problems.append(f"{kind}={ref}: {problem}")
            elif NO_PATTERN.match(text.strip()):
                nones.append(ref)
    if nones and len([ref for ref in refs if not ref.startswith(NOT_RUN)]) > 1:
        problems.append(f"{kind}={nones[0]}: a `none:` file says the change has no pattern, so it's the only {kind} ref")
    return stored, problems


def _unsourced(text: str) -> str | None:
    """What keeps an idiom file from grounding the change, or None when each line names a
    pattern and its source URL or the file is one `none: <why>` line."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) == 1 and NO_PATTERN.match(lines[0]):
        return None
    if not lines:
        return "the file is blank"
    if unsourced := [line for line in lines if not _sourced(line)]:
        return (f"`{unsourced[0][:80]}` isn't `<pattern> · source: <URL>`: write one such line per pattern,"
                " or one `none: <why>` line")
    return None


def _sourced(line: str) -> bool:
    """Whether a line is grounding's evidence line: a pattern, then ` · ` parts, one of
    them a `source:` naming a URL whose host has a dot."""
    pattern, *parts = [part.strip() for part in line.split("·")]
    urls = [url for part in parts if part.startswith("source:") for url in SOURCE_URL.findall(part)]
    return (bool(re.search(r"\w", pattern)) and not pattern.startswith("none:")
            and any("." in (urlsplit(url).hostname or "") for url in urls))


def survivors(refs: list[str]) -> str | None:
    """The `survived:` mutants in `check`ed mutants logs, or None when there are none."""
    found = [mutant for ref in refs if not ref.startswith(NOT_RUN)
             for outcome, mutant in MUTANT_LINE.findall(Path(ref).read_text(errors="replace")) if outcome == "survived"]
    return f"{len(found)} survived ({'; '.join(found)})" if found else None


def left_out_mutants(folders: list[Path], refs: list[str]) -> list[tuple[str, list[str]]]:
    """(path, survivors) for each regular file under folders, a head's evidence folders,
    whose name says mutant or mutation and that holds a survivor or 3 results (`killed:` or
    `survived:` lines), when refs, a Done's mutants evidence, don't name that file. Fewer, all
    killed, hide nothing, and `check` wouldn't take them. verify-108-1 saved a log with three
    survivors there on Nov 8, 2026, and recorded Done without it. Files and folders compare
    by device and inode, so a case-variant path, a hard link, or a linked folder counts once.
    It raises OSError for a file or folder it can't read, since that could hide a survivor
    too; `is_dir()` and `is_file()` would read one as absent."""
    def fail(error):
        raise error
    def identity(path):
        info = os.stat(path)
        return info.st_dev, info.st_ino
    given = {identity(ref) for ref in refs if not ref.startswith(NOT_RUN)}
    found, walked, read = [], set(), set()
    for folder in folders:
        if not stat.S_ISDIR(os.stat(folder).st_mode) or identity(folder) in walked:
            continue  # a file named like the head isn't an evidence folder
        walked.add(identity(folder))
        for root, subfolders, names in os.walk(folder, onerror=fail, followlinks=True):
            kept = []
            for name in sorted(subfolders):
                if (key := identity(os.path.join(root, name))) not in walked:
                    walked.add(key)
                    kept.append(name)
            subfolders[:] = kept
            for name in sorted(names):
                path = os.path.join(root, name)
                os.lstat(path)  # raises where root lists names it can't search, so a link there isn't skipped
                if not MUTANT_LOG.search(name):
                    continue
                info = os.stat(path)
                if not stat.S_ISREG(info.st_mode) or (key := (info.st_dev, info.st_ino)) in given | read:
                    continue  # reading a FIFO would wait for a writer
                read.add(key)
                results = MUTANT_LINE.findall(Path(path).read_text(errors="replace"))
                if any(outcome == "survived" for outcome, _ in results) or len(results) >= 3:
                    found.append((path, [mutant for outcome, mutant in results if outcome == "survived"]))
    return found


def dev_cost_growth(refs: list[str]) -> str | None:
    """How the head's mean dev-server cost grew past GROWTH over the base's in `check`ed
    toolchain logs, or None when it didn't or an `accepted:` line names the growth."""
    texts = [Path(ref).read_text(errors="replace") for ref in refs if not ref.startswith(NOT_RUN)]
    if any(ACCEPTED.search(text) for text in texts):
        return None
    runs = [run for text in texts for run in DEV_RUN.findall(text)]
    grew = []
    for name, unit, index in (("peak RSS", " MB", 1), ("processes", "", 2)):
        base, head = ([float(run[index]) for run in runs if run[0] == label] for label in ("base", "head"))
        base, head = sum(base) / len(base) if base else 0, sum(head) / len(head) if head else 0
        if base and head / base - 1 >= GROWTH:
            grew.append(f"{name} {round(base)} → {round(head)}{unit} (+{round((head / base - 1) * 100)}%)")
    return f"dev cost grew: {', '.join(grew)}" if grew else None


def done_gap(kind: str, refs: list[str]) -> str | None:
    """Why `check`ed refs don't back Done for `kind`, or None when they do."""
    if not [ref for ref in refs if not ref.startswith(NOT_RUN)]:
        reasons = [ref[len(NOT_RUN):].strip() for ref in refs]
        return f"not run here ({'; '.join(reasons)})" if reasons else "no evidence"
    if kind == "toolchain":
        return dev_cost_growth(refs)
    return survivors(refs) if kind == "mutants" else None
