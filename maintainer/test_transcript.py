"""Run: python3 -m unittest discover -s maintainer -p test_transcript.py"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import transcript


def write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def claude_row(kind, content, **extra):
    return {"type": kind, "cwd": "/tmp", "message": {"role": kind, "content": content}, **extra}


class ClaudeSession(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.loaded = self.tmp / "loaded" / "SKILL.md"
        self.authored = self.tmp / "authored" / "SKILL.md"
        for skill in (self.loaded, self.authored):
            skill.parent.mkdir()
            skill.write_text("---\nname: x\n---\n")
        self.path = write_jsonl(self.tmp / "session.jsonl", [
            claude_row("user", "<system-reminder>injected</system-reminder>"),
            claude_row("user", "a question"),
            claude_row("user", [{"type": "text", "text": f"Base directory for this skill: {self.loaded.parent}\n\nbody"}],
                       isMeta=True),
            claude_row("assistant", [{"type": "text", "text": "working on it"},
                                     {"type": "tool_use", "name": "Skill", "input": {"skill": "plugin-ns:loaded"}}]),
            claude_row("user", [{"type": "tool_result", "content": "boom", "is_error": True}]),
            claude_row("assistant", [{"type": "tool_use", "name": "Read",
                                      "input": {"file_path": str(self.authored)}},
                                     {"type": "tool_use", "name": "Write",
                                      "input": {"file_path": str(self.authored), "content": "x"}}]),
            claude_row("assistant", [{"type": "tool_use", "name": "Edit",
                                      "input": {"file_path": str(self.loaded), "old_string": "x"}},
                                     {"type": "tool_use", "name": "Skill", "input": {"skill": "builtin"}},
                                     {"type": "tool_use", "name": "Skill", "input": {"skill": "builtin"}}]),
            claude_row("assistant", [{"type": "text", "text": "the reply"}]),
            claude_row("user", "This session is being continued from a previous conversation.",
                       isCompactSummary=True),
            claude_row("user", "<request>tagged but typed by the user</request>"),
            claude_row("user", "sidechain", isSidechain=True),
        ])

    def test_skills_names_each_loaded_skill_and_a_called_one_with_no_body_but_no_authored_one(self):
        self.assertEqual(transcript.skills(self.path), ["builtin", "loaded"])

    def test_skills_names_a_linked_skill_file_or_folder_by_what_it_links_to(self):
        (self.tmp / "file-alias").mkdir()
        (self.tmp / "file-alias" / "SKILL.md").symlink_to(self.loaded)
        (self.tmp / "folder-alias").symlink_to(self.loaded.parent)
        for alias in ("file-alias", "folder-alias"):
            with self.subTest(alias=alias):
                path = write_jsonl(self.tmp / f"{alias}.jsonl", [claude_row(
                    "user", [{"type": "text", "text": f"Base directory for this skill: {self.tmp / alias}\n\nbody"}],
                    isMeta=True)])
                self.assertEqual(transcript.skills(path), ["loaded"])


class Reading(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_harness_tags_are_injected_and_the_users_own_tagged_input_is_not(self):
        for text in ("<system-reminder>x", "  <task-notification>", "<app-context>"):
            self.assertTrue(transcript.is_injected(text), text)
        for text in ("<command-name>/tidy</command-name>", "<request>typed</request>", "plain words"):
            self.assertFalse(transcript.is_injected(text), text)

    def test_records_skips_a_line_that_isnt_json_and_keeps_line_numbers(self):
        path = self.tmp / "session.jsonl"
        path.write_text('{"a": 1}\nnot json\n{"b": 2}\n')
        self.assertEqual(list(transcript.records(path)), [(1, {"a": 1}), (3, {"b": 2})])

    def test_a_renamed_codex_rollout_is_codex_by_its_session_meta(self):
        path = write_jsonl(self.tmp / "renamed.jsonl", [{"type": "session_meta", "payload": {"id": "s1"}}])
        self.assertTrue(transcript.is_codex(path))
        self.assertEqual(transcript.codex_session_id(path), "s1")
        self.assertFalse(transcript.is_codex(write_jsonl(self.tmp / "claude.jsonl", [claude_row("user", "hi")])))


if __name__ == "__main__":
    unittest.main()
