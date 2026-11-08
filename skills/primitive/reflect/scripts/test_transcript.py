"""Run: python3 -m unittest discover -s reflect/scripts"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import transcript


def write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def claude_row(kind, content, **extra):
    return {"type": kind, "cwd": "/tmp", "message": {"role": kind, "content": content}, **extra}


def codex_row(payload):
    return {"type": "response_item", "payload": payload}


def run(fn, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        fn(*args)
    return out.getvalue()


class ClaudeSession(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.loaded = self.tmp / "loaded" / "SKILL.md"
        self.authored = self.tmp / "authored" / "SKILL.md"
        for skill in (self.loaded, self.authored):
            skill.parent.mkdir()
            skill.write_text("---\nname: x\n---\n")
        self.long_reply = "verdict " + "x" * 25000 + " TAIL"
        self.long_question = "question " + "y" * 9000 + " correction at the end"
        self.path = write_jsonl(self.tmp / "session.jsonl", [
            claude_row("user", "<system-reminder>injected</system-reminder>"),
            claude_row("user", self.long_question),
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
            claude_row("assistant", [{"type": "text", "text": self.long_reply}]),
            claude_row("user", "This session is being continued from a previous conversation.",
                       isCompactSummary=True),
            claude_row("user", "<request>tagged but typed by the user</request>"),
            claude_row("user", "sidechain", isSidechain=True),
        ])

    def test_digest_numbers_user_turns_and_skips_injected(self):
        digest = transcript.digest(self.path)
        self.assertIn("## Turn 1 · user\n\n" + self.long_question, digest)
        self.assertIn("## Turn 2 · user\n\n<request>", digest)
        self.assertNotIn("## Turn 3", digest)
        self.assertIn("- injected context [L1]", digest)
        self.assertIn("- injected context [L3]: Base directory", digest)
        self.assertIn("- injected context [L9]: This session is being continued", digest)
        self.assertNotIn("sidechain", digest)

    def test_digest_keeps_final_reply_whole(self):
        digest = transcript.digest(self.path)
        self.assertIn("### reply\n\n" + self.long_reply, digest)
        self.assertIn("### assistant\n\nworking on it", digest)

    def test_digest_marks_errors_and_line_numbers(self):
        digest = transcript.digest(self.path)
        self.assertIn("- tool Skill [L4]:", digest)
        self.assertIn("→ ❌ boom", digest)

    def test_skills_labels_loaded_and_authored(self):
        lines = run(transcript.skills, self.path).splitlines()
        labels = {row[0]: row[3] for row in (line.split("\t") for line in lines)}
        self.assertEqual(labels, {"loaded": "authored+loaded", "authored": "authored", "builtin": "loaded"})
        self.assertEqual(sum(line.startswith("builtin\t(not found)") for line in lines), 1)


class TypedTurns(unittest.TestCase):
    """Only what the user typed is a turn: hooks/transcripts.py decides, as the scorecard does."""

    def test_notices_wakes_and_agent_briefs_are_not_turns(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = write_jsonl(tmp / "0f5c3a1e-2b4d-4c6e-8f90-a1b2c3d4e5f6.jsonl", [
            claude_row("user", "Act as the implementation sub-agent.\nMode: personal"),
            claude_row("user", "fix the login bug"),
            claude_row("user", "Delegated task node: task_1 finished. Result: done"),
            claude_row("user", "Update on pull request #153: a new review comment"),
            claude_row("user", "[Assistant quote](t3-citation://t/1?comment=move+the+skills+checkout+to+main)"),
            claude_row("user", "[User attached one or more files without additional text.]"),
            claude_row("user", "<command-message>reflect</command-message>\n<command-name>/reflect</command-name>\n"
                               "<command-args>how can we avoid this?</command-args>"),
        ])
        brief = {"Act as the implementation sub-agent.\nMode: personal": ["agent"]}
        with mock.patch.object(transcript.transcripts.t3_child, "senders", return_value=brief):
            digest = transcript.digest(path)
        self.assertIn("## Turn 1 · user\n\nfix the login bug", digest)
        self.assertIn("## Turn 2 · user\n\nmove the skills checkout to main", digest)
        self.assertIn("## Turn 3 · user\n\n[User attached", digest)
        self.assertIn("## Turn 4 · user\n\n/reflect how can we avoid this?", digest)
        self.assertNotIn("## Turn 5", digest)
        for line in ("L1]: Act as", "L3]: Delegated task node:", "L4]: Update on pull request"):
            self.assertIn(f"- injected context [{line}", digest)


    def test_a_chip_the_user_sent_alone_is_a_turn(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = write_jsonl(tmp / "session.jsonl", [
            claude_row("user", '[Thread: tower-app; ref=thread-1]\n\n<t3_context version="1">\n'
                               'The user attached this thread.\n</t3_context>'),
        ])
        self.assertIn("## Turn 1 · user\n\n[Thread: tower-app", transcript.digest(path))

    def test_a_t3_context_block_alone_is_no_turn(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = write_jsonl(tmp / "session.jsonl", [
            claude_row("user", '<assistant_citations>\n[{"citation": {"comment": 1}}]\n</assistant_citations>'),
            claude_row("user", '<t3_context version="1">\n<context kind="review-comment" id="rc">\nfile: PR #87\n'
                               'comment:\n  titled [Image cache] Fix previews\n</context>\n</t3_context>'),
            claude_row("user", "fix it"),
        ])
        digest = transcript.digest(path)
        self.assertIn("## Turn 1 · user\n\nfix it", digest)
        self.assertNotIn("## Turn 2", digest)

    def test_a_turn_keeps_the_context_its_words_are_about(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = write_jsonl(tmp / "session.jsonl", [
            claude_row("user", "[Review comment: a.ts L3; ref=rc-1]\n\n<t3_context version=\"1\">\n"
                               "<context kind=\"review-comment\" id=\"rc-1\">\nfile: a.ts\ncomment:\n"
                               "  can we inline this?\ndiff:\n  +x\n</context>\n</t3_context>"),
        ])
        digest = transcript.digest(path)
        self.assertIn("## Turn 1 · user\n\ncan we inline this?\n\n- with context [L1]: [Review comment: a.ts", digest)
        self.assertIn("diff:\n  +x", digest)

    def test_a_wake_keeps_the_reply_before_it(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = write_jsonl(tmp / "session.jsonl", [
            claude_row("user", "fix it"),
            claude_row("assistant", [{"type": "text", "text": "ORIGINAL " + "x" * 2000 + " END"}]),
            claude_row("user", "Update on pull request #153: checks passed"),
            claude_row("assistant", [{"type": "text", "text": "Wake handled."}]),
            claude_row("user", "what changed?"),
        ])
        self.assertIn("### reply\n\nORIGINAL " + "x" * 2000 + " END", transcript.digest(path))

    def test_an_interrupt_is_no_turn(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = write_jsonl(tmp / "session.jsonl", [
            claude_row("user", "fix it"),
            claude_row("user", "[Request interrupted by user]"),
            claude_row("user", "stop"),
        ])
        digest = transcript.digest(path)
        self.assertIn("## Turn 2 · user\n\nstop", digest)
        self.assertNotIn("## Turn 3", digest)

    def test_a_codex_page_file_finds_its_session_id_in_session_meta(self):
        sid = "0f5c3a1e-2b4d-4c6e-8f90-a1b2c3d4e5f6"
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = write_jsonl(tmp / f"rollout-2026-01-01T00-00-00-{sid}_01a0cccc.jsonl", [
            {"type": "session_meta", "payload": {"id": sid, "cwd": "/repo"}},
            codex_row({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Agent report"}]}),
        ])
        with mock.patch.object(transcript.transcripts.t3_child, "senders", return_value={"Agent report": ["agent"]}) as senders:
            digest = transcript.digest(path)
        senders.assert_called_once_with(sid)
        self.assertNotIn("## Turn", digest)

    def test_an_installed_copy_reads_typed_turns_on_its_own(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copytree(Path(__file__).parent, tmp / "reflect" / "scripts", symlinks=False)
        path = write_jsonl(tmp / "session.jsonl", [
            claude_row("user", "fix it"),
            claude_row("user", "Delegated task node: task_1 finished."),
        ])
        out = subprocess.run([sys.executable, "-I", str(tmp / "reflect" / "scripts" / "transcript.py"), "digest",
                              str(path)], capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.count("## Turn"), 1)


class CodexSession(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.loaded = self.tmp / "loaded" / "SKILL.md"
        self.patched = self.tmp / "patched" / "SKILL.md"
        self.native = self.tmp / "native" / "SKILL.md"
        self.redirected = self.tmp / "redirected" / "SKILL.md"
        self.relative = self.tmp / "work" / "relative" / "SKILL.md"
        self.wrapped = self.tmp / "wrapped" / "SKILL.md"
        self.batched = self.tmp / "second" / "batched" / "SKILL.md"
        self.teed = self.tmp / "work" / "teed" / "SKILL.md"
        self.quoted = self.tmp / "quoted" / "SKILL.md"
        self.single = self.tmp / "third" / "single" / "SKILL.md"
        for skill in (self.loaded, self.patched, self.native, self.redirected, self.relative, self.wrapped,
                      self.batched, self.teed, self.quoted, self.single):
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: x\n---\n")
        self.path = write_jsonl(self.tmp / "rollout-test.jsonl", [
            {"type": "session_meta", "payload": {"cwd": str(self.tmp)}},
            codex_row({"type": "message", "role": "user",
                       "content": [{"type": "input_text", "text": "# AGENTS.md instructions\nrules"}]}),
            codex_row({"type": "message", "role": "user",
                       "content": [{"type": "input_text", "text": "<recommended_plugins>\n- Airtable</recommended_plugins>"},
                                   {"type": "input_text", "text": "codex question"}]}),
            codex_row({"type": "message", "role": "user", "content": [{"type": "input_text", "text":
                       f"<skill>\n<name>native</name>\n<path>{self.native}</path>\n---\nname: native\n---\nbody"}]}),
            codex_row({"type": "function_call", "name": "exec_command",
                       "arguments": json.dumps({"cmd": f"cat {self.loaded}"})}),
            codex_row({"type": "function_call_output", "output": "file body"}),
            codex_row({"type": "function_call", "name": "exec_command",
                       "arguments": json.dumps({"cmd": "cat relative/SKILL.md", "workdir": str(self.tmp / "work")})}),
            codex_row({"type": "function_call", "name": "exec_command",
                       "arguments": json.dumps({"cmd": f"cat > {self.redirected} <<'EOF'\nbody\nEOF"})}),
            codex_row({"type": "function_call", "name": "exec_command",
                       "arguments": json.dumps({"cmd": f'echo x | tee "teed/SKILL.md"; cat > "{self.quoted}"',
                                                "workdir": str(self.tmp / "work")})}),
            codex_row({"type": "custom_tool_call", "name": "apply_patch",
                       "input": f"*** Begin Patch\n*** Update File: {self.patched}\n@@\n-a\n+b\n"}),
            codex_row({"type": "custom_tool_call", "name": "exec", "input":
                       f'await tools.exec_command({{cmd:"ls", workdir:"/nonexistent"}}); '
                       f'await tools.exec_command({{cmd:"cat batched/SKILL.md", workdir:"{self.tmp / "second"}"}});'}),
            codex_row({"type": "custom_tool_call", "name": "exec", "input":
                       f"await tools.exec_command({{cmd:'cat single/SKILL.md', workdir:'{self.tmp / 'third'}'}});"}),
            codex_row({"type": "custom_tool_call", "name": "exec", "input":
                       f"await tools.exec_command({{cmd:'wc -l {self.wrapped}'}});"}),
            codex_row({"type": "custom_tool_call", "name": "exec", "input":
                       f'text(await tools.apply_patch("*** Begin Patch\\n*** Add File: {self.wrapped}'
                       f'\\n+---\\n*** End Patch"));'}),
            codex_row({"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "<subagent_notification>\n{\"status\": \"done\"}"}]}),
            codex_row({"type": "message", "role": "user", "content": [{"type": "input_text", "text":
                "<in-app-browser-context source=\"ambient-ui-state\">\nurl: x\n</in-app-browser-context>\n"
                "## My request:\njust do it instead of this"}]}),
            codex_row({"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "look at this screenshot"},
                {"type": "input_text", "text": "<image name=shot.png>"},
                {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
                {"type": "input_text", "text": "</image>"}]}),
            codex_row({"type": "message", "role": "assistant",
                       "content": [{"type": "output_text", "text": "first part " + "z" * 2000},
                                   {"type": "output_text", "text": "done"}]}),
        ])

    def test_digest(self):
        digest = transcript.digest(self.path)
        self.assertIn("## Turn 1 · user\n\ncodex question", digest)
        self.assertIn("## Turn 2 · user\n\njust do it instead of this", digest)
        self.assertIn("## Turn 3 · user\n\nlook at this screenshot\n<image name=shot.png>\n</image>", digest)
        self.assertNotIn("## Turn 4", digest)
        self.assertIn("- injected context [L15]: <subagent_notification>", digest)
        self.assertIn("- tool exec_command [L5]:", digest)
        self.assertIn("- injected context [L3]: <recommended_plugins>", digest)
        self.assertIn("- injected context [L4]: <skill>", digest)
        self.assertEqual(transcript.opening_prompt(self.path), "codex question")
        self.assertIn("### reply\n\nfirst part " + "z" * 2000 + "\ndone", digest)

    def test_a_batched_write_resolves_against_its_own_workdir(self):
        guide_a, guide_b = self.tmp / "a" / "guide" / "SKILL.md", self.tmp / "b" / "guide" / "SKILL.md"
        for guide in (guide_a, guide_b):
            guide.parent.mkdir(parents=True)
            guide.write_text("---\nname: guide\n---\n")
        path = write_jsonl(self.tmp / "rollout-batch.jsonl", [
            {"type": "session_meta", "payload": {"cwd": str(self.tmp)}},
            codex_row({"type": "function_call", "name": "exec_command",
                       "arguments": json.dumps({"cmd": f"cat {guide_a}"})}),
            codex_row({"type": "custom_tool_call", "name": "exec", "input":
                       f'await tools.exec_command({{cmd:"ls", workdir:"{self.tmp / "a"}"}}); '
                       f'await tools.exec_command\n  ({{cmd:"cat > guide/SKILL.md", workdir:"{self.tmp / "b"}"}});'}),
        ])
        rows = {row[1]: row[3] for row in (line.split("\t") for line in run(transcript.skills, path).splitlines())}
        self.assertEqual(rows, {os.path.realpath(guide_a): "read", os.path.realpath(guide_b): "authored"})

    def test_opening_prompt_splits_only_at_a_header_line(self):
        path = write_jsonl(self.tmp / "rollout-quote.jsonl", [
            {"type": "session_meta", "payload": {"cwd": str(self.tmp)}},
            codex_row({"type": "message", "role": "user", "content": [{"type": "input_text",
                       "text": "review this; it quotes ## My request for Codex: mid-line"}]}),
        ])
        self.assertEqual(transcript.opening_prompt(path), "review this; it quotes ## My request for Codex: mid-line")

    def test_skills(self):
        rows = [line.split("\t") for line in run(transcript.skills, self.path).splitlines()]
        labels = {row[0]: row[3] for row in rows}
        self.assertEqual(labels, {"loaded": "read", "patched": "authored", "native": "loaded",
                                  "redirected": "authored", "relative": "read", "wrapped": "authored",
                                  "batched": "read", "teed": "authored", "quoted": "authored",
                                  "single": "read"})


class RewoundCodexSession(unittest.TestCase):
    """Editing an earlier message continues the session in a new rollout file, whose
    history_base cuts the previous file; the tail after the cut is an abandoned branch."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.project, self.sid = self.tmp / "project", "01a0aaaa-0000-0000-0000-000000000000"
        self.project.mkdir()
        self.day = self.tmp / "codex" / "sessions" / "2026" / "01" / "01"
        self.day.mkdir(parents=True)

    def user(self, text):
        return codex_row({"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]})

    def meta(self, **extra):
        return {"type": "session_meta", "payload": {"id": self.sid, "session_id": self.sid,
                                                    "cwd": str(self.project), **extra}}

    def test_digest_follows_the_kept_history_and_marks_the_rewind(self):
        self.long_reply = "here is the plan " + "q" * 3000 + " END"
        kept = [self.meta(), self.user("first message"),
                codex_row({"type": "message", "role": "assistant",
                           "content": [{"type": "output_text", "text": self.long_reply}]})]
        cut = len(("\n".join(json.dumps(r) for r in kept) + "\n").encode())
        first = write_jsonl(self.day / f"rollout-2026-01-01T00-00-00-{self.sid}.jsonl",
                            kept + [self.user("commit if everything is good")])
        second = write_jsonl(self.day / f"rollout-2026-01-01T01-00-00-{self.sid}_01a0bbbb.jsonl", [
            self.meta(history_base={"thread_id": self.sid, "end_byte_offset": cut}),
            self.user("commit if everything is production-ready"),
            codex_row({"type": "function_call", "name": "exec_command", "arguments": json.dumps({"cmd": "ls"})}),
        ])
        with contextlib.chdir(self.day):
            relative = transcript.digest(second.name)
        self.assertIn("- rewound after", relative)
        self.assertNotIn("is good", relative)
        digest = transcript.digest(second)
        self.assertIn("## Turn 1 · user\n\nfirst message", digest)
        self.assertIn("### reply\n\n" + self.long_reply, digest)
        self.assertIn("- rewound after [p1:L3]: the user edited an earlier message here", digest)
        self.assertIn("## Turn 2 · user\n\ncommit if everything is production-ready", digest)
        self.assertNotIn("is good", digest)
        self.assertIn("- tool exec_command [p2:L3]:", digest)
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.tmp / "codex"),
                                          "CLAUDE_CONFIG_DIR": str(self.tmp / "claude")}):
            out = run(transcript.find, str(self.project))
        self.assertEqual(len(out.splitlines()), 1)
        self.assertIn(f"{first}\t", out)
        self.assertIn("\tfirst message", out)

    def test_a_rewind_right_after_session_meta_points_at_line_1(self):
        first_kept = [self.meta(), self.user("first message")]
        first_cut = len(("\n".join(json.dumps(r) for r in first_kept) + "\n").encode())
        write_jsonl(self.day / f"rollout-2026-01-01T00-00-00-{self.sid}.jsonl", first_kept + [self.user("tail")])
        second_meta = self.meta(history_base={"thread_id": self.sid, "end_byte_offset": first_cut})
        second_cut = len((json.dumps(second_meta) + "\n").encode())
        write_jsonl(self.day / f"rollout-2026-01-01T01-00-00-{self.sid}_01a0bbbb.jsonl",
                    [second_meta, self.user("edited away at once")])
        third = write_jsonl(self.day / f"rollout-2026-01-01T02-00-00-{self.sid}_01a0cccc.jsonl", [
            self.meta(history_base={"thread_id": self.sid, "end_byte_offset": second_cut}),
            self.user("final edit")])
        digest = transcript.digest(third)
        self.assertIn("- rewound after [p2:L1]:", digest)
        self.assertNotIn("L0]", digest)
        self.assertNotIn("edited away at once", digest)

    def test_a_file_without_history_base_restarts_the_session(self):
        kept = [self.meta(), self.user("abandoned first message")]
        cut = len(("\n".join(json.dumps(r) for r in kept) + "\n").encode())
        write_jsonl(self.day / f"rollout-2026-01-01T00-00-00-{self.sid}.jsonl", kept + [self.user("tail")])
        write_jsonl(self.day / f"rollout-2026-01-01T01-00-00-{self.sid}_01a0bbbb.jsonl", [
            self.meta(history_base={"thread_id": self.sid, "end_byte_offset": cut}),
            self.user("abandoned second message")])
        third = write_jsonl(self.day / f"rollout-2026-01-01T02-00-00-{self.sid}_01a0cccc.jsonl",
                            [self.meta(), self.user("edited first message")])
        digest = transcript.digest(third)
        self.assertNotIn("abandoned", digest)
        self.assertIn("## Turn 1 · user\n\nedited first message", digest)
        self.assertEqual(transcript.opening_prompt(third), "edited first message")
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.tmp / "codex"),
                                          "CLAUDE_CONFIG_DIR": str(self.tmp / "claude")}):
            out = run(transcript.find, str(self.project))
        self.assertIn(f"{third}\t", out)
        self.assertIn("\tedited first message", out)

    def test_a_subagent_is_its_own_session(self):
        child = "01a0cccc-0000-0000-0000-000000000000"
        write_jsonl(self.day / f"rollout-2026-01-01T00-00-00-{self.sid}.jsonl",
                    [self.meta(), self.user("parent message")])
        sub = write_jsonl(self.day / f"rollout-2026-01-01T00-00-05-{child}.jsonl", [
            {"type": "session_meta", "payload": {"id": child, "session_id": self.sid, "cwd": str(self.project),
                                                 "source": {"subagent": {}}}},
            self.user("subagent task"),
        ])
        digest = transcript.digest(sub)
        self.assertIn("subagent task", digest)
        self.assertNotIn("parent message", digest)


