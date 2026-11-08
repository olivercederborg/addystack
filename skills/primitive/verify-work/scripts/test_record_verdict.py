"""record-verdict.sh in a real repo whose checkout isn't at the reviewed head: it records
from a temporary worktree at that head, names the branch, resolves evidence against the
caller's directory, and leaves no worktree behind. verdicts.py itself still refuses a
HEAD that isn't the reviewed head.
Run: python3 -m unittest discover -s verify-work/scripts"""
import json, os, pathlib, subprocess, tempfile, unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent
CONTEXT = json.dumps({"session_id": "s", "agent_id": "a1", "agent_type": "work-verifier"})


class RecordVerdict(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)])
        self.repo, self.scratch = self.tmp / "repo", self.tmp / "scratch"
        self.scratch.mkdir()
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.tmp)
        self.commit("a\n")
        self.git("switch", "-q", "-c", "feat")
        self.commit("b\n")
        self.base, self.head = self.git("rev-parse", "main").strip(), self.git("rev-parse", "feat").strip()
        self.git("switch", "-q", "main")

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, check=True, capture_output=True,
                              text=True).stdout

    def commit(self, text):
        (self.repo / "f").write_text(text)
        self.git("add", "f")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", text)

    def run_script(self, *args, script="record-verdict.sh", command=()):
        return subprocess.run([str(SCRIPTS / script), *command, self.base, self.head, *args], cwd=self.repo,
                              capture_output=True, text=True,
                              env={**os.environ, "VERIFY_WORK_HOOK_CONTEXT": CONTEXT, "TMPDIR": str(self.scratch)})

    def last_row(self):
        return json.loads((self.repo / ".git/verify-work/verdicts.tsv").read_text().splitlines()[-1].split("\t")[8])

    def assert_no_worktree_left(self):
        self.assertEqual(self.git("worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_records_the_reviewed_head_from_a_checkout_at_another_head(self):
        (self.repo / "log.txt").write_text("base 1 failure, head 0\n")  # only in this checkout
        result = self.run_script("--evidence", "parity=log.txt")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual((receipt["reviewed"]["head"], receipt["evidence"]),
                         (self.head, {"parity": [str((self.repo / "log.txt").resolve())]}))
        self.assertEqual(self.last_row()["branch"], "feat")
        self.assert_no_worktree_left()

    def test_names_no_branch_when_two_share_the_head_unless_told(self):
        self.git("branch", "twin", "feat")
        self.assertEqual(self.run_script().returncode, 0)
        self.assertNotIn("branch", self.last_row())
        self.assertEqual(self.run_script("--branch", "twin").returncode, 0)
        self.assertEqual(self.last_row()["branch"], "twin")

    def test_removes_its_worktree_when_recording_fails(self):
        result = self.run_script("--verdict", "not-done")
        self.assertEqual((result.returncode, result.stderr), (1, "a not-done verdict names at least one finding\n"))
        self.assert_no_worktree_left()

    def test_records_in_place_at_the_head(self):
        self.git("switch", "-q", "feat")
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.last_row()["branch"], "feat")
        self.git("branch", "twin", "feat")  # the same head on another branch records from a worktree
        self.assertEqual(self.run_script("--branch", "twin").returncode, 0)
        self.assertEqual(self.last_row()["branch"], "twin")
        self.assert_no_worktree_left()

    def test_verdicts_py_still_refuses_another_head_or_branch(self):
        result = self.run_script(script="verdicts.py", command=("record",))
        self.assertEqual((result.returncode, result.stderr), (1, f"HEAD isn't the reviewed head {self.head[:12]}\n"))
        self.git("switch", "-q", "feat")
        result = self.run_script("--branch", "other", script="verdicts.py", command=("record",))
        self.assertEqual((result.returncode, result.stderr), (1, "--branch other isn't the checked-out branch feat\n"))


if __name__ == "__main__":
    unittest.main()
