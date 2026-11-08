"""Tests for sync-copies.py: it writes each copy in copies.txt from its source with a marker
naming the source, keeps the source's mode and shebang, and --check names a copy that is
hand-edited, stale, or missing, a symlink left in the kit, a copied script whose sibling it
needs isn't copied beside it, a skill with the format pointer that lacks its copies, and a
marked copy that no pair lists."""
import importlib.util, os, pathlib, shutil, subprocess, tempfile, unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "sync-copies.py"
POINTER = "<!-- toolkit-format:start -->\nread references/format.md\n<!-- toolkit-format:end -->\n"
LISTED = """\
# a comment, then a blank line

shared/notes.md      one/references/notes.md
shared/notes.md      two/references/notes.md
hooks/tool.py        one/scripts/tool.py
"""


class Kit:
    """A temporary kit with sources, a copies list, and the script, written once."""

    def __init__(self, listed=LISTED):
        self.root = pathlib.Path(tempfile.mkdtemp())
        (self.root / "scripts").mkdir()
        shutil.copy(SCRIPT, self.root / "scripts")
        self.write("scripts/copies.txt", listed)
        self.write("shared/notes.md", "# Notes\n")
        self.write("hooks/tool.py", "#!/usr/bin/env python3\n\"\"\"A tool.\"\"\"\nprint('ok')\n")
        os.chmod(self.root / "hooks/tool.py", 0o755)
        for skill in ("one", "two"):
            self.write(f"{skill}/SKILL.md", "---\nname: x\n---\n")

    def write(self, path, text):
        (self.root / path).parent.mkdir(parents=True, exist_ok=True)
        (self.root / path).write_text(text)

    def run(self, *args):
        return subprocess.run([str(self.root / "scripts" / SCRIPT.name), *args], capture_output=True, text=True)

    def text(self, path):
        return (self.root / path).read_text()


