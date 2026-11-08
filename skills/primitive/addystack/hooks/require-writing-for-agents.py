#!/usr/bin/env python3
"""PreToolUse on Write|Edit|MultiEdit|Bash: deny writes to agent-facing docs until this
session has loaded writing-for-agents. Agent-facing: SKILL.md, a skill's references or
feature map, the skills kit's shared docs, principles, and core templates, the global
instructions' sources (`global/`), AGENTS.md, and CLAUDE.md.

Bash counts because most skill edits go through it (python heredocs, `sed -i`, `>`,
`tee`, `sync-format.sh`), which the first, Write/Edit-only version never saw. Each write
counts by the paths it writes, never by the names elsewhere in the command: a redirect's
target, the files after `tee`, `sed -i`, or `perl -i`, a `cp` or `mv` destination (in a
folder, under the source's name), and an `open()` or `write_text()` path. So reads with
`2>/dev/null` or `>&2` pass, and so does copying CLAUDE.md out to /tmp. A target built from
a variable (`> "$f"`, `open(p, "w")`) counts when its literal tail is an agent doc's
(`"$d/SKILL.md"`), or when an agent doc is named where the command binds that variable:
`f='a.md'; f='AGENTS.md'`, `for f in */SKILL.md`, `p = root / "SKILL.md"`, a helper's
parameter at its call sites (`edit("build/SKILL.md")`), followed two names deep. A variable
the command never binds, and a computed `open()` path, fall back to every name the command
holds. On Oct 30, 2026 two coordinators' heredocs writing project.md were denied: one
because its text quoted `cp -RL` and named SKILL.md files, the other because it wrote two
files through the same `p`, and its text named CLAUDE.md.

Known limits: regexes can't balance parentheses or tell a script's text from what it runs,
so a `tee`, `cp`, `sed -i`, or redirect inside a string the command writes still counts as
a write of its own targets, as on main. A `cp -r` of a folder is judged by its destination's
path, so copying a whole skill folder into place passes. After any `cd`, a resolved relative
path shaped like a kit doc counts even when the `cd` led elsewhere, which costs one skill
load; a literal redirect after a `cd` into the kit from another folder is missed, as on main.
An arrow or a tag's `/>` isn't read as a redirect, so `printf x/>AGENTS.md` is missed."""
import functools, json, keyword, os, pathlib, re, sys

payload = json.load(sys.stdin)
tool = payload.get("tool_name", "")
tool_input = payload.get("tool_input") or {}
transcript = payload.get("transcript_path") or ""
cwd = payload.get("cwd") or os.getcwd()

AGENT_DOC = re.compile(r"(?:^|/)(?:SKILL\.md|AGENTS\.md|CLAUDE\.md)$"
                       r"|/skills/(?:[^/\s]+/)?[^/\s]+/(?:references|features)/[^/\s]+\.md$"
                       r"|/skills/(?:shared|principles)/[^/\s]+\.md$"
                       r"|/addystack/(?:principles|core)/[^/\s]+\.md$"
                       r"|/skills/global/(?:built/)?[^/\s]+\.md$")
TOKEN = re.compile(r"[\"']?([~./\w-][^\s\"'`;|&<>()]*\.md)")
# An arrow (`a -> b`, `x => f(x)`) and a tag's `/>` are text, not redirects.
REDIRECT = re.compile(r"(?<![-=/])>>?\|?\s*[\"']?([^\s\"';|&<>()]+)")
# A write command anywhere in the text, strings included, with what follows it.
WRITE_COMMAND = re.compile(r"\b(tee|cp|mv)\s|\b(?:sed|perl)\s+(?:-[a-zA-Z]+\s+)*?-[a-zA-Z]*i")
# One argument: quoted (single quotes may hold parens, a sed script's), `$(…)`, or bare,
# concatenated; it ends at a shell separator or at a quote that doesn't close on its line.
ARG = re.compile(r"(?:'[^'\n]*'|\"(?:\\.|\$\([^()\n]*\)|[^\"\\\n()])*\"|\$\([^()\n]*\)|[^\s;&|<>()`'\"])+")
OPEN_WRITE = re.compile(r"\bopen\(\s*f?[\"']([^\"']+)[\"']\s*,\s*(?:mode\s*=\s*)?[\"'][wa]"
                        r"|\bopen\(\s*(\w+)\s*,\s*(?:mode\s*=\s*)?[\"'][wa]"
                        r"|\bPath\(\s*f?[\"']([^\"']+)[\"']\s*\)\.write_text\("
                        r"|(?<![\w.)])(\w+)\.write_text\(")
