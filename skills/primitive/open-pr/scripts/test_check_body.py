"""Runs check-body.mjs on sample PR bodies: each counted line must be flagged, and each
clean one must pass."""
import pathlib, subprocess, tempfile, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "check-body.mjs"


def check(body):
    """The flagged line numbers, and the script's exit code."""
    with tempfile.NamedTemporaryFile("w", suffix=".md") as file:
        file.write(body)
        file.flush()
        run = subprocess.run(["node", str(SCRIPT), file.name], capture_output=True, text=True)
    lines = [int(line.split(":")[1].split()[0]) for line in run.stdout.splitlines() if "counts tests" in line]
    return lines, run.returncode


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


if __name__ == "__main__":
    unittest.main()
