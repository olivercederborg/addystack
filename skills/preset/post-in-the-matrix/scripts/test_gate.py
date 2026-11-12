"""Tests for gate.py: run `python3 -m unittest discover -s skills/preset/post-in-the-matrix/scripts`.

The gate may wake the check for nothing, but it must never sleep through a new request,
so most of these feed it a channel and check that the request wakes it."""
import io
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
    """slack(name, input) over a channel of pages and threads, counting thread reads. A
    thread given as a list is pages."""

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
        thread = self.threads[tool_input["message_ts"]]
        if isinstance(thread, str):
            return {"messages": thread}
        index = int(tool_input.get("cursor", "0"))
        info = f"use cursor: `{index + 1}`" if index + 1 < len(thread) else "There are no more messages in this thread."
        return {"messages": thread[index], "pagination_info": info}


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


def asks(reasons):
    """The message timestamps among a run's reasons to wake."""
    return sorted(r.split(":")[1] for r in reasons if r.startswith("msg:"))


class NewRequestsWake(unittest.TestCase):
    def setUp(self):
        self.old = channel_block(ts(100), TEAMMATE, "<@U0ME> review #12", replies=1, latest="a")
        self.threads = {ts(100): thread_text(ts(100), [(ts(99), ME, "approved · #12")])}
        self.state = {}
        check(FakeSlack([self.old], self.threads), self.state)

    def test_a_new_post_wakes(self):
        new = channel_block(ts(0.1), TEAMMATE, "<@U0ME> review #13")
        self.assertEqual(asks(check(FakeSlack([new + self.old], self.threads), self.state)), [ts(0.1)])

    def test_a_new_reply_under_an_old_parent_wakes(self):
        old = self.old.replace("Thread: 1 replies (latest: a)", "Thread: 2 replies (latest: b)")
        threads = {ts(100): thread_text(ts(100), [(ts(99), ME, "approved · #12"),
                                                   (ts(0.1), TEAMMATE, "<@U0ME> re-review #12")])}
        self.assertEqual(asks(check(FakeSlack([old], threads), self.state)), [ts(0.1)])

    def test_a_new_post_that_already_has_replies_wakes(self):
        new = channel_block(ts(0.2), TEAMMATE, "<@U0ME> review #13", replies=1, latest="c")
        threads = {**self.threads, ts(0.2): thread_text(ts(0.2), [(ts(0.1), TEAMMATE, "ci: green now")])}
        self.assertEqual(asks(check(FakeSlack([new + self.old], threads), self.state)), [ts(0.2), ts(0.1)])

    def test_a_reply_on_a_later_thread_page_wakes(self):
        parent = channel_block(ts(5), TEAMMATE, "stack is up", replies=101, latest="x")
        pages = [thread_text(ts(5), [(ts(4.5), ME, "approved")]),
                 f"--- Reply 101 of 101 ---\nFrom: Sam <sam@example.com> ({TEAMMATE})\n"
                 f"Message TS: {ts(0.1)}\n<@U0ME> re-review #13\n"]
        self.assertEqual(asks(check(FakeSlack([parent + self.old], {**self.threads, ts(5): pages}), self.state)),
                         [ts(5), ts(0.1)])

    def test_a_thread_line_in_the_text_or_a_preview_never_hides_the_reply_count(self):
        parent = channel_block(ts(5), TEAMMATE, "Thread: 0 replies\nThread: FYI", replies=1, latest="x")
        message = gate.parse_channel(parent)[0]
        self.assertEqual(message.replies, 1)
        preview = parent + "App notification from App (https://example.com):\nThread: 0 replies\n"
        self.assertEqual(gate.parse_channel(preview)[0].replies, 1)
        edited = parent.replace("Thread: FYI", "Thread: <@U0ME> review #13")
        self.assertNotEqual(gate.body_hash(message.text), gate.body_hash(gate.parse_channel(edited)[0].text))

    def test_a_request_on_a_later_page_wakes(self):
        new = channel_block(ts(0.1), TEAMMATE, "<@U0ME> review #13")
        self.assertEqual(asks(check(FakeSlack([self.old, new], self.threads), self.state)), [ts(0.1)])

    def test_a_post_without_a_user_id_still_wakes(self):
        bot = f"=== Message from Some App at 2027-01-15 10:00:00 CET === \nMessage TS: {ts(0.1)}\nreview #13\n\n"
        self.assertEqual(asks(check(FakeSlack([bot + self.old], self.threads), self.state)), [ts(0.1)])

    def test_an_fyi_edited_into_a_request_wakes(self):
        fyi = channel_block(ts(1), TEAMMATE, "fyi #13 is up")
        check(FakeSlack([fyi + self.old], self.threads), self.state)
        edited = channel_block(ts(1), TEAMMATE, "<@U0ME> review #13")
        self.assertEqual(asks(check(FakeSlack([edited + self.old], self.threads), self.state)), [ts(1)])

    def test_an_edited_young_reply_wakes_though_the_thread_looks_unchanged(self):
        parent = channel_block(ts(5), TEAMMATE, "stack is up", replies=1, latest="x")
        threads = {**self.threads, ts(5): thread_text(ts(5), [(ts(4), TEAMMATE, "fyi")])}
        check(FakeSlack([parent + self.old], threads), self.state)
        threads[ts(5)] = thread_text(ts(5), [(ts(4), TEAMMATE, "<@U0ME> re-review #13")])
        self.assertEqual(asks(check(FakeSlack([parent + self.old], threads), self.state)), [ts(4)])

    def test_a_new_reaction_sleeps(self):
        post = channel_block(ts(1), TEAMMATE, "<@U0ME> review #13")
        check(FakeSlack([post + self.old], self.threads), self.state)
        reacted = post.replace("Reactions: eyes (1)", "Reactions: eyes (1), lgtm (1)")
        self.assertEqual(check(FakeSlack([reacted + self.old], self.threads), self.state), [])

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
        return {12: {"state": state, "headRefOid": head,
                     "reviews": [{"state": r[0], "commit": r[1], "at": r[2] if len(r) > 2 else "t1"} for r in reviews]}}

    def wakes(self, before, after):
        state = {}
        current = gate.signals([], before, me=ME, now=NOW, ask_hours=72)
        state.update(seen=sorted(current), last_wake=NOW)
        return gate.decide(gate.signals([], after, me=ME, now=NOW, ask_hours=72), state, now=NOW, quiet_hours=24)

    def test_merge_wakes(self):
        self.assertEqual(self.wakes(self.pr(), self.pr("MERGED")), ["pr:12:MERGED"])

    def test_approval_wakes(self):
        self.assertEqual(self.wakes(self.pr(), self.pr("OPEN", "h1", ("APPROVED", "h1"))), ["pr:12:approved:h1:t1"])

    def test_approving_the_same_head_again_wakes(self):
        approved = self.pr("OPEN", "h1", ("APPROVED", "h1", "t1"))
        again = self.pr("OPEN", "h1", ("APPROVED", "h1", "t1"), ("CHANGES_REQUESTED", "h1", "t2"), ("APPROVED", "h1", "t3"))
        self.assertEqual(self.wakes(approved, again), ["pr:12:approved:h1:t3"])

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