OPEN_ANY_WRITE = re.compile(r"\bopen\((?:[^()]|\([^()]*\))*,\s*(?:mode\s*=\s*)?[\"'][wa]|\.write_text\(")
# `p = 'x.md'` or `p = Path("x.md")`, the literal ending the statement, but not `p == 'x'`,
# `p = 'a' + b`, or an unquoted `p=os.path.join(...)`.
ASSIGN = re.compile(r"(?:^|[\s;(])(\w+)\s*=(?!=)\s*(?:(?:pathlib\.)?Path\(\s*)?f?([\"'])([^\"'\n]+)\2\)?"
                    r"(?=[ \t]*(?:[;\n#]|$))", re.M)
# sync-format.sh as the command of a segment, optionally after env assignments or a
# shell, and without --check in that segment; `cat scripts/sync-format.sh` only reads it.
RUNS_SYNC_FORMAT = re.compile(r"(?:^|[;&|(\n])\s*(?:\w+=\S*\s+)*(?:(?:ba|z)?sh\s+)?[\"']?"
                              r"[^\s;&|<>()\"']*sync-format\.sh\b[\"']?(?![^;&|\n]*--check)")
VARIABLE = re.compile(r"\$")  # f-string braces become ${...}, so awk's `>=2{print}` stays literal


def kit_path(path):
    """path as /skills/<path inside the kit> when it's inside a skills kit checkout, which
    a T3 worktree (…/worktrees/skills/t3-1a2b/) names differently; else path. A kit
    checkout, the workshop or the addystack repo, holds the tool at skills/primitive/addystack/."""
    for parent in pathlib.Path(path).parents:
        if (parent / "skills" / "primitive" / "addystack" / "hooks" / "manifest.json").is_file():
            return "/skills/" + os.path.relpath(path, parent)
    return path


def agent_doc(path):
    expanded = os.path.expanduser(path)
    if not expanded.startswith("/"):
        # A relative path can name a kit folder only through the working directory.
        if AGENT_DOC.search("/" + expanded):
            return True
        expanded = os.path.normpath(os.path.join(cwd, expanded))
    return bool(AGENT_DOC.search(expanded) or AGENT_DOC.search(kit_path(expanded)))


def may_be_agent_doc(target):
    """A literal target is checked exactly. A target built from variables counts unless
    the literal text after its last variable shows a basename no agent doc has."""
    if not VARIABLE.search(target):
        return agent_doc(target)
    last = list(re.finditer(r"\$\{[^}]*\}", target))[-1:]
    if last and re.match(r"\$\{\w+[%#/:^,]", last[0].group()) and "/" not in target[last[0].end():]:
        return True  # `${f%.md}.md` rewrites the basename, so its tail proves nothing
    tail = re.split(r"\$\{?\w+\}?|\{[^}]*\}", target)[-1]
    if "/" not in tail and tail in ("", ".md"):
        return True  # the basename itself is a variable
    if not tail.endswith(".md"):
        return False
    if re.search(r"(?:^|/)(?:SKILL|AGENTS|CLAUDE)\.md$|/(?:references|features|skills|shared)/", target):
        return True
    return False


CHANGES_DIR = re.compile(r"(?:^|[;&|({\n]|\b(?:if|elif|then|else|do|while|until)\b)\s*(?:cd|pushd)\s"
                         r"|\bchdir\(|\bcwd\s*=")
INTERPRETER = re.compile(r"\b(?:python3?|node|bun|ruby|perl|deno)\b[^\n]*<<")


def strip_data_heredocs(command):
    """Drop heredoc bodies that are data (a PR body passed to cat), and keep ones fed to
    an interpreter, whose code may write a SKILL.md."""
    def keep_or_drop(match):
        return match.group(0) if INTERPRETER.search(match.group(1)) else match.group(1)
    return re.sub(r"([^\n]*<<-?\s*['\"]?(\w+)['\"]?[^\n]*)\n.*?\n\2\b", keep_or_drop, command, flags=re.S)


def bindings(name, command):
    """How many places the command may bind name. Anything left of an `=` on its line
    counts (`p =`, `p +=`, `p: str =`, `(a, p) =`, `f(p=1)`), as do a for, `as`, a def or
    lambda parameter, a match case, and shell `read`, `mapfile`, or `printf -v`;
    overcounting only keeps the scan."""
    n = rf"(?<![\w.]){re.escape(name)}\b"
    return sum(len(re.findall(pattern, command)) for pattern in [
        rf"{n}[^=\n]*(?<![=!<>])=(?!=)",
        rf"\bfor\b[^:]*?{n}",
        rf"\bas\s+[\w\s,(]*?{n}",
        rf"\bdef\s+\w+\s*\([^)]*{n}",
        rf"\blambda\b[^:\n]*{n}",
        rf"\bcase\b[^:\n]*{n}",
        rf"\b(?:read|mapfile|readarray)\b[^\n;|&]*{n}",
        rf"\bprintf\b[^\n;|&]*\s-v\s*{n}",
        rf"\bglobal\b[^\n]*{n}",
    ])


