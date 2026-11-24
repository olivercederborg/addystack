"""github.sh against a stub `gh` that answers from a scenario file, after each `--jq` would
have run: `required` says `not run` only for a draft whose CI skipped, and otherwise
prints what it always has."""
import json, os, pathlib, subprocess, tempfile, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "github.sh"
VERDICTS = SCRIPT.parent.parent.parent / "skills" / "primitive" / "addystack" / "hooks" / "verdicts.py"

GH = r"""#!/usr/bin/env python3
import json, os, sys
s = json.load(open(os.environ["SCENARIO"]))
a = " ".join(sys.argv[1:])
if a.startswith("repo view"):
    print("o/r")
elif a.startswith("pr view"):
    print(f"main {str(s['draft']).lower()}")
elif a.startswith("api repos/o/r/rules/branches/main"):
    print("\n".join(s["required"]))
elif a.startswith("api repos/o/r/branches/main/protection"):
    print('{"message":"Branch not protected"}')
    sys.exit(1)
elif a.startswith("pr checks"):
    print("\n".join(f"{name}\t{bucket}" for name, bucket in s["checks"]))
elif a.startswith("api graphql") and "expression=main:.github/workflows" in a:
    print("\n".join(s["workflows"]))
else:
    sys.exit(f"unexpected: gh {a}")
"""

SKIPPED = [["build", "skipping"], ["ci", "pass"]]


class Required(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)])
        (self.tmp / "bin").mkdir()
        stub = self.tmp / "bin" / "gh"
        stub.write_text(GH)
        stub.chmod(0o755)

    def required(self, draft=True, required=(), checks=SKIPPED, workflows=("ci.yml",)):
        scenario = self.tmp / "scenario.json"
        scenario.write_text(json.dumps({"draft": draft, "required": list(required), "checks": checks,
                                        "workflows": list(workflows)}))
        result = subprocess.run([str(SCRIPT), "required", "7"], capture_output=True, text=True, cwd=self.tmp,
                                env={**os.environ, "PATH": f"{self.tmp / 'bin'}:{os.environ['PATH']}",
                                     "SCENARIO": str(scenario)})
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_a_draft_whose_ci_skipped_did_not_run(self):
        self.assertEqual(self.required(required=["ci"]), "ci\tpass\nworkflows that skip drafts: ci.yml\n"
                                                         "required: not run (draft; CI skips drafts here)\n")
        # A required job that skips on a draft may never report.
        self.assertEqual(self.required(required=["ci", "deploy"]),
                         "ci\tpass\ndeploy\tnot reported\nworkflows that skip drafts: ci.yml\n"
                         "required: not run (draft; CI skips drafts here)\n")

    def test_a_failing_check_counts_when_the_base_requires_none(self):
        self.assertEqual(self.required(checks=[*SKIPPED, ["Require Linear issue", "fail"]]),
                         "no required checks on main\nworkflows that skip drafts: ci.yml\nrequired: all passed\n")

    def test_a_running_required_check_is_not_all_passed(self):
        self.assertEqual(self.required(required=["ci"], checks=[["build", "skipping"], ["ci", "pending"]]),
                         "ci\tpending\nworkflows that skip drafts: ci.yml\nrequired: not all passed\n")

    def test_a_ready_pr_or_a_base_that_never_skips_drafts_is_unchanged(self):
        for label, kwargs in {"ready": {"draft": False}, "no draft workflows": {"workflows": ()}}.items():
            with self.subTest(label):
                self.assertEqual(self.required(required=["ci"], **kwargs), "ci\tpass\nrequired: all passed\n")


FILES_GH = r"""#!/usr/bin/env python3
import os, sys
a = " ".join(sys.argv[1:])
if a.startswith("repo view"):
    print("o/r")
elif a.startswith("api --paginate repos/o/r/pulls/7/files"):
    print(open(os.environ["FILES"]).read(), end="")
elif a.startswith("pr view 7 --json headRefOid"):
    print(os.environ["HEAD_SHA"])
else:
    sys.exit(f"unexpected: gh {a}")
"""

# New lines 1-2 are context and 3-4 are added; old line 3 is deleted.
PATCH = "@@ -1,3 +1,4 @@\n a\n b\n+c\n-d\n+e"


