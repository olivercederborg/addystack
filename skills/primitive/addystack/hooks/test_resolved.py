"""Tests for resolved: each kind of checkout gets the defaults, its matching rules field by
field, or policy.unresolved; replies() and kit() read resolved.json; and a missing or
unreadable resolved.json gives the kit's defaults. The fixture is built by lib/config.py
from a user config shaped like a real one: loose defaults, a rule that tightens trust, a
path rule, and a team's rule."""
from __future__ import annotations

import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest, unittest.mock

import resolved

HOOKS = pathlib.Path(__file__).resolve().parent
sys.path.append(str(HOOKS.parent / "lib"))
import config  # noqa: E402

USER = """// A user's config.
{
  "identity": { "name": "Sam" },
  "policy": {
    "defaults": { "planning": "autonomous", "trust": "merge-on-go" },
    "repos": [
      { "match": { "remote": "/(blog|site)" }, "trust": "gate" },
      { "match": { "path": "PATHS/*" }, "issues": "github" },
      { "match": { "remote": "[:/]acme-team/" }, "planning": "gated", "trust": "draft", "pushVia": "gh-stack",
        "issues": "linear", "lenses": ["team-conventions"], "verifySkill": "verify-team", "decisionsSection": true },
      { "match": { "remote": "[:/]reviewed/" }, "review": { "app": "my-reviewer" } },
      { "match": { "remote": "[:/]unreviewed/" }, "review": null }
    ]
  },
  "replies": { "style": "reply-shape", "rules": "replies.md", "next": "lettered", "turnBlock": true }
}
"""
FIELDS = ("planning", "trust", "pushVia", "issues")


class Fixture(unittest.TestCase):
    def setUp(self):
        # Resolved, since git prints a checkout's root with symlinks such as /var resolved.
        self.root = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "paths").mkdir()
        # The path rule names a link to paths/, so matching resolves the rule's folders too.
        (self.root / "linked").symlink_to(self.root / "paths")
        user = self.root / "addystack.jsonc"
        user.write_text(USER.replace("PATHS", str(self.root / "linked")))
        (self.root / "replies.md").write_text("rules")
        self.state = self.root / "state" / "resolved.json"
        self.state.parent.mkdir()
        self.state.write_text(json.dumps(config.resolve(user)))
        self.addCleanup(setattr, resolved, "STATE", resolved.STATE)
        resolved.STATE = self.state

    def folder(self, name=None):
        if name is None:
            return pathlib.Path(tempfile.mkdtemp(dir=self.root))
        path = self.root / name
        path.mkdir()
        return path

    def repo(self, name=None, **remotes):
        path = self.folder(name)
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        for remote, url in remotes.items():
            subprocess.run(["git", "-C", str(path), "remote", "add", remote, url], check=True)
        return path

    def fields(self, path, *names):
        policy = resolved.policy(path)
        return tuple(getattr(policy, name) for name in names) + (policy.matched,)


