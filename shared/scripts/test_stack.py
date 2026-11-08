"""stack.sh on a real git fixture with the real gh-stack extension, behind a `gh` stub that
answers GitHub's API from a scenario file and adds each branch's PR to `gh stack view
--json`, since a local bare origin has no PRs. Each test replays a gh stack error agents
hit in T3 threads from Oct 20 to 30, 2026 (suite-audit r2, section 4), with its count."""
import json, os, pathlib, shutil, subprocess, tempfile, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "stack.sh"
REAL_GH = shutil.which("gh")
HAS_STACK = bool(REAL_GH) and subprocess.run([REAL_GH, "stack", "--help"], capture_output=True).returncode == 0

GH = r"""#!/usr/bin/env python3
import json, os, subprocess, sys
s = json.load(open(os.environ["SCENARIO"]))
a, real = sys.argv[1:], os.environ["REAL_GH"]
if a[:3] == ["stack", "view", "--json"]:
    view = subprocess.run([real, *a], capture_output=True, text=True)
    if view.returncode:
        sys.stderr.write(view.stderr)
        sys.exit(view.returncode)
    stack = json.loads(view.stdout)
    for branch in stack["branches"]:
        if branch["name"] in s["prs"]:
            branch["pr"] = {"number": s["prs"][branch["name"]], "state": "OPEN"}
    print(json.dumps(stack, indent=2))
elif a[:3] == ["stack", "rebase", "--continue"] and s.get("continue_fails"):
    sys.exit(s["continue_fails"])  # such as a commit it can't sign: the stop stays where it was
elif a[:1] == ["stack"]:
    os.execv(real, [real, *a])
elif a[:2] == ["repo", "view"]:
    print("main" if "defaultBranchRef" in a else "o/r")
elif a[:2] == ["pr", "view"]:
    if a[2] not in s["prs"]:
        sys.exit(f'no pull requests found for branch "{a[2]}"')
    print(s["prs"][a[2]])
elif a[:2] == ["api", "graphql"]:
    print(s["pulls"][next(arg[2:] for arg in a if arg.startswith("n="))])
else:
    sys.exit(f"unexpected: gh {' '.join(a)}")
"""


