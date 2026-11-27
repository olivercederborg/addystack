"""project.snapshot and status_server.py on project folders shaped like a real
orchestrate folder: a project.md, the tick's tick.json beside it, and the timer's .tick
stamp above them. The server reads files only, so no fake `t3` or `gh` is needed.
Run: python3 -m unittest discover -s coordinator/scripts"""
import json, os, pathlib, subprocess, sys, tempfile, unittest, unittest.mock

import project

PROJECT = """# ◆ export

Coordinator: <t3-thread://v2/env/lead> · Checkout: {checkout} (on `main`) · Mode: personal

## Goal

Ship the export.
Proof: #12 merged.
Follow-ups: none

## Queue

Next id: 2

| # | Kind | Name | From | Since |
|---|---|---|---|---|
| 1 | decide | pick the export format | coordinator | 2026-11-20 09:00 |

## Decisions

## Workers

| Worker | Thread | Branch or PR | State | Waits on | Last side effect |
|---|---|---|---|---|---|
| build | <t3-thread://v2/env/w1> · task t1 | `export` · #12 | running | — | pushed abc |
| probe | <t3-thread://v2/env/w2> · task t2 | #13 | done | — | report |

## Listening

- Heartbeat: tick
- Startup: none
- Watches: none
"""

TICK = {"threads": {"w1": {"status": "completed", "runs": 2, "items": 40, "asked": 0, "since": 1.0},
                    "w2": {"status": "running", "runs": 1, "items": 5, "asked": 0, "since": 1.0}},
        "prs": {"acme/app#12": ["OPEN", True], "acme/app#13": ["MERGED", False]}, "sent": {}}


