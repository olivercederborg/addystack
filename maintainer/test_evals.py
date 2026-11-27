import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import evals  # noqa: E402

SCENARIO = {
    "id": "01-basic",
    "skill": "demo",
    "prompt": "is this done?",
    "preamble": "Use no gh and no network.",
    "cwd": "/tmp/demo-eval",
    "setup": "./setup.sh /tmp/demo-eval",
    "turns": ["fix all"],
    "assertions": ["Status opens with a red marker", "Every turn ends with Next"],
    "folder": "/repo/evals/demo",
}

GRADES = {"results": [
    {"n": 1, "pass": True, "evidence": "🔴 **Not done.**"},
    {"n": 2, "pass": False, "evidence": "turn 2 ends with Done"},
]}


def grades(*passes):
    return json.dumps({"results": [
        {"n": n, "pass": ok, "evidence": "quote"} for n, ok in enumerate(passes, 1)
    ]})


class BriefTest(unittest.TestCase):
    def test_no_assertions_leak(self):
        text = evals.brief(SCENARIO)
        for assertion in SCENARIO["assertions"]:
            self.assertNotIn(assertion, text)
        self.assertTrue(text.startswith(f"{evals.REPLY_RULES}\nWork in /tmp/demo-eval.\nUse no gh and no network.\n"
                                        f"{evals.LIMITS}\n"))
        self.assertTrue(text.endswith("\n\nis this done?"))

    def test_opt_in_line_comes_first(self):
        for variants in [{}, {"demo": "/tmp/new-demo"}]:
            with self.subTest(variants=variants):
                first = evals.brief(SCENARIO, variants).splitlines()[0]
                self.assertEqual(first, "Reply rules: on. This run plays Oliver's own session.")

    def test_variant_line_follows_the_opt_in(self):
        line = evals.brief(SCENARIO, {"demo": "/tmp/new-demo"}).splitlines()[1]
        self.assertIn("/tmp/new-demo/SKILL.md", line)
        self.assertIn("in place of the installed demo skill", line)

    def test_each_variant_gets_a_line_and_children_get_them_too(self):
        variants = {"autopilot": "/tmp/k/autopilot", "review-loop": "/tmp/k/review-loop", "build": "/tmp/k/build"}
        lines = evals.brief(SCENARIO, variants, cwd="/tmp/trial/repo").splitlines()
        # brief resolves each folder, and macOS resolves /tmp to /private/tmp.
        k = pathlib.Path("/tmp/k").resolve()
        self.assertEqual(lines[1:5], [
            f"For this whole session, read {k}/autopilot/SKILL.md and follow it in place of the installed "
            "autopilot skill.",
            f"For this whole session, read {k}/review-loop/SKILL.md and follow it in place of the installed "
            "review-loop skill.",
            f"For this whole session, read {k}/build/SKILL.md and follow it in place of the installed build skill.",
            "Copy the lines above, and this one, into the brief of any child task or subagent you start.",
        ])
        self.assertEqual(lines[5], "Work in /tmp/trial/repo.")

    def test_relative_cwd_needs_start(self):
        with self.assertRaisesRegex(evals.EvalError, "relative cwd, so only start can brief it"):
            evals.brief({**SCENARIO, "cwd": "repo"})

    def test_relative_paths_become_absolute(self):
        variant = evals.brief(SCENARIO, {"demo": "new-demo"}).splitlines()[1]
        self.assertIn(f"read {pathlib.Path.cwd() / 'new-demo' / 'SKILL.md'} ", variant)
        grading = evals.grade_brief(SCENARIO, "out/demo/01-basic.replies.md")
        self.assertIn(f"the role, interaction mode, and target of each `delegate_task` call it made: {pathlib.Path.cwd() / 'out/demo/01-basic.replies.md'}\n", grading)

    def test_variant_without_skill_fails(self):
        err = io.StringIO()
        with mock.patch.object(evals, "load_scenarios", return_value={("demo", "01-basic"): SCENARIO}), \
                contextlib.redirect_stderr(err), tempfile.TemporaryDirectory() as folder:
            code = evals.main(["start", "demo", "01-basic", folder, "--variant", folder])
        self.assertEqual(code, 1)
        self.assertIn("no SKILL.md in", err.getvalue())

    def test_cwd_only(self):
        bare = {"skill": "demo", "id": "02", "prompt": "hi", "cwd": "/tmp/x"}
        self.assertEqual(evals.brief(bare), f"{evals.REPLY_RULES}\nWork in /tmp/x.\n{evals.LIMITS}\n\nhi")

    def test_every_brief_tells_the_player_to_pass_its_limits(self):
        # The Oct 26, 2026 player called verify-work with no arguments, and its verifier
        # ran gh, git fetch, and ssh in a session that allowed none of them.
        for (skill, scenario_id), scenario in evals.load_scenarios().items():
            if not scenario.get("cwd"):
                continue
            with self.subTest(scenario=f"{skill}/{scenario_id}"):
                lines = evals.brief(scenario, cwd="/tmp/trial").splitlines()
                self.assertIn(evals.LIMITS, lines)

    def test_missing_cwd_exits_1(self):
        no_cwd = {k: v for k, v in SCENARIO.items() if k != "cwd"}
        err = io.StringIO()
        with mock.patch.object(evals, "load_scenarios", return_value={("demo", "01-basic"): no_cwd}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(evals.main(["start", "demo", "01-basic", "/tmp/unused"]), 1)
        self.assertIn("demo/01-basic has no cwd", err.getvalue())


class StartTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name).resolve()
        self.evals = self.root / "evals" / "demo"
        self.evals.mkdir(parents=True)
        # The stub records its argument and where it ran, the way a real setup builds cwd.
        (self.evals / "setup.sh").write_text('mkdir -p "$1" && pwd > "$1/ran-from"\n')
        self.scenario = {**SCENARIO, "cwd": "repo", "setup": "bash ./setup.sh {cwd}", "folder": str(self.evals)}

    def skill(self, name, folder):
        path = self.root / folder
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n\n# {name}\n")
        return str(path)

    def test_relative_cwd_resolves_in_the_trial_folder(self):
        out = self.root / "side" / "t1"
        text = evals.start(out, self.scenario, {})
        repo = out / "demo" / "01-basic" / "repo"
        self.assertEqual((repo / "ran-from").read_text().strip(), str(self.evals))
        self.assertIn(f"\nWork in {repo}.\n", text)
        self.assertEqual(evals.load_trial(out, self.scenario),
                         {"cwd": str(repo), "brief": text, "variants": {}, "rules": None})

    def test_absolute_cwd_and_plain_setup_run_as_written(self):
        target = self.root / "abs"
        scenario = {**self.scenario, "cwd": str(target), "setup": f"bash ./setup.sh {target}"}
        text = evals.start(self.root / "out", scenario, {})
        self.assertTrue((target / "ran-from").exists())
        self.assertEqual(text, evals.brief(scenario))

    def test_cwd_with_a_space_and_a_semicolon_stays_one_argument(self):
        out = self.root / "eval runs;touch pwned" / "t1"
        evals.start(out, self.scenario, {})
        repo = out / "demo" / "01-basic" / "repo"
        self.assertEqual((repo / "ran-from").read_text().strip(), str(self.evals))
        self.assertFalse((self.root / "eval").exists())
        self.assertFalse((self.evals / "pwned").exists())
        grading = evals.grade_brief(self.scenario, out / "demo" / "01-basic.replies.md")
        self.assertIn(f"Setup, run from {self.evals}: bash ./setup.sh '{repo}'\n", grading)

    def test_failing_setup_stops(self):
        scenario = {**self.scenario, "setup": "echo broke >&2; exit 3"}
        with self.assertRaisesRegex(evals.EvalError, "setup exited 3: broke"):
            evals.start(self.root / "out", scenario, {})
        self.assertIsNone(evals.load_trial(self.root / "out", scenario))

    def test_cli_names_variants_from_their_frontmatter(self):
        build, review = self.skill("build", "kit/build"), self.skill("review-loop", "kit/rl")
        out = io.StringIO()
        with mock.patch.object(evals, "load_scenarios", return_value={("demo", "01-basic"): self.scenario}), \
                contextlib.redirect_stdout(out):
            code = evals.main(["start", "demo", "01-basic", str(self.root / "o"), "--variant", build,
                               "--variant", review])
        self.assertEqual(code, 0)
        self.assertIn(f"read {build}/SKILL.md and follow it in place of the installed build skill.", out.getvalue())
        self.assertIn(f"read {review}/SKILL.md and follow it in place of the installed review-loop skill.",
                      out.getvalue())
        trial = evals.load_trial(self.root / "o", self.scenario)
        self.assertEqual(trial["variants"], {"build": build, "review-loop": review})
        self.assertEqual(trial["brief"] + "\n", out.getvalue())

    def test_two_variants_of_one_skill_fail(self):
        dirs = [self.skill("build", "a/build"), self.skill("build", "b/build")]
        with self.assertRaisesRegex(evals.EvalError, "two --variant dirs name the build skill"):
            evals.variant_names(dirs)

    def rules(self, *files):
        folder = self.root / "rules"
        for name in files:
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_text("rules")
        return str(folder)

    def test_rules_folder_replaces_the_installed_rules(self):
        rules = self.rules("replies.md", "reply-shape/SKILL.md")
        text = evals.start(self.root / "t1", self.scenario, {}, rules)
        first = text.splitlines()[0]
        # The hook loads the installed rules only after a line starting "Reply rules: on".
        self.assertFalse(first.startswith("Reply rules: on"))
        self.assertIn(f"{rules}/replies.md and {rules}/reply-shape/SKILL.md", first)
        self.assertEqual(evals.load_trial(self.root / "t1", self.scenario)["rules"], rules)

    def test_no_rules_drops_the_opt_in(self):
        first = evals.start(self.root / "t1", self.scenario, {}, "none").splitlines()[0]
        self.assertNotIn("Reply rules", first)
        self.assertIn("without his reply rules", first)

    def test_rules_folder_missing_a_file_fails_before_setup(self):
        with self.assertRaisesRegex(evals.EvalError, "lacks reply-shape/SKILL.md"):
            evals.start(self.root / "t1", self.scenario, {}, self.rules("replies.md"))
        # Setup resets the trial's repo, so a bad --rules must leave a graded trial alone.
        self.assertFalse((self.root / "t1" / "demo" / "01-basic" / "repo").exists())

    def test_cwd_fills_the_preamble_and_assertions(self):
        scenario = {**self.scenario, "preamble": "The database is {cwd}-t3.sqlite.",
                    "assertions": ["{cwd} has a clean `git status`", "Every turn ends with Next"]}
        out = self.root / "side" / "t1"
        text = evals.start(out, scenario, {})
        repo = out / "demo" / "01-basic" / "repo"
        self.assertIn(f"\nThe database is {repo}-t3.sqlite.\n", text)
        grading = evals.grade_brief(scenario, out / "demo" / "01-basic.replies.md")
        self.assertIn(f"1. {repo} has a clean `git status`\n", grading)

    def test_grade_brief_names_the_trial_repo(self):
        out = self.root / "side" / "t2"
        evals.start(out, self.scenario, {})
        repo = out / "demo" / "01-basic" / "repo"
        grading = evals.grade_brief(self.scenario, out / "demo" / "01-basic.replies.md")
        self.assertIn(f"Repo the player worked in: {repo}\n", grading)
        self.assertIn(f"Setup, run from {self.evals}: bash ./setup.sh {repo}\n", grading)


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)

    def test_valid_grades_are_written_with_assertions(self):
        path = evals.record(self.out.name, SCENARIO, json.dumps(GRADES))
        data = json.loads(path.read_text())
        self.assertEqual(path, pathlib.Path(self.out.name, "demo", "01-basic.json"))
        self.assertEqual(data["assertions"], SCENARIO["assertions"])
        self.assertEqual([r["pass"] for r in data["results"]], [True, False])

    def test_fenced_block_is_read(self):
        text = "Here are the grades:\n\n```json\n" + json.dumps(GRADES) + "\n```\n"
        self.assertTrue(evals.record(self.out.name, SCENARIO, text).exists())

    def test_wrong_count_fails(self):
        with self.assertRaisesRegex(evals.EvalError, "one result for each assertion"):
            evals.record(self.out.name, SCENARIO, grades(True))

    def test_missing_evidence_fails(self):
        bad = json.loads(json.dumps(GRADES))
        bad["results"][1]["evidence"] = " "
        with self.assertRaisesRegex(evals.EvalError, "result 2: evidence is empty"):
            evals.record(self.out.name, SCENARIO, json.dumps(bad))

    def test_result_without_int_n_fails(self):
        for n in (None, True, "2", 2.0):
            bad = json.loads(json.dumps(GRADES))
            bad["results"][1]["n"] = n
            if n is None:
                del bad["results"][1]["n"]
            with self.subTest(n=n), self.assertRaisesRegex(evals.EvalError, "integer n"):
                evals.record(self.out.name, SCENARIO, json.dumps(bad))

    def test_invalid_json_fails(self):
        with self.assertRaisesRegex(evals.EvalError, "grades aren't JSON"):
            evals.record(self.out.name, SCENARIO, "not json")

    def test_missing_grades_file_exits_1(self):
        err = io.StringIO()
        with mock.patch.object(evals, "load_scenarios", return_value={("demo", "01-basic"): SCENARIO}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = evals.main(["record", self.out.name, "demo", "01-basic", f"{self.out.name}/nope.txt"])
        self.assertEqual(code, 1)
        self.assertIn("no grades file at", err.getvalue())

    def test_non_object_result_fails(self):
        bad = {"results": GRADES["results"] + ["extra"]}
        with self.assertRaisesRegex(evals.EvalError, "each result must be an object"):
            evals.record(self.out.name, SCENARIO, json.dumps(bad))


class TurnsTest(unittest.TestCase):
    def run_main(self, *args):
        bare = {(SCENARIO["skill"], SCENARIO["id"]): {k: v for k, v in SCENARIO.items() if k != "turns"}}
        out = io.StringIO()
        with mock.patch.object(evals, "load_scenarios", return_value=bare), contextlib.redirect_stdout(out):
            self.assertEqual(evals.main(list(args)), 0)
        return out.getvalue()

    def test_missing_turns_lists_as_zero(self):
        self.assertIn("demo/01-basic · 0 turns · 2 assertions", self.run_main("list"))

    def test_one_turn_is_singular(self):
        out = io.StringIO()
        with mock.patch.object(evals, "load_scenarios", return_value={("demo", "01-basic"): SCENARIO}), \
                contextlib.redirect_stdout(out):
            evals.main(["list"])
        self.assertIn("demo/01-basic · 1 turn · 2 assertions", out.getvalue())

    def test_missing_turns_prints_empty_list(self):
        self.assertEqual(json.loads(self.run_main("turns", "demo", "01-basic")), [])


def run_table(after, before=None):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return evals.main(["table", str(after)] + (["--against", str(before)] if before else []))


class TableTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.before = pathlib.Path(folder.name, "before")
        self.after = pathlib.Path(folder.name, "after")
        evals.record(self.before, SCENARIO, grades(True, True))

    def test_regression_exits_1(self):
        evals.record(self.after, SCENARIO, grades(True, False))
        _, regressions = evals.table(self.after, self.before)
        self.assertEqual(regressions, ["demo/01-basic #2"])
        self.assertEqual(run_table(self.after, self.before), 1)

    def test_missing_scenario_counts_as_regression(self):
        evals.record(self.after, {**SCENARIO, "id": "02-other"}, grades(True, True))
        _, regressions = evals.table(self.after, self.before)
        self.assertEqual(regressions, ["demo/01-basic #1 (missing)", "demo/01-basic #2 (missing)",
                                       "demo/02-other #1 (missing before)", "demo/02-other #2 (missing before)"])

    def test_missing_failed_scenario_exits_1(self):
        evals.record(self.before, {**SCENARIO, "id": "02-other"}, grades(False, False))
        evals.record(self.after, SCENARIO, grades(True, True))
        text, regressions = evals.table(self.after, self.before)
        self.assertEqual(regressions, ["demo/02-other #1 (missing)", "demo/02-other #2 (missing)"])
        self.assertEqual(text.splitlines()[-1].split(" · ")[0], "after: 2/4 pass")
        self.assertEqual(run_table(self.after, self.before), 1)

    def test_missing_run_fails(self):
        with self.assertRaisesRegex(evals.EvalError, "no recorded results in .*befor$"):
            evals.table(self.before, self.before.parent / "befor")
        self.assertEqual(run_table(self.before, self.after), 1)

    def test_ungraded_single_trial_is_missing(self):
        write_trial(self.after, "brief")
        text, regressions = evals.table(self.after, self.before)
        self.assertEqual(regressions, ["demo/01-basic #1 (missing)", "demo/01-basic #2 (missing)"])
        self.assertIn("| demo/01-basic | 1 | Status opens with a red marker | ✅ | — |", text)
        self.assertEqual(run_table(self.after, self.before), 1)

    def test_empty_run_fails(self):
        self.after.mkdir()
        with self.assertRaisesRegex(evals.EvalError, "no recorded results"):
            evals.table(self.after, self.before)

    def test_no_regression_exits_0(self):
        evals.record(self.after, SCENARIO, grades(True, True))
        self.assertEqual(run_table(self.after, self.before), 0)

    def test_changed_assertion_text_warns(self):
        assertions = [SCENARIO["assertions"][0], "Every turn ends with Done"]
        evals.record(self.after, {**SCENARIO, "assertions": assertions}, grades(True, True))
        text, regressions = evals.table(self.after, self.before)
        self.assertIn("Warning: assertion text changed between runs: demo/01-basic #2", text)
        self.assertEqual(regressions, [])
        self.assertEqual(run_table(self.after, self.before), 0)

    def test_summary_line(self):
        evals.record(self.after, SCENARIO, grades(True, False))
        text, _ = evals.table(self.after, self.before)
        self.assertIn("| demo/01-basic | 2 | Every turn ends with Next | ✅ | ❌ |", text)
        self.assertEqual(text.splitlines()[-1], "after: 1/2 pass · 1 regression: demo/01-basic #2")
        self.assertEqual(evals.table(self.after)[0].splitlines()[-1], "1/2 pass")


def cost(wall_s, cache_read, usd):
    return {"wall_s": wall_s, "tokens": {"input": 1000, "cache_write": 0, "cache_read": cache_read, "output": 50},
            "usd": usd, "sessions": [], "rates": {}, "missing": [], "unpriced": [] if usd is not None else ["x-1"]}


class TrialTableTest(unittest.TestCase):
    """Two trials a side. #1 passes in both before trials and one after trial (a flip); #2
    passes in one trial on each side (no flip)."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        self.before, self.after = self.root / "before", self.root / "after"
        for side, runs in ((self.before, [(True, True), (True, False)]), (self.after, [(True, False), (False, True)])):
            for n, passes in enumerate(runs, 1):
                evals.record(side / f"t{n}", SCENARIO, grades(*passes))

    def save_cost(self, trial, value):
        path = trial / "demo" / "01-basic" / "cost.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def test_flip_only_when_every_before_trial_passed(self):
        text, regressions = evals.table(self.after, self.before)
        self.assertEqual(regressions, ["demo/01-basic #1 (flip)"])
        self.assertIn("| scenario | # | assertion | before (2) | after (2) |", text)
        self.assertIn("| demo/01-basic | 1 | Status opens with a red marker | 2/2 | 1/2 ⚠ flip |", text)
        self.assertIn("| demo/01-basic | 2 | Every turn ends with Next | 1/2 | 1/2 |", text)
        self.assertEqual(text.splitlines()[-1],
                         "after: 0/2 pass in every trial · 1 regression: demo/01-basic #1 (flip)")
        self.assertEqual(run_table(self.after, self.before), 1)

    def test_scenario_missing_from_one_after_trial(self):
        for n in (1, 2):
            evals.record(self.before / f"t{n}", {**SCENARIO, "id": "02-other"}, grades(False, False))
        evals.record(self.after / "t1", {**SCENARIO, "id": "02-other"}, grades(True, True))
        text, regressions = evals.table(self.after, self.before)
        self.assertIn("demo/02-other #1 (missing)", regressions)
        self.assertIn("| demo/02-other | 2 | Every turn ends with Next | 0/2 | 1/2 ⚠ missing |", text)

    def test_scenario_one_before_trial_never_started_is_missing_before(self):
        before, after = self.root / "b", self.root / "a"
        other = {**SCENARIO, "id": "02-other"}
        evals.record(before / "t1", other, grades(True, True))
        for side in (before, after):
            for n in (1, 2):
                evals.record(side / f"t{n}", SCENARIO, grades(True, True))
        for n in (1, 2):
            evals.record(after / f"t{n}", other, grades(False, False))
        text, regressions = evals.table(after, before)
        self.assertEqual(regressions, [f"demo/02-other #{n} (missing before)" for n in (1, 2)])
        self.assertIn("| demo/02-other | 1 | Status opens with a red marker | 1/2 ⚠ missing | 0/2 |", text)
        self.assertEqual(run_table(after, before), 1)

    def test_ungraded_trial_on_each_side_is_missing(self):
        for side in (self.before, self.after):
            write_trial(side / "t3", "brief")
        text, regressions = evals.table(self.after, self.before)
        self.assertEqual(regressions, [f"demo/01-basic #{n} (missing before and after)" for n in (1, 2)])
        self.assertIn("| scenario | # | assertion | before (3) | after (3) |", text)
        self.assertIn("| demo/01-basic | 1 | Status opens with a red marker | 2/3 ⚠ missing | 1/3 ⚠ missing |", text)
        self.assertNotIn("has 1 trial", text)
        self.assertEqual(run_table(self.after, self.before), 1)

    def test_two_against_two_with_one_ungraded_trial_a_side(self):
        legacy, new = self.root / "legacy", self.root / "new"
        evals.record(legacy / "t1", SCENARIO, grades(True, True))
        write_trial(legacy / "t2", "brief")
        write_trial(new / "t1", "brief")
        evals.record(new / "t2", SCENARIO, grades(True, True))
        text, regressions = evals.table(new, legacy)
        self.assertEqual(regressions, [f"demo/01-basic #{n} (missing before and after)" for n in (1, 2)])
        self.assertIn("| demo/01-basic | 2 | Every turn ends with Next | 1/2 ⚠ missing | 1/2 ⚠ missing |", text)
        self.assertEqual(text.splitlines()[-1].split(" · ")[0], "after: 0/2 pass in every trial")
        self.assertEqual(run_table(new, legacy), 1)

    def test_ungraded_before_trial_alone_is_missing_before(self):
        write_trial(self.before / "t3", "brief")
        evals.record(self.after / "t3", SCENARIO, grades(True, True))
        _, regressions = evals.table(self.after, self.before)
        self.assertIn("demo/01-basic #2 (missing before)", regressions)

    def test_scenario_no_trial_graded_is_missing(self):
        for side in (self.before, self.after):
            write_trial(side / "t1", "brief", {**SCENARIO, "id": "02-other"})
        _, regressions = evals.table(self.after, self.before)
        self.assertIn("demo/02-other (missing)", regressions)

    def test_cost_medians_and_unknown_usd(self):
        for n, (wall, read) in enumerate([(600, 10_000_000), (1000, 12_000_000)], 1):
            self.save_cost(self.before / f"t{n}", cost(wall, read, 4.0 * n))
        self.save_cost(self.after / "t1", cost(500, 800_000, 1.0))
        self.save_cost(self.after / "t2", cost(700, 900_000, None))
        text, _ = evals.table(self.after, self.before)
        self.assertIn("| median of trials | wall | input | cache write | cache read | output | USD |", text)
        self.assertIn("| before | 13m 20s | 1.0k | 0 | 11.0M | 50 | $6.00 |", text)
        self.assertIn("| after | 10m 00s | 1.0k | 0 | 850k | 50 | ? |", text)
        self.assertIn("Warning: after/t2: no rate for x-1, so USD is ?", text)
        self.assertLess(text.index("| before | 13m"), text.index("| after | 10m"))

    def test_run_without_cost_warns(self):
        self.save_cost(self.before / "t1", cost(600, 1, 1.0))
        text, _ = evals.table(self.after, self.before)
        self.assertIn("Warning: before/t2: no cost.json for demo/01-basic", text)
        self.assertIn("| after | — | — | — | — | — | — |", text)

    def test_started_run_warns_when_no_run_has_a_cost(self):
        write_trial(self.after / "t3", "brief")
        evals.record(self.after / "t3", SCENARIO, grades(True, True))
        text, _ = evals.table(self.after, self.before)
        self.assertNotIn("median of trials", text)
        self.assertEqual([line for line in text.splitlines() if "cost.json" in line],
                         ["Warning: after/t3: no cost.json for demo/01-basic"])

    def test_results_recorded_before_start_stay_silent_without_cost(self):
        text, _ = evals.table(self.after, self.before)
        self.assertNotIn("median of trials", text)
        self.assertNotIn("Warning", text)

    def test_single_run_side_against_trials_warns(self):
        legacy = self.root / "legacy"
        evals.record(legacy, SCENARIO, grades(True, True))
        text, regressions = evals.table(self.after, legacy)
        self.assertIn("| scenario | # | assertion | before (1) | after (2) |", text)
        self.assertIn("Warning: before has 1 trial; a flip needs 2 or more a side to mean much", text)
        self.assertEqual(regressions, ["demo/01-basic #1 (flip)", "demo/01-basic #2 (flip)"])

    def test_one_side_alone(self):
        text, regressions = evals.table(self.after)
        self.assertIn("| scenario | # | assertion | result (2) |", text)
        self.assertEqual((text.splitlines()[-1], regressions), ("0/2 pass in every trial", []))
        self.assertEqual(run_table(self.after), 0)

    def test_ungraded_trial_alone_is_missing(self):
        lone = self.root / "lone"
        write_trial(lone, "brief")
        text, regressions = evals.table(lone)
        self.assertEqual(regressions, ["demo/01-basic (missing)"])
        self.assertEqual(text.splitlines()[-1], "0/0 pass · 1 regression: demo/01-basic (missing)")
        self.assertEqual(run_table(lone), 1)

    def test_graded_and_ungraded_trial_alone_is_missing(self):
        write_trial(self.after / "t3", "brief")
        text, regressions = evals.table(self.after)
        self.assertEqual(regressions, [f"demo/01-basic #{n} (missing)" for n in (1, 2)])
        self.assertIn("| demo/01-basic | 1 | Status opens with a red marker | 1/3 ⚠ missing |", text)
        self.assertEqual(run_table(self.after), 1)


def user(content, **extra):
    return {"type": "user", "message": {"role": "user", "content": content}, **extra}


def assistant(*parts):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(parts)}}


def text(value):
    return {"type": "text", "text": value}


def write_transcript(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return path


def write_trial(out, brief_text, scenario=SCENARIO):
    """The trial.json start writes, without running the scenario's setup."""
    folder = pathlib.Path(out, scenario["skill"], scenario["id"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "trial.json").write_text(json.dumps({"cwd": scenario["cwd"], "brief": brief_text, "variants": {}}))


class RepliesTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        self.projects = self.root / "projects"
        self.brief = evals.brief(SCENARIO)
        self.session = write_transcript(self.projects / "-tmp-demo" / "s1.jsonl", [
            {"type": "queue-operation"},
            user(f"Act as the test sub-agent for this task.\n\n{self.brief}"),
            assistant({"type": "thinking", "thinking": "hmm"}),
            assistant(text("Checking the branch.")),
            assistant({"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}),
            user([{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]),
            user([text("Base directory for this skill: ...")], isMeta=True),
            assistant(text("🔴 **Not done.**")),
            user("fix all"),
            assistant(text("Fixing."), text("✅ **Done.**")),
        ])
        # A subagent's transcript repeats the brief, but isn't the player's.
        write_transcript(self.projects / "-tmp-demo" / "s1" / "subagents" / "a1.jsonl", [
            user(self.brief), assistant(text("subagent reply")),
        ])
        write_trial(self.root / "out", self.brief)
        self.measured = []

    def measure(self, path):
        self.measured.append(pathlib.Path(path))
        return {"wall_s": 1.0, "usd": 0.5}

    def run_main(self, *args, out_dir=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(evals, "load_scenarios", return_value={("demo", "01-basic"): SCENARIO}), \
                mock.patch.object(evals, "PROJECTS", self.projects), \
                mock.patch.object(evals.run_cost, "measure", self.measure), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = evals.main(["replies", "demo", "01-basic", str(out_dir or self.root / "out"), *args])
        return code, out.getvalue(), err.getvalue()

    def test_last_reply_of_each_turn(self):
        code, out, _ = self.run_main()
        path = self.root / "out" / "demo" / "01-basic.replies.md"
        cost = self.root / "out" / "demo" / "01-basic" / "cost.json"
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [str(self.session), str(path), str(cost)])
        self.assertEqual(path.read_text(), "=== turn 1 ===\n🔴 **Not done.**\n\n=== turn 2 ===\n✅ **Done.**\n\n"
                         "=== skills loaded ===\nnone\n")
        self.assertEqual(json.loads(cost.read_text()), {"wall_s": 1.0, "usd": 0.5})
        self.assertEqual(self.measured, [self.session])

    def test_parallel_trials_each_find_their_own_transcript(self):
        found = {}
        for trial in ("t1", "t2"):
            task = evals.brief(SCENARIO, cwd=f"/tmp/side/{trial}/demo/01-basic/repo")
            write_trial(self.root / trial, task)
            found[trial] = write_transcript(self.projects / f"-tmp-{trial}" / f"{trial}.jsonl", [
                user(f"Act as the test sub-agent for this task.\n\n{task}"), assistant(text("one")),
                user("fix all"), assistant(text("two")),
            ])
        os.utime(found["t1"], (5, 5))  # t2's transcript is newer, but only t1's brief matches t1
        for trial in ("t1", "t2"):
            with self.subTest(trial=trial):
                code, out, _ = self.run_main(out_dir=self.root / trial)
                self.assertEqual((code, out.splitlines()[0]), (0, str(found[trial])))

    def test_a_brief_and_turns_t3_names_the_sender_of_still_match(self):
        sender = 'Code: the agent in T3 thread "thread:parent" sent this message, not the user.]\n\n'
        session = write_transcript(self.projects / "-tmp-sent" / "s2.jsonl", [
            user(f"[T3 {sender}Act as the test sub-agent for this task.\n\n{self.brief}"),
            assistant(text("🔴 **Not done.**")), user(f"[T3 {sender}fix all"), assistant(text("✅ **Done.**")),
        ])
        os.utime(self.session, (5, 5))
        code, out, _ = self.run_main()
        self.assertEqual((code, out.splitlines()[0]), (0, str(session)))
        self.assertTrue((self.root / "out" / "demo" / "01-basic.replies.md").read_text().startswith(
            "=== turn 1 ===\n🔴 **Not done.**\n\n=== turn 2 ===\n✅ **Done.**\n\n"))

    def test_run_without_start_fails(self):
        code, _, err = self.run_main(out_dir=self.root / "unstarted")
        self.assertEqual(code, 1)
        self.assertIn("no trial.json for demo/01-basic", err)
        self.assertIn("begin the run with start", err)

    def test_cost_failure_exits_1_after_saving_replies(self):
        def untracked(path):
            raise LookupError("no T3 thread ran session s1")
        self.measure = untracked
        code, out, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(len(out.splitlines()), 2)
        self.assertIn("no cost for", err)
        self.assertIn("no T3 thread ran session s1", err)
        self.assertFalse((self.root / "out" / "demo" / "01-basic" / "cost.json").exists())

    def test_newest_matching_transcript_wins(self):
        newer = write_transcript(self.projects / "-tmp-other" / "s2.jsonl", [
            user(self.brief), assistant(text("rerun")),
        ])
        os.utime(self.session, (1, 1))
        _, out, _ = self.run_main()
        self.assertEqual(out.splitlines()[0], str(newer))

    def test_plain_brief_skips_newer_variant_run(self):
        variant = evals.brief(SCENARIO, {"demo": "/tmp/new-demo"})
        write_transcript(self.projects / "-tmp-other" / "s2.jsonl", [
            user(f"Act as the test sub-agent for this task.\n\n{variant}"), assistant(text("variant")),
        ])
        os.utime(self.session, (1, 1))
        _, out, _ = self.run_main()
        self.assertEqual(out.splitlines()[0], str(self.session))

    def test_variant_brief_must_match(self):
        write_trial(self.root / "variant", evals.brief(SCENARIO, {"demo": "/tmp/new-demo"}))
        code, _, err = self.run_main(out_dir=self.root / "variant")
        self.assertEqual(code, 1)
        self.assertIn("no transcript in", err)

    def test_explicit_transcript(self):
        other = write_transcript(self.root / "elsewhere.jsonl", [
            user("hi"), assistant(text("hello")), user("fix all"), assistant(text("done")),
        ])
        for out_dir in (self.root / "out", self.root / "unstarted"):
            with self.subTest(out_dir=out_dir.name):
                code, out, _ = self.run_main("--transcript", str(other), out_dir=out_dir)
                self.assertEqual((code, out.splitlines()[0]), (0, str(other)))

    def test_task_notification_is_not_a_turn(self):
        write_transcript(self.session, [
            user(self.brief), assistant(text("Started the build.")),
            user("<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n</task-notification>"),
            assistant(text("🔴 **Not done.**")),
            user("fix all"), assistant(text("✅ **Done.**")),
        ])
        code, _, _ = self.run_main()
        path = self.root / "out" / "demo" / "01-basic.replies.md"
        self.assertEqual(code, 0)
        self.assertEqual(path.read_text(), "=== turn 1 ===\nStarted the build.\n\n--- after a harness notice ---\n"
                         "🔴 **Not done.**\n\n=== turn 2 ===\n✅ **Done.**\n\n=== skills loaded ===\nnone\n")

    def test_t3_notices_split_a_turn_without_dropping_the_report(self):
        write_transcript(self.session, [
            user(self.brief), assistant(text("Started layer 1.")),
            user("Continue where you left off."), assistant(text("Resuming.")), assistant(text("🔴 **Not done.**")),
            user("Delegated task node:delegated-task:command%3Amcp%3Aab%3Adelegate-task%3Areview-r1 "
                 "(Codex review) [completed]:\nClean."),
            assistant(text("A late review copy is clean too.")),
            user("fix all"), assistant(text("✅ **Done.**")),
        ])
        code, _, _ = self.run_main()
        path = self.root / "out" / "demo" / "01-basic.replies.md"
        self.assertEqual(code, 0)
        self.assertEqual(path.read_text(), "=== turn 1 ===\nStarted layer 1.\n\n--- after a harness notice ---\n"
                         "🔴 **Not done.**\n\n--- after a harness notice ---\nA late review copy is clean too.\n\n"
                         "=== turn 2 ===\n✅ **Done.**\n\n=== skills loaded ===\nnone\n")

    def test_sent_turn_counts_whatever_it_says(self):
        write_transcript(self.session, [
            user(self.brief), assistant(text("🔴 **Not done.**")),
            user("Continue where you left off."), assistant(text("✅ **Done.**")),
        ])
        with mock.patch.dict(SCENARIO, {"turns": ["Continue where you left off."]}):
            code, _, _ = self.run_main()
        path = self.root / "out" / "demo" / "01-basic.replies.md"
        self.assertEqual(code, 0)
        self.assertEqual(path.read_text(), "=== turn 1 ===\n🔴 **Not done.**\n\n=== turn 2 ===\n✅ **Done.**\n\n"
                         "=== skills loaded ===\nnone\n")

    def test_notice_after_a_tool_call_does_not_split_the_turn(self):
        write_transcript(self.session, [
            user(self.brief), assistant(text("Checking."), {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}),
            user([{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]),
            user("<system-reminder>a file changed</system-reminder>"),
            assistant(text("🔴 **Not done.**")),
            user("fix all"), assistant(text("✅ **Done.**")),
        ])
        code, _, _ = self.run_main()
        path = self.root / "out" / "demo" / "01-basic.replies.md"
        self.assertEqual(code, 0)
        self.assertEqual(path.read_text(), "=== turn 1 ===\n🔴 **Not done.**\n\n=== turn 2 ===\n✅ **Done.**\n\n"
                         "=== skills loaded ===\nnone\n")

    def test_compaction_before_a_late_notice_keeps_the_report(self):
        write_transcript(self.session, [
            user(self.brief), assistant(text("🔴 **Not done.**")),
            user("This session is being continued from a previous conversation.", isCompactSummary=True),
            user("Delegated task node:delegated-task:command%3Amcp%3Aab%3Adelegate-task%3Ar1 (Review) [completed]:\nClean."),
            assistant(text("A late review copy is clean too.")),
            user("fix all"), assistant(text("✅ **Done.**")),
        ])
        code, _, _ = self.run_main()
        path = self.root / "out" / "demo" / "01-basic.replies.md"
        self.assertEqual(code, 0)
        self.assertEqual(path.read_text(), "=== turn 1 ===\n🔴 **Not done.**\n\n--- after a harness notice ---\n"
                         "A late review copy is clean too.\n\n=== turn 2 ===\n✅ **Done.**\n\n"
                         "=== skills loaded ===\nnone\n")

    def test_notice_with_no_reply_after_it_adds_no_part(self):
        write_transcript(self.session, [
            user(self.brief), assistant(text("🔴 **Not done.**")),
            user("<task-notification>\n<status>completed</status>\n</task-notification>"),
            user("fix all"), assistant(text("✅ **Done.**")),
            user("Continue where you left off."),
        ])
        code, _, _ = self.run_main()
        path = self.root / "out" / "demo" / "01-basic.replies.md"
        self.assertEqual(code, 0)
        self.assertEqual(path.read_text(), "=== turn 1 ===\n🔴 **Not done.**\n\n=== turn 2 ===\n✅ **Done.**\n\n"
                         "=== skills loaded ===\nnone\n")

    def test_interrupt_and_sidechain_are_not_turns(self):
        write_transcript(self.session, [
            user(self.brief), assistant(text("Started.")),
            user([text("[Request interrupted by user for tool use]")]),
            assistant(text("🔴 **Not done.**")),
            user("side question", isSidechain=True), {**assistant(text("side answer")), "isSidechain": True},
            user("fix all"), assistant(text("✅ **Done.**")),
        ])
        code, _, _ = self.run_main()
        path = self.root / "out" / "demo" / "01-basic.replies.md"
        self.assertEqual(code, 0)
        self.assertEqual(path.read_text(), "=== turn 1 ===\n🔴 **Not done.**\n\n=== turn 2 ===\n✅ **Done.**\n\n"
                         "=== skills loaded ===\nnone\n")

    def test_compaction_summary_is_not_a_turn(self):
        write_transcript(self.session, [
            user(self.brief), assistant(text("🔴 **Not done.**")),
            user("fix all"), assistant(text("Fixing.")),
            user("This session is being continued from a previous conversation.", isCompactSummary=True),
            assistant(text("✅ **Done.**")),
        ])
        code, _, _ = self.run_main()
        path = self.root / "out" / "demo" / "01-basic.replies.md"
        self.assertEqual(code, 0)
        self.assertEqual(path.read_text(), "=== turn 1 ===\n🔴 **Not done.**\n\n=== turn 2 ===\n✅ **Done.**\n\n"
                         "=== skills loaded ===\nnone\n")

    def test_turn_count_mismatch_fails(self):
        write_transcript(self.session, [user(self.brief), assistant(text("🔴 **Not done.**"))])
        code, _, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("expected 2 turns in", err)

    def test_turn_without_reply_fails(self):
        write_transcript(self.session, [user(self.brief), assistant(text("hi")), user("fix all")])
        code, _, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("turn 2 in", err)


class SaveRepliesTest(unittest.TestCase):
    def test_lists_the_skills_the_player_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = pathlib.Path(tmp, "diagnosing-bugs", "SKILL.md")
            skill.parent.mkdir()
            skill.write_text("---\nname: diagnosing-bugs\n---\n")

            def row(kind, content, **extra):
                return json.dumps({"type": kind, "cwd": tmp, "message": {"role": kind, "content": content}, **extra})

            path = pathlib.Path(tmp, "session.jsonl")
            path.write_text("\n".join([
                row("user", "the rest timer is broken again"),
                row("user", [{"type": "text", "text": f"Base directory for this skill: {skill.parent}\n\nbody"}],
                    isMeta=True),
                row("assistant", [{"type": "text", "text": "🔴 **The timer never resets.**"}]),
            ]) + "\n")
            scenario = {**SCENARIO, "turns": []}
            saved = evals.save_replies(tmp, scenario, path).read_text()
        self.assertIn("=== turn 1 ===\n🔴 **The timer never resets.**", saved)
        self.assertTrue(saved.endswith("=== skills loaded ===\ndiagnosing-bugs\n"))

    def test_lists_each_delegate_task_call(self):
        review = {"role": "review", "interactionMode": "plan",
                  "target": {"driverKind": "codex", "model": "gpt-6.1-terra", "options": {"reasoningEffort": "max"}}}
        test = {"role": "test", "interactionMode": "default", "target": {"driverKind": "claudeAgent", "model": "claude-opus-5-5"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp, "session.jsonl")
            path.write_text("\n".join(json.dumps({"type": kind, "message": {"role": kind, "content": content}}) for kind, content in [
                ("user", "review PR 12"),
                *[("assistant", [{"type": "tool_use", "id": f"t{n}", "name": "mcp__t3-code__delegate_task",
                                  "input": {"task": "brief", **call}}]) for n, call in enumerate([review, test])],
                ("assistant", [{"type": "text", "text": "🔴 **Fee rows key on currency.**"}]),
            ]) + "\n")
            saved = evals.save_replies(tmp, {**SCENARIO, "turns": []}, path).read_text()
        self.assertTrue(saved.endswith("=== skills loaded ===\nnone\n\n=== delegate_task calls ===\n"
                                       + json.dumps(review, sort_keys=True) + "\n" + json.dumps(test, sort_keys=True) + "\n"))
    def test_lists_tool_calls_when_the_scenario_asks(self):
        two_calls = [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "node --test a.test.ts"}},
                     {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "node --test b.test.ts"}}]
        rows = [
            {"type": "user", "message": {"content": "review PR 12"}},
            {"type": "assistant", "message": {"content": two_calls}},
            # A request snapshot repeats the calls; they print once.
            {"type": "api-request-blob", "message": {"content": two_calls}},
            # Parallel results come back in either order and pair by id.
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t2", "is_error": True, "content": "Exit code 1: failed"},
                {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "pass 4"}]}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "✅ **Approve.**"}]}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp, "session.jsonl")
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            sub = pathlib.Path(tmp, "session", "subagents", "agent-a1.jsonl")
            sub.parent.mkdir(parents=True)
            sub.write_text("\n".join(json.dumps(row) for row in [
                {"type": "assistant", "isSidechain": True, "message": {"content": [
                    {"type": "tool_use", "id": "s1", "name": "Read", "input": {"file_path": "src/a.ts"}}]}},
                {"type": "user", "isSidechain": True, "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "s1", "content": "x" * 8005}]}},
            ]) + "\n")
            plain = evals.save_replies(tmp, {**SCENARIO, "turns": []}, path).read_text()
            saved = evals.save_replies(tmp, {**SCENARIO, "turns": [], "tool_calls": True}, path).read_text()
        self.assertNotIn("=== tool calls ===", plain)
        self.assertTrue(saved.endswith(
            "=== tool calls ===\n> Bash: node --test a.test.ts\n< pass 4\n"
            "> Bash: node --test b.test.ts\n<! Exit code 1: failed\n"
            '[agent-a1] > Read: {"file_path": "src/a.ts"}\n'
            f"[agent-a1] < {'x' * 8000} …[5 more chars in {sub}]\n"))

    def test_tool_calls_keep_long_evidence_and_mark_a_missing_result(self):
        command = "node --input-type=module -e '" + "x" * 700 + "'"
        output = "y" * 7000 + " pass 4"
        rows = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": command}},
                {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "sleep 9"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": output}]}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp, "session.jsonl")
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            lines = evals.tool_calls(path)
        # The input prints whole, and a result is cut only past 8,000 characters.
        self.assertEqual(lines, [f"> Bash: {command}", f"< {output}", "> Bash: sleep 9", "< (no result)"])

    def test_grade_brief_names_the_tool_calls_only_when_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            replies = pathlib.Path(tmp, "demo", "01-basic.replies.md")
            self.assertNotIn("tool calls", evals.grade_brief(SCENARIO, replies))
            self.assertIn("`=== tool calls ===`, every tool call it and its native subagents made, with each result "
                          "(`<!` marks an error)", evals.grade_brief({**SCENARIO, "tool_calls": True}, replies))


if __name__ == "__main__":
    unittest.main()
