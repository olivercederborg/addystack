#!/usr/bin/env python3
"""Plan check 9: a fresh user, who already has a CLAUDE.md, an AGENTS.md, and a hook of
their own in each host, installs the kit as the README says, in a temporary HOME. It runs
`npx skills add SOURCE -g -y -a claude-code codex`, then the installed tool's `init --yes`,
`install`, and `doctor`, and exits 1 naming each of these that fails:

- doctor passes;
- the old CLAUDE.md and AGENTS.md text is in ~/.config/addystack/global.md;
- the user's own hooks, and the other keys of their settings, are still there;
- ~/.claude/agents/work-verifier.md resolves to the work-verifier agent the CLI installed in
  Claude Code's verify-work folder;
- every other hook command runs a script in the installed addystack skill's hooks/, and
  each PreToolUse Bash hook, run on a plain `ls`, exits 0 and allows it.

SOURCE is what `npx skills add` installs from. By default it's this checkout's files as a
git repo of one commit, cloned through a file:// URL the way the CLI clones a GitHub repo.
Pass owner/repo to install a published kit; for a private one, set GITHUB_TOKEN, which the
CLI reads for GitHub's API and this check hands git for the clone.

`claude` and `codex` are stubs that print a version, since doctor's hosts check runs
them. Needs node with npm, git, and the npm registry (the Dagger check `fresh-install`
runs it in Linux).

Usage: scripts/check-fresh-install.py [SOURCE]
"""

import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_install", ROOT / "scripts" / "check-install.py")
check_install = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_install)

CLAUDE_TEXT = "# My Claude rules\n\n- Answer in French.\n"
CODEX_TEXT = "# My Codex rules\n\n- Run tests first.\n"
MY_HOOK = "my-hook.sh"
MY_CODEX_HOOK = "my-codex-hook.sh"


UNTRACKED = shutil.ignore_patterns(".git", "__pycache__", ".DS_Store", "node_modules", ".venv", ".review-loop",
                                   ".ruff_cache")


def tree_repo(folder, root=ROOT):
    """The kit's files in this checkout, without what git and tools leave untracked, as a
    git repo of one commit, and its file:// URL. In the workshop the kit is the paths
    maintainer/kit.txt lists, as maintainer/export_kit.py exports them, so its workshop-only
    skills stay out; in the addystack repo it's the whole tree."""
    repo = pathlib.Path(folder, "addystack")
    listing = root / "maintainer" / "kit.txt"
    if listing.is_file():
        spec = importlib.util.spec_from_file_location("export_kit", root / "maintainer" / "export_kit.py")
        export_kit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(export_kit)
        repo.mkdir(parents=True)
        for name in export_kit.listed(listing):
            source, target = root / name, repo / name
            if source.is_dir():
                shutil.copytree(source, target, ignore=UNTRACKED)
            elif source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            else:
                raise SystemExit(f"check-fresh-install: {listing} lists {name}, which {root} doesn't have")
    else:
        shutil.copytree(root, repo, ignore=UNTRACKED)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                 ["-c", "user.name=addystack", "-c", "user.email=addystack@localhost", "commit", "-q", "-m", "kit"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)
    return f"file://{repo}"


def fresh_home(home):
    """A user who has their own instruction files and one hook of their own per host."""
    files = {
        ".claude/CLAUDE.md": CLAUDE_TEXT,
        ".codex/AGENTS.md": CODEX_TEXT,
        ".claude/settings.json": json.dumps({"theme": "dark", "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": f"{home}/bin/{MY_HOOK}"}]}]}}),
        ".codex/hooks.json": json.dumps({"hooks": {"Stop": [
            {"hooks": [{"type": "command", "command": f"{home}/bin/{MY_CODEX_HOOK}"}]}]}}),
        ".gitconfig": "[user]\n\tname = Sam Doe\n\temail = sam@example.com\n",
    }
    for name, text in files.items():
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    stubs = home / "stubs"
    stubs.mkdir()
    for name in ("claude", "codex"):
        (stubs / name).write_text("#!/bin/sh\necho 1.0.0\n")
        (stubs / name).chmod(0o755)
    return stubs


