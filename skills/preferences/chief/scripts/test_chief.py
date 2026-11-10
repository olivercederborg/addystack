"""Tests for inbox.py and projects.py: run `python3 skills/preferences/chief/scripts/test_chief.py`."""
import json, os, subprocess, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# The kit's hooks, from this checkout's addystack skill.
sys.path.insert(1, str(HERE.parents[3] / "skills" / "primitive" / "addystack" / "hooks"))
import inbox as chief, projects, snooze  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402
import bare_references, reply_budget, turn_block  # noqa: E402

DEVBOX = "8ef1f244-6d9b-47af-addf-af15ee5f56ee"
MAC = "0c5f5b0f-2c19-43e6-8a82-8fe66c1580b9"
NOW = datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc)


def iso(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def listed(id, title, status="completed", env=MAC, by="user", hours=1, prs=(), items=40):
    return {"env": env, "id": id, "title": title, "status": status, "createdBy": by,
            "updatedAt": iso(hours), "itemCount": items, "prs": list(prs)}


def block(state, needs=(), eta=None, options=()):
    value = {"state": state, "needs": [{"id": n, "kind": kind, "name": name} for n, (kind, name) in
                                       enumerate(needs, 1)],
             "options": [{"key": key, "class": cls, "text": text} for key, cls, text in options]}
    if state == "running":
        value.update(elapsed="1 min", **({"eta": eta} if eta else {}))
    return f"<!-- turn {json.dumps(value)} -->"


def read(item, turn=None, hours=None, worker_of=None, pending=0, last_user=None, headline="A reply"):
    found = {"env": item["env"], "id": item["id"], "updatedAt": item["updatedAt"], "turn": turn,
             "replyAt": iso(hours if hours is not None else 1), "headline": headline, "pending": pending,
             "runCompletedAt": iso(hours if hours is not None else 1),
             "lastUserAt": iso(last_user) if last_user is not None else None}
    if worker_of is not None:
        found["workerOf"] = worker_of
    return found


def page(threads, reads, prs=(), digests=()):
    cache = chief.merge({}, reads)
    return chief.build(threads, cache, list(digests), list(prs), NOW)


def pr(number, review=None, checks="SUCCESS", reviewers=0, reviewed=False, draft=False, hours=30):
    return {"repo": "hifranklin-tech/franklin-next", "number": number, "title": f"PR {number}", "draft": draft,
            "url": f"https://github.com/hifranklin-tech/franklin-next/pull/{number}", "createdAt": iso(hours),
            "updatedAt": iso(hours), "review": review, "mergeable": "MERGEABLE", "reviewers": reviewers,
            "reviewed": reviewed, "approvedAt": iso(hours) if review == "APPROVED" else None, "checks": checks,
            "readyAt": None}


class Plan(unittest.TestCase):
    def test_reads_only_idle_threads_that_changed(self):
        idle = listed("a", "Export fix")
        busy = listed("b", "Busy", status="running")
        cached = listed("c", "Seen before")
        own = listed("d", "chief")
        cache = {chief.key(MAC, "c"): {"updatedAt": cached["updatedAt"], "turn": None}}
        reads = chief.plan([idle, busy, cached, own], cache)
        self.assertEqual([(read["threadId"], "tail" in read) for read in reads], [("a", True), ("b", False)])
        self.assertEqual(reads[0]["tail"]["afterPosition"], 40 - chief.TAIL)
        self.assertNotIn("first", reads[0])

    def test_agent_made_threads_get_one_first_message_read(self):
        worker = listed("thread:delegated-task:x", "chief: inbox", by="agent", hours=2)
        cache = {chief.key(MAC, worker["id"]): {"updatedAt": worker["updatedAt"], "turn": None}}
        reads = chief.plan([worker], cache)
        self.assertEqual(len(reads), 1)
        self.assertIn("first", reads[0])
        self.assertNotIn("tail", reads[0])
        chief.merge(cache, [{"env": MAC, "id": worker["id"], "workerOf": None}])
        self.assertEqual(chief.plan([worker], cache), [])


    def test_caps_tail_reads_newest_first(self):
        many = [listed(f"t{n}", f"Thread {n}", hours=n + 1) for n in range(chief.TAILS + 5)]
        reads = chief.plan(many, {})
        self.assertEqual(len(reads), chief.TAILS)
        self.assertEqual(reads[0]["threadId"], "t0")


class Merge(unittest.TestCase):
    def test_turn_blocks_go_through_the_checker(self):
        item = listed("a", "Export fix")
        good = chief.merge({}, [read(item, block("stop", [("decide", "which export fix")]))])
        self.assertEqual(good[chief.key(MAC, "a")]["turn"]["needs"][0]["name"], "which export fix")
        bad = chief.merge({}, [read(item, '<!-- turn {"state":"stop","needs":[],"options":[]} -->')])
        self.assertIsNone(bad[chief.key(MAC, "a")]["turn"])

    def test_worker_of_keeps_the_coordinator_key(self):
        item = listed("w", "worker", by="agent")
        cache = chief.merge({}, [{"env": MAC, "id": item["id"], "workerOf": f"t3-thread://v2/{DEVBOX}/coord"}])
        self.assertEqual(cache[chief.key(MAC, "w")]["workerOf"], chief.key(DEVBOX, "coord"))


class Rows(unittest.TestCase):
    def rows(self, threads, reads, prs=(), digests=()):
        cache = chief.merge({}, reads)
        found = chief.thread_rows(chief.threads_from(threads, cache), chief.project_index(list(digests)), NOW)
        return found

    def test_a_stop_on_olivers_thread_is_a_call_flagged_after_a_day(self):
        item = listed("a", "Export fix", hours=30)
        rows = self.rows([item], [read(item, block("stop", [("decide", "which export fix")]), hours=30)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].what, "Decide: which export fix")
        self.assertEqual(rows[0].flags, ["over a day"])

    def test_a_workers_stop_is_its_coordinators_not_olivers(self):
        coordinator = listed("coord", "◆ export", env=DEVBOX, hours=0.1)
        worker = listed("w", "export: adapter", by="agent", hours=2)
        reads = [read(coordinator, block("done"), hours=0.1),
                 read(worker, block("stop", [("decide", "which adapter")]), hours=2,
                      worker_of=f"t3-thread://v2/{DEVBOX}/coord")]
        self.assertEqual(self.rows([coordinator, worker], reads), [])

    def test_a_workers_pending_request_is_olivers(self):
        worker = listed("w", "export: adapter", by="agent")
        rows = self.rows([worker], [read(worker, block("stop", [("decide", "which adapter")]), pending=1,
                                         worker_of=f"t3-thread://v2/{DEVBOX}/coord")])
        self.assertEqual([row.kind for row in rows], ["do"])

    def test_a_quiet_coordinator_with_unread_workers_is_flagged(self):
        coordinator = listed("coord", "◆ release-order", env=DEVBOX, hours=5)
        worker = listed("w", "release-order: notes", by="agent", hours=3)
        reads = [read(coordinator, block("done"), hours=5),
                 read(worker, block("done"), hours=3, worker_of=f"t3-thread://v2/{DEVBOX}/coord")]
        rows = self.rows([coordinator, worker], reads)
        self.assertEqual([row.flags for row in rows], [["quiet coordinator"]])
        self.assertIn("release-order: notes", rows[0].what)

    def test_a_coordinator_that_already_read_its_worker_is_quiet_for_good_reason(self):
        coordinator = listed("coord", "◆ release-order", env=DEVBOX, hours=1)
        worker = listed("w", "release-order: notes", by="agent", hours=3)
        reads = [read(coordinator, block("done"), hours=1),
                 read(worker, block("stop", [("decide", "the notes")]), hours=3,
                      worker_of=f"t3-thread://v2/{DEVBOX}/coord")]
        self.assertEqual(self.rows([coordinator, worker], reads), [])

    def test_a_coordinators_call_holds_its_unread_workers(self):
        coordinator = listed("coord", "◆ release-order", env=DEVBOX, hours=5)
        worker = listed("w", "release-order: notes", by="agent", hours=3)
        reads = [read(coordinator, block("stop", [("decide", "release order")]), hours=5),
                 read(worker, block("done"), hours=3, worker_of=f"t3-thread://v2/{DEVBOX}/coord")]
        rows = self.rows([coordinator, worker], reads)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].blocks, 2)
        self.assertIn("1 worker reply unread", rows[0].flags)

    def test_project_md_waiting_rows_count_as_held(self):
        coordinator = listed("coord", "◆ dinero", env=DEVBOX, hours=5)
        digest = ("devbox", {"projects": [{"project": "dinero", "coordinator": f"t3-thread://v2/{DEVBOX}/coord",
                                           "workers": [{"worker": "adapter", "thread": None,
                                                        "state": "waiting", "waits": "Oliver: push go"}]}]})
        rows = self.rows([coordinator], [read(coordinator, block("stop", [("review", "the push")]), hours=5)],
                         digests=[digest])
        self.assertEqual(rows[0].blocks, 2)

    def test_a_running_block_past_its_eta_never_rewoken_is_flagged(self):
        worker = listed("w", "suite-audit: replay", by="agent", hours=6)
        coordinator = listed("coord", "◆ suite-audit", env=DEVBOX, status="running")
        reads = [read(worker, block("running", eta="10 min"), hours=6, headline="⏳ **CI on #12, about 10 left**",
                      worker_of=f"t3-thread://v2/{DEVBOX}/coord")]
        rows = self.rows([worker, coordinator], reads)
        self.assertEqual([row.flags for row in rows], [["never re-woken"]])
        self.assertEqual(rows[0].blocks, 2)
        self.assertTrue(rows[0].what.startswith("Never re-woken: said ⏳ CI on #12, about 10 left"))

    def test_a_running_block_within_its_eta_or_answered_is_fine(self):
        early = listed("e", "Early", hours=0.05)
        answered = listed("a", "Answered", hours=6)
        reads = [read(early, block("running", eta="10 min"), hours=0.05),
                 read(answered, block("running", eta="10 min"), hours=6, last_user=5)]
        self.assertEqual(self.rows([early, answered], reads), [])

    def test_a_running_block_with_no_measured_eta_is_flagged_after_an_hour(self):
        """With no eta, as when nothing measured time left, the flag waits an hour, past 99% of wakes."""
        quiet = listed("q", "Quiet", hours=2)
        reads = [read(quiet, block("running"), hours=2, headline="⏳ **CI on #12, 6 min in**")]
        self.assertEqual([row.flags for row in self.rows([quiet], reads)], [["never re-woken"]])
        for no_time in (None, "after CI"):
            with self.subTest(eta=no_time):
                recent = listed("r", "Recent", hours=0.5)
                self.assertEqual(self.rows([recent], [read(recent, block("running", eta=no_time), hours=0.5)]), [])

    def test_a_request_mid_run_is_a_call(self):
        busy = listed("b", "Export fix", status="running")
        self.assertIn("status", chief.plan([busy], {})[0])
        stale = read(busy, block("stop", [("decide", "an old call")]), pending=0)
        now = {"env": MAC, "id": "b", "updatedAt": busy["updatedAt"], "activePending": 1}
        rows = self.rows([busy], [stale, now])
        self.assertEqual([(row.kind, row.what) for row in rows], [("do", "Answer its pending question or approval in T3")])
        self.assertEqual(self.rows([busy], [stale, dict(now, activePending=0)]), [])

    def test_children_and_settled_kinds_never_show(self):
        child = listed("thread:delegated-task:c", "child", by="agent")
        reads = [read(child, block("stop", [("decide", "child call")]), worker_of="")]
        self.assertEqual(self.rows([child], reads), [])


