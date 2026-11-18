"""Pipe tests for coordinator_queue.py: feed it the Stop event Claude Code sends from a ◆
thread whose project.md has a queue, and check whether it sends the reply back."""
import json, os, pathlib, shutil, sqlite3, subprocess, tempfile, unittest
from datetime import datetime

import project_queue

HOOK = pathlib.Path(__file__).resolve().parent / "coordinator_queue.py"
SESSION = "0b6e3c1a-5d2f-4c8e-9a71-2f4d6b8e0c13"
LINK = "<t3-thread://v2/env-mac/thread-c1>"
WORKER = "R153 <t3-thread://v2/env-mac/thread-w3>"
PROJECT = f"""# ◆ audit

Coordinator: {LINK} · Checkout: ~/kit · Mode: personal, planning autonomous

## Goal

Audit the suite.
Proof: five reports.
Follow-ups: none

## Decisions

## Workers

| Worker | Thread | Branch or PR | State | Waits on | Last side effect |
|---|---|---|---|---|---|
"""


def block(state="stop", needs=(), standing=(), options=None, **extra):
    turn = {"state": state, "needs": list(needs), **({"standing": list(standing)} if standing else {})}
    if state == "stop":
        turn["options"] = options if options is not None else [
            {"key": "a", "class": "decision", "text": "yes: stop them"}, {"key": "b", "class": "decision", "text": "no"}]
    return f"<!-- turn {json.dumps({**turn, **extra}, ensure_ascii=False)} -->"


def need(ident, name, kind="decide"):
    return {"id": ident, "kind": kind, "name": name}


SEND_BACKS = need(2, "stop format send-backs")
CARD = f"""🟡 **Stop format send-backs that double-post cards?**

1 of 2 need you · stop format send-backs · {WORKER}

| Problem | A format send-back makes the card post twice. |
|---|---|
| Pick | Yes: log them instead. |

---

**Next**

- **`a` → yes: stop them** · *recommended*
- `b` → no

"""


