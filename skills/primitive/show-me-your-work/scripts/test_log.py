"""log.sh: the pr column, the evidence refusal for --pr rows, import from a plan, the
header on an empty file, and logs that already use the 6-column header.
Run: python3 -m unittest discover -s show-me-your-work/scripts"""
import pathlib, re, subprocess, tempfile, unittest

LOG_SH = pathlib.Path(__file__).resolve().parent / "log.sh"
HEADER6 = "ts\tphase\tdecision\twhy\tevidence\tresult"
HEADER7 = HEADER6 + "\tpr"


class LogSh(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.dir)])
        self.log = self.dir / "decisions.tsv"

    def run_log(self, *args):
        return subprocess.run([str(LOG_SH), *args], capture_output=True, text=True)

    def rows(self):
        return [line.split("\t") for line in self.log.read_text().splitlines()]

    def test_writes_the_header_into_an_empty_file(self):
        self.log.write_text("")
        result = self.run_log(str(self.log), "build", "picked a", "simpler", "commit a1b2c3d", "done")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines()[0], HEADER7)
        self.assertEqual(len(self.rows()), 2)

    def test_a_row_without_pr_leaves_the_column_empty(self):
        self.run_log(str(self.log), "build", "ran tests", "proof", "make test", "green")
        self.assertEqual(self.rows()[1][1:], ["build", "ran tests", "proof", "make test", "green", ""])
        self.assertRegex(self.rows()[1][0], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_pr_row_with_a_path_line_or_sha(self):
        for evidence in ("src/filter.ts:28", "commit a1b2c3d", "9f8e7d6c5b4a", "Dockerfile:1"):
            result = self.run_log("--pr", "agent", str(self.log), "build", "has means accepted",
                                  "instead of has means set", evidence, "done")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([row[6] for row in self.rows()[1:]], ["agent"] * 4)

    def test_refuses_a_pr_row_without_a_code_pointer(self):
        for evidence in ("the docs", "see PR 12", "ABCDEFG", "at 12:30", "2026-10-31T09:10:00Z"):
            result = self.run_log("--pr", "you", str(self.log), "build", "x", "y", evidence, "z")
            self.assertEqual(result.returncode, 1)
            self.assertIn("path:line or a commit SHA", result.stderr)
        self.assertEqual(len(self.rows()), 1)

    def test_refuses_an_unknown_pr_value(self):
        result = self.run_log("--pr", "coordinator", str(self.log), "b", "x", "y", "a.ts:1", "z")
        self.assertEqual(result.returncode, 1)
        self.assertIn("you or agent", result.stderr)

    def test_import_maps_assumed_to_agent_and_the_rest_to_you(self):
        plan = self.dir / "plan.md"
        plan.write_text("Goal: export CSV\nDecisions:\n- D1. CSV only, no JSON\n"
                        "- D2. Dates are inclusive [assumed]\nNot in scope: D9 isn't a decision\n"
                        "  D3. Keep the old column order\n")
        result = self.run_log("import", str(self.log), str(plan))
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = self.rows()[1:]
        self.assertEqual([(row[1], row[2], row[6]) for row in rows], [
            ("plan", "D1. CSV only, no JSON", "you"),
            ("plan", "D2. Dates are inclusive", "agent"),
            ("plan", "D3. Keep the old column order", "you"),
        ])
        self.assertEqual([row[4] for row in rows], [f"{plan}:3", f"{plan}:4", f"{plan}:6"])

    def test_an_old_six_column_log_keeps_its_shape_and_refuses_pr(self):
        self.log.write_text(HEADER6 + "\n")
        self.assertEqual(self.run_log(str(self.log), "b", "x", "y", "a.ts:1", "z").returncode, 0)
        self.assertEqual(len(self.rows()[1]), 6)
        result = self.run_log("--pr", "agent", str(self.log), "b", "x", "y", "a.ts:1", "z")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no pr column", result.stderr)

    def test_refuses_a_log_with_another_header(self):
        self.log.write_text("when\twhat\n")
        result = self.run_log(str(self.log), "b", "x", "y", "a.ts:1", "z")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.log.read_text(), "when\twhat\n")

    def test_formula_cells_stay_text(self):
        self.run_log(str(self.log), "b", "=SUM(A1)", "-y", "a.ts:1", "@z")
        self.assertEqual(self.rows()[1][2:4], ["'=SUM(A1)", "'-y"])


if __name__ == "__main__":
    unittest.main()