class SyncCopies(unittest.TestCase):
    def setUp(self):
        self.kit = Kit()
        self.addCleanup(shutil.rmtree, self.kit.root)

    def synced(self):
        result = self.kit.run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def check(self):
        return self.kit.run("--check")

    def test_writes_each_copy_with_a_marker_and_check_passes(self):
        self.synced()
        self.assertEqual(self.kit.text("one/references/notes.md"),
                         "<!-- Copy of shared/notes.md, written by scripts/sync-copies.py:"
                         " edit the source, then run the script. -->\n# Notes\n")
        self.assertEqual(self.kit.text("two/references/notes.md"), self.kit.text("one/references/notes.md"))
        result = self.check()
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)

    def test_a_script_keeps_its_shebang_first_and_its_mode(self):
        self.synced()
        copy = self.kit.root / "one/scripts/tool.py"
        self.assertEqual(copy.read_text().split("\n")[:2],
                         ["#!/usr/bin/env python3", "# Copy of hooks/tool.py, written by scripts/sync-copies.py:"
                          " edit the source, then run the script."])
        self.assertEqual(copy.stat().st_mode & 0o777, 0o755)
        self.assertEqual(subprocess.run([str(copy)], capture_output=True, text=True).stdout, "ok\n")

    def test_replaces_a_symlink_with_a_copy(self):
        (self.kit.root / "one/references").mkdir(parents=True)
        (self.kit.root / "one/references/notes.md").symlink_to("../../shared/notes.md")
        self.synced()
        self.assertFalse((self.kit.root / "one/references/notes.md").is_symlink())
        self.assertEqual(self.check().returncode, 0)

    def test_check_names_a_hand_edited_copy(self):
        self.synced()
        self.kit.write("two/references/notes.md", self.kit.text("two/references/notes.md") + "- hand edit\n")
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("two/references/notes.md (differs from shared/notes.md)", result.stdout)
        self.assertNotIn("one/references/notes.md", result.stdout)

    def test_check_names_each_copy_of_a_source_changed_without_a_sync(self):
        self.synced()
        self.kit.write("shared/notes.md", "# Notes, changed\n")
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("one/references/notes.md (differs", result.stdout)
        self.assertIn("two/references/notes.md (differs", result.stdout)

    def test_check_names_a_copy_whose_mode_differs(self):
        self.synced()
        os.chmod(self.kit.root / "one/scripts/tool.py", 0o644)
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("one/scripts/tool.py (mode differs", result.stdout)

    def test_check_names_a_missing_copy_and_writes_nothing(self):
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("one/references/notes.md (missing)", result.stdout)
        self.assertFalse((self.kit.root / "one/references/notes.md").exists())

    def test_check_names_a_symlink_left_in_the_kit(self):
        self.synced()
        (self.kit.root / "two/scripts").mkdir()
        (self.kit.root / "two/scripts/tool.py").symlink_to("../../hooks/tool.py")
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("two/scripts/tool.py (a symlink", result.stdout)

    def test_refuses_to_write_through_a_linked_folder(self):
        outside = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside)
        (outside / "notes.md").write_text("user data\n")
        (self.kit.root / "one/references").symlink_to(outside)
        result = self.kit.run()
        self.assertEqual(result.returncode, 1)
        self.assertIn("one/references (a symlink: make it a real folder)", result.stdout)
        self.assertEqual((outside / "notes.md").read_text(), "user data\n")
        self.assertFalse((self.kit.root / "two/references/notes.md").exists())

    def test_check_skips_a_tool_folder_even_when_it_is_a_link(self):
        self.synced()
        outside = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside)
        (self.kit.root / "node_modules").symlink_to(outside)
        self.assertEqual(self.check().returncode, 0)

    def test_check_names_a_copied_script_without_the_sibling_it_needs(self):
        self.kit.write("skills/primitive/addystack/hooks/transcripts.py", "import t3_child\n")
        self.kit.write("skills/primitive/addystack/hooks/t3_child.py", "\n")
        self.kit.write("scripts/copies.txt", LISTED + "skills/primitive/addystack/hooks/transcripts.py one/scripts/transcripts.py\n")
        result = self.kit.run()
        self.assertEqual(result.returncode, 1)
        self.assertIn("one/scripts/transcripts.py needs a copy of skills/primitive/addystack/hooks/t3_child.py at one/scripts/t3_child.py",
                      result.stdout)

    def test_check_names_a_pointer_skill_without_its_format_copies(self):
        self.kit.write("shared/format.md", "# Format\n")
        self.kit.write("shared/views.md", "# Views\n")
        self.kit.write("skills/primitive/one/SKILL.md", "---\nname: x\n---\n" + POINTER)
        result = self.kit.run()
        self.assertEqual(result.returncode, 1)
        self.assertIn("skills/primitive/one has the format pointer, so scripts/copies.txt needs shared/format.md "
                      "skills/primitive/one/references/format.md", result.stdout)
        self.assertIn("shared/views.md skills/primitive/one/references/views.md", result.stdout)

    def test_rejects_a_line_without_one_source_and_one_destination(self):
        self.kit.write("scripts/copies.txt", "shared/notes.md\n")
        result = self.kit.run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("copies.txt:1", result.stderr)

    def test_the_workshops_list_counts_too(self):
        self.kit.write("maintainer/copies.txt", "hooks/tool.py two/scripts/tool.py\n")
        result = self.kit.run()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue((self.kit.root / "two/scripts/tool.py").is_file())
        self.kit.write("maintainer/copies.txt", "hooks/tool.py one/references/notes.md\n")
        result = self.kit.run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("maintainer/copies.txt:1: one/references/notes.md is listed twice", result.stderr)

    def test_check_names_a_marked_copy_no_pair_lists_and_writing_keeps_it(self):
        self.synced()
        self.kit.write("scripts/copies.txt", "shared/notes.md one/references/notes.md\n")
        result = self.check()
        self.assertEqual(result.returncode, 1)
        for copy in ("two/references/notes.md", "one/scripts/tool.py"):
            self.assertIn(f"{copy} (a copy no pair lists: delete it, or list it in scripts/copies.txt)",
                          result.stdout)
        self.assertNotIn("one/references/notes.md", result.stdout)
        result = self.kit.run()
        self.assertEqual(result.returncode, 1)
        self.assertIn("two/references/notes.md (a copy no pair lists", result.stdout)
        self.assertTrue((self.kit.root / "two/references/notes.md").is_file())
        self.assertTrue((self.kit.root / "one/scripts/tool.py").is_file())

    def test_a_file_quoting_the_marker_below_its_top_is_not_a_copy(self):
        self.synced()
        marker = "Copy of shared/notes.md, written by scripts/sync-copies.py: edit the source, then run the script."
        self.kit.write("docs/about.md", f"# About\n\n<!-- {marker} -->\n")
        self.kit.write("docs/about.py", f"#!/usr/bin/env python3\n\"\"\"About.\"\"\"\n# {marker}\n")
        self.kit.write("node_modules/pkg/notes.md", f"<!-- {marker} -->\n")
        result = self.check()
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_a_listed_destination_spelled_with_dot_slash_is_not_an_orphan(self):
        self.kit.write("scripts/copies.txt", LISTED.replace(" one/references/notes.md", " ./one/references/notes.md"))
        self.assertEqual(self.kit.run().returncode, 0)
        result = self.check()
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_check_names_an_unlisted_copy_whose_suffix_differs_from_its_source(self):
        self.kit.write("scripts/copies.txt", LISTED + "shared/notes.md one/references/notes.txt\n")
        self.assertEqual(self.kit.run().returncode, 0)
        self.kit.write("scripts/copies.txt", LISTED)
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("one/references/notes.txt (a copy no pair lists", result.stdout)

    def test_rejects_a_destination_listed_twice(self):
        self.kit.write("scripts/copies.txt", LISTED + "hooks/tool.py one/references/notes.md\n")
        result = self.kit.run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("one/references/notes.md is listed twice", result.stderr)