class Scan(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.project = self.tmp / "claude" / "projects" / "-repo"
        self.project.mkdir(parents=True)
        self.day = self.tmp / "codex" / "sessions" / "2026" / "01" / "01"
        self.day.mkdir(parents=True)

    def scan(self, *args):
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.tmp / "codex"),
                                          "CLAUDE_CONFIG_DIR": str(self.tmp / "claude")}):
            return run(transcript.scan, *args)

    def test_counts_commands_across_sessions_and_skips_subagents(self):
        write_jsonl(self.project / "one.jsonl", [
            claude_row("assistant", [{"type": "tool_use", "name": "Bash", "input": {"command": "git push origin HEAD"}}]),
            claude_row("assistant", [{"type": "tool_use", "name": "Bash", "input": {"command": "echo 'git push' > notes.md"}}]),
        ])
        write_jsonl(self.day / "rollout-2026-01-01T00-00-00-main.jsonl", [
            {"type": "session_meta", "payload": {"id": "main", "cwd": "/repo"}},
            codex_row({"type": "custom_tool_call", "name": "exec",
                       "input": 'await tools.exec_command({cmd:"git push -u origin x", workdir:"/repo"});'}),
            codex_row({"type": "function_call", "name": "shell",
                       "arguments": json.dumps({"command": ["bash", "-lc", "gh pr ready 3"]})}),
        ])
        write_jsonl(self.day / "rollout-2026-01-01T00-00-01-child.jsonl", [
            {"type": "session_meta", "payload": {"id": "child", "cwd": "/repo", "source": {"subagent": {}}}},
            codex_row({"type": "custom_tool_call", "name": "exec", "input": 'tools.exec_command({cmd:"git push"})'}),
        ])
        out = self.scan(r"(?:^|[;&|\n])\s*(?:git push|gh pr ready)\b")
        self.assertIn("3 matching commands in 2 of 2 sessions", out)

    def test_counts_only_shell_commands(self):
        write_jsonl(self.project / "one.jsonl", [
            claude_row("assistant", [{"type": "tool_use", "name": "Bash", "input": {"command": "deny-me now"}}]),
            claude_row("assistant", [{"type": "tool_use", "name": "Edit",
                                      "input": {"file_path": "/x/SKILL.md", "new_string": "then deny-me"}}]),
        ])
        hook = self.tmp / "hook.py"
        hook.write_text("#!/usr/bin/env python3\nimport json, sys\nc = json.load(sys.stdin)['tool_input']['command']\n"
                        "print(json.dumps({'decision': 'deny'}) if 'deny-me' in c else '')\n")
        hook.chmod(0o755)
        self.assertIn("1 matching commands in 1 of 1 sessions", self.scan(None, str(hook)))
        self.assertIn("1 matching commands in 1 of 1 sessions", self.scan("deny-me"))

    def test_reads_a_javascript_escape_that_json_rejects(self):
        # "\d" is legal in a JavaScript string and invalid JSON; scan died on it on 10-27.
        self.assertEqual(transcript.shell_command("exec", r'await tools.exec_command({cmd:"rg \d+ \"a b\""})'),
                         'rg d+ "a b"')
        self.assertEqual(transcript.js_string(r"git \x70u\u{73}\u0068 \\n\nx"), "git push \\n\nx")
        self.assertEqual(transcript.js_string("a\\\nb"), "ab")  # a line continuation
        self.assertEqual(transcript.js_string(r"echo \ud83d\ude80"), "echo 🚀")


