#!/usr/bin/env python3
"""SessionStart: keep the skills checkout that Claude Code's skill folder links into on
`origin/main`, since merged skill changes don't load until it is. Added after a checkout
sat on a merged branch, 29 commits behind, while sessions loaded its stale skills (Oct
2026). Reads only local refs, so it needs no network and stays fast.

On a clean `main` that's behind, it fast-forwards and says nothing. Otherwise it warns,
and on another branch only once a day per branch: in the month to Oct 29, 2026 it warned
in 179 sessions, one branch for 9 days. Also warns when this machine's installed hooks
drift from manifest.json (hook_parity.py), since a second machine once ran a week-old hook set,
5 hooks short, unnoticed.

Then it reruns `addystack build` when the built files no longer match the kit and the
user's config, by build's own test (lib/doctor.py's `_stale`), so a pull, a branch switch,
this fast-forward, or a config edit can't leave sessions on old instructions: Nov 11 to 13,
2026, the Mac loaded a principles index two merges old in 71 sessions. Claude Code and Codex
read their instruction files before SessionStart hooks run, so the rebuild reaches the next
session, and this one is told to read the rebuilt files. It builds only the kit resolved.json
names when that's its own, and only on a clean `main` or a kit no repo tracks: a dirty
`main` gets a warning instead, and another branch the warning above."""
import datetime, json, os, pathlib, shutil, subprocess, sys, time

import hook_parity

json.load(sys.stdin)
link = (pathlib.Path(os.environ["SKILLS_LINK"]).expanduser() if os.environ.get("SKILLS_LINK")
        else hook_parity.config.claude_home() / "skills" / "reply-shape")