class Policy(Fixture):
    def test_a_team_origin_gets_the_team_rule(self):
        for url in ["git@github.com:acme-team/app.git",
                    "https://github.com/Acme-Team/app.git"]:
            with self.subTest(url=url):
                policy = resolved.policy(self.repo(origin=url))
                self.assertEqual((policy.planning, policy.trust, policy.pushVia, policy.issues),
                                 ("gated", "draft", "gh-stack", "linear"))
                self.assertEqual(policy.verifySkill, "verify-team")
                self.assertTrue(policy.decisionsSection)
                self.assertIn("team-conventions", policy.lenses)
                self.assertEqual(policy.matched, ("user#2",))

    def test_another_origin_gets_the_defaults(self):
        path = self.repo(origin="git@github.com:sam/skills.git")
        self.assertEqual(self.fields(path, *FIELDS), ("autonomous", "merge-on-go", "git", "none", ()))

    def test_a_lookalike_org_gets_the_defaults(self):
        path = self.repo(origin="git@github.com:not-acme-team/x.git")
        self.assertEqual(self.fields(path, "planning", "trust"), ("autonomous", "merge-on-go", ()))

    def test_a_rule_sets_only_its_own_fields(self):
        path = self.repo(origin="https://github.com/sam/site.git")
        self.assertEqual(self.fields(path, *FIELDS), ("autonomous", "gate", "git", "none", ("user#0",)))

    def test_matching_rules_apply_field_by_field_in_order(self):
        path = self.repo("paths/blog", origin="git@github.com:sam/blog.git")
        self.assertEqual(self.fields(path, "trust", "issues"), ("gate", "github", ("user#0", "user#1")))

    def test_no_remotes_gets_the_defaults(self):
        self.assertEqual(self.fields(self.repo(), "planning", "trust"), ("autonomous", "merge-on-go", ()))

    def test_a_path_rule_matches_a_repo_with_no_remotes(self):
        path = self.repo("paths/new")
        self.assertEqual(self.fields(path / ".", "issues"), ("github", ("user#1",)))

    def test_a_path_rule_matches_through_a_link(self):
        self.repo("paths/new")
        self.assertEqual(self.fields(self.root / "linked" / "new", "issues"), ("github", ("user#1",)))

    def test_a_wildcard_that_covers_a_link_matches_from_a_subfolder(self):
        repo = self.repo("team-real")
        (repo / "sub").mkdir()
        (self.root / "paths" / "team").symlink_to(repo)
        self.assertEqual(self.fields(self.root / "linked" / "team" / "sub", "issues"), ("github", ("user#1",)))

    def test_remotes_without_origin_get_unresolved(self):
        path = self.repo(upstream="git@github.com:a/b.git")
        self.assertEqual(self.fields(path, *FIELDS), ("gated", "draft", "gh-stack", "linear", ("unresolved",)))

    def test_a_git_error_inside_a_repo_gets_unresolved(self):
        path = self.repo(origin="git@github.com:sam/skills.git")
        with open(path / ".git" / "config", "a") as git_config:
            git_config.write("[broken\n")
        self.assertEqual(self.fields(path, "planning", "trust"), ("gated", "draft", ("unresolved",)))

    def test_a_folder_outside_a_repo_gets_the_defaults(self):
        self.assertEqual(self.fields(self.folder(), "planning", "trust"), ("autonomous", "merge-on-go", ()))
        self.assertEqual(self.fields(self.root / "missing", "planning"), ("autonomous", ()))


