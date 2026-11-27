"""Tests for agent_memory_guard.py on synthetic process snapshots and a few real processes.
Run from hooks/: python3 -m unittest test_agent_memory_guard"""
import contextlib, io, json, os, pathlib, shutil, signal, subprocess, sys, tempfile, time, unittest
from unittest import mock

import agent_memory_guard as guard
from agent_memory_guard import GB, Owners, Proc


def proc(pid, ppid, pgid=None, footprint=0, argv=("sleep",), ident=None, marked=False,
         parent_ident=None, cpu=0, start=0, reaped=0):
    return Proc(pid, ppid, pgid or pid, ident or pid, 1, parent_ident or ppid, footprint,
                list(argv), marked, cpu, start, reaped)


def snapshot(*procs):
    return {p.pid: p for p in procs}


AGENT = proc(100, 50, argv=("claude", "--output-format", "stream-json"))
CODEX = proc(90, 50, argv=("/x/bin/codex", "app-server"))
# Tests that read real processes through libproc, which only macOS has.
MACOS = unittest.skipUnless(sys.platform == "darwin", "libproc is macOS-only")


class Attribution(unittest.TestCase):
    def test_each_agent_child_heads_a_command_that_owns_its_descendants(self):
        commands = Owners().attribute(snapshot(
            AGENT, proc(200, 100), proc(201, 200, pgid=200), proc(202, 201, pgid=200),
            proc(300, 100), proc(400, 1)))
        self.assertEqual({head: sorted(p.pid for p in members)
                          for head, members in commands.items()},
                         {200: [200, 201, 202], 300: [300]})

    def test_agent_is_never_a_member(self):
        commands = Owners().attribute(snapshot(AGENT, proc(200, 100)))
        self.assertNotIn(100, [p.pid for members in commands.values() for p in members])

    def test_orphan_keeps_its_owner_after_the_shell_exits(self):
        owners = Owners()
        owners.attribute(snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=200)))
        commands = owners.attribute(snapshot(AGENT, proc(201, 1, pgid=200)))
        self.assertEqual([p.pid for p in commands[200]], [201])

    def test_orphan_in_its_own_group_keeps_its_owner(self):
        # A detached child (a browser Playwright starts) leads its own group.
        owners = Owners()
        owners.attribute(snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=201)))
        commands = owners.attribute(snapshot(AGENT, proc(201, 1, pgid=201)))
        self.assertEqual([p.pid for p in commands[200]], [201])

    def test_new_orphan_joins_the_command_whose_group_it_is_in(self):
        owners = Owners()
        owners.attribute(snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=200),
                                  proc(203, 201, pgid=200)))
        # 200 exits, and 201 forks 202 and exits before the next tick; 203 lives on.
        commands = owners.attribute(snapshot(AGENT, proc(202, 1, pgid=200),
                                             proc(203, 1, pgid=200)))
        self.assertEqual(sorted(p.pid for p in commands[200]), [202, 203])

    def test_once_the_whole_group_is_gone_an_agent_mark_reestablishes_it(self):
        # The group id could have been reused, so a new orphan needs its own evidence; an
        # unmarked process sharing a live group with a marked one is the same job.
        owners = Owners()
        owners.attribute(snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=200)))
        commands = owners.attribute(snapshot(AGENT, proc(202, 1, pgid=200, marked=True),
                                             proc(204, 1, pgid=200), proc(701, 1, pgid=700)))
        self.assertEqual({head: [p.pid for p in members] for head, members in commands.items()},
                         {202: [202, 204]})

    def test_unmarked_orphans_scanned_before_their_marked_group_mate_join_in_one_tick(self):
        commands = Owners().attribute(snapshot(
            AGENT, proc(204, 1, pgid=200), proc(205, 1, pgid=200), proc(202, 1, pgid=200,
                                                                         marked=True)))
        self.assertEqual(sorted(p.pid for p in commands[202]), [202, 204, 205])

    def test_orphan_in_an_unknown_group_is_left_alone(self):
        commands = Owners().attribute(snapshot(AGENT, proc(500, 1, pgid=500)))
        self.assertEqual(commands, {})

    def test_agent_marked_orphans_no_tick_saw_start_are_grouped_by_process_group(self):
        # `node worker.js &` in a command that exited before the first tick saw it.
        commands = Owners().attribute(snapshot(
            AGENT, proc(501, 1, pgid=500, marked=True), proc(502, 1, pgid=500, marked=True),
            proc(503, 502, pgid=500), proc(601, 1, pgid=600, marked=True)))
        self.assertEqual(sorted(p.pid for p in commands[501]), [501, 502, 503])
        self.assertEqual([p.pid for p in commands[601]], [601])

    def test_reused_group_id_does_not_inherit_the_old_owner(self):
        owners = Owners()
        owners.attribute(snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=200)))
        # The whole command exits; an unrelated app gets pid 200 and leads group 200.
        commands = owners.attribute(snapshot(AGENT, proc(200, 1, ident=9200)))
        self.assertEqual(commands, {})

    def test_reused_group_id_whose_new_leader_exited_is_not_inherited(self):
        owners = Owners()
        owners.attribute(snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=200)))
        # The command exits; a new group 200 forms, its leader exits, an unmarked member stays.
        commands = owners.attribute(snapshot(AGENT, proc(300, 1, pgid=200)))
        self.assertEqual(commands, {})

    def test_parent_link_to_a_reused_pid_is_not_followed(self):
        # 201's parent exited and an agent got its pid between the two samples.
        commands = Owners().attribute(snapshot(AGENT, proc(201, 100, parent_ident=7100)))
        self.assertEqual(commands, {})

    def test_reused_pid_does_not_inherit_the_old_owner(self):
        owners = Owners()
        owners.attribute(snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=200)))
        commands = owners.attribute(snapshot(AGENT, proc(201, 1, pgid=201, ident=9201)))
        self.assertEqual(commands, {})

    def test_nested_agent_is_excluded_and_its_children_are_its_commands(self):
        nested = proc(201, 200, pgid=200, argv=("/Users/me/.local/bin/claude", "-p"))
        commands = Owners().attribute(snapshot(
            AGENT, proc(200, 100), nested, proc(202, 201, pgid=202)))
        self.assertEqual(sorted(commands), [200, 202])
        self.assertEqual([p.pid for p in commands[200]], [200])

    def test_guard_never_joins_a_command(self):
        me = os.getpid()
        commands = Owners().attribute(snapshot(
            AGENT, proc(200, 100), proc(me, 200, pgid=200, marked=True)))
        self.assertEqual([p.pid for p in commands[200]], [200])

    def test_agent_child_that_is_not_a_shell_is_a_service(self):
        owners = Owners()
        commands = owners.attribute(snapshot(
            AGENT, proc(200, 100, argv=("/opt/homebrew/bin/bash", "-c", "make")),
            proc(300, 100, argv=("npm", "exec", "effect-mcp@latest")),
            proc(301, 300, pgid=300, argv=("node", "mcp.js"))))
        self.assertEqual(sorted(commands), [200, 300])
        self.assertEqual(owners.services, {300})

    def test_claude_mcp_server_is_a_service_though_marked(self):
        # Claude Code passes CLAUDECODE to its MCP servers.
        owners = Owners()
        owners.attribute(snapshot(AGENT, proc(200, 100, marked=True, argv=("node", "mcp.js"))))
        self.assertEqual(owners.services, {200})

    def test_codex_shell_that_exec_d_into_its_program_is_still_a_command(self):
        # Codex's `zsh -lc "pnpm typecheck"` becomes node; the agent mark survives the exec.
        owners = Owners()
        owners.attribute(snapshot(CODEX, proc(200, 90, marked=True, argv=("node", "tsc"))))
        self.assertEqual(owners.services, set())

    def test_codex_child_with_a_hidden_environment_is_a_command(self):
        # macOS hides an Apple binary's environment, such as git or sandbox-exec.
        owners = Owners()
        owners.attribute(snapshot(CODEX, proc(200, 90, marked=None, argv=("/usr/bin/git",))))
        self.assertEqual(owners.services, set())

    def test_codex_server_with_a_cleared_environment_is_a_service(self):
        owners = Owners()
        owners.attribute(snapshot(CODEX, proc(200, 90, argv=("npm", "exec", "effect-mcp"))))
        self.assertEqual(owners.services, {200})

    def test_service_is_forgotten_once_it_exits(self):
        owners = Owners()
        owners.attribute(snapshot(AGENT, proc(300, 100, argv=("gt", "mcp"))))
        owners.attribute(snapshot(AGENT))
        self.assertEqual(owners.services, set())

    # Info.plist executables, so these tests don't read the apps installed here.
    BUNDLES = {"/Applications/OrbStack.app": "OrbStack",
               "/Applications/OrbStack.app/Contents/Frameworks/OrbStack Helper.app": "OrbStack Helper",
               "/Applications/Stremio.app": "Stremio"}

    def attribute_with_bundles(self, *procs):
        with mock.patch.dict(guard.bundle_executables, self.BUNDLES, clear=True):
            return Owners().attribute(snapshot(AGENT, *procs))

    def test_marked_orphan_from_an_app_bundle_is_left_alone(self):
        vm = "/Applications/OrbStack.app/Contents/Frameworks/OrbStack Helper.app/Contents/MacOS/OrbStack Helper"
        commands = self.attribute_with_bundles(proc(501, 1, pgid=501, marked=True, argv=(vm, "vmgr")))
        self.assertEqual(commands, {})

    def test_marked_helper_in_an_app_s_group_does_not_claim_it(self):
        app = "/Applications/OrbStack.app/Contents/MacOS/OrbStack"
        commands = self.attribute_with_bundles(
            proc(501, 1, pgid=501, marked=True, argv=(app,)),
            proc(502, 501, pgid=501, marked=True, argv=("/Applications/OrbStack.app/Contents/MacOS/node",)))
        self.assertEqual(commands, {})

    def test_marked_helper_never_claims_a_group_whose_leader_reads_late_as_an_app(self):
        app = "/Applications/OrbStack.app/Contents/MacOS/OrbStack"
        helper = proc(502, 501, pgid=501, marked=True, argv=("node",))
        owners = Owners()
        with mock.patch.dict(guard.bundle_executables, self.BUNDLES, clear=True):
            unread = owners.attribute(snapshot(AGENT, proc(501, 1, pgid=501, argv=()), helper))
            read = owners.attribute(snapshot(
                AGENT, proc(501, 1, pgid=501, marked=True, argv=(app,)), helper))
        self.assertEqual((unread, read), ({}, {}))

    def test_detached_job_on_an_app_s_bundled_cli_is_still_agent_work(self):
        xcode_python = ("/Applications/Xcode.app/Contents/Developer/Library/Frameworks/"
                        "Python3.framework/Versions/3.9/Resources/Python.app")
        bundles = {**self.BUNDLES, xcode_python: "Python"}
        for cli in ("/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node",
                    "/Applications/Stremio.app/Contents/MacOS/node",
                    xcode_python + "/Contents/MacOS/Python"):  # what /usr/bin/python3 runs
            with mock.patch.dict(guard.bundle_executables, bundles, clear=True):
                commands = Owners().attribute(snapshot(
                    AGENT, proc(501, 1, pgid=501, marked=True, argv=(cli, "-e", "job"))))
            self.assertEqual(list(commands), [501], cli)

    def test_orphaned_python_job_is_still_agent_work(self):
        # Homebrew's python3 re-execs into Python.app; `nohup python3 … &` stays in the
        # exited command's group.
        python = "/opt/homebrew/Cellar/python@3.15/3.15.2/Frameworks/Python.framework/Versions/3.15/Resources/Python.app/Contents/MacOS/Python"
        commands = Owners().attribute(snapshot(
            AGENT, proc(47025, 1, pgid=47023, marked=True, argv=(python, "-c", "job"))))
        self.assertEqual(list(commands), [47025])

    def test_deep_chain_does_not_overflow_the_stack(self):
        chain = [proc(1000 + i, 999 + i, pgid=1000) for i in range(1, 5000)]
        commands = Owners().attribute(snapshot(AGENT, proc(1000, 100), *chain))
        self.assertEqual(len(commands[1000]), 5000)