def git(*args):
    result = subprocess.run(["git", "-C", str(link.resolve().parent), *args],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def warned_today(branch):
    """True when this branch was already warned about today; records it otherwise."""
    state = pathlib.Path(git("rev-parse", "--absolute-git-dir"), "skills-checkout-warned")
    today = str(datetime.date.today())
    entry = f"{today} {branch}"
    try:
        seen = state.read_text().splitlines() if state.exists() else []
        if entry in seen:
            return True
        state.write_text("\n".join([line for line in seen if line.startswith(today)] + [entry]) + "\n")
    except OSError:
        pass
    return False


def checkout_warning():
    repo = git("rev-parse", "--show-toplevel") if link.exists() else ""
    if not repo:
        return ""
    branch = git("branch", "--show-current") or "a detached HEAD"
    behind = git("rev-list", "--count", "HEAD..origin/main") or "0"
    if branch == "main" and behind != "0" and not git("status", "--porcelain", "--untracked-files=no"):
        git("merge", "--ff-only", "-q", "origin/main")
        behind = git("rev-list", "--count", "HEAD..origin/main") or "0"
    if branch == "main" and behind == "0":
        return ""
    if branch != "main" and warned_today(branch):
        return ""
    where = f"is on {branch}" if branch != "main" else "is on main"
    lag = f", {behind} commits behind origin/main" if behind != "0" else ""
    return (f"⚠️ The skills checkout at {repo} {where}{lag}, so this session loads "
            "skills that differ from main.")


_LOADED_BY = {"claude": "Claude Code", "codex": "Codex", "agents": "agents linked to it"}


def _named(paths, render, hosts, removed, value):
    """paths as home-relative names, each with what loads it: Codex and the agents file inline what
    Claude Code imports, and a skill note loads with its skill in any of them."""
    loaders = {path: _LOADED_BY[host] for host, path in render.outputs(value).items()}

    def kind(path):
        if path in removed:
            return "skill note, removed: stop following it"
        if path in hosts:
            return loaders.get(path, "Claude Code")
        return "skill note"
    return ", ".join(f"{render._home(path)} ({kind(path)})" for path in paths)


def build_warning():
    """Rebuilds stale built files, or warns, as the module docstring says."""
    kit = hook_parity.HOOKS.parent
    try:
        # A missing resolved.json reads as the kit's defaults, this kit, and is rebuilt.
        if hook_parity.resolved.kit().resolve() != kit:
            return ""
        import doctor, notes, render
        value = hook_parity.config.resolve()
        stale = doctor._stale(value)
        hosts = render.instructions(value)
    except Exception as error:  # an invalid config or a broken kit: report it, never block the session
        reason = "the config doesn't resolve" if isinstance(error, hook_parity.config.Invalid) else repr(error)
        return f"⚠️ addystack couldn't check its built instructions ({reason}): run `addystack doctor`."
    # Another session's rebuild can land between this one loading its instructions and this hook,
    # whole or in part.
    recent = [path for path in [*hosts, *notes.built(value)]
              if path.is_file() and time.time() - path.stat().st_mtime < 30]
    if not stale:
        return (f"⚠️ addystack rebuilt {_named(recent, render, hosts, (), value)} in the last 30 seconds, maybe after this session "
                "loaded them, so read the ones your host loads now and follow them where they differ."
                if recent else "")
    # A host file addystack didn't build, such as a CLAUDE.md under another CLAUDE_CONFIG_DIR, is
    # install's to adopt; build would overwrite it.
    import reconcile
    try:
        foreign = [render._home(path) for path in render.outputs(value).values()
                   if path in stale and reconcile._hand_written(path)]
    except ValueError as error:
        foreign = [str(error)]
    if foreign:
        return (f"⚠️ addystack's built instructions are out of date, but {', '.join(foreign)} holds text addystack "
                "didn't build, so nothing was rebuilt: run `addystack install` to adopt it.")
    top = subprocess.run(["git", "-C", str(kit), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    # A kit inside another repo, such as a home folder kept in git, isn't a kit checkout.
    tracked = subprocess.run(["git", "-C", str(kit), "ls-files", "--error-unmatch", "bin/addystack"],
                             capture_output=True).returncode == 0
    if top.returncode == 0 and tracked:
        repo = ["git", "-C", top.stdout.strip()]
        branch = subprocess.run([*repo, "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
        if branch != "main":
            return ""
        if subprocess.run([*repo, "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout:
            return (f"⚠️ addystack's built instructions don't match the kit at {top.stdout.strip()}, which has local "
                    "changes, so they weren't rebuilt: run `addystack build` once those changes should load.")
    # The build refreshes each note's skill hash, which is how doctor flags a note to reread after its
    # skill changes, so the session hears it here instead.
    reread = [fix for _, fix in notes.problems(value)]
    # A line added by hand under a built file's header looks like stale text, so the replaced host
    # files are kept beside them, as `addystack init --force` keeps the config it replaces.
    kept = []
    try:
        for path in render.outputs(value).values():
            if path in stale and path.is_file():
                shutil.copyfile(path, path.with_name(f"{path.name}.bak"))
                kept.append(render._home(path.with_name(f"{path.name}.bak")))
        done = subprocess.run([sys.executable, str(kit / "bin" / "addystack"), "build"], capture_output=True,
                              text=True, timeout=3, stdin=subprocess.DEVNULL)  # a rebuild takes about 0.2 s
        failed = done.returncode and (done.stderr.strip().splitlines() or ["no output"])[-1]
    except (OSError, subprocess.TimeoutExpired) as error:
        failed = str(error)
    # Everything the build wrote or removed but resolved.json, which hooks read when they run.
    rebuilt = [path for path in stale if path != hook_parity.resolved.STATE.expanduser()]
    rebuilt += [path for path in recent if path not in stale]
    return " ".join(
        ([f"⚠️ addystack's built instructions are out of date, and `addystack build` failed ({failed}): run "
          "`addystack doctor`."] if failed else [])
        + ([f"⚠️ addystack rebuilt {_named(rebuilt, render, hosts, [p for p in rebuilt if stale.get(p, '') is None], value)}, "
          "which no longer matched the kit and the user's config. This session loaded the old text, so read the "
          "ones your host loads, and any note already read, now and follow them where they differ."
          + (f" The replaced text is in {', '.join(kept)}." if kept else "")]
           if rebuilt and not failed else [])
        + ([f"⚠️ addystack notes to check against their changed skills: {'; '.join(reread)}."] if reread else []))


def hook_drift():
    """hook_parity's drift lines, from a fresh process: this one loaded hookset before the
    fast-forward, which can change what drift checks, such as RETIRED."""
    try:
        parity = subprocess.run([sys.executable, hook_parity.__file__], capture_output=True, text=True,
                                stdin=subprocess.DEVNULL, timeout=3)
    except (OSError, subprocess.TimeoutExpired) as error:
        return [f"not checked: {error}"]
    if parity.returncode == 0:
        return []
    return parity.stdout.splitlines() or [f"not checked: hook_parity.py exited {parity.returncode}"]


# The checkout first, since a fast-forward can change the manifest drift reads and the
# built files.
checkout = checkout_warning()
build = build_warning()
drift = hook_drift()
warnings = [checkout, build] + ([
    "⚠️ This machine's hooks differ from hooks/manifest.json, so some checks don't run as "
    f"declared (recheck with `python3 {hook_parity.__file__} --codex-trust`): " + "; ".join(drift) + "."]
    if drift else [])
warnings = [warning for warning in warnings if warning]
if warnings:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": " ".join(warnings) + " Tell the user in your first reply, "
                             "before relying on a skill's rules.",
    }}))