class Anchors(unittest.TestCase):
    def run_script(self, *args, drafts=(), head="abc"):
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(tmp)])
        (tmp / "bin").mkdir()
        stub = tmp / "bin" / "gh"
        stub.write_text(FILES_GH)
        stub.chmod(0o755)
        (tmp / "files.jsonl").write_text(json.dumps({"filename": "a.ts", "patch": getattr(self, "patch", PATCH)}) + "\n")
        (tmp / "drafts.json").write_text(json.dumps(list(drafts)))
        (tmp / "body.md").write_text("Why?")
        args = [str(tmp / "drafts.json") if arg == "DRAFTS" else arg for arg in args]
        return subprocess.run([str(SCRIPT), *args], capture_output=True, text=True,
                              env={**os.environ, "PATH": f"{tmp / 'bin'}:{os.environ['PATH']}",
                                   "FILES": str(tmp / "files.jsonl"), "HEAD_SHA": head, "DRY_RUN": "1"})

    def anchors(self, *drafts):
        return self.run_script("anchors", "7", "DRAFTS", drafts=drafts)

    def test_a_range_over_an_added_line_is_changed(self):
        result = self.anchors({"path": "a.ts", "start_line": 2, "line": 3})
        self.assertEqual((result.returncode, result.stdout), (0, "a.ts:2-3 RIGHT\tchanged\n"))

    def test_context_lines_inside_a_hunk_are_flagged_but_postable(self):
        result = self.anchors({"path": "a.ts", "start_line": 1, "line": 2})
        self.assertEqual((result.returncode, result.stdout),
                         (0, "a.ts:1-2 RIGHT\tcontext only: the PR didn't write these lines\n"))

    def test_a_line_past_the_hunk_fails(self):
        result = self.anchors({"path": "a.ts", "start_line": 4, "line": 6})
        self.assertEqual((result.returncode, result.stdout), (1, "a.ts:4-6 RIGHT\toutside the diff at line 5\n"))

    def test_a_form_feed_inside_a_line_keeps_the_numbering(self):
        # The hunk has 3 new lines; splitlines() would split "x\fy" and invent a line 4.
        self.patch = "@@ -1,2 +1,3 @@\n a\n+x\x0cy\n b"
        result = self.anchors({"path": "a.ts", "line": 4})
        self.assertEqual((result.returncode, result.stdout), (1, "a.ts:4-4 RIGHT\toutside the diff at line 4\n"))

    def test_a_deleted_line_counts_on_the_left(self):
        result = self.anchors({"path": "a.ts", "line": 3, "side": "LEFT"})
        self.assertEqual((result.returncode, result.stdout), (0, "a.ts:3-3 LEFT\tchanged\n"))

    def test_approve_stops_when_the_head_moved(self):
        result = self.run_script("approve", "7", "abc", head="def")
        self.assertEqual(result.returncode, 1)
        self.assertIn("the head moved from abc to def", result.stderr)

    def test_approve_sends_its_comments_in_the_approving_review(self):
        result = self.run_script("approve", "7", "abc", "DRAFTS",
                                 drafts=[{"path": "a.ts", "line": 3, "body_file": "body.md"}])
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(payload, {"commit_id": "abc", "event": "APPROVE",
                                   "comments": [{"path": "a.ts", "line": 3, "side": "RIGHT", "body": "Why?"}]})

    def test_approve_refuses_a_comment_outside_the_diff(self):
        result = self.run_script("approve", "7", "abc", "DRAFTS",
                                 drafts=[{"path": "a.ts", "line": 9, "body_file": "body.md"}])
        self.assertEqual((result.returncode, result.stdout), (1, "a.ts:9-9 RIGHT\toutside the diff at line 9\n"))


BRANCH_GH = r"""#!/usr/bin/env python3
import sys
a = " ".join(sys.argv[1:])
if a.startswith("repo view --json defaultBranchRef"):
    print("main")
else:
    sys.exit(f"unexpected: gh {a}")
"""


