"""project.py tick and tick.sh against fake `t3` and `gh` on PATH, which serve thread and PR
state from JSON files and record each `t3 thread send`. The rule under test: a change T3
doesn't tell the coordinator wakes it once, and an unchanged project wakes nothing.
Run: python3 -m unittest discover -s coordinator/scripts"""
import contextlib, json, os, pathlib, sqlite3, subprocess, sys, tempfile, time, unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE / "project.py"

PROJECT = """# ◆ export

Coordinator: <t3-thread://v2/env/lead> · Checkout: {checkout} (on `main`) · Mode: personal

## Goal

Ship the export.
Proof: #12 merged.
Follow-ups: none

## Workers

| Worker | Thread | Branch or PR | State | Waits on | Last side effect |
|---|---|---|---|---|---|
| build | <t3-thread://v2/env/w1> · task t1 | `export` · #12 | running | #12 ← review | pushed abc |
| probe | <t3-thread://v2/env/w2> · task t2 | acme/app#7 | done | — | report |
| remote | <t3-thread://v2/other/w3> · task t3 | — | {remote} | — | launched |

## Listening

- Heartbeat: {heartbeat}
- Startup: none
"""

FAKE_T3 = r"""#!/usr/bin/env python3
import json, os, sys
fake = os.environ["FAKE"]
if sys.argv[1:3] == ["thread", "show"]:
    threads = json.load(open(f"{fake}/threads.json"))
    if sys.argv[3] not in threads:
        sys.exit("Thread is no longer available.")
    print(json.dumps({"thread": threads[sys.argv[3]], "messages": []}))
elif sys.argv[1:3] == ["thread", "send"]:
    with open(f"{fake}/sent.jsonl", "a") as out:
        out.write(json.dumps({"to": sys.argv[3], "message": sys.stdin.read()}) + "\n")
    sys.exit(int(os.environ.get("SEND_CODE", "0")))
"""

FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
repo = args[args.index("-R") + 1]
prs = json.load(open(os.environ["FAKE"] + "/prs.json"))
key = f"{repo}#{args[2]}"
with open(os.environ["FAKE"] + "/gh-calls.jsonl", "a") as out:
    out.write(json.dumps({"key": key}) + "\n")
if key not in prs:
    sys.exit("no pull requests found")
