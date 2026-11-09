"""packet.sh in a real repo, with a stub `gh` for the PR target: one prompt with the lenses
inlined and every placeholder filled, a packet without lockfiles or binaries, and a
baseline equal to `git diff --shortstat` over the files the packet keeps.
Run: python3 -m unittest discover -s review-loop/scripts"""
import os, pathlib, subprocess, tempfile, unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent
LENSES = (SCRIPTS.parent / "references" / "review-lenses.md").read_text().strip()

GH = r"""#!/usr/bin/env python3
import os, sys
a = " ".join(sys.argv[1:])
if a.startswith("pr view 7 --json baseRefName"):
    print(f"main\t{os.environ['BASE_SHA']}\t{os.environ['HEAD_SHA']}\tmain\thttps://github.com/o/r/pull/7")
elif a.startswith("pr view 7 --json title,body"):
    print("# Cap retries\n\nRetries stop after 3.")
elif a.startswith("pr view 7 --json closingIssuesReferences"):
    print("https://github.com/o/r/issues/3")
elif a.startswith("issue view https://github.com/o/r/issues/3"):
    print("### Retries never stop (https://github.com/o/r/issues/3)\n\nA failing job retries forever.")
else:
    sys.exit(f"unexpected: gh {a}")
"""


class Packet(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)])
        (self.tmp / "bin").mkdir()
        stub = self.tmp / "bin" / "gh"
        stub.write_text(GH)
        stub.chmod(0o755)
        self.repo = self.tmp / "repo"
        self.git("init", "-q", "--bare", "-b", "main", str(self.tmp / "origin.git"), cwd=self.tmp)
        self.git("clone", "-q", str(self.tmp / "origin.git"), str(self.repo), cwd=self.tmp)
        self.commit({"retry.ts": "a\n"})
        self.base = self.git("rev-parse", "HEAD")
        self.commit({"retry.ts": "a\nb\n", "yarn.lock": "x\n", "logo.png": b"\x89PNG\x00\x01"})
        self.head = self.git("rev-parse", "HEAD")
        self.git("push", "-q", "origin", "main", f"{self.head}:refs/pull/7/head")
        (self.tmp / "checks.txt").write_text("npm test → 12 passed\n")

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, files):
        for name, text in files.items():
            path = self.repo / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(text) if isinstance(text, bytes) else path.write_text(text)
            self.git("add", name)
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")

    def packet(self, *args, code=0):
        result = subprocess.run([str(SCRIPTS / "packet.sh"), *args], capture_output=True, text=True, cwd=self.repo,
                                env={**os.environ, "PATH": f"{self.tmp / 'bin'}:{os.environ['PATH']}",
                                     "BASE_SHA": self.base, "HEAD_SHA": self.head})
        self.assertEqual(result.returncode, code, result.stderr)
        return dict(line.split(": ", 1) for line in result.stdout.splitlines())

    def read(self, out):
        return pathlib.Path(out["packet"]).read_text(), pathlib.Path(out["prompt"]).read_text()

    def test_a_range_leaves_out_the_lockfile_and_binary_and_inlines_the_lenses(self):
        out = self.packet("range", f"{self.base}..{self.head}", "--checks", str(self.tmp / "checks.txt"))
        packet, prompt = self.read(out)
        self.assertIn("- retry.ts (+1 -0)\n\nLeft out: logo.png (binary), yarn.lock (lockfile)\n", packet)
        self.assertNotIn("yarn.lock b/yarn.lock", packet)
        self.assertEqual(out["baseline"], self.git("diff", "--shortstat", f"{self.base}...{self.head}", "--",
                                                   "retry.ts"))
        self.assertIn(LENSES, prompt)
        self.assertIn(f"Packet: {out['packet']}\n\nChecks already run:\nnpm test → 12 passed\nRerun none", prompt)
        self.assertNotRegex(prompt.replace(LENSES, ""), r"\{[a-z]+\}")
        self.assertEqual(self.packet("range", f"{self.base}..{self.head}", "--checks", str(self.tmp / "checks.txt")),
                         out)
        self.assertEqual(self.read(out)[1], prompt)  # the same target writes the same prompt

    def test_from_a_subfolder_it_reads_the_whole_repo_and_the_files_given_from_there(self):
        self.commit({"sub/a.ts": "s\n"})
        self.head = self.git("rev-parse", "HEAD")
        (self.tmp / "kit").symlink_to(SCRIPTS.parent)  # run by a path that holds only from sub/
        result = subprocess.run(["../../kit/scripts/packet.sh", "range", f"{self.base}..{self.head}", "--checks",
                                 "../../checks.txt"], capture_output=True, text=True, cwd=self.repo / "sub")
        self.assertEqual(result.returncode, 0, result.stderr)
        out = dict(line.split(": ", 1) for line in result.stdout.splitlines())
        self.assertIn("- retry.ts (+1 -0)\n- sub/a.ts (+1 -0)\n", self.read(out)[0])
        self.assertIn("npm test → 12 passed", self.read(out)[1])
        only = self.packet("range", f"{self.base}..{self.head}", "--only", "sub/")
        self.assertIn("## Files\n\n- sub/a.ts (+1 -0)\n\nLeft out: nothing\n", self.read(only)[0])
        self.assertEqual(only["baseline"], "1 file changed, 1 insertion(+)")

    def test_a_moved_file_is_its_rename_and_the_lines_that_changed(self):
        # A move used to hold the whole file twice, as a deletion and an addition.
        body = "".join(f"line {n}\n" for n in range(40))
        self.commit({"old/job.ts": body})
        base = self.git("rev-parse", "HEAD")
        (self.repo / "new").mkdir()
        self.git("mv", "old/job.ts", "new/job.ts")
        self.commit({"new/job.ts": body.replace("line 7\n", "line seven\n")})
        self.git("config", "diff.renames", "false")  # the packet finds moves whatever the user's config says
        out = self.packet("range", f"{base}..{self.git('rev-parse', 'HEAD')}")
        packet = self.read(out)[0]
        self.assertIn("## Files\n\n- {old => new}/job.ts (+1 -1)\n\nLeft out: nothing\n", packet)
        self.assertIn("rename from old/job.ts\nrename to new/job.ts\n", packet)
        self.assertIn("-line 7\n+line seven\n", packet)
        self.assertNotIn("line 3\n", packet.replace(" line 3\n", ""))  # only as context, if at all
        self.assertEqual(out["baseline"], "1 file changed, 1 insertion(+), 1 deletion(-)")

    def test_a_kept_lockfile_counts(self):
        out = self.packet("range", f"{self.base}..{self.head}", "--keep", "yarn.lock")
        self.assertIn("yarn.lock b/yarn.lock", self.read(out)[0])
        self.assertEqual(out["baseline"], "2 files changed, 2 insertions(+)")

    def test_a_pr_packet_holds_its_description_and_linked_issue(self):
        packet, prompt = self.read(self.packet("pr", "7"))
        self.assertIn("## PR description\n\n# Cap retries\n\nRetries stop after 3.\n", packet)
        self.assertIn("A failing job retries forever.", packet)
        self.assertIn("Target: PR #7 (https://github.com/o/r/pull/7)\n", prompt)
        self.assertIn("Spec: the packet's PR description, Linked issues sections\n", prompt)

    def test_a_pr_with_unpushed_fixes_packs_the_local_branch(self):
        self.commit({"retry.ts": "a\nb\nfix\n"})  # committed by the loop, not pushed yet
        out = self.packet("pr", "7")
        self.assertIn(f"Head: {self.git('rev-parse', 'HEAD')}\n", self.read(out)[0])
        self.assertIn("Target: PR #7 (https://github.com/o/r/pull/7) at local main, ahead of the PR\n",
                      self.read(out)[1])
        self.assertEqual(out["baseline"], "1 file changed, 2 insertions(+)")

    def test_working_changes_keep_their_base_after_a_fix_commits(self):
        (self.repo / "new.ts").write_text("n\n")
        (self.repo / "retry.ts").write_text("a\nb\nc\n")
        round1 = self.packet("working")
        self.assertEqual(round1["baseline"], "2 files changed, 2 insertions(+)")
        self.commit({"fix.ts": "f\n"})
        self.assertEqual(self.packet("working", "--base", self.head)["baseline"], "3 files changed, 3 insertions(+)")

    def test_working_leaves_the_users_index_alone(self):
        (self.repo / "new.ts").write_text("n\n")
        (self.repo / "staged.ts").write_text("t\n")
        self.git("add", "staged.ts")
        before = self.git("status", "--porcelain")
        out = self.packet("working")
        self.assertIn("- new.ts (+1 -0)\n- staged.ts (+1 -0)\n", self.read(out)[0])
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertEqual(before, "A  staged.ts\n?? new.ts")

    def test_working_changes_count_untracked_files_and_hide_the_packet(self):
        (self.repo / "new.ts").write_text("n\n")
        (self.repo / "retry.ts").write_text("a\nb\nc\n")
        out = self.packet("working")
        self.assertIn("+n", self.read(out)[0])
        self.assertEqual(out["baseline"], "2 files changed, 2 insertions(+)")
        self.assertNotIn(".review-loop", self.git("status", "--porcelain", "--untracked-files=all"))

    def test_round_two_needs_the_previous_and_settled_findings(self):
        self.packet("range", f"{self.base}..{self.head}", "--round", "2", code=2)
        (self.tmp / "previous.md").write_text("1 · Blocker · retries forever → fixed in abc123\n")
        (self.tmp / "settled.md").write_text("2 · Optional · rename → follow-up\n")
        prompt = self.read(self.packet("range", f"{self.base}..{self.head}", "--round", "2", "--previous",
                                       str(self.tmp / "previous.md"), "--settled", str(self.tmp / "settled.md")))[1]
        self.assertIn("Round 2. Previous findings and their fixes:\n1 · Blocker · retries forever → fixed in abc123\n"
                      "Settled, each with why:\n2 · Optional · rename → follow-up\n", prompt)

    def test_a_plan_has_no_diff_or_size_and_clean_removes_the_packets(self):
        (self.tmp / "plan.md").write_text("Cap retries at 3.\n")
        out = self.packet("plan", str(self.tmp / "plan.md"))
        packet, prompt = self.read(out)
        self.assertEqual((out["baseline"], "## Plan\n\nCap retries at 3.\n" in packet, "## Diff" in packet),
                         ("none (a plan has no size)", True, False))
        self.assertTrue(prompt.startswith("Review this plan."))
        self.assertIn("Report every gap, risk, and simpler option", prompt)
        self.packet("clean")
        self.assertFalse((self.repo / ".review-loop").exists())


if __name__ == "__main__":
    unittest.main()
