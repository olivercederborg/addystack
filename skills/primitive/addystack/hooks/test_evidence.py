"""Tests for evidence.py: which change types a diff needs evidence for, and which refs
back them, on real git repos."""
import json, os, pathlib, shutil, struct, subprocess, sys, tempfile, unittest, zlib

import evidence, verdicts

HOOKS = pathlib.Path(__file__).resolve().parent
VERIFIER = json.dumps({"session_id": "s", "agent_id": "a1", "agent_type": "work-verifier"})
chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
# A real 1x1 grey PNG and GIF, and the first bytes of each other capture type.
PNG = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(b"\x00\x80")) + chunk(b"IEND", b""))
GIF = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x80\x80\x80\x00\x00\x00"
       b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")
CAPTURES = {"shot.png": PNG, "shot.gif": GIF, "shot.jpg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00",
            "shot.webp": b"RIFF\x24\x00\x00\x00WEBPVP8 ", "run.mp4": b"\x00\x00\x00\x18ftypisom",
            "run.mov": b"\x00\x00\x00\x14ftypqt  ", "run.webm": b"\x1a\x45\xdf\xa3\x9f"}
APP = "export const App = () => <main />\n"


class Repo(unittest.TestCase):
    """A repo with a base commit; `change` commits files on top and returns the head."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.dir)
        self.repo = self.dir / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        self.base = self.change({"README.md": "# app\n", "src/api.ts": "export function list() {}\n"}, "Base")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def change(self, files, message="Change"):
        for path, text in files.items():
            target = self.repo / path
            if text is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)
        return self.git("rev-parse", "HEAD").strip()

    def kinds(self, head):
        """The kinds `base...head` needs other than idiom, which every code file brings
        and `Idiom` tests."""
        return {kind: reasons for kind, reasons in evidence.classify(self.repo, self.base, head).items()
                if kind != "idiom"}

    def classify(self, files, message="Change"):
        return self.kinds(self.change(files, message))


class Classify(Repo):
    def test_each_kind_has_a_diff_that_triggers_it(self):
        cases = {
            "ui": ({"src/App.tsx": APP, "Sources/Home.swift": "import SwiftUI\n"}, "Change",
                   ["Sources/Home.swift: imports SwiftUI", "src/App.tsx: UI file"]),
            "contract": ({"api/openapi.yaml": "x\n", "src/api.ts": "export function list(page: number) {}\n"},
                         "Change", ["api/openapi.yaml: API schema",
                                    "src/api.ts: changes or removes `export function list() {}`"]),
            "mutants": ({"src/billing/chargeCard.ts": "x\n", "db/001_users.sql": "x\n"}, "Change",
                        ["db/001_users.sql: SQL", "src/billing/chargeCard.ts: billing path"]),
            "parity": ({"src/util.ts": "x\n"}, "Refactor errors\n\nNo behavior change.",
                       ["commit SHA 'Refactor errors': says \"No behavior change\""]),
            "deploy": ({"fly.toml": "x\n", ".github/workflows/ci.yml": "steps: [flyctl deploy]\n"}, "Change",
                       [".github/workflows/ci.yml: deploy workflow", "fly.toml: deploy config"]),
            "toolchain": ({"apps/web/next.config.js": "x\n", "vite.config.ts": "x\n", ".babelrc": "x\n"}, "Change",
                          [".babelrc: dev toolchain config", "apps/web/next.config.js: dev toolchain config",
                           "vite.config.ts: dev toolchain config"]),
        }
        for kind, (files, message, reasons) in cases.items():
            with self.subTest(kind=kind):
                self.setUp()
                head = self.change(files, message)
                sha = self.git("rev-parse", "--short=7", head).strip()
                self.assertEqual(self.kinds(head),
                                 {kind: [reason.replace("SHA", sha) for reason in reasons]})

    def test_plain_diffs_and_test_files_need_none(self):
        self.assertEqual(self.classify({
            "README.md": "# app\n\nMore.\n",
            "src/api.ts": "export function list() {}\nexport function count() {}\n",  # a new export only
            "src/App.test.tsx": "x\n", "src/__tests__/auth.ts": "x\n", "tests/payments.py": "x\n",
            "AppTests/LoginTests.swift": "import SwiftUI\n", "src/tokens.css.ts": "x\n",
            "Sources/Model.swift": "import Foundation\n", ".github/workflows/ci.yml": "steps: [test]\n",
            "scripts/env.sh": "export A=1\n",
        }, "Add count and fix the lock release"), {})

    def test_rules_tuned_on_real_branches_stay_quiet(self):
        """Each case here made noise on 40 merged workout-tracker PRs before tuning."""
        self.base = self.change({"src/db/version.ts": "export const databaseVersion = 19;\n"}, "Add the version")
        self.assertEqual(self.classify({
            "src/db/version.ts": "export const databaseVersion = 20;\n",  # a literal value, same declaration
            "src/history.jest.tsx": "x\n", "src/features/session/screen.ts": "x\n",  # a training session
            "docs/review-assets/pricing.png": "x\n", "docs/pricing.md": "x\n",
        }, "feat(notes): add a note\n\nShip it once review passes."), {})
        self.change({"src/b.ts": "x\n"}, "test(mobile): release the write gate")
        self.change({"src/a.ts": "x\n"}, "refactor(ui): drop a guard")  # one refactor inside a feature
        self.change({"src/c.ts": "x\n"}, "Add the parity test")  # names parity, doesn't claim it
        self.change({"src/d.ts": "x\n"}, "Add eval fixtures by change type: ui, parity, contract")
        self.assertEqual(self.kinds("HEAD"), {})

    def test_a_named_parity_claim_needs_parity(self):
        head = self.change({"src/a.ts": "x\n"}, "Split the mapper\n\nKeeps behavior parity with the old one.")
        sha = self.git("rev-parse", "--short=7", head).strip()
        self.assertEqual(self.kinds(head),
                         {"parity": [f"commit {sha} 'Split the mapper': says \"behavior parity\""]})

    def test_a_quoted_claim_is_a_mention(self):
        self.change({"src/a.ts": "x\n"}, 'Stop reading "no behavior change" as a claim; keep "behavior parity"')
        self.change({"src/b.ts": "x\n"}, "Match `logic parity` and 'deploy to prod' in messages, don't drop them")
        self.assertEqual(self.kinds("HEAD"), {})
        head = self.change({"src/c.ts": "x\n"}, "Split the mapper\n\nNo behavior change; it's the same output.")
        sha = self.git("rev-parse", "--short=7", head).strip()
        self.assertEqual(self.kinds(head),
                         {"parity": [f"commit {sha} 'Split the mapper': says \"No behavior change\""]})

    def test_a_branch_of_only_refactors_needs_parity(self):
        first = self.change({"src/a.ts": "x\n"}, "refactor: name the error")
        head = self.change({"src/b.ts": "x\n"}, "Migrate b to Effect v4")
        sha = lambda rev: self.git("rev-parse", "--short=7", rev).strip()
        self.assertEqual(self.kinds(head), {"parity": [
            f"commit {sha(head)} 'Migrate b to Effect v4': says \"Migrate\"",
            f"commit {sha(first)} 'refactor: name the error': says \"refactor\""]})

    def test_deleting_a_file_still_counts(self):
        self.assertEqual(self.classify({"src/api.ts": None}), {"contract": ["src/api.ts: changes or removes `export function list() {}`"]})

    def test_a_tsx_file_without_jsx_is_not_ui(self):
        self.assertEqual(self.classify({"src/bot.tsx": "const skills = new Set<Skill>();\n",
                                        "src/escape.tsx": 'export const esc = (v: string) => v.replace(/>/g, "&gt;")\n'}), {})
        self.assertEqual(self.classify({"src/Upload.tsx": 'export const U = () => <input accept="image/*" />\n/* types */\n'}),
                         {"ui": ["src/Upload.tsx: UI file"]})
        for jsx in ("<>{x}</>", "<div>x</div>", "<Icon />", "<_Card>x</_Card>", "<$Card>x</$Card>",
                    "<Icon onClick={() => go()} />", "<Icon\n  size={2}\n/>"):
            with self.subTest(jsx=jsx):
                self.setUp()
                self.assertEqual(self.classify({"src/View.jsx": f"export const View = () => {jsx}\n"}),
                                 {"ui": ["src/View.jsx: UI file"]})

    def test_a_deleted_component_is_read_where_the_diff_starts(self):
        self.base = self.change({"src/View.tsx": "export const View = () => <div>Before</div>\n"}, "Add the view")
        self.git("switch", "-qc", "work")
        head = self.change({"src/View.tsx": None}, "Drop the view")
        self.git("switch", "-q", "main")
        tip = self.change({"src/View.tsx": "export const view = 1\n"}, "Main moves on")
        self.assertEqual(evidence.classify(self.repo, tip, head)["ui"], ["src/View.tsx: UI file"])

    def test_a_symlinked_component_is_read_through_its_links(self):
        self.base = self.change({"src/Target.tsx": "export const T = () => <div>After</div>\n"}, "Add the target")
        (self.repo / "src/Middle.tsx").symlink_to("Target.tsx")
        (self.repo / "src/View.tsx").symlink_to("Middle.tsx")
        self.assertEqual(self.kinds(self.change({}, "Link the view"))["ui"],
                         ["src/Middle.tsx: UI file", "src/View.tsx: UI file"])

    def test_a_component_linked_from_outside_the_tree_or_with_a_newline_counts(self):
        outside = self.dir / "Button.tsx"
        outside.write_text("export const Button = () => <button>Save</button>\n")
        (self.repo / "src/Button.tsx").symlink_to(outside)
        self.assertEqual(self.classify({"src/view\ncard.tsx": "export const Card = () => <div>Hi</div>\n"})["ui"],
                         ["src/Button.tsx: UI file", "src/view\ncard.tsx: UI file"])

    def test_deleting_a_risky_file_needs_no_mutants(self):
        self.base = self.change({"src/auth/check.ts": "function check() {}\n"}, "Add the check")
        self.base = self.change({"db/auth/old.sql": "SELECT 1;\n", "prisma/schema.prisma": "model U { id Int @id }\n"})
        self.assertEqual(self.classify({"src/auth/check.ts": None, "db/auth/old.sql": None, "prisma/schema.prisma": None}), {})
        self.assertEqual(self.classify({"src/auth/check.ts": "function check() { return 1 }\n"}),
                         {"mutants": ["src/auth/check.ts: auth path"]})

    def test_a_member_inside_a_multi_line_exported_type_is_contract(self):
        self.base = self.change({"src/user.ts": "export interface User {\n  id: string\n  displayName: string\n}\n\n"
                                                "export type Status =\n  | 'active'\n  | 'gone'\n\n"
                                                "export function greet(user: User) {\n  const name = user.displayName\n"
                                                "  return name\n}\n\nfunction helper() {\n  return 1\n}\n"}, "Add users")
        self.assertEqual(self.classify({"src/user.ts": "export interface User {\n  id: string\n  fullName: string\n}\n\n"
                                                       "export type Status =\n  | 'active'\n  | 'gone'\n\n"
                                                       "export function greet(user: User) {\n  const name = user.fullName\n"
                                                       "  return name\n}\n"}),
                         {"contract": ["src/user.ts: changes or removes `export interface User { … displayName: string`"]})
        self.base = self.git("rev-parse", "HEAD").strip()
        self.assertEqual(self.classify({"src/user.ts": "export interface User {\n  id: string\n  fullName: string\n}\n\n"
                                                       "export type Status =\n  | 'active'\n\n"
                                                       "export function greet(user: User) {\n  return user.fullName\n}\n"}),
                         {"contract": ["src/user.ts: changes or removes `export type Status = … | 'gone'`"]})

    def test_body_edits_and_added_members_are_not_contract(self):
        self.base = self.change({"src/user.ts": "export interface User {\n  id: string\n}\n\n"
                                                "export function greet(user: User) {\n  const name = user.id\n"
                                                "  return name;\n}\n\nfunction helper() {\n  return 1\n}\n"}, "Add users")
        self.assertEqual(self.classify({"src/user.ts": "export interface User {\n  id: string;\n  email: string\n}\n\n"
                                                       "export function greet(user: User) {\n  const name = user.email\n"
                                                       "  return `hi ${name}`\n}\n"}), {})

    def test_moving_a_function_below_an_exported_type_is_not_contract(self):
        self.base = self.change({"src/id.ts": "export type Id = string\n\nexport function greet(id: Id) {\n"
                                              "  const name = id\n  return name\n}\n\n"
                                              "export function bye(id: Id) {\n  return id\n}\n"}, "Add ids")
        self.assertEqual(self.classify({"src/id.ts": "export type Id = string\n\nexport function bye(id: Id) {\n"
                                                     "  return id\n}\n\nexport function greet(id: Id) {\n"
                                                     "  const name = id.trim()\n  return name\n}\n"}), {})

    def test_a_member_moved_to_another_exported_type_is_contract(self):
        self.base = self.change({"src/user.ts": "export interface User {\n  id: string\n  displayName: string\n}\n\n"
                                                "export interface Audit {\n  at: string\n}\n"}, "Add users")
        self.assertEqual(self.classify({"src/user.ts": "export interface User {\n  id: string\n}\n\n"
                                                       "export interface Audit {\n  at: string\n  displayName: string\n}\n"}),
                         {"contract": ["src/user.ts: changes or removes `export interface User { … displayName: string`"]})

    def test_deploy_from_a_commit_message(self):
        head = self.change({"src/a.ts": "x\n"}, "Ship to production")
        sha = self.git("rev-parse", "--short=7", head).strip()
        self.assertEqual(self.kinds(head),
                         {"deploy": [f"commit {sha} 'Ship to production': says \"Ship to production\""]})

    def test_a_subject_that_ships_a_change_claims_no_deploy(self):
        # addystack f3cd47e and 267f28e: "Ship" as the subject's verb, with no environment,
        # made verify-work ask for deploy evidence that couldn't exist.
        self.change({"src/a.ts": "x\n"}, "Ship the confirmed cause's fix in slim-scope's shape, not only the lines "
                                         "it needs")
        self.change({"src/b.ts": "x\n"}, "Ship the turn block spec and cite it when the user keeps no reply rules file")
        self.assertEqual(self.kinds("HEAD"), {})

    def test_bad_revisions_raise(self):
        with self.assertRaisesRegex(evidence.EvidenceError, "git diff"):
            evidence.classify(self.repo, self.base, "nope")


class Check(Repo):
    def file(self, name, text="x\n"):
        path = self.dir / name
        path.write_bytes(text) if isinstance(text, bytes) else path.write_text(text)
        return path

    def test_valid_refs_are_stored_as_absolute_paths(self):
        for name, data in CAPTURES.items():
            with self.subTest(name=name):
                self.file(name, data)
                self.assertEqual(evidence.check("ui", [name], self.dir), ([str(self.dir / name)], []))
        self.assertEqual(evidence.check("deploy", ["https://app.example.com/version"], self.dir),
                         (["https://app.example.com/version"], []))

    def test_each_kind_refuses_a_ref_that_proves_nothing(self):
        self.file("notes.txt")
        self.file("fake.png", "a screenshot, honest\n")
        self.file("swapped.webm", PNG)
        self.file("empty.log", "")
        self.file("short.log", "killed: a\nsurvived: b\n")
        self.file("head-only.log", "head: peak_rss_mb=5815 procs=14 startup_s=29\n")
        cases = [("ui", "notes.txt", "not an image or video"), ("ui", "missing.png", "no such file"),
                 ("ui", "fake.png", "bytes aren't a png file"), ("ui", "swapped.webm", "bytes aren't a webm file"),
                 ("parity", "empty.log", "empty"), ("contract", "missing.diff", "no such file"),
                 ("mutants", "short.log", "fewer than 3"),
                 ("toolchain", "head-only.log", "needs a `base:` and a `head:` line"),
                 ("deploy", "ftp://x", "no such file"),
                 ("deploy", "not-run: ", "names no reason"), ("tests", "x", "isn't one of")]
        for kind, ref, problem in cases:
            with self.subTest(kind=kind, ref=ref):
                _, problems = evidence.check(kind, [ref], self.dir)
                self.assertEqual(len(problems), 1)
                self.assertIn(problem, problems[0])

    def test_what_backs_done(self):
        log = self.file("mutants.log", "killed: flip a\nkilled: drop b\nsurvived: drop alias clause\n")
        self.assertEqual(evidence.done_gap("mutants", [str(log)]), "1 survived (drop alias clause)")
        self.assertEqual(evidence.done_gap("ui", ["not-run:no simulator"]), "not run here (no simulator)")
        self.assertEqual(evidence.done_gap("ui", []), "no evidence")
        self.assertIsNone(evidence.done_gap("ui", ["not-run:no simulator", "/tmp/a.png"]))

    def test_a_dev_cost_jump_refuses_done_until_accepted(self):
        """The base and head runs from the Sentry loader regression that motivated the kind."""
        runs = ("base: peak_rss_mb=4808 procs=5 startup_s=22\nbase: peak_rss_mb=4951 procs=5 startup_s=21\n"
                "head: peak_rss_mb=5815 procs=14 startup_s=29\nhead: peak_rss_mb=5916 procs=10 startup_s=27\n")
        grew = self.file("grew.log", runs)
        self.assertEqual(evidence.check("toolchain", [str(grew)], self.dir), ([str(grew)], []))
        self.assertEqual(evidence.done_gap("toolchain", [str(grew)]),
                         "dev cost grew: peak RSS 4880 → 5866 MB (+20%), processes 5 → 12 (+140%)")
        accepted = self.file("accepted.log", runs + "accepted: the PR adds a second dev server on purpose\n")
        self.assertIsNone(evidence.done_gap("toolchain", [str(accepted)]))
        steady = self.file("steady.log", "base: peak_rss_mb=4808 procs=5\nhead: peak_rss_mb=4900 procs=5\n")
        self.assertIsNone(evidence.done_gap("toolchain", [str(steady)]))


class Recording(Repo):
    """verdicts.record refuses a Done without the evidence its change type needs."""

    def media(self, name, text="x\n"):
        path = self.dir / name
        path.write_bytes(text) if isinstance(text, bytes) else path.write_text(text)
        return str(path)

    def record(self, head, verdict="done", **kwargs):
        return verdicts.record(self.repo, verdicts.ReviewTarget(self.base, head), VERIFIER, verdict, **kwargs)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(HOOKS / "verdicts.py"), *args], cwd=self.repo, capture_output=True,
                              text=True, env={**os.environ, verdicts.HOOK_CONTEXT: VERIFIER})

    def test_done_needs_each_kind_its_change_needs(self):
        kills = "killed: flip a\nkilled: drop b\nkilled: drop c\n"
        cases = {"ui": ({"src/App.tsx": APP}, "Change", "shot.png", PNG),
                 "parity": ({"src/util.ts": "x\n"}, "Migrate errors to v4", "parity.log", "same outcomes\n"),
                 "contract": ({"src/api.ts": None}, "Change", "exports.diff", "-list\n"),
                 "mutants": ({"src/auth/login.ts": "x\n"}, "Change", "mutants.log", kills),
                 "deploy": ({"Dockerfile": "FROM x\n"}, "Change", "https://app.example.com/version", None)}
        for kind, (files, message, ref, text) in cases.items():
            with self.subTest(kind=kind):
                self.setUp()
                head = self.change(files, message)
                idiom = {"idiom": [self.media("idiom.txt", "none: a fixture\n")]}
                with self.assertRaisesRegex(verdicts.VerdictError, rf"^Done needs evidence: {kind} \(.+\)"
                                                                   rf" → --evidence {kind}=<\w+>$"):
                    self.record(head, evidence=idiom)
                ref = ref if text is None else self.media(ref, text)
                receipt = self.record(head, evidence={kind: [ref], **idiom})
                self.assertEqual((receipt.verdict, receipt.evidence, [k for k in receipt.required if k != "idiom"]),
                                 ("done", {kind: [ref], **idiom}, [kind]))
                found = verdicts.find_done(self.repo, verdicts.diff(self.repo, self.base, head))
                self.assertEqual(found, receipt)

    def test_a_check_not_run_here_backs_not_verified_only(self):
        head = self.change({"src/App.tsx": APP})
        with self.assertRaisesRegex(verdicts.VerdictError, r"ui \(src/App.tsx: UI file\): not run here \(no simulator\)"):
            self.record(head, evidence={"ui": ["not-run:no simulator"]})
        receipt = self.record(head, "not-verified", evidence={"ui": ["not-run:no simulator"]}, findings=["no simulator"])
        self.assertEqual(receipt.evidence, {"ui": ["not-run:no simulator"]})

    def test_a_surviving_mutant_refuses_done(self):
        head = self.change({"src/payments.ts": "x\n"})
        log = self.media("mutants.log", "killed: flip a\nkilled: drop b\nsurvived: drop alias clause\n")
        with self.assertRaisesRegex(verdicts.VerdictError, r"mutants \(src/payments.ts: payment path\): "
                                                           r"1 survived \(drop alias clause\)"):
            self.record(head, evidence={"mutants": [log]})
        self.record(head, "not-done", evidence={"mutants": [log]}, findings=["drop alias clause survives"])

    def test_a_surviving_mutant_refuses_done_on_a_path_that_does_not_need_mutants(self):
        head = self.change({"src/format.ts": "x\n"})
        idiom = [self.media("idiom.txt", "none: a fixture\n")]
        log = self.media("mutants.log", "killed: flip a\nkilled: drop b\nsurvived: drop the pad\n")
        with self.assertRaisesRegex(verdicts.VerdictError, r"^Done needs evidence: mutants \(supplied\): "
                                                           r"1 survived \(drop the pad\)"):
            self.record(head, evidence={"mutants": [log], "idiom": idiom})
        kills = self.media("kills.log", "killed: flip a\nkilled: drop b\nkilled: drop the pad\n")
        self.assertEqual(list(self.record(head, evidence={"mutants": [kills], "idiom": idiom}).required), ["idiom"])

    def saved(self, head, name, text):
        """A file in head's evidence folder, where verify-work's evidence.md says to save it."""
        common = self.git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        path = pathlib.Path(common, "verify-work", "evidence", head, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return str(path)

    def test_a_mutant_log_left_out_of_done_refuses_it(self):
        """verify-108-1, Nov 8, 2026: three survivors in mutants.log, and a Done that passed only idiom."""
        head = self.change({"src/format.ts": "x\n"})
        idiom = [self.media("idiom.txt", "none: a fixture\n")]
        log = self.saved(head, "mutants.log", "killed: stale-revision-key by ReviewsTests\n"
                                              "survived: tick-follows-not-fresh (107 tests passed)\n"
                                              "survived: no-server-backstop (38 tests passed)\n")
        with self.assertRaisesRegex(verdicts.VerdictError, r"^Done needs evidence: mutants \(run here\): mutants\.log in "
                                                           r"this head's evidence folder isn't passed.*; it shows 2 survived "
                                                           r"\(tick-follows-not-fresh .*; no-server-backstop .*\), so record "
                                                           r"Not done naming each → --evidence mutants=<log>$"):
            self.record(head, evidence={"idiom": idiom})
        with self.assertRaisesRegex(verdicts.VerdictError, r"mutants \(supplied\): 2 survived"):
            self.record(head, evidence={"idiom": idiom, "mutants": [log]})
        self.record(head, "not-done", evidence={"idiom": idiom}, findings=["tick-follows-not-fresh survives"])

    def test_a_left_out_log_with_every_mutant_killed_backs_done_once_passed(self):
        head = self.change({"src/format.ts": "x\n"})
        idiom = [self.media("idiom.txt", "none: a fixture\n")]
        log = self.saved(head[:10], "nested/Mutants-delta.txt", "killed: a\nkilled: b\nkilled: c\n")
        with self.assertRaisesRegex(verdicts.VerdictError, r"Mutants-delta\.txt in this head's evidence folder"):
            self.record(head, evidence={"idiom": idiom})
        self.assertEqual(self.record(head, evidence={"idiom": idiom, "mutants": [log]}).verdict, "done")

    def test_only_a_mutant_log_with_results_for_this_head_counts(self):
        head = self.change({"src/format.ts": "x\n"})
        idiom = [self.media("idiom.txt", "none: a fixture\n")]
        other = self.change({"src/other.ts": "x\n"})
        self.git("checkout", "-q", head)
        self.saved(other, "mutants.log", "survived: on another head\n")  # another head's folder
        self.saved(head[:6], "mutants.log", "survived: too short a prefix to name the head\n")
        self.saved(head, "mutants-run.log", "Building for debugging...\nmutant 1 of 3\n")  # no results in it
        self.saved(head, "tests.log", "survived: a test log that quotes a result\n")  # not named for mutants
        self.saved(head, "mutants.log", "killed: one probe\nkilled: and another\n")  # hides nothing, and too few to pass
        self.assertEqual(self.record(head, evidence={"idiom": idiom}).verdict, "done")
        self.saved(head, "mutants-2.log", "killed:\nsurvived: one is enough\n")  # `killed:` alone doesn't take the next line
        with self.assertRaisesRegex(verdicts.VerdictError, r"mutants-2\.log in this head's evidence folder.*1 survived \(one is enough\)"):
            self.record(head, evidence={"idiom": idiom})
        # A Not done reads no folder, so it records with neither log passed.
        self.assertEqual(self.record(head, "not-done", evidence={"idiom": idiom}, findings=["one survives"]).verdict,
                         "not-done")

    @unittest.skipIf(os.geteuid() == 0, "root reads any file")
    def test_a_mutant_log_done_cannot_read_refuses_done_but_not_a_not_done(self):
        head = self.change({"src/format.ts": "x\n"})
        idiom = [self.media("idiom.txt", "none: a fixture\n")]
        hidden = pathlib.Path(self.saved(head, "nested/mutants.log", "survived: behind a locked folder\n")).parent
        evidence_root = hidden.parent.parent
        # 0 hides names too; 0o644 lists them but can't search, and is_dir() reads that as absent.
        for locked, mode in [(hidden, 0), (evidence_root, 0), (hidden, 0o644), (hidden.parent, 0o644),
                             (evidence_root, 0o644)]:
            with self.subTest(locked=locked.name, mode=oct(mode)):
                locked.chmod(mode)
                self.addCleanup(locked.chmod, 0o755)
                with self.assertRaisesRegex(verdicts.VerdictError, "Done reads every mutant log.*Permission denied"):
                    self.record(head, evidence={"idiom": idiom})
                self.assertEqual(self.record(head, "not-done", evidence={"idiom": idiom}, findings=["x"]).verdict,
                                 "not-done")
                locked.chmod(0o755)

    def test_a_mutant_log_behind_a_linked_folder_counts(self):
        head = self.change({"src/format.ts": "x\n"})
        idiom = [self.media("idiom.txt", "none: a fixture\n")]
        elsewhere = self.dir / "runs"
        elsewhere.mkdir()
        (elsewhere / "mutants.log").write_text("survived: hidden regression\n")
        folder = pathlib.Path(self.saved(head, "idiom.txt", "none: x\n")).parent
        (folder / "run").symlink_to(elsewhere)
        (elsewhere / "loop").symlink_to(folder)  # a cycle back to the head's folder
        with self.assertRaisesRegex(verdicts.VerdictError, r"mutants\.log in this head's evidence folder.*hidden regression"):
            self.record(head, evidence={"idiom": idiom})

    def test_each_mutant_log_counts_once_by_identity(self):
        head = self.change({"src/format.ts": "x\n"})
        idiom = [self.media("idiom.txt", "none: a fixture\n")]
        log = pathlib.Path(self.saved(head, "runs/mutants.log", "survived: real regression\n"))
        folder = log.parent.parent
        (folder / "a").symlink_to(log.parent)
        (folder / "b").symlink_to(log.parent)
        short = pathlib.Path(self.saved(head[:8], "notes.txt", "x\n")).parent
        (short / "runs").symlink_to(log.parent)
        with self.assertRaisesRegex(verdicts.VerdictError, r"it shows 1 survived \(real regression\)"):
            self.record(head, evidence={"idiom": idiom})
        os.link(log, folder / "mutants-again.log")
        (log.parent / "x").mkdir()
        (log.parent / "x" / "y").symlink_to(log.parent / "z")
        (log.parent / "z").mkdir()
        (log.parent / "z" / "x").symlink_to(log.parent / "x")  # a cycle below the head's folder
        for name in ("p1", "p2"):  # a branching one, which a walk that revisits folders takes 2^40 steps through
            (log.parent / "x" / name).symlink_to(log.parent)
        with self.assertRaisesRegex(verdicts.VerdictError, r"it shows 1 survived \(real regression\)"):
            self.record(head, evidence={"idiom": idiom})
        os.unlink(folder / "mutants-again.log")
        kills =pathlib.Path(self.saved(head, "runs/mutants.log", "killed: a\nkilled: b\nkilled: c\n"))
        os.link(kills, folder / "mutants-copy.log")  # a hard link is the same file
        variant = str(kills).replace("mutants.log", "MUTANTS.log")
        same_case = os.path.exists(variant) and os.path.samefile(variant, kills)
        for ref in [str(kills), str(folder / "mutants-copy.log")] + ([variant] if same_case else []):
            with self.subTest(ref=ref):
                self.assertEqual(self.record(head, evidence={"idiom": idiom, "mutants": [ref]}).verdict, "done")

    def test_a_file_named_for_the_head_or_a_fifo_is_no_log(self):
        head = self.change({"src/format.ts": "x\n"})
        idiom = [self.media("idiom.txt", "none: a fixture\n")]
        folder = pathlib.Path(self.saved(head, "idiom.txt", "none: x\n")).parent
        (folder.parent / head[:8]).write_text("not a folder\n")
        os.mkfifo(folder / "mutants.fifo")  # reading one would wait for a writer
        self.assertEqual(self.record(head, evidence={"idiom": idiom}).verdict, "done")

    @unittest.skipIf(os.geteuid() == 0, "root reads any file")
    def test_a_link_in_a_folder_done_cannot_search_refuses_done(self):
        head = self.change({"src/format.ts": "x\n"})
        idiom = [self.media("idiom.txt", "none: a fixture\n")]
        elsewhere = self.dir / "runs"
        elsewhere.mkdir()
        (elsewhere / "mutants.log").write_text("survived: real regression\n")
        folder = pathlib.Path(self.saved(head, "idiom.txt", "none: x\n")).parent
        (folder / "run").symlink_to(elsewhere)
        folder.chmod(0o644)
        self.addCleanup(folder.chmod, 0o755)
        with self.assertRaisesRegex(verdicts.VerdictError, "Done reads every mutant log.*Permission denied"):
            self.record(head, evidence={"idiom": idiom})

    def test_bad_evidence_is_refused_for_every_verdict(self):
        head = self.change({"README.md": "# app\n\nMore.\n"})
        for verdict in verdicts.VERDICTS:
            for bad in [{"ui": ["missing.png"]}, {"tests": ["x"]}]:
                with self.subTest(verdict=verdict, bad=bad), self.assertRaises(verdicts.VerdictError):
                    self.record(head, verdict, evidence=bad, findings=["x"])
        with self.assertRaisesRegex(verdicts.VerdictError, "'tests' isn't one of"):
            self.record(head, require=["tests"])
        self.assertEqual(self.record(head).required, {})

    def test_require_adds_a_kind_the_diff_does_not_show(self):
        head = self.change({"README.md": "# app\n\nMore.\n"})
        with self.assertRaisesRegex(verdicts.VerdictError, r"parity \(--require: the intent implies it\)"):
            self.record(head, require=["parity"])
        out = self.cli("record", self.base, head, "--require", "parity", "--evidence", f"parity={self.media('p.log')}")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["required"], {"parity": ["--require: the intent implies it"]})
        row = (self.repo / ".git/verify-work/verdicts.tsv").read_text().splitlines()[-1].split("\t")
        self.assertEqual(json.loads(row[8])["required"], {"parity": ["--require: the intent implies it"]})

    def test_a_row_recorded_before_required_still_reads(self):
        head = self.change({"README.md": "# app\n\nMore.\n"})
        receipt = self.record(head)
        store = self.repo / ".git/verify-work/verdicts.tsv"
        row = store.read_text().rstrip("\n").split("\t")
        store.write_text("\t".join([*row[:8], json.dumps({"verdict": "done", "evidence": {}, "findings": []})]) + "\n")
        self.assertEqual(verdicts.find_done(self.repo, verdicts.diff(self.repo, self.base, head)), receipt)

    def test_a_broken_evidence_module_breaks_only_recording(self):
        hooks = self.dir / "hooks"
        hooks.mkdir()
        shutil.copy(HOOKS / "verdicts.py", hooks)
        (hooks / "evidence.py").write_text("raise ImportError('broken')\n")
        head = self.change({"README.md": "# app\n\nMore.\n"})
        run = lambda *args: subprocess.run([sys.executable, str(hooks / "verdicts.py"), *args], cwd=self.repo,
                                           capture_output=True, text=True, env={**os.environ, verdicts.HOOK_CONTEXT: VERIFIER})
        self.assertEqual(run("status", self.base, head).returncode, 0)
        self.assertNotEqual(run("record", self.base, head).returncode, 0)

    def test_the_cli_refuses_and_classifies(self):
        head = self.change({"src/App.tsx": APP, "src/api.ts": None}, "Change")
        refused = self.cli("record", self.base, head)
        self.assertEqual((refused.returncode, refused.stdout), (1, ""))
        self.assertEqual(refused.stderr, "Done needs evidence: ui (src/App.tsx: UI file) → --evidence ui=<capture>; "
                                         "contract (src/api.ts: changes or removes `export function list() {}`)"
                                         " → --evidence contract=<diff>; idiom (src/App.tsx: code)"
                                         " → --evidence idiom=<sources>\n")
        classified = self.cli("classify", self.base, head)
        self.assertEqual((classified.returncode, classified.stdout),
                         (0, "ui: src/App.tsx: UI file\ncontract: src/api.ts: changes or removes `export function list() {}`"
                             "\nidiom: src/App.tsx: code\n"))
        none = self.cli("classify", self.base, self.base)
        self.assertEqual((none.returncode, none.stdout), (0, "none\n"))
        self.assertEqual(self.cli("classify", self.base, "nope").returncode, 1)


class Idiom(Repo):
    """Done on code needs a file naming the upstream source for each non-trivial pattern."""

    media, record, cli = Recording.media, Recording.record, Recording.cli

    SOURCED = ("`Effect.retry` with `Schedule.exponential` · verified by the retry test · "
               "source: https://effect.website/docs/error-management/retrying/\n"
               "`AbortSignal.timeout` · source: https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/timeout_static\n")

    def test_code_outside_tests_needs_it(self):
        self.base = self.change({"src/old.ts": "x\n", "scripts/gone.py": "x\n"}, "Add files")
        self.assertEqual(evidence.classify(self.repo, self.base, self.change({
            "src/api.ts": "export function list() {}\nexport function count() {}\n", "src/new.py": "x\n",
            "src/old.ts": "y\n", "scripts/gone.py": None, "src/App.test.tsx": "x\n", "tests/test_a.py": "x\n",
            "README.md": "more\n", "scripts/env.sh": "x\n"})),
            {"idiom": ["src/api.ts: code", "src/new.py: code", "src/old.ts: code"]})

    def test_the_ref_names_a_source_per_pattern_or_says_none(self):
        refs = {"missing.txt": None, "empty.txt": "", "blank.txt": "\n  \n",
                "unsourced.txt": "`Effect.retry` for the upload · verified by the retry test\n",
                "half.txt": self.SOURCED + "`Layer.scoped` for the pool\n", "bare-none.txt": "none:\n",
                "none-and-more.txt": "none: a rename\n" + self.SOURCED,
                "bare-url.txt": "https://effect.website/docs/error-management/retrying/\n",
                "hostless.txt": "`Effect.retry` · source: [docs](https://)\n",
                "userinfo-only.txt": "`Effect.retry` · source: https://example.com@\n",
                "url-elsewhere.txt": "`Effect.retry` · source: not checked · seen: https://example.com\n",
                "other-label.txt": "`Effect.retry` · not-source: https://example.com\n"}
        problems = {"missing.txt": "no such file", "empty.txt": "the file is empty", "blank.txt": "the file is blank",
                    "unsourced.txt": "``Effect.retry` for the upload", "half.txt": "``Layer.scoped` for the pool` isn't",
                    "bare-none.txt": "`none:` isn't", "none-and-more.txt": "`none: a rename` isn't",
                    "bare-url.txt": "`https://effect.website/", "hostless.txt": "``Effect.retry` · source: [docs](https://)` isn't",
                    "userinfo-only.txt": "``Effect.retry` · source: https://example.com@` isn't",
                    "url-elsewhere.txt": "``Effect.retry` · source: not checked", "other-label.txt": "``Effect.retry` · not-source"}
        for name, text in refs.items():
            with self.subTest(name=name):
                if text is not None:
                    self.media(name, text)
                _, found = evidence.check("idiom", [name], self.dir)
                self.assertEqual(len(found), 1)
                self.assertTrue(found[0].startswith(f"idiom={name}: {problems[name]}"), found[0])
        for text in [self.SOURCED, "none: renames a variable; adds no pattern\n",
                     "`useId` · source: [React docs](https://react.dev/reference/react/useId)\n"]:
            with self.subTest(text=text):
                self.assertEqual(evidence.check("idiom", [self.media("ok.txt", text)], self.dir)[1], [])
        none, sourced = self.media("none.txt", "none: a rename\n"), self.media("sourced.txt", self.SOURCED)
        self.assertEqual(evidence.check("idiom", [none, "not-run:offline"], self.dir)[1], [])
        self.assertEqual(evidence.check("idiom", [none, sourced], self.dir)[1],
                         [f"idiom={none}: a `none:` file says the change has no pattern, so it's the only idiom ref"])

    def test_done_on_code_needs_it_and_not_run_backs_not_verified_only(self):
        head = self.change({"src/upload.ts": "x\n"})
        with self.assertRaisesRegex(verdicts.VerdictError, r"^Done needs evidence: idiom \(src/upload.ts: code\)"
                                                           r" → --evidence idiom=<sources>$"):
            self.record(head)
        with self.assertRaisesRegex(verdicts.VerdictError, r"idiom \(src/upload.ts: code\): not run here \(no docs\)"):
            self.record(head, evidence={"idiom": ["not-run:no docs"]})
        self.record(head, "not-verified", evidence={"idiom": ["not-run:no docs"]}, findings=["no docs"])
        for text in [self.SOURCED, "none: renames a variable\n"]:
            with self.subTest(text=text):
                ref = self.media("idiom.txt", text)
                self.assertEqual(self.record(head, evidence={"idiom": [ref]}).evidence, {"idiom": [ref]})

    def test_status_shows_a_dones_sources(self):
        head = self.change({"src/upload.ts": "x\n"})
        ref = self.media("idiom.txt", self.SOURCED)
        self.record(head, evidence={"idiom": [ref, "not-run:offline"]})
        sources = lambda: [line for line in self.cli("status", self.base, head).stdout.splitlines() if line.startswith("idiom:")]
        self.assertEqual(sources(), [f"idiom: {line}" for line in self.SOURCED.splitlines()])
        pathlib.Path(ref).unlink()
        self.assertEqual(sources(), [f"idiom: missing: {ref}"])

    def test_a_done_recorded_before_the_kind_still_reads(self):
        """The merge gate reads find_done, which doesn't re-check evidence, so a code
        diff's Done from before idiom existed still lets it merge."""
        head = self.change({"src/upload.ts": "x\n"})
        self.record(head, evidence={"idiom": [self.media("idiom.txt", self.SOURCED)]})
        store = self.repo / ".git/verify-work/verdicts.tsv"
        row = store.read_text().rstrip("\n").split("\t")
        before = {"verdict": "done", "evidence": {}, "findings": [], "required": {}, "branch": "main"}
        store.write_text("\t".join([*row[:8], json.dumps(before, separators=(",", ":"))]) + "\n")
        found = verdicts.find_done(self.repo, verdicts.diff(self.repo, self.base, head))
        self.assertEqual((found.verdict, found.evidence, found.required), ("done", {}, {}))
        self.assertEqual(verdicts.last(self.repo, "main").patch_id, found.patch_id)
        self.assertEqual(self.cli("status", self.base, head).stdout.splitlines()[1:2],
                         [f"done: yes ({row[3]}, head {head[:12]}, a1)"])


if __name__ == "__main__":
    unittest.main()
