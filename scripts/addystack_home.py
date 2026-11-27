"""A scratch HOME for tests that run bin/addystack install, init, update, and doctor: every
path addystack, the skills CLI, Claude Code, and Codex read points into it, PATH starts
with a folder of stub commands, `claude` and `codex` among them, and both hosts' skill
folders link each of the kit's skills, so no test reads or writes the real home."""
from __future__ import annotations

import json, os, pathlib, subprocess, sys, tempfile, unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
# The addystack skill's folder, which holds the tool.
KIT = REPO / "skills" / "primitive" / "addystack"
BIN = KIT / "bin" / "addystack"
# Each skill's folder in the checkout, skills/<layer>/<skill>, by name.
SKILLS = {skill.parent.name: skill.parent for skill in sorted(REPO.glob("skills/*/*/SKILL.md"))}


class Home(unittest.TestCase):
    # Link each skill in both hosts' skill folders to the kit's, as a maintainer's checkout
    # is, so doctor's skill check passes; a test of that check turns it off.
    linked = True

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = pathlib.Path(folder.name).resolve()
        self.stubs = self.home / "stubs"
        self.stubs.mkdir()
        for name in ("claude", "codex"):
            self.stub(name, "echo 1.2.3")
        # launchctl logs each call and keeps a loaded flag; the guard runs it by absolute path
        # (ADDYSTACK_LAUNCHCTL), so no test touches the real launchd.
        self.launchctl_log = self.home / "launchctl.log"
        loaded = self.home / "launchctl.loaded"
        launchctl = str(self.stub(
            "launchctl", f'echo "$*" >> {self.launchctl_log}\n'
            f'case $1 in bootstrap) touch {loaded} ;; bootout) rm -f {loaded} ;; '
            f'print) test -f {loaded} ;; esac'))
        # ZDOTDIR would point zsh, and the guard's .zshenv write, outside the scratch HOME.
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("ADDYSTACK_") and key != "ZDOTDIR"}
        self.env.update({"HOME": str(self.home), "XDG_STATE_HOME": str(self.home / ".local/state"),
                         "XDG_CONFIG_HOME": str(self.home / ".config"),
                         "CLAUDE_CONFIG_DIR": str(self.home / ".claude"), "CODEX_HOME": str(self.home / ".codex"),
                         "PATH": f"{self.stubs}{os.pathsep}{os.environ.get('PATH', '')}",
                         "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"),
                         "GIT_CONFIG_NOSYSTEM": "1"})
        self.env["ADDYSTACK_LAUNCHCTL"] = launchctl
        self.config = self.home / ".config/addystack/addystack.jsonc"
        self.state = self.home / ".local/state/addystack"
        self.claude_md = self.home / ".claude/CLAUDE.md"
        self.codex_md = self.home / ".codex/AGENTS.md"
        self.settings = self.home / ".claude/settings.json"
        self.codex_hooks = self.home / ".codex/hooks.json"
        if self.linked:
            self.link_skills()

    def link_skills(self, names=None):
        """Links each named skill, or every one, into both hosts' skill folders."""
        for folder in (".claude/skills", ".agents/skills"):
            (self.home / folder).mkdir(parents=True, exist_ok=True)
            for name in SKILLS if names is None else names:
                (self.home / folder / name).symlink_to(SKILLS[name])

    def stub(self, name, body):
        """A command on PATH that runs this shell body."""
        path = self.stubs / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)
        return path

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def cli(self, *args, bin_=BIN, cwd=None):
        return subprocess.run([sys.executable, str(bin_), *args], capture_output=True, text=True, env=self.env,
                              cwd=cwd or self.home, stdin=subprocess.DEVNULL)

    def ok(self, *args, **kwargs):
        result = self.cli(*args, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def json(self, path):
        return json.loads(path.read_text())

    def commands(self, path):
        """Every hook command in a settings file, by event."""
        return {event: [hook["command"] for group in groups for hook in group["hooks"]]
                for event, groups in self.json(path)["hooks"].items()}

    def snapshot(self):
        """Every file under HOME but the stubs, with its bytes, and every link with its target."""
        found = {}
        for path in sorted(self.home.rglob("*")):
            if self.stubs in path.parents or path == self.stubs:
                continue
            if path.is_symlink():
                found[path] = ("link", os.readlink(path))
            elif path.is_file():
                found[path] = ("file", path.read_bytes())
        return found
