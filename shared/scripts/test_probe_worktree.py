"""Layout tests for probe-worktree.sh: build a small repo, create a probe worktree, and
check where each node_modules link resolves."""
import os, pathlib, subprocess, tempfile, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "probe-worktree.sh"


def run(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout


class ProbeWorktree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name).resolve() / "repo"
        for package in ("a", "b"):
            (self.repo / "packages" / package).mkdir(parents=True)
            (self.repo / "packages" / package / "package.json").write_text("{}")
        run(self.repo, "git", "init", "-q")
        run(self.repo, "git", "add", ".")
        run(self.repo, "git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
        self.probe = None

    def tearDown(self):
        if self.probe:
            run(self.repo, str(SCRIPT), "remove", str(self.probe))
        self.tmp.cleanup()

    def create(self):
        self.probe = pathlib.Path(run(self.repo, str(SCRIPT), "create", "HEAD").strip())
        return self.probe

    def link(self, relative, target):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, path)

    def test_creates_a_worktree_without_node_modules(self):
        probe = self.create()
        self.assertTrue((probe / "packages" / "a" / "package.json").exists())
        self.assertFalse((probe / "node_modules").exists())

    def test_points_a_hoisted_workspace_link_at_the_probe_tree(self):
        (self.repo / "node_modules" / "lodash").mkdir(parents=True)
        self.link("node_modules/@s/b", "../../packages/b")
        probe = self.create()
        self.assertEqual((probe / "node_modules/@s/b").resolve(), probe / "packages" / "b")
        self.assertEqual((probe / "node_modules/lodash").resolve(), self.repo / "node_modules" / "lodash")

    def test_points_a_nested_workspace_link_at_the_probe_tree(self):
        (self.repo / "packages/a/node_modules/react").mkdir(parents=True)
        self.link("packages/a/node_modules/@s/b", "../../../b")
        probe = self.create()
        self.assertEqual((probe / "packages/a/node_modules/@s/b").resolve(), probe / "packages" / "b")
        self.assertEqual((probe / "packages/a/node_modules/react").resolve(),
                         self.repo / "packages/a/node_modules/react")

    def test_keeps_a_dangling_link(self):
        (self.repo / "node_modules").mkdir()
        self.link("node_modules/ghost", "../nowhere/ghost")
        probe = self.create()
        self.assertTrue((probe / "node_modules" / "ghost").is_symlink())


if __name__ == "__main__":
    unittest.main()
