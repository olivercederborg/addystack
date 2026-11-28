"""Tests for lib/config.py: JSONC comments strip outside strings, layers load in merge
order, validation names each bad key's dotted path, and merge applies the docstring's
rules, including policy.unresolved's strictest values."""
from __future__ import annotations

import json, os, pathlib, sys, tempfile, unittest, unittest.mock

KIT = pathlib.Path(__file__).resolve().parent.parent / "skills" / "primitive" / "addystack"
sys.path.insert(0, str(KIT / "lib"))
import config  # noqa: E402
from config import Issue, Layer  # noqa: E402

SCHEMA = json.loads((KIT / "schema" / "v1.json").read_text())
DEFAULTS = config.load_layers(KIT / "missing")[0]
LOOSE = {"planning": "autonomous", "trust": "merge-on-go", "pushVia": "git", "issues": "none", "lenses": [],
         "verifySkill": None, "decisionsSection": False, "review": None}


def schema_nodes(node):
    """Every schema object inside node, node included."""
    if isinstance(node, dict):
        yield node
        for key, value in node.items():
            if key in ("properties", "definitions"):
                for child in value.values():
                    yield from schema_nodes(child)
            elif key in ("items", "additionalProperties"):
                yield from schema_nodes(value)


def leaves(node, path=()):
    """(path, default) for each schema key with no properties of its own, or whose default
    is null, outside arrays."""
    for name, child in node.get("properties", {}).items():
        while "$ref" in child:
            child = SCHEMA["definitions"][child["$ref"].split("/")[-1]]
        if "properties" in child and child["default"] is not None:
            yield from leaves(child, (*path, name))
        else:
            yield (*path, name), child["default"]


