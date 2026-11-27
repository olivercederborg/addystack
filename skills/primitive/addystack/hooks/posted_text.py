"""Which text a tool call is about to post, and where, for named-links-check.py. Owns every
rule about it: the routes (gh pr create, edit, and comment in Bash; T3's pull_request_create
and pull_request_update; Linear's save_issue, save_comment, and save_project, directly or
through Executor's `call`), gh's body flags, a heredoc the same command writes to its body
file, a body file's bounds, and Linear's fields and patch operations. Titles and relation
fields are never posted text here.

A body it can't place, such as stdin, a FIFO, a device, an oversized or unreadable file, or
a file the command writes some other way than a heredoc, yields no Post, so the check
passes it.

It reads a command as the gates do (shell_dirs): heredoc bodies and quoted strings are
data, kept aside by placeholder so the words and pieces around them read as the shell splits
them, and `Walk` says where each piece runs, which places a relative --body-file."""
import os, re, stat
from typing import Callable, List, NamedTuple, Optional, Tuple

from shell_dirs import HEREDOC, QUOTED, Walk

# The tool names whose calls may post text, as one regex both runtimes' manifest entries
# carry; test_named_links checks the manifest against it.
MATCHER = ("Bash|mcp__t3-code__pull_request_(create|update)"
           "|mcp__.*[Ll]inear.*__save_(issue|comment|project)|mcp__executor-.+__call")


class Post(NamedTuple):
    target: str  # where it posts, as the call names it: "gh pr comment 12", "save_issue DEV-4"
    text: str    # the Markdown it posts there


# A body file past this is no PR body or comment gh would send (GitHub caps a body at 65,536
# characters), so it isn't read.
_MOST_BYTES = 512 * 1024
# The gh options that take a value, from gh 2.103's --help for pr create, edit, and comment,
# so a value is never read as a flag or an argument; short forms mean the same in all three.
_VALUED = {"-R", "--repo", "-t", "--title", "-b", "--body", "-F", "--body-file", "-B", "--base", "-H", "--head",
           "-a", "--assignee", "-l", "--label", "-m", "--milestone", "-p", "--project", "-r", "--reviewer",
           "-T", "--template", "--recover",
           *(f"--{change}-{what}" for change in ("add", "remove") for what in ("assignee", "label", "project", "reviewer"))}
_SUBCOMMANDS = {"create", "new", "edit", "comment"}
# Placeholders for a heredoc body (H) and a quoted string (Q): no character Walk splits on.
_HOLD = re.compile(r"\x01([HQ])(\d+)\x01")
# A write to a file: `> f`, `>| f`, `1>f`, or an append, `>> f`, whose result it can't place.
_WRITE = re.compile(r"(?<![<>&])\d*(>>|>\|?)\s*([^\s<>&]+)")
# A quoted command substitution that only prints a heredoc, gh's usual --body form.
_CAT = re.compile(r"\$\(\s*cat\s*<<\x01H(\d+)\x01\s*\)")
# What the shell expands in a double-quoted string, an unquoted word, or an unquoted
# heredoc: a $ or a backtick it doesn't escape.
_EXPANDS = re.compile(r"(?<!\\)[$`]")
_COMMENT = re.compile(r"(?:(?<=[;&|(`])|(?<=(?<!\\)\s)|^)#[^\n]*", re.M)


def posts(tool_name: object, tool_input: object, cwd: Optional[str]) -> List[Post]:
    """Each text this call would post that can be placed, in the order the call posts them;
    [] for any other call or a shape it doesn't expect."""
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return []
    for pattern, read in _ROUTES:
        found = re.fullmatch(pattern, tool_name)
        if found:
            return read(found, tool_input, cwd)
    return []