class PullRequests(unittest.TestCase):
    def test_merge_ready_and_no_reviewer_rows(self):
        rows = chief.pr_rows([pr(1, review="APPROVED"), pr(2), pr(3, draft=True), pr(4, reviewers=1),
                              pr(5, review="APPROVED", checks="FAILURE", reviewed=True)], [], {}, NOW)
        self.assertEqual([(row.kind, row.title) for row in rows],
                         [("merge", "franklin-next #1"), ("flag", "franklin-next #2")])

    def test_a_bot_review_is_no_reviewer(self):
        node = {"number": 5527, "title": "t", "url": "u", "isDraft": False, "createdAt": iso(30), "updatedAt": iso(1),
                "reviewDecision": "REVIEW_REQUIRED", "mergeable": "MERGEABLE",
                "repository": {"nameWithOwner": "hifranklin-tech/franklin-next", "owner": {"__typename": "Organization"}}, "reviewRequests": {"totalCount": 0},
                "latestReviews": {"nodes": [{"state": "COMMENTED", "submittedAt": iso(29),
                                             "author": {"__typename": "Bot"}}]},
                "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
                "timelineItems": {"nodes": []}}
        self.assertFalse(chief.read_pr(node)["reviewed"])
        rows = chief.pr_rows([chief.read_pr(node)], [], {}, NOW)
        self.assertEqual([row.flags for row in rows], [["no reviewer"]])

    def test_a_pr_whose_thread_already_asks_is_left_to_that_thread(self):
        item = listed("a", "Export fix", prs=[{"repo": "hifranklin-tech/franklin-next", "number": 2,
                                               "state": "open"}, {"repo": "hifranklin-tech/franklin-next",
                                                                  "number": 3, "state": "open"}])
        threads = chief.threads_from([item], {})
        rows = chief.pr_rows([pr(2), pr(3)], threads, {chief.key(MAC, "a"): "Do: request reviewers on #2"}, NOW)
        self.assertEqual([row.title for row in rows], ["franklin-next #3"])

    def test_a_solo_repo_has_no_one_to_ask(self):
        solo = dict(pr(9), team=False)
        self.assertEqual(chief.pr_rows([solo], [], {}, NOW), [])