def resolve(target, command):
    """A bare variable whose only binding in the command is one quoted literal becomes
    that literal, with an f-string's `{x}` as `${x}` so may_be_agent_doc reads its tail."""
    name = re.fullmatch(r"\$\{?(\w+)\}?", target)
    values = [value for n, _, value in ASSIGN.findall(command) if name and n == name.group(1)]
    if len(values) != 1 or bindings(name.group(1), command) != 1:
        return target
    return values[0] if "$" in values[0] else values[0].replace("{", "${")


def substituted(target, command, limit=16, partial=False):
    """Each literal path target becomes when every variable in it takes one of the plain
    values the command binds it to (`d='global'`, `d=build`, `for d in a b`, a `mktemp`
    folder); none when any binding of a variable is something else, such as an expression.
    With partial, such a variable stays in the path instead."""
    names = list(dict.fromkeys(re.findall(r"\$\{?([A-Za-z_]\w*)\}?", target)))
    if not names or re.search(r"\$\{\w+[^\w}]", target):
        return []  # `${f%.md}` and the like rewrite the value
    paths = [target]
    for name in names:
        values = set()
        for text in binding_texts(name, command, depth=0):
            if re.match(r"\s*[\"']?\$\(mktemp\b", text):
                values.add("/tmp/mktemp")  # a new temp folder, outside any kit
                continue
            word = r"'[^'\n]*'|\"[^\"\n$`]*\"|[^\s;&|<>()`'\"$\[\]{},=]+"
            if not text.strip() or text.rstrip().endswith(":") or re.sub(rf"(?:{word})|\s+", "", text):
                # an expression, such as `Path(path)`, or a Python loop over a name (`for p in edits:`)
                values = None
                break
            values |= {unquote(w) for w in re.findall(word, text)}
        if not values or len(values) > limit:
            if partial:
                continue  # leave the variable in the path
            return []
        paths = [re.sub(rf"\$\{{?{name}\}}?(?!\w)", lambda _: v, p) for p in paths for v in values][:limit]
    return paths if partial else [p for p in paths if not VARIABLE.search(p)]


def arguments(text):
    """The arguments that open text, up to the first shell separator or unbalanced quote."""
    args, at = [], 0
    while True:
        space = re.match(r"[ \t]*(?:\\\n[ \t]*)*", text[at:])
        at += space.end()
        match = ARG.match(text, at)
        if not match:
            return args
        args.append(match.group())
        at = match.end()


def unquote(arg):
    return re.sub(r"'([^']*)'|\"((?:\\.|[^\"\\])*)\"", lambda m: m.group(1) if m.group(1) is not None else m.group(2), arg)


def command_targets(command):
    """Paths the write commands in command write: tee's files, sed -i's and perl -i's files
    (after the script), and cp's or mv's destination, inside it under each source's name when
    it's a folder. A sed fed its files by xargs or find -exec counts its whole segment."""
    found = []
    for match in WRITE_COMMAND.finditer(command):
        args = [unquote(a) for a in arguments(command[match.end():])]
        files = [a for a in args if not a.startswith("-")]
        if match.group(1) == "tee":
            found += files
        elif match.group(1):  # cp or mv
            if "-t" in args[:-1]:
                dest = args[args.index("-t") + 1]
                sources, folder = [f for f in files if f != dest], True
            elif len(files) < 2:
                continue
            else:
                dest, sources = files[-1], files[:-1]
                # A variable destination is a folder when a value the command binds it to is one.
                folder = any(d.endswith("/") or d in (".", "..", "~") or os.path.isdir(os.path.join(cwd, os.path.expanduser(d)))
                             for d in [dest] + substituted(dest, command))
            found += [dest.rstrip("/") + "/" + os.path.basename(src.rstrip("/")) for src in sources] if folder else [dest]
        else:  # sed -i or perl -i: the first plain argument is the script unless -e gave it
            files = [a for a in files if a]  # macOS sed's `-i ''` backup suffix
            given = any(a in ("-e", "-f") for a in args) or re.search(r"\s-[a-zA-Z]*e\s*$", match.group())
            found += files if given else files[1:]
            segment = re.split(r"[;&\n]", command[:match.start()])[-1]
            if re.search(r"\bxargs\b|-exec\b", segment):
                found += ["$segment:" + segment]
    return found


