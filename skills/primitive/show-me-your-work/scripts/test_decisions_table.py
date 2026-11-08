"""decisions-table.sh: the PR table from a log's --pr rows (agent first, at most 5, stable
numbers, a warning for a row whose path or commit isn't in the diff), --calls, and exit 1
on the three malformed log shapes agents write by hand (another header, a short ts, mixed
columns).
Run: python3 -m unittest discover -s show-me-your-work/scripts"""
import pathlib, shutil, subprocess, tempfile, unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent
TABLE = SCRIPTS / "decisions-table.sh"
FIXTURES = SCRIPTS / "fixtures"
FILTER = "apps/web/src/features/bookkeeping/(receipts)/(export-readiness)/matches-vat-code-filter.utils.ts"
CARDS = "apps/web/src/features/bookkeeping/(receipts)/(export-readiness)/readiness-card.utils.ts"


class DecisionsTable(unittest.TestCase):
    def setUp(self):
        # Resolved, so a path under it reads as in the repo on macOS too, whose /var is a symlink.
        self.repo = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.repo)
        self.plans = pathlib.Path(tempfile.mkdtemp()).resolve()  # a plan saved outside the repo
        self.addCleanup(shutil.rmtree, self.plans)
        self.git("init", "-q", "-b", "main")
        self.git("remote", "add", "origin", "git@github.com:acme/shop.git")
        self.write(CARDS, "cards\n")
        self.write("src/gone.ts", "gone\n")
        self.write("old/src/config.ts", "unchanged\n")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("switch", "-q", "-c", "feat")
        self.write(FILTER, "filter\n")
        self.write(CARDS, "cards\nvat\n")
        self.write("src/config.ts", "config\n")
        self.write("src/my file.ts", "spaced\n")
        self.git("rm", "-q", "src/gone.ts")
        for name in ("a", "b", "c"):
            self.write(f"tests/{name}.test.ts", "test\n")
        self.commit("feat")
        self.head = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def write(self, path, text):
        (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / path).write_text(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)

    def table(self, *args):
        return subprocess.run([str(TABLE), *args], cwd=self.repo, capture_output=True, text=True)

    def rows(self, output):
        return [line for line in output.splitlines() if line.startswith("| D")]

    def test_renders_the_5472_mock(self):
        result = self.table(str(FIXTURES / "pr5472.tsv"), "main")
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = (FIXTURES / "pr5472.md").read_text().replace("<head>", self.head)
        self.assertEqual(result.stdout, expected)

    def test_a_forty_row_log_with_two_pr_rows_renders_two(self):
        result = self.table(str(FIXTURES / "forty-rows.tsv"), "main")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = self.rows(result.stdout)
        self.assertEqual(len(rows), 2)
        self.assertIn("🤖 agent · build", rows[0])
        self.assertIn("🧑 human · architect", rows[1])
        self.assertIn("Approving means you agree with D1–D2.", result.stdout)

    def test_caps_at_five_rows_agent_first(self):
        log = self.repo / "decisions.tsv"
        lines = ["ts\tphase\tdecision\twhy\tevidence\tresult\tpr"]
        for n in range(4):
            lines.append(f"2026-10-31T09:0{n}:00Z\tplan\tD{n + 1}. human call {n}\tplan\tsrc/config.ts:{n + 1}\tplanned\tyou")
        for n in range(3):
            lines.append(f"2026-10-31T10:0{n}:00Z\tbuild\tagent call {n}\tinstead of x\tsrc/config.ts:{n + 9}\tdone\tagent")
        log.write_text("\n".join(lines) + "\n")
        result = self.table(str(log), "main")
        rows = self.rows(result.stdout)
        self.assertEqual(len(rows), 5)
        self.assertEqual([("agent call" in row) for row in rows], [True, True, True, False, False])
        self.assertIn("+2 more in log.", result.stdout)
        self.assertIn("agree with D1, D2, D5, D6, D7.", result.stdout)

    def test_warns_on_a_row_whose_path_is_not_in_the_diff(self):
        log = self.repo / "decisions.tsv"
        log.write_text("ts\tphase\tdecision\twhy\tevidence\tresult\tpr\n"
                       "2026-10-31T09:00:00Z\tbuild\tkept the old reader\tinstead of a rewrite\tsrc/old.ts:4\tdone\tagent\n"
                       "2026-10-31T09:01:00Z\tbuild\tcached the config\tinstead of reparsing\tsrc/config.ts:2\tdone\tagent\n")
        result = self.table(str(log), "main")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("src/old.ts isn't in main...HEAD", result.stderr)
        self.assertEqual(len(self.rows(result.stdout)), 1)
        self.assertIn("cached the config", result.stdout)

    def log_rows(self, *rows):
        log = self.repo / "decisions.tsv"
        log.write_text("ts\tphase\tdecision\twhy\tevidence\tresult\tpr\n" + "".join(
            f"2026-10-31T09:{n:02d}:00Z\t{row}\n" for n, row in enumerate(rows)))
        return log

    def test_numbers_stay_put_when_a_call_is_added(self):
        before = self.log_rows("plan\tD1. CSV only\tinstead of JSON\tsrc/config.ts:1\tplanned\tyou")
        self.assertIn("| D1 | CSV only |", self.table(str(before), "main").stdout)
        after = self.log_rows("plan\tD1. CSV only\tinstead of JSON\tsrc/config.ts:1\tplanned\tyou",
                              "build\ttab delimiter\tinstead of commas\tsrc/config.ts:1\tdone\tagent")
        rows = self.rows(self.table(str(after), "main").stdout)
        self.assertEqual([row.split(" | ")[1] for row in rows], ["tab delimiter", "CSV only"])
        self.assertTrue(rows[0].startswith("| D2 |") and rows[1].startswith("| D1 |"))

    def test_a_reimport_or_relabeled_row_replaces_the_earlier_one(self):
        plan = self.plans / "plan.md"
        plan.write_text("- D1. CSV only\n- D2. Inclusive dates [assumed]\n")
        log = self.repo / "imported.tsv"
        for _ in range(2):
            subprocess.run([str(SCRIPTS / "log.sh"), "import", str(log), str(plan)], check=True, capture_output=True)
        subprocess.run([str(SCRIPTS / "log.sh"), "--pr", "you", str(log), "build", "D1. CSV only",
                        "instead of JSON", "src/config.ts:1", "done"], check=True, capture_output=True)
        result = self.table(str(log), "main")
        rows = self.rows(result.stdout)
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0].startswith("| D2 | Inclusive dates | 🤖 agent · plan |") and rows[0].endswith("| plan |"))
        self.assertTrue(rows[1].startswith("| D1 | CSV only | 🧑 human · build | JSON |"))
        self.assertIn("config.ts:1", rows[1])

    def test_text_joins_a_labeled_import_and_a_reimport_keeps_the_built_row(self):
        plan = self.plans / "plan.md"
        plan.write_text("- D1. CSV only\n")
        log = self.repo / "joined.tsv"
        run = lambda *args: subprocess.run([str(SCRIPTS / "log.sh"), *args], check=True, capture_output=True)
        run("import", str(log), str(plan))
        run("--pr", "you", str(log), "build", "CSV only", "instead of JSON", "src/config.ts:1", "done")
        run("import", str(log), str(plan))
        rows = self.rows(self.table(str(log), "main").stdout)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].startswith("| D1 | CSV only | 🧑 human · build | JSON |"))

    def test_plan_labels_keep_their_numbers(self):
        log = self.log_rows("plan\tD1. CSV only\tplan\t/plans/p.md:1\tplanned\tyou",
                            "build\tcache config\tinstead of X\tsrc/config.ts:1\tdone\tagent",
                            "plan\tD3. Keep order\tplan\t/plans/p.md:2\tplanned\tyou",
                            "plan\tD2. Inclusive dates\tplan\t/plans/p.md:3\tplanned\tagent")
        rows = self.rows(self.table(str(log), "main").stdout)
        self.assertEqual([row.split(" | ")[0:2] for row in rows],
                         [["| D2", "Inclusive dates"], ["| D4", "cache config"], ["| D1", "CSV only"], ["| D3", "Keep order"]])

    def test_evidence_needs_the_whole_path_and_a_commit_can_carry_it(self):
        head = self.git("rev-parse", "HEAD").strip()
        log = self.log_rows("build\tsuffix only\tinstead of X\told/src/config.ts:1\tdone\tagent",
                            "build\tabsolute code path\tinstead of X\t/tmp/missing.ts:1\tdone\tagent",
                            f"build\tchanged by commit\tinstead of X\tdocs/plan.md:1 commit {head[:8]}\tdone\tagent")
        result = self.table(str(log), "main")
        self.assertEqual([row.split(" | ")[1] for row in self.rows(result.stdout)], ["changed by commit"])
        self.assertIn("old/src/config.ts isn't in", result.stderr)
        self.assertIn("/tmp/missing.ts isn't in", result.stderr)

    def test_a_deleted_file_links_to_the_base(self):
        result = self.table(str(self.log_rows("build\tremoved the old file\tinstead of X\tsrc/gone.ts:1\tdone\tagent")), "main")
        self.assertIn(f"[`gone.ts:1` (deleted)](https://github.com/acme/shop/blob/{self.base}/src/gone.ts#L1)",
                      result.stdout)

    def test_absolute_paths_spaced_plans_and_a_second_sha(self):
        head = self.git("rev-parse", "HEAD").strip()
        top = self.repo.resolve()
        log = self.log_rows(f"build\tabsolute in the repo\tinstead of X\t{top}/src/config.ts:1\tdone\tagent",
                            "plan\tD1. spaced plan\tplan\t/plans/plan folder/plan.md:1\tplanned\tagent",
                            f"architect\tsecond sha\tinstead of B\tissue #1234567; commit {head}\tpicked\tagent")
        result = self.table(str(log), "main")
        rows = self.rows(result.stdout)
        self.assertEqual([row.split(" | ")[1] for row in rows], ["spaced plan", "absolute in the repo", "second sha"])
        self.assertTrue(rows[0].endswith("| plan |"))
        self.assertIn("config.ts:1", rows[1])
        self.assertIn(f"/commit/{head})", rows[2])

    def test_a_correction_under_a_plan_number_lands_on_it(self):
        log = self.log_rows("plan\tD1. CSV only\tplan\t/plans/p.md:1\tplanned\tyou",
                            "build\tcache config\tinstead of reparse\tsrc/config.ts:1\tdone\tagent",
                            "plan\tD2. Inclusive dates\tplan\t/plans/p.md:2\tplanned\tagent",
                            "build\tD2. Exclusive dates\tinstead of inclusive\tsrc/config.ts:1\tdone\tagent")
        rows = self.rows(self.table(str(log), "main").stdout)
        self.assertEqual([row.split(" | ")[0:2] for row in rows],
                         [["| D2", "Exclusive dates"], ["| D3", "cache config"], ["| D1", "CSV only"]])

    def test_a_plan_imported_after_architect_keeps_every_decision(self):
        architect_then_plan = (f"architect\tshape 1: one loadConfig export\tinstead of a class\tcommit {self.head}\tpicked\tyou",
                               "plan\tD1. CSV only\tplan\t/plans/p.md:1\tplanned\tyou",
                               "plan\tD2. Inclusive dates\tplan\t/plans/p.md:2\tplanned\tyou",
                               "plan\tD3. Keep order\tplan\t/plans/p.md:3\tplanned\tagent")
        result = self.table(str(self.log_rows(*architect_then_plan)), "main")
        rows = self.rows(result.stdout)
        self.assertEqual([row.split(" | ")[0:2] for row in rows],
                         [["| D3", "Keep order"], ["| D1", "CSV only"], ["| D2", "Inclusive dates"],
                          ["| D4", "shape 1: one loadConfig export"]])
        self.assertIn("agree with D1–D4.", result.stdout)
        corrected = self.log_rows(*architect_then_plan,
                                  "build\tD1. CSV and JSON\tinstead of CSV only\tsrc/config.ts:1\tdone\tagent")
        rows = self.rows(self.table(str(corrected), "main").stdout)
        self.assertEqual([row.split(" | ")[0:2] for row in rows],
                         [["| D1", "CSV and JSON"], ["| D3", "Keep order"], ["| D2", "Inclusive dates"],
                          ["| D4", "shape 1: one loadConfig export"]])

    def test_a_timestamp_is_not_a_path(self):
        log = self.log_rows("build\tpicked at a time\tinstead of X\tsrc/config.ts:1 at 2026-10-31T09:10:00Z\tdone\tagent")
        result = self.table(str(log), "main")
        self.assertEqual(len(self.rows(result.stdout)), 1)
        self.assertEqual(result.stderr, "")

    def test_prints_nothing_when_every_row_is_stale(self):
        result = self.table(str(self.log_rows("build\told reader\tinstead of x\tsrc/old.ts:4\tdone\tagent")), "main")
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertIn("src/old.ts isn't in main...HEAD", result.stderr)

    def test_a_commit_outside_the_range_is_left_out(self):
        base = self.git("rev-parse", "main").strip()
        inside = self.git("rev-parse", "HEAD").strip()
        log = self.log_rows(f"architect\tcontract from the layer below\tinstead of x\tcommit {base[:9]}\tpicked\tagent",
                            f"architect\tcontract here\tinstead of y\tcommit {inside[:9]}\tpicked\tagent")
        result = self.table(str(log), "main")
        self.assertEqual([row.split(" | ")[1] for row in self.rows(result.stdout)], ["contract here"])
        self.assertIn(f"commit {base[:9]} isn't in main...HEAD", result.stderr)
        self.assertIn(f"/commit/{inside})", result.stdout)

    def test_a_path_with_a_space(self):
        result = self.table(str(self.log_rows("build\tspaced\tinstead of x\tsrc/my file.ts:1\tdone\tagent")), "main")
        self.assertIn("[`my file.ts:1`]", result.stdout)
        self.assertIn("**Read in code:** `src/my file.ts`", result.stdout)

    def test_one_skim_file_is_singular(self):
        self.git("switch", "-q", "-c", "solo", "main")
        self.write(CARDS, "cards\nsolo\n")
        self.write("src/config.ts", "config\n")
        self.commit("solo")
        result = self.table(str(self.log_rows("build\tcached\tinstead of x\tsrc/config.ts:1\tdone\tagent")), "main")
        self.assertIn("**Skim:** 1 file: `apps/web", result.stdout)

    def test_exits_1_on_an_impossible_ts(self):
        log = self.repo / "bad.tsv"
        log.write_text("ts\tphase\tdecision\twhy\tevidence\tresult\tpr\n"
                       "2026-99-99T99:99:99Z\tbuild\tx\ty\tsrc/config.ts:1\tdone\tagent\n")
        self.assertEqual(self.table(str(log), "main").returncode, 1)

    def test_exits_1_on_each_malformed_shape(self):
        for name, message in (("malformed-header", "header is not log.sh's"),
                              ("malformed-ts", "is not a real YYYY-MM-DDTHH:MM:SSZ"),
                              ("malformed-columns", "5 columns, header has 7")):
            with self.subTest(name):
                result = self.table(str(FIXTURES / f"{name}.tsv"), "main")
                self.assertEqual(result.returncode, 1)
                self.assertIn(message, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_no_pr_rows_prints_nothing(self):
        log = self.repo / "decisions.tsv"
        log.write_text("ts\tphase\tdecision\twhy\tevidence\tresult\n2026-10-31T09:00:00Z\tbuild\tx\ty\tz\tok\n")
        result = self.table(str(log), "main")
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_calls_lists_every_agent_row(self):
        result = self.table("--calls", str(FIXTURES / "pr5472.tsv"))
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith('- "Has VAT code" means start export accepts'))
        self.assertTrue(lines[0].endswith(f"{FILTER}:28"))


if __name__ == "__main__":
    unittest.main()