class Card(unittest.TestCase):
    def full_card(self):
        threads = [listed("a", "Export fix", hours=30), listed("b", "Search speed", env=DEVBOX, hours=2),
                   listed("coord", "◆ release-order", env=DEVBOX, hours=5),
                   listed("w", "release-order: notes", by="agent", hours=3)]
        reads = [read(threads[0], block("stop", [("decide", "which export fix")]), hours=30),
                 read(threads[1], block("stop", [("review", "the index migration")]), hours=2),
                 read(threads[2], block("done"), hours=5),
                 read(threads[3], block("done"), hours=3, worker_of=f"t3-thread://v2/{DEVBOX}/coord")]
        return page(threads, reads, prs=[pr(7)])

    def test_ranks_by_blocker_hours(self):
        text = self.full_card()
        table = [line for line in text.splitlines() if line.startswith("| ") and line[2].isdigit()]
        order = [line.split("|")[2] for line in table]
        self.assertIn("Export fix", order[0])
        self.assertIn("release-order", order[1])
        self.assertIn("Search speed", order[2])
        self.assertIn("franklin-next #7", order[3])

    def test_card_passes_the_reply_hooks(self):
        text = self.full_card()
        turn = turn_block.parse(text)
        self.assertEqual(turn.state, "stop")
        self.assertEqual(len(turn.needs), 4)
        self.assertEqual(reply_budget.unplain(text), [])
        self.assertEqual(bare_references.problems(text), [])
        self.assertIn("<t3-thread://v2/", text)

    def test_an_empty_inbox_is_done(self):
        text = page([], [])
        self.assertTrue(text.startswith("✅"))
        self.assertEqual(turn_block.parse(text).state, "done")


class Record(unittest.TestCase):
    def setUp(self):
        self.threads = [listed("a", "Export fix", hours=30, prs=[{"repo": "hifranklin-tech/franklin-next",
                                                                  "number": 7, "state": "open"}]),
                        listed("w", "export: adapter", by="agent", hours=1)]
        self.reads = [read(self.threads[0], block("stop", [("decide", "which export fix")]), hours=30),
                      read(self.threads[1], block("stop", [("decide", "x")]), pending=1,
                           worker_of=f"t3-thread://v2/{DEVBOX}/coord")]
        self.runs = []

    def build(self, reply):
        def record(run):
            self.runs.append(run)
            return reply
        cache = chief.merge({}, self.reads)
        return chief.build(self.threads, cache, [], [pr(9)], NOW, record=record)

    def test_rows_map_to_needs_in_rank_order(self):
        text = self.build("Recorded in Executor as run_x.")
        run = self.runs[0]
        self.assertEqual(run["state"], "stop")
        self.assertEqual(run["headline"], text.split("\n", 1)[0].replace("**", ""))
        self.assertEqual(run["readAt"], "2026-11-02T20:00:00Z")
        first = run["needs"][0]
        self.assertEqual(first["objectId"], f"t3-thread://v2/{MAC}/a")
        self.assertEqual((first["kind"], first["what"], first["holds"], first["since"]),
                         ("decide", "Decide: which export fix", 1, "2026-11-01T14:00:00Z"))
        self.assertEqual(first["related"], ["https://github.com/hifranklin-tech/franklin-next/pull/7"])
        worker = run["needs"][1]
        self.assertEqual(worker["related"], [f"t3-thread://v2/{DEVBOX}/coord"])
        self.assertEqual(run["needs"][-1]["objectId"], "https://github.com/hifranklin-tech/franklin-next/pull/9")
        self.assertTrue(run["needs"][-1]["pr"])
        self.assertEqual([need["title"] for need in run["needs"]],
                         [line.split("](")[0].split("[", 1)[1] for line in text.splitlines()
                          if line.startswith("| ") and line[2].isdigit()])
        self.assertIn("- Recorded in Executor as run_x.", text)
        turn_block.parse(text)

    def test_a_failed_record_still_prints_the_card(self):
        with tempfile.TemporaryDirectory() as folder:
            cases = {"exit 1": "echo 'AppProviderFailed (HTTP 502)' >&2; exit 1",
                     "garbage": "echo not-json", "ok": "cat >/dev/null; echo '{\"runId\":\"run_1\"}'"}
            lines = {}
            for name, body in cases.items():
                script = Path(folder, name.replace(" ", "-"))
                script.write_text(f"#!/bin/sh\n{body}\n")
                script.chmod(0o755)
                cache = chief.merge({}, self.reads)
                text = chief.build(self.threads, cache, [], [], NOW, record=chief.record_with(str(script)))
                turn_block.parse(text)
                lines[name] = [line for line in text.splitlines() if "Executor" in line]
            missing = chief.record_with(str(Path(folder, "absent")))({"needs": []})
        self.assertEqual(lines["exit 1"], ["- Not recorded in Executor: AppProviderFailed (HTTP 502)."])
        self.assertTrue(lines["garbage"][0].startswith("- Not recorded in Executor: unreadable reply"))
        self.assertEqual(lines["ok"], ["- Recorded in Executor as run_1."])
        self.assertTrue(missing.startswith("Not recorded in Executor:"))


OPTIONS = (("a", "routine", "yes: fix the currency column"), ("b", "decision", "no: leave it"),
           ("c", "stop:merge", "merge #12"))


class Fixes(unittest.TestCase):
    def test_headline_leads_with_the_oldest_call_not_a_stale_pr(self):
        rows = [chief.Row("decide", "🟡 ◆ ci-speed", "t3-thread://v2/e/a", "devbox", "Decide: x", NOW - timedelta(hours=29)),
                chief.Row("decide", "Other", "t3-thread://v2/e/b", "Mac", "Decide: y", NOW - timedelta(hours=2)),
                chief.Row("flag", "franklin-next #1", "https://github.com/o/r/pull/1", "GitHub", "No reviewer",
                          NOW - timedelta(days=32), pr=True)]
        self.assertEqual(chief.headline(rows, NOW), "🟡 **2 calls wait on you, plus 1 PR; ci-speed for 29 h.**")
        self.assertEqual(chief.headline(rows[2:], NOW), "🟡 **1 PR waits on you; the oldest for 32 d.**")

    def test_closing_line_says_how_to_answer(self):
        text = page([], [])
        self.assertIn('"<rank or name>: <answer>"', text)
        self.assertIn('"<rank or name>: snooze <when>"', text)
        self.assertNotIn("only reads", text)

    def test_failure_keeps_the_reason(self):
        trace = ("node:fs:483\n  return binding.readFileUtf8(path, stringToFlags(options.flag));\n  ^\n\n"
                 "Error: ENOENT: no such file or directory, open '/home/oliver/.config/executor/api-key'\n"
                 "    at Object.readFileSync (node:fs:483:20)\n")
        self.assertTrue(chief.failure(trace).startswith("Error: ENOENT: no such file or directory"))
        self.assertEqual(chief.failure('{\n  "kind": "ToolFailure",\n  "message": "AppProviderFailed (HTTP 502)"\n}'),
                         "AppProviderFailed (HTTP 502).")
        self.assertFalse(chief.failure("x" * 300).endswith("…."))

    def test_plain_keeps_a_leading_hash_or_backtick(self):
        self.assertEqual(chief.plain("⏳ **#5533 green**"), "#5533 green")
        self.assertEqual(chief.plain("⏳ `inbox.py` runs"), "`inbox.py` runs")


