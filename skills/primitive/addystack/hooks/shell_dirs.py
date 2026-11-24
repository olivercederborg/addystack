"""Where a shell command's working directory stands as bash runs it, piece by piece, for the
gates that check what a command reaches from where it runs (ready-gate.py, merge-gate.py).
`Walk` follows cd, pushd, and popd, and records in `unknown` why it can't tell once a change
it can't read may have run: inside a subshell, pipeline, or block, after `||`, in an `&&`
chain past its end, to where only the shell knows (a variable, ~+, a dir-stack entry, CDPATH,
a changed HOME, zsh's AUTO_CD), or an escaped `\\cd`. Its `unsure` gives a caller the same
reading for another setting, such as GH_REPO."""
import os
import re
import shutil

# Shell words that lead a command. A block opens at the first set and closes at CLOSES, and a
# cd or GH_REPO inside one may not run.
OPENS, CLOSES = {"if", "while", "until", "for", "select", "case", "{"}, {"fi", "done", "esac", "}"}
LEADS = OPENS | {"then", "else", "elif", "do", "!", "time", "builtin", "command"}  # builtin cd is cd
ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
MOVES = ("cd", "pushd", "popd")


def unreadable(word):
    """Whether a path or value holds what only the shell can expand: a variable, a glob, or a
    quoted string with spaces, which reads as ''."""
    return word == "''" or bool(re.search(r"[$*?\[{]", word))


class Walk:
    """Iterating yields each piece of `code` (split at `&&`, `||`, `;`, `|`, `&`, a new line,
    parentheses, and backticks) as (at, words, lead), once the piece's block depth and any
    cd, pushd, or popd in it are applied; `lead` indexes its command word. `cwd` is where the
    shell stands after it, `before` and `after` the separators around it, `depth` its block
    depth, and `unknown` why the directory can't be told from there on."""

    def __init__(self, code, cwd):
        self.cwd, self.previous, self.pushed = cwd, None, []
        self.unknown, self.pending = {}, {}
        self.depth, self.cases, self.tick, self.ors = 0, 0, False, False
        self.before = self.after = ""
        self.pieces = re.split(r"(&&|\|\||[;|&\n()`])", code)  # `$(…)` and backticks run their command
        self.cdpath = bool(os.environ.get("CDPATH") or re.search(r"(?<![\w$])CDPATH=", code))  # session or command
        self.home_set = bool(re.search(r"(?<![\w$])HOME=", code))  # a cd home or to ~ goes where the command says

    def resolve(self, command, args):
        """Where cd, pushd, or popd leaves the shell, or None when the gate can't read it. cd
        -P resolves symlinks first, as `..` then leaves the link's target."""
        physical = False
        while command == "cd" and args[:1] and re.fullmatch(r"-[LPe@]+", args[0]):
            for letter in args.pop(0)[1:]:
                physical = {"L": False, "P": True}.get(letter, physical)
        if command == "cd" and args == ["-"]:
            return self.previous
        if command == "popd":
            return self.pushed.pop() if self.pushed and not args else None
        path = args[0] if args else "~"
        # A dir-stack entry (+1, -2), a ~ form other than a home (~+, ~-), or a name CDPATH may
        # find elsewhere is where only the shell knows.
        if (len(args) > 1 or (command == "pushd" and not args) or unreadable(path) or path[:1] in "+-"
                or path.startswith("~") and (self.home_set or os.path.expanduser(path) == path)
                or self.cdpath and not re.match(r"(?:/|~|\.\.?(?:/|$))", path)):
            return None
        if command == "pushd":
            self.pushed.append(self.cwd)
        target = os.path.join(self.cwd, os.path.expanduser(path))
        return os.path.realpath(target) if physical else os.path.normpath(target)

    def may_not_run(self):
        """Whether the current piece may not run in this shell before what follows."""
        return bool(self.depth or self.ors or "|" in (self.before, self.after) or self.after == "&")

    def unsure(self, key, said):
        """Whether a setting the current piece changes may not hold for what follows, noting
        why in unknown; one that holds only while an && chain does goes to pending."""
        if self.may_not_run():
            self.unknown.setdefault(key, f"{said} inside a subshell, pipeline, or block, or after `||`")
            return True
        if self.before == "&&":
            self.pending[key] = f"{said} only if the command before it succeeds"
        return False

    def __iter__(self):
        pieces = self.pieces
        for at in range(0, len(pieces), 2):
            self.before, self.after = pieces[at - 1] if at else "", pieces[at + 1] if at + 1 < len(pieces) else ""
            if self.before in (";", "\n", "&", "||"):
                self.unknown, self.pending = {**self.pending, **self.unknown}, {}
                self.ors = self.before == "||"
            # Inside a case block, a pattern's ) closes no subshell; the block itself keeps depth up.
            self.depth += {"(": 0 if self.cases else 1, ")": 0 if self.cases else -1,
                           "`": -1 if self.tick else 1}.get(self.before, 0)
            self.tick ^= self.before == "`"
            words = pieces[at].split()
            lead = 0
            while lead < len(words) and (words[lead] in LEADS or ASSIGNMENT.match(words[lead])):
                self.depth, self.cases = self.depth + (words[lead] in OPENS), self.cases + (words[lead] == "case")
                lead += 1
            self.depth -= bool(words[:1] and words[0] in CLOSES)
            self.cases -= words[:1] == ["esac"]
            self.follow(words, lead)
            yield at, words, lead

    def follow(self, words, lead):
        command = words[lead] if lead < len(words) else None
        if command and command.lstrip("\\") in MOVES and command not in MOVES:
            self.unknown.setdefault("dir", f"runs `{' '.join(words[lead:])}`, an escaped `{command[1:]}` it can't read")
        elif command and command not in MOVES and not shutil.which(command) and os.path.isdir(
                os.path.join(self.cwd, os.path.expanduser(command))):
            self.unknown.setdefault("dir", f"names the directory `{command}`, which zsh's AUTO_CD enters")
        elif command in MOVES:
            said = f"runs `{command}`"
            # A cd that may not run matters only when it would move the shell.
            if self.may_not_run() and command == "cd" and self.resolve(command, words[lead + 1:]) == self.cwd:
                return
            if self.unsure("dir", said):
                return
            target = self.resolve(command, words[lead + 1:])
            if target is None:
                self.unknown.setdefault("dir", f"runs `{' '.join(words[lead:])}`, whose directory it can't read")
            else:
                self.previous, self.cwd = self.cwd, target
