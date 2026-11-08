"""Run: python3 -m unittest discover -s reply-shape/scripts

The html_render hook: validate-card.py --hook, run through the kit's hooks/reply-card.py
as Claude Code and Codex run it."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
WRAPPER = SKILL.parents[1] / "primitive" / "addystack" / "hooks" / "reply-card.py"
URL = (SKILL / "ui" / "renderer.url").read_text().strip()
REFERENCE = (SKILL / "ui" / "examples" / "reference.json").read_text().strip()


def page(payload=REFERENCE, src=URL):
    return f'<script src="{src}"></script>\n<script type="application/json" id="ui">{payload}</script>'


def run(tool_input, wrapper=WRAPPER):
    call = {"hook_event_name": "PreToolUse", "tool_name": "mcp__t3-code__html_render", "tool_input": tool_input}
    done = subprocess.run([sys.executable, str(wrapper)], input=json.dumps(call), capture_output=True, text=True)
    return json.loads(done.stdout)["hookSpecificOutput"]["permissionDecisionReason"] if done.stdout.strip() else None


class Hook(unittest.TestCase):
    def test_a_pinned_valid_card_passes(self):
        self.assertIsNone(run({"title": "t", "height": 400, "html": page()}))

    def test_another_version_or_host_is_denied_with_the_pinned_url(self):
        for src in [URL.replace("@v", "@v0."), URL.replace("@v1.1.0", ""), "https://example.com/reply-ui/reply.js"]:
            with self.subTest(src):
                reason = run({"html": page(src=src)})
                self.assertIn(f"load exactly {URL}", reason)

    def test_an_invalid_card_is_denied_with_its_first_problem(self):
        reason = run({"html": page('{"ui":[{"outcome":{"status":"ok","text":"x"}},{"bogus":{}}]}')})
        self.assertRegex(reason, r'^Reply card is invalid: \$\.ui\[0\]\.outcome\.status: "ok" is not one of .* \(and 1 more\)')
        self.assertIn("validate-card.py", reason)

    def test_bad_json_and_a_missing_payload_are_denied(self):
        self.assertIn("not JSON", run({"html": page('{"ui":[oops')}))
        self.assertIn("has no payload", run({"html": f'<script src="{URL}"></script>'}))

    def test_a_page_without_the_renderer_passes(self):
        self.assertIsNone(run({"html": "<svg><rect/></svg><script>console.log(1)</script>"}))
        self.assertIsNone(run({"html": '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>'}))

    def test_a_page_given_by_path_is_read(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "card.html")
            path.write_text("<!doctype html>" + page(src=URL.replace("1.1.0", "1.0.0")))
            self.assertIn("load exactly", run({"path": str(path)}))

    def test_the_wrapper_passes_without_reply_shape(self):
        with tempfile.TemporaryDirectory() as folder:
            lone = Path(folder, "addystack", "hooks", "reply-card.py")
            lone.parent.mkdir(parents=True)
            shutil.copy(WRAPPER, lone)
            self.assertIsNone(run({"html": page(src="https://example.com/reply-ui/reply.js")}, wrapper=lone))


class PinnedUrl(unittest.TestCase):
    def test_every_reply_shape_file_names_the_pinned_url(self):
        pinned = re.compile(r"https://cdn\.jsdelivr\.net/gh/[^\s\"'`)]*reply-ui@[^\s\"'`)]*")
        for path in sorted(SKILL.rglob("*.md")):
            for found in pinned.findall(path.read_text()):
                with self.subTest(path=path.name):
                    self.assertEqual(found, URL)


if __name__ == "__main__":
    unittest.main()