class Options(unittest.TestCase):
    def test_a_calls_options_go_to_record_run(self):
        item = listed("a", "Export fix", hours=3)
        runs = []
        cache = chief.merge({}, [read(item, block("stop", [("decide", "which fix")], options=OPTIONS), hours=3)])
        chief.build([item], cache, [], [], NOW, record=lambda run: runs.append(run) or "ok")
        self.assertEqual(runs[0]["needs"][0]["options"],
                         [{"key": key, "class": cls, "text": text} for key, cls, text in OPTIONS])

    def test_turns_cached_before_options_are_read_again_once(self):
        item = listed("a", "Export fix")
        old = {chief.key(MAC, "a"): {"updatedAt": item["updatedAt"], "turn": {"state": "stop", "needs": []}}}
        self.assertEqual(len(chief.plan([item], old)), 1)
        new = chief.merge({}, [read(item, block("stop", [("decide", "x")]))])
        self.assertEqual(chief.plan([item], new), [])


class Relay(unittest.TestCase):
    needs = [{"rank": 1, "objectId": f"t3-thread://v2/{DEVBOX}/coord", "title": "🟡 ◆ ci-speed",
              "options": [{"key": key, "class": cls, "text": text} for key, cls, text in OPTIONS]},
             {"rank": 2, "objectId": f"t3-thread://v2/{MAC}/disk", "title": "Free Up Disk Space on Mac", "options": []},
             {"rank": 3, "objectId": "https://github.com/o/r/pull/9", "title": "franklin-next #9", "options": []},
             {"rank": 4, "objectId": f"t3-thread://v2/{MAC}/w", "title": "chief: inbox", "options": []}]

    def test_sends_oliver_s_words_verbatim_under_one_prefix(self):
        plans = chief.relay_plan([{"id": "ans_1", "objectId": self.needs[0]["objectId"], "key": "b", "text": "b"},
                                  {"id": "ans_2", "objectId": self.needs[1]["objectId"],
                                   "text": "done, freed 40 GB\n  and ran t3 doctor"}], self.needs)
        self.assertEqual(plans[0], {"kind": "answer", "answerId": "ans_1", "environmentId": DEVBOX, "threadId": "coord",
                                    "text": "b",
                                    "message": "Oliver answered via chief:\nb\n\n(b: no: leave it)"})
        self.assertEqual(plans[1]["message"], "Oliver answered via chief:\ndone, freed 40 GB\n  and ran t3 doctor")
        self.assertEqual((plans[1]["environmentId"], plans[1]["threadId"]), (MAC, "disk"))

    def test_refuses_a_stop_option_and_a_pr(self):
        plans = chief.relay_plan([{"id": "ans_1", "objectId": self.needs[0]["objectId"], "key": "c", "text": "c"},
                                  {"id": "ans_2", "objectId": self.needs[2]["objectId"], "text": "lgtm"}], self.needs)
        self.assertIn("stop:merge", plans[0]["refuse"])
        self.assertIn("not a thread", plans[1]["refuse"])
        self.assertTrue(all("message" not in plan for plan in plans))

    def test_chat_answers_resolve_by_rank_or_name(self):
        need, key, text = chief.parse_answer("1: b", self.needs)
        self.assertEqual((need["rank"], key, text), (1, "b", "b"))
        need, key, text = chief.parse_answer("ci-speed: start with the lint rule: it is cheaper", self.needs)
        self.assertEqual((need["rank"], key, text), (1, None, "start with the lint rule: it is cheaper"))
        need, _, text = chief.parse_answer("chief: inbox: looks right", self.needs)
        self.assertEqual((need["rank"], text), (4, "looks right"))
        need, _, _ = chief.parse_answer("disk space: done", self.needs)
        self.assertEqual(need["rank"], 2)

    def test_a_thread_with_a_call_and_a_flag_keeps_its_options(self):
        flag = {"rank": 5, "objectId": self.needs[0]["objectId"], "title": "🟡 ◆ ci-speed", "options": []}
        needs = self.needs + [flag]
        plans = chief.relay_plan([{"id": "ans_1", "objectId": flag["objectId"], "key": "c", "text": "c"},
                                  {"id": "ans_2", "objectId": flag["objectId"], "key": "b", "text": "b"}], needs)
        self.assertIn("stop:merge", plans[0]["refuse"])
        self.assertTrue(plans[1]["message"].endswith("(b: no: leave it)"))
        with self.assertRaises(chief.ChiefError):
            chief.parse_answer("5: c", needs)
        need, key, _ = chief.parse_answer("ci-speed: b", needs)
        self.assertEqual((need["rank"], key), (1, "b"))

    def test_chat_answers_refuse_a_stop_option_a_pr_and_no_match(self):
        for line, words in (("1: c", "crosses a stop"), ("3: lgtm", "no thread"), ("nothing here: a", "no item"),
                            ("1:   ", "empty")):
            with self.assertRaises(chief.ChiefError) as raised:
                chief.parse_answer(line, self.needs)
            self.assertIn(words, str(raised.exception))



CPH = ZoneInfo("Europe/Copenhagen")


def at(text):
    return datetime.fromisoformat(text).astimezone(timezone.utc)


