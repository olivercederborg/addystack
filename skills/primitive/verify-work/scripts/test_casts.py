"""casts.py in a real repo: it lists the casts and suppressions a branch adds with their
twins at the base, and leaves out moved, renamed, and kept ones, aliases, `as const`, and
text in strings and comments. Run: python3 -m unittest discover -s verify-work/scripts"""
import os, pathlib, subprocess, sys, tempfile, unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import casts  # noqa: E402

SHIM_USE = "store.add(sql as never, 1)\n"


class Casts(unittest.TestCase):
    def setUp(self):
        self.repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.repo)])
        self.git("init", "-q", "-b", "main")
        self.write({
            "checks/a.check.mts": SHIM_USE * 3,
            "checks/b.check.mts": SHIM_USE * 2,
            "src/store.ts": "export const read = (row: unknown) => row as Row\n",
            "src/lint.ts": "// eslint-disable-next-line no-console\nconsole.log(1)\n",
        })
        self.commit("base")
        self.git("switch", "-q", "-c", "feat")
        cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def write(self, files):
        for path, text in files.items():
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_text(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message)

    def scan(self, files):
        self.write(files)
        self.commit("change")
        return casts.scan("main", "feat")

    def test_a_new_file_copying_its_folder_lists_each_cast_with_its_twins(self):
        groups, reasoned, moved = self.scan({"checks/c.check.mts": SHIM_USE * 4})
        self.assertEqual([(g.shape, len(g.new), g.same_file, dict(g.same_folder), g.elsewhere) for g in groups],
                         [("sql as never", 4, 0, {"checks/a.check.mts": 3, "checks/b.check.mts": 2}, 0)])
        self.assertEqual((reasoned, moved), ([], 0))
        self.assertIn("9 copies, one cause", casts.report("main", "feat"))

    def test_a_cast_beside_its_twin_in_the_same_file_counts_it_there(self):
        groups, _, _ = self.scan({"checks/a.check.mts": SHIM_USE * 4})
        self.assertEqual([(len(g.new), g.same_file, sum(g.same_folder.values())) for g in groups], [(1, 3, 2)])

    def test_a_moved_or_renamed_cast_and_a_reason_added_to_a_disable_are_not_new(self):
        self.git("mv", "checks/a.check.mts", "checks/renamed.check.mts")
        (self.repo / "src/store.ts").unlink()
        groups, reasoned, moved = self.scan({
            "src/rows/read.ts": "// Reads one row.\nexport const read = (row: unknown) =>\n  row as Row\n",
            "src/lint.ts": "// eslint-disable-next-line no-console -- the CLI prints\nconsole.log(1)\n",
        })
        self.assertEqual((groups, reasoned, moved), ([], [], 2))

    def test_a_moved_cast_whose_trailing_comment_changed_is_not_new(self):
        self.write({"src/a.ts": "const v = raw as Value // set by the loader\n"})
        self.commit("comment")
        self.git("switch", "-q", "-c", "move")
        (self.repo / "src/a.ts").unlink()
        self.write({"src/b.ts": "export const v = raw as Value\n"})
        self.commit("move")
        self.assertEqual(casts.scan("feat", "move"), ([], [], 1))

    def test_aliases_const_strings_and_comments_are_not_casts(self):
        groups, reasoned, _ = self.scan({"src/other.ts": (
            'import { a as b } from "./a"\nimport * as path from "node:path"\nimport {\n  c as d,\n} from "./c"\n'
            'export { e as f }\nconst xs = [1] as const\nconst label = "save as draft"\n// read it as text\n'
            "/*\n  treat it as never\n*/\nconst t = `cast ${'x'} as never`\n")})
        self.assertEqual((groups, reasoned), ([], []))

    def test_a_reason_that_says_why_it_casts_moves_it_apart_and_a_heading_does_not(self):
        groups, reasoned, _ = self.scan({"src/sdk.ts": (
            "// The SDK brands the id type, approved in DEV-12\nconst id = raw as RunId\n"
            "// Refunds\nconst r = raw as Refund\n"
            "// eslint-disable-next-line ts/consistent-type-assertions -- the decoder erases it\n"
            "const v = raw as Value\n")})
        self.assertEqual([g.shape for g in groups], ["raw as Refund"])
        self.assertEqual(sorted(hit.shape for hit in reasoned),
                         ["eslint-disable-next-line ts/consistent-type-assertions", "raw as RunId", "raw as Value"])

    def test_a_type_keeps_its_generics_and_stops_where_the_expression_ends(self):
        self.assertEqual([s for s, _ in casts.shapes("f(x as Record<string, Cell>, y)", "")],
                         ["x as Record<string, Cell>"])
        self.assertEqual([s for s, _ in casts.shapes("const g = h as (a: A) => B;", "")], ["h as (a: A) => B"])
        self.assertEqual([s for s, _ in casts.shapes("ok = ctx.user as Member || fallback", "")],
                         ["user as Member"])
        self.assertEqual([s for s, _ in casts.shapes("const c = {} as unknown as Client", "")],
                         ["… as unknown as Client"])

    def test_a_cast_on_a_string_or_template_literal_is_listed(self):
        groups, _, _ = self.scan({"src/fixtures.ts": 'const t = "INVALID_TYPE" as any\nconst r = `/x/${id}` as Route\n'})
        self.assertEqual(sorted(g.shape for g in groups), ["… as Route", "… as any"])

    def test_a_string_in_a_type_keeps_its_text(self):
        groups, _, _ = self.scan({"src/jobs.ts": 'const h = raw as RunHandle<"export">\n'})
        self.assertEqual([g.shape for g in groups], ['raw as RunHandle<"export">'])


if __name__ == "__main__":
    unittest.main()