def _bash(found: "re.Match", tool_input: dict, cwd: Optional[str]) -> List[Post]:
    """One Post per gh pr create, new, edit, or comment in the command that has a body."""
    command = tool_input.get("command")
    if not isinstance(command, str) or not re.search(r"\bgh\b", command):
        return []
    # A heredoc's body, None when the shell expands it (an unquoted delimiter and a $ or `),
    # so what it posts can't be known here.
    bodies: List[Optional[str]] = []
    quoted: List[Tuple[str, bool]] = []  # each quoted string's text, and whether the shell expands it

    def hold_heredoc(match: "re.Match") -> str:
        whole, delimiter = match.group(0), match.group(1)
        opener = re.match(r"<<(-?)\s*(['\"]?)\w+['\"]?", whole)
        line_end = whole.index("\n")
        body = whole[line_end + 1:-len(delimiter) - 1]
        if opener.group(1):  # <<- drops each line's leading tabs
            body = re.sub(r"^\t+", "", body, flags=re.M)
        bodies.append(None if not opener.group(2) and _EXPANDS.search(body) else body)
        return f"<<\x01H{len(bodies) - 1}\x01{whole[opener.end():line_end]}\n"

    def hold_quoted(match: "re.Match") -> str:
        text = match.group(0)
        if text[0] == "'":
            quoted.append((text[1:-1], False))
        else:
            quoted.append((re.sub(r'\\([\\"$`])', r"\1", text[1:-1]), bool(_EXPANDS.search(text[1:-1]))))
        return f"\x01Q{len(quoted) - 1}\x01"

    code = _COMMENT.sub("", QUOTED.sub(hold_quoted, HEREDOC.sub(hold_heredoc, command)))

    def value(word: str) -> Optional[str]:
        """A word's text with its quoted strings and heredoc bodies put back; a quoted
        `"$(cat <<EOF … EOF)"` is the heredoc's body. None when the shell expands any of
        it, such as `"see $LINK"`."""
        unknown = []

        def put_back(held: "re.Match") -> str:
            if held.group(1) == "H":
                body = bodies[int(held.group(2))]
            else:
                text, expands = quoted[int(held.group(2))]
                cat = _CAT.fullmatch(text)
                if not cat:
                    unknown.extend([True] if expands else [])
                    return _HOLD.sub(put_back, text)
                body = bodies[int(cat.group(1))]
            unknown.extend([True] if body is None else [])
            return body or ""
        found = _HOLD.sub(put_back, word)
        return None if unknown or _EXPANDS.search(_HOLD.sub("", word)) else found

    def place(word: str, at: Optional[str]) -> Optional[str]:
        """The absolute path a word names when run from `at`, or None."""
        path = value(word)
        if not path or re.search(r"[$*?\[{`]", path):
            return None
        path = os.path.expanduser(path)
        if os.path.isabs(path):
            return os.path.normpath(path)
        return os.path.normpath(os.path.join(at, path)) if at else None

    walk = Walk(code, cwd or "")
    pieces = []  # (words, lead, the piece's text, its cwd or None)
    for at, words, lead in walk:
        known = bool(cwd) and "dir" not in walk.unknown
        pieces.append((words, lead, walk.pieces[at], walk.cwd if known else None))

    found_posts = []
    for index, (words, lead, text, at) in enumerate(pieces):
        if words[lead:lead + 2] != ["gh", "pr"] or len(words) < lead + 3 or words[lead + 2] not in _SUBCOMMANDS:
            continue
        flags, positional = _options(words[lead + 3:])
        body_flags = [(name, given) for name, given in flags if name in ("-b", "--body", "-F", "--body-file")]
        if not body_flags:
            continue
        name, given = body_flags[-1]  # pflag keeps a string flag's last value
        if given is None:
            continue
        if name in ("-b", "--body"):
            body = value(given)
        elif value(given) == "-":  # stdin: only a heredoc on this gh command places it
            held = re.findall(r"<<\x01H(\d+)\x01", text)
            body = bodies[int(held[-1])] if held else None
        else:
            body = _file_body(place(given, at), index, pieces, bodies, place)
        if body is None:
            continue
        repo = [given for flag, given in flags if flag in ("-R", "--repo")][-1:]
        target = " ".join(["gh", "pr", words[lead + 2], *[value(word) or "" for word in positional[:1] + repo]])
        found_posts.append(Post(target, body))
    return found_posts


def _file_body(path: Optional[str], index: int, pieces: list, bodies: List[str],
               place: Callable[[str, Optional[str]], Optional[str]]) -> Optional[str]:
    """The text a --body-file at `path` holds when the gh command at `index` reads it: the
    heredoc a `cat > path <<EOF` in the same command wrote last before it, else the file on
    disk. None when the command names the path any other way before it, so it may write it;
    a piece after the gh command, such as `&& rm body.md`, runs once gh has read it."""
    if path is None:
        return None
    written: Optional[str] = None
    wrote = False
    for words, lead, text, at in pieces[:index]:
        writes = [(mode, place(target, at)) for mode, target in _WRITE.findall(text)]
        named = [place(re.sub(r"^\d*[<>|]+", "", word), at) for word in words]
        if path not in named and path not in [target for _, target in writes]:
            continue
        held = re.findall(r"<<\x01H(\d+)\x01", text)
        if (words[lead:lead + 1] == ["cat"] and held
                and [target for mode, target in writes if mode != ">>"] == [path] and len(writes) == 1):
            written, wrote = bodies[int(held[-1])], True
        else:
            return None
    return written if wrote else _file(path)


def _file(path: str) -> Optional[str]:
    """A regular file's text, at most _MOST_BYTES, else None. It opens without blocking, so
    a FIFO's writer is never awaited."""
    try:
        handle = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        status = os.fstat(handle)
        if not stat.S_ISREG(status.st_mode) or status.st_size > _MOST_BYTES:
            return None
        with os.fdopen(handle, "rb") as stream:
            handle = None
            return stream.read(_MOST_BYTES + 1).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        if handle is not None:
            os.close(handle)