@unittest.skipUnless(HAS_STACK, "needs gh with the gh-stack extension")
class Stack(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "bin").mkdir()
        stub = self.tmp / "bin" / "gh"
        stub.write_text(GH)
        stub.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{self.tmp / 'bin'}:{os.environ['PATH']}", "REAL_GH": REAL_GH,
                    "SCENARIO": str(self.tmp / "scenario.json"), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}
        self.scenario()
        self.repo = self.tmp / "repo"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.tmp / "origin.git")], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        self.git("remote", "add", "origin", "../origin.git")
        self.commit("f", "base\n")
        self.git("push", "-q", "origin", "main")
        self.git("fetch", "-q", "origin")

    def scenario(self, prs=None, pulls=None, **extra):
        (self.tmp / "scenario.json").write_text(json.dumps({"prs": prs or {}, "pulls": pulls or {}, **extra}))

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, name, text, cwd=None):
        (cwd or self.repo).joinpath(name).write_text(text)
        self.git("add", name, cwd=cwd)
        self.git("commit", "-qm", f"{name}: {text.strip()}", cwd=cwd)

    def run_in(self, *args, cwd=None):
        return subprocess.run([*args], cwd=cwd or self.repo, env=self.env, capture_output=True, text=True)

    def stack(self, *args, cwd=None):
        result = self.run_in(str(SCRIPT), *args, cwd=cwd)
        return result.returncode, result.stdout + result.stderr

    def land_on_main(self, text):
        """A commit on origin's main that conflicts with any branch that changed f."""
        other = self.tmp / "other"
        if not other.exists():
            subprocess.run(["git", "clone", "-q", str(self.tmp / "origin.git"), str(other)], check=True)
        self.git("pull", "-q", "origin", "main", cwd=other)
        self.commit("f", text, cwd=other)
        self.git("push", "-q", "origin", "main", cwd=other)

    # start

    def test_start_from_a_detached_checkout(self):
        # 45 errors in 26 threads, 37 from `init` in a fresh T3 worktree.
        self.git("checkout", "-q", "--detach")
        init = self.run_in("gh", "stack", "init", "--base", "main", "feat")
        self.assertIn("not on any branch", init.stderr)
        # It still made the branch, so the usual retry, `git switch -c feat`, fails too.
        self.assertEqual(self.git("branch", "--list", "feat"), "feat")
        status, out = self.stack("start", "feat")
        self.assertEqual(status, 0, out)
        self.assertEqual(self.git("branch", "--show-current"), "feat")
        self.assertEqual(self.git("rev-parse", "feat"), self.git("rev-parse", "origin/main"))
        self.assertIn("  feat no PR  ← current", out)

    def test_start_refuses_on_a_stacked_branch(self):
        # 16 errors in 15 threads: `init` on a branch already in a stack.
        status, out = self.stack("start", "first")  # from main, before any stack
        self.assertEqual(status, 0, out)
        self.assertNotIn("Traceback", out)
        init = self.run_in("gh", "stack", "init", "second")
        self.assertIn('current branch "first" is already part of a stack', init.stderr)
        status, out = self.stack("start", "second")
        self.assertEqual(status, 1)
        self.assertIn("first is already in a stack", out)
        self.assertIn("  first no PR  ← current", out)
        self.assertEqual(self.git("branch", "--list", "second"), "")
        # The trunk of one stack starts another, as gh stack init does there.
        self.git("checkout", "-q", "main")
        status, out = self.stack("start", "second")
        self.assertEqual(status, 0, out)
        self.assertIn("  second no PR  ← current", out)
        # The trunk of two stacks fails `gh stack view`, and still starts a third.
        self.git("checkout", "-q", "main")
        status, out = self.stack("start", "third")
        self.assertEqual(status, 0, out)
        self.assertNotIn("Traceback", out)

    def test_start_keeps_a_branch_with_its_own_commits(self):
        self.git("checkout", "-q", "-b", "work")
        self.commit("w", "work\n")
        self.git("checkout", "-q", "--detach", "main")
        status, out = self.stack("start", "work")
        self.assertEqual(status, 1)
        self.assertIn("work already exists with commits not on origin/main", out)
        # A branch with none of its own, left behind origin by a failed init, starts at origin.
        self.git("branch", "-q", "left", "main")
        self.land_on_main("main moved\n")
        self.assertEqual(self.stack("start", "left")[0], 0)
        self.assertEqual(self.git("rev-parse", "left"), self.git("rev-parse", "origin/main"))

    # state

    def test_state_names_what_gh_stack_view_refuses(self):
        # Not part of a stack: 48 errors in 44 threads, 41 from `view`.
        status, out = self.stack("state")
        self.assertEqual(status, 0, out)
        self.assertIn('stack: none (✗ current branch "main" is not part of a stack)', out)
        # Two stacks on one trunk: the trunk belongs to both (8 errors).
        for name in ("one", "two"):
            self.git("checkout", "-q", "--detach", "main")
            self.stack("start", name)
        self.git("checkout", "-q", "main")
        self.assertIn('branch "main" belongs to multiple stacks', self.stack("state")[1])
        self.git("checkout", "-q", "--detach", "main")
        out = self.stack("state")[1]
        self.assertRegex(out, r"branch: detached at \w+ \(tip of: main one two\)")
        self.assertIn("changes: 0 tracked files, 0 untracked", out)
        self.assertIn("rebase: none", out)

    # where

    def test_where_a_lone_pr_merges_with_gh_pr_merge(self):
        # Not a stack number: 19 errors in 13 threads, 17 from `merge`. GitHub links a stack
        # only once it has two PRs.
        self.scenario(pulls={"7": "7 OPEN false feat none merge", "8": "8 OPEN true feat2 none squash"})
        status, out = self.stack("where", "#7")
        self.assertEqual(status, 0, out)
        self.assertIn("stack: none (GitHub has no stack with this PR)", out)
        self.assertIn(f"merge: cd {self.repo} && gh pr merge 7 --merge", out)
        out = self.stack("where", "8")[1]
        self.assertIn("pr: #8 (OPEN, draft)", out)
        # GitHub's preselected method for this user, since `gh pr merge` won't prompt in a pipe.
        self.assertIn(f"merge: cd {self.repo} && gh pr merge 8 --squash\n", out)

    def stacked(self):
        """Stack #30: feat (#12) under top (#13); top checked out in its own worktree."""
        self.git("checkout", "-q", "--detach")
        self.stack("start", "feat")
        self.commit("a", "a\n")
        self.run_in("gh", "stack", "add", "top")
        self.commit("b", "b\n")
        self.git("checkout", "-q", "--detach")
        worktree = self.tmp / "wt-top"
        self.git("worktree", "add", "-q", str(worktree), "top")
        self.scenario(prs={"feat": 12, "top": 13},
                      pulls={"12": "12 OPEN false feat 30 merge feat top", "13": "13 OPEN false top 30 merge feat top"})
        return worktree

    def test_where_a_stacked_pr_names_the_checkout_that_holds_its_stack(self):
        # The merge gate's "can't tell which PRs" (12 denials), and 192 hand-rolled worktree
        # searches in 121 threads.
        worktree = self.stacked()
        status, out = self.stack("where", "13")
        self.assertEqual(status, 0, out)
        self.assertIn(f"worktree: {worktree}", out)
        self.assertIn("stack: #30", out)
        self.assertIn(f"merge: cd {worktree} && gh stack merge 13 --yes", out)
        # The lower PR's branch has no checkout, so the one holding the layer above serves.
        out = self.stack("where", "feat")[1]
        self.assertIn(f"merge: cd {worktree} && gh stack merge 12 --yes", out)
        # GitHub's stack gained a layer this clone's catalog lacks: the gate would check only
        # the layers it lists, and GitHub would merge the other one too.
        self.scenario(prs={"feat": 12, "top": 13}, pulls={"13": "13 OPEN false top 30 merge feat lower top"})
        self.assertIn(f"merge: none: GitHub stack has lower, which the stack in {worktree} lacks",
                      self.stack("where", "13")[1])

    def test_where_names_why_there_is_no_merge_line(self):
        worktree = self.stacked()
        self.git("worktree", "remove", str(worktree))
        status, out = self.stack("where", "13")
        self.assertEqual(status, 1)
        self.assertIn("merge: none: no checkout holds top", out)
        # GitHub has the stack, but this clone's catalog doesn't: the gate's `gh stack view` fails.
        self.git("checkout", "-q", "-b", "untracked")
        self.scenario(prs={"untracked": 14}, pulls={"14": "14 OPEN false untracked 31 merge untracked other"})
        status, out = self.stack("where", "#14")
        self.assertEqual(status, 1)
        self.assertIn(f"merge: none: gh stack view in {self.repo} fails: ✗ current branch", out)
        self.scenario(pulls={"15": "15 MERGED false done 30 merge"})
        self.assertEqual(self.stack("where", "15"), (1, "pr: #15 (MERGED)\nbranch: done\nworktree: none\n"
                                                        "stack: #30\nmerge: none (MERGED)\n"))
        self.assertEqual(self.stack("where", "no-pr"), (1, "pr: none for branch no-pr\n"))

    # restack

    def conflicted(self):
        self.git("checkout", "-q", "--detach")
        self.stack("start", "feat")
        self.commit("f", "feat\n")
        before = self.git("rev-parse", "HEAD")
        self.land_on_main("main moved\n")
        return before

    def test_restack_stops_at_a_conflict_and_continues_after_it(self):
        self.conflicted()
        status, out = self.stack("restack")
        self.assertEqual(status, 3, out)
        self.assertIn(f"conflict: resolve each file", out)
        self.assertIn(f"{self.repo}: f\n", out)
        self.assertIn(f"rebase: stopped in {self.repo} (stack.sh restack continues it)\n", self.stack("state")[1])
        # A rerun before the file is resolved stops at the same place.
        self.assertEqual(self.stack("restack")[0], 3)
        (self.repo / "f").write_text("both\n")
        self.git("add", "f")
        status, out = self.stack("restack")
        self.assertEqual(status, 0, out)
        self.assertIn("rebase: none", out)
        self.git("merge-base", "--is-ancestor", "origin/main", "feat")

    def test_restack_continues_past_a_rerere_resolution(self):
        # 12 "Recorded resolution" stops on continue: git resolved the file, and the stop
        # still needed a `--continue`.
        self.git("config", "rerere.enabled", "true")
        self.git("config", "rerere.autoUpdate", "true")
        before = self.conflicted()
        self.assertEqual(self.stack("restack")[0], 3)
        (self.repo / "f").write_text("both\n")
        self.git("add", "f")
        self.assertEqual(self.stack("restack")[0], 0)
        self.git("reset", "-q", "--hard", before)
        status, out = self.stack("restack")
        self.assertEqual(status, 0, out)
        self.assertNotIn("conflict:", out)
        self.assertEqual((self.repo / "f").read_text(), "both\n")

    def test_restack_leaves_rebases_it_does_not_own(self):
        # Another checkout's plain git rebase, stopped on a conflict, isn't this stack's.
        other = self.tmp / "other-wt"
        self.git("worktree", "add", "-q", "-b", "side", str(other), "main")
        self.commit("f", "side\n", cwd=other)
        self.git("checkout", "-q", "-b", "side-base", "main")
        self.commit("f", "side base\n")
        self.run_in("git", "rebase", "side-base", cwd=other)
        self.assertIn("f", self.git("diff", "--name-only", "--diff-filter=U", cwd=other))
        self.conflicted()
        self.assertEqual(self.stack("restack")[0], 3)
        (self.repo / "f").write_text("both\n")
        self.git("add", "f")
        status, out = self.stack("restack")
        self.assertEqual(status, 0, out)
        self.assertNotIn(str(other), out)
        # A stopped gh stack rebase belongs to its stack: another checkout's restack refuses it.
        self.land_on_main("again\n")
        self.assertEqual(self.stack("restack")[0], 3)
        status, out = self.stack("restack", cwd=other)
        self.assertEqual(status, 1)
        self.assertIn(f"a gh stack rebase of feat is stopped in {self.repo}; finish it there first", out)

    def test_restack_stops_on_a_continue_that_makes_no_progress(self):
        self.conflicted()
        self.assertEqual(self.stack("restack")[0], 3)
        (self.repo / "f").write_text("both\n")
        self.git("add", "f")
        self.scenario(continue_fails="✗ rebase continue failed: error: gpg failed to sign the data")
        status, out = self.stack("restack")
        self.assertEqual(status, 1, out)
        self.assertEqual(out.count("gpg failed to sign"), 1, out)  # one continue, then it stops
        self.assertIn("gh stack rebase --continue failed without moving on", out)

    def test_restack_reports_a_refusal_before_any_conflict(self):
        # 19 "uncommitted changes" errors.
        self.git("checkout", "-q", "--detach")
        self.stack("start", "feat")
        self.commit("f", "feat\n")
        self.land_on_main("main moved\n")
        (self.repo / "f").write_text("dirty\n")
        status, out = self.stack("restack")
        self.assertEqual(status, 1, out)
        self.assertIn("uncommitted changes", out)
        self.assertIn("gh stack rebase failed before any conflict", out)


if __name__ == "__main__":
    unittest.main()