class RepoFile(Fixture):
    """A repo's own .agents/addystack.jsonc only tightens the user's policy (D14)."""

    def with_file(self, text, **remotes):
        path = self.repo(**remotes)
        (path / ".agents").mkdir()
        (path / ".agents" / "addystack.jsonc").write_text(text)
        return path

    def test_merge_on_go_doesnt_loosen_a_draft_user(self):
        path = self.with_file('{ "trust": "merge-on-go", "planning": "autonomous", "pushVia": "git" }',
                              origin="git@github.com:acme-team/app.git")
        self.assertEqual(self.fields(path, "planning", "trust", "pushVia"),
                         ("gated", "draft", "gh-stack", ("user#2", "repo-file")))

    def test_gated_tightens_an_autonomous_user(self):
        path = self.with_file('// Our team plans first.\n{ "planning": "gated" }',
                              origin="git@github.com:sam/skills.git")
        self.assertEqual(self.fields(path, "planning", "trust", "pushVia"),
                         ("gated", "merge-on-go", "git", ("repo-file",)))

    def test_each_field_takes_the_stricter_value(self):
        path = self.with_file('{ "trust": "gate", "pushVia": "gh-stack" }',
                              origin="https://github.com/sam/site.git")
        self.assertEqual(self.fields(path, "planning", "trust", "pushVia"),
                         ("autonomous", "gate", "gh-stack", ("user#0", "repo-file")))
        draft = self.with_file('{ "trust": "draft" }', origin="https://github.com/sam/site.git")
        self.assertEqual(self.fields(draft, "trust"), ("draft", ("user#0", "repo-file")))

    def test_gate_doesnt_loosen_a_merge_on_go_user(self):
        # gate merges without the user's go, so it's looser than merge-on-go.
        path = self.with_file('{ "trust": "gate" }', origin="git@github.com:sam/skills.git")
        self.assertEqual(self.fields(path, "trust"), ("merge-on-go", ("repo-file",)))
        tighter = self.with_file('{ "trust": "merge-on-go" }',
                                 origin="https://github.com/sam/site.git")
        self.assertEqual(self.fields(tighter, "trust"), ("merge-on-go", ("user#0", "repo-file")))

    def test_a_top_level_ending_in_a_space_keeps_its_file(self):
        path = self.repo("checkout ", origin="git@github.com:sam/skills.git")
        (path / ".agents").mkdir()
        (path / ".agents" / "addystack.jsonc").write_text('{ "pushVia": "gh-stack" }')
        self.assertEqual(self.fields(path, "pushVia"), ("gh-stack", ("repo-file",)))

    def test_the_file_is_read_from_the_top_level(self):
        path = self.with_file('{ "planning": "gated" }', origin="git@github.com:sam/skills.git")
        (path / "sub").mkdir()
        self.assertEqual(self.fields(path / "sub", "planning"), ("gated", ("repo-file",)))

    def test_an_invalid_file_gives_unresolved(self):
        for text in ["{not json", "[]", '{ "issues": "linear" }', '{ "trust": "maybe" }',
                     '{ "lenses": ["x"], "planning": "gated" }']:
            with self.subTest(text=text):
                path = self.with_file(text, origin="git@github.com:sam/skills.git")
                self.assertEqual(self.fields(path, *FIELDS),
                                 ("gated", "draft", "gh-stack", "linear", ("unresolved", "repo-file-invalid")))

    def test_an_unreadable_file_gives_unresolved(self):
        path = self.repo(origin="git@github.com:sam/skills.git")
        (path / ".agents" / "addystack.jsonc").mkdir(parents=True)
        self.assertEqual(self.fields(path, "trust"), ("draft", ("unresolved", "repo-file-invalid")))
        link = self.repo(origin="git@github.com:sam/skills.git")
        (link / ".agents").mkdir()
        (link / ".agents" / "addystack.jsonc").symlink_to(self.root / "gone.jsonc")
        self.assertEqual(self.fields(link, "trust"), ("draft", ("unresolved", "repo-file-invalid")))

    def test_a_file_that_isnt_utf8_gives_unresolved(self):
        path = self.with_file("", origin="git@github.com:sam/skills.git")
        (path / ".agents" / "addystack.jsonc").write_bytes(b"\xff")
        self.assertEqual(self.fields(path, "trust"), ("draft", ("unresolved", "repo-file-invalid")))

    def test_a_fifo_gives_unresolved_without_reading_it(self):
        path = self.repo(origin="git@github.com:sam/skills.git")
        (path / ".agents").mkdir()
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        (path / ".agents" / "addystack.jsonc").symlink_to(fifo)
        # Opening the FIFO would block until a writer came, so a finished call proves it wasn't.
        self.assertEqual(self.fields(path, "trust"), ("draft", ("unresolved", "repo-file-invalid")))

    @unittest.skipIf(os.geteuid() == 0, "root can search any folder")
    def test_a_folder_that_cant_be_searched_gives_unresolved(self):
        path = self.with_file('{ "pushVia": "gh-stack" }', origin="git@github.com:sam/skills.git")
        (path / ".agents").chmod(0)
        self.addCleanup((path / ".agents").chmod, 0o755)
        self.assertEqual(self.fields(path, "trust"), ("draft", ("unresolved", "repo-file-invalid")))

    def test_a_file_the_decoder_chokes_on_gives_unresolved(self):
        # Nesting past the recursion limit raises RecursionError, not a JSON decode error.
        path = self.with_file("[" * 5000, origin="git@github.com:sam/skills.git")
        self.assertEqual(self.fields(path, "trust"), ("draft", ("unresolved", "repo-file-invalid")))

    def test_inside_the_git_folder_fails_closed(self):
        path = self.with_file('{ "pushVia": "gh-stack" }', origin="git@github.com:sam/skills.git")
        self.assertEqual(self.fields(path / ".git", "pushVia"), ("gh-stack", ("unresolved",)))

    def test_an_unexpected_lookup_error_gives_unresolved(self):
        path = self.repo(origin="git@github.com:sam/skills.git")
        real = resolved._git

        def flaky(checkout, *args):
            if args[:2] == ("rev-parse", "--show-toplevel"):
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
            return real(checkout, *args)
        with unittest.mock.patch.object(resolved, "_git", flaky):
            self.assertEqual(self.fields(path, "trust"), ("draft", ("unresolved",)))

    def test_a_projects_config_module_on_pythonpath_doesnt_replace_the_kits(self):
        path = self.with_file('{ "pushVia": "gh-stack" }', origin="git@github.com:sam/skills.git")
        project = self.folder("project")
        (project / "config.py").write_text("raise SystemExit('project code ran')\n")
        run = subprocess.run([sys.executable, "-c", "import resolved, sys; print(resolved.policy(sys.argv[1]).pushVia)",
                              str(path)], capture_output=True, text=True, cwd=str(HOOKS),
                             env={**os.environ, "PYTHONPATH": str(project), "ADDYSTACK_STATE": str(self.state.parent)})
        self.assertEqual((run.returncode, run.stdout.strip()), (0, "gh-stack"), run.stderr)

    def test_a_dangling_agents_link_gives_unresolved(self):
        path = self.repo(origin="git@github.com:sam/skills.git")
        (path / ".agents").symlink_to(self.root / "gone")
        self.assertEqual(self.fields(path, "trust"), ("draft", ("unresolved", "repo-file-invalid")))

    def test_a_repo_file_names_the_review_app_for_every_user(self):
        path = self.with_file('{ "review": { "app": "acme-reviewer" } }', origin="git@github.com:sam/skills.git")
        self.assertEqual(self.fields(path, "review", "trust"),
                         (resolved.Review("acme-reviewer"), "merge-on-go", ("repo-file",)))

    def test_the_users_review_app_wins_over_the_repo_files(self):
        path = self.with_file('{ "review": { "app": "acme-reviewer" } }', origin="git@github.com:reviewed/app.git")
        self.assertEqual(self.fields(path, "review"), (resolved.Review("my-reviewer"), ("user#3", "repo-file")))

    def test_a_users_null_review_turns_the_repo_files_app_off(self):
        path = self.with_file('{ "review": { "app": "acme-reviewer" } }', origin="git@github.com:unreviewed/app.git")
        self.assertEqual(self.fields(path, "review"), (None, ("user#4", "repo-file")))

    def test_without_a_review_app_anywhere_review_is_none(self):
        path = self.with_file('{ "trust": "draft" }', origin="git@github.com:sam/skills.git")
        self.assertEqual(self.fields(path, "review"), (None, ("repo-file",)))

    def test_a_malformed_review_gives_unresolved(self):
        for text in ['{ "review": "acme-reviewer" }', '{ "review": {} }', '{ "review": { "app": 1 } }',
                     '{ "review": { "app": "x", "required": true } }',
                     # Agents paste the slug into shell commands, so only a slug is accepted.
                     '{ "review": { "app": "x\'; touch pwned; echo \'" } }', '{ "review": { "app": "My Reviewer" } }',
                     '{ "review": { "app": "my-reviewer[bot]" } }']:
            with self.subTest(text=text):
                path = self.with_file(text, origin="git@github.com:sam/skills.git")
                self.assertEqual(self.fields(path, "review", "trust"),
                                 (None, "draft", ("unresolved", "repo-file-invalid")))

    def test_without_a_file_the_policy_is_the_users(self):
        path = self.repo(origin="git@github.com:sam/skills.git")
        (path / ".agents").mkdir()
        self.assertEqual(self.fields(path, "planning", "trust"), ("autonomous", "merge-on-go", ()))


