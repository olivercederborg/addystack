import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

EVALS = pathlib.Path(__file__).resolve().parent.parent / "evals"


class SetupGuardTest(unittest.TestCase):
    """Every eval setup.sh, and each setup script listed with it, runs rm -rf on its argument, so `/tmp/..` must not escape /tmp."""

    def test_setups_refuse_paths_that_escape_tmp(self):
        scripts = [*sorted(EVALS.glob("*/setup.sh")), EVALS / "reply-shape" / "setup-ship-gate.sh"]
        self.assertTrue(scripts)
        for script in scripts:
            with self.subTest(script=str(script.relative_to(EVALS))):
                # Linux's default temp dir is /tmp itself, so build the target under $HOME.
                target = pathlib.Path(tempfile.mkdtemp(dir=pathlib.Path.home())).resolve()
                self.addCleanup(shutil.rmtree, target, ignore_errors=True)
                sentinel = target / "sentinel"
                sentinel.write_text("keep")
                # Relative to the resolved /tmp, so it holds whether /tmp is a symlink (macOS) or not.
                relative = os.path.relpath(target, os.path.realpath("/tmp"))
                self.assertTrue(relative.startswith(".."), f"{target} is inside /tmp")
                escape = "/tmp/" + relative
                self.assertEqual(os.path.realpath(escape), str(target))
                run = subprocess.run(["bash", str(script), escape], capture_output=True, text=True, timeout=60)
                self.assertNotEqual(run.returncode, 0, run.stderr)
                self.assertIn("Refusing to write outside /tmp", run.stderr)
                self.assertTrue(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