class Runaway(unittest.TestCase):
    def command(self, head, count, gb_each=0):
        return head, [proc(head + i, 1, footprint=gb_each * GB) for i in range(count)]

    def test_under_every_budget_is_left_alone(self):
        self.assertIsNone(guard.runaway(dict([self.command(1, 30, 0.1)])))

    def test_too_many_processes_in_one_command(self):
        head, reason = guard.runaway(dict([self.command(1, 30), self.command(10000, 601)]))
        self.assertEqual(head, 10000)
        self.assertIn("601 processes", reason)

    def test_too_much_footprint_in_one_command(self):
        head, _ = guard.runaway(dict([self.command(1, 3, 7)]))
        self.assertEqual(head, 1)

    def test_full_unit_suite_is_left_alone(self):
        self.assertIsNone(guard.runaway(dict([self.command(1, 229, 13.6 / 229)])))

    def test_commands_together_over_the_total_kill_the_biggest(self):
        # 14 + 10 + 6 GB passes the 28 GB total; each is under the 20 GB per-command budget.
        commands = dict([self.command(1, 2, 7), self.command(100, 2, 5), self.command(200, 1, 6)])
        head, reason = guard.runaway(commands)
        self.assertEqual(head, 1)
        self.assertIn("over the total", reason)

    def test_services_stay_out_of_the_total(self):
        # 19 GB of idle MCP servers plus a 10 GB typecheck passed the 28 GB total.
        services = dict(self.command(1000 * i, 2, 0.17) for i in range(1, 57))
        commands = {**services, **dict([self.command(100, 3, 10 / 3)])}
        self.assertIsNone(guard.runaway(commands, services.keys()))
        self.assertIsNotNone(guard.runaway(commands))

    def test_work_a_service_runs_counts_past_its_idle_allowance(self):
        # Codex's Node REPL runs a 16 GB job beside a 14 GB command: 15 GB past the
        # allowance plus 14 passes 28.
        repl = [proc(1, 1), proc(2, 1, footprint=16 * GB)]
        commands = {1: repl, 100: [proc(100, 1, footprint=14 * GB)]}
        head, _ = guard.runaway(commands, {1})
        self.assertEqual(head, 1)

    def test_a_service_within_its_allowance_adds_nothing(self):
        self.assertEqual(guard.counted(1, [proc(1, 1, footprint=0.9 * GB)], {1}), (0, 0))

    def test_a_service_still_gets_the_per_command_budget(self):
        head, _ = guard.runaway(dict([self.command(1, 3, 7)]), {1})
        self.assertEqual(head, 1)

    def test_storm_split_across_commands_is_caught_by_the_total(self):
        commands = dict(self.command(i * 1000, 400) for i in range(1, 5))
        self.assertIsNotNone(guard.runaway(commands))


