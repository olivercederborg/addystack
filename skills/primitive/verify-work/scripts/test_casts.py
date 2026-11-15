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
        self.assertEqual([s for s, _, _ in casts.shapes("f(x as Record<string, Cell>, y)", "")],
                         ["x as Record<string, Cell>"])
        self.assertEqual([s for s, _, _ in casts.shapes("const g = h as (a: A) => B;", "")], ["h as (a: A) => B"])
        self.assertEqual([s for s, _, _ in casts.shapes("ok = ctx.user as Member || fallback", "")],
                         ["user as Member"])
        self.assertEqual([s for s, _, _ in casts.shapes("const c = {} as unknown as Client", "")],
                         ["… as unknown as Client"])

    def test_a_cast_on_a_literal_or_a_non_null_assertion_is_listed(self):
        groups, _, _ = self.scan({"src/fixtures.ts": (
            'const t = "INVALID_TYPE" as any\nconst r = `/x/${id}` as Route\n'
            "const k = 'DK' as CountryCode\nconst el = byId(id)! as HTMLElement\n")})
        self.assertEqual(sorted(g.shape for g in groups),
                         ["… as CountryCode", "… as HTMLElement", "… as Route", "… as any"])

    def test_a_string_in_a_type_keeps_its_text(self):
        groups, _, _ = self.scan({"src/jobs.ts": 'const h = raw as RunHandle<"export">\n'})
        self.assertEqual([g.shape for g in groups], ['raw as RunHandle<"export">'])

    def test_code_in_a_template_counts_and_a_regular_expression_does_not(self):
        groups, _, _ = self.scan({"src/token.ts": (
            "const origin = `http://h:${(server.address() as AddressInfo).port}`\n"
            "const tick = /`/\nconst value = raw as Value\nconst m = /foo as Bar/g\nconst half = a / b as number\n")})
        self.assertEqual(sorted(g.shape for g in groups), ["b as number", "raw as Value", "… as AddressInfo"])

    def test_a_cast_in_an_exported_function_or_after_an_import_on_its_line_is_listed(self):
        groups, _, _ = self.scan({"src/decode.ts": (
            "export function decode(raw: unknown) {\n  return raw as string\n}\n"
            'import { x } from "./x"; const row = data as Row\nexport { y as z }; const k = key as Key\n')})
        self.assertEqual(sorted(g.shape for g in groups), ["data as Row", "key as Key", "raw as string"])

    def test_a_cast_whose_type_is_on_the_next_line_is_listed_and_arithmetic_ends_a_type(self):
        groups, _, _ = self.scan({"src/value.ts": (
            "const value = raw as\n  Value; const other = x as Other\nconst sum = left as number + (right as number)\n")})
        self.assertEqual(sorted(g.shape for g in groups),
                         ["left as number", "raw as Value", "right as number", "x as Other"])

    def test_removing_one_operand_does_not_hide_a_new_cast_on_another(self):
        self.write({"src/customer.ts": "const row = customer.record as Row\n"})
        self.commit("customer")
        self.git("branch", "-f", "main")
        groups, _, moved = self.scan({"src/customer.ts": "const row = parse(customer.record)\n",
                                      "src/invoice.ts": "const row = invoice.record as Row\n"})
        self.assertEqual(([g.shape for g in groups], moved), (["record as Row"], 0))

    def test_a_path_with_a_space_or_a_quote_is_read(self):
        groups, _, _ = self.scan({"src/my file.ts": "const a = raw as Row\n", 'src/say "hi".ts': "const b = raw as Hi\n"})
        self.assertEqual(sorted(hit.path for g in groups for hit in g.new), ['src/my file.ts', 'src/say "hi".ts'])

    def test_a_twin_in_a_comment_does_not_count_and_one_after_a_tab_does(self):
        self.write({"src/notes.ts": "/*\nconst example = raw as Row\n*/\n", "src/old.ts": "const old = raw as\tRow\n"})
        self.commit("twins")
        self.git("branch", "-f", "main")
        groups, _, _ = self.scan({"src/new.ts": "const row = raw as Row\n"})
        self.assertEqual([(g.shape, g.same_folder) for g in groups], [("raw as Row", {"src/old.ts": 1})])

    def test_a_reason_explains_only_what_it_is_about(self):
        groups, reasoned, _ = self.scan({"src/unrelated.ts": (
            "// eslint-disable-next-line no-console -- diagnostics need logging\nconsole.log(raw as Value)\n"
            "// Mapping payload types\n// @ts-ignore\nsend(payload)\n"
            "const v = raw as Decoded // eslint-disable-line ts/consistent-type-assertions -- the decoder erases it\n")})
        self.assertEqual(sorted(g.shape for g in groups), ["@ts-ignore", "raw as Value"])
        self.assertEqual(sorted(hit.shape for hit in reasoned),
                         ["eslint-disable-line ts/consistent-type-assertions", "eslint-disable-next-line no-console",
                          "raw as Decoded"])

    def test_prose_that_names_a_directive_is_not_one(self):
        groups, reasoned, _ = self.scan({"src/note.ts": (
            "// Do not use eslint-disable-next-line no-console\nconst a = 1\n/**\n * Prefer @ts-expect-error here\n */\n"
            "/* @ts-expect-error */\nf(a)\n")})
        self.assertEqual(([g.shape for g in groups], reasoned), (["@ts-expect-error"], []))

    def test_a_users_diff_settings_do_not_hide_a_cast(self):
        self.git("config", "diff.noprefix", "true")
        self.git("config", "diff.interHunkContext", "3")
        self.write({"src/value.ts": "const a = first as Old\nconst keep = 1\nconst b = second as Old\n"})
        self.commit("old")
        self.git("branch", "-f", "main")
        groups, _, _ = self.scan({"src/value.ts": "const a = first as New\nconst keep = 1\nconst b = second as New\n"})
        self.assertEqual(sorted(g.shape for g in groups), ["first as New", "second as New"])

    def test_a_cast_on_a_different_expression_or_a_suppression_over_different_code_is_new(self):
        self.write({"src/old.ts": 'const a = customer.get() as Row\nconst b = "customer" as Key\n// @ts-ignore\noldCall("x")\n'})
        self.commit("old")
        self.git("branch", "-f", "main")
        self.git("rm", "-q", "src/lint.ts")  # its disable moves to kept.ts, over the same code
        groups, _, moved = self.scan({
            "src/old.ts": "oldCall(1)\n",
            "src/new.ts": 'const a = invoice.get() as Row\nconst b = "invoice" as Key\n// @ts-ignore\nnewCall("x")\n',
            "src/kept.ts": "const pad = 1\n" * 5 + "// eslint-disable-next-line no-console\nconsole.log(1)\n"})
        self.assertEqual((sorted(g.shape for g in groups), moved), (["@ts-ignore", "… as Key", "… as Row"], 1))

    def test_an_operand_is_the_whole_expression(self):
        self.assertEqual([k for _, k, _ in casts.shapes('f(a.b?.c(x)[0]! as T, "s" as U, (p + q) as V)', "",
                                                         'f(a.b?.c(x)[0]! as T, "s" as U, (p + q) as V)')],
                         ["a.b?.c(x)[0]! as T", '"s" as U', "(p + q) as V"])

    def test_a_directive_counts_in_its_own_comment_and_a_reason_only_from_what_covers_the_line(self):
        groups, reasoned, _ = self.scan({"src/value.ts": (
            "/* note */ // eslint-disable-next-line no-console\nconsole.log(1)\n"
            "//! eslint-disable-next-line no-alert\nalert(1)\n/** @ts-expect-error the SDK types it wrong */\nf(1)\n"
            "// Types\nconst a = raw as Row\n"
            "// eslint-disable-line ts/consistent-type-assertions -- old diagnostic\nconst b = raw as Col\n")})
        self.assertEqual(sorted(g.shape for g in groups), ["eslint-disable-next-line no-console", "raw as Col", "raw as Row"])
        self.assertEqual(sorted(hit.shape for hit in reasoned),
                         ["@ts-expect-error", "eslint-disable-line ts/consistent-type-assertions"])

    def test_a_regex_after_an_arrow_and_a_continued_string_are_not_code(self):
        groups, _, _ = self.scan({"src/value.ts": (
            "const m = (t: string) => /foo as Bar/.test(t)\nconst ok = (x: string) => /'/.test(x); const v = raw as Row\n"
            'const message = "save \\\ntext as Draft"\nconst out = `${raw as Col}`\n')})
        self.assertEqual(sorted(g.shape for g in groups), ["raw as Col", "raw as Row"])

    def test_a_type_ends_before_satisfies_and_a_type_changed_on_the_next_line_is_new(self):
        self.assertEqual([k for _, k, _ in casts.shapes("const v = raw as Row satisfies Row", "")], ["raw as Row"])
        self.assertEqual([k for _, k, _ in casts.shapes("const v = raw as Row instanceof Row", "")], ["raw as Row"])
        self.write({"src/value.ts": "const value = raw as\n  OldType\n"})
        self.commit("old")
        self.git("branch", "-f", "main")
        groups, _, _ = self.scan({"src/value.ts": "const value = raw as\n  NewType\n",
                                  "src/union.ts": "const f = undefined as\n  | undefined\n  | Fetch\n"})
        self.assertEqual(sorted(g.shape for g in groups), ["raw as NewType", "undefined as | undefined"])


if __name__ == "__main__":
    unittest.main()