class Tracking(unittest.TestCase):
    def test_an_open_pr_stays_watched_after_its_link_ages_out(self):
        state, asked = {}, []
        def lookup(states):
            def fetch(numbers):
                asked.append(sorted(numbers))
                return {n: {"state": states[n], "headRefOid": "h", "reviews": []} for n in numbers}
            return fetch
        gate.track({12}, state, lookup({12: "OPEN"}))
        prs = gate.track(set(), state, lookup({12: "MERGED"}))
        self.assertIn("pr:12:MERGED", gate.signals([], prs, me=ME, now=NOW, ask_hours=72))
        gate.track(set(), state, lookup({}))
        self.assertEqual(asked, [[12], [12], []])


class IncompleteReads(unittest.TestCase):
    """A read that came back partial fails, so it counts toward fail-open, and leaves
    what the gate watches as it was."""

    def test_a_slack_reply_without_messages_fails(self):
        with self.assertRaises(KeyError):
            gate.read_channel(lambda name, tool_input: {}, CONFIG, {}, NOW)

    def test_a_graphql_error_other_than_not_found_fails(self):
        reply = {"data": {"repository": {"p66": None}}, "errors": [{"type": "RATE_LIMITED", "message": "slow down"}]}
        done = subprocess.CompletedProcess(["gh"], 1, json.dumps(reply), "")
        with mock.patch.object(gate.subprocess, "run", return_value=done), self.assertRaises(RuntimeError):
            gate.pr_states({66}, {"repo": "o/r", "github_login": "me"})

    def test_a_number_that_isnt_a_pr_is_skipped(self):
        reply = {"data": {"repository": {"p3": None}}, "errors": [{"type": "NOT_FOUND", "message": "no PR"}]}
        done = subprocess.CompletedProcess(["gh"], 1, json.dumps(reply), "")
        with mock.patch.object(gate.subprocess, "run", return_value=done):
            self.assertEqual(gate.pr_states({3}, {"repo": "o/r", "github_login": "me"}), {})

    def test_a_watched_pr_the_lookup_missed_stays_watched(self):
        state = {"open": [66]}
        gate.track(set(), state, lambda numbers: {})
        self.assertEqual(state["open"], [66])


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
        with mock.patch.object(gate, "gather", side_effect=gathered if isinstance(gathered, BaseException) else None,
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

    def test_a_run_killed_mid_read_still_counts_toward_fail_open(self):
        with self.assertRaises(KeyboardInterrupt):  # what a kill leaves: no except ran
            self.run_gate(KeyboardInterrupt())
        self.assertEqual(json.loads(self.state_file.read_text())["last_ok"], NOW)
        with mock.patch.object(gate, "gather", return_value=set()), mock.patch.object(gate, "wake") as woke:
            gate.run(self.config, dry_run=False, now=NOW + 3700)
        self.assertTrue(woke.call_args_list[0].args[1][0].startswith("gate failing since"))

    def test_a_failed_wake_never_logs_the_url(self):
        error = ValueError("unknown url type: 'hooks.example/SECRET'")
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.run_gate({"msg:1"}, wake=error)
        self.assertIn("ValueError", err.getvalue())
        self.assertNotIn("SECRET", err.getvalue())

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


class LinearLinks(unittest.TestCase):
    def test_a_search_runs_again_hourly_and_keeps_earlier_hits(self):
        state, results = {}, iter([[{"number": 1}], [{"number": 2}]])
        with mock.patch.object(gate, "gh", side_effect=lambda *args: json.dumps(next(results))) as gh:
            self.assertEqual(gate.resolve_linear({"DEV-9"}, CONFIG, state, NOW), {1})
            self.assertEqual(gate.resolve_linear({"DEV-9"}, CONFIG, state, NOW + 600), {1})
            self.assertEqual(gate.resolve_linear({"DEV-9"}, CONFIG, state, NOW + 3600), {1, 2})
        self.assertEqual(gh.call_count, 2)


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