class TargetBranch(unittest.TestCase):
    """A stack with no PRs: main ← layer1 ← layer2, origin a bare repo whose main is a
    commit ahead of the local main."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)])
        (self.tmp / "bin").mkdir()
        stub = self.tmp / "bin" / "gh"
        stub.write_text(BRANCH_GH)
        stub.chmod(0o755)
        self.repo = self.tmp / "repo"
        self.git("init", "-q", "--bare", "-b", "main", str(self.tmp / "origin.git"), cwd=self.tmp)
        self.git("clone", "-q", str(self.tmp / "origin.git"), str(self.repo), cwd=self.tmp)
        self.commit("f", "a\n")
        self.git("push", "-q", "origin", "main")
        self.commit("f", "b\n")
        self.git("push", "-q", "origin", "main")
        self.git("reset", "-q", "--hard", "HEAD~1")  # local main is behind origin's
        self.git("switch", "-q", "-c", "layer1", "origin/main")
        self.commit("g", "1\n")
        self.git("switch", "-q", "-c", "layer2")
        self.commit("h", "2\n")

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, name, text):
        (self.repo / name).write_text(text)
        self.git("add", name)
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", text)

    def target(self, *args):
        return subprocess.run([str(SCRIPT), "target", *args], capture_output=True, text=True, cwd=self.repo,
                              env={**os.environ, "PATH": f"{self.tmp / 'bin'}:{os.environ['PATH']}"})

    def fields(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return dict(line.split(": ", 1) for line in result.stdout.splitlines())

    def patch_id(self, base, head):
        diff = subprocess.run(["git", "diff", "--full-index", f"{base}...{head}"], cwd=self.repo, check=True,
                              capture_output=True).stdout
        return subprocess.run(["git", "patch-id", "--verbatim"], cwd=self.repo, input=diff, check=True,
                              capture_output=True).stdout.decode().split(" ")[0]

    def test_a_stacked_branch_diffs_against_its_parent(self):
        fields = self.fields(self.target("--branch", "layer2", "--parent", "layer1"))
        head = self.git("rev-parse", "layer2")
        self.assertEqual(fields, {
            "pr": "none", "branch": "layer2", "base": "layer1", "base_sha": self.git("rev-parse", "layer1"),
            "head_sha": head, "local_head": f"matches ({head})", "clean": "yes",
            "patch-id": self.patch_id("layer1", "layer2"), "done": "no", "size": "+1 −0 in 1 file", "review": "none",
            "last": "none"})

    def test_without_a_parent_it_diffs_against_the_newer_default_branch(self):
        self.git("switch", "-q", "main")
        fields = self.fields(self.target("--branch", "layer1"))
        self.assertEqual((fields["base"], fields["base_sha"], fields["local_head"].split(" ")[0]),
                         ("main", self.git("rev-parse", "origin/main"), "differs"))
        self.assertEqual(fields["patch-id"], self.patch_id("origin/main", "layer1"))

    def test_a_branch_ahead_of_origin_keeps_its_unpushed_commits(self):
        self.git("push", "-q", "origin", "layer2")
        self.commit("h", "3\n")  # a fix commit not pushed yet
        fields = self.fields(self.target("--branch", "layer2", "--parent", "layer1"))
        self.assertEqual(fields["head_sha"], self.git("rev-parse", "layer2"))
        self.assertNotEqual(fields["head_sha"], self.git("rev-parse", "origin/layer2"))

    def test_a_recheck_reads_known_only_at_the_head(self):
        # Review of #99: a checkout ahead of the head target reads holds commits the kept
        # Done never saw, so its re-check reads them.
        context = json.dumps({"session_id": "s", "agent_id": "a", "agent_type": "work-verifier"})
        subprocess.run(["python3", str(VERDICTS), "record", self.git("rev-parse", "layer1"), self.git("rev-parse", "layer2"),
                        "--branch", "layer2"], cwd=self.repo, check=True, capture_output=True,
                       env={**os.environ, "VERIFY_WORK_HOOK_CONTEXT": context})
        last = lambda: json.loads(self.target("--branch", "layer2", "--parent", "layer1").stdout.splitlines()[-1])
        self.assertIn("Done stands", last()["known"])
        (self.repo / "h").write_text("uncommitted\n")  # its checks would run this, not the head
        self.assertNotIn("known", last())
        self.git("checkout", "-q", "h")
        self.git("switch", "-q", "--detach", "layer1")  # this checkout isn't at the head target reads
        self.assertNotIn("known", last())

    def test_a_missing_branch_fails(self):
        result = self.target("--branch", "nope")
        self.assertEqual((result.returncode, result.stderr), (1, "no branch nope here or on origin\n"))
        self.assertEqual(self.target("--branch", "layer1", "--parent").returncode, 2)


if __name__ == "__main__":
    unittest.main()
