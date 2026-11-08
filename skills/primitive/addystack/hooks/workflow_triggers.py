"""Whether a repo's GitHub Actions workflows would run for a pull request, for merge-gate.py.
A PR whose every workflow skips it by its branch or path filters gets no checks, so the gate
treats it like a PR in a repo with no CI. Stdlib only: /usr/bin/python3 and a bare Linux host have no
PyYAML. So this reads only the top-level `on:` key, strictly: a scalar, a flow list, or a
block mapping whose pull_request and pull_request_target hold `branches`, `branches-ignore`,
`paths`, `paths-ignore`, and `types` as flow or block lists of plain or quoted scalars.
Anything else there, such as an anchor, a tab, or a multi-line scalar, raises Unknown, and
an unknown workflow counts as running. Filter globs follow GitHub's filter pattern cheat
sheet (docs.github.com, Workflow syntax); a pattern outside it is Unknown too."""
import re, subprocess

# GitHub's docs give 3,000 files as the point where path filters stop being reliable; a
# smaller cap keeps big diffs counted as running.
MAX_FILES = 300
PR_EVENTS = ("pull_request", "pull_request_target")
FILTERS = ("branches", "branches-ignore", "paths", "paths-ignore", "types")


class Unknown(Exception):
    """A workflow, or a filter in one, this reader can't follow. It counts as running."""


def skipped(cwd, base_branch, base_oid, head_oid, merge_oid, default_oid):
    """Whether no workflow at any revision GitHub runs one from runs for the PR from base_oid
    to head_oid: pull_request runs the merge commit's workflows and pull_request_target the
    default branch's (docs.github.com, Events that trigger workflows). Base and head are read
    too, since each revision read can only add a run. Any git failure, or a workflow it can't
    read, raises; the caller counts that as CI."""
    files = _git(cwd, "diff", "-z", "--name-only", "--no-renames", f"{base_oid}...{head_oid}")
    files = [name for name in files.split("\0") if name]
    texts = [text for oid in (base_oid, head_oid, merge_oid, default_oid) for text in _workflows(cwd, oid)]
    return bool(texts) and not any(runs(text, base_branch, files) for text in texts)


def _git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=20)
    if result.returncode:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.decode(errors='replace').strip()[:200]}")
    return result.stdout.decode()


def _workflows(cwd, oid):
    # GitHub runs only the files directly in .github/workflows.
    for entry in filter(None, _git(cwd, "ls-tree", "-z", oid, "--", ".github/workflows/").split("\0")):
        meta, path = entry.split("\t", 1)
        mode, kind, blob = meta.split()
        if not path.lower().endswith((".yml", ".yaml")):
            continue
        if kind != "blob" or mode not in ("100644", "100755"):
            raise Unknown(f"{path} is a {kind} with mode {mode}")
        yield _git(cwd, "cat-file", "blob", blob)


def runs(text, base_branch, files):
    """Whether this workflow runs for a PR into base_branch that changes files."""
    try:
        return any(_trigger_runs(filters, base_branch, files) for filters in triggers(text))
    except Unknown:
        return True


def _trigger_runs(filters, base_branch, files):
    if "branches" in filters and not _included(filters["branches"], base_branch):
        return False
    if "branches-ignore" in filters and _ignored(filters["branches-ignore"], base_branch):
        return False
    if "paths" not in filters and "paths-ignore" not in filters:
        return True
    if not files or len(files) > MAX_FILES:
        return True
    if "paths" in filters:
        return any(_included(filters["paths"], name) for name in files)
    return not all(_ignored(filters["paths-ignore"], name) for name in files)


def _included(patterns, name):
    """Patterns in order, a leading `!` negating, the last match winning."""
    compiled = [(pattern.startswith("!"), glob(pattern[1:] if pattern.startswith("!") else pattern))
                for pattern in patterns]
    result = False
    for negated, regex in compiled:
        if regex.fullmatch(name):
            result = not negated
    return result


def _ignored(patterns, name):
    if any(pattern.startswith("!") for pattern in patterns):
        raise Unknown("a `!` pattern in an -ignore filter")
    return any(regex.fullmatch(name) for regex in map(glob, patterns))


