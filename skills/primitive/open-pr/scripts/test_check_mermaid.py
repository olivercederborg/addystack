"""Runs check-mermaid.mjs against a scratch cache with a fake npm on PATH, so its install
never looks complete after npm fails, two first runs at once both pass, and an install
prunes cache folders unused for 30 days and partials a killed install left."""
import os, pathlib, subprocess, tempfile, textwrap, time, unittest
from concurrent.futures import ThreadPoolExecutor

SCRIPT = pathlib.Path(__file__).resolve().parent / "check-mermaid.mjs"
DAY = 24 * 60 * 60

# Writes stand-in mermaid and jsdom packages into --prefix and logs each call. With
# FAKE_NPM=fail it leaves mermaid's folder behind and exits 1, like an interrupted install.
NPM = textwrap.dedent("""\
    #!/bin/sh
    prefix=$3
    echo "$prefix" >> "$NPM_LOG"
    mkdir -p "$prefix/node_modules/mermaid" "$prefix/node_modules/jsdom"
    echo '{"name": "mermaid", "main": "index.js"}' > "$prefix/node_modules/mermaid/package.json"
    [ "$FAKE_NPM" = fail ] && exit 1
    sleep "${NPM_DELAY:-0}"
    echo 'module.exports = { parse: async () => ({ diagramType: "fake" }) };' > "$prefix/node_modules/mermaid/index.js"
    echo '{"name": "jsdom", "main": "index.js"}' > "$prefix/node_modules/jsdom/package.json"
    echo 'exports.JSDOM = class { constructor() { this.window = { document: {} }; } };' > "$prefix/node_modules/jsdom/index.js"
    """)


class CheckMermaid(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name)
        (self.tmp / "bin").mkdir()
        (self.tmp / "bin" / "npm").write_text(NPM)
        (self.tmp / "bin" / "npm").chmod(0o755)
        self.cache = self.tmp / "cache" / "skills-mermaid"
        self.doc = self.tmp / "doc.md"
        self.doc.write_text("```mermaid\nflowchart LR\n  a --> b\n```\n")
        self.log = self.tmp / "npm.log"

    def run_check(self, **env):
        return subprocess.run(
            ["node", str(SCRIPT), str(self.doc)], capture_output=True, text=True,
            env={**os.environ, "PATH": f"{self.tmp / 'bin'}:{os.environ['PATH']}",
                 "XDG_CACHE_HOME": str(self.tmp / "cache"), "NPM_LOG": str(self.log), **env})

    def installs(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_interrupted_install_is_retried(self):
        failed = self.run_check(FAKE_NPM="fail")
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(list(self.cache.iterdir()), [])
        passed = self.run_check()
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertIn("✅ fake", passed.stdout)
        self.assertEqual(len(self.installs()), 2)

    def test_skips_old_half_installed_folders(self):
        for version in ("12.1.0", "12.2.0"):
            (self.cache / version / "node_modules" / "mermaid").mkdir(parents=True)
        run = self.run_check()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(len(self.installs()), 1)

    def test_concurrent_first_runs_both_pass(self):
        with ThreadPoolExecutor(2) as pool:
            runs = list(pool.map(lambda _: self.run_check(NPM_DELAY="1"), range(2)))
        for run in runs:
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("✅ fake", run.stdout)
        self.assertEqual(len(self.installs()), 2)
        self.assertEqual(len(list(self.cache.iterdir())), 1)

    def entry(self, name, days_old):
        path = self.cache / name
        path.mkdir(parents=True)
        when = time.time() - days_old * DAY
        os.utime(path, (when, when))
        return path

    def test_install_prunes_unused_folders_and_stale_partials(self):
        self.entry("0.0.1-jsdom1.0.0", 31)
        self.entry("0.0.2-jsdom1.0.0", 2)
        self.entry("0.0.3-jsdom1.0.0.partial-old", 2)
        self.entry("0.0.3-jsdom1.0.0.partial-new", 0)
        run = self.run_check()
        self.assertEqual(run.returncode, 0, run.stderr)
        used = {path.name for path in self.cache.iterdir()} - {
            "0.0.2-jsdom1.0.0", "0.0.3-jsdom1.0.0.partial-new"}
        self.assertEqual(len(used), 1, used)
        self.assertTrue(used.pop().endswith("-jsdom30.1.2"))

    def test_each_run_refreshes_the_used_folder(self):
        self.assertEqual(self.run_check().returncode, 0)
        [used] = self.cache.iterdir()
        old = time.time() - 40 * DAY
        os.utime(used, (old, old))
        run = self.run_check()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(len(self.installs()), 1)
        self.assertGreater(used.stat().st_mtime, time.time() - DAY)

    def test_removal_error_does_not_fail_the_check(self):
        stuck = self.entry("0.0.1-jsdom1.0.0", 31) / "locked"
        stuck.mkdir()
        (stuck / "file").write_text("")
        stuck.chmod(0o500)
        self.addCleanup(stuck.chmod, 0o700)
        run = self.run_check()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("✅ fake", run.stdout)
        self.assertTrue((stuck / "file").exists())


if __name__ == "__main__":
    unittest.main()
