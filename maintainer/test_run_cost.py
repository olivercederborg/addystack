import contextlib
import datetime
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import run_cost  # noqa: E402
import t3_child  # noqa: E402  run_cost puts hooks/ on the path.

OPUS = {"input_cost_per_token": 1e-6, "cache_creation_input_token_cost": 2e-6,
        "cache_creation_input_token_cost_above_1hr": 3e-6, "cache_read_input_token_cost": 1e-7,
        "output_cost_per_token": 5e-6}
SOL = {"input_cost_per_token": 2e-6, "cache_creation_input_token_cost": 4e-6,
       "cache_read_input_token_cost": 2e-7, "output_cost_per_token": 1e-5}


def lines(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def reply(message_id, usage, model="claude-opus-5-5", at="2026-10-29T00:05:00Z"):
    return {"type": "assistant", "timestamp": at,
            "message": {"id": message_id, "model": model, "role": "assistant", "usage": usage, "content": []}}


def rollout(session_id, totals, model="gpt-6.1-sol"):
    records = [{"type": "session_meta", "payload": {"id": session_id}},
               {"type": "turn_context", "payload": {"model": model}},
               {"type": "event_msg", "payload": {"type": "token_count", "info": None}}]
    for inp, cached, write, out in totals:
        records.append({"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {
            "input_tokens": inp, "cached_input_tokens": cached, "cache_write_input_tokens": write,
            "output_tokens": out, "reasoning_output_tokens": 1}}}})
    return records


def state_db(path, threads, links):
    """threads: (thread id, driver, native id); links: (parent thread, child thread, origin)."""
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        db.execute("create table orchestration_v2_projection_provider_threads (provider_thread_id text, "
                   "thread_id text, first_run_ordinal integer, payload_json text, driver text)")
        db.execute("create table orchestration_v2_projection_subagents (thread_id text, child_thread_id text, "
                   "origin text, started_at text)")
        for n, (thread, driver, native) in enumerate(threads):
            db.execute("insert into orchestration_v2_projection_provider_threads values (?, ?, 1, ?, ?)",
                       (f"pt{n}", thread, json.dumps({"nativeThreadRef": {"driver": driver, "nativeId": native}}),
                        driver))
        for n, (parent, child, origin) in enumerate(links):
            db.execute("insert into orchestration_v2_projection_subagents values (?, ?, ?, ?)",
                       (parent, child, origin, f"2026-10-29T00:0{n}:00Z"))
    return path


