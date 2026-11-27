"""Tests for proposals.py: each part of the contract refuses a proposal on its own."""
import contextlib, io, json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import proposals  # noqa: E402

GOOD = {"title": "Lint helpers below the main export", "metric": "3 corrections per merged PR",
        "cases": ["https://github.com/hifranklin-tech/franklin-next/pull/5453#discussion_r1",
                  "Oliver in t3-thread://v2/p/t1: 'helpers go below'"],
        "replaces": "the coding-standards line on helper order", "rung": "lint",
        "check": "corrections tagged helper order drop to 0 in 2 weeks"}


class Check(unittest.TestCase):
    def test_a_complete_proposal_passes(self):
        self.assertEqual(proposals.check([GOOD]), {"passed": [GOOD], "refused": []})

    def test_each_missing_part_refuses_it(self):
        cases = {
            "metric": ({"metric": "fewer corrections"}, "no metric"),
            "one case": ({"cases": GOOD["cases"][:1]}, "1 cited cases"),
            "uncited": ({"cases": ["Oliver said so", "and again"]}, "0 cited cases"),
            "duplicate": ({"cases": [GOOD["cases"][0]] * 2}, "1 cited cases"),
            "replaces": ({"replaces": "None."}, "deletes or replaces"),
            "rung": ({"rung": "docs"}, "no rung"),
            "check": ({"check": ""}, "no check"),
        }
        for name, (change, reason) in cases.items():
            with self.subTest(name):
                result = proposals.check([{**GOOD, **change}])
                self.assertEqual(result["passed"], [])
                self.assertTrue(any(reason in r for r in result["refused"][0]["reasons"]), result)

    def test_a_missing_key_refuses_it(self):
        bare = {k: v for k, v in GOOD.items() if k != "replaces"}
        self.assertEqual(proposals.check([bare])["refused"][0]["reasons"], ["doesn't say what it deletes or replaces"])

    def test_citations_cover_paths_prs_and_shas(self):
        for case in ("hooks/verdicts.py:120", "skills#241", "commit 745a616c"):
            with self.subTest(case):
                self.assertTrue(proposals.CITATION.search(case))
        for case in ("about 3 times last week", "the #1 issue", "on 20261030"):
            with self.subTest(case):
                self.assertFalse(proposals.CITATION.search(case))

    def test_metric_1_needs_a_calibrated_judge(self):
        scope = {**GOOD, "metric": "1 scope creep"}
        self.assertIn("metric 1 is uncalibrated", proposals.check([scope])["refused"][0]["reasons"][0])
        self.assertEqual(proposals.check([scope], scope_calibrated=True)["passed"], [scope])

    def test_a_fourth_proposal_is_over_the_cap(self):
        result = proposals.check([{**GOOD, "title": str(n)} for n in range(4)])
        self.assertEqual([p["title"] for p in result["passed"]], ["0", "1", "2"])
        self.assertEqual(result["refused"], [{"title": "3", "reasons": ["over the weekly cap of 3"]}])

    def test_a_refused_proposal_leaves_room_under_the_cap(self):
        result = proposals.check([{**GOOD, "rung": ""}] + [{**GOOD, "title": str(n)} for n in range(3)])
        self.assertEqual(len(result["passed"]), 3)

    def test_main_exits_1_when_any_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "p.json")
            for given, code in (([GOOD], 0), ([GOOD, {**GOOD, "check": "none"}], 1)):
                path.write_text(json.dumps(given))
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(proposals.main(["check", str(path)]), code)
                self.assertEqual(len(json.loads(out.getvalue())["passed"]), 1)
            path.write_text(json.dumps([{**GOOD, "metric": "1 scope creep"}]))
            labeled = Path(tmp, "calibration.json")
            labeled.write_text(json.dumps({"hunks": [{"judge": "in", "label": "in"}] * 10}))
            for extra, code in (([], 1), (["--calibration", str(Path(tmp, "none.json"))], 1),
                                (["--calibration", str(labeled)], 0)):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(proposals.main(["check", str(path), *extra]), code)


if __name__ == "__main__":
    unittest.main()
