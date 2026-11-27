"""Tests for schema/v1.json: its policy fields are resolved.Policy's, and every key it
declares carries the `default` and `markdownDescription` the editor shows."""
from __future__ import annotations

import dataclasses, json, pathlib, sys, unittest

KIT = pathlib.Path(__file__).resolve().parent.parent / "skills" / "primitive" / "addystack"
sys.path.insert(0, str(KIT / "hooks"))
import resolved  # noqa: E402

SCHEMA = json.loads((KIT / "schema" / "v1.json").read_text())


def deref(node):
    """The node a local `#/definitions/…` $ref points at, or the node itself."""
    while "$ref" in node:
        target = SCHEMA
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        node = target
    return node


def keys(node, path=""):
    """Each (dotted path, schema) the schema declares under `properties`, following $refs."""
    node = deref(node)
    for name, child in node.get("properties", {}).items():
        yield f"{path}{name}", deref(child)
        yield from keys(child, f"{path}{name}.")
    if "items" in node:
        yield from keys(node["items"], f"{path}[].")


class PolicyFields(unittest.TestCase):
    def test_defaults_declare_each_policy_field(self):
        fields = {f.name for f in dataclasses.fields(resolved.Policy)} - {"matched"}
        declared = set(SCHEMA["properties"]["policy"]["properties"]["defaults"]["properties"])
        self.assertEqual(declared, fields)

    def test_a_rule_declares_its_match_and_each_policy_field(self):
        fields = {f.name for f in dataclasses.fields(resolved.Policy)} - {"matched"}
        self.assertEqual(set(SCHEMA["definitions"]["rule"]["properties"]), fields | {"match"})

    def test_a_repo_file_declares_the_fields_it_may_tighten_and_its_review_app(self):
        properties = SCHEMA["definitions"]["repoPolicy"]["properties"]
        self.assertEqual(set(properties), {"$schema", "planning", "trust", "pushVia", "review"})
        for field in ("planning", "trust", "pushVia", "review"):
            self.assertEqual(properties[field], {"$ref": f"#/definitions/{field}"})


class Annotations(unittest.TestCase):
    def test_every_key_has_a_default_and_a_description(self):
        found = list(keys(SCHEMA))
        self.assertGreater(len(found), 30)
        for path, node in found:
            with self.subTest(key=path):
                self.assertIn("default", node)
                self.assertIn("markdownDescription", node)

    def test_every_object_forbids_unknown_keys(self):
        for path, node in [("", SCHEMA), *keys(SCHEMA)]:
            if "properties" in node:
                with self.subTest(key=path):
                    self.assertIs(node.get("additionalProperties"), False)


if __name__ == "__main__":
    unittest.main()