class AbandonedCommands(unittest.TestCase):
    """Abandoned.busy() over a timeline of ticks; `cores` is how busy each process is."""
    WINDOW = guard.ABANDONED_WINDOW_SECONDS

    def run_ticks(self, minutes, members, abandoned=None, start=0):
        """Tick once a minute from second `start`; `members(t)` is the command's processes
        at second t. Returns the first kill found and the minute it came."""
        abandoned = abandoned or guard.Abandoned()
        for minute in range(minutes + 1):
            t = start + minute * 60
            found = abandoned.busy({200: members(t)}, {100: 100}, t)
            if found:
                return found, minute
        return None, None

    def spinning_orphan(self, t, cores=1.0, ppid=1):
        return [proc(201, ppid, pgid=200, cpu=int(cores * t * 1e9))]

    def test_a_spinning_orphan_is_killed_after_the_window(self):
        (head, reason), minute = self.run_ticks(60, self.spinning_orphan)
        self.assertEqual((head, minute), (200, self.WINDOW // 60))
        self.assertIn("abandoned by its agent, at 1.0 cores for 30 min", reason)

    def test_a_command_whose_shell_an_agent_still_waits_on_is_left_alone(self):
        found, _ = self.run_ticks(90, lambda t: [proc(200, 100, cpu=int(t * 1e9))]
                                  + self.spinning_orphan(t))
        self.assertIsNone(found)

    def test_a_command_its_agent_waits_on_is_killed_after_two_hours_busy(self):
        # Nov 27, 2026: `bun -e` ran as Codex's direct child, no shell, at 100% for 11 hours.
        abandoned = guard.Abandoned()
        for minute in range(180):
            t = minute * 60
            found = abandoned.busy(
                {201: [proc(201, 90, argv=("bun", "-e", "..."), marked=True,
                            cpu=int(t * 1e9))]}, {90: 90}, t)
            if found:
                break
        self.assertEqual((found[0], minute), (201, guard.ATTENDED_WINDOW_SECONDS // 60))
        self.assertIn("busy while its agent waits on it, at 1.0 cores for 120 min", found[1])

    def test_a_waited_on_command_that_built_then_idles_is_left_alone(self):
        # `next build && next start`: 6 cores for 12 minutes, 0.6 cores over 2 hours, then
        # serving at 0.01 cores.
        abandoned = guard.Abandoned()
        for minute in range(240):
            t = minute * 60
            cpu = 6 * min(t, 720) + 0.01 * max(0, t - 720)
            self.assertIsNone(abandoned.busy(
                {201: [proc(201, 90, argv=("sh", "-c", "next build && next start"),
                            cpu=int(cpu * 1e9))]}, {90: 90}, t))

    def test_a_waited_on_command_just_under_half_a_core_lately_is_left_alone(self):
        # 2 cores for an hour, then 0.499: over the budget for 2 hours, just under it for
        # the last 30 minutes.
        abandoned, cpu = guard.Abandoned(), 0.0
        for tick in range(3 * 3600 * 2):
            t = tick / 2
            cpu += (2.0 if t < 3600 else 0.499) / 2
            self.assertIsNone(abandoned.busy(
                {201: [proc(201, 90, cpu=int(cpu * 1e9))]}, {90: 90}, t))

    def test_a_waited_on_command_just_over_half_a_core_lately_is_killed(self):
        # 0.501 cores throughout: over the budget for 2 hours and for its last 30 minutes.
        abandoned, cpu, found = guard.Abandoned(), 0.0, None
        for tick in range(3 * 3600 * 2):
            t = tick / 2
            cpu += 0.501 / 2
            found = abandoned.busy({201: [proc(201, 90, cpu=int(cpu * 1e9))]}, {90: 90}, t)
            if found:
                break
        self.assertEqual(found[0], 201)

    def test_a_busy_agent_server_is_killed_after_two_hours(self):
        # A server's classification misfires both ways under Codex, so servers get no pass.
        found, minute = self.run_ticks(
            180, lambda t: [proc(200, 100, argv=("node", "mcp.js"), cpu=int(t * 1e9))])
        self.assertEqual((found[0], minute), (200, guard.ATTENDED_WINDOW_SECONDS // 60))

    def test_an_idle_orphan_such_as_a_dev_server_is_left_alone(self):
        found, _ = self.run_ticks(90, lambda t: self.spinning_orphan(t, cores=0.05))
        self.assertIsNone(found)

    def test_a_burst_that_averages_under_the_budget_is_left_alone(self):
        # The rule averages over the window: a 10-minute burst is a third of a core.
        found, _ = self.run_ticks(90, lambda t: self.spinning_orphan(min(t, 600)))
        self.assertIsNone(found)

    def test_the_window_starts_when_the_command_is_abandoned(self):
        abandoned = guard.Abandoned()
        for minute in range(60):  # busy for an hour while its shell is alive
            t = minute * 60
            self.assertIsNone(abandoned.busy(
                {200: [proc(200, 100)] + self.spinning_orphan(t)}, {100: 100}, t))
        found, minute = self.run_ticks(60, self.spinning_orphan, abandoned, start=3600)
        self.assertEqual((found[0], minute), (200, self.WINDOW // 60))

    def test_a_late_joiner_s_earlier_cpu_does_not_count(self):
        # 202 joins at minute 10 with 10 hours of CPU behind it, then idles.
        def members(t):
            late = [proc(202, 1, pgid=200, cpu=36000 * 10 ** 9)] if t >= 600 else []
            return self.spinning_orphan(t, cores=0.1) + late
        found, _ = self.run_ticks(90, members)
        self.assertIsNone(found)

    def test_a_worker_its_shell_reaps_counts_once(self):
        # An idle shell starts a worker each minute that spins for 50 s; the shell reaps it,
        # so its reaped CPU grows by 50 s.
        def members(t):
            minute, second = divmod(t, 60)
            shell = [proc(201, 1, pgid=200, reaped=int(50e9 * (minute + (second >= 50))))]
            if second >= 50:
                return shell
            return shell + [proc(1000 + minute, 201, pgid=200, ident=1000 + minute,
                                 cpu=int(second * 1e9), start=minute * 60)]
        abandoned = guard.Abandoned()
        for tick in range(0, 40 * 60, 10):  # every 10 s, so each worker is seen alive
            found = abandoned.busy({200: members(tick)}, {100: 100}, tick)
            if found:
                break
        self.assertEqual(found[0], 200)
        self.assertIn("0.8 cores", found[1])  # 50 of every 60 s

    def test_workers_no_tick_sees_count_through_the_shell_that_reaps_them(self):
        found, _ = self.run_ticks(
            60, lambda t: [proc(201, 1, pgid=200, reaped=int(50e9 * (t // 60)))])
        self.assertIn("0.8 cores", found[1])

    def test_a_worker_started_since_counts_its_cpu_from_its_start(self):
        # Each minute a new orphaned worker is seen once, 50 s into its life, and nobody
        # reaps it into a member.
        found, _ = self.run_ticks(60, lambda t: [proc(1000 + t, 1, pgid=200, ident=1000 + t,
                                                      cpu=int(50e9), start=t - 50)] if t else [
            proc(999, 1, pgid=200)])
        self.assertIn("0.8 cores", found[1])

    def test_a_reused_agent_pid_does_not_pass_for_the_agent(self):
        # 202's parent exited and the agent now has its pid, but not its kernel id.
        found, minute = self.run_ticks(60, lambda t: self.spinning_orphan(t) + [
            proc(202, 100, pgid=200, parent_ident=7100)])
        self.assertEqual(minute, self.WINDOW // 60)

    def test_the_window_does_not_reach_past_30_minutes(self):
        # 8 cores for the first minute, under a quarter core to minute 30, half a core
        # for a minute, then 8 cores at 1859 s. The 30 minutes before each tick to 1859 s
        # average at most 0.5 cores; with the first minute in its window, it passes.
        def cpu(half):
            if half <= 120:
                return half * 4 * 10 ** 9
            if half <= 3600:
                return 480 * 10 ** 9 + (half - 120) * (10 ** 9 // 2) * 7 // 29
            if half <= 3718:
                return 900 * 10 ** 9 + (half - 3600) * (10 ** 9 // 4)
            return 900 * 10 ** 9 + 118 * (10 ** 9 // 4) + (half - 3718) * 4 * 10 ** 9
        abandoned = guard.Abandoned()
        for half in range(3720):
            found = abandoned.busy({200: [proc(201, 1, cpu=cpu(half))]}, {100: 100}, half / 2)
            self.assertIsNone(found, f"killed at {half / 2} s")

    def test_a_worker_reaped_with_its_parent_in_one_tick_counts_once(self):
        # Each minute the shell runs `sh -c worker`: the worker spins 20 s, seen at 0 and
        # 10 s, and it and its sh exit before the next tick; the shell reaps both.
        def members(t):
            minute, second = divmod(t, 60)
            shell = [proc(201, 1, pgid=200, reaped=int(20e9 * (minute + (second >= 20))))]
            if second >= 20:
                return shell
            sh, worker = 2000 + minute, 3000 + minute
            return shell + [proc(sh, 201, pgid=200, ident=sh, start=minute * 60),
                            proc(worker, sh, pgid=200, ident=worker, start=minute * 60,
                                 cpu=int(second * 1e9))]
        abandoned = guard.Abandoned()
        for tick in range(0, 60 * 60, 10):
            self.assertIsNone(abandoned.busy({200: members(tick)}, {100: 100}, tick))
        self.assertEqual(abandoned.state[200][4], int(20e9 * 60))  # a third of a core

    def test_a_scan_that_reads_the_parent_before_the_reap_never_drops_the_total(self):
        # The worker spun 900 s before tracking began; one scan sees it gone before its
        # parent's cpu shows the reap, the next sees the parent with it.
        abandoned, totals = guard.Abandoned(), []
        scans = [[proc(201, 1), proc(202, 201, cpu=int(900e9))],
                 [proc(201, 1)]] + [[proc(201, 1, reaped=int(900e9))]] * 3600
        for half, members in enumerate(scans):
            self.assertIsNone(abandoned.busy({200: members}, {100: 100}, half / 2))
            totals.append(abandoned.state[200][4])
        self.assertEqual(set(totals), {0})

    def test_a_parent_s_own_cpu_does_not_repay_its_child_s_debt(self):
        # The worker spins 100 s and exits; its parent then spins on its own until 1900 s,
        # when it reaps the worker, and idles. Own CPU counts when used; the reap adds none.
        def members(t):
            parent = proc(201, 1, cpu=int(max(0, min(t, 1900) - 100) * 1e9),
                          reaped=int(100e9) if t >= 1900 else 0)
            return [parent] + ([proc(202, 201, cpu=int(t * 1e9))] if t < 100 else [])
        abandoned, totals = guard.Abandoned(), {}
        for tick in range(0, 4000, 10):
            abandoned.busy({200: members(tick)}, {100: 100}, tick)
            totals[tick] = abandoned.state[200][4]
        self.assertEqual(totals[1890], int((90 + 1790) * 1e9))
        self.assertEqual(totals[3990], int((100 + 1800) * 1e9))  # the reap adds its last 10 s

    def test_the_window_uses_the_monotonic_clock(self):
        # 0.4 cores while the wall clock jumps back 10 minutes at 15 min.
        abandoned = guard.Abandoned()
        for half in range(5001):
            t = half / 2
            wall = 1.7e9 + t - (600 if t >= 900 else 0)
            members = [proc(201, 1, cpu=int(t * 0.4e9), start=1.7e9 - 1)]
            self.assertIsNone(abandoned.busy({200: members}, {100: 100}, t, wall))

    def test_only_cpu_inside_the_window_counts(self):
        # A 15-core burst in the first 5 s, then just under 0.5 cores in the 30 minutes
        # before each later tick.
        rate = (899.95 - 75) / 1795
        def cpu(t):
            if t <= 5:
                return 15 * t
            return 75 + (t - 5) * rate if t <= 1800 else 899.95 + (t - 1800)
        abandoned = guard.Abandoned()
        for half in range(3603):
            members = [proc(201, 1, cpu=int(cpu(half / 2) * 1e9))]
            self.assertIsNone(abandoned.busy({200: members}, {100: 100}, half / 2))

    def test_a_failed_cpu_read_does_not_count_a_process_twice(self):
        # An idle orphan with 100 s of CPU behind it, whose read fails every other minute.
        def members(t):
            cpu = None if (t // 60) % 2 else 100 * 10 ** 9
            return [proc(201, 1, pgid=200, cpu=cpu)]
        found, _ = self.run_ticks(90, members)
        self.assertIsNone(found)

    def test_tick_kills_a_spinning_orphan_with_its_whole_command(self):
        killed, owners, abandoned = [], Owners(), guard.Abandoned()
        owners.attribute(snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=200)))
        with mock.patch.multiple(guard, LOG=os.devnull, notify=lambda *args: None,
                                 kill=lambda owners, head, scan: killed.append(head) or ([], [])):
            for minute in range(31):
                t = minute * 60
                guard.tick(owners, lambda: snapshot(AGENT, *self.spinning_orphan(t)),
                           abandoned, now=lambda: t)
        self.assertEqual(killed, [200])


class CommandLine(unittest.TestCase):
    def procargs(self, *argv, env=()):
        body = b"/usr/bin/python3\0\0\0\0" + b"\0".join(argv) + b"\0" + b"\0".join(env) + b"\0"
        return len(argv).to_bytes(4, "little") + body

    def test_empty_argument_does_not_shift_the_environment(self):
        args, marked, tool_call = guard.parse_procargs(
            self.procargs(b"python3", b"worker.py", b"", env=[b"CLAUDECODE=1", b"HOME=/x"]))
        self.assertEqual(args, ["python3", "worker.py", ""])
        self.assertTrue(marked)
        self.assertIsNone(tool_call)

    def test_codex_tool_call_id_is_read(self):
        env = [b"CODEX_THREAD_ID=t1", b"CODEX_TOOL_CALL_ID=call_abc123", b"HOME=/x"]
        self.assertEqual(guard.parse_procargs(self.procargs(b"node", b"tsc", env=env))[1:], (True, "call_abc123"))

    def test_unmarked_environment(self):
        self.assertIs(guard.parse_procargs(self.procargs(b"node", env=[b"HOME=/x"]))[1], False)

    def test_codex_thread_id_marks_a_command(self):
        env = [b"HOME=/x", b"CODEX_THREAD_ID=t1"]
        self.assertIs(guard.parse_procargs(self.procargs(b"node", env=env))[1], True)

    def test_hidden_environment_is_unknown(self):
        self.assertIsNone(guard.parse_procargs(self.procargs(b"node", env=[]))[1])

    # Spins until its own CPU clock reads half a second, not for a wall-clock span: on a
    # loaded Mac a second of wall time can hold a fifth of a CPU second.
    SPIN = "import time\nwhile time.process_time() < 0.5: pass\n"

    @MACOS
    def test_cpu_time_is_in_nanoseconds(self):
        # rusage_info counts Mach ticks; unconverted, Apple silicon would read 24 times low.
        # The child reports its own CPU clock, in nanoseconds, at two CPU-time targets and
        # blocks at each, so the guard's reading must advance by what the child used.
        script = ("import time\nfor target in (0.25, 0.75):\n"
                  "    while time.process_time() < target: pass\n"
                  "    print(time.process_time_ns(), flush=True)\n    input()\n")
        with subprocess.Popen([sys.executable, "-c", script],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE) as child:
            try:
                readings = []
                for _ in range(2):
                    clock = int(child.stdout.readline())
                    readings.append((clock, guard.processes()[child.pid].cpu))
                    child.stdin.write(b"\n")
                    child.stdin.flush()
                (first_clock, first_cpu), (last_clock, last_cpu) = readings
                spun, used = last_clock - first_clock, last_cpu - first_cpu
                self.assertGreater(used, 0.9 * spun)
                self.assertLess(used, 1.1 * spun)
            finally:
                child.kill()

    @MACOS
    def test_cpu_includes_reaped_children_and_start_is_wall_clock(self):
        before = time.time()
        # Its own session, so killing the group takes its sleep too, not just the shell.
        shell = subprocess.Popen(["/bin/sh", "-c", '"$0" -c "$1"; sleep 30', sys.executable,
                                  self.SPIN], start_new_session=True)
        after = time.time()
        try:
            deadline = time.monotonic() + 60  # until the shell reaps the spin
            while True:
                subprocess.run(["sleep", "0.05"])  # past the tolerance: no scan's time is a start
                mine = guard.processes()[shell.pid]
                if mine.reaped or time.monotonic() > deadline:
                    break
            self.assertGreater(mine.reaped, 0.45e9)  # the reaped half-second spin
            self.assertLess(mine.reaped, 0.6e9)
            self.assertLess(mine.cpu, 0.1 * mine.reaped)  # its own CPU leaves the child's out
            self.assertGreater(mine.start, before - 0.01)
            self.assertLess(mine.start, after + 0.01)
        finally:
            os.killpg(shell.pid, signal.SIGKILL)
            shell.wait()

    @MACOS
    def test_exec_is_seen_although_the_process_id_stays(self):
        child = subprocess.Popen(["/bin/zsh", "-c", "read line; exec /bin/cat"],
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
        try:
            before = guard.processes()[child.pid]
            child.stdin.write(b"go\n")
            child.stdin.flush()
            for _ in range(50):
                after = guard.processes()[child.pid]
                if after.argv[:1] == ["/bin/cat"]:
                    break
                subprocess.run(["sleep", "0.02"])
            self.assertEqual(before.argv[0], "/bin/zsh")
            self.assertEqual((after.ident, after.argv), (before.ident, ["/bin/cat"]))
            self.assertNotEqual(after.version, before.version)
            self.assertNotIn((before.ident, before.version), guard.command_lines)
        finally:
            child.kill()
            child.wait()
            child.stdin.close()


class Kill(unittest.TestCase):
    """kill() against scripted snapshots: `alive` is what the kernel would report."""

    def setUp(self):
        self.alive, self.sent = {}, []

    def run_kill(self, *snapshots, replaced=None, head=200):
        scans = iter(snapshots)

        def scan():
            procs = next(scans)
            self.alive = {p.pid: p.ident for p in procs.values()}
            self.alive.update(replaced or {})  # pids reused after this scan
            return procs

        def send(pid, sig):
            self.sent.append((pid, sig))

        return guard.kill(Owners(), head, scan, send, lambda pid: self.alive.get(pid))

    def test_a_pid_reused_by_a_new_member_before_the_stop_is_still_killed(self):
        first = snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=200))
        second = snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=200, ident=9201))
        killed, _ = self.run_kill(first, second, second, replaced={201: 9201})
        self.assertEqual(sorted(p.ident for p in killed), [200, 201, 9201])
        self.assertIn((201, signal.SIGKILL), self.sent)

    def test_a_reused_orphan_group_is_not_killed_with_the_old_one(self):
        first = snapshot(AGENT, proc(501, 1, pgid=500, marked=True))
        # 501 exits and group 500 is reused by a new agent-marked orphan before the rescan.
        second = snapshot(AGENT, proc(601, 1, pgid=500, marked=True, ident=9601))
        killed, _ = self.run_kill(first, second, head=501)
        self.assertEqual([p.ident for p in killed], [501])
        self.assertNotIn(601, [pid for pid, _ in self.sent])

    def test_a_child_forked_during_the_stop_is_stopped_and_killed(self):
        first = snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=200))
        second = snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=200),
                          proc(202, 201, pgid=200))
        killed, refused = self.run_kill(first, second, second)
        self.assertEqual(sorted(p.pid for p in killed), [200, 201, 202])
        self.assertIn((202, signal.SIGSTOP), self.sent)
        self.assertEqual(sorted(pid for pid, sig in self.sent if sig == signal.SIGKILL),
                         [200, 201, 202])
        self.assertNotIn(100, [pid for pid, _ in self.sent])

    def test_a_failing_rescan_still_kills_what_was_stopped(self):
        first = snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=200))
        with self.assertRaises(StopIteration):
            self.run_kill(first)  # the second scan raises
        self.assertEqual(sorted(pid for pid, sig in self.sent if sig == signal.SIGKILL),
                         [200, 201])


class Tick(unittest.TestCase):
    def test_a_failed_log_write_still_kills(self):
        killed = []
        with mock.patch.multiple(guard, LOG="/nonexistent/agent-memory-guard.log", MAX_PROCESSES=1,
                                 kill=lambda owners, head, scan: killed.append(head) or ([], []),
                                 notify=lambda *args: None), \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            guard.tick(Owners(), lambda: snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=200)))
        self.assertEqual(killed, [200])
        self.assertIn("couldn't log a kill", stderr.getvalue())


class CommandText(unittest.TestCase):
    def test_strips_claude_shell_setup(self):
        args = ["/bin/zsh", "-c", "source /x/snapshot.sh && setopt NO_EXTENDED_GLOB && "
                "eval 'zsh -c '\"'\"'for i in {1..700}; do sleep 1 & done'\"'\"'' "
                "< /dev/null && pwd -P >| /tmp/cwd"]
        self.assertEqual(guard.command_text(args), "zsh -c 'for i in {1..700}; do sleep 1 & done'")

    def test_strips_claude_shell_setup_around_a_heredoc(self):
        command = "python3 - <<'EOF'\nprint(1)\nEOF"
        args = ["/bin/zsh", "-c", "source /x/snapshot.sh && eval '"
                + command.replace("'", "'\"'\"'") + "' && pwd -P >| /tmp/cwd"]
        self.assertEqual(guard.command_text(args), command)

    def test_keeps_other_commands_whole(self):
        self.assertEqual(guard.command_text(["node", "server.js"]), "node server.js")


@MACOS
class Signals(unittest.TestCase):
    def setUp(self):
        self.children = [subprocess.Popen(["sleep", "30"]) for _ in range(2)]
        procs = guard.processes()
        self.members = [procs[child.pid] for child in self.children]

    def tearDown(self):
        for child in self.children:
            child.kill()
            child.wait()

    def test_a_refused_process_does_not_stop_the_rest(self):
        sent = []

        def send(pid, sig):
            if pid == self.members[0].pid:
                raise PermissionError
            sent.append((pid, sig))

        refused = guard.signal_all(self.members, signal.SIGKILL, send)
        self.assertEqual(refused, [self.members[0].pid])
        self.assertEqual(sent, [(self.members[1].pid, signal.SIGKILL)])

    def test_a_reused_pid_is_not_signalled(self):
        sent = []
        stale = self.members[0]._replace(ident=0)
        guard.signal_all([stale], signal.SIGKILL, lambda pid, sig: sent.append(pid))
        self.assertEqual(sent, [])


class HeavyChecks(unittest.TestCase):
    """Which processes the check queue counts as a heavy check."""

    def test_each_checker_binary_is_heavy(self):
        for argv in (["/x/node_modules/.bin/tsc", "--noEmit"], ["/x/tsgolint"], ["/x/node_modules/.bin/oxlint"],
                     ["node", "/x/node_modules/eslint/bin/eslint.js", "."],
                     ["node", "/x/node_modules/vitest/vitest.mjs", "run"], ["node", "/x/jest/bin/jest.js"],
                     ["bun", "run", "--bun", "/x/node_modules/typescript/bin/tsc"], ["bunx", "tsc"],
                     ["/x/node_modules/@typescript/native-preview-darwin-arm64/lib/tsgo"]):
            with self.subTest(argv=argv):
                self.assertTrue(guard.is_heavy(argv))

    def test_an_interpreters_script_is_classified_never_a_later_argument(self):
        for argv in (["grep", "tsc"], ["node", "server.js", "tsc"], ["node", "/x/typescript/lib/tsserver.js"],
                     ["bun", "run", "dev"], ["node"], []):
            with self.subTest(argv=argv):
                self.assertFalse(guard.is_heavy(argv))

    def test_watch_forms_of_vitest_are_not_heavy(self):
        vitest = ["node", "/x/node_modules/vitest/vitest.mjs"]
        for rest in (["--watch"], ["-w"], ["watch"], ["dev"], ["--watch=true"]):
            with self.subTest(rest=rest):
                self.assertFalse(guard.is_heavy(vitest + rest))
        self.assertFalse(guard.is_heavy(["/x/.bin/tsc", "--watch"]))
        self.assertFalse(guard.is_heavy(["node", "/x/jest/bin/jest.js", "--watchAll"]))

    def test_vitest_run_is_heavy(self):
        vitest = ["node", "/x/node_modules/vitest/vitest.mjs"]
        for rest in (["run"], [], ["--watch=false"], ["run", "src/a.test.ts"]):
            with self.subTest(rest=rest):
                self.assertTrue(guard.is_heavy(vitest + rest))

    def test_a_units_child_shares_its_parents_slot(self):
        units = guard.heavy_units(Owners().attribute(snapshot(
            AGENT, proc(200, 100, argv=("zsh", "-c", "bun run lint")),
            proc(201, 200, argv=("/x/.bin/oxlint",)), proc(202, 201, argv=("/x/tsgolint",)),
            proc(300, 100, argv=("/x/.bin/turbo", "run", "typecheck")),
            proc(301, 300, argv=("/x/.bin/tsc",)), proc(302, 300, argv=("/x/.bin/tsc",)))))
        self.assertEqual({top: sorted(p.pid for p in unit.members) for top, unit in units.items()},
                         {201: [201, 202], 301: [301], 302: [302]})
        self.assertEqual({unit.head for unit in units.values()}, {200, 300})


class AgentCommand(unittest.TestCase):
    """Unwrapping the agent's wrapper shell to the command it ran."""

    def test_claude_eval_wrapper_unwraps_to_its_command(self):
        args = ["/bin/zsh", "-c", "source /x/snapshot.sh && eval 'bun run typecheck' < /dev/null && pwd -P >| /tmp/cwd"]
        self.assertEqual(guard.agent_command(args), "bun run typecheck")

    def test_codex_shell_wrapper_unwraps_to_its_command(self):
        self.assertEqual(guard.agent_command(["/bin/zsh", "-lc", "pnpm typecheck"]), "pnpm typecheck")
        self.assertEqual(guard.command_text(["/bin/zsh", "-lc", "pnpm typecheck"]), "pnpm typecheck")

    def test_any_other_argv_is_none(self):
        for argv in (["node", "tsc"], ["/bin/zsh", "-lc"], ["python3", "-c", "print(1)"], []):
            with self.subTest(argv=argv):
                self.assertIsNone(guard.agent_command(argv))

    def test_a_head_keeps_its_first_seen_argv_after_it_execs(self):
        owners = Owners()
        owners.attribute(snapshot(CODEX, proc(200, 90, marked=True, argv=("/bin/zsh", "-lc", "pnpm typecheck"))))
        owners.attribute(snapshot(CODEX, proc(200, 90, marked=True, argv=("node", "tsc"))))
        self.assertEqual(owners.argv, {200: ["/bin/zsh", "-lc", "pnpm typecheck"]})
        owners.attribute(snapshot(CODEX))
        self.assertEqual(owners.argv, {})

    def test_a_kill_entry_names_the_first_seen_command_and_tool_call(self):
        owners = Owners()
        owners.attribute(snapshot(CODEX, proc(200, 90, marked=True, argv=("/bin/zsh", "-lc", "pnpm typecheck"))))
        execed = guard.Proc(*proc(200, 90, marked=True, argv=("node", "tsc"))[:12], tool_call="call_1")
        commands = owners.attribute(snapshot(CODEX, execed))
        line = guard.entry(owners, 200, commands[200], "why", rule="queue")
        self.assertEqual((line["command"], line["tool_call_id"], line["rule"], line["agent_pid"]),
                         ("pnpm typecheck", "call_1", "queue", 90))


TSC = ("node", "/x/node_modules/typescript/bin/tsc", "--noEmit")


class Queue:
    """A Governor on synthetic snapshots: AGENT runs check n as shell 200+10n with tsc
    201+10n under it. Clocks start at wall 1000, monotonic 0, and move half a second a tick."""

    def __init__(self, test, cap=2, cores=100, state=None, current=None):
        import resolved
        folder = tempfile.mkdtemp()
        test.addCleanup(shutil.rmtree, folder)
        self.test, self.state = test, state or os.path.join(folder, "check-queue.json")
        self.config = resolved.CheckQueue(True, cap, cores)
        self.sent, self.lines, self.notified, self.saved_at_stop = [], [], [], {}
        self.now, self.wall = 0.0, 1000.0
        self.governor = guard.Governor(
            settings=lambda: self.settings(), state=self.state, send=self.send,
            current=current or (lambda pid: pid), record=self.lines.append,
            notify=lambda *args: self.notified.append(args), wall=lambda: 1000.0)
        self.owners = Owners()

    def settings(self):
        if isinstance(self.config, Exception):
            raise self.config
        return self.config

    def send(self, pid, sig):
        if sig == signal.SIGSTOP:
            with open(self.state) as file:
                self.saved_at_stop[pid] = file.read()
        self.sent.append((pid, sig))

    def check(self, n, born=None, cpu=0, reaped=0, tool_call=None, shell=True):
        born = self.wall if born is None else born
        top = guard.Proc(*proc(201 + 10 * n, 200 + 10 * n if shell else 1, argv=TSC, start=born,
                               cpu=cpu, reaped=reaped)[:12], tool_call=tool_call)
        return ([proc(200 + 10 * n, 100, argv=("/bin/zsh", "-lc", f"check {n}"))] if shell else []) + [top]

    def tick(self, *checks, seconds=0.5):
        procs = snapshot(AGENT, *[p for check in checks for p in check])
        commands = self.owners.attribute(procs)
        agents = {pid: p.ident for pid, p in procs.items() if guard.is_agent(p)}
        self.governor.tick(self.owners, commands, agents, self.now, self.wall)
        self.now += seconds
        self.wall += seconds

    def stopped(self):
        state = {}
        for pid, sig in self.sent:
            state[pid] = sig
        return {pid for pid, sig in state.items() if sig == signal.SIGSTOP}

    def killed(self):
        return {pid for pid, sig in self.sent if sig == signal.SIGKILL}


class CheckQueue(unittest.TestCase):
    """The Governor, on synthetic snapshots with fake signals and clocks."""

    def setUp(self):
        guard._settings[:] = [None, None]

    def test_a_third_unit_over_a_cap_of_two_is_held_within_a_tick(self):
        q = Queue(self)
        q.tick(q.check(1), q.check(2), q.check(3))
        self.assertEqual(q.stopped(), {221, 231})  # one starts; the gate spaces the rest
        for _ in range(4):
            q.tick(q.check(1, 1000), q.check(2, 1000), q.check(3, 1000))
        self.assertEqual(q.stopped(), {231})

    def test_a_held_unit_resumes_before_a_newer_arrival(self):
        q = Queue(self, cap=1)
        q.tick(q.check(1), q.check(2))
        q.tick(q.check(1, 1000), q.check(2, 1000), q.check(3))
        self.assertEqual(q.stopped(), {221, 231})
        for _ in range(3):
            q.tick(q.check(2, 1000), q.check(3, 1000.5))
        self.assertEqual(q.stopped(), {231})

    def test_a_unit_running_when_the_guard_starts_is_never_stopped(self):
        q = Queue(self, cap=1)
        q.tick(q.check(1, 990), q.check(2, 995), q.check(3, 999.9))
        self.assertEqual(q.sent, [])

    def test_a_unit_running_when_the_queue_is_reenabled_is_never_stopped(self):
        import resolved
        q = Queue(self, cap=1)
        q.config = resolved.CheckQueue(False, 1, 100)
        q.tick(q.check(1), q.check(2))
        q.config = resolved.CheckQueue(True, 1, 100)
        q.tick(q.check(1, 1000), q.check(2, 1000), q.check(3, 1000.2))
        self.assertEqual(q.stopped(), set())
        q.tick(q.check(1, 1000), q.check(2, 1000), q.check(3, 1000.2), q.check(4))
        self.assertEqual(q.stopped(), {241})

    def test_members_that_join_a_held_unit_are_stopped(self):
        q = Queue(self, cap=1)
        q.tick(q.check(1), q.check(2))
        q.tick(q.check(1, 1000), q.check(2, 1000) + [proc(222, 221, argv=("node", "worker.js"))])
        self.assertEqual(q.stopped(), {221, 222})
        self.assertIn('[222, 222]', q.saved_at_stop[222])

    def test_a_held_units_survivors_resume_when_its_top_is_gone(self):
        q = Queue(self, cap=1)
        worker = proc(222, 221, argv=("node", "worker.js"))
        q.tick(q.check(1), q.check(2) + [worker])
        q.tick(q.check(1, 1000), [q.check(2, 1000)[0], worker])
        self.assertEqual(q.stopped(), set())
        self.assertEqual(q.governor.held, {})

    def test_a_held_top_read_without_its_argv_stays_held(self):
        q = Queue(self, cap=1)
        q.tick(q.check(1), q.check(2))
        shell, top = q.check(2, 1000)
        q.tick(q.check(1, 1000), [shell, top._replace(argv=[])])
        self.assertEqual(q.stopped(), {221})
        self.assertIn(221, q.governor.held)

    def test_a_held_unit_whose_agent_shell_is_gone_is_resumed(self):
        q = Queue(self, cap=1)
        q.tick(q.check(1), q.check(2))
        q.tick(q.check(1, 1000), q.check(2, 1000, shell=False))
        self.assertEqual(q.stopped(), set())
        self.assertEqual(q.lines[-1]["event"], "cont")
        self.assertEqual(q.lines[-1]["why"], "its agent's shell is gone")

    def test_disabling_resumes_held_units_on_the_next_tick(self):
        import resolved
        q = Queue(self, cap=1)
        q.tick(q.check(1), q.check(2))
        q.config = resolved.CheckQueue(False, 1, 100)
        q.tick(q.check(1, 1000), q.check(2, 1000), q.check(3))
        self.assertEqual(q.stopped(), set())
        self.assertNotIn((231, signal.SIGSTOP), q.sent)
        with open(q.state) as file:
            self.assertEqual(json.load(file), {"held": []})

    def test_start_resumes_saved_members_whose_ident_matches_and_skips_reused_pids(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        state = os.path.join(folder, "check-queue.json")
        with open(state, "w") as file:
            json.dump({"held": [{"unit": 401, "members": [[401, 401], [402, 999]]}]}, file)
        q = Queue(self, state=state)
        self.assertEqual(q.sent, [(401, signal.SIGCONT)])
        with open(state) as file:
            self.assertEqual(json.load(file), {"held": []})

    def test_a_unit_is_saved_before_it_is_stopped(self):
        q = Queue(self, cap=1)
        q.tick(q.check(1), q.check(2))
        self.assertEqual(json.loads(q.saved_at_stop[221]), {"held": [{"unit": 221, "members": [[221, 221]]}]})

    def test_a_failed_state_write_leaves_the_unit_running(self):
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            q = Queue(self, cap=1, state="/dev/null/nowhere/check-queue.json")
            q.tick(q.check(1), q.check(2))
        self.assertEqual(q.sent, [])
        self.assertIn("couldn't save a held unit", stderr.getvalue())
        q.tick(q.check(1, 1000), q.check(2, 1000), q.check(3))
        self.assertEqual(q.sent, [])  # the file still can't be written, so check 3 runs too

    def test_a_failed_write_after_a_resume_never_strands_the_unit(self):
        q = Queue(self, cap=1)
        q.tick(q.check(1), q.check(2))
        save, failures = q.governor._save, [1]

        def flaky():
            if failures:
                failures.pop()
                raise OSError("disk full")
            save()

        q.governor._save = flaky
        with contextlib.redirect_stderr(io.StringIO()):
            q.tick(q.check(2, 1000))
            q.tick(q.check(2, 1000))
        self.assertEqual(q.stopped(), set())
        self.assertEqual(q.sent[-1], (221, signal.SIGCONT))

    def test_a_governor_error_resumes_every_held_unit_and_reports_once(self):
        q = Queue(self, cap=1)
        q.tick(q.check(1), q.check(2))
        q.config = RuntimeError("boom")
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            q.tick(q.check(1, 1000), q.check(2, 1000))
            q.tick(q.check(1, 1000), q.check(2, 1000))
        self.assertEqual(q.stopped(), set())
        self.assertEqual(stderr.getvalue().count("check queue failed"), 1)

    def test_a_unit_released_after_an_error_is_never_stopped_again(self):
        import resolved
        q = Queue(self, cap=1)
        q.tick(q.check(1), q.check(2))
        q.config = RuntimeError("transient")
        with contextlib.redirect_stderr(io.StringIO()):
            q.tick(q.check(1, 1000), q.check(2, 1000))
        q.config = resolved.CheckQueue(True, 1, 100)
        q.tick(q.check(1, 1000), q.check(2, 1000))
        self.assertEqual(q.sent, [(221, signal.SIGSTOP), (221, signal.SIGCONT)])

    def test_a_governor_error_never_skips_the_memory_rules(self):
        killed = []
        governor = guard.Governor(settings=lambda: 1 / 0, state=os.devnull + "/x", send=lambda *a: None,
                                  record=lambda line: None, notify=lambda *a: None)
        with mock.patch.multiple(guard, MAX_PROCESSES=1, notify=lambda *args: None, record=lambda line: None,
                                 kill=lambda owners, head, scan: killed.append(head) or ([], [])), \
                contextlib.redirect_stderr(io.StringIO()):
            guard.tick(Owners(), lambda: snapshot(AGENT, proc(200, 100), proc(201, 200, pgid=200)),
                       governor=governor)
        self.assertEqual(killed, [200])

    def test_a_unit_held_fifteen_minutes_with_the_queue_full_is_killed_alone(self):
        q = Queue(self, cap=1)
        q.tick(q.check(1), q.check(2))
        q.now += guard.HOLD_SECONDS
        q.tick(q.check(1, 1000), q.check(2, 1000))
        self.assertEqual(q.killed(), {221})
        kill = [line for line in q.lines if line.get("rule") == "queue"]
        self.assertEqual(len(kill), 1)
        self.assertEqual(q.lines.index(kill[0]), len(q.lines) - 1)  # logged, then killed
        self.assertEqual(kill[0]["command"], "check 2")
        self.assertEqual(len(q.notified), 1)

    def test_a_unit_whose_turn_comes_at_fifteen_minutes_runs_instead(self):
        q = Queue(self, cap=1)
        q.tick(q.check(1), q.check(2))
        q.tick(q.check(2, 1000))
        q.now += guard.HOLD_SECONDS
        q.tick(q.check(2, 1000))
        self.assertEqual(q.killed(), set())
        self.assertEqual(q.stopped(), set())

    def test_the_queue_kill_logs_its_rule_unit_and_codex_tool_call_id(self):
        q = Queue(self, cap=1)
        q.tick(q.check(1), q.check(2, tool_call="call_9"))
        q.now += guard.HOLD_SECONDS
        q.tick(q.check(1, 1000), q.check(2, 1000, tool_call="call_9"))
        [line] = [line for line in q.lines if line.get("rule") == "queue"]
        self.assertEqual((line["tool_call_id"], line["unit"], line["agent_pid"]), ("call_9", "node tsc --noEmit", 100))
        self.assertIn("check queue stayed full", line["reason"])

    def test_the_gate_holds_a_unit_while_running_units_use_max_cores(self):
        q = Queue(self, cap=4, cores=2)
        cpu = 0
        for _ in range(6):
            q.tick(q.check(1, 1000, cpu=cpu))
            cpu += int(1.5e9)  # 3 cores
        q.tick(q.check(1, 1000, cpu=cpu), q.check(2))
        self.assertEqual(q.stopped(), {221})

    def test_the_gate_counts_a_worker_that_exited_between_scans(self):
        q = Queue(self, cap=4, cores=2)
        reaped = 0
        for _ in range(6):
            q.tick(q.check(1, 1000, reaped=reaped))
            reaped += int(1.5e9)
        q.tick(q.check(1, 1000, reaped=reaped), q.check(2))
        self.assertEqual(q.stopped(), {221})

    def test_the_gate_admits_when_no_unit_runs(self):
        q = Queue(self, cap=4, cores=1)
        q.tick(q.check(1), q.check(2))
        self.assertEqual(q.stopped(), {221})
        q.tick(q.check(2, 1000))
        q.tick(q.check(2, 1000))  # check 1 is gone two scans in a row; within the spacing
        self.assertEqual(q.stopped(), set())

    def test_the_gate_admits_at_most_one_unit_per_window(self):
        q = Queue(self, cap=4)
        q.tick(q.check(1), q.check(2), q.check(3))
        self.assertEqual(q.stopped(), {221, 231})
        for _ in range(3):
            q.tick(q.check(1, 1000), q.check(2, 1000), q.check(3, 1000))
        self.assertEqual(q.stopped(), {221, 231})
        q.tick(q.check(1, 1000), q.check(2, 1000), q.check(3, 1000))
        self.assertEqual(q.stopped(), {231})

    def test_memory_rules_still_kill_the_biggest_command_with_held_units(self):
        q = Queue(self, cap=1)
        killed = []
        big = [proc(220, 100, argv=("/bin/zsh", "-lc", "check 2")),
               proc(221, 220, argv=TSC, start=1000.0, footprint=30 * GB)]
        scan = lambda: snapshot(AGENT, *q.check(1), *big)
        with mock.patch.multiple(guard, notify=lambda *args: None, record=lambda line: None,
                                 kill=lambda owners, head, scan: killed.append(head) or ([], [])):
            guard.tick(q.owners, scan, governor=q.governor, now=lambda: 0.0, wall=lambda: 1000.0)
        self.assertEqual(q.stopped(), {221})
        self.assertEqual(killed, [220])

    def test_a_resolved_json_change_applies_without_a_restart(self):
        import resolved
        folder = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        state = folder / "resolved.json"
        built = resolved._kit_defaults()
        built["checkQueue"]["maxChecks"] = 2
        state.write_text(json.dumps(built))
        with mock.patch.object(resolved, "STATE", state):
            self.assertEqual(guard.settings().maxChecks, 2)
            built["checkQueue"]["maxChecks"] = 3
            state.write_text(json.dumps(built))
            os.utime(state, ns=(time.time_ns(), time.time_ns() + 10 ** 9))
            self.assertEqual(guard.settings().maxChecks, 3)

    def test_the_state_file_holds_one_record_per_held_unit(self):
        q = Queue(self, cap=1)
        q.tick(q.check(1), q.check(2) + [proc(222, 221, argv=("node", "w.js"))], q.check(3))
        with open(q.state) as file:
            self.assertEqual(json.load(file), {"held": [
                {"unit": 221, "members": [[221, 221], [222, 222]]}, {"unit": 231, "members": [[231, 231]]}]})


if __name__ == "__main__":
    unittest.main()
