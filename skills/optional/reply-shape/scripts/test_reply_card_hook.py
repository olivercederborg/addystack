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
OLD = re.sub(r"@v[\d.]+/", "@v0.9.0/", URL)  # the renderer at another version


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
        for src in [OLD, re.sub(r"@v[\d.]+", "", URL), "https://example.com/reply-ui/reply.js"]:
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

    def test_the_page_is_read_as_a_browser_reads_it(self):
        good = '{"ui":[{"outcome":{"status":"done","text":"Fixed"}}]}'
        self.assertIn("load exactly", run({"html": f'<script src = "{OLD}"></script><script type="application/json" id="ui">{good}</script>'}))
        self.assertIn("more than one", run({"html": page() + f'<script type="application/json" id="ui">{good}</script>'}))
        self.assertIn("has no payload", run({"html": f'<script src="{URL}"></script><script type="application/json" id="ui-state">{good}</script>'}))

    def test_nan_and_infinity_are_not_json(self):
        nan = '{"ui":[{"delta":{"label":"CPU","now":"1 s","was":"2 s","bars":[["run",NaN]]}}]}'
        self.assertIn("not JSON: NaN", run({"html": page(nan)}))

    def test_a_page_without_the_renderer_passes(self):
        self.assertIsNone(run({"html": "<svg><rect/></svg><script>console.log(1)</script>"}))
        self.assertIsNone(run({"html": '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>'}))

    def test_a_page_given_by_path_is_read(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "card.html")
            path.write_text("<!doctype html>" + page(src=OLD))
            self.assertIn("load exactly", run({"path": str(path)}))

    def test_the_wrapper_passes_without_reply_shape(self):
        with tempfile.TemporaryDirectory() as folder:
            lone = Path(folder, "addystack", "hooks", "reply-card.py")
            lone.parent.mkdir(parents=True)
            shutil.copy(WRAPPER, lone)
            self.assertIsNone(run({"html": page(src="https://example.com/reply-ui/reply.js")}, wrapper=lone))


class PinnedUrl(unittest.TestCase):
    def test_every_renderer_url_in_reply_shape_is_the_pinned_one(self):
        # Any URL to the renderer's repo or file, pinned to any version or none.
        renderer = re.compile(r"https?://[^\s\"'`)<>]*(?:reply-ui|/reply\.js)[^\s\"'`)<>]*")
        docs = sorted(SKILL.rglob("*.md"))
        self.assertIn(SKILL / "references" / "ui-cards.md", docs, "the docs aren't in this suite's input")
        self.assertIn(URL, (SKILL / "references" / "ui-cards.md").read_text())
        for path in docs:
            for found in renderer.findall(path.read_text()):
                with self.subTest(path=path.name, url=found):
                    self.assertEqual(found, URL)


if __name__ == "__main__":
    unittest.main()