def _options(args: List[str]) -> Tuple[List[Tuple[str, Optional[str]]], List[str]]:
    """gh's flags in args as (name, value) pairs, value None for a bare switch, and its
    positional arguments, read as gh's pflag does: `-bx` and `-b x` give -b its value, a
    valued flag takes the next word even when it starts with -, and `--` ends the flags."""
    pairs: List[Tuple[str, Optional[str]]] = []
    positional: List[str] = []
    at = 0
    while at < len(args):
        arg, at = args[at], at + 1
        if arg == "--":
            return pairs, positional + args[at:]
        if arg.startswith("--"):
            name, equals, given = arg.partition("=")
            if not equals and name in _VALUED and at < len(args):
                given, at, equals = args[at], at + 1, "="
            pairs.append((name, given if equals else None))
        elif arg.startswith("-") and len(arg) > 1:
            letters = arg[1:]
            while letters:
                name, letters = "-" + letters[0], letters[1:]
                if letters.startswith("="):
                    pairs.append((name, letters[1:]))
                    break
                if name in _VALUED:
                    if not letters and at < len(args):
                        letters, at = args[at], at + 1
                    pairs.append((name, letters))
                    break
                pairs.append((name, None))
        else:
            positional.append(arg)
    return pairs, positional


def _t3(found: "re.Match", tool_input: dict, cwd: Optional[str]) -> List[Post]:
    """The body of a T3 pull_request_create or pull_request_update."""
    body = tool_input.get("body")
    if not isinstance(body, str):
        return []
    number = tool_input.get("number")
    return [Post(" ".join(["pull_request_" + found.group(1), *([str(number)] if number is not None else [])]), body)]


def _linear(kind: str, fields: object) -> List[Post]:
    """A Linear save_issue, save_comment, or save_project's posted text as one Post: its
    description or body, and each patch op's inserted text. Titles, a patch's anchor and
    old_string, and relation fields such as relatedTo, blocks, and parentId cite ids on
    purpose, so they aren't read."""
    if not isinstance(fields, dict):
        return []
    parts = [fields[name] for name in ("description", "body") if isinstance(fields.get(name), str)]
    patch = fields.get("patch")
    for op in patch if isinstance(patch, list) else []:
        if isinstance(op, dict):
            parts += [op[name] for name in ("new_string", "text") if isinstance(op.get(name), str)]
    if not parts:
        return []
    # Where it posts: the item it saves, or a new one's parent, team, or name, so a denial
    # on one never lets the same text through on another.
    where = [str(fields[key]) for key in _WHERE if isinstance(fields.get(key), (str, int))]
    if kind != "comment" and "id" not in fields:
        where = ["new", *where]
    return [Post(" ".join([f"save_{kind}", *where]), "\n\n".join(parts))]


# The fields that say which item a Linear save writes, or where a new one goes.
_WHERE = ("id", "issueId", "projectId", "documentId", "initiativeId", "projectUpdateId", "parentId", "team", "name")


def _direct(found: "re.Match", tool_input: dict, cwd: Optional[str]) -> List[Post]:
    return _linear(found.group(1), tool_input)


# An Executor call's path to a Linear save: tools["linear-mcp"].save_issue or
# tools.linear-mcp.save_issue, any app slug that names Linear.
_EXECUTOR_PATH = re.compile(r"tools\s*(?:\[\s*[\"']([^\"']+)[\"']\s*\]|\.([\w-]+))\s*\.\s*save_(issue|comment|project)")


def _executor(found: "re.Match", tool_input: dict, cwd: Optional[str]) -> List[Post]:
    """Executor's `call`: `calls` is one {path, input} or a list of them, and a Linear
    save's fields sit in input["input"], beside the accountId."""
    calls = tool_input.get("calls")
    found_posts: List[Post] = []
    for call in calls if isinstance(calls, list) else [calls]:
        if not isinstance(call, dict) or not isinstance(call.get("path"), str):
            continue
        path = _EXECUTOR_PATH.fullmatch(call["path"].strip())
        given = call.get("input")
        if path and "linear" in (path.group(1) or path.group(2)).lower() and isinstance(given, dict):
            found_posts += _linear(path.group(3), given.get("input"))
    return found_posts


_ROUTES: List[Tuple[str, Callable[["re.Match", dict, Optional[str]], List[Post]]]] = [
    ("Bash", _bash),
    (r"mcp__t3-code__pull_request_(create|update)", _t3),
    (r"mcp__.*[Ll]inear.*__save_(issue|comment|project)", _direct),
    (r"mcp__executor-.+__call", _executor),
]
