"""project.snapshot and status_server.py on project folders shaped like a real
orchestrate folder: a project.md, the tick's tick.json beside it, and the timer's .tick
stamp above them. The server reads files only, so no fake `t3` or `gh` is needed.
Run: python3 -m unittest discover -s coordinator/scripts"""
import http.client, json, os, pathlib, socket, subprocess, sys, tempfile, threading, time, unittest, unittest.mock

import project
import status_server

HERE = pathlib.Path(__file__).resolve().parent

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
        self.assertIsNone(card["asOf"]["tick"])  # TICK's looks hold no read times, so they're undated

    def test_a_state_the_tick_kept_from_an_older_look_dates_the_card(self):
        folder = self.write()
        now = time.time()
        threads = {key: {**value, "at": now - 60} for key, value in TICK["threads"].items()}
        # #12 wasn't read for an hour, as while the coordinator runs, though the tick rewrote the file.
        self.tick(folder, {**TICK, "threads": threads, "prsAt": {"acme/app#12": now - 3600, "acme/app#13": now - 60}})
        self.assertEqual(project.snapshot(folder)["asOf"]["tick"], now - 3600)

    def test_a_live_row_the_tick_holds_no_look_for_leaves_the_card_with_no_tick_data(self):
        folder = self.write()
        now = time.time()
        # The tick's first read of w1 failed, so it wrote no thread, though it read #12.
        self.tick(folder, {"threads": {}, "prs": TICK["prs"], "prsAt": {"acme/app#12": now, "acme/app#13": now},
                           "sent": {}})
        self.assertIsNone(project.snapshot(folder)["asOf"]["tick"])

    def test_a_read_time_that_isnt_a_number_leaves_the_card_with_no_tick_data(self):
        folder = self.write()
        threads = {"w1": {**TICK["threads"]["w1"], "at": "bad"}, "w2": TICK["threads"]["w2"]}
        self.tick(folder, {**TICK, "threads": threads, "prsAt": {"acme/app#12": 1.0, "acme/app#13": 1.0}})
        card = project.snapshot(folder)
        self.assertEqual((card["state"], card["asOf"]["tick"]), ("ok", None))
        self.assertEqual([item["name"] for item in card["data"]["queue"]], ["pick the export format"])

    def test_the_tick_keeps_each_reads_time_and_an_older_one_for_a_pr_it_couldnt_read(self):
        lines = PROJECT.format(checkout=self.checkout).split("\n")
        show = lambda thread: {"status": "running", "runCount": 1, "itemCount": 3, "updatedAt": None}
        _, first = project.tick(lines, {}, 100.0, show=show, view=lambda ref: ["OPEN", False], hold=False)
        _, second = project.tick(lines, first, 200.0, show=show, view=lambda ref: None, hold=False)
        self.assertEqual((first["threads"]["w1"]["at"], first["prsAt"]), (100.0, {"acme/app#12": 100.0}))
        self.assertEqual((second["threads"]["w1"]["at"], second["prsAt"]), (200.0, {"acme/app#12": 100.0}))

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

    def test_an_empty_result_a_workers_table_it_cant_read_or_a_parked_goal_beside_a_live_row_is_unknown(self):
        result = {"## Queue": "## Result\n\nShipped #12.\n\n## Queue", "| running |": "| done |"}
        empty = self.write("empty", **{**result, "## Result\n\nShipped #12.": "## Result\n"})
        headless = self.write("headless", **{**result, "|---|---|---|---|---|---|\n": ""})
        stateless = self.write("stateless", **{**result, "| State |": "| Status |"})
        parked = self.write("parked", **{"## Queue": "## Result\n\nShipped #13.\n\n## Queue",
                                         "Ship the export.\nProof: #12 merged.": "Parked 2026-11-20: waiting"})
        workerless = self.write("workerless", **{**result, "## Workers": "## Notes"})
        for folder in (empty, headless, stateless, parked, workerless):
            with self.subTest(folder.name):
                self.assertEqual(project.snapshot(folder)["phase"], "unknown")

    def test_a_project_from_before_the_queue_has_a_null_queue(self):
        start = PROJECT.index("## Queue")
        folder = self.write(text=PROJECT[:start] + PROJECT[PROJECT.index("## Decisions"):])
        card = project.snapshot(folder)
        self.assertEqual((card["state"], card["phase"], card["data"]["queue"]), ("ok", "active", None))

    def test_a_project_md_it_cant_read_gives_an_unknown_card_with_the_reason(self):
        unreadable = self.write("unreadable")
        (unreadable / "project.md").write_bytes(b"# \xff\xfe not text\n")
        missing = self.orchestrate / "missing"
        missing.mkdir()
        for folder in (unreadable, missing):
            with self.subTest(folder.name):
                card = project.snapshot(folder)
                self.assertEqual(set(card), {"folder", "state", "error", "asOf"})
                self.assertEqual((card["folder"], card["state"]), (folder.name, "unknown"))
                self.assertTrue(card["error"])
        self.assertIsNone(project.snapshot(missing)["asOf"]["project"])

    def test_a_tick_json_it_cant_read_still_shows_the_queue_with_no_tick_data(self):
        broken_tick = self.write("broken-tick")
        (broken_tick / "tick.json").write_text("{not json")
        odd_tick = self.write("odd-tick")
        self.tick(odd_tick, {"threads": [], "prs": {}})
        for folder in (broken_tick, odd_tick):
            with self.subTest(folder.name):
                card = project.snapshot(folder)
                self.assertEqual((card["state"], card["asOf"]["tick"]), ("ok", None))
                self.assertEqual([item["name"] for item in card["data"]["queue"]], ["pick the export format"])
                self.assertNotIn("thread_status", self.units(card)["build"])

    def test_the_tick_is_on_only_while_heartbeat_is_tick_and_the_coordinator_is_on_this_machine(self):
        cases = {"on": ({}, True), "none": ({"- Heartbeat: tick": "- Heartbeat: none"}, False),
                 "elsewhere": ({"v2/env/lead": "v2/other/lead"}, False),
                 "no-listening": ({"## Listening\n\n- Heartbeat: tick": "## Notes\n\n- Heartbeat: tick"}, False)}
        for name, (replace, on) in cases.items():
            with self.subTest(name):
                self.assertIs(project.snapshot(self.write(name, **replace))["tickOn"], on)
        with unittest.mock.patch.dict(os.environ, {"T3CODE_HOME": str(self.root / "nowhere")}):
            self.assertIs(project.snapshot(self.orchestrate / "on")["tickOn"], False)  # this machine's id unknown


