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
elif a.startswith("api repos/o/r/branches/main --jq"):
    print("\n".join(s.get("classic", [])))
elif a.startswith("api graphql --paginate") and "statusCheckRollup" in a:
    workflows = "workflowRun{" in a  # the query asks for it; the --jq filter names .workflowRun either way
    if s["checks"] == "unreadable" or workflows and s.get("no_actions"):
        sys.exit("GraphQL: Resource not accessible by integration (repository.pullRequest.commits)")
    # As the --jq prints them: type, name, app id, workflow or suite, creation order and bucket. A
    # scenario row is [name, bucket, app id, order, workflow id, event, suite id, type] and may stop
    # after any field; a token that can't read workflows gets the suite.
    def row(c):
        name, bucket = c[0], c[1]
        app, order, workflow, event, suite, kind = (list(c[2:]) + ["", 1, "", "", 1, "check"][len(c) - 2:])[:6]
        group = f"workflow:{workflow}/{event}" if workflows and workflow else f"suite:{suite}"
        return "\t".join([kind, name, app, "" if kind == "status" else group, str(order), bucket])
    print("\n".join(row(c) for c in s["checks"]))
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

    def required(self, draft=True, required=(), checks=SKIPPED, workflows=("ci.yml",), classic=(), code=0, no_actions=False):
        scenario = self.tmp / "scenario.json"
        scenario.write_text(json.dumps({"draft": draft, "required": list(required), "checks": checks,
                                        "workflows": list(workflows), "classic": list(classic), "no_actions": no_actions}))
        result = subprocess.run([str(SCRIPT), "required", "7"], capture_output=True, text=True, cwd=self.tmp,
                                env={**os.environ, "PATH": f"{self.tmp / 'bin'}:{os.environ['PATH']}",
                                     "SCENARIO": str(scenario)})
        self.assertEqual(result.returncode, code, result.stderr)
        return result.stdout if code == 0 else result.stderr

    def test_classic_protection_contexts_count(self):
        self.assertEqual(self.required(draft=False, classic=["ci"], checks=[["ci", "pending"]]),
                         "ci\tpending\nrequired: not all passed\n")

    def test_checks_it_cannot_read_are_an_error_not_none(self):
        self.assertIn("Resource not accessible by integration", self.required(draft=False, checks="unreadable", code=1))
        self.assertEqual(self.required(draft=False, checks=[]), "no required checks on main\nrequired: all passed\n")

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

    def test_a_checks_newest_run_counts_not_an_older_pass(self):
        # Newest by creation order, whatever the rows' order; a run not started yet is newer too.
        rerun = [["ci", "pass", "github-actions", 10, "CI", "pull_request", 1], ["ci", "pending", "github-actions", 11, "CI", "pull_request", 1]]
        for checks in (rerun, rerun[::-1]):
            self.assertEqual(self.required(draft=False, required=["ci"], checks=checks), "ci\tpending\nrequired: not all passed\n")
        fixed = [["ci", "fail", "github-actions", 10, "CI", "pull_request", 1], ["ci", "pass", "github-actions", 11, "CI", "pull_request", 2]]
        self.assertEqual(self.required(draft=False, required=["ci"], checks=fixed), "ci\tpass\nrequired: all passed\n")
        # A skipped run that never started is older than a later failure: order is creation, not start.
        skipped = [["ci", "skipping", "github-actions", 10, "CI", "pull_request", 1], ["ci", "fail", "github-actions", 11, "CI", "pull_request", 2]]
        self.assertEqual(self.required(draft=False, required=["ci"], checks=skipped), "ci\tfail\nrequired: not all passed\n")

    def test_one_name_from_two_workflows_apps_or_kinds_counts_its_worst(self):
        workflows = [["deploy", "fail", "github-actions", 10, "Preview", "pull_request", 1],
                     ["deploy", "pass", "github-actions", 11, "Deploy", "pull_request", 2]]
        self.assertEqual(self.required(draft=False, required=["deploy"], checks=workflows),
                         "deploy\tfail\nrequired: not all passed\n")
        apps = [["ci", "pass", "github-actions", 11], ["ci", "pending", "other-ci", 10]]
        self.assertEqual(self.required(draft=False, required=["ci"], checks=apps), "ci\tpending\nrequired: not all passed\n")
        # A check with no app and a commit status of one name stay apart.
        kinds = [["ci", "fail", "", 10], ["ci", "pass", "", 0, "", "", 1, "status"]]
        self.assertEqual(self.required(draft=False, required=["ci"], checks=kinds), "ci\tfail\nrequired: not all passed\n")

    def test_a_context_required_from_one_app_counts_only_that_apps_checks(self):
        # A ruleset's integration_id, or classic protection's app_id: another app's pass, or a
        # commit status that can't say which app set it, isn't that check.
        for rule in ({"required": ["ci\t15368"]}, {"classic": ["ci\t15368"]}):
            with self.subTest(rule):
                other = [["ci", "pass", "999", 11], ["ci", "pass", "", 0, "", "", 1, "status"]]
                self.assertEqual(self.required(draft=False, checks=other, **rule), "ci\tnot reported\nrequired: not all passed\n")
                mixed = [["ci", "fail", "15368", 10], ["ci", "pass", "999", 11]]
                self.assertEqual(self.required(draft=False, checks=mixed, **rule), "ci\tfail\nrequired: not all passed\n")
                own = [["ci", "pass", "15368", 10], ["ci", "fail", "999", 11]]
                self.assertEqual(self.required(draft=False, checks=own, **rule), "ci\tpass\nrequired: all passed\n")

    def test_a_token_that_cannot_read_workflows_keeps_each_suite_and_fails_closed(self):
        # An App's token without the actions permission: a re-run stays in its suite, so its newest
        # counts; two suites of one name may be two workflows, so the worst counts.
        rerun = [["Lint", "fail", "github-actions", 10, "CI", "pull_request", 1], ["Lint", "pass", "github-actions", 11, "CI", "pull_request", 1]]
        self.assertEqual(self.required(draft=False, required=["Lint"], checks=rerun, no_actions=True),
                         "Lint\tpass\nrequired: all passed\n")
        two = [["ci", "fail", "github-actions", 10, "Test", "pull_request", 1], ["ci", "pass", "github-actions", 11, "Build", "pull_request", 2]]
        self.assertEqual(self.required(draft=False, required=["ci"], checks=two, no_actions=True),
                         "ci\tfail\nrequired: not all passed\n")

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
        args = [{"DRAFTS": str(tmp / "drafts.json"), "BODY": str(tmp / "body.md")}.get(arg, arg) for arg in args]
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

    def test_approve_carries_a_body_without_inline_comments(self):
        result = self.run_script("approve", "7", "abc", "", "BODY")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.splitlines()[-1]),
                         {"commit_id": "abc", "event": "APPROVE", "comments": [], "body": "Why?"})

    def test_a_review_requests_changes_with_its_comments_and_a_body(self):
        result = self.run_script("review", "7", "abc", "DRAFTS", "REQUEST_CHANGES", "BODY",
                                 drafts=[{"path": "a.ts", "line": 3, "body_file": "body.md"}])
        self.assertEqual(result.returncode, 0, result.stderr)
        # One request with the event and the body: a failed post leaves no pending review behind.
        self.assertIn("post a review on o/r#7 with event=REQUEST_CHANGES and the body in ", result.stdout)
        payload = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(payload["comments"], [{"path": "a.ts", "line": 3, "side": "RIGHT", "body": "Why?"}])
        self.assertEqual(payload["event"], "REQUEST_CHANGES")
        self.assertIn("body", payload)

    def test_a_review_never_approves_and_needs_a_body_with_its_event(self):
        for args in (("APPROVE", "BODY"), ("REQUEST_CHANGES",)):
            with self.subTest(args):
                result = self.run_script("review", "7", "abc", "DRAFTS", *args)
                self.assertEqual(result.returncode, 2)

    def test_dismiss_sends_the_message_file(self):
        result = self.run_script("dismiss", "7", "42", "BODY")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("api --method PUT repos/o/r/pulls/7/reviews/42/dismissals -f event=DISMISS -F message=@", result.stdout)