class SnoozeTimes(unittest.TestCase):
    # Monday 2026-11-02 23:40 in Copenhagen (CET, +01:00).
    now = at("2026-11-02T22:40:00+00:00")

    def until(self, words, now=None):
        return snooze.until(words, now or self.now, CPH).strftime("%Y-%m-%dT%H:%MZ")

    def test_spans_count_from_now(self):
        for words, end in (("1h", "2026-11-02T23:40Z"), ("1 h", "2026-11-02T23:40Z"), ("90m", "2026-11-03T00:10Z"),
                           ("in 2 hours", "2026-11-03T00:40Z"), ("for 3 days", "2026-11-05T22:40Z"),
                           ("1w", "2026-11-09T22:40Z"), ("1.5h", "2026-11-03T00:10Z")):
            self.assertEqual(self.until(words), end, words)

    def test_the_page_presets_in_words(self):
        self.assertEqual(self.until("tomorrow"), "2026-11-03T08:00Z")
        self.assertEqual(self.until("tomorrow 9"), "2026-11-03T08:00Z")
        self.assertEqual(self.until("Tomorrow at 12"), "2026-11-03T11:00Z")
        self.assertEqual(self.until("until tomorrow 12:00"), "2026-11-03T11:00Z")
        self.assertEqual(self.until("tomorrow 2pm"), "2026-11-03T13:00Z")
        self.assertEqual(self.until("tomorrow 9.30am"), "2026-11-03T08:30Z")

    def test_a_bare_time_already_past_is_tomorrow(self):
        self.assertEqual(self.until("23:50"), "2026-11-02T22:50Z")
        self.assertEqual(self.until("3pm"), "2026-11-03T14:00Z")
        self.assertEqual(self.until("at 8"), "2026-11-03T07:00Z")

    def test_a_weekday_is_the_next_one_never_today(self):
        self.assertEqual(self.until("monday"), "2026-11-09T08:00Z")
        self.assertEqual(self.until("next mon 10"), "2026-11-09T09:00Z")
        self.assertEqual(self.until("wed 14:30"), "2026-11-04T13:30Z")
        self.assertEqual(self.until("tuesday"), "2026-11-03T08:00Z")

    def test_dates_are_local_unless_they_carry_an_offset(self):
        self.assertEqual(self.until("2026-11-05"), "2026-11-05T08:00Z")
        self.assertEqual(self.until("2026-11-05 14:00"), "2026-11-05T13:00Z")
        self.assertEqual(self.until("2026-11-05T14:00"), "2026-11-05T13:00Z")
        self.assertEqual(self.until("2026-11-05T14:00Z"), "2026-11-05T14:00Z")
        self.assertEqual(self.until("2026-11-05T14:00+02:00"), "2026-11-05T12:00Z")

    def test_tomorrow_is_the_local_day_across_a_clock_change(self):
        # 00:30 local on Oct 25 is still Oct 24 in UTC; the clocks go back that night.
        self.assertEqual(self.until("tomorrow", at("2026-10-24T22:30:00+00:00")), "2026-10-26T08:00Z")
        self.assertEqual(self.until("tomorrow", at("2026-10-23T10:00:00+00:00")), "2026-10-24T07:00Z")

    def test_refuses_what_it_cant_place(self):
        for words, reason in (("soon", "isn't a time I know"), ("13pm", "isn't a time"), ("25:00", "isn't a time"),
                              ("today", "needs a time"), ("today 9", "is past"), ("2026-11-01", "is past"),
                              ("90 days", "60 days"), ("2026-13-01", "isn't a date"), ("yesterday", "isn't a time")):
            with self.assertRaises(snooze.Unparsed, msg=words) as raised:
                snooze.until(words, self.now, CPH)
            self.assertIn(reason, str(raised.exception), words)

    def test_only_an_explicit_snooze_is_one(self):
        self.assertEqual(snooze.command("snooze tomorrow 12"), ("snooze", "tomorrow 12"))
        self.assertEqual(snooze.command("Snooze 1h"), ("snooze", "1h"))
        self.assertEqual(snooze.command("snooze"), ("snooze", ""))
        self.assertEqual(snooze.command("unsnooze"), ("unsnooze", ""))
        # D15: a reminder in free text is Oliver's words, passed on.
        self.assertIsNone(snooze.command("remind me about this tomorrow at 12"))
        self.assertIsNone(snooze.command("snoozed it already, go on"))

    def test_zone_comes_from_chief_tz(self):
        old = os.environ.get("CHIEF_TZ")
        os.environ["CHIEF_TZ"] = "America/New_York"
        try:
            self.assertEqual(str(snooze.zone()), "America/New_York")
        finally:
            os.environ.pop("CHIEF_TZ") if old is None else os.environ.__setitem__("CHIEF_TZ", old)


class Snoozes(unittest.TestCase):
    needs = Relay.needs
    thread = f"t3-thread://v2/{DEVBOX}/coord"

    def test_relay_snoozes_and_unsnoozes_threads_in_t3_oldest_first(self):
        until = int(at("2026-11-03T08:00:00+00:00").timestamp() * 1000)
        plans = chief.relay_plan([
            {"id": "ans_3", "kind": "unsnooze", "objectId": self.thread, "text": "unsnooze", "createdAt": 3},
            {"id": "ans_1", "kind": "snooze", "objectId": self.thread, "text": "snooze until …", "until": until,
             "createdAt": 1},
            {"id": "ans_2", "kind": "snooze", "objectId": "https://github.com/o/r/pull/9", "until": until,
             "text": "snooze until …", "createdAt": 2}], self.needs)
        self.assertEqual(plans, [
            {"kind": "snooze", "answerId": "ans_1", "environmentId": DEVBOX, "threadId": "coord",
             "snoozedUntil": "2026-11-03T08:00:00.000Z"},
            {"answerId": "ans_2", "done": "hidden in Executor; no thread to snooze"},
            {"kind": "unsnooze", "answerId": "ans_3", "environmentId": DEVBOX, "threadId": "coord"}])
        self.assertTrue(all("message" not in plan for plan in plans))

    def chat(self, line, needs=None, asleep_ids=None):
        calls = []
        need, key, text = chief.parse_answer(line, needs or self.needs)
        made = chief.chat_answer(need, key, text, SnoozeTimes.now, asleep_ids=asleep_ids,
                                 call=lambda tool, body: calls.append((tool, body)) or {"id": "ans_x",
                                                                                         "status": "pending"})
        return made, calls

    def test_chat_snooze_takes_a_rank_or_name_and_a_when(self):
        old = os.environ.get("CHIEF_TZ")
        os.environ["CHIEF_TZ"] = "Europe/Copenhagen"
        try:
            made, calls = self.chat("1: snooze tomorrow 12")
            self.assertEqual(calls, [("snooze", {"objectId": self.thread, "until": "2026-11-03T11:00:00Z"})])
            self.assertEqual((made["kind"], made["local"]), ("snooze", "Tue 03 Nov 12:00 CET"))
            # A PR row can be snoozed, though it can't be answered.
            _, calls = self.chat("franklin-next #9: snooze 2h")
            self.assertEqual(calls, [("snooze", {"objectId": "https://github.com/o/r/pull/9",
                                                 "until": "2026-11-03T00:40:00Z"})])
            _, calls = self.chat("ci-speed: unsnooze", asleep_ids={self.thread})
            self.assertEqual(calls, [("unsnooze", {"objectId": self.thread})])
            with self.assertRaises(chief.ChiefError) as raised:
                self.chat("ci-speed: unsnooze", asleep_ids=set())
            self.assertIn("isn't snoozed", str(raised.exception))
        finally:
            os.environ.pop("CHIEF_TZ") if old is None else os.environ.__setitem__("CHIEF_TZ", old)

    def test_chat_reminders_in_words_pass_on_and_a_bad_when_is_refused(self):
        made, calls = self.chat("1: remind me about this tomorrow at 12")
        self.assertEqual(calls, [("answer", {"objectId": self.thread, "text": "remind me about this tomorrow at 12"})])
        self.assertEqual(made["kind"], "answer")
        for line, reason in (("1: snooze", "say when"), ("1: snooze whenever", "isn't a time I know")):
            with self.assertRaises(chief.ChiefError) as raised:
                self.chat(line)
            self.assertIn(reason, str(raised.exception))

    def test_card_leaves_out_what_t3_or_executor_snoozed(self):
        held = {"repo": "hifranklin-tech/franklin-next", "number": 2, "state": "open"}
        threads = [dict(listed("a", "Export fix", hours=30), snoozed=True, prs=[held]),
                   listed("b", "Search speed", env=DEVBOX, hours=2)]
        reads = [read(threads[0], block("stop", [("decide", "which export fix")]), hours=30),
                 read(threads[1], block("stop", [("review", "the index migration")]), hours=2)]
        cache = chief.merge({}, reads)
        runs = []
        text = chief.build(threads, cache, [], [pr(2), pr(7), pr(8)], NOW,
                           record=lambda run: runs.append(run) or "ok",
                           # PR 7 snoozed on the page; thread b's Executor snooze is T3's call, not the card's.
                           snoozed=["https://github.com/hifranklin-tech/franklin-next/pull/7",
                                    f"t3-thread://v2/{DEVBOX}/b"])
        ids = [need["objectId"] for need in runs[0]["needs"]]
        self.assertEqual(ids, [f"t3-thread://v2/{DEVBOX}/b", "https://github.com/hifranklin-tech/franklin-next/pull/8"])
        self.assertIn("Snoozed, so left out until their time: 1 thread, 2 other rows.", text)
        self.assertNotIn("Export fix", text)