class Page(Folders, unittest.TestCase):
    def test_the_signature_changes_with_project_md_tick_json_and_the_timer_stamp(self):
        folder = self.write()
        (self.orchestrate / "reports").mkdir()  # a folder with no project.md isn't a project
        seen = status_server.signature(self.orchestrate)
        self.assertEqual([row[0] for row in seen[:-1]], ["export"])
        for path in (folder / "project.md", folder / "tick.json", self.orchestrate / ".tick"):
            with self.subTest(path.name):
                path.touch()
                os.utime(path, ns=(10**18, 10**18 + len(seen)))
                self.assertNotEqual(status_server.signature(self.orchestrate), seen)
                self.assertNotEqual(status_server.tag(status_server.signature(self.orchestrate)), status_server.tag(seen))
                seen = status_server.signature(self.orchestrate)
        self.assertEqual(status_server.tag(seen), status_server.tag(status_server.signature(self.orchestrate)))

    def test_a_folder_it_cant_look_into_shows_as_unknown_and_an_unlisted_root_says_so(self):
        self.write("readable")
        hidden = self.write("hidden")
        hidden.chmod(0)
        self.addCleanup(hidden.chmod, 0o755)
        cards = {card["folder"]: card for card in status_server.collect(self.orchestrate)["projects"]}
        self.assertEqual((cards["readable"]["state"], cards["hidden"]["state"]), ("ok", "unknown"))
        self.orchestrate.chmod(0)
        self.addCleanup(self.orchestrate.chmod, 0o755)
        [card] = status_server.collect(self.orchestrate)["projects"]
        self.assertEqual((card["folder"], card["state"]), ("orchestrate", "unknown"))
        self.assertIn("can't list", card["error"])
        self.assertEqual(status_server.signature(self.orchestrate)[0][:2], ("", "unlisted"))

    def test_a_file_turning_readable_changes_the_signature(self):
        folder = self.write()
        path = folder / "project.md"
        path.chmod(0)
        self.addCleanup(path.chmod, 0o644)
        seen = status_server.signature(self.orchestrate)
        time.sleep(0.01)
        path.chmod(0o644)
        self.assertNotEqual(status_server.signature(self.orchestrate), seen)

    def test_projects_come_unknown_and_active_first_then_parked_then_closed_and_more_queue_items_first(self):
        self.write("closed", **{"## Queue": "## Result\n\nShipped #12.\n\n## Queue", "| running |": "| done |"})
        self.write("parked", **{"Ship the export.\nProof: #12 merged.": "Parked 2026-11-20: waiting"})
        self.write("quiet", **{"| 1 | decide | pick the export format | coordinator | 2026-11-20 09:00 |\n": ""})
        self.write("busy", **{"Next id: 2": "Next id: 3", "| coordinator | 2026-11-20 09:00 |":
                              "| coordinator | 2026-11-20 09:00 |\n| 2 | do | rotate the key | coordinator | 2026-11-20 |"})
        self.write("active")
        broken = self.orchestrate / "broken"
        broken.mkdir()
        (broken / "project.md").write_bytes(b"\xff")
        (self.orchestrate / ".tick").touch()
        page = status_server.collect(self.orchestrate)
        self.assertEqual([card["folder"] for card in page["projects"]],
                         ["busy", "active", "broken", "quiet", "parked", "closed"])
        self.assertEqual(page["staleAfter"], project.STALE)
        self.assertEqual(page["timer"], (self.orchestrate / ".tick").stat().st_mtime)
        self.assertTrue(page["machine"])
        (self.orchestrate / ".tick").unlink()
        self.assertIsNone(status_server.collect(self.orchestrate)["timer"])


