#!/usr/bin/env python3
"""Plan check 11 (D17): installs every skill in this kit with the skills CLI, the way a user
runs `npx skills add <repo> -g`, into a temporary HOME, and exits 1 naming each file a
skill's checkout folder has that its installed copy lacks or holds with other bytes, or
when verify-work's work-verifier agent (AGENT) isn't installed. The CLI skips a symlink
that leaves the skill's folder, so a link shows up here as lost.

Needs node with npm and the npm registry (the Dagger check `install` runs it in Linux).

Usage: scripts/check-install.py
"""

import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = "skills@1.7.6"
# What a checkout holds that git doesn't track, so an install never carries it.
UNTRACKED = {"__pycache__", ".DS_Store"}
# The work-verifier agent, in a skill folder so the CLI installs it, which `addystack
# install` links into ~/.claude/agents/. Named here so moving it out of every skill fails.
AGENT = "verify-work/agents/work-verifier.md"


def files(tree):
    """Each path under tree, relative, outside UNTRACKED, as {path: is_symlink}."""
    found = {}
    for folder, dirs, names in os.walk(tree):
        dirs[:] = [d for d in dirs if d not in UNTRACKED]
        for name in [*names, *(d for d in dirs if os.path.islink(os.path.join(folder, d)))]:
            if name not in UNTRACKED:
                path = os.path.join(folder, name)
                found[os.path.relpath(path, tree)] = os.path.islink(path)
    return found


def lost(checkout, installed):
    """Each file of the checkout's skill folder its installed copy lacks, holds with other
    bytes, or that is a symlink in either."""
    have, problems = files(installed), []
    for path, link in sorted(files(checkout).items()):
        if link:
            problems.append(f"{path} (a symlink in the checkout)")
        elif path not in have:
            problems.append(f"{path} (missing)")
        elif have[path]:
            problems.append(f"{path} (a symlink in the install)")
        elif (checkout / path).read_bytes() != (installed / path).read_bytes():
            problems.append(f"{path} (differs)")
    return problems


def scratch_env(environ, home):
    """environ with HOME and every variable the CLI reads for an install or lock path
    (CLAUDE_CONFIG_DIR, CODEX_HOME, XDG_STATE_HOME) pointed into the scratch home, so a
    caller's own overrides can't send the install to their real skills."""
    return {**environ, "HOME": home, "DO_NOT_TRACK": "1", "DISABLE_TELEMETRY": "1",
            "npm_config_update_notifier": "false", "CLAUDE_CONFIG_DIR": f"{home}/.claude",
            "CODEX_HOME": f"{home}/.codex", "XDG_STATE_HOME": f"{home}/.local/state"}


def main():
    skills = sorted(path.parent for path in ROOT.glob("skills/*/*/SKILL.md"))
    with tempfile.TemporaryDirectory() as home:
        env = scratch_env(os.environ, home)
        # An agent's environment makes the CLI install without prompts; -y covers the rest.
        # `npm exec` is `npx`, which the Dagger toolbox doesn't link.
        install = subprocess.run(["npm", "exec", "--yes", f"--package={CLI}", "--", "skills", "add", str(ROOT),
                                  "--skill", "*", "-g", "-y", "-a", "claude-code"],
                                 env=env, cwd=home, capture_output=True, text=True)
        if install.returncode:
            print(install.stdout, install.stderr, sep="\n")
            return 1
        problems = []
        for skill in skills:
            installed = pathlib.Path(home, ".claude/skills", skill.name).resolve()
            if not installed.is_dir():
                problems.append(f"{skill.name}: not installed")
                continue
            problems += [f"{skill.name}/{path}" for path in lost(skill, installed)]
        if not pathlib.Path(home, ".claude/skills", AGENT).is_file():
            problems.append(f"{AGENT}: not installed, so addystack install has no work-verifier agent to link")
    if problems:
        print(f"npx {CLI} add lost files from {len(skills)} skills:", *problems, sep="\n  ")
        return 1
    print(f"npx {CLI} add installed every file of {len(skills)} skills")
    return 0


if __name__ == "__main__":
    sys.exit(main())