class CoordinatorQueue(unittest.TestCase):
    def setUp(self):
        self.folder = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        self.project_md = self.folder / ".local/state/orchestrate/audit/project.md"
        self.project_md.parent.mkdir(parents=True)
        self.write(PROJECT, ("do", "pull the Mac's dotfiles", "coordinator"), ("decide", "stop format send-backs", WORKER))

    def write(self, text, *items):
        lines = text.split("\n")
        for kind, name, source in items:
            project_queue.add(lines, kind, name, source, datetime(2026, 11, 18, 12, 0))
        self.project_md.write_text("\n".join(lines))

    def state_db(self, title="◆ audit"):
        path = self.folder / f"{len(list(self.folder.glob('*.sqlite')))}.sqlite"
        with sqlite3.connect(path) as db:
            db.execute("create table orchestration_v2_projection_provider_threads (thread_id text, payload_json text)")
            db.execute("create table orchestration_v2_projection_threads (thread_id text, title text)")
            db.execute("insert into orchestration_v2_projection_provider_threads values (?, ?)",
                       ("thread-c1", json.dumps({"nativeThreadRef": {"nativeId": SESSION}})))
            db.execute("insert into orchestration_v2_projection_threads values (?, ?)", ("thread-c1", title))
        db.close()
        return str(path)

    def run_on(self, reply, title="◆ audit", t3=True, **event):
        env = {k: v for k, v in os.environ.items() if k not in ("T3CODE_CLI_PATH", "T3_STATE_DB")}
        env.update(HOME=str(self.folder), T3_STATE_DB=self.state_db(title))
        if t3:
            env["T3CODE_CLI_PATH"] = "/t3/bin/t3"
        payload = {"session_id": SESSION, "hook_event_name": "Stop", "last_assistant_message": reply, **event}
        out = subprocess.run([str(HOOK)], input=json.dumps(payload), env=env, capture_output=True, text=True,
                             check=True).stdout
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else None

    def test_a_reply_that_ends_on_the_top_item_passes(self):
        self.assertIsNone(self.run_on(CARD + block(needs=[SEND_BACKS])))
        # A reminder after the card: its question, the strip, and Next.
        self.assertIsNone(self.run_on("🟡 **Stop format send-backs?**\n\n1 of 2 need you · stop format send-backs · R153\n\n---\n\n**Next**\n\n"
                                      "- **`a` → yes: stop them** · *recommended*\n\n" + block(needs=[SEND_BACKS])))
        # Running work beside a Do at the top: a ⏳ line can carry it.
        self.write(PROJECT, ("do", "pull the Mac's dotfiles", "coordinator"))
        self.assertIsNone(self.run_on("⏳ **R151 is 20 min in**, then: report its PR.\n\n1 of 1 needs you · pull the "
                                      "Mac's dotfiles\n\n" + block("running", needs=[need(1, "pull the Mac's dotfiles",
                                                                                         "do")], elapsed="20 min")))

    def test_a_status_that_parks_the_calls_in_standing_goes_back(self):
        """The shape of the ◆ suite-audit replies before 'Anything else waiting for me?' on Nov 18."""
        status = "⏳ **#5965's round-four fixes are moving to a new PR, 3 min in**, then: watch it.\n\n"
        found = self.run_on(status + block("running", standing=[SEND_BACKS, need(1, "pull the Mac's dotfiles", "do")],
                                           elapsed="3 min"))
        self.assertIn("holds 2 items for the user, and your reply hides them: its `needs` leaves out the queue's top "
                      f"item, 2; no line the user sees carries the strip `1 of 2 need you · stop format send-backs · "
                      f"{WORKER}`.", found)
        self.assertIn('with `{"id":2,"kind":"decide","name":"stop format send-backs"}` in the turn block\'s `needs`',
                      found)
        self.assertIn(f"the strip `1 of 2 need you · stop format send-backs · {WORKER}`", found)
        self.assertIn(f"`{self.project_md.parent} queue done 2 --answer", found)
        done = "✅ **The re-review is on #75.**\n\n---\n\n**Done**. Two audit calls are queued.\n\n"
        self.assertIn("its `needs` leaves out", self.run_on(done + block("done", standing=[SEND_BACKS])))
        self.assertIn("its `needs` leaves out", self.run_on(block("running", elapsed="3 min")))  # a quiet wake

    def test_the_strip_counts_the_whole_queue_and_names_its_top_where_the_user_sees_it(self):
        named = "1 of 2 need you · stop format send-backs"
        for strip in ["1 of 3 need you · stop format send-backs", "1 of 2 need you · R153",
                      f"```text\n{named}\n```", f"<!--\n{named}\n-->", f"<!-- note --> x <!-- {named} -->",
                      f"<details><summary>Queue</summary>\n\n{named}\n\n</details>",
                      f"<details><summary>A</summary>\n\n<details><summary>B</summary>\n\nb\n\n</details>\n\n{named}"
                      "\n\n</details>", ""]:
            with self.subTest(strip=strip):
                reply = CARD.replace(f"1 of 2 need you · stop format send-backs · {WORKER}", strip)
                self.assertIn("no line the user sees carries the strip", self.run_on(reply + block(needs=[SEND_BACKS])))
        for strip in ["**1 of 2 needs you** · Stop Format Send-backs", f"<!-- note --> {named}",
                      f"<details><summary>A</summary>\n\nfolded\n\n</details>\n\n{named}"]:
            with self.subTest(strip=strip):
                reply = CARD.replace(f"1 of 2 need you · stop format send-backs · {WORKER}", strip)
                self.assertIsNone(self.run_on(reply + block(needs=[SEND_BACKS])))

    def test_an_item_under_a_queued_id_must_be_that_item(self):
        for wrong in [need(2, "delete all backups"), need(2, "stop format send-backs", "do")]:
            with self.subTest(need=wrong):
                found = self.run_on(CARD + block(needs=[wrong]))
                self.assertIn(f"its turn block's item 2 is {wrong['kind']} \"{wrong['name']}\", but the queue's is "
                              "decide \"stop format send-backs\"", found)
        self.write(PROJECT, ("stuck", "retry R151 or drop it", "R151"))
        stuck = need(1, "retry R151 or drop it")
        self.assertIsNone(self.run_on("🟡 **Retry R151?**\n\n1 of 1 needs you · retry R151 or drop it · R151\n\n"
                                      + block(needs=[stuck])))

    def test_an_item_the_queue_doesnt_hold_goes_back(self):
        found = self.run_on(CARD + block(needs=[SEND_BACKS], standing=[need(9, "reply to Ander about Fable writers",
                                                                             "review")]))
        self.assertIn('its turn block names review 9 "reply to Ander about Fable writers", which the queue doesn\'t '
                      "hold", found)
        self.write(PROJECT)  # no Queue section yet: the first call creates it
        found = self.run_on(CARD + block(needs=[SEND_BACKS]))
        self.assertIn("Every call or Do this thread puts to the user goes on its queue first", found)
        self.assertIn(f"`{self.project_md.parent} queue add <kind> \"<name>\"", found)
        self.assertIsNone(self.run_on("✅ **Nothing waits on you.**\n\n" + block("done")))

    def test_an_item_the_reply_before_named_reaches_the_queue_or_a_queue_done(self):
        """The first replies after the hook ships, in a project whose open calls lived in `standing`."""
        transcript = self.folder / f"{SESSION}.jsonl"
        before = "⏳ **R153 runs.**\n\n" + block("running", standing=[SEND_BACKS], elapsed="1 min")
        transcript.write_text("\n".join(json.dumps(entry) for entry in [
            {"type": "user", "message": {"content": "start R153"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": before}]}},
            {"type": "user", "message": {"content": "how is it going?"}}]) + "\n")
        dropped = 'the reply before named decide 2 "stop format send-backs", which the queue doesn\'t hold'
        quiet = "⏳ **R153 is 4 min in.**\n\n" + block("running", elapsed="4 min")
        self.write(PROJECT)  # no Queue section yet
        found = self.run_on(quiet, transcript_path=str(transcript))
        self.assertIn(dropped, found)
        self.assertIn("queue each one still open, in the order it arose", found)
        self.assertIsNone(self.run_on(quiet))  # no transcript to read: nothing carried
        # A new call queued first doesn't end the carry-over, and an id the queue reuses for
        # another item isn't the old call.
        self.write(PROJECT, ("do", "pull the Mac's dotfiles", "coordinator"), ("decide", "keep the v1 export", WORKER))
        shown = "🟡 **Pull the dotfiles?**\n\n1 of 2 need you · keep the v1 export\n\n"
        found = self.run_on(shown + block(needs=[need(2, "keep the v1 export")]), transcript_path=str(transcript))
        self.assertIn(dropped, found)
        self.assertIn("Queue each other item a reason names that's still open with `queue add`.", found)
        # Queued as that item, or closed with `queue done`, it's accounted for.
        self.write(PROJECT, ("do", "pull the Mac's dotfiles", "coordinator"), ("decide", "stop format send-backs", WORKER))
        self.assertIsNone(self.run_on(CARD.replace("1 of 2", "1 of 2") + block(needs=[SEND_BACKS]),
                                      transcript_path=str(transcript)))
        self.write(PROJECT.replace("## Decisions\n", "## Decisions\n\n- 2026-11-18 · R153 asked: stop format send-backs "
                                   "(queue 2, decide) → yes · the user: 'a'\n"))
        self.assertIsNone(self.run_on(quiet, transcript_path=str(transcript)))

    def test_an_empty_queue_lets_a_status_or_done_line_end_the_reply(self):
        lines = PROJECT.split("\n")
        project_queue.add(lines, "do", "pull the dotfiles", "coordinator")
        project_queue.done(lines, 1)
        self.project_md.write_text("\n".join(lines))
        self.assertIsNone(self.run_on("⏳ **R151 is 20 min in**, then: report its PR.\n\n" + block("running",
                                                                                                    elapsed="20 min")))
        self.assertIn("which the queue doesn't hold", self.run_on(CARD + block(needs=[SEND_BACKS])))

    def test_doubt_lets_the_reply_through(self):
        hidden = block("running", standing=[SEND_BACKS], elapsed="3 min")
        self.assertIsNotNone(self.run_on(hidden))
        self.assertIsNone(self.run_on(hidden, t3=False))
        self.assertIsNone(self.run_on(hidden, title="◇ audit · R153"))
        self.assertIsNone(self.run_on(hidden, title="◆ other-project"))
        self.assertIsNone(self.run_on(hidden, stop_hook_active=True))
        self.assertIsNone(self.run_on("⏳ no block"))
        self.assertIsNotNone(self.run_on(hidden, title="🟡 ◆ audit"))
        text = self.project_md.read_text()
        self.project_md.write_text(text.replace(LINK, "<t3-thread://v2/env-mac/thread-other>"))
        self.assertIsNone(self.run_on(hidden))
        self.project_md.write_text(text.replace("| 1 | do |", "| 1 | blocked |"))
        self.assertIsNone(self.run_on(hidden))


if __name__ == "__main__":
    unittest.main()
