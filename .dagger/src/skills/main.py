import re
from typing import Annotated

import dagger
from dagger import DefaultPath, Ignore, check, dag, function, object_type

PYTHON = "python:3.15-slim-trixie@sha256:8c13a3f37a6a5b71498228e902c4b9f51c1f7900d49fabf71f9a650c6120e0d0"
# The hook tests also run each hook under /usr/bin/python3 when it exists, macOS's 3.9.
PYTHON39 = "python:3.9-slim-trixie@sha256:2d97f6910b16bd338d3060f261f53f144965f755599aab1acda1e13cf1731b1b"
NODE = "node:24-trixie-slim@sha256:54f84b4cf8432b21aaffd5d3ce8d41e12cea0d10d33c09d2f3c9879d49d6b446"
# The versions on the maintainer's Mac on 2026-11-02, so shared-tests runs gh-stack's tests.
GH = "2.103.3"
GH_STACK = "v0.2.1"
KIT = "/kit"
# The addystack skill's folder, which holds the tool: bin/, lib/, hooks/, schema/, core/.
TOOL = "skills/primitive/addystack"

# The hook tests' inputs, the same list scripts/hook-inputs-staged.sh keeps for
# pre-commit; hooks_tests fails when the two differ.
HOOK_INPUTS = [f"{TOOL}/hooks", "skills/optional/reply-shape/SKILL.md", "replies.md",
               f"{TOOL}/scripts/check-body.mjs", f"{TOOL}/scripts/check-mermaid.mjs", f"{TOOL}/scripts/stack.sh",
               f"{TOOL}/lib", f"{TOOL}/addystack.defaults.jsonc", f"{TOOL}/schema",
               # routine_stop.py cites it when the user keeps no reply rules file.
               f"{TOOL}/references/turn-block.md",
               # ReadyGate records through review-loop's copy.
               "skills/primitive/review-loop/scripts/verdicts.py"]
# The kit's Python modules other suites import, without the hook tests.
HOOK_MODULES = [f"{TOOL}/hooks/*.py", f"-{TOOL}/hooks/test_*.py"]
# Each kit folder whose scripts/ holds tests, a skill's as skills/<layer>/<skill>, with the files
# they read outside the folder or in its Markdown, which skill_source leaves out. A skill's
# copies of kit files (scripts/copies.txt) are in its folder, so they need no entry.
SKILL_SUITES = {
    "skills/orchestrator/coordinator": [],
    "skills/primitive/correct": [],
    "skills/primitive/open-pr": [],
    "skills/primitive/reflect": [],
    "skills/primitive/review-loop": ["skills/primitive/review-loop/references/review-lenses.md"],
    # github.sh in shared/scripts runs the tool's hooks/verdicts.py, as it has no copy beside it.
    "shared": [f"{TOOL}/hooks/verdicts.py", f"{TOOL}/hooks/evidence.py"],
    # The html_render hook tests run the kit's wrapper, which finds reply-shape beside it,
    # and check that reply-shape's docs name the pinned renderer URL.
    "skills/optional/reply-shape": [f"{TOOL}/hooks/reply-card.py", "skills/optional/reply-shape/**/*.md"],
    "skills/primitive/show-me-your-work": [],
    "skills/primitive/verify-work": [],
}
# Where pre-commit's glob finds each kit suite: a shipped skill's scripts/, and
# shared/scripts/. The workshop that holds the kit runs its own suites on the host.
SUITE_TESTS = ("skills/primitive/*/scripts/test_*.py", "skills/orchestrator/*/scripts/test_*.py",
               "skills/optional/*/scripts/test_*.py", "shared/scripts/test_*.py")


# Every folder and the root files git tracks, not a root file only one checkout keeps, such
# as an untracked decision log, since Dagger doesn't read git's ignores.
TRACKED = ("*/**", ".dagger/**", ".githooks/**", "-.dagger/sdk", "-.dagger/.venv", ".gitignore", "LICENSE",
           "CHANGELOG.md", "README.md", "dagger.json", "replies.md", "router.md")

# Dagger doesn't read .gitignore, so every source also drops these untracked files,
# among them review-loop's packets, which it writes inside the checkout under review.
UNTRACKED = ["**/__pycache__", "**/.DS_Store", "**/.review-loop"]