def glob(pattern):
    """GitHub's filter glob as a regex: `*` any characters but `/`, `**` any characters, `?`
    zero or one and `+` one or more of the preceding character, `[...]` one listed
    alphanumeric character or range. `**/` also matches no directory, as `**/README.md`
    matches a root README.md."""
    if not pattern or pattern.startswith(("/", "./")) or pattern.endswith("/"):
        raise Unknown(f"pattern {pattern!r}")
    out, i, quantifiable = [], 0, False
    while i < len(pattern):
        char = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i, quantifiable = i + 3, False
        elif pattern.startswith("**", i):
            out.append(".*")
            i, quantifiable = i + 2, False
        elif char == "*":
            out.append("[^/]*")
            i, quantifiable = i + 1, False
        elif char in "?+":
            if not quantifiable:
                raise Unknown(f"pattern {pattern!r}: {char} with nothing to repeat")
            out.append(char)
            i, quantifiable = i + 1, False
        elif char == "[":
            end = pattern.find("]", i)
            body = pattern[i + 1:end]
            if end < 0 or not re.fullmatch(r"(?:[a-z](?:-[a-z])?|[A-Z](?:-[A-Z])?|[0-9](?:-[0-9])?)+", body):
                raise Unknown(f"pattern {pattern!r}: class")
            out.append(f"[{body}]")
            i, quantifiable = end + 1, True
        elif char in "\\{}]":
            raise Unknown(f"pattern {pattern!r}: {char}")
        else:
            out.append(re.escape(char))
            i, quantifiable = i + 1, True
    try:
        return re.compile("".join(out))
    except re.error as error:  # such as a class range that runs backwards
        raise Unknown(f"pattern {pattern!r}: {error}") from None


def triggers(text):
    """The filters of each pull_request or pull_request_target trigger in a workflow's `on:`,
    an empty dict for one without filters, or [] when it has neither."""
    section, inline = _on_section(text)
    if inline:
        if section:
            raise Unknown("`on:` has a value and lines under it")
        if inline.startswith("{") or inline in ("~", "null"):
            raise Unknown(f"`on:` is {inline}")
        events = _flow_list(inline) if inline.startswith("[") else [_scalar(inline)]
        return [{} for event in events if event in PR_EVENTS]
    if not section:
        raise Unknown("`on:` is empty")
    indent = section[0][0]
    if indent == 0:
        raise Unknown("`on:` content at column 0")
    if _is_item(section[0][1]):
        return [{} for event in _block_list(section, indent) if event in PR_EVENTS]
    found = []
    for event, value, children in _block_map(section, indent):
        if event in PR_EVENTS:
            found.append(_filters(value, children))
    return found


def _filters(value, children):
    if value not in (None, "{}"):
        raise Unknown(f"pull_request value {value!r}")
    if value == "{}" and children:
        raise Unknown("pull_request has a value and lines under it")
    if not children:
        return {}
    filters = {}
    for key, value, items in _block_map(children, children[0][0]):
        if key not in FILTERS:
            raise Unknown(f"pull_request key {key!r}")
        if value is not None:
            if items or not value.startswith("["):
                raise Unknown(f"{key} value {value!r}")
            filters[key] = _flow_list(value)
        elif items:
            filters[key] = _block_list(items, items[0][0])
        else:
            raise Unknown(f"{key} is empty")
        if not filters[key]:
            raise Unknown(f"{key} is an empty list")
    if {"branches", "branches-ignore"} <= filters.keys() or {"paths", "paths-ignore"} <= filters.keys():
        raise Unknown("a filter and its -ignore on one event")
    return filters


ON_LINE = re.compile(r"""(?:on|"on"|'on'|true)[ ]*:(?:[ ](.*))?""")
TOP_KEY = re.compile(r"""(?:[A-Za-z_][\w-]*|"[^"\\]*"|'[^']*')[ ]*:(?:[ ].*)?""")