class Editable(unittest.TestCase):
    def test_a_skill_in_the_repos_skills_lock_is_an_installed_copy(self):
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, repo)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        own, locked = repo / "skills/own/SKILL.md", repo / ".agents/skills/vendored/SKILL.md"
        source = repo / "skills/vendored/SKILL.md"
        personal = repo / ".agents/skills/personal/SKILL.md"
        (repo / ".git/info/exclude").write_text(".agents/skills/personal/\n")
        for skill in (own, locked, source, personal):
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: x\n---\n")
        (repo / "skills-lock.json").write_text(json.dumps({"version": 1, "skills": {"vendored": {}}}))
        self.assertTrue(transcript.editable(own))
        self.assertFalse(transcript.editable(locked))
        self.assertTrue(transcript.editable(source))
        self.assertFalse(transcript.editable(personal))


class Find(unittest.TestCase):
    def test_finds_a_resumed_codex_session_behind_newer_ones(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        project, other = tmp / "project", tmp / "other"
        project.mkdir()
        other.mkdir()
        day = tmp / "codex" / "sessions" / "2026" / "01" / "01"
        day.mkdir(parents=True)
        resumed = write_jsonl(day / "rollout-2026-01-01T00-00-00-old.jsonl", [
            {"type": "session_meta", "payload": {"cwd": str(project)}},
            codex_row({"type": "message", "role": "user",
                       "content": [{"type": "input_text", "text":
                                    "# Files mentioned by the user:\n- a.ts\n## My request:\nresumed today"}]}),
        ])
        for i in range(201):
            write_jsonl(day / f"rollout-2026-01-01T00-00-01-{i:03}.jsonl",
                        [{"type": "session_meta", "payload": {"cwd": str(other)}}])
        write_jsonl(day / "rollout-2026-01-01T00-00-02-child.jsonl", [
            {"type": "session_meta", "payload": {"cwd": str(project),
                                                 "source": {"subagent": {"thread_spawn": {}}}}},
            codex_row({"type": "message", "role": "user",
                       "content": [{"type": "input_text", "text": "subagent copy"}]}),
        ])
        os.utime(resumed)
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(tmp / "codex"),
                                          "CLAUDE_CONFIG_DIR": str(tmp / "claude")}):
            out = run(transcript.find, str(project))
        self.assertIn("\tresumed today", out)
        self.assertNotIn("subagent copy", out)


if __name__ == "__main__":
    unittest.main()