class Replies(Fixture):
    def test_reads_the_reply_preferences(self):
        self.assertEqual(resolved.replies(), resolved.Replies("reply-shape", self.root / "replies.md", "lettered", True))

    def test_kit_is_this_checkout(self):
        self.assertEqual(resolved.kit(), HOOKS.parent)


class MissingState(Fixture):
    def assertKitDefaults(self):
        path = self.repo(origin="git@github.com:sam/skills.git")
        self.assertEqual(self.fields(path, *FIELDS), ("gated", "draft", "git", "none", ()))
        self.assertEqual(resolved.replies(), resolved.Replies("own", None, "off", False))
        self.assertEqual(resolved.kit(), HOOKS.parent)

    def test_a_missing_file_gives_the_kit_defaults(self):
        self.state.unlink()
        self.assertKitDefaults()

    def test_an_unreadable_file_gives_the_kit_defaults(self):
        for text in ["{not json", "[]", "[" * 5000 + "]" * 5000, '{"kit": "/x"}', '{"kit": "/x", "policy": {}, "replies": {}}',
                     '{"kit": "/x", "policy": {"defaults": {}, "unresolved": {}, "rules": []}, "replies": {}}']:
            with self.subTest(text=text):
                self.state.write_text(text)
                self.assertKitDefaults()

    def test_a_build_from_before_review_reads_as_no_review_app(self):
        data = json.loads(self.state.read_text())
        for fields in (data["policy"]["defaults"], data["policy"]["unresolved"]):
            del fields["review"]
        self.state.write_text(json.dumps(data))
        path = self.repo(origin="git@github.com:sam/skills.git")
        self.assertEqual(self.fields(path, "planning", "review"), ("autonomous", None, ()))

    def test_a_field_of_the_wrong_type_or_value_gives_the_kit_defaults(self):
        good = self.state.read_text()
        self.assertIn('"lenses": []', good)
        for bad in (good.replace('"lenses": []', '"lenses": null'),
                    good.replace('"style": "reply-shape"', '"style": "fancy"'),
                    good.replace('"trust": "gate"', '"trust": "maybe"')):
            with self.subTest(bad=bad[:40]):
                self.assertNotEqual(bad, good)
                self.state.write_text(bad)
                self.assertKitDefaults()


if __name__ == "__main__":
    unittest.main()