def _on_section(text):
    """The `on:` key's inline value and the (indent, content) lines under it, comments and
    blank lines dropped. Outside `on:`, only where each top-level key starts matters."""
    lines = text.lstrip("\ufeff").splitlines()
    start = None
    for number, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#") or line[0] in " -":
            continue  # nested content, or a block list at the top-level key's indent
        if line.rstrip() == "---" and not any(_strip(earlier) for earlier in lines[:number]):
            continue
        if not TOP_KEY.fullmatch(line.rstrip()):
            raise Unknown(f"top-level line {line[:40]!r}")
        if ON_LINE.fullmatch(line.rstrip()):
            if start is not None:
                raise Unknown("two `on:` keys")
            start = number
    if start is None:
        raise Unknown("no `on:` key")
    inline = _strip(ON_LINE.fullmatch(lines[start].rstrip()).group(1) or "")
    if "\t" in lines[start]:
        raise Unknown("a tab in `on:`")
    section = []
    for line in lines[start + 1:]:
        content = _strip(line)
        if content and line[0] not in " \t-":
            break  # the next top-level key
        if "\t" in line:
            raise Unknown("a tab in `on:`")
        if content:
            section.append((len(line) - len(line.lstrip(" ")), content))
    return section, inline


def _strip(line):
    """line without its comment or surrounding spaces; a `#` starts one after a space."""
    quote = None
    for i, char in enumerate(line):
        if quote:
            quote = None if char == quote else quote
        elif char in "'\"" and (i == 0 or line[i - 1] in " [,"):
            quote = char
        elif char == "#" and (i == 0 or line[i - 1] == " "):
            return line[:i].strip()
    return line.strip()


def _is_item(content):
    return content == "-" or content.startswith("- ")


KEY = re.compile(r"""([A-Za-z_][\w-]*|"[^"\\]*"|'[^']*')[ ]*:(?:[ ]+(.*))?""")


def _block_map(lines, indent):
    """Each (key, inline value or None, child lines) of a block mapping at indent. A key's
    block list may sit at the key's own indent."""
    entries, seen = [], set()
    for line_indent, content in lines:
        if line_indent > indent or (line_indent == indent and _is_item(content) and entries):
            if entries[-1][1] is not None and line_indent == indent:
                raise Unknown(f"list item {content!r} under a key with a value")
            entries[-1][2].append((line_indent, content))
            continue
        match = KEY.fullmatch(content) if line_indent == indent else None
        if not match:
            raise Unknown(f"line {content!r} at indent {line_indent}")
        key = _scalar(match.group(1))
        if key in seen:
            raise Unknown(f"key {key!r} twice")
        seen.add(key)
        value = match.group(2)
        entries.append((key, None if value in (None, "", "~", "null") else value, []))
    return entries


def _block_list(lines, indent):
    items = []
    for line_indent, content in lines:
        if line_indent != indent or not _is_item(content):
            raise Unknown(f"list line {content!r} at indent {line_indent}")
        items.append(_scalar(content[1:].strip()))
    return items


def _flow_list(value):
    if not (value.startswith("[") and value.endswith("]")):
        raise Unknown(f"flow list {value!r}")
    body = value[1:-1].strip()
    if not body:
        return []
    items, item, quote = [], "", None
    for char in body:
        if quote:
            quote = None if char == quote else quote
        elif char in "'\"" and not item.strip():
            quote = char
        elif char == ",":
            items.append(item)
            item = ""
            continue
        item += char
    return [_scalar(item.strip(), flow=True) for item in items + [item]]


def _scalar(value, flow=False):
    """A single-line plain or quoted scalar as its string."""
    if len(value) >= 2 and value[0] == value[-1] == '"' and not re.search(r'[\\"]', value[1:-1]):
        return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == "'" and "'" not in value[1:-1].replace("''", ""):
        return value[1:-1].replace("''", "'")
    # A plain scalar can't open with an indicator, though `-`, `?`, or `:` may lead a word.
    opener = value[:1] in "-?:" and value[1:2] not in ("", " ")
    if (not value or (value[0] in "-?:,[]{}#&*!|>'\"%@`" and not opener) or ": " in value
            or value.endswith(":") or (flow and re.search(r"[\[\]{},]", value))):
        raise Unknown(f"scalar {value!r}")
    return value