class Folders:
    """An orchestrate folder in a scratch directory, a git checkout whose origin is
    acme/app, and T3's environment id `env`, as this machine's."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.root)])
        self.orchestrate = self.root / "orchestrate"
        self.orchestrate.mkdir()
        (self.root / "t3" / "userdata").mkdir(parents=True)
        (self.root / "t3" / "userdata" / "environment-id").write_text("env\n")
        self.checkout = self.root / "app"
        subprocess.run(["git", "init", "-q", str(self.checkout)], check=True)
        subprocess.run(["git", "-C", str(self.checkout), "remote", "add", "origin", "git@github.com:acme/app.git"],
                       check=True)
        environment = unittest.mock.patch.dict(os.environ, {"T3CODE_HOME": str(self.root / "t3")})
        environment.start()
        self.addCleanup(environment.stop)

    def write(self, name="export", text=PROJECT, **replace):
        folder = self.orchestrate / name
        folder.mkdir(exist_ok=True)
        text = text.format(checkout=self.checkout)
        for old, new in replace.items():
            text = text.replace(old, new)
        (folder / "project.md").write_text(text)
        return folder

    def tick(self, folder, state=TICK):
        (folder / "tick.json").write_text(json.dumps(state))


class Snapshot(Folders, unittest.TestCase):
    def units(self, card):
        return {unit["worker"]: unit for group in card["data"]["groups"] for unit in group["units"]}

    def test_a_running_project_is_active_with_its_queue_and_file_times(self):
        folder = self.write()
        card = project.snapshot(folder)
        self.assertEqual((card["folder"], card["state"], card["phase"], card["tickOn"]), ("export", "ok", "active", True))
        self.assertEqual(card["data"]["project"], "export")
        self.assertEqual([item["name"] for item in card["data"]["queue"]], ["pick the export format"])
        self.assertEqual(card["asOf"], {"project": (folder / "project.md").stat().st_mtime, "tick": None})

    def test_without_tick_json_no_thread_or_pr_state_is_filled(self):
        build = self.units(project.snapshot(self.write()))["build"]
        self.assertNotIn("thread_status", build)
        self.assertEqual(build["prs"], [{"ref": "acme/app#12", "name": "#12", "url": "https://github.com/acme/app/pull/12"}])

    def test_tick_json_fills_each_live_rows_thread_and_each_prs_state(self):
        folder = self.write()
        self.tick(folder)
        card = project.snapshot(folder)
        units = self.units(card)
        self.assertEqual(units["build"]["thread_status"], "completed")
        self.assertEqual((units["build"]["prs"][0]["state"], units["build"]["prs"][0]["draft"]), ("OPEN", True))
        self.assertNotIn("thread_status", units["probe"])  # a done row's thread is never shown, as live status does
        self.assertEqual((units["probe"]["prs"][0]["state"], units["probe"]["prs"][0]["draft"]), ("MERGED", False))
        self.assertEqual(card["asOf"]["tick"], (folder / "tick.json").stat().st_mtime)

    def test_a_parked_project_is_parked(self):
        folder = self.write(**{"Ship the export.\nProof: #12 merged.": "Parked 2026-11-20: waiting on the API"})
        self.assertEqual(project.snapshot(folder)["phase"], "parked")

    def test_a_result_with_no_live_row_is_closed(self):
        folder = self.write(**{"## Queue": "## Result\n\nShipped #12.\n\n## Queue", "| running |": "| done |"})
        self.assertEqual(project.snapshot(folder)["phase"], "closed")

    def test_a_result_beside_a_live_row_or_a_goal_it_cant_read_is_unknown(self):
        interim = self.write("interim", **{"## Queue": "## Result (interim, 2026-11-20)\n\nShipped #13.\n\n## Queue"})
        odd = self.write("odd", **{"## Queue": "## Result\n\n## Queue", "| running |": "| done |",
                                   "## Listening": "| odd | broken | row |\n\n## Listening"})
        goalless = self.write("goalless", **{"## Goal\n\nShip the export.": "## Aim\n\nShip the export."})
        for folder in (interim, odd, goalless):
            with self.subTest(folder.name):
                card = project.snapshot(folder)
                self.assertEqual((card["state"], card["phase"]), ("ok", "unknown"))

    def test_a_project_from_before_the_queue_has_a_null_queue(self):
        start = PROJECT.index("## Queue")
        folder = self.write(text=PROJECT[:start] + PROJECT[PROJECT.index("## Decisions"):])
        card = project.snapshot(folder)
        self.assertEqual((card["state"], card["phase"], card["data"]["queue"]), ("ok", "active", None))

    def test_a_file_it_cant_read_or_parse_gives_an_unknown_card_with_the_reason(self):
        unreadable = self.write("unreadable")
        (unreadable / "project.md").write_bytes(b"# \xff\xfe not text\n")
        broken_tick = self.write("broken-tick")
        (broken_tick / "tick.json").write_text("{not json")
        odd_tick = self.write("odd-tick")
        self.tick(odd_tick, {"threads": [], "prs": {}})
        missing = self.orchestrate / "missing"
        missing.mkdir()
        for folder in (unreadable, broken_tick, odd_tick, missing):
            with self.subTest(folder.name):
                card = project.snapshot(folder)
                self.assertEqual(set(card), {"folder", "state", "error", "asOf"})
                self.assertEqual((card["folder"], card["state"]), (folder.name, "unknown"))
                self.assertTrue(card["error"])
        self.assertIsNone(project.snapshot(missing)["asOf"]["project"])
        self.assertIsNotNone(project.snapshot(broken_tick)["asOf"]["tick"])

    def test_the_tick_is_on_only_while_heartbeat_is_tick_and_the_coordinator_is_on_this_machine(self):
        cases = {"on": ({}, True), "none": ({"- Heartbeat: tick": "- Heartbeat: none"}, False),
                 "elsewhere": ({"v2/env/lead": "v2/other/lead"}, False),
                 "no-listening": ({"## Listening\n\n- Heartbeat: tick": "## Notes\n\n- Heartbeat: tick"}, False)}
        for name, (replace, on) in cases.items():
            with self.subTest(name):
                self.assertIs(project.snapshot(self.write(name, **replace))["tickOn"], on)
        with unittest.mock.patch.dict(os.environ, {"T3CODE_HOME": str(self.root / "nowhere")}):
            self.assertIs(project.snapshot(self.orchestrate / "on")["tickOn"], False)  # this machine's id unknown


if __name__ == "__main__":
    unittest.main()