@functools.lru_cache(maxsize=None)
def bindable(command):
    """Every name command could bind: each word left of a line's last `=`, and each word on
    a line with a loop, `with`, `def`, `lambda`, `case`, `read`, or `printf`. A cheap
    filter, so binding_texts scans the whole command only for these."""
    names = set()
    for line in command.split("\n"):
        if "=" in line:
            names |= set(re.findall(r"[A-Za-z_]\w*", line[:line.rfind("=")]))
        if re.search(r"\b(?:for|in|with|as|def|lambda|case|read|mapfile|readarray|printf)\b", line):
            names |= set(re.findall(r"[A-Za-z_]\w*", line))
    # A def's parameters, and a loop's or `as`'s parenthesized names, can span lines.
    for group in re.findall(r"\b(?:def\s+\w+\s*|for\s*|as\s*)\(([^)]*)\)", command):
        names |= set(re.findall(r"[A-Za-z_]\w*", group))
    return frozenset(names)


def binding_texts(name, command, depth=2, seen=None):
    """The text of each place command may bind name, and, depth names deep, of the names
    those bind from; empty when it binds name nowhere. Overcounting only keeps a write."""
    seen = (seen or set()) | {name}
    texts = list(direct_bindings(name, command)) if name in bindable(command) else []
    if re.search(r"\bargv\b|\bARGV\b|\$[@*1-9]", " ".join(texts)):
        # A script's arguments come from the line that runs it: `python3 - "$f" <<'EOF'`.
        texts += re.findall(r"[^\n]*\b(?:python3?|node|bun|ruby|perl|deno|bash|sh|zsh)\b[^\n]*", command)
    if depth:
        for word in sorted(set().union(*map(referenced, texts)) - seen):
            texts += binding_texts(word, command, depth - 1, seen)
    return texts


@functools.lru_cache(maxsize=None)
def direct_bindings(name, command):
    n = rf"(?<![\w.$]){re.escape(name)}\b"
    texts = []
    for pattern in [rf"{n}[^=\n]*(?<![=!<>])=(?!=)([^;\n]*(?:\"\"\"[\s\S]*?\"\"\")?[^;\n]*)",  # p = …, p: T = …, (a, p) = …, NAME=…
                    rf"\bfor\s+(?:\([^)]*?{n}[^)]*\)|[^:;\n]*?{n})[^:;\n]*?\bin\b([^:;\n]*:?)",  # loops; Python's keep their `:`
                    rf"\bwith\b([^\n]*?)\bas\b[\w\s,(]*?{n}",
                    rf"{n}\s*:=([^\n)]*)",
                    rf"\blambda\b([^:\n]*{n}[^\n]*)",
                    rf"\bcase\b([^:\n]*{n}[^\n]*)",
                    rf"([^\n]*\b(?:read|mapfile|readarray)\b[^\n;|&]*{n}[^\n]*)",
                    rf"(\bprintf\b[^\n;|&]*\s-v\s*{n}[^\n;|&]*)"]:
        texts += [through_brackets(command, m.start(1), m.end(1)) for m in re.finditer(pattern, command)]
    for function in re.finditer(rf"\bdef\s+(\w+)\s*\([^)]*{n}", command):
        texts += [m.group(1) for m in re.finditer(rf"(?<!def ){function.group(1)}\(([^\n]*)", command)] or [""]
    return tuple(texts)


def referenced(text):
    """The names text reads: each `$NAME`, and each Python name outside its strings that
    isn't a call, an attribute, a keyword, or a word of a path (`~/a/decisions.tsv`)."""
    code = re.sub(r"'[^'\n]*'|\"(?:\\.|[^\"\\\n])*\"", "''", text)
    bare = re.findall(r"(?<![\w./~$-])([A-Za-z_]\w*)\b(?![(/-])", code)
    return set(re.findall(r"\$\{?([A-Za-z_]\w*)", text)) | {w for w in bare if not keyword.iskeyword(w)}


STRING = re.compile(r'"""[\s\S]*?"""' r"|'''[\s\S]*?'''|'[^'\n]*'" r'|"(?:\\.|[^"\\\n])*"')