class Fixture(unittest.TestCase):
    """A player (Claude P) with a native subagent, a delegated Claude child C, a delegated
    Codex child X spread over two rollout files with its own native child Y, a Claude
    provider_native thread T3 records without a provider thread, a Codex child Z whose
    rollout isn't on this machine, and a subagents row that loops back to the player."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = pathlib.Path(folder.name)
        self.projects, self.codex = root / "projects", root / "sessions"
        rates = root / "rates.json"
        rates.write_text(json.dumps({"fetchedAtMs": 1, "document": {"claude-opus-5-5": OPUS, "gpt-6.1-sol": SOL}}))
        self.player = lines(self.projects / "-tmp-repo" / "P.jsonl", [
            {"type": "user", "timestamp": "2026-10-29T00:00:00Z", "message": {"role": "user", "content": "go"}},
            reply("m1", {"input_tokens": 10, "cache_read_input_tokens": 100, "output_tokens": 1}),
            reply("m1", {"input_tokens": 10, "cache_read_input_tokens": 100, "output_tokens": 5}),
            reply("m2", {"input_tokens": 2, "cache_creation_input_tokens": 300, "cache_read_input_tokens": 50,
                         "output_tokens": 7, "cache_creation": {"ephemeral_5m_input_tokens": 100,
                                                                "ephemeral_1h_input_tokens": 200}}),
            reply("syn", {"input_tokens": 0, "output_tokens": 0}, model="<synthetic>"),
            reply("m2b", {"input_tokens": 1, "output_tokens": 1}, at="2026-10-29T00:10:30Z"),
        ])
        self.subagent = lines(self.projects / "-tmp-repo" / "P" / "subagents" / "agent-x.jsonl", [
            reply("m3", {"input_tokens": 1, "cache_creation_input_tokens": 40, "output_tokens": 3}),
            reply("m2", {"input_tokens": 2, "output_tokens": 999}),  # copied from the player: counted once
        ])
        self.child = lines(self.projects / "-tmp-child" / "C.jsonl", [
            reply("m4", {"input_tokens": 5, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 1000,
                         "output_tokens": 20, "cache_creation": {"ephemeral_1h_input_tokens": 10}}),
        ])
        self.x1 = lines(self.codex / "2026" / "10" / "28" / "rollout-2026-10-28T23-00-00-X.jsonl",
                        rollout("X", [(100, 60, 0, 10), (200, 150, 0, 30), (300, 200, 5, 40)]))
        self.x2 = lines(self.codex / "2026" / "10" / "29" / "rollout-2026-10-29T00-01-00-X.jsonl",
                        rollout("X", [(50, 20, 0, 4)]))
        self.y = lines(self.codex / "2026" / "10" / "29" / "rollout-2026-10-29T00-02-00-Y.jsonl",
                       rollout("Y", [(10, 0, 0, 1)]))
        self.db = state_db(root / "state.sqlite", [
            ("thread:parent", "claudeAgent", "P"),
            ("thread:claude", "claudeAgent", "C"),
            ("thread:codex", "codex", "X"),
            ("thread:codex-native", "codex", "Y"),
            ("thread:gone", "codex", "Z"),
        ], [
            ("thread:parent", "thread:claude", "app_owned"),
            ("thread:parent", "thread:codex", "app_owned"),
            ("thread:parent", "thread:claude-native", "provider_native"),
            ("thread:codex", "thread:codex-native", "provider_native"),
            ("thread:codex-native", "thread:parent", "provider_native"),
            ("thread:claude", "thread:gone", "app_owned"),
        ])
        for patch in (mock.patch.object(run_cost, "PROJECTS", self.projects),
                      mock.patch.object(run_cost, "CODEX_SESSIONS", self.codex),
                      mock.patch.object(run_cost, "RATES", rates),
                      mock.patch.object(t3_child, "STATE_DB", str(self.db))):
            patch.start()
            self.addCleanup(patch.stop)


class SessionTreeTest(Fixture):
    def test_walks_every_child_once_root_first(self):
        self.assertEqual(t3_child.session_tree("P"), [
            ("claudeAgent", "P"), ("claudeAgent", "C"), ("codex", "X"), ("codex", "Z"), ("codex", "Y")])

    def test_unknown_session_raises(self):
        with self.assertRaisesRegex(LookupError, "no T3 thread ran session nope"):
            t3_child.session_tree("nope")

    def test_unreadable_db_raises(self):
        with mock.patch.object(t3_child, "STATE_DB", str(self.db.parent / "missing" / "db")), \
                self.assertRaises(sqlite3.Error):
            t3_child.session_tree("P")


class MeasureTest(Fixture):
    def test_totals_and_usd(self):
        cost = run_cost.measure(self.player)
        self.assertEqual([s["path"] for s in cost["sessions"]],
                         [str(p) for p in (self.player, self.subagent, self.child, self.x1, self.x2, self.y)])
        self.assertEqual(cost["sessions"][0]["models"], {"claude-opus-5-5": {
            "input": 13, "cache_write": 300, "cache_read": 150, "output": 13}})
        self.assertEqual(cost["sessions"][1]["models"]["claude-opus-5-5"],
                         {"input": 1, "cache_write": 40, "cache_read": 0, "output": 3})
        self.assertEqual(cost["sessions"][3]["models"]["gpt-6.1-sol"],
                         {"input": 100, "cache_write": 5, "cache_read": 200, "output": 40})
        # Claude: P 13/5m 100/1h 200/150/13, subagent 1/5m 40/0/3, C 5/1h 10/1000/20.
        # Codex: X 100+30 input, 5 written, 200+20 read, 40+4 out; Y 10 input, 1 out.
        self.assertEqual(cost["tokens"], {"input": 13 + 1 + 5 + 130 + 10, "cache_write": 300 + 40 + 10 + 5,
                                          "cache_read": 150 + 1000 + 220, "output": 13 + 3 + 20 + 44 + 1})
        claude = 19 * 1e-6 + 140 * 2e-6 + 210 * 3e-6 + 1150 * 1e-7 + 36 * 5e-6
        codex = 140 * 2e-6 + 5 * 4e-6 + 220 * 2e-7 + 45 * 1e-5
        self.assertAlmostEqual(cost["usd"], claude + codex, places=12)
        self.assertEqual(cost["wall_s"], 630.0)
        self.assertEqual(cost["missing"], ["codex Z: no rollout file"])
        self.assertEqual(cost["unpriced"], [])
        self.assertEqual(cost["rates"]["claude-opus-5-5"]["cache_write_1h"], 3e-6)
        self.assertNotIn("cache_write_1h", cost["rates"]["gpt-6.1-sol"])
        self.assertEqual(json.loads(json.dumps(cost)), cost)

    def test_wall_time_reads_z_timestamps_before_python_3_11(self):
        class Py310(datetime.datetime):
            @classmethod
            def fromisoformat(cls, value):
                if value.endswith("Z"):
                    raise ValueError(f"Invalid isoformat string: {value!r}")
                return super().fromisoformat(value)

        with mock.patch.object(run_cost.datetime, "datetime", Py310):
            self.assertEqual(run_cost.measure(self.player)["wall_s"], 630.0)

    def test_unknown_model_is_unpriced(self):
        lines(self.child, [reply("m9", {"input_tokens": 5, "output_tokens": 1}, model="claude-mystery")])
        cost = run_cost.measure(self.player)
        self.assertEqual(cost["unpriced"], ["claude-mystery"])
        self.assertIsNone(cost["sessions"][2]["usd"])
        self.assertIsNone(cost["usd"])
        self.assertIsNotNone(cost["sessions"][0]["usd"])

    def test_codex_rollout_as_the_player(self):
        cost = run_cost.measure(self.y)
        self.assertEqual([s["path"] for s in cost["sessions"]],
                         [str(self.y), str(self.player), str(self.subagent), str(self.child),
                          str(self.x1), str(self.x2)])

    def test_untracked_session_raises(self):
        stray = lines(self.projects / "-tmp-repo" / "S.jsonl", [reply("s1", {"input_tokens": 1})])
        with self.assertRaises(LookupError):
            run_cost.measure(stray)

    def test_add_sums_scenarios(self):
        one = run_cost.measure(self.player)
        two = run_cost.add([one, one])
        self.assertEqual(two["tokens"]["cache_read"], 2 * one["tokens"]["cache_read"])
        self.assertAlmostEqual(two["usd"], 2 * one["usd"])
        self.assertEqual(two["wall_s"], 1260.0)
        self.assertIsNone(run_cost.add([one, {**one, "usd": None}])["usd"])


if __name__ == "__main__":
    unittest.main()
