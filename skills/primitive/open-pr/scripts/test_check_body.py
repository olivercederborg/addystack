"""Runs check-body.mjs on sample PR bodies: each counted line and each screenshot outside a
Before | After table must be flagged, and each clean body must pass."""
import pathlib, subprocess, tempfile, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "check-body.mjs"


def check(body, problem="counts tests"):
    """The line numbers flagged with `problem`, and the script's exit code."""
    with tempfile.NamedTemporaryFile("w", suffix=".md") as file:
        file.write(body)
        file.flush()
        run = subprocess.run(["node", str(SCRIPT), file.name], capture_output=True, text=True)
    lines = [int(line.split(":")[1].split()[0]) for line in run.stdout.splitlines() if problem in line]
    return lines, run.returncode


def screenshots(body):
    return check(body, problem="Before | After")


class CheckBody(unittest.TestCase):
    def test_flags_counts_on_check_lines(self):
        body = "\n".join([
            "- **Checks**: ✅ typecheck · ✅ 65 + 8 package tests",
            "- **Checks**: ✅ 5 new hook tests",
            "- **Checks**: ✅ SnoopKit tests (93)",
            "- **Checks**: ✅ server tests (179, 4 new)",
            "- **Checks**: ❌ tests 11/12",
            "## Checks",
            "- 56 tests passed",
            "### Unit",
            "- 12 tests passed",
        ])
        self.assertEqual(check(body), ([1, 2, 3, 4, 5, 7, 9], 1))

    def test_passes_named_checks_and_prose(self):
        body = "\n".join([
            "- **Checks**: ✅ typecheck · ✅ package tests · review-loop: Clean (round 2)",
            "This adds 3 tests for the claim path.",
            "## Checks",
            "- ✅ unit tests",
            "## Reach",
            "- 2 tests moved to the new folder",
            "- **Checks**: ✅ browser tests (3 browsers) · ✅ Python 3.13 unit tests",
        ])
        self.assertEqual(check(body), ([], 0))


    def test_flags_counts_inside_a_code_fence(self):
        self.assertEqual(check("```text\n✅ 56 tests\n```"), ([2], 1))

    def test_flags_screenshots_outside_a_before_after_table(self):
        body = "\n".join([
            "**Setup asks for fewer fields.**",
            "![Setup](./setup.png)",
            "",
            "| Screen | Old | New |",
            "|---|---|---|",
            "| Setup | ![Old](./old.png) | ![New](./new.png) |",
            "",
            "<img src=\"./row.png\" width=\"400\">",
        ])
        self.assertEqual(screenshots(body), ([2, 6, 8], 1))

    def test_flags_a_row_missing_its_before_or_after(self):
        body = "\n".join([
            "| Screen | Before | After |",
            "|---|---|---|",
            "| Setup | ![Before](./a.png) |  |",
            "| Row |  | ![After](./b.png) |",
        ])
        self.assertEqual(screenshots(body), ([3, 4], 1))

    def test_passes_a_before_after_table(self):
        body = "\n".join([
            "| Screen | **Before** (light) | **After** (light) |",
            "|:---|:---:|:---:|",
            "| Setup | ![Before](./a.png) | ![After](./b.png) |",
            "| Prompt | _new screen_ | <img src=\"./c.png\" width=\"400\"> |",
            "",
            "```markdown",
            "![Example](./example.png)",
            "```",
        ])
        self.assertEqual(screenshots(body), ([], 0))

    def test_passes_a_rendered_visual_outside_a_table(self):
        body = "\n".join([
            "## Visual",
            "![Visual: retries reuse their receipt](./pr-visual.png)",
            "<img alt=\"Visual: retries reuse their receipt\" src=\"https://x/y.png\" width=\"880\">",
            "![Visualized setup](./setup.png)",
        ])
        self.assertEqual(screenshots(body), ([4], 1))


if __name__ == "__main__":
    unittest.main()