def through_brackets(command, start, end):
    """command[start:end], run on to where its brackets close, so a binding written over
    several lines (`edits = {` and then one path per line) keeps them all."""
    depth, at = 0, start
    while at < len(command) and (at < end or depth > 0):
        string = STRING.match(command, at)
        if string:
            at = string.end()
            continue
        depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(command[at], 0)
        at += 1
    return command[start:at]


def named_docs(text, moves=False):
    """The agent docs text names; after a `cd`, also each relative name shaped like a kit doc."""
    return {t for t in TOKEN.findall(text) if agent_doc(t) or (
        moves and not os.path.isabs(os.path.expanduser(t)) and AGENT_DOC.search("/skills/" + os.path.normpath(t)))}


def variable_docs(target, command, moves=False):
    """Agent docs a target built from variables may write: itself when its literal text
    says so, else those named where the command binds its variables, else, for a variable
    it never binds, any it names."""
    if target.startswith("$segment:"):
        return named_docs(target)
    if target.count("${") > target.count("}"):
        return set()  # `${T(…` is a template's text; the shell would refuse it
    def doc(path):
        return agent_doc(path) or (moves and not os.path.isabs(os.path.expanduser(path))
                                   and AGENT_DOC.search("/skills/" + os.path.normpath(path)))
    values = substituted(target, command)
    if values:  # every variable has a plain value, so the paths are known
        return {v for v in values if doc(v)}
    if not may_be_agent_doc(target):
        return set()
    folders = [v.rpartition("/") for v in substituted(target, command, partial=True)]
    if folders and all(f and not VARIABLE.search(f) and not doc(f + "/x.md") for f, _, _ in folders):
        # Only the file name is unknown, in a folder that holds no agent doc of its own:
        # it's one when its variable's bindings name a SKILL.md, AGENTS.md, or CLAUDE.md.
        names = {t for _, _, base in folders for name in re.findall(r"\$\{?([A-Za-z_]\w*)", base)
                 for text in binding_texts(name, command) for t in named_docs(text, moves)}
        return {t for t in names if re.search(r"(?:^|/)(?:SKILL|AGENTS|CLAUDE)\.md$", t)}
    if re.search(r"(?:^|/)(?:SKILL|AGENTS|CLAUDE)\.md$|/(?:references|features|skills|shared)/", target):
        return {target}
    names = [n for n in re.findall(r"\$\{?([A-Za-z_]\w*)", target)]
    if not names:
        return set()  # a positional parameter, `$1`, is empty in a tool call
    found = set()
    for name in names:
        texts = binding_texts(name, command)
        found |= {t for text in texts for t in named_docs(text, moves)} if texts else named_docs(command, moves)
    return found


def targets():
    if tool in ("Write", "Edit", "MultiEdit"):
        path = tool_input.get("file_path", "")
        return [path] if agent_doc(path) else []
    if tool == "Bash":
        command = strip_data_heredocs(tool_input.get("command", ""))
        if RUNS_SYNC_FORMAT.search(command):
            return ["SKILL.md files (sync-format.sh)"]
        opens = [(a or c).replace("{", "${") if a or c else "$" + (b or d)
                 for a, b, c, d in OPEN_WRITE.findall(command)]
        computed = len(OPEN_ANY_WRITE.findall(command)) > len(opens)
        writes = REDIRECT.findall(command) + opens + command_targets(command)
        resolved = {t: resolve(t, command) for t in writes}
        # A resolved literal may land under a `cd` the hook can't follow, so when the
        # command can change directory, a relative one counts if it has a kit doc's shape.
        moves = CHANGES_DIR.search(command)
        found = {r for t, r in resolved.items() if not VARIABLE.search(r) and (
            agent_doc(r) or (moves and r != t and not os.path.isabs(os.path.expanduser(r))
                             and AGENT_DOC.search("/skills/" + os.path.normpath(r))))}
        for r in resolved.values():
            if VARIABLE.search(r):
                found |= variable_docs(r, command, moves)
        if computed:  # an open() path the regexes can't read, such as os.path.join(…)
            found |= named_docs(command)
        return sorted(found)
    return []


found = targets()
if not found or not os.path.isfile(transcript):
    sys.exit(0)  # nothing agent-facing, or no transcript to check
log = open(transcript, errors="replace").read()
if re.search(r'"skill":"writing-for-agents"|/writing-for-agents/SKILL\.md|Base directory for this skill: [^"\\]*/writing-for-agents', log):
    sys.exit(0)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": f"Load the writing-for-agents skill before writing {', '.join(found)}, then retry. "
                                "It applies to every SKILL.md, skill reference or feature map, the kit's shared and global docs, AGENTS.md, and CLAUDE.md.",
}}))