class Workspace(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = pathlib.Path(folder.name)

    def write(self, name, text):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path


class StripComments(unittest.TestCase):
    def test_strips_line_and_block_comments(self):
        text = '{\n  // a line\n  "a": 1, /* a block */ "b": 2\n}'
        self.assertEqual(json.loads(config.strip_comments(text)), {"a": 1, "b": 2})

    def test_keeps_comment_markers_inside_strings(self):
        text = '{"url": "https://example.com//x", "glob": "a/*b*/c", "quote": "say \\"/* hi\\" // there"}'
        self.assertEqual(json.loads(config.strip_comments(text)),
                         {"url": "https://example.com//x", "glob": "a/*b*/c", "quote": 'say "/* hi" // there'})

    def test_an_escaped_backslash_ends_the_string(self):
        text = '{"path": "C:\\\\", // gone\n "b": 1}'
        self.assertEqual(json.loads(config.strip_comments(text)), {"path": "C:\\", "b": 1})

    def test_a_block_comment_keeps_line_numbers(self):
        text = '{\n/* one\ntwo\n*/\n"a": }'
        with self.assertRaises(json.JSONDecodeError) as caught:
            json.loads(config.strip_comments(text))
        self.assertEqual(caught.exception.lineno, 5)


class LoadLayers(Workspace):
    def test_without_a_user_config_only_the_defaults_load(self):
        layers = config.load_layers(self.dir / "missing.jsonc")
        self.assertEqual([layer.name for layer in layers], ["defaults"])

    def test_the_user_loads_after_the_defaults(self):
        user = self.write("addystack.jsonc", '// mine\n{"identity": {"name": "Sam"}}')
        layers = config.load_layers(user)
        self.assertEqual([layer.name for layer in layers], ["defaults", "user"])
        self.assertEqual(layers[1].dir, self.dir)

    def test_bad_jsonc_names_the_file_and_line(self):
        user = self.write("addystack.jsonc", '{\n  "version": 1\n  "identity": {}\n}')
        with self.assertRaises(config.Invalid) as caught:
            config.load_layers(user)
        [issue] = caught.exception.issues
        self.assertEqual(issue.path, str(user))
        self.assertIn("line 3", issue.message)


class Review(Workspace):
    """Inputs that passed silently or crashed before (review-loop round 1)."""

    def test_wrong_shapes_report_instead_of_crashing(self):
        for data, path in [({"policy": None}, "policy"),
                           ({"policy": {"repos": [{"match": None}]}}, "policy.repos.0.match")]:
            with self.subTest(data=data):
                self.assertIn(path, [issue.path for issue in config.validate([Layer("user", self.dir, data)])])

    def test_a_named_file_that_isnt_there_is_an_issue(self):
        self.write("taste.md", "taste")
        data = {"judgment": {"taste": "taste.md"}, "instructions": "missing.md",
                "policy": {"repos": [{"match": {"remote": "x"}, "lenses": ["skill", "gone.md"]}]}}
        issues = config.validate([Layer("user", self.dir, data)])
        self.assertEqual([issue.path for issue in issues], ["instructions", "policy.repos.0.lenses.1"])
        self.assertIn(str(self.dir / "missing.md"), issues[0].message)

    def test_a_link_to_a_missing_config_is_an_issue(self):
        user = self.dir / "addystack.jsonc"
        user.symlink_to(self.dir / "moved.jsonc")
        with self.assertRaises(config.Invalid) as caught:
            config.load_layers(user)
        self.assertIn("doesn't exist", caught.exception.issues[0].message)

    def test_a_named_file_that_cant_be_read_is_an_issue(self):
        path = self.write("global.md", "mine")
        path.chmod(0)
        self.addCleanup(path.chmod, 0o644)
        issues = config.validate([Layer("user", self.dir, {"instructions": "global.md"})])
        self.assertEqual([(issue.path, issue.message) for issue in issues], [("instructions", f"can't read {path}")])

    def test_true_isnt_the_version_1(self):
        issues = config.validate([Layer("user", self.dir, {"version": True})])
        self.assertEqual([issue.path for issue in issues], ["version"])

    def test_an_unterminated_block_comment_is_invalid(self):
        user = self.write("addystack.jsonc", '{"version": 1} /* unfinished')
        with self.assertRaises(config.Invalid):
            config.load_layers(user)


class Validate(unittest.TestCase):
    def issues(self, data, name="user"):
        return config.validate([Layer(name, KIT, data)])

    def test_the_kit_files_are_valid(self):
        examples = config.load_layers(KIT / "examples" / "addystack.jsonc")
        self.assertEqual([layer.name for layer in examples], ["defaults", "user"])
        self.assertEqual(config.validate(examples), [])

    def test_a_typo_in_a_value_names_its_key_path(self):
        self.assertEqual(self.issues({"replies": {"style": "reply-shap"}}),
                         [Issue("replies.style", '"reply-shap" is not one of reply-shape, own')])

    def test_an_unknown_key_names_its_path(self):
        [issue] = self.issues({"replies": {"styel": "own"}})
        self.assertEqual(issue.path, "replies.styel")
        self.assertIn("unknown key", issue.message)

    def test_array_items_are_numbered(self):
        rules = [{"match": {"path": "~/a"}}, {"match": {"remote": "x"}, "trust": 3}, {"trust": "gate"}]
        self.assertEqual(self.issues({"policy": {"repos": rules}}), [
            Issue("policy.repos.1.trust", '3 is not one of draft, gate, merge-on-go'),
            Issue("policy.repos.2.match", "missing"),
        ])

    def test_types_consts_and_empty_matches(self):
        self.assertEqual(self.issues({"version": 2, "hosts": {"claude": 1}, "policy": {"repos": [{"match": {}}]}}), [
            Issue("version", "must be 1"),
            Issue("hosts.claude", "expected boolean, got number"),
            Issue("policy.repos.0.match", "needs at least 1 key"),
        ])

    def test_a_remote_that_isnt_a_regex_is_an_issue(self):
        [issue] = self.issues({"policy": {"repos": [{"match": {"remote": "[:/]org("}}]}})
        self.assertEqual(issue.path, "policy.repos.0.match.remote")
        self.assertIn("not a valid regex", issue.message)

    def test_extends_is_removed_and_says_what_to_do_instead(self):
        for value in (["team"], [], "team"):
            with self.subTest(value=value):
                [issue] = self.issues({"extends": value, "identity": {"name": "Sam"}})
                self.assertEqual(issue.path, "extends")
                self.assertIn("first in policy.repos[]", issue.message)
                self.assertIn("relative to this config or absolute", issue.message)

    def test_skills_is_removed_and_says_to_install_with_the_skills_cli(self):
        for value in ({"enable": ["my-inbox"]}, {}, []):
            with self.subTest(value=value):
                [issue] = self.issues({"skills": value})
                self.assertEqual(issue.path, "skills")
                self.assertIn("npx skills add <source> --skill <name> -g", issue.message)

    def test_a_nested_extends_is_an_ordinary_unknown_key(self):
        [issue] = self.issues({"replies": {"extends": []}})
        self.assertEqual(issue.path, "replies.extends")
        self.assertIn("unknown key", issue.message)

    def test_the_schema_uses_only_keywords_validate_evaluates(self):
        used = {key for node in schema_nodes(SCHEMA) for key in node}
        self.assertLessEqual(used, config._ASSERTIONS | config._ANNOTATIONS)

    def test_an_unknown_keyword_stops_validation(self):
        with self.assertRaises(ValueError):
            list(config._check("x", {"format": "y"}, [], {}))

    def test_a_string_must_match_its_pattern(self):
        self.assertEqual(list(config._check("my-app", {"pattern": "^[a-z-]+$"}, [], {})), [])
        [issue] = config._check("My App", {"pattern": "^[a-z-]+$"}, ["app"], {})
        self.assertEqual((issue.path, issue.message), ("app", '"My App" doesn\'t match ^[a-z-]+$'))


class ClaudeHome(Workspace):
    """claude_home() is Claude Code's folder as Claude Code and the skills CLI read it:
    $CLAUDE_CONFIG_DIR when it isn't blank, else ~/.claude, looked up on each call."""

    def home(self, **env):
        with unittest.mock.patch.dict(os.environ, {"HOME": str(self.dir), **env}):
            if "CLAUDE_CONFIG_DIR" not in env:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            return config.claude_home()

    def test_claude_config_dir_trimmed_and_expanded(self):
        self.assertEqual(self.home(CLAUDE_CONFIG_DIR="/opt/claude"), pathlib.Path("/opt/claude"))
        self.assertEqual(self.home(CLAUDE_CONFIG_DIR=" /opt/claude\n"), pathlib.Path("/opt/claude"))
        # Like the skills CLI: a `~` stays literal, and a relative path is from the working
        # directory.
        self.assertEqual(self.home(CLAUDE_CONFIG_DIR="~/claude-work"), pathlib.Path.cwd() / "~/claude-work")
        self.assertEqual(self.home(CLAUDE_CONFIG_DIR="cc"), pathlib.Path.cwd() / "cc")
        self.assertEqual(self.home(CLAUDE_CONFIG_DIR="/opt/missing/../claude"), pathlib.Path("/opt/claude"))

    def test_unset_or_blank_is_dot_claude_in_home(self):
        self.assertEqual(self.home(), self.dir / ".claude")
        self.assertEqual(self.home(CLAUDE_CONFIG_DIR=""), self.dir / ".claude")
        self.assertEqual(self.home(CLAUDE_CONFIG_DIR="  "), self.dir / ".claude")


class KitFiles(unittest.TestCase):
    def test_the_defaults_file_sets_each_schema_default(self):
        defaults = config.load_layers(KIT / "missing")[0].data
        for path, default in leaves(SCHEMA):
            if path == ("$schema",):
                continue
            with self.subTest(key=".".join(path)):
                value = defaults
                for part in path:
                    value = value[part]
                self.assertEqual(value, default)


class Merge(Workspace):
    def merge(self, *layers):
        """The layers merged over the kit's defaults, as load_layers always starts."""
        return config.merge([DEFAULTS, *layers], KIT)

    def kit(self, data, folder=KIT):
        """The kit's defaults with data over them, as a kit could ship them."""
        return Layer("defaults", folder, config._deep_merge(DEFAULTS.data, data))

    def test_objects_deep_merge_and_later_scalars_win(self):
        resolved = config.merge([self.kit({"hosts": {"machines": ["a"]}}),
                              Layer("user", self.dir, {"identity": {"name": "Sam"}, "hosts": {"machines": ["b"]}})], KIT)
        self.assertEqual(resolved["identity"], {"name": "Sam", "github": None})
        self.assertEqual(resolved["hosts"], {"claude": True, "codex": True, "t3": False, "machines": ["b"]})

    def test_repo_rules_concatenate_in_layer_order(self):
        rule = {"match": {"remote": "x"}, "trust": "gate"}
        resolved = config.merge([self.kit({"policy": {"defaults": LOOSE, "repos": [rule]}}),
                                Layer("user", self.dir, {"policy": {"repos": [rule, {"match": {"path": "~/p/*"}}]}})],
                               KIT)
        rules = resolved["policy"]["rules"]
        self.assertEqual([r["source"] for r in rules], ["defaults#0", "user#0", "user#1"])
        self.assertEqual(rules[0]["set"], {"trust": "gate"})
        self.assertEqual(rules[2]["match"], {"path": str(pathlib.Path.home() / "p" / "*")})

    def test_enable_and_disable_apply_in_layer_order(self):
        resolved = config.merge([self.kit({"hooks": {"enable": ["a", "b"]}}),
                                Layer("user", self.dir, {"hooks": {"preset": "all", "disable": ["a"], "enable": ["c"]}})],
                               KIT)
        self.assertEqual(resolved["hooks"], {"preset": "all", "enable": ["b", "c"], "disable": ["a"]})
        self.assertNotIn("skills", resolved)

    def test_principle_excludes_combine(self):
        resolved = config.merge([self.kit({"judgment": {"principles": {"exclude": ["slim-scope"]}}}),
                                Layer("user", self.dir, {"judgment": {"principles": {"preset": "addystack",
                                                                                     "exclude": ["check-exposure"]}}})],
                               KIT)
        self.assertEqual(resolved["judgment"]["principles"],
                         {"preset": "addystack", "exclude": ["slim-scope", "check-exposure"]})

    def test_relative_paths_resolve_against_their_own_layer(self):
        kit = self.dir / "kit"
        resolved = config.merge([
            self.kit({"instructions": "team.md",
                      "policy": {"repos": [{"match": {"remote": "x"}, "lenses": ["skill", "../a.md"]}]}}, kit),
            Layer("user", self.dir, {"instructions": "global.md", "replies": {"rules": "replies.md"},
                                     "judgment": {"taste": "~/taste.md"}})], KIT)
        self.assertEqual(resolved["instructions"], [str(kit / "team.md"), str(self.dir / "global.md")])
        self.assertEqual(resolved["replies"]["rules"], str(self.dir / "replies.md"))
        self.assertEqual(resolved["judgment"]["taste"], str(pathlib.Path.home() / "taste.md"))
        self.assertEqual(resolved["policy"]["rules"][0]["set"]["lenses"], ["skill", str(self.dir / "a.md")])

    def test_unresolved_takes_the_strictest_value_of_each_field(self):
        team = {"match": {"remote": "team"}, "planning": "gated", "trust": "draft", "pushVia": "gh-stack",
                "issues": "linear", "lenses": ["team-lens"], "verifySkill": "verify-team", "decisionsSection": True,
                "review": {"app": "team-reviewer"}}
        mine = {"match": {"remote": "mine"}, "trust": "gate", "issues": "github", "lenses": ["my-lens"]}
        resolved = config.merge([self.kit({"policy": {"defaults": {**LOOSE, "lenses": ["base"]}}}),
                                Layer("user", self.dir, {"policy": {"repos": [mine, team]}})], KIT)
        self.assertEqual(resolved["policy"]["defaults"], {**LOOSE, "lenses": ["base"]})
        self.assertEqual(resolved["policy"]["unresolved"], {
            "planning": "gated", "trust": "draft", "pushVia": "gh-stack", "issues": "linear",
            "lenses": ["base", "my-lens", "team-lens"], "verifySkill": "verify-team", "decisionsSection": True,
            # A rule's review App names one repo's reviewer, so a failed lookup doesn't wait for it.
            "review": None})

    def test_without_rules_unresolved_is_the_defaults(self):
        resolved = self.merge(Layer("user", self.dir, {"policy": {"defaults": LOOSE}}))
        self.assertEqual(resolved["policy"]["unresolved"], LOOSE)

    def test_the_digest_follows_named_files(self):
        rules = self.write("replies.md", "one")
        user = Layer("user", self.dir, {"replies": {"rules": "replies.md"}})
        before = self.merge(user)["digest"]
        rules.write_text("two")
        self.assertNotEqual(self.merge(user)["digest"], before)


class Resolve(Workspace):
    def test_raises_every_issue(self):
        user = self.write("addystack.jsonc", '{"replies": {"style": "reply-shap", "next": "on"}}')
        with self.assertRaises(config.Invalid) as caught:
            config.resolve(user)
        self.assertEqual([issue.path for issue in caught.exception.issues], ["replies.style", "replies.next"])

    def test_resolves_the_example(self):
        resolved = config.resolve(KIT / "examples" / "addystack.jsonc")
        self.assertEqual(resolved["layers"], ["defaults", "user"])
        self.assertEqual(resolved["kit"], str(KIT))
        self.assertEqual(resolved["policy"]["defaults"]["pushVia"], "git")
        self.assertEqual(resolved["hooks"]["enable"], [])


if __name__ == "__main__":
    unittest.main()
