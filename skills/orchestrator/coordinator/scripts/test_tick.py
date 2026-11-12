"""project.py tick and tick.sh against fake `t3` and `gh` on PATH, which serve thread and PR
state from JSON files and record each `t3 thread send`. The rule under test: a change T3
doesn't tell the coordinator wakes it once, and an unchanged project wakes nothing.
Run: python3 -m unittest discover -s coordinator/scripts"""
import json, os, pathlib, subprocess, sys, tempfile, time, unittest

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
| build | <t3-thread://v2/env/w1> · task t1 | `export` · #12 | running | — | pushed abc |
| probe | <t3-thread://v2/env/w2> · task t2 | — | done | — | report |
| remote | <t3-thread://v2/other/w3> · task t3 | — | {remote} | — | launched |

## Listening

- Heartbeat: {heartbeat}
- Startup: none
- Watches: #12 (build), acme/app#7 (the user)
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
repo = args[args.index("-R") + 1] if "-R" in args else ""
prs = json.load(open(os.environ["FAKE"] + "/prs.json"))
key = f"{repo}#{args[2]}"
if key not in prs:
    sys.exit("no pull requests found")
print(json.dumps(prs[key]))
"""


def thread(status="running", runs=1, items=10, asked=0, **more):
    return {"status": status, "runCount": runs, "itemCount": items, "pendingRequestCount": asked, **more}


class Tick(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.root)])
        self.fake, self.dir = self.root / "fake", self.root / "orchestrate" / "export"
        (self.fake / "bin").mkdir(parents=True)
        self.dir.mkdir(parents=True)
        for name, body in [("t3", FAKE_T3), ("gh", FAKE_GH)]:
            (self.fake / "bin" / name).write_text(body)
            (self.fake / "bin" / name).chmod(0o755)
        self.write_project()
        self.threads = {"lead": thread("completed", 40), "w1": thread()}
        self.prs = {"#12": {"state": "OPEN", "isDraft": True}, "acme/app#7": {"state": "OPEN", "isDraft": False}}

    def write_project(self, heartbeat="tick", remote="done", rows=None):
        text = PROJECT.format(checkout=self.root, heartbeat=heartbeat, remote=remote)
        for old, new in (rows or {}).items():
            text = text.replace(old, new)
        (self.dir / "project.md").write_text(text)

    def tick(self, *args, code=0, send_code=0):
        (self.fake / "threads.json").write_text(json.dumps(self.threads))
        (self.fake / "prs.json").write_text(json.dumps(self.prs))
        env = {**os.environ, "FAKE": str(self.fake), "SEND_CODE": str(send_code),
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
        self.prs["#12"] = {"state": "MERGED", "isDraft": False}
        self.prs["acme/app#7"] = {"state": "OPEN", "isDraft": True}
        self.tick("--send")
        [sent] = self.sent()
        self.assertIn("- #12: merged\n", sent["message"])
        self.assertIn("- acme/app#7: turned draft\n", sent["message"])
        self.tick("--send")
        self.assertEqual(self.sent(), [])

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

    def test_nothing_is_checked_while_the_coordinator_runs(self):
        self.tick("--send")
        self.threads["lead"] = thread("running", 41)
        self.prs["#12"] = {"state": "MERGED", "isDraft": False}
        before = self.state()
        self.tick("--send")
        self.assertEqual((self.sent(), self.state()), ([], before))
        self.threads["lead"] = thread("completed", 41)
        self.tick("--send")
        self.assertIn("- #12: merged\n", self.sent()[0]["message"], "its turn over, the change is still news")

    def test_a_failed_send_keeps_the_state_so_the_next_tick_retries(self):
        self.tick("--send")
        self.prs["#12"] = {"state": "CLOSED", "isDraft": True}
        before = self.state()
        result = self.tick("--send", code=1, send_code=1)
        self.assertIn("t3 thread send failed", result.stderr)
        self.assertEqual(self.state(), before)
        self.sent()
        self.tick("--send")
        self.assertIn("- #12: closed\n", self.sent()[0]["message"])

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

    def test_tick_sh_ticks_each_project_and_stamps_its_run(self):
        other = self.dir.parent / "parked"
        other.mkdir()
        (other / "project.md").write_text((self.dir / "project.md").read_text().replace("Heartbeat: tick", "Heartbeat: none"))
        self.write_project(remote="running")
        (self.fake / "threads.json").write_text(json.dumps(self.threads))
        (self.fake / "prs.json").write_text(json.dumps(self.prs))
        env = {**os.environ, "FAKE": str(self.fake), "PATH": f"{self.fake / 'bin'}:{os.environ['PATH']}"}
        subprocess.run([str(HERE / "tick.sh"), str(self.dir.parent)], env=env, check=True)
        self.assertEqual([m["to"] for m in self.sent()], ["lead"])
        self.assertLess(time.time() - (self.dir.parent / ".tick").stat().st_mtime, 60)
        self.assertFalse((other / "tick.json").exists())


if __name__ == "__main__":
    unittest.main()