class Projects(unittest.TestCase):
    def test_digest_keeps_open_workers_and_links(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root, "dinero")
            folder.mkdir()
            (folder / "project.md").write_text(
                "# ◆ dinero\n\nCoordinator: <t3-thread://v2/env/coord> · Checkout: x · Mode: m\n\n## Goal\n\n"
                "Ship Dinero on V3.\nProof: p\n\n## Workers\n\n| Worker | Thread | Branch or PR | State | Waits on | "
                "Last side effect |\n|---|---|---|---|---|---|\n| adapter | <t3-thread://v2/env/w1> · taskId t | b | "
                "waiting | Oliver: push go | x |\n| audit | <t3-thread://v2/env/w2> | - | done: merged | - | x |\n")
            found = projects.read_all(root)
        self.assertEqual(found[0]["project"], "dinero")
        self.assertEqual(found[0]["coordinator"], "t3-thread://v2/env/coord")
        self.assertEqual(found[0]["goal"], "Ship Dinero on V3.")
        self.assertEqual([(w["worker"], w["thread"], w["waits"]) for w in found[0]["workers"]],
                         [("adapter", "t3-thread://v2/env/w1", "Oliver: push go")])

    def test_runs_from_stdin_as_the_mac_feed_does(self):
        with tempfile.TemporaryDirectory() as root:
            out = subprocess.run([sys.executable, "-", "--root", root], input=(HERE / "projects.py").read_text(),
                                 capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(out.stdout)["projects"], [])


class Transcript:
    """A Claude Code transcript as the router's session writes it: prompts, then each tool
    call as an assistant tool_use and a user tool_result under the prompt's promptId."""

    def __init__(self, folder):
        self.folder, self.lines, self.prompt_id, self.count = Path(folder), [], None, 0

    def prompt(self, text, **flags):
        self.count += 1
        if not flags:
            self.prompt_id = f"prompt-{self.count}"
        self.lines.append(dict({"type": "user", "promptId": self.prompt_id,
                                "message": {"role": "user", "content": text}}, **flags))
        return self

    def call(self, tool, args, result=None, error=None, saved=False):
        self.count += 1
        use = f"toolu_{self.count}"
        self.lines.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": use, "name": f"mcp__t3-code__{tool}", "input": args}]}})
        text = error if error else json.dumps(result)
        if saved:
            path = self.folder / f"mcp-t3-code-{tool}-{self.count}.txt"
            path.write_text(text)
            text = (f"Error: result ({len(text):,} characters) exceeds maximum allowed tokens. Output has been saved "
                    f"to {path}.\nFormat: JSON with schema: {{threads: [{{...}}]}}")
        part = {"type": "tool_result", "tool_use_id": use, "content": [{"type": "text", "text": text}]}
        if error:
            part["is_error"] = True
        self.lines.append({"type": "user", "promptId": self.prompt_id, "message": {"role": "user", "content": [part]}})
        return self

    def write(self):
        path = self.folder / "session.jsonl"
        path.write_text("".join(json.dumps(line) + "\n" for line in self.lines))
        return path

    def calls(self):
        return chief.tool_results.turn_calls(self.write())


def t3_thread(id, title, env=MAC, status="completed", hours=1, items=40, prs=(), by="user"):
    return {"threadId": id, "title": title, "link": f"<t3-thread://v2/{env}/{id}>", "createdBy": by,
            "status": status, "itemCount": items, "updatedAt": iso(hours), "snoozed": False, "settled": False,
            "pullRequests": [{"repository": repo, "number": number, "state": state} for repo, number, state in prs]}


def links(*linked):
    return {"environmentId": DEVBOX, "links": [{"environmentId": env, "label": label, "status": status}
                                                for env, label, status in linked]}


def list_args(env, cursor=None):
    return dict({"environmentId": env, **chief.LIST_ARGS}, **({"cursor": cursor} if cursor else {}))


def message(kind, text, position, hours=1, cut_at=None):
    item = {"type": kind, "position": position, "itemId": f"item-{position}", "text": text,
            "textTruncated": False, "nextTextOffset": None, "updatedAt": iso(hours)}
    if cut_at:
        item.update(text=text[:cut_at], textTruncated=True, nextTextOffset=cut_at)
    return item


def thread_read(id, items, pending=0, title="A thread", env=MAC):
    return {"thread": {"threadId": id, "title": title, "pendingRequestCount": pending,
                       "link": f"<t3-thread://v2/{env}/{id}>"},
            "recentRuns": [{"completedAt": iso(1)}], "items": items}


class ToolResults(unittest.TestCase):
    def test_reads_only_this_turns_t3_results_and_their_saved_files(self):
        with tempfile.TemporaryDirectory() as folder:
            transcript = Transcript(folder).prompt("Run the chief skill")
            transcript.call("t3_environment_read", {}, {"old": True})
            transcript.prompt("Run the chief skill")
            transcript.call("t3_environment_links", {}, links())
            transcript.prompt("summary of the run so far", isCompactSummary=True)
            transcript.call("t3_thread_list", list_args(DEVBOX), {"threads": [], "nextCursor": None}, saved=True)
            transcript.call("t3_thread_read", {"threadId": "x"}, error="Error: environment unreachable")
            transcript.lines.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "bash", "name": "Bash", "input": {}}]}})
            transcript.call("t3_thread_list", {"subagent": True}, {"threads": []})
            for line in transcript.lines[-2:]:
                line["isSidechain"] = True
            calls = transcript.calls()
        self.assertEqual([call.tool for call in calls], ["t3_environment_links", "t3_thread_list", "t3_thread_read"])
        self.assertEqual(calls[1].result, {"threads": [], "nextCursor": None})
        self.assertEqual(calls[2].error, "Error: environment unreachable")

    def test_finds_the_sessions_transcript(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "-home-oliver-skills").mkdir()
            Path(root, "-home-oliver-skills", "abc.jsonl").write_text("")
            old, chief.tool_results.PROJECTS = chief.tool_results.PROJECTS, root
            try:
                self.assertEqual(chief.tool_results.transcript_path({"CLAUDE_CODE_SESSION_ID": "abc"}).name, "abc.jsonl")
                with self.assertRaises(chief.tool_results.Unavailable):
                    chief.tool_results.transcript_path({"CLAUDE_CODE_SESSION_ID": "gone"})
                with self.assertRaises(chief.tool_results.Unavailable):
                    chief.tool_results.transcript_path({})
            finally:
                chief.tool_results.PROJECTS = old


