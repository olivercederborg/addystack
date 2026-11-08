"""Run: python3 -m unittest discover -s correct/scripts"""
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("corrections.py")


def message(thread, created_at, text, created_by="user", role="user"):
    return (thread, role, created_at, json.dumps({"text": text, "createdBy": created_by}))


def build_db(path):
    db = sqlite3.connect(path)
    db.executescript("""
        create table projection_projects (project_id text, title text, workspace_root text);
        create table orchestration_v2_projection_threads (thread_id text, project_id text, title text);
        create table orchestration_v2_projection_messages (
            message_id integer primary key, thread_id text, role text, created_at text, payload_json text);
    """)
    db.executemany("insert into projection_projects values (?, ?, ?)", [
        ("p-strict", "strict", "/repos/strict"),
        ("p-skills-1", "skills", "/repos/skills"),
        ("p-skills-2", "skills", "/work/skills"),
    ])
    db.executemany("insert into orchestration_v2_projection_threads values (?, ?, ?)", [
        ("t-redesign", "p-strict", "Redesign\tsets"),
        ("t-spacing", "p-strict", "Fix spacing"),
        ("t-kit", "p-skills-1", "Kit"),
    ])
    db.executemany(
        "insert into orchestration_v2_projection_messages (thread_id, role, created_at, payload_json) values (?, ?, ?, ?)", [
            message("t-redesign", "2026-10-01T09:00:00.000Z", "use the theme spacing token,\nnot 12"),
            message("t-redesign", "2026-10-01T09:01:00.000Z", "Done: switched to tokens", "agent", "assistant"),
            message("t-redesign", "2026-10-01T09:02:00.000Z", "Owner report: layer 1 built", "agent"),
            message("t-redesign", "2026-10-01T09:03:00.000Z", "<task-notification>child finished</task-notification>"),
            message("t-spacing", "2026-10-03T10:00:00.000Z", "Spacing again: theme tokens only"),
            message("t-spacing", "2026-10-03T10:05:00.000Z", "rename the branch to fix-sets"),
            message("t-kit", "2026-10-02T08:00:00.000Z", "skills kit message"),
        ])
    db.commit()
    db.close()


class CorrectionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name, "state.sqlite")
        build_db(self.db)
        self.digest = hashlib.sha256(self.db.read_bytes()).hexdigest()

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), self.digest, "the DB changed")
        self.assertEqual(sorted(p.name for p in Path(self.tmp.name).iterdir()), ["state.sqlite"])
        self.tmp.cleanup()

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--db", str(self.db), *args],
                              capture_output=True, text=True)

    def rows(self, *args):
        result = self.run_script(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [line.split("\t") for line in result.stdout.splitlines()]

    def test_messages_keep_only_what_the_user_typed(self):
        self.assertEqual(self.rows("messages", "--project", "strict"), [
            ["2026-10-01T09:00:00.000Z", "t-redesign", "Redesign\\tsets", "use the theme spacing token,\\nnot 12"],
            ["2026-10-03T10:00:00.000Z", "t-spacing", "Fix spacing", "Spacing again: theme tokens only"],
            ["2026-10-03T10:05:00.000Z", "t-spacing", "Fix spacing", "rename the branch to fix-sets"],
        ])

    def test_project_by_id(self):
        self.assertEqual([row[3] for row in self.rows("messages", "--project", "p-skills-1")], ["skills kit message"])

    def test_since_drops_older_messages(self):
        self.assertEqual([row[0] for row in self.rows("messages", "--project", "strict", "--since", "2026-10-02")],
                         ["2026-10-03T10:00:00.000Z", "2026-10-03T10:05:00.000Z"])

    def test_grep_matches_case_insensitively(self):
        self.assertEqual([row[3] for row in self.rows("messages", "--project", "strict", "--grep", "theme (spacing|tokens)")],
                         ["use the theme spacing token,\\nnot 12", "Spacing again: theme tokens only"])

    def test_ambiguous_title_asks_for_an_id(self):
        result = self.run_script("messages", "--project", "skills")
        self.assertEqual(result.returncode, 1)
        self.assertIn("p-skills-1", result.stderr)
        self.assertIn("p-skills-2", result.stderr)

    def test_unknown_project_fails(self):
        result = self.run_script("messages", "--project", "nope")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no project", result.stderr)

    def test_projects_count_typed_messages(self):
        self.assertEqual(self.rows("projects"), [
            ["p-skills-1", "skills", "/repos/skills", "1"],
            ["p-skills-2", "skills", "/work/skills", "0"],
            ["p-strict", "strict", "/repos/strict", "3"],
        ])


if __name__ == "__main__":
    unittest.main()