def run(argv, env, home):
    done = subprocess.run(argv, env=env, cwd=home, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    print("$", " ".join(map(str, argv)), f"(exit {done.returncode})")
    return done


def commands(path):
    """Each hook command in a settings file, as (event, matcher, command)."""
    hooks = json.loads(path.read_text()).get("hooks", {})
    return [(event, group.get("matcher"), hook["command"])
            for event, groups in hooks.items() for group in groups for hook in group.get("hooks", [])]


def script(command, home):
    """The script a hook command runs: its first word, with ~ expanded."""
    first = command.split()[0]
    return pathlib.Path(str(home) + first[1:] if first.startswith("~/") else first)


def checks(home, env, kit):
    """Each problem the finished install has, and how many kit hooks it found and ran."""
    problems, found_kit, ran = [], 0, 0
    global_md = home / ".config/addystack/global.md"
    text = global_md.read_text() if global_md.is_file() else ""
    problems += [f"{global_md} lacks the old {name}"
                 for name, old in (("CLAUDE.md", CLAUDE_TEXT), ("AGENTS.md", CODEX_TEXT))
                 if old.strip().splitlines()[-1] not in text]
    agent, installed = home / ".claude/agents/work-verifier.md", home / ".claude/skills" / check_install.AGENT
    if not installed.is_file() or agent.resolve() != installed.resolve():
        problems.append(f"{agent} doesn't resolve to {installed}")
    settings, codex = home / ".claude/settings.json", home / ".codex/hooks.json"
    if json.loads(settings.read_text()).get("theme") != "dark":
        problems.append(f"{settings} lost the user's theme")
    for path, mine in ((settings, MY_HOOK), (codex, MY_CODEX_HOOK)):
        found = commands(path)
        if not any(command.endswith(f"/{mine}") for _, _, command in found):
            problems.append(f"{path} lost the user's hook {mine}")
        kits = [entry for entry in found if not entry[2].endswith(f"/{mine}")]
        found_kit += len(kits)
        if not kits:
            problems.append(f"{path} has none of the kit's hooks")
        for event, matcher, command in kits:
            path_run = script(command, home)
            if path_run.parent != kit / "hooks" or not path_run.is_file():
                problems.append(f"{path}: {command} doesn't run a script in {kit / 'hooks'}")
            elif path == settings and event == "PreToolUse" and matcher in ("Bash", None):
                payload = {"session_id": "fresh-install", "transcript_path": "", "cwd": str(home),
                           "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}
                done = subprocess.run(command, shell=True, input=json.dumps(payload), env=env, cwd=home,
                                      capture_output=True, text=True)
                ran += 1
                if done.returncode or '"deny"' in done.stdout:
                    output = (done.stdout + done.stderr).strip()[:300]
                    problems.append(f"{command} on `ls` exited {done.returncode}: {output}")
    if not ran:
        problems.append(f"{settings} has no PreToolUse Bash hook of the kit's to run")
    return problems, found_kit, ran


def main(argv):
    if len(argv) > 1 or argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as folder:
        home = pathlib.Path(folder, "home").resolve()
        home.mkdir()
        stubs = fresh_home(home)
        env = {**check_install.scratch_env(os.environ, str(home)), "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
               "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"}
        env = {key: value for key, value in env.items() if not key.startswith("ADDYSTACK_")}
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token and argv:
            # The CLI clones with git, which reads this, not GITHUB_TOKEN.
            env.update({"GIT_CONFIG_COUNT": "1",
                        "GIT_CONFIG_KEY_0": f"url.https://x-access-token:{token}@github.com/.insteadOf",
                        "GIT_CONFIG_VALUE_0": "https://github.com/"})
        source = argv[0] if argv else tree_repo(folder)
        add = run(["npm", "exec", "--yes", f"--package={check_install.CLI}", "--", "skills", "add", source,
                   "-g", "-y", "-a", "claude-code", "codex"], env, home)
        kit = home / ".agents/skills/addystack"
        if add.returncode or not (kit / "bin/addystack").is_file():
            print(add.stdout, add.stderr, f"npx skills add {source} installed no {kit}/bin/addystack", sep="\n")
            return 1
        tool = [sys.executable, str(kit / "bin/addystack")]
        for step in (["init", "--yes"], ["install"], ["doctor"]):
            done = run([*tool, *step], env, home)
            if done.returncode:
                print(done.stdout, done.stderr, f"addystack {' '.join(step)} failed", sep="\n")
                return 1
        problems, found_kit, ran = checks(home, env, kit)
    if problems:
        print("A fresh install from", source, "went wrong:", *problems, sep="\n  ")
        return 1
    print(f"a fresh user installed {source}: doctor passes, global.md keeps the old instructions, their own hooks "
          f"stay, the work-verifier agent is linked, and the kit's {found_kit} hooks run from the installed "
          f"addystack skill ({ran} run on `ls`)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