class Listing(unittest.TestCase):
    def test_pages_past_one_tool_output_and_keeps_open_prs(self):
        mac_threads = [t3_thread(f"m{n}", f"Mac thread {n}", hours=n) for n in range(150)]
        mac_threads[0]["pullRequests"] = [{"repository": "o/r", "number": 1, "state": "open"},
                                          {"repository": "o/r", "number": 2, "state": "merged"}]
        with tempfile.TemporaryDirectory() as folder:
            transcript = Transcript(folder).prompt("Run the chief skill")
            transcript.call("t3_environment_links", {}, links((MAC, "Oliver's MBP", "reachable")))
            transcript.call("t3_thread_list", list_args(DEVBOX),
                            {"threads": [t3_thread("d1", "chief", env=DEVBOX)], "nextCursor": None})
            transcript.call("t3_thread_list", list_args(MAC), {"threads": mac_threads[:100], "nextCursor": 100},
                            saved=True)
            threads, notes, missing = chief.listing(transcript.calls())
            self.assertEqual(missing, [list_args(MAC, 100)])
            transcript.call("t3_thread_list", list_args(MAC, 100), {"threads": mac_threads[100:], "nextCursor": None})
            threads, notes, missing = chief.listing(transcript.calls())
        self.assertEqual((len(threads), notes, missing), (151, [], []))
        first = next(thread for thread in threads if thread["id"] == "m0")
        self.assertEqual(first["prs"], [{"repo": "o/r", "number": 1, "state": "open"}])
        self.assertEqual(first["env"], MAC)

    def test_a_machine_that_doesnt_answer_gets_a_note_and_no_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            transcript = Transcript(folder).prompt("Run the chief skill")
            transcript.call("t3_environment_links", {}, links((MAC, "Oliver's MBP", "unreachable")))
            transcript.call("t3_thread_list", list_args(DEVBOX), {"threads": [t3_thread("d1", "x", env=DEVBOX)]})
            threads, notes, missing = chief.listing(transcript.calls())
            self.assertEqual(([thread["id"] for thread in threads], missing), (["d1"], []))
            self.assertEqual(notes, ["Mac didn't answer: its link is unreachable."])
            # Reachable when linked, gone by the call: its error is the note, and no retry is asked.
            transcript = Transcript(folder).prompt("Run the chief skill")
            transcript.call("t3_environment_links", {}, links((MAC, "Oliver's MBP", "reachable")))
            transcript.call("t3_thread_list", list_args(DEVBOX), {"threads": []})
            transcript.call("t3_thread_list", list_args(MAC), error="Error: environment 0c5f5b0f timed out")
            threads, notes, missing = chief.listing(transcript.calls())
        self.assertEqual((threads, missing), ([], []))
        self.assertEqual(notes, ["Mac didn't answer: Error: environment 0c5f5b0f timed out"])

    def test_asks_for_the_links_first_and_ignores_lists_with_other_filters(self):
        with tempfile.TemporaryDirectory() as folder:
            transcript = Transcript(folder).prompt("Run the chief skill")
            with self.assertRaises(chief.ChiefError):
                chief.listing(transcript.calls())
            transcript.call("t3_environment_links", {}, links())
            transcript.call("t3_thread_list", dict(list_args(DEVBOX), settled=True), {"threads": []})
            self.assertEqual(chief.listing(transcript.calls())[2], [list_args(DEVBOX)])


class Gather(unittest.TestCase):
    def test_a_cut_reply_asks_for_its_rest_then_keeps_its_turn_block(self):
        item = listed("a", "Export fix", items=40)
        planned = chief.plan([item], {})
        (kind, tail), = chief.read_calls(planned[0])
        turn = block("stop", [("decide", "which export fix")])
        reply = "**Which export fix?**\n" + "x" * 7000 + "\n\n" + turn
        with tempfile.TemporaryDirectory() as folder:
            transcript = Transcript(folder).prompt("Run the chief skill")
            transcript.call("t3_thread_read", tail, thread_read("a", [
                message("assistant_message", reply, 30, cut_at=6000), message("user_message", "later", 31, hours=0.5)]))
            reads, missing, failed = chief.gather(planned, transcript.calls())
            rest = chief.rest_call(MAC, "a", "item-30", 6000)
            self.assertEqual((reads, missing, failed), ([], [rest], []))
            transcript.call("t3_thread_read", rest, thread_read("a", [
                dict(message("assistant_message", reply[6000:], 30), itemId="item-30")]))
            reads, missing, failed = chief.gather(planned, transcript.calls())
        self.assertEqual((missing, failed), ([], []))
        self.assertEqual(reads[0]["turn"], turn)
        self.assertEqual(reads[0]["headline"], "**Which export fix?**")
        self.assertEqual(reads[0]["lastUserAt"], iso(0.5))
        cache = chief.merge({}, reads)
        self.assertEqual(cache[chief.key(MAC, "a")]["turn"]["needs"][0]["name"], "which export fix")
        self.assertEqual(chief.plan([item], cache), [])

    def test_status_and_first_reads_and_a_failed_read(self):
        busy = listed("b", "Busy", status="running")
        worker = listed("w", "Worker", by="agent")
        planned = chief.plan([busy, worker], {chief.key(MAC, "w"): {"updatedAt": worker["updatedAt"], "turn": None}})
        (_, status), = chief.read_calls(planned[0])
        (_, first), = chief.read_calls(planned[1])
        brief = f"Mode: personal\nWorker of: t3-thread://v2/{DEVBOX}/coord (the ◆ x coordinator)\n\nDo it."
        with tempfile.TemporaryDirectory() as folder:
            transcript = Transcript(folder).prompt("Run the chief skill")
            transcript.call("t3_thread_read", status, thread_read("b", [], pending=1))
            transcript.call("t3_thread_read", first, error="Error: environment unreachable")
            reads, missing, failed = chief.gather(planned, transcript.calls())
            self.assertEqual((reads[0]["activePending"], missing, failed),
                             (1, [], ["Error: environment unreachable"]))
            transcript.call("t3_thread_read", first, thread_read("w", [message("user_message", brief, 0)]))
            reads, _, failed = chief.gather(planned, transcript.calls())
        self.assertEqual((reads[1]["workerOf"], failed), (f"t3-thread://v2/{DEVBOX}/coord", []))

    def test_the_mac_feeds_reply_is_its_projects(self):
        digest = {"read": "2026-11-02T21:32:23Z", "projects": [{"name": "chief"}]}
        reply = "```json\n" + json.dumps(digest) + "\n```\n" + block("done")
        with tempfile.TemporaryDirectory() as folder:
            transcript = Transcript(folder).prompt("Run the chief skill")
            transcript.call("t3_thread_read", {"threadId": "feed"},
                            thread_read("feed", [message("assistant_message", reply, 9)], title=chief.FEED_TITLE))
            self.assertEqual(chief.feed_projects(transcript.calls()), digest)
            transcript.call("t3_thread_read", {"threadId": "feed", "limit": 4}, thread_read(
                "feed", [message("assistant_message", reply, 12, cut_at=len(reply) - 5)], title=chief.FEED_TITLE))
            self.assertIsNone(chief.feed_projects(transcript.calls()))