pr = {"headRefOid": "c0ffee1234", **prs[key]}  # a head that never moves, unless a test sets one
print(json.dumps({field: pr[field] for field in args[args.index("--json") + 1].split(",")}))
"""


def thread(status="running", runs=1, items=10, asked=0, **more):
    return {"status": status, "runCount": runs, "itemCount": items, "pendingRequestCount": asked, **more}


class Tick(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.root)])
        self.fake, self.dir = self.root / "fake", self.root / "orchestrate" / "export"
        (self.fake / "bin").mkdir(parents=True)
        (self.fake / "userdata").mkdir()
        (self.fake / "userdata" / "environment-id").write_text("env\n")  # this machine's, as T3 writes it
        self.dir.mkdir(parents=True)
        for name, body in [("t3", FAKE_T3), ("gh", FAKE_GH)]:
            (self.fake / "bin" / name).write_text(body)
            (self.fake / "bin" / name).chmod(0o755)
        self.checkout = self.root / "check out"  # a space, as a real path may have
        subprocess.run(["git", "init", "-q", str(self.checkout)], check=True)
        subprocess.run(["git", "-C", str(self.checkout), "remote", "add", "origin", "git@github.com:acme/app.git"], check=True)
        self.write_project()
        self.threads = {"lead": thread("completed", 40), "w1": thread()}
        self.prs = {"acme/app#12": {"state": "OPEN", "isDraft": True}, "acme/app#7": {"state": "OPEN", "isDraft": False}}
        self.watch(12, 7)

    def watch(self, *numbers, links=None):
        """T3's state database with the lead thread watching acme/app's numbers, or the given links."""
        path = self.fake / "userdata" / "statev2.sqlite"
        path.unlink(missing_ok=True)
        links = links if links is not None else [
            {"repository": "Acme/App", "number": n, "source": "agent", "snapshot": {"state": "open"},
             "watch": {"startedAt": "2026-11-27T12:00:00Z", "headSha": "c0ff", "wakes": 0}} for n in numbers]
        with contextlib.closing(sqlite3.connect(path)) as db, db:
            db.execute("create table orchestration_v2_projection_threads (thread_id text, payload_json text, deleted_at text)")
            db.execute("insert into orchestration_v2_projection_threads values ('lead', ?, null)",
                       (json.dumps({"pullRequests": links}),))

    def write_project(self, heartbeat="tick", remote="done", rows=None):
        text = PROJECT.format(checkout=self.checkout, heartbeat=heartbeat, remote=remote)
        for old, new in (rows or {}).items():
            text = text.replace(old, new)
        (self.dir / "project.md").write_text(text)

    def tick(self, *args, code=0, send_code=0):
        (self.fake / "threads.json").write_text(json.dumps(self.threads))
        (self.fake / "prs.json").write_text(json.dumps(self.prs))
        env = {**os.environ, "FAKE": str(self.fake), "SEND_CODE": str(send_code), "T3CODE_HOME": str(self.fake),
               "PATH": f"{self.fake / 'bin'}:{os.environ['PATH']}"}
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.dir), "tick", *args],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, code, result.stderr)
        return result

    def sent(self):
        path = self.fake / "sent.jsonl"
        messages = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        path.unlink(missing_ok=True)
        return messages

    def state(self):
        return json.loads((self.dir / "tick.json").read_text())

    def age(self, seconds):
        """Moves every saved time back, as if the last tick ran `seconds` ago."""
        state = self.state()
        for saved in state["threads"].values():
            saved["since"] -= seconds
        for draft in state.get("drafts", {}).values():
            draft["since"] -= seconds
        state["sent"] = {key: at - seconds for key, at in state["sent"].items()}
        (self.dir / "tick.json").write_text(json.dumps(state))

    def test_an_unchanged_project_wakes_nothing(self):
        for _ in range(3):
            self.tick("--send")
        self.assertEqual(self.sent(), [])

    def test_a_stopped_worker_wakes_the_coordinator_once_its_row_is_stale_for_a_tick(self):
        self.tick("--send")
        self.threads["w1"] = thread("failed", 1, 12)
        self.tick("--send")
        self.assertEqual(self.sent(), [], "a just-stopped thread waits a tick for T3's own delivery")
        self.tick("--send")
        [sent] = self.sent()
        self.assertEqual(sent["to"], "lead")
        self.assertTrue(sent["message"].startswith('<coordinator-tick project="export">\n'), sent["message"])
        self.assertIn("- build: its thread stopped (failed) while its row says running\n", sent["message"])
        self.assertIn(f"Read {self.dir / 'project.md'} and handle", sent["message"], "a fresh session finds the folder")
        self.tick("--send")
        self.assertEqual(self.sent(), [], "sent once an hour, not each tick")
        self.age(3600)
        self.tick("--send")
        self.assertEqual(len(self.sent()), 1, "still unfixed an hour later, so it repeats")

    def test_a_stopped_worker_whose_row_the_coordinator_fixed_wakes_nothing(self):
        self.tick("--send")
        self.threads["w1"] = thread("completed", 1, 12)
        self.tick("--send")
        self.write_project(rows={"| `export` · #12 | running |": "| `export` · #12 | done |"})
        self.tick("--send")
        self.assertEqual(self.sent(), [])

    def test_a_worker_with_no_new_item_for_an_hour_is_stalled(self):
        self.tick("--send")
        self.age(3000)
        self.tick("--send")
        self.assertEqual(self.sent(), [])
        self.age(700)
        self.tick("--send")
        [sent] = self.sent()
        self.assertIn("- build: no new thread item in 61 min\n", sent["message"])
        self.threads["w1"] = thread(items=11)
        self.tick("--send")
        self.assertEqual(self.sent(), [], "a new item ends the stall")

    def test_a_question_the_row_doesnt_show_wakes_it(self):
        self.tick("--send")
        self.threads["w1"] = thread("waiting", asked=1)
        self.tick("--send")
        self.tick("--send")
        [sent] = self.sent()
        self.assertIn("- build: its thread waits on 1 question(s) its row doesn't show\n", sent["message"])

    def test_a_pr_that_merges_or_turns_ready_wakes_it_once(self):
        self.tick("--send")
        self.prs["acme/app#12"] = {"state": "MERGED", "isDraft": False}
        self.prs["acme/app#7"] = {"state": "OPEN", "isDraft": True}
        self.tick("--send")
        [sent] = self.sent()
        self.assertIn("- acme/app#12: merged", sent["message"])
        self.assertIn("- acme/app#7: turned draft\n", sent["message"])
        self.tick("--send")
        self.assertEqual(self.sent(), [])

    def test_a_push_to_a_draft_is_no_pr_event(self):
        self.tick("--send")
        self.prs["acme/app#12"]["headRefOid"] = "d00d"
        self.tick("--send")
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.state()["prs"]["acme/app#12"], ["OPEN", True], "tick.json keeps [state, draft]")

    def test_a_draft_idle_for_30_min_that_no_wait_names_is_flagged(self):
        # Nov 25-27, 2026: a row held two repos' PRs with one Waits on, so two drafts that needed nothing
        # sat for two days behind another PR's blocker.
        self.write_project(rows={"| `export` · #12 | running | #12 ← review |": "| #20 · #21 · #31 | waiting | #21 ← acme/tools#138 |"})
        for n in (20, 21, 31):
            self.prs[f"acme/app#{n}"] = {"state": "OPEN", "isDraft": True, "headRefOid": f"{n}aaaaaaaa"}
        self.prs["acme/tools#138"] = {"state": "OPEN", "isDraft": False}
        self.watch(7, 20, 21, 31)
        self.tick("--send")
        self.age(1700)
        self.tick("--send")
        self.assertEqual(self.sent(), [], "under 30 min at one head")
        self.age(200)
        self.tick("--send")
        [sent] = self.sent()
        for n in (20, 31):
            self.assertIn(f"- acme/app#{n}: a draft at {n}aaaaa for 31 min, and its row's Waits on names nothing it "
                          f"waits for: mark it ready, or write `acme/app#{n} ← <what it waits on>`\n", sent["message"])
        self.assertNotIn("acme/app#21", sent["message"])
        self.write_project(rows={"| `export` · #12 | running | #12 ← review |": "| #20 · #21 · #31 | waiting | "
                                 "#21 ← acme/tools#138; #20 ← sandbox tests; #31 ← review |"})
        self.age(3600)
        self.tick("--send")
        self.assertEqual(self.sent(), [], "a named wait silences it")

    def test_a_push_or_leaving_draft_restarts_the_draft_clock_and_a_failed_read_keeps_it(self):
        self.write_project(rows={"| running | #12 ← review |": "| waiting | — |"})
        self.tick("--send")
        self.age(1900)
        self.prs["acme/app#12"]["headRefOid"] = "d00d"
        self.tick("--send")
        self.assertEqual(self.sent(), [], "a push restarts the clock")
        self.age(1900)
        self.tick("--send")
        self.assertIn("- acme/app#12: a draft at d00d for 31 min", self.sent()[0]["message"])
        self.prs["acme/app#12"]["isDraft"] = False
        self.tick("--send")
        self.assertEqual(self.state()["drafts"], {}, "a ready PR leaves the draft clocks")
        self.prs["acme/app#12"]["isDraft"] = True
        self.tick("--send")
        self.assertEqual([m["message"].count("- acme/app#12: a draft") for m in self.sent()], [0, 0])
        self.age(1900)
        del self.prs["acme/app#12"]
        self.tick("--send")
        self.assertEqual(self.sent(), [], "no finding on a stale look")
        self.prs["acme/app#12"] = {"state": "OPEN", "isDraft": True, "headRefOid": "d00d"}
        self.tick("--send")
        self.assertIn("- acme/app#12: a draft at d00d for 31 min", self.sent()[0]["message"], "the clock survived")

    def test_an_open_worker_pr_t3_isnt_watching_repeats_until_watched(self):
        # Nov 26-27, 2026: a user's Stop ended a coordinator's watches on 4 open PRs, twice, and a
        # reviewer's two reviews woke nobody for an hour. Links as T3 kept them: watch null, endedWatch set.
        ended = {"startedAt": "2026-11-27T11:58:18Z", "headSha": "a5b7", "wakes": 1}
        link = lambda n, repository="acme/tools": {
            "host": "github.com", "repository": repository, "number": n, "source": "agent",
            "url": f"https://github.com/{repository}/pull/{n}", "linkedAt": "2026-11-27T11:58:18Z",
            "snapshot": {"state": "open", "isDraft": n == 122}, "stack": None, "watch": None, "endedWatch": ended}
        self.watch(links=[link(n) for n in (109, 110, 122)])
        self.write_project(rows={"| `export` · #12 | running | #12 ← review |": "| acme/tools#109 → acme/tools#110 → "
                                 "acme/tools#122 | waiting | acme/tools#122 ← acme/tools#110 |"})
        for n in (109, 110, 122):
            self.prs[f"acme/tools#{n}"] = {"state": "OPEN", "isDraft": n == 122}
        self.tick("--send")
        [sent] = self.sent()
        for ref in ("acme/tools#109", "acme/tools#110", "acme/tools#122", "acme/app#7"):
            self.assertIn(f"- {ref}: open, and T3 isn't watching it for this thread, so call `watch_pull_request` "
                          "on it\n", sent["message"])
        self.tick("--send")
        self.assertEqual(self.sent(), [], "sent once an hour, not each tick")
        self.age(3600)
        self.tick("--send")
        self.assertEqual(len(self.sent()), 1, "still unwatched an hour later, so it repeats")
        on = {"startedAt": "2026-11-27T13:00:00Z", "headSha": "a5b7", "wakes": 0}
        self.watch(links=[{**link(n), "watch": on} for n in (109, 110, 122)] + [{**link(7, "Acme/App"), "watch": on}])
        self.age(3600)
        self.tick("--send")
        self.assertEqual(self.sent(), [])

    def test_a_stack_dismissed_watch_counts_as_unwatched(self):
        self.watch(links=[{"repository": "acme/app", "number": 12, "source": "stack-dismissed", "watch": {"wakes": 0}},
                          {"repository": "acme/app", "number": 7, "source": "stack", "watch": {"wakes": 0}}])
        self.tick("--send")
        message = self.sent()[0]["message"]
        self.assertIn("- acme/app#12: open, and T3 isn't watching it", message)
        self.assertNotIn("acme/app#7", message)

    def test_a_pr_seen_closed_while_t3_is_unreadable_is_judged_anew_on_reopening(self):
        self.watch(7)
        self.tick("--send")
        self.assertIn("- acme/app#12: open, and T3 isn't watching it", self.sent()[0]["message"])
        (self.fake / "userdata" / "statev2.sqlite").unlink()
        self.prs["acme/app#12"]["state"] = "CLOSED"
        self.age(600)
        self.tick("--send")
        self.watch(7)
        self.prs["acme/app#12"]["state"] = "OPEN"
        self.age(600)
        self.tick("--send")
        self.assertIn("- acme/app#12: open, and T3 isn't watching it", "".join(m["message"] for m in self.sent()))

    def test_a_failed_read_judges_no_watch_and_keeps_the_repeat_clock(self):
        self.watch(7)
        self.tick("--send")
        self.assertIn("- acme/app#12: open, and T3 isn't watching it", self.sent()[0]["message"])
        saved = self.prs.pop("acme/app#12")
        self.age(3600)
        self.tick("--send")
        self.assertNotIn("acme/app#12: open", "".join(m["message"] for m in self.sent()),
                         "an unread PR's saved state isn't news")
        self.prs["acme/app#12"] = saved
        self.tick("--send")
        self.assertIn("- acme/app#12: open, and T3 isn't watching it", self.sent()[0]["message"],
                      "read again, still unwatched past the hour, so it repeats")

    def test_a_finished_pr_needs_no_watch_and_isnt_read_again(self):
        self.prs["acme/app#7"] = {"state": "MERGED", "isDraft": False}
        self.watch(12)
        self.tick("--send")
        self.assertEqual(self.sent(), [], "a PR merged before the first look needs no watch")
        (self.fake / "gh-calls.jsonl").unlink()
        self.tick("--send")
        calls = [json.loads(line)["key"] for line in (self.fake / "gh-calls.jsonl").read_text().splitlines()]
        self.assertEqual(calls, ["acme/app#12"], "a merged PR isn't viewed again")

    def test_an_unreadable_t3_database_skips_the_watch_check(self):
        self.watch()
        (self.fake / "userdata" / "statev2.sqlite").unlink()
        self.assertIn("so the tick skips its unwatched-PR check", self.tick("--send").stderr)
        self.assertEqual(self.sent(), [])
        self.watch()  # nothing watched, but the database has no thread `missing`
        self.threads["missing"] = self.threads["lead"]
        self.write_project(rows={"<t3-thread://v2/env/lead>": "<t3-thread://v2/env/missing>"})
        self.assertIn("so the tick skips its unwatched-PR check", self.tick("--send").stderr)
        self.assertEqual(self.sent(), [])

    def test_while_the_coordinator_runs_no_watch_is_checked(self):
        self.watch()
        self.threads["lead"] = thread("running", 41)
        self.tick("--send")
        self.assertEqual(self.sent(), [])
        self.threads["lead"] = thread("completed", 41)
        self.tick("--send")
        self.assertIn("- acme/app#12: open, and T3 isn't watching it", self.sent()[0]["message"])

    def test_a_legacy_watches_line_is_named_until_removed(self):
        self.write_project(rows={"- Startup: none\n": "- Startup: none\n- Watches: acme/app#99 (the user)\n"})
        before = (self.dir / "project.md").read_text()
        self.tick("--send")
        self.assertIn("remove it with `project.py <folder> listen Watches none`", self.sent()[0]["message"])
        self.assertEqual(sorted(self.state()["prs"]), ["acme/app#12", "acme/app#7"], "its PRs aren't read")
        self.assertEqual((self.dir / "project.md").read_text(), before, "the tick writes no project.md")

    def test_an_unreadable_t3_keeps_an_unwatched_findings_clock(self):
        self.watch(7)
        self.tick("--send")
        self.assertIn("- acme/app#12: open, and T3 isn't watching it", self.sent()[0]["message"])
        (self.fake / "userdata" / "statev2.sqlite").unlink()
        self.age(1200)
        self.tick("--send")
        self.watch(7)
        self.age(1200)
        self.tick("--send")
        self.assertNotIn("acme/app#12: open", "".join(m["message"] for m in self.sent()),
                         "T3 read again 40 min after the alert, so it waits for the hour")

    def test_one_pr_written_two_ways_or_in_a_range_is_checked_once_each(self):
        self.write_project(rows={"`export` · #12": "`export` · #12, acme/app#12, app#12, #20–#22"})
        for n in (20, 21, 22):
            self.prs[f"acme/app#{n}"] = {"state": "OPEN", "isDraft": False}
        self.tick("--send")
        self.assertEqual(sorted(self.state()["prs"]), ["acme/app#12", "acme/app#20", "acme/app#21", "acme/app#22", "acme/app#7"])

    def test_a_repo_ref_without_a_known_owner_is_flagged(self):
        subprocess.run(["git", "-C", str(self.checkout), "remote", "remove", "origin"], check=True)
        self.write_project(rows={"`export` · #12": "`export` · skills#246"})
        self.tick("--send")
        self.assertIn("- skills#246: the tick can't tell its repo from the checkout's origin, so write it as owner/repo#N\n", self.sent()[0]["message"])

    def test_a_running_rows_ref_for_another_repo_is_flagged_not_guessed(self):
        self.write_project(rows={"`export` · #12": "`export` · #12; tools #9 → tools#10 (#8 merged)"})
        self.tick("--send")
        message = self.sent()[0]["message"]
        self.assertIn("- tools #9: the tick can't tell its repo from the checkout's origin, so write it as owner/repo#N\n", message)
        self.assertIn("- tools#10: the tick can't tell its repo", message)
        calls = [json.loads(line)["key"] for line in (self.fake / "gh-calls.jsonl").read_text().splitlines()]
        self.assertEqual(sorted(set(calls)), ["acme/app#12", "acme/app#7"], "no PR is read under a guessed repo")

    def test_a_failed_read_keeps_the_stall_clock(self):
        self.tick("--send")
        self.age(3060)
        del self.threads["w1"]
        self.tick("--send")
        self.sent()
        self.threads["w1"] = thread()
        self.age(600)
        self.tick("--send")
        self.assertIn("- build: no new thread item in 61 min\n", self.sent()[0]["message"])

    def test_a_pr_number_without_a_checkout_origin_is_flagged(self):
        subprocess.run(["rm", "-rf", str(self.checkout)], check=True)
        self.tick("--send")
        message = self.sent()[0]["message"]
        self.assertIn("- #12: the tick can't tell its repo from the checkout's origin, so write it as owner/repo#N\n", message)
        self.assertNotIn("acme/app#7:", message, "a full owner/repo#N needs no checkout")

    def test_a_closed_pr_that_reopens_is_news(self):
        self.tick("--send")
        self.prs["acme/app#12"] = {"state": "CLOSED", "isDraft": True}
        self.tick("--send")
        self.assertIn("- acme/app#12: closed\n", self.sent()[0]["message"])
        self.prs["acme/app#12"] = {"state": "OPEN", "isDraft": True}
        self.tick("--send")
        self.assertIn("- acme/app#12: reopened\n", self.sent()[0]["message"])

    def test_a_merged_pr_isnt_read_again(self):
        self.tick("--send")
        self.prs["acme/app#12"] = {"state": "MERGED", "isDraft": False}
        self.tick("--send")
        self.assertIn("- acme/app#12: merged\n", self.sent()[0]["message"])
        (self.fake / "gh-calls.jsonl").unlink()
        self.tick("--send")
        calls = [json.loads(line)["key"] for line in (self.fake / "gh-calls.jsonl").read_text().splitlines()]
        self.assertEqual(calls, ["acme/app#7"])

    def test_a_metadata_update_doesnt_reset_the_stall_clock(self):
        stamp = lambda ago: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - ago))
        self.threads["w1"] = thread(updatedAt=stamp(600))
        self.tick("--send")
        self.age(3060)
        self.threads["w1"] = thread(updatedAt=stamp(0))  # a title change, no new item
        self.tick("--send")
        self.assertIn("- build: no new thread item in 61 min\n", self.sent()[0]["message"])

    def test_a_worker_on_another_machine_gets_an_hourly_reminder(self):
        self.write_project(remote="running")
        self.tick("--send")
        [sent] = self.sent()
        self.assertIn("- remote: its thread is on another machine, so read its status with `t3_thread_read` "
                      "and environmentId other\n", sent["message"])

    def test_a_running_row_with_no_thread_link_is_flagged(self):
        self.write_project(rows={"<t3-thread://v2/env/w1> · task t1": "task t1"})
        self.tick("--send")
        self.assertIn("- build: its row says running but has no thread link to check\n", self.sent()[0]["message"])

    def test_links_paths_and_refs_parse_as_coordinators_write_them(self):
        self.write_project(rows={"<t3-thread://v2/env/w1> · task t1": "[build](t3-thread://v2/env/w1) · task t1",
                                 "| acme/app#7 | done |": "| app#7 and acme/app#7 | done |"})
        self.tick("--send")
        calls = [json.loads(line) for line in (self.fake / "gh-calls.jsonl").read_text().splitlines()]
        self.assertEqual(sorted({call["key"] for call in calls}), ["acme/app#12", "acme/app#7"],
                         "#12 resolved through the origin of a checkout path with a space")
        self.assertEqual(list(self.state()["threads"]), ["w1"])

    def test_a_live_row_the_tick_cant_parse_is_flagged(self):
        self.write_project(rows={"| probe | <t3-thread://v2/env/w2> · task t2 | acme/app#7 | done | — | report |":
                                 "| probe | <t3-thread://v2/env/w2> | running (round 2) |"})
        self.tick("--send")
        self.assertIn("- probe: its row's cells don't match the Workers header", self.sent()[0]["message"])
        self.write_project(rows={"| probe | <t3-thread://v2/env/w2> · task t2 | acme/app#7 | done | — | report |":
                                 "| probe | <t3-thread://v2/env/w2> | done | was running fine |"})
        self.age(3600)
        self.threads["w1"] = thread(items=11)
        self.tick("--send")
        self.assertEqual(self.sent(), [], "a done row that mentions running isn't live")

    def test_nothing_is_sent_while_the_coordinator_runs_but_workers_are_still_timed(self):
        self.tick("--send")
        self.threads["lead"] = thread("running", 41)
        self.threads["w1"] = thread("failed", 1, 12)
        self.prs["acme/app#12"] = {"state": "MERGED", "isDraft": False}
        self.tick("--send")
        self.tick("--send")
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.state()["prs"]["acme/app#12"], ["OPEN", True], "a PR waits for the coordinator's turn to end")
        self.threads["lead"] = thread("completed", 41)
        self.tick("--send")
        [sent] = self.sent()
        self.assertIn("- build: its thread stopped (failed)", sent["message"], "its stop was timed while it ran")
        self.assertIn("- acme/app#12: merged", sent["message"])

    def test_a_stall_is_timed_from_the_threads_last_update(self):
        hour_ago = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3660))
        self.threads["w1"] = thread(updatedAt=hour_ago)
        self.tick("--send")
        self.assertIn("- build: no new thread item in 61 min\n", self.sent()[0]["message"])

    def test_a_failed_send_keeps_the_state_so_the_next_tick_retries(self):
        self.tick("--send")
        self.prs["acme/app#12"] = {"state": "CLOSED", "isDraft": True}
        before = self.state()
        result = self.tick("--send", code=1, send_code=1)
        self.assertIn("t3 thread send failed", result.stderr)
        self.assertEqual(self.state(), before)
        self.sent()
        self.tick("--send")
        self.assertIn("- acme/app#12: closed", self.sent()[0]["message"])

    def test_with_the_heartbeat_off_send_does_nothing(self):
        self.write_project(heartbeat="none", remote="running")
        self.tick("--send")
        self.assertEqual((self.sent(), (self.dir / "tick.json").exists()), ([], False))

    def test_a_dry_run_prints_without_sending_or_saving(self):
        self.write_project(remote="running")
        result = self.tick()
        self.assertIn("the tick timer hasn't run in 20 minutes", result.stdout)
        self.assertIn("- remote: its thread is on another machine", result.stdout)
        self.assertEqual((self.sent(), (self.dir / "tick.json").exists()), ([], False))

    def test_a_dry_run_from_the_running_coordinator_still_checks_and_warns(self):
        self.threads["lead"] = thread("running", 41)
        self.write_project(remote="running")
        result = self.tick()
        self.assertIn("the tick timer hasn't run in 20 minutes", result.stdout)
        self.assertIn("- remote: its thread is on another machine", result.stdout)

    def test_a_pr_saved_in_mixed_case_keeps_its_news(self):
        self.write_project(rows={"- Watches: #12 (build), acme/app#7 (the user)": "- Watches: none"})
        self.tick("--send")
        state = self.state()
        state["prs"] = {key.replace("acme/app", "Acme/App"): value for key, value in state["prs"].items()}
        (self.dir / "tick.json").write_text(json.dumps(state))
        self.prs["acme/app#12"]["state"] = "MERGED"
        self.tick("--send")
        self.assertIn("- acme/app#12: merged\n", self.sent()[0]["message"], "a tick.json from before lowercase refs")

    def test_failed_reads_are_named_on_stderr(self):
        del self.prs["acme/app#12"]
        self.assertIn("tick: can't read PR acme/app#12", self.tick("--send").stderr)
        del self.threads["lead"]
        self.assertIn("tick: can't read the coordinator's thread", self.tick("--send", code=1).stderr)

    def test_a_failed_read_names_the_clis_reason_with_the_time(self):
        # The Mac's timer log held 158 bare "can't read" lines by Nov 25, 2026, with no time or cause.
        del self.threads["lead"]
        err = self.tick("--send", code=1).stderr
        self.assertRegex(err, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ tick: `t3 thread show lead` exited 1: "
                              r"Thread is no longer available\.\n")
        self.assertRegex(err, r"\n\S+Z tick: can't read the coordinator's thread")
        self.threads["lead"] = thread("completed", 40)
        del self.prs["acme/app#7"]  # review-loop r1: a PR read names gh's reason too
        self.assertRegex(self.tick("--send").stderr, r"\S+Z tick: `gh pr view 7 -R acme/app` exited 1: no pull requests found")

    def test_a_project_whose_coordinator_is_on_another_machine_is_left_to_that_machine(self):
        # Nov 23 to 26, 2026: a linked machine's timer logged "can't read the coordinator's thread" 410 times for
        # a copy of a Mac project, every 10 minutes, since its T3 can't read a Mac thread.
        (self.fake / "userdata" / "environment-id").write_text("linked\n")
        result = self.tick("--send")
        self.assertEqual((result.stderr, self.sent(), (self.dir / "tick.json").exists()), ("", [], False))
        self.assertEqual(self.tick().stdout, "its coordinator's thread is on environment env, not this machine's "
                                             "linked, so that machine's timer ticks it\n")
        (self.fake / "userdata" / "environment-id").unlink()  # unknown: ticks as before
        self.threads["w1"] = thread("completed", 2)
        self.tick("--send")
        self.tick("--send")
        self.assertEqual(len(self.sent()), 1)

    def test_tick_sh_ticks_each_project_and_stamps_its_run(self):
        other = self.dir.parent / "parked"
        other.mkdir()
        (other / "project.md").write_text((self.dir / "project.md").read_text().replace("Heartbeat: tick", "Heartbeat: none"))
        self.write_project(remote="running")
        (self.fake / "threads.json").write_text(json.dumps(self.threads))
        (self.fake / "prs.json").write_text(json.dumps(self.prs))
        env = {**os.environ, "FAKE": str(self.fake), "T3CODE_HOME": str(self.fake),
               "PATH": f"{self.fake / 'bin'}:{os.environ['PATH']}"}
        subprocess.run([str(HERE / "tick.sh"), str(self.dir.parent)], env=env, check=True)
        self.assertEqual([m["to"] for m in self.sent()], ["lead"])
        self.assertLess(time.time() - (self.dir.parent / ".tick").stat().st_mtime, 60)
        self.assertFalse((other / "tick.json").exists())


if __name__ == "__main__":
    unittest.main()
