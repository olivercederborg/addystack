"""Tests for check-reply-budget.py: each payload is checked on its own against 8,000
characters, a reply-shape or rules payload over it fails, a rules file that can't load
fails, the rules file is the one the built config names, or the kit's replies.md
without a build, and the checkout's own copies count their path as 80 characters."""
import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent
KIT = SCRIPTS.parent / "skills" / "primitive" / "addystack"
HOOKS = KIT / "hooks"
sys.path.insert(0, str(KIT / "lib"))
import config  # noqa: E402


def built(folder, rules):
    """An ADDYSTACK_STATE folder whose resolved.json names rules, built by lib/config.py."""
    user = pathlib.Path(folder, "addystack.jsonc")
    user.write_text(json.dumps({"replies": {"style": "reply-shape", "rules": str(rules)}}))
    layers = config.load_layers(user)
    assert not config.validate(layers), config.validate(layers)
    pathlib.Path(folder, "resolved.json").write_text(json.dumps(config.merge(layers, KIT)))
    return folder


def run(skill=100, replies=100, state=None, installed=None, deep=False):
    """Runs a copy of the check against rules files of these sizes; None leaves one out.
    state is the ADDYSTACK_STATE folder, a missing one by default; installed is the
    reply-shape the hook loads (REPLY_SHAPE_SKILL), a missing one by default, or "own"
    for the checkout's own copy; deep puts the copy in a folder whose path passes 200
    characters."""
    temp = pathlib.Path(tempfile.mkdtemp())
    root = temp / ("checkout-" + "x" * 200) if deep else temp
    try:
        for folder, names in (("scripts", [SCRIPTS / "check-reply-budget.py"]),
                              ("skills/primitive/addystack/hooks",
                               [HOOKS / "reply-shape-context.py", HOOKS / "t3_child.py", HOOKS / "resolved.py"])):
            (root / folder).mkdir(parents=True)
            for name in names:
                shutil.copy(name, root / folder)
        reply_shape = root / "skills" / "optional" / "reply-shape"
        reply_shape.mkdir(parents=True)
        if skill is not None:
            (reply_shape / "SKILL.md").write_text("---\nname: reply-shape\n---\n" + "x" * skill)
        if replies is not None:
            (root / "replies.md").write_text("x" * replies)
        env = {**os.environ, "ADDYSTACK_STATE": state or str(root / "no-state"),
               "REPLY_SHAPE_SKILL": str(reply_shape / "SKILL.md") if installed == "own"
               else installed or str(root / "no-installed-skill")}
        return subprocess.run([str(root / "scripts" / "check-reply-budget.py")],
                              capture_output=True, text=True, env=env)
    finally:
        shutil.rmtree(temp)


class CheckReplyBudget(unittest.TestCase):
    def test_passes_under_the_budget(self):
        result = run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reply-shape: ", result.stdout)
        self.assertIn("rules: ", result.stdout)

    def test_checks_each_payload_on_its_own(self):
        # Together they pass 8,000; each alone is under it.
        result = run(skill=5_000, replies=5_000)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fails_when_reply_shape_is_over(self):
        result = run(skill=8_000)
        self.assertEqual(result.returncode, 1)
        self.assertIn("reply-shape: over the budget", result.stderr)

    def test_fails_when_replies_is_over(self):
        result = run(replies=8_000)
        self.assertEqual(result.returncode, 1)
        self.assertIn("rules: over the budget", result.stderr)

    def test_fails_when_reply_shape_cant_load(self):
        result = run(skill=None)
        self.assertEqual(result.returncode, 1)
        self.assertIn("reply-shape: couldn't load", result.stderr)

    def test_a_checkout_without_replies_checks_only_reply_shape(self):
        result = run(replies=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("rules:", result.stdout)

    def test_a_configured_rules_file_that_cant_load_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            rules = pathlib.Path(folder, "mine.md")
            rules.write_text("y")
            state = built(folder, rules)
            rules.chmod(0)
            try:
                result = run(replies=None, state=state)
            finally:
                rules.chmod(0o644)
        self.assertEqual(result.returncode, 1)
        self.assertIn("rules: couldn't load", result.stderr)

    def test_without_a_build_checks_the_kits_replies(self):
        result = run()
        self.assertRegex(result.stdout, r"rules: .*/replies\.md\)")

    def test_checks_the_rules_file_the_build_names(self):
        with tempfile.TemporaryDirectory() as folder:
            rules = pathlib.Path(folder, "mine.md")
            rules.write_text("y" * 9_000)
            result = run(replies=100, state=built(folder, rules))
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"({rules})", result.stdout)
        self.assertIn("rules: over the budget", result.stderr)

    def test_a_checkout_replies_over_budget_fails_even_when_the_build_names_another(self):
        with tempfile.TemporaryDirectory() as folder:
            rules = pathlib.Path(folder, "mine.md")
            rules.write_text("y" * 100)
            result = run(replies=9_000, state=built(folder, rules))
        self.assertEqual(result.returncode, 1)
        self.assertIn("rules: over the budget", result.stderr)

    # The hook's header is 70 characters plus the path, counted as 80 for the checkout's
    # copies, so 7,850 characters of text come to exactly 8,000 wherever the checkout sits.
    def test_a_long_checkout_path_counts_as_80(self):
        result = run(skill=7_850, replies=7_850, deep=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reply-shape: 8,000 of 8,000", result.stdout)
        self.assertIn("rules: 8,000 of 8,000", result.stdout)

    def test_a_short_checkout_path_counts_as_80(self):
        result = run(skill=7_851, replies=7_851)
        self.assertEqual(result.returncode, 1)
        self.assertIn("reply-shape: 8,001 of 8,000", result.stdout)
        self.assertIn("rules: 8,001 of 8,000", result.stdout)

    def test_a_checkout_copy_the_hook_loads_counts_its_real_path(self):
        result = run(skill=7_850, replies=None, installed="own", deep=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("reply-shape: 8,000 of 8,000", result.stdout)
        self.assertIn("reply-shape: over the budget", result.stderr)

    def test_checks_the_reply_shape_the_hook_loads(self):
        with tempfile.TemporaryDirectory() as folder:
            installed = pathlib.Path(folder, "SKILL.md")
            installed.write_text("z" * 9_000)
            result = run(installed=str(installed))
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"({installed})", result.stdout)


if __name__ == "__main__":
    unittest.main()