class Cli(unittest.TestCase):
    def run_inbox(self, env, *args):
        return subprocess.run([sys.executable, str(HERE / "inbox.py"), *args], env=env, capture_output=True,
                              text=True, check=True)

    def test_list_plan_card_round_trip_from_the_transcript(self):
        with tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as orchestrate, \
                tempfile.TemporaryDirectory() as folder:
            transcript = Transcript(folder).prompt("Run the chief skill")
            env = dict(os.environ, CHIEF_STATE=state, CHIEF_ORCHESTRATE=orchestrate,
                       CHIEF_TRANSCRIPT=str(Path(folder, "session.jsonl")))
            transcript.call("t3_environment_links", {}, links((MAC, "Oliver's MBP", "unreachable"))).write()
            self.assertEqual([json.loads(line) for line in self.run_inbox(env, "list").stdout.splitlines()],
                             [list_args(DEVBOX)])
            transcript.call("t3_thread_list", list_args(DEVBOX),
                            {"threads": [t3_thread("a", "Export fix", env=DEVBOX, hours=3)], "nextCursor": None}).write()
            self.assertEqual(self.run_inbox(env, "list").stdout, "")
            (planned,) = [json.loads(line) for line in self.run_inbox(env, "plan").stdout.splitlines()]
            self.assertEqual(planned["threadId"], "a")
            reply = "Which fix?\n\n" + block("stop", [("decide", "the fix")])
            transcript.call("t3_thread_read", planned,
                            thread_read("a", [message("assistant_message", reply, 30, hours=3)], env=DEVBOX)).write()
            self.assertEqual(self.run_inbox(env, "plan").stdout, "")
            text = self.run_inbox(env, "card", "--no-gh", "--no-record", "--now", NOW.isoformat()).stdout
            self.assertIn("Decide: the fix", text)
            self.assertIn("Mac didn't answer: its link is unreachable.", text)
            self.assertNotIn("not made", text)
            # The next turn, with nothing new, plans nothing.
            transcript.prompt("Run the chief skill").write()
            self.assertEqual(self.run_inbox(env, "plan").stdout, "")

    def test_card_names_reads_left_unmade(self):
        with tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as orchestrate, \
                tempfile.TemporaryDirectory() as folder:
            Path(state, "threads.json").write_text(json.dumps([listed("a", "Export fix", hours=3)]))
            path = Transcript(folder).prompt("Run the chief skill").write()
            env = dict(os.environ, CHIEF_STATE=state, CHIEF_ORCHESTRATE=orchestrate, CHIEF_TRANSCRIPT=str(path))
            text = self.run_inbox(env, "card", "--no-gh", "--no-record", "--now", NOW.isoformat()).stdout
        self.assertIn("1 planned read not made, so its thread keeps its last read.", text)


def shell(id, title, status="completed", env=DEVBOX, hours=1, reply=None, first=None, by="user", pending=0,
          snoozed=False, last_user=None):
    """One thread as the live feeder hands it to `inbox.py live`: shell fields, and its
    projection's details once read (reply=None means not read yet)."""
    item = {"env": env, "id": id, "title": title, "status": status, "createdBy": by, "updatedAt": iso(hours),
            "snoozed": snoozed, "prs": [], "pending": pending, "runCompletedAt": iso(hours)}
    if reply is not None:
        item["details"] = {"reply": {"text": reply, "at": iso(hours)}, "first": first,
                           "lastUserAt": iso(last_user) if last_user is not None else None}
    return item


class Live(unittest.TestCase):
    def needs(self, *items):
        return chief.live_needs(list(items), [], NOW)

    def test_a_turn_block_need_is_a_call_with_its_options(self):
        reply = "Which fix?\n\n" + block("stop", [("decide", "the fix")], options=[("a", "decision", "Ship")])
        (need,) = self.needs(shell("a", "Export fix", reply=reply, hours=3))
        self.assertEqual((need["objectId"], need["kind"], need["what"], need["machine"]),
                         (f"t3-thread://v2/{DEVBOX}/a", "decide", "Decide: the fix", "devbox"))
        self.assertEqual(need["options"], [{"key": "a", "class": "decision", "text": "Ship"}])
        self.assertEqual(need["since"], iso(3)[:19] + "Z")

    def test_a_reply_with_no_block_or_a_cleared_one_makes_no_call(self):
        self.assertEqual(self.needs(shell("a", "No block", reply="Done, nothing else.")), [])
        self.assertEqual(self.needs(shell("b", "Cleared", reply="Done.\n\n" + block("done"))), [])
        self.assertEqual(self.needs(shell("c", "Malformed", reply="Hm.\n\n<!-- turn {not json} -->")), [])
        # Not read yet: only its shell, so no call until the feeder reads it.
        self.assertEqual(self.needs(shell("d", "Unread")), [])

    def test_a_running_thread_counts_only_its_pending_request(self):
        stop = "Which?\n\n" + block("stop", [("decide", "x")])
        self.assertEqual(self.needs(shell("a", "Busy", status="running", reply=stop)), [])
        (need,) = self.needs(shell("b", "Asks", status="running", reply=stop, pending=1))
        self.assertEqual((need["kind"], need["what"]), ("do", "Answer its pending question or approval in T3"))

    def test_a_workers_stop_is_its_coordinators_and_a_snoozed_thread_drops_off(self):
        stop = "Which?\n\n" + block("stop", [("decide", "x")])
        worker = shell("w", "worker", reply=stop, by="agent",
                       first=f"Mode: personal\nWorker of: t3-thread://v2/{DEVBOX}/coord\n\nDo it.")
        self.assertEqual(self.needs(worker), [])
        self.assertEqual(self.needs(shell("s", "Snoozed", reply=stop, snoozed=True)), [])

    def test_flags_stay_the_hourly_runs(self):
        coordinator = shell("coord", "◆ chief", reply="Started.\n\n" + block("done"), hours=5)
        worker = shell("w", "worker", reply="Report.\n\n" + block("done"), hours=2, by="agent",
                       first=f"Worker of: t3-thread://v2/{DEVBOX}/coord")
        listed, reads = zip(*(chief.live_read(item) for item in (coordinator, worker)))
        hourly = chief.thread_rows(chief.threads_from(list(listed), chief.merge({}, list(reads))), {}, NOW)
        self.assertEqual([row.flags for row in hourly], [["quiet coordinator"]])
        self.assertEqual(self.needs(coordinator, worker), [])

    def test_the_cli_reads_threads_on_stdin(self):
        reply = "Which?\n\n" + block("stop", [("review", "the export PR")])
        with tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as orchestrate:
            env = dict(os.environ, CHIEF_STATE=state, CHIEF_ORCHESTRATE=orchestrate)
            out = subprocess.run([sys.executable, str(HERE / "inbox.py"), "live"], env=env, capture_output=True,
                                 text=True, check=True,
                                 input=json.dumps({"now": iso(0), "env": DEVBOX,
                                                   "threads": [shell("a", "Review", reply=reply),
                                                               shell("b", "Quiet", reply="ok")]}))
        self.assertEqual(json.loads(out.stdout)["machine"], "devbox")
        (need,) = json.loads(out.stdout)["needs"]
        self.assertEqual((need["title"], need["kind"]), ("Review", "review"))


@unittest.skipUnless(__import__("shutil").which("node"), "node isn't installed")
class Feeder(unittest.TestCase):
    def test_the_feeders_node_suite(self):
        """chief/feeder's shell mirror, run key and health rows, which node tests."""
        out = subprocess.run(["node", "--test", str(HERE.parent / "feeder" / "shell.test.mjs")],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout[-2000:] + out.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