def only(*paths: str) -> Ignore:
    """Ignore patterns that load just these paths; a leading `-` drops a path again."""
    return Ignore(["**", *(p[1:] if p.startswith("-") else f"!{p}" for p in paths), *UNTRACKED])


def source(*paths: str):
    """A `source` argument holding the repository's copy of these paths."""
    return Annotated[dagger.Directory, DefaultPath("/"), only(*paths)]


async def toolbox(kit: dagger.Directory, suite: str) -> dagger.Container:
    """Python 3.15 (and 3.9 at /usr/bin/python3), git, ps, ss, node with npm, and gh with
    gh-stack as a non-root user, with the kit at /kit.

    check-mermaid.mjs installs Mermaid into ~/.cache/skills-mermaid on first use, so that
    folder is a cache volume the engine keeps between runs, one per suite: two checks
    installing into one empty folder at once break each other's install."""
    arch = str(await dag.default_platform()).split("/")[1]
    node = dag.container().from_(NODE)
    py39 = dag.container().from_(PYTHON39)
    gh = (
        dag.container()
        .from_(PYTHON)
        .with_mounted_file("/gh.tar.gz", dag.http(f"https://github.com/cli/cli/releases/download/v{GH}/"
                                                  f"gh_{GH}_linux_{arch}.tar.gz"))
        .with_exec(["tar", "-xzf", "/gh.tar.gz", "--strip-components=2", "-C", "/usr/local/bin",
                    f"gh_{GH}_linux_{arch}/bin/gh"])
        .file("/usr/local/bin/gh")
    )
    extension = "/home/runner/.local/share/gh/extensions/gh-stack"
    manifest = (f"owner: github\nname: gh-stack\nhost: github.com\ntag: {GH_STACK}\nispinned: true\n"
                f"path: {extension}/gh-stack\n")
    return (
        dag.container()
        .from_(PYTHON)
        .with_exec(["sh", "-c", "apt-get update -q && apt-get install -yq --no-install-recommends git iproute2 procps"
                    " && rm -rf /var/lib/apt/lists/*"])
        # hooks/test_hooks.py checks turn blocks against CommonMark with these, when installed.
        .with_exec(["pip", "install", "-q", "--no-cache-dir", "--root-user-action=ignore",
                    "markdown-it-py==4.2.0", "html5lib==1.1"])
        .with_file("/usr/local/bin/node", node.file("/usr/local/bin/node"))
        .with_directory("/usr/local/lib/node_modules/npm", node.directory("/usr/local/lib/node_modules/npm"))
        .with_exec(["ln", "-s", "../lib/node_modules/npm/bin/npm-cli.js", "/usr/local/bin/npm"])
        .with_file("/usr/local/bin/python3.9", py39.file("/usr/local/bin/python3.9"))
        .with_file("/usr/local/lib/libpython3.9.so.1.0", py39.file("/usr/local/lib/libpython3.9.so.1.0"))
        .with_directory("/usr/local/lib/python3.9", py39.directory("/usr/local/lib/python3.9"))
        .with_exec(["sh", "-c", "ldconfig && ln -s /usr/local/bin/python3.9 /usr/bin/python3"])
        .with_file("/usr/local/bin/gh", gh)
        .with_exec(["useradd", "--create-home", "runner"])
        .with_file(f"{extension}/gh-stack", dag.http(f"https://github.com/github/gh-stack/releases/download/"
                                                     f"{GH_STACK}/linux-{arch}"), permissions=0o755, owner="runner")
        .with_new_file(f"{extension}/manifest.yml", manifest, owner="runner")
        .with_user("runner")
        .with_mounted_cache("/home/runner/.cache/skills-mermaid", dag.cache_volume(f"skills-mermaid-{suite}"),
                            owner="runner")
        .with_env_variable("PYTHONDONTWRITEBYTECODE", "1")
        .with_directory(KIT, kit, owner="runner")
        .with_workdir(KIT)
    )


async def run(kit: dagger.Directory, *command: str, suite: str = "lint") -> None:
    await (await toolbox(kit, suite)).with_exec(list(command)).sync()


async def unittests(kit: dagger.Directory, folder: str) -> None:
    await run(kit, "python3", "-m", "unittest", "discover", "-q", "-s", folder, "-p", "test_*.py",
              suite=folder.removesuffix("/scripts").split("/")[-1])