KIT = SCRIPT.parent.parent


def copied_scripts():
    """The copies.txt entries, the workshop's too, whose destination is a skill script, as
    (source, copy)."""
    pairs = []
    lists = [KIT / "scripts/copies.txt", KIT / "maintainer/copies.txt"]
    for line in (line for path in lists if path.is_file() for line in path.read_text().splitlines()):
        words = line.split("#", 1)[0].split()
        if len(words) == 2 and "/scripts/" in words[1]:
            pairs.append((KIT / words[0], KIT / words[1]))
    return pairs


class RealTree(unittest.TestCase):
    def test_every_marked_copy_in_this_checkout_is_listed(self):
        # Imported, not run with --check: Dagger's suite holds only part of the tree, so its
        # listed copies can be missing, but any marked copy it holds must still be listed.
        spec = importlib.util.spec_from_file_location("sync_copies", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.orphans(KIT, {destination for _, destination in module.listed(KIT)}), [])


class CopiedScriptsRun(unittest.TestCase):
    """Each copied script works from its copy, as a skill installed alone holds it: shell
    scripts print the same usage as their source, which some read from their own header,
    and Python modules import with only their own folder on the path."""

    def setUp(self):
        self.pairs = copied_scripts()
        if not self.pairs:
            self.skipTest("this checkout lists no copied scripts")
        self.cwd = tempfile.mkdtemp()  # outside any repo, so no command reaches one
        self.addCleanup(shutil.rmtree, self.cwd)

    def usage(self, path):
        result = subprocess.run(["bash", str(path)], capture_output=True, text=True, cwd=self.cwd)
        return result.returncode, (result.stdout + result.stderr).replace(str(path), "<script>")

    def test_shell_copies_print_their_sources_usage(self):
        for source, copy in self.pairs:
            if copy.suffix == ".sh":
                with self.subTest(copy=str(copy.relative_to(KIT))):
                    self.assertEqual(self.usage(copy), self.usage(source))

    def test_python_copies_import_from_their_own_folder(self):
        # verdicts.py imports evidence.py only when it records or classifies, so import both.
        lazy = {"verdicts": ["evidence"]}
        for _, copy in self.pairs:
            if copy.suffix == ".py":
                with self.subTest(copy=str(copy.relative_to(KIT))):
                    names = ", ".join([copy.stem, *lazy.get(copy.stem, [])])
                    program = (f"import sys; sys.path[:0] = [{str(copy.parent)!r}]; import {names}; "
                               f"print('\\n'.join(m.__file__ for m in list(sys.modules.values())"
                               f" if (getattr(m, '__file__', None) or '').startswith({str(KIT)!r})))")
                    result = subprocess.run(["python3", "-I", "-B", "-c", program],
                                            capture_output=True, text=True, cwd=self.cwd)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    for loaded in result.stdout.split():
                        self.assertEqual(pathlib.Path(loaded).parent, copy.parent)


if __name__ == "__main__":
    unittest.main()