REVIEWED_GH = r"""#!/usr/bin/env python3
import os, sys
a = " ".join(sys.argv[1:])
if a.startswith("repo view"):
    print("o/r")
elif a.startswith("api graphql") and "viewer" in a and os.environ.get("VIEWER_FAILS"):
    sys.exit("temporary GitHub failure")
elif a.startswith("api graphql") and "viewer" in a:
    print("reviewer-app[bot]")
elif a.startswith("api --paginate repos/o/r/issues/7/timeline") and "review_dismissed" in a:
    print('{"review_id":"4","state":"approved"}')
    print('{"review_id":5,"state":"changes_requested"}')
elif a.startswith("api --paginate repos/o/r/pulls/7/reviews") and '"reviewer-app[bot]"' in a and '"PENDING"' in a:
    print('{"id":1,"state":"APPROVED","commit_id":"abc"}')
    print('{"id":4,"state":"DISMISSED","commit_id":"bcd"}')
    print('{"id":5,"state":"DISMISSED","commit_id":"cde"}')
    print('{"id":2,"state":"CHANGES_REQUESTED","commit_id":"def"}')
    print('{"id":3,"state":"COMMENTED","commit_id":"fed"}')
else:
    sys.exit(f"unexpected: gh {a}")
"""


class Reviewed(unittest.TestCase):
    def test_the_viewers_latest_submitted_review(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(tmp)])
        (tmp / "bin").mkdir()
        (tmp / "bin" / "gh").write_text(REVIEWED_GH)
        (tmp / "bin" / "gh").chmod(0o755)
        env = {**os.environ, "PATH": f"{tmp / 'bin'}:{os.environ['PATH']}"}
        viewer = subprocess.run([str(SCRIPT), "viewer"], capture_output=True, text=True, env=env)
        self.assertEqual((viewer.returncode, viewer.stdout), (0, "reviewer-app[bot]\n"), viewer.stderr)
        reviewed = subprocess.run([str(SCRIPT), "reviewed", "7"], capture_output=True, text=True, env=env)
        # The latest review is a comment; the request for changes before it still counts. The
        # latest approval is the one a push dismissed, which the timeline says was an approval.
        self.assertEqual((reviewed.returncode, json.loads(reviewed.stdout)),
                         (0, {"id": 3, "state": "COMMENTED", "commit_id": "fed",
                              "active": {"id": 2, "state": "CHANGES_REQUESTED", "commit_id": "def"},
                              "approved": {"id": 4, "state": "DISMISSED", "commit_id": "bcd"}}), reviewed.stderr)
        # A viewer it can't read fails the command, rather than reading as no reviews at all.
        failed = subprocess.run([str(SCRIPT), "reviewed", "7"], capture_output=True, text=True, env={**env, "VIEWER_FAILS": "1"})
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(failed.stdout, "")


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
        (self.repo / "lib.py").write_text("untracked\n")  # a module the head lacks can pass its tests
        self.assertNotIn("known", last())
        (self.repo / "lib.py").unlink()
        self.git("switch", "-q", "--detach", "layer1")  # this checkout isn't at the head target reads
        self.assertNotIn("known", last())

    def test_a_missing_branch_fails(self):
        result = self.target("--branch", "nope")
        self.assertEqual((result.returncode, result.stderr), (1, "no branch nope here or on origin\n"))
        self.assertEqual(self.target("--branch", "layer1", "--parent").returncode, 2)


if __name__ == "__main__":
    unittest.main()