async def skill_tests(kit: dagger.Directory, skill: str) -> None:
    await unittests(kit, f"{skill}/scripts")


def skill_source(skill: str):
    """The skill's folder (skills/<layer>/<skill>) without its Markdown outside scripts/, so a
    SKILL.md or reference edit keeps the cached result, plus the suite's SKILL_SUITES entries."""
    return source(skill, f"-{skill}/**/*.md", f"{skill}/scripts/**", *SKILL_SUITES[skill])


@object_type
class Skills:
    @function
    @check
    async def frontmatter(self, kit: source("skills/*/*/SKILL.md", "skills/*/*/agents/openai.yaml",
                                            "scripts/check-frontmatter.sh")) -> None:
        """scripts/check-frontmatter.sh"""
        await run(kit, "scripts/check-frontmatter.sh")

    @function
    @check
    async def skill_size(self, kit: source("skills/*/*/SKILL.md", "scripts/check-skill-size.sh")) -> None:
        """scripts/check-skill-size.sh"""
        await run(kit, "scripts/check-skill-size.sh")

    @function
    @check
    async def layers(self, kit: source("**/*.md", "scripts/check-layers.py", f"{TOOL}/lib/skill_layer.py")) -> None:
        """scripts/check-layers.py, over every Markdown file, since a skill's links reach shared/ and docs/"""
        await run(kit, "scripts/check-layers.py")

    @function
    @check
    async def neutral(self, kit: source(*TRACKED)) -> None:
        """scripts/check-neutral.py, over the whole kit"""
        await run(kit, "scripts/check-neutral.py")

    @function
    @check
    async def format_sync(self, kit: source("skills/*/*/SKILL.md", "shared/format-pointer.md", "scripts/sync-format.sh")) -> None:
        """scripts/sync-format.sh --check"""
        await run(kit, "scripts/sync-format.sh", "--check")

    @function
    @check
    async def notes_line(self, kit: source("skills/*/*/SKILL.md", "shared/notes-line.md", "scripts/sync-notes.py",
                                           f"{TOOL}/lib/skill_layer.py")) -> None:
        """scripts/sync-notes.py --check: every core skill has the notes line near its top (plan D15)"""
        await run(kit, "scripts/sync-notes.py", "--check")

    @function
    @check
    async def copies_sync(self, kit: source(*TRACKED)) -> None:
        """scripts/sync-copies.py --check, over the whole kit, since it also finds any symlink"""
        await run(kit, "scripts/sync-copies.py", "--check")

    @function
    @check
    async def install(self, kit: source(*TRACKED)) -> None:
        """scripts/check-install.py: npx skills add installs every file of every skill (plan check 11)"""
        await run(kit, "scripts/check-install.py", suite="install")

    @function
    @check
    async def fresh_install(self, kit: source(*TRACKED)) -> None:
        """scripts/check-fresh-install.py: a fresh Linux user installs this tree with npx skills add,
        then runs addystack init, install, and doctor (plan check 9)"""
        await run(kit, "scripts/check-fresh-install.py", suite="fresh-install")

    @function
    async def fresh_install_from(
        self,
        repo: str,
        kit: source("scripts/check-fresh-install.py", "scripts/check-install.py"),
        token: dagger.Secret | None = None,
    ) -> None:
        """Plan check 9 on a published kit, such as owner/addystack: npx skills add installs it from
        GitHub. token, a read-only GitHub token, reads a private repo."""
        container = await toolbox(kit, "fresh-install")
        if token is not None:
            container = container.with_secret_variable("GITHUB_TOKEN", token)
        await container.with_exec(["scripts/check-fresh-install.py", repo]).sync()

    @function
    @check
    async def examples(self, kit: source("skills/*/*/SKILL.md", "replies.md", "skills/optional/reply-shape/references/*.md",
                                         "scripts/check_examples.py", *HOOK_MODULES)) -> None:
        """scripts/check_examples.py"""
        await run(kit, "scripts/check_examples.py")

    @function
    @check
    async def reply_budget(self, kit: source("skills/optional/reply-shape/SKILL.md", "replies.md",
                                             "scripts/check-reply-budget.py", f"{TOOL}/lib/config.py", *HOOK_MODULES)) -> None:
        """scripts/check-reply-budget.py"""
        await run(kit, "scripts/check-reply-budget.py")

    @function
    @check
    async def hooks_tests(self, kit: source(*HOOK_INPUTS, "scripts/hook-inputs-staged.sh")) -> None:
        """The tool's hooks/test_*.py, after checking HOOK_INPUTS matches scripts/hook-inputs-staged.sh"""
        script = await kit.file("scripts/hook-inputs-staged.sh").contents()
        listed = re.search(r"^inputs=\(([^)]*)\)", script, re.M).group(1).split()
        if listed != HOOK_INPUTS:
            raise ValueError(f"HOOK_INPUTS in .dagger/src/skills/main.py differs from {listed!r}")
        await unittests(kit, f"{TOOL}/hooks")

    @function
    @check
    async def scripts_tests(
        self,
        # check_examples reads every SKILL.md and reply-shape's references, the scripts
        # import the tool's hooks/, and the addystack tests run the whole tool (bin/addystack,
        # its schema, lib/, defaults, example config, core templates, and principles) and
        # compare the core templates with the router and principles index they copy.
        # test_sync_copies runs each copied skill script beside its source. The install tests
        # link the work-verifier agent from verify-work's folder.
        kit: source("scripts", "skills/*/*/scripts", "shared/scripts", ".githooks/pre-commit", TOOL,
                    f"-{TOOL}/hooks/README.md", "skills/*/*/SKILL.md", "skills/*/*/agents/*.md", "replies.md",
                    "skills/optional/reply-shape/references/*.md", "router.md", "principles/index.md"),
    ) -> None:
        """scripts/test_*.py"""
        await unittests(kit, "scripts")

    @function
    @check
    async def suites_listed(self, kit: source(*SUITE_TESTS)) -> None:
        """Every skill with scripts/test_*.py has a check here, as pre-commit's glob finds it."""
        found = {path.rsplit("/scripts/", 1)[0] for pattern in SUITE_TESTS for path in await kit.glob(pattern)}
        if missing := sorted(found - SKILL_SUITES.keys()):
            raise ValueError(f"add a check and a SKILL_SUITES entry for {', '.join(missing)}")
        if extra := sorted(SKILL_SUITES.keys() - found):
            raise ValueError(f"SKILL_SUITES lists skills without tests: {', '.join(extra)}")

    @function
    @check
    async def coordinator_tests(self, kit: skill_source("skills/orchestrator/coordinator")) -> None:
        """skills/orchestrator/coordinator/scripts/test_*.py"""
        await skill_tests(kit, "skills/orchestrator/coordinator")

    @function
    @check
    async def correct_tests(self, kit: skill_source("skills/primitive/correct")) -> None:
        """skills/primitive/correct/scripts/test_*.py"""
        await skill_tests(kit, "skills/primitive/correct")

    @function
    @check
    async def open_pr_tests(self, kit: skill_source("skills/primitive/open-pr")) -> None:
        """skills/primitive/open-pr/scripts/test_*.py"""
        await skill_tests(kit, "skills/primitive/open-pr")

    @function
    @check
    async def reflect_tests(self, kit: skill_source("skills/primitive/reflect")) -> None:
        """skills/primitive/reflect/scripts/test_*.py"""
        await skill_tests(kit, "skills/primitive/reflect")

    @function
    @check
    async def review_loop_tests(self, kit: skill_source("skills/primitive/review-loop")) -> None:
        """skills/primitive/review-loop/scripts/test_*.py"""
        await skill_tests(kit, "skills/primitive/review-loop")

    @function
    @check
    async def reply_shape_tests(self, kit: skill_source("skills/optional/reply-shape")) -> None:
        """skills/optional/reply-shape/scripts/test_*.py"""
        await skill_tests(kit, "skills/optional/reply-shape")

    @function
    @check
    async def shared_tests(self, kit: skill_source("shared")) -> None:
        """shared/scripts/test_*.py"""
        await skill_tests(kit, "shared")

    @function
    @check
    async def show_me_your_work_tests(self, kit: skill_source("skills/primitive/show-me-your-work")) -> None:
        """skills/primitive/show-me-your-work/scripts/test_*.py"""
        await skill_tests(kit, "skills/primitive/show-me-your-work")

    @function
    @check
    async def verify_work_tests(self, kit: skill_source("skills/primitive/verify-work")) -> None:
        """skills/primitive/verify-work/scripts/test_*.py"""
        await skill_tests(kit, "skills/primitive/verify-work")
