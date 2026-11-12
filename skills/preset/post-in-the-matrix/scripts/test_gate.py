"""Tests for gate.py: run `python3 -m unittest discover -s skills/preset/post-in-the-matrix/scripts`.

The gate may wake the check for nothing, but it must never sleep through a new request,
so most of these feed it a channel and check that the request wakes it."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gate  # noqa: E402

ME, TEAMMATE = "U0ME", "U0MATE"
REPO = "acme/app"
NOW = 1_800_000_000.0
CONFIG = {**gate.DEFAULTS, "channel": "C1", "repo": REPO}


def channel_block(ts, user, text, replies=0, latest=""):
    thread = f"Thread: {replies} replies (latest: {latest})\n" if replies else ""
    return (f"=== Message from Sam <sam@example.com> ({user}) at 2027-01-15 10:00:00 CET === \n"
            f"Message TS: {ts}\n{text}\n{thread}Reactions: eyes (1)\n\n")


def thread_text(parent_ts, replies):
    out = (f"=== THREAD PARENT MESSAGE ===\nFrom: Sam <sam@example.com> ({TEAMMATE})\n"
           f"Time: 2027-01-01 10:00:00 CET\nMessage TS: {parent_ts}\nparent\n\n"
           f"=== THREAD REPLIES ({len(replies)} total) ===\n\n")
    for i, (ts, user, text) in enumerate(replies, 1):
        out += (f"--- Reply {i} of {len(replies)} ---\nFrom: Sam <sam@example.com> ({user})\n"
                f"Time: 2027-01-15 10:00:00 CET\nMessage TS: {ts}\n{text}\n")
    return out


class FakeSlack:
    """slack(name, input) over a channel of pages and threads, counting thread reads."""

    def __init__(self, pages, threads=None):
        self.pages, self.threads, self.thread_reads = pages, threads or {}, []

    def __call__(self, name, tool_input):
        if name == "slack_read_channel":
            index = int(tool_input.get("cursor", "0"))
            more = index + 1 < len(self.pages)
            info = f"There are more messages available. To view the next page, use cursor: `{index + 1}`" \
                if more else "There are no more messages available."
            return {"messages": "Channel: #c (C1)\n\n" + self.pages[index], "pagination_info": info}
        self.thread_reads.append(tool_input["message_ts"])
        return {"messages": self.threads[tool_input["message_ts"]]}


def check(slack, state, prs=None, now=NOW):
    """One gate run on a fake channel: the reasons to wake, with state updated as run() does."""
    messages = gate.read_channel(slack, CONFIG, state, now)
    current = gate.signals(messages, prs or {}, me=ME, now=now, ask_hours=CONFIG["ask_hours"])
    reasons = gate.decide(current, state, now=now, quiet_hours=CONFIG["quiet_hours"])
    if reasons:
        state["last_wake"] = now
    state["seen"] = sorted(current)
    return reasons


def ts(hours_ago):
    return f"{NOW - hours_ago * 3600:.6f}"


class NewRequestsWake(unittest.TestCase):
    def setUp(self):
        self.old = channel_block(ts(48), TEAMMATE, "<@U0ME> review #12", replies=1, latest="a")
        self.threads = {ts(48): thread_text(ts(48), [(ts(47), ME, "approved · #12")])}
        self.state = {}
        check(FakeSlack([self.old], self.threads), self.state)

    def test_a_new_post_wakes(self):
        new = channel_block(ts(0.1), TEAMMATE, "<@U0ME> review #13")
        self.assertIn(f"msg:{ts(0.1)}", check(FakeSlack([new + self.old], self.threads), self.state, now=NOW))

    def test_a_new_reply_under_an_old_parent_wakes(self):
        old = self.old.replace("Thread: 1 replies (latest: a)", "Thread: 2 replies (latest: b)")
        threads = {ts(48): thread_text(ts(48), [(ts(47), ME, "approved · #12"),
                                                 (ts(0.1), TEAMMATE, "<@U0ME> re-review #12")])}
        self.assertEqual(check(FakeSlack([old], threads), self.state), [f"msg:{ts(0.1)}"])

    def test_a_new_post_that_already_has_replies_wakes(self):
        new = channel_block(ts(0.2), TEAMMATE, "<@U0ME> review #13", replies=1, latest="c")
        threads = {**self.threads, ts(0.2): thread_text(ts(0.2), [(ts(0.1), TEAMMATE, "ci: green now")])}
        self.assertEqual(check(FakeSlack([new + self.old], threads), self.state), sorted([f"msg:{ts(0.1)}", f"msg:{ts(0.2)}"]))

    def test_a_request_on_a_later_page_wakes(self):
        new = channel_block(ts(0.1), TEAMMATE, "<@U0ME> review #13")
        self.assertIn(f"msg:{ts(0.1)}", check(FakeSlack([self.old, new], self.threads), self.state))

    def test_a_post_without_a_user_id_still_wakes(self):
        bot = f"=== Message from Some App at 2027-01-15 10:00:00 CET === \nMessage TS: {ts(0.1)}\nreview #13\n\n"
        self.assertIn(f"msg:{ts(0.1)}", check(FakeSlack([bot + self.old], self.threads), self.state))

    def test_nothing_new_sleeps_and_reads_no_thread_again(self):
        slack = FakeSlack([self.old], self.threads)
        self.assertEqual(check(slack, self.state), [])
        self.assertEqual(slack.thread_reads, [])

    def test_your_own_post_sleeps(self):
        mine = channel_block(ts(0.1), ME, "<@U0MATE> review #14")
        self.assertEqual(check(FakeSlack([mine + self.old], self.threads), self.state), [])

    def test_a_post_older_than_the_ask_window_sleeps(self):
        stale = channel_block(ts(80), TEAMMATE, "<@U0ME> review #9")
        self.assertEqual(check(FakeSlack([self.old + stale], self.threads), self.state), [])


class PullRequestChangesWake(unittest.TestCase):
    def pr(self, state="OPEN", head="h1", *reviews):
        return {12: {"state": state, "headRefOid": head, "reviews": [{"state": s, "commit": c} for s, c in reviews]}}

    def wakes(self, before, after):
        state = {}
        current = gate.signals([], before, me=ME, now=NOW, ask_hours=72)
        state.update(seen=sorted(current), last_wake=NOW)
        return gate.decide(gate.signals([], after, me=ME, now=NOW, ask_hours=72), state, now=NOW, quiet_hours=24)

    def test_merge_wakes(self):
        self.assertEqual(self.wakes(self.pr(), self.pr("MERGED")), ["pr:12:MERGED"])

    def test_approval_wakes(self):
        self.assertEqual(self.wakes(self.pr(), self.pr("OPEN", "h1", ("APPROVED", "h1"))), ["pr:12:approved:h1"])

    def test_dismissal_and_each_new_head_while_dismissed_wake(self):
        approved = self.pr("OPEN", "h1", ("APPROVED", "h1"))
        dismissed = self.pr("OPEN", "h2", ("DISMISSED", "h1"))
        self.assertEqual(self.wakes(approved, dismissed), ["pr:12:dismissed:h1:head:h2"])
        self.assertEqual(self.wakes(dismissed, self.pr("OPEN", "h3", ("DISMISSED", "h1"))),
                         ["pr:12:dismissed:h1:head:h3"])

    def test_a_comment_review_or_a_push_while_approved_sleeps(self):
        approved = self.pr("OPEN", "h1", ("APPROVED", "h1"))
        self.assertEqual(self.wakes(approved, self.pr("OPEN", "h1", ("APPROVED", "h1"), ("COMMENTED", "h1"))), [])
        self.assertEqual(self.wakes(approved, self.pr("OPEN", "h2", ("APPROVED", "h1"))), [])


class Backstops(unittest.TestCase):
    def test_quiet_hours_wake_once_nothing_else_has(self):
        state = {"seen": [], "last_wake": NOW - 3 * 3600}
        self.assertEqual(len(gate.decide(set(), state, now=NOW, quiet_hours=2)), 1)
        self.assertEqual(gate.decide(set(), {"seen": [], "last_wake": NOW - 3600}, now=NOW, quiet_hours=2), [])

    def test_fail_open_on_every_run_once_failing_for_the_window(self):
        self.assertFalse(gate.fail_open({"last_ok": NOW - 600, "last_wake": NOW - 9999}, now=NOW, minutes=60))
        self.assertTrue(gate.fail_open({"last_ok": NOW - 3700, "last_wake": NOW - 3700}, now=NOW, minutes=60))
        self.assertTrue(gate.fail_open({"last_ok": NOW - 9999, "last_wake": NOW - 300}, now=NOW, minutes=60))


class Run(unittest.TestCase):
    """run() wakes, records what it saw only once the wake went out, and fails open."""

    def setUp(self):
        folder = pathlib.Path(tempfile.mkdtemp())
        self.state_file = folder / "state.json"
        self.config = {**CONFIG, "state_file": str(self.state_file)}

    def run_gate(self, gathered, wake=None):
        with mock.patch.object(gate, "gather", side_effect=gathered if isinstance(gathered, Exception) else None,
                               return_value=gathered), \
                mock.patch.object(gate, "wake", side_effect=wake) as woke:
            code = gate.run(self.config, dry_run=False, now=NOW)
        state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        return code, woke.call_args_list, state

    def test_a_failed_wake_keeps_the_request_new(self):
        code, _, state = self.run_gate({"msg:1"}, wake=OSError("relay down"))
        self.assertEqual(code, 1)
        self.assertNotIn("msg:1", state.get("seen", []))
        code, calls, state = self.run_gate({"msg:1"})
        self.assertEqual((code, calls[0].args[1], state["seen"]), (0, ["msg:1"], ["msg:1"]))

    def test_any_failing_read_wakes_the_check_after_the_window(self):
        failures = [RuntimeError("Executor down"), subprocess.TimeoutExpired("gh", 120), IndexError("no content")]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.state_file.write_text(json.dumps({"last_ok": NOW - 7200, "last_wake": NOW - 7200, "seen": []}))
                code, calls, state = self.run_gate(failure)
                self.assertEqual((code, len(calls), state["last_wake"]), (1, 1, NOW))


class WakeId(unittest.TestCase):
    """T3 drops a repeated wakeId for days, so only a retried POST may repeat one."""

    def ids(self, *wakes):
        hook = pathlib.Path(tempfile.mkdtemp()) / "hook"
        hook.write_text("https://hooks.example/x\n")
        sent = []
        response = mock.MagicMock(status=202)
        response.__enter__.return_value = response
        with mock.patch.object(gate.urllib.request, "urlopen",
                               side_effect=lambda request, timeout: sent.append(json.loads(request.data)) or response):
            for reasons, last_wake in wakes:
                gate.wake({"webhook_url_file": str(hook)}, reasons, last_wake)
        return [body["wakeId"] for body in sent]

    def test_the_next_quiet_wake_gets_a_new_id(self):
        quiet = ["quiet: no wake for 24 hours"]
        first, second = self.ids((quiet, NOW - 86400), (quiet, NOW))
        self.assertNotEqual(first, second)

    def test_a_retried_wake_keeps_its_id(self):
        first, retry = self.ids((["msg:1"], NOW), (["msg:1"], NOW))
        self.assertEqual(first, retry)


class Naming(unittest.TestCase):
    def test_pr_numbers(self):
        text = ("<https://github.com/acme/app/pull/101|#101 Fix> and "
                "https://app.graphite.com/github/pr/acme/app/102 and #103, not <#C0CHAN> "
                "or https://github.com/other/repo/pull/104 or &#39;")
        self.assertEqual(gate.pr_numbers(text, REPO), {101, 102, 103})

    def test_linear_keys(self):
        text = ("<https://linear.app/acme/review/dev-12-fix-it-abc|DEV-12> "
                "<https://linear.app/acme/review/fix-the-thing-abc|Fix the user&#39;s thing> "
                "<https://linear.app/acme/review/other-abc|#105>")
        self.assertEqual(gate.linear_keys(text), {"DEV-12", "Fix the user's thing"})


if __name__ == "__main__":
    unittest.main()