class Server(Folders, unittest.TestCase):
    """A real server on an ephemeral port, in this process, so status.html's path can move."""

    def setUp(self):
        super().setUp()
        self.folder = self.write()
        self.server = status_server._Server(0, self.orchestrate)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path="/overview.json", host=None, etag=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(connection.close)
        headers = {"Host": host or f"localhost:{self.port}", **({"If-None-Match": etag} if etag else {})}
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        body = response.read()
        self.assertEqual(response.getheader("Server"), status_server.SERVER)
        self.assertFalse([name for name, _ in response.getheaders() if name.lower().startswith("access-control-")])
        return response, body

    def test_an_unchanged_poll_is_304_until_a_project_changes(self):
        response, body = self.get()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "application/json; charset=utf-8")
        self.assertEqual(response.getheader("Cache-Control"), "no-cache")
        etag = response.getheader("ETag")
        self.assertTrue(etag.startswith('"'))
        self.assertEqual([card["folder"] for card in json.loads(body)["projects"]], ["export"])
        response, body = self.get(etag=etag)
        self.assertEqual((response.status, body, response.getheader("ETag")), (304, b"", etag))
        added = subprocess.run([sys.executable, str(HERE / "project.py"), str(self.folder), "queue", "add", "do",
                                "rotate the export key"], capture_output=True, text=True)
        self.assertEqual(added.returncode, 0, added.stderr)
        response, body = self.get(etag=etag)
        self.assertEqual(response.status, 200)
        self.assertNotEqual(response.getheader("ETag"), etag)
        self.assertEqual(len(json.loads(body)["projects"][0]["data"]["queue"]), 2)
        self.assertEqual(self.get(host=f"127.0.0.1:{self.port}", etag=response.getheader("ETag"))[0].status, 304)

    def test_a_foreign_host_gets_403_and_any_other_path_404(self):
        for host in ("evil.example", f"evil.example:{self.port}", f"localhost:{self.port + 1}", f"localhost"):
            with self.subTest(host):
                self.assertEqual(self.get(host=host)[0].status, 403)
        self.assertEqual(self.get("/projects")[0].status, 404)
        self.assertEqual(self.get("/overview.json?x=1")[0].status, 200)

    def test_text_holding_script_comes_out_as_text_in_the_json(self):
        text = "check <script>alert(1)</script> & <b>"
        self.write(**{"pick the export format": text})
        response, body = self.get()
        self.assertNotIn(b"<", body)
        self.assertNotIn(b">", body)
        self.assertNotIn(b"&", body)
        self.assertEqual(json.loads(body)["projects"][0]["data"]["queue"][0]["name"], text)

    def test_the_page_is_status_html_beside_the_script_and_503_until_it_is_there(self):
        page = self.root / "status.html"
        with unittest.mock.patch.object(status_server, "PAGE", page):
            response, body = self.get("/")
            self.assertEqual((response.status, response.getheader("Content-Type")), (503, "text/plain; charset=utf-8"))
            page.write_text("<!doctype html><title>status</title>")
            response, body = self.get("/")
        self.assertEqual((response.status, response.getheader("Content-Type"), body),
                         (200, "text/html; charset=utf-8", page.read_bytes()))

    def test_the_page_served_is_the_unbaked_template_which_polls_the_overview(self):
        response, body = self.get("/")
        self.assertEqual((response.status, body), (200, status_server.PAGE.read_bytes()))
        page = body.decode()
        self.assertEqual(page.count(project.STATUS_DATA), 1)  # null, so the page runs in live mode
        for hook in ('fetch("/overview.json"', '"If-None-Match"', "setTimeout(poll, 2000)",
                     'location.protocol === "http:"', "function draw(data, root"):
            self.assertIn(hook, page)
        self.assertNotRegex(page, r"setInterval|innerHTML|<(script|link)[^>]+src=")


class Main(Folders, unittest.TestCase):
    def test_main_serves_the_root_it_is_given_on_the_port_it_is_given(self):
        self.write()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        process = subprocess.Popen([sys.executable, str(HERE / "status_server.py"), "--port", str(port), "--root",
                                    str(self.orchestrate)], stderr=subprocess.PIPE)
        self.addCleanup(process.stderr.close)
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        for _ in range(100):
            try:
                connection = http.client.HTTPConnection("localhost", port, timeout=10)
                connection.request("GET", "/overview.json")
                response = connection.getresponse()
                break
            except ConnectionRefusedError:
                time.sleep(0.05)
        else:
            self.fail(f"nothing answered on {port}: {process.stderr.read() if process.poll() is not None else ''}")
        self.assertEqual((response.status, response.getheader("Server")), (200, status_server.SERVER))
        self.assertEqual([card["folder"] for card in json.loads(response.read())["projects"]], ["export"])
        connection.close()
        busy = subprocess.run([sys.executable, str(HERE / "status_server.py"), "--port", str(port)],
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(busy.returncode, 1)
        self.assertIn(f"can't serve 127.0.0.1:{port}", busy.stderr)


if __name__ == "__main__":
    unittest.main()
