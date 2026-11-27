#!/usr/bin/env python3
"""Launchd watchdog: kill a coding agent's runaway command before it freezes the Mac.

Each command a `claude` or `codex` process starts is its direct child, and everything
that child spawns is that command's. Every half second this reads the user's processes
from the kernel (libproc, so it still works when the process table is full), attributes
each to its command, and SIGKILLs a command whose processes or physical footprint pass
its budget. When all agent commands together pass the total budget, it kills the biggest.
A notification and a line in ~/Library/Logs/agent-memory-guard.log say what died. The
agent's command fails with no output, since its wrapper shell dies too; in Claude Code,
agent-memory-guard-notice.py reads the log and tells the agent why.

Added after Oct 15, 2026: an agent's stress script lost its parallelism limit and started
200 vitest runs at once, about 4,500 node processes. Memory pressure went critical two
and a half minutes in and the Mac froze. Hooks can't catch this: they see only the
command text, and most of the kit's Bash hooks don't run in Codex. macOS has no memory limit for
a process tree, so this polls. `ulimit -Su 3000` in ~/.zshenv is the kernel backstop for
fork storms.

It also kills an abandoned command, one whose shell, the agent's direct child, is gone,
once it averages over half a core for 30 minutes. Added after Nov 2, 2026: an agent's
Vitest runs hung in a busy loop, and each `pkill` of the main Vitest process left its fork
worker spinning under launchd, since a fork worker exits only when it next messages its
parent. Ten of them ran at 100% CPU for 15 hours. Idle leftovers, such as a dev server an
agent started with `nohup`, stay. A command its agent still waits on, its servers
included, gets 2 hours at that rate, and dies only while still busy in its last 30
minutes, so a dev server's first build doesn't kill it: on Nov 27, 2026 two `bun` probe
scripts Codex started without a shell spun at 100% CPU for 9 and 11 hours under a live
Codex, long after their threads finished. Claude Code in a terminal sets no time limit on
a background command, so 2 hours is a budget, not an agent's cap: in November 2026 no Codex
rollout on one Mac polled one command for more than 37 minutes.

It also queues heavy checks (tsc, tsgo, tsgolint, oxlint, eslint, jest, vitest not
watching): at most checkQueue.maxChecks run at once across every agent's commands, and a
new one waits while running checks use checkQueue.maxCores cores or more (Governor).
Added after Nov 27, 2026: five agents' type checks and lint runs, turbo's eight lint tasks
each, used all 18 cores and throttled the Mac. A waiting check is SIGSTOPped within a tick
of its start, never mid-run, saved to ~/.local/state/addystack/check-queue.json first, and
resumed oldest first; one still waiting after 15 minutes with the queue full is killed,
and agent-memory-guard-notice.py tells the agent why, as it does for every kill here. The
next guard start, a SIGTERM, `"checkQueue": {"enabled": false}`, or any governor error
resumes every waiting check.

Known limits:
- A checker started outside an agent's commands, in the user's own terminal, isn't
  queued, and its CPU doesn't count toward the gate.
- A checker that runs under another name, or as a later argument of a script only that
  script knows, such as `node build.js` calling tsc's API in-process, isn't queued.
- An orphan of an Apple binary (sleep, yes, zsh) whose command exited within one
  half-second tick escapes, since macOS hides those binaries' environment; the ulimit
  backstop caps how many there can be. Work an agent hands to launchd or XPC, or starts
  with a cleared environment, escapes too.
- Codex counts as an agent only when T3 Code starts it, or its process is named codex.
- Processes are signalled by pid right after their kernel id is rechecked; only a pid
  reused within those microseconds would be hit.
- A process running as another user (a `sudo` child) isn't seen.
- An agent's direct child that isn't a shell counts as a service, such as an MCP server:
  it gets the per-command budgets, and only its use past 1 GB and 10 processes counts
  toward the total. Under Codex it also needs a readable environment without the agent
  mark, so a Codex server that's an Apple binary, such as Xcode's mcpbridge, counts in
  full, and a command Codex starts with a cleared environment and no shell gets the
  allowance. So does a Claude command that `exec`s out of its wrapper shell. The CPU rule
  doesn't use this split, so a server over half a core for 2 hours dies like a command.
- An orphan in a process group led by an installed app's own executable (under
  /Applications/, the one its bundle's Info.plist names) isn't agent work by its
  environment alone, since an app such as OrbStack starts its VM with the environment of whichever
  command woke it.
- Codex's code-mode host, a small long-lived server T3 starts with the agent mark,
  counts toward the total, and like Xcode's mcpbridge falls under the 2-hour CPU rule.
  It's one process under each Codex app-server, so killing it fails the `exec` calls of
  every Codex thread on that app-server, not only the one that kept it busy.
- A CPU-heavy job an agent starts dies at over half a core: after 30 minutes when the
  agent doesn't wait on it (`nohup` or `&`), after 2 hours, still busy in the last 30
  minutes, when it does, a background task it tracks included. Run a longer one in a terminal, outside the agent.
- A worker whose parent exits before reaping it loses the CPU it used after the last tick
  saw it.
- When the guard starts, or a command moves between waited-on and abandoned, a worker that
  has exited but isn't reaped yet when that first scan reads it counts all its CPU once its
  parent reaps it, CPU from before the window included."""
import ctypes, ctypes.util, hashlib, json, os, plistlib, re, signal, struct, subprocess, sys, time
from collections import namedtuple

AGENTS = {"claude", "codex"}
GB = 1024 ** 3
# Measured on a large work repo: the incident's single test peaks at 17 processes and 0.7 GB, the
# full unit suite (`bun run test:unit`) at 229 processes and 13.6 GB. The Mac has 48 GB
# and idles at about 12 GB, so agent commands together get 28 GB. The incident's storm
# passes 600 processes at about 35 runs.
MAX_PROCESSES = 600
MAX_FOOTPRINT = 20 * GB
MAX_TOTAL_PROCESSES = 1500
MAX_TOTAL_FOOTPRINT = 28 * GB
INTERVAL_SECONDS = 0.5
# A service's use past this allowance is work it runs, and counts toward the total. Idle
# MCP servers measured 0.06 to 0.14 GB and 1 or 2 processes each on Nov 8, 2026.
SERVICE_IDLE_FOOTPRINT = 1 * GB
SERVICE_IDLE_PROCESSES = 10
# An abandoned command is killed once it averages ABANDONED_CORES over the window. A
# spinning Vitest worker uses 1 core; an idle dev server, under 0.05.
ABANDONED_CORES = 0.5
ABANDONED_WINDOW_SECONDS = 30 * 60
# A command its agent still waits on, an agent's server included, is killed once it
# averages ABANDONED_CORES over this longer window and over the last
# ABANDONED_WINDOW_SECONDS of it.
ATTENDED_WINDOW_SECONDS = 2 * 60 * 60
CHECKPOINT_SECONDS = 5  # CPU in a window's first this-many seconds may go uncounted
LOG = os.path.expanduser("~/Library/Logs/agent-memory-guard.log")

# ident is the kernel's process id that's never reused within a boot and survives exec;
# version changes on every exec (XNU kern_exec.c, "identity version"); parent_ident is
# the parent's ident, so a parent link survives pid reuse.
# cpu is the process's own user plus system time and reaped its reaped children's, in
# nanoseconds, or None when the read failed; start is when it started, in seconds since
# the epoch. tool_call is the CODEX_TOOL_CALL_ID Codex gives each command, or None.
Proc = namedtuple("Proc", "pid ppid pgid ident version parent_ident footprint argv marked "
                  "cpu start reaped tool_call", defaults=(0, 0, 0, None))


class BsdInfo(ctypes.Structure):  # struct proc_bsdinfo, <sys/proc_info.h>
    _fields_ = [("flags", ctypes.c_uint32), ("status", ctypes.c_uint32),
                ("xstatus", ctypes.c_uint32), ("pid", ctypes.c_uint32),
                ("ppid", ctypes.c_uint32), ("uid", ctypes.c_uint32), ("gid", ctypes.c_uint32),
                ("ruid", ctypes.c_uint32), ("rgid", ctypes.c_uint32),
                ("svuid", ctypes.c_uint32), ("svgid", ctypes.c_uint32), ("rfu", ctypes.c_uint32),
                ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32),
                ("nfiles", ctypes.c_uint32), ("pgid", ctypes.c_uint32),
                ("pjobc", ctypes.c_uint32), ("tdev", ctypes.c_uint32),
                ("tpgid", ctypes.c_uint32), ("nice", ctypes.c_int32),
                ("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64)]


class UniqueIds(ctypes.Structure):  # struct proc_uniqidentifierinfo, XNU proc_info.h
    _fields_ = [("uuid", ctypes.c_uint8 * 16), ("ident", ctypes.c_uint64),
                ("parent_ident", ctypes.c_uint64), ("version", ctypes.c_int32),
                ("orig_ppid_version", ctypes.c_int32), ("reserved", ctypes.c_uint64 * 2)]


class ProcInfo(ctypes.Structure):  # PROC_PIDT_BSDINFOWITHUNIQID
    _fields_ = [("bsd", BsdInfo), ("ids", UniqueIds)]


class RusageInfo(ctypes.Structure):  # struct rusage_info_v1, <sys/resource.h>
    _fields_ = [("uuid", ctypes.c_uint8 * 16), ("user_time", ctypes.c_uint64),
                ("system_time", ctypes.c_uint64), ("pkg_idle_wkups", ctypes.c_uint64),
                ("interrupt_wkups", ctypes.c_uint64), ("pageins", ctypes.c_uint64),
                ("wired_size", ctypes.c_uint64), ("resident_size", ctypes.c_uint64),
                ("phys_footprint", ctypes.c_uint64), ("start_abstime", ctypes.c_uint64),
                ("exit_abstime", ctypes.c_uint64), ("child_user_time", ctypes.c_uint64),
                ("child_system_time", ctypes.c_uint64), ("child_pkg_idle_wkups", ctypes.c_uint64),
                ("child_interrupt_wkups", ctypes.c_uint64), ("child_pageins", ctypes.c_uint64),
                ("child_elapsed_abstime", ctypes.c_uint64)]


class Timebase(ctypes.Structure):  # struct mach_timebase_info, <mach/mach_time.h>
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
PROC_RUID_ONLY, PROC_PIDT_BSDINFOWITHUNIQID, RUSAGE_INFO_V1 = 5, 18, 1
CTL_KERN, KERN_ARGMAX, KERN_PROCARGS2 = 1, 8, 49


def sysctl(mib, buf):
    length = ctypes.c_size_t(len(buf))
    mib = (ctypes.c_int * len(mib))(*mib)
    if libc.sysctl(mib, len(mib), buf, ctypes.byref(length), None, 0) != 0:
        return None
    return ctypes.string_at(buf, length.value)


# KERN_ARGMAX is macOS's. Elsewhere the module still imports, so its tests run on Linux.
if sys.platform == "darwin":
    ARGMAX = struct.unpack("i", sysctl([CTL_KERN, KERN_ARGMAX], ctypes.create_string_buffer(4)))[0]
    args_buffer = ctypes.create_string_buffer(ARGMAX)  # reused: ARGMAX is 1 MB
    # rusage_info's CPU times are Mach ticks, which are nanoseconds on Intel only.
    timebase = Timebase()
    libc.mach_timebase_info(ctypes.byref(timebase))
    NS_PER_TICK = timebase.numer / timebase.denom
# Environment variables an agent passes to everything it runs: Claude Code sets
# CLAUDECODE, T3 Code starts Codex with CODEX_INTERNAL_ORIGINATOR_OVERRIDE, and Codex
# gives each shell command CODEX_THREAD_ID, however Codex was started.
AGENT_ENV = (b"CLAUDECODE=", b"CODEX_INTERNAL_ORIGINATOR_OVERRIDE=", b"CODEX_THREAD_ID=")
# Codex 0.172 sets it to the exec call's id, which its PostToolUse hook gets as tool_use_id.
TOOL_CALL_ENV = b"CODEX_TOOL_CALL_ID="
command_lines = {}


def parse_procargs(raw):
    """KERN_PROCARGS2 is argc, the exec path, NUL padding, argv, then the environment.
    Returns argv, whether the environment marks the process as agent work, or None when
    the environment is hidden or empty, as macOS hides Apple binaries', and its
    CODEX_TOOL_CALL_ID or None."""
    argc = struct.unpack("i", raw[:4])[0]
    body = raw[4:]
    start = body.find(b"\0")
    while 0 <= start < len(body) and body[start] == 0:
        start += 1
    fields = body[start:].split(b"\0") if start >= 0 else []
    args = [arg.decode(errors="replace") for arg in fields[:argc]]
    env = [var for var in fields[argc:] if var]
    tool_call = next((var[len(TOOL_CALL_ENV):].decode(errors="replace") for var in env
                      if var.startswith(TOOL_CALL_ENV)), None)
    return args, any(var.startswith(AGENT_ENV) for var in env) if env else None, tool_call


def command_line(pid, ident, version):
    """The process's argv, agent mark, and Codex tool call, read once per exec. The kernel hides argv from
    other users and the environment of Apple's own binaries (sleep, zsh), so either can
    come back empty; a failed read is retried next tick."""
    key = (ident, version)
    if key not in command_lines:
        raw = sysctl([CTL_KERN, KERN_PROCARGS2, pid], args_buffer)
        if not raw:
            return [], False, None
        command_lines[key] = parse_procargs(raw)
    return command_lines[key]


def processes():
    """Every live process of this user, read in-process so a full process table can't
    stop it."""
    count = libc.proc_listpids(PROC_RUID_ONLY, os.getuid(), None, 0) // 4 + 256
    pids = (ctypes.c_int * count)()
    found = libc.proc_listpids(PROC_RUID_ONLY, os.getuid(), pids, ctypes.sizeof(pids)) // 4
    result = {}
    for pid in pids[:found]:
        info, usage = proc_info(pid), RusageInfo()
        if pid <= 0 or info is None:
            continue  # exited since the listing
        footprint, cpu, reaped = 0, None, None
        if libc.proc_pid_rusage(pid, RUSAGE_INFO_V1, ctypes.byref(usage)) == 0:
            footprint = usage.phys_footprint
            cpu = int((usage.user_time + usage.system_time) * NS_PER_TICK)
            reaped = int((usage.child_user_time + usage.child_system_time) * NS_PER_TICK)
        ident, version = info.ids.ident, info.ids.version
        argv, marked, tool_call = command_line(pid, ident, version)
        result[pid] = Proc(pid, info.bsd.ppid, info.bsd.pgid, ident, version,
                           info.ids.parent_ident, footprint, argv, marked, cpu,
                           info.bsd.start_sec + info.bsd.start_usec / 1e6, reaped, tool_call)
    live = {(p.ident, p.version) for p in result.values()}
    for key in [key for key in command_lines if key not in live]:
        del command_lines[key]
    return result


def proc_info(pid):
    info = ProcInfo()
    if libc.proc_pidinfo(pid, PROC_PIDT_BSDINFOWITHUNIQID, 0, ctypes.byref(info),
                         ctypes.sizeof(info)) != ctypes.sizeof(info):
        return None
    return info


def identity(pid):
    info = proc_info(pid)
    return info and info.ids.ident


def is_agent(proc):
    return bool(proc.argv) and os.path.basename(proc.argv[0]) in AGENTS


SHELLS = {"sh", "bash", "zsh", "dash", "fish"}


def is_service(proc, agent):
    """A server an agent keeps for its session, such as an MCP server: a direct child that
    isn't a shell. Claude Code runs each command in a compound shell that never execs, and
    passes CLAUDECODE to its servers. Codex's shell can exec into the program, which keeps
    the agent mark, while Codex starts its servers with a cleared environment; so under
    Codex a service also needs a readable environment without the mark."""
    if not proc.argv or os.path.basename(proc.argv[0]).lstrip("-") in SHELLS:
        return False
    return os.path.basename(agent.argv[0]) == "claude" or proc.marked is False


bundle_executables = {}


def bundle_executable(bundle):
    """The executable an app bundle's Info.plist names, or None."""
    if bundle not in bundle_executables:
        try:
            with open(os.path.join(bundle, "Contents", "Info.plist"), "rb") as info:
                bundle_executables[bundle] = plistlib.load(info).get("CFBundleExecutable")
        except Exception:  # a missing or malformed plist must not fail every tick
            bundle_executables[bundle] = None
    return bundle_executables[bundle]


def is_installed_app(proc):
    """An installed app's own process, such as OrbStack's VM, which leads its own process
    group and inherits the environment of the agent command that woke it. It's the
    executable its bundle's Info.plist names, a nested helper app's included; a CLI the
    app bundles, such as Stremio's node or ChatGPT's, stays agent work, and so do
    Homebrew's Python and Playwright's browsers, which aren't under /Applications/."""
    if not proc.argv or proc.pgid != proc.pid or not proc.argv[0].startswith("/Applications/"):
        return False
    bundle, marker, name = proc.argv[0].rpartition(".app/Contents/MacOS/")
    # A framework's Python.app is the interpreter /usr/bin/python3 runs, not an app.
    return (bool(marker) and "/" not in name and ".framework/" not in bundle
            and bundle_executable(bundle + ".app") == name)


class Owners:
    """Which agent command owns each process. A process keeps its owner after its parent
    exits, and a new orphan joins the command whose process group it's in, so
    backgrounded and reparented jobs still count. An orphan whose command exited before
    any tick saw it is grouped by process group when its environment marks it as agent
    work, headed by the first such orphan seen."""

    def __init__(self):
        self.owner = {}  # process ident -> head: the ident of the command's first process
        self.group = {}  # pgid a command head leads -> head
        self.services = set()  # heads that are an agent's servers, not its commands
        # head -> its argv when first seen, so a Codex shell that execs into its program
        # still names the command it ran.
        self.argv = {}

    def resolve(self, procs, agents):
        owner = {}
        for pid in procs:
            if pid == os.getpid():
                continue  # stopping itself would leave the command stopped, never killed
            # Walk up to an agent, a known process, or a missing parent, then resolve
            # back down: a process inherits its parent's owner, else keeps its own.
            chain, head = [], None
            while True:
                proc = procs[pid]
                key = proc.ident
                if key in owner:
                    head = owner[key]
                    break
                if pid in agents:
                    owner[key] = None
                    break
                parent = procs.get(proc.ppid)
                if parent is not None and parent.ident != proc.parent_ident:
                    parent = None  # the parent exited and its pid was reused mid-scan
                if parent is not None and parent.pid in agents:
                    head = owner[key] = key
                    break
                chain.append(proc)
                if parent is None or parent.pid <= 1 or len(chain) > len(procs):
                    break
                pid = parent.pid
            for proc in reversed(chain):
                head = head or self.owner.get(proc.ident) or self.group.get(proc.pgid)
                # Not while the group's leader is an app, or unread, so may be one: the
                # adoption outlives the read.
                leader = procs.get(proc.pgid)
                if (head is None and proc.marked and not (
                        leader is not None and (not leader.argv or is_installed_app(leader)))):
                    head = self.group[proc.pgid] = proc.ident
                owner[proc.ident] = head
        return owner

    def attribute(self, procs):
        agents = {pid for pid, proc in procs.items() if is_agent(proc)}
        # A group id is only reused once the group is empty, so a remembered group stays
        # valid while a process already known to be in it is alive.
        known = {(proc.pgid, self.owner[proc.ident]) for proc in procs.values()
                 if proc.ident in self.owner}
        self.group = {pgid: head for pgid, head in self.group.items() if (pgid, head) in known}
        groups = dict(self.group)
        owner = self.resolve(procs, agents)
        if self.group != groups:  # a group found late in the scan applies to all of it
            owner = self.resolve(procs, agents)
        self.owner = {ident: head for ident, head in owner.items() if head}
        commands = {}
        for proc in procs.values():
            head = self.owner.get(proc.ident)
            if head:
                commands.setdefault(head, []).append(proc)
                if proc.ident == head and proc.pgid == proc.pid:
                    self.group[proc.pgid] = head
                parent = procs.get(proc.ppid)
                if (proc.ident == head and parent is not None and is_agent(parent)
                        and parent.ident == proc.parent_ident and is_service(proc, parent)):
                    self.services.add(head)
        self.services &= commands.keys()
        for head, members in commands.items():
            first = next((proc for proc in members if proc.ident == head), None)
            if head not in self.argv and first is not None and first.argv:
                self.argv[head] = list(first.argv)
        self.argv = {head: argv for head, argv in self.argv.items() if head in commands}
        return commands


def footprint(members):
    return sum(proc.footprint for proc in members)


def counted(head, members, services):
    """What a command adds to the total, as (processes, bytes). A service adds only what
    it uses past an idle server's allowance, so work it runs, such as a job in Codex's
    Node REPL, still counts."""
    if head not in services:
        return len(members), footprint(members)
    return (max(0, len(members) - SERVICE_IDLE_PROCESSES),
            max(0, footprint(members) - SERVICE_IDLE_FOOTPRINT))


def runaway(commands, services=frozenset()):
    """Return (head, reason) for the command to kill, or None. A service gets the
    per-command budgets, and only its use past the idle allowance counts toward the
    total: on Nov 8, 2026 one Codex server's 54 sessions kept 19 GB of idle MCP servers,
    and the total killed real work all evening."""
    for head, members in commands.items():
        if len(members) > MAX_PROCESSES:
            return head, f"{len(members)} processes, over the per-command {MAX_PROCESSES}"
        if footprint(members) > MAX_FOOTPRINT:
            return head, (f"{footprint(members) / GB:.1f} GB, over the per-command "
                          f"{MAX_FOOTPRINT / GB:g} GB")
    usage = {head: counted(head, members, services) for head, members in commands.items()}
    if not usage:
        return None
    total_processes = sum(processes for processes, _ in usage.values())
    total_footprint = sum(size for _, size in usage.values())
    if total_processes > MAX_TOTAL_PROCESSES:
        head = max(usage, key=lambda h: usage[h][0])
        return head, (f"agent commands at {total_processes} processes, over the total "
                      f"{MAX_TOTAL_PROCESSES}; this is the biggest")
    if total_footprint > MAX_TOTAL_FOOTPRINT:
        head = max(usage, key=lambda h: usage[h][1])
        return head, (f"agent commands at {total_footprint / GB:.1f} GB, over the total "
                      f"{MAX_TOTAL_FOOTPRINT / GB:g} GB; this is the biggest")
    return None


class Abandoned:
    """CPU use of each abandoned command since it was first seen abandoned. Each tick adds
    what every member used since the tick before, its own and its reaped children's, so
    a worker that exits between ticks, or lives less than one, still counts through the
    ancestor that reaps it. What a vanished member already counted becomes a debt that
    only that ancestor's reaped CPU repays, so the total never drops or counts it twice,
    even when a scan reads the parent before the reap. The window is 30 minutes of awake
    time, on the monotonic clock, which stops while the Mac sleeps: CPU only burns while
    it's awake. Process start times are compared with the wall clock. A command an agent
    still waits on, its shell or itself a direct child of a live agent, is measured the
    same way over the 2-hour window, and must average over half a core in its last 30
    minutes too; one that moves between the two states starts over."""

    def __init__(self):
        # head -> (attended, wall time first seen in that state,
        #          last {ident: (cpu ns, reaped ns, parent ident)},
        #          debt {ident: ns}, total ns, [(time, total)] oldest first)
        self.state = {}

    def busy(self, commands, agents, now, wall=None):
        """Return (head, reason) for a command whose CPU inside the last window is over
        ABANDONED_CORES for the whole window, or None: 30 minutes for an abandoned command,
        2 hours and its last 30 minutes for one an agent still waits on. `agents` maps each agent's pid to its
        kernel id, so a reused pid can't pass for one."""
        wall = now if wall is None else wall
        found, kept = None, {}
        for head, members in commands.items():
            attended = any(agents.get(proc.ppid) == proc.parent_ident for proc in members)
            window = ATTENDED_WINDOW_SECONDS if attended else ABANDONED_WINDOW_SECONDS
            state = self.state.get(head)
            if state is None or state[0] != attended:
                state = (attended, wall, {}, {}, 0, [])
            _, began, last, debt, total, marks = state
            gained, seen, debt = cpu_gained(members, last, debt, began)
            total += gained
            if not marks or now - marks[-1][0] >= CHECKPOINT_SECONDS:
                marks = marks + [(now, total)]
            while now - marks[0][0] > window:
                marks.pop(0)  # only CPU inside the window counts
            kept[head] = (attended, began, seen, debt, total, marks)
            since, before = marks[0]
            if found or now - since < window - CHECKPOINT_SECONDS:
                continue
            # Divided by the whole window, CPU from its first few seconds is left out, so
            # this never reads above the true average.
            cores = (total - before) / 1e9 / window
            if attended:
                # It must still be busy: a build before its server starts (`next build &&
                # next start`) doesn't kill the server once it idles.
                _, recent = next(mark for mark in marks
                                 if now - mark[0] <= ABANDONED_WINDOW_SECONDS)
                if (total - recent) / 1e9 / ABANDONED_WINDOW_SECONDS <= ABANDONED_CORES:
                    continue
            if cores > ABANDONED_CORES:
                label = "busy while its agent waits on it" if attended else "abandoned by its agent"
                found = head, f"{label}, at {cores:.1f} cores for {window // 60} min"
        self.state = kept
        return found


def cpu_gained(members, last, debt, began):
    """CPU in ns the members used since `last` ({ident: (cpu, reaped, parent ident)}, from
    the call before), their own and their reaped children's, so a worker that exits between
    calls, or lives less than one, still counts through the ancestor that reaps it. What a
    vanished member already counted becomes a debt ({ident: ns}) that only that ancestor's
    reaped CPU repays, so the total never drops or counts it twice. A member not in `last`
    counts all its CPU when it started after `began` (epoch seconds), else from now.
    Returns (ns, the new last, the new debt)."""
    gained_total, seen, debt, here = 0, {}, dict(debt), {proc.ident for proc in members}
    for ident in last.keys() - here:
        # The nearest ancestor still here reaps it, directly or through parents that
        # vanished with it, and its reaped CPU then holds this one's again.
        cpu, reaped, parent = last[ident]
        owed = cpu + reaped + debt.pop(ident, 0)
        while parent in last and parent not in here:
            parent = last[parent][2]
        if parent in here:
            debt[parent] = debt.get(parent, 0) + owed
    for proc in members:
        if proc.cpu is None:  # a failed read keeps the last value
            if proc.ident in last:
                seen[proc.ident] = last[proc.ident]
            continue
        if proc.ident in last:
            cpu, reaped, _ = last[proc.ident]
            gained_total += max(0, proc.cpu - cpu)
            gained = max(0, proc.reaped - reaped)
            owed = debt.pop(proc.ident, 0)
            if owed > gained:
                debt[proc.ident] = owed - gained
            gained_total += max(0, gained - owed)
        elif proc.start > began:
            gained_total += proc.cpu + proc.reaped  # started since: all of it is new
        # else it existed before tracking began, so it counts from now
        seen[proc.ident] = (proc.cpu, proc.reaped, proc.parent_ident)
    return gained_total, seen, debt


def signal_all(members, sig, send=os.kill, current=identity):
    """Signal each member that's still the same process; return the pids that refused."""
    refused = []
    for proc in members:
        if current(proc.pid) != proc.ident:
            continue  # exited, or the pid now belongs to another process
        try:
            send(proc.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            refused.append(proc.pid)
    return refused


def kill(owners, head, scan=processes, send=os.kill, current=identity):
    """Stop the command until no new process joins it, then kill it all. Returns the
    members killed and the pids that refused."""
    stopped = {}
    try:
        for _ in range(20):
            members = owners.attribute(scan()).get(head, [])
            new = [proc for proc in members if proc.ident not in stopped]
            if not new:
                break
            signal_all(new, signal.SIGSTOP, send, current)
            stopped.update((proc.ident, proc) for proc in new)
    finally:  # never leave a command stopped
        refused = signal_all(stopped.values(), signal.SIGKILL, send, current)
    return list(stopped.values()), refused


def command_text(args):
    """What the agent ran, or the whole argv when no agent's wrapper shell is around it."""
    return agent_command(args) or " ".join(args)


def agent_command(argv):
    """The command an agent ran, from its wrapper shell's argv; None for any other argv.
    A Claude Bash call wraps it as `<setup> && eval '<cmd>' < /dev/null && pwd -P >| <file>`,
    without `< /dev/null` when <cmd> has a heredoc, and with each ' in <cmd> written as
    '"'"'. Codex runs it as `<shell> -lc <cmd>`."""
    text = " ".join(argv)
    start = text.find("eval '")
    if start >= 0:
        end = text.rfind(" && pwd -P >| ")
        quoted = text[start + 6:end if end > start else len(text)]
        return quoted.removesuffix(" < /dev/null").removesuffix("'").replace("'\"'\"'", "'")
    if (len(argv) == 3 and os.path.basename(argv[0]).lstrip("-") in SHELLS
            and argv[1] in ("-lc", "-c")):
        return argv[2]
    return None


def entry(owners, head, members, reason, **more):
    """The log line for killing members of the command `head`, the fields
    agent-memory-guard-notice.py matches on: agent_pid and the full command's hash for
    Claude, tool_call_id (CODEX_TOOL_CALL_ID) for Codex. `more` adds fields, such as
    rule="queue" and unit=<text>."""
    first = next((p for p in members if p.ident == head), None)
    text = command_text(owners.argv.get(head) or (first or members[0]).argv)
    line = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "at": time.time(), "reason": reason,
            "processes": len(members), "gb": round(footprint(members) / GB, 1),
            "agent_pid": first.ppid if first and first.ppid > 1 else None,
            "command_sha256": hashlib.sha256(text.encode()).hexdigest(), "command": text[:500],
            "tool_call_id": next((p.tool_call for p in members if p.tool_call), None)}
    line.update(more)
    return line


def record(line):
    """Appends one JSON line to LOG; never raises, since a full disk must not stop a kill."""
    try:
        with open(LOG, "a") as log:
            log.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError as error:
        print(f"{line.get('time', '')} couldn't log a {line.get('event', 'kill')}: {error!r}",
              file=sys.stderr, flush=True)


def notify(title, subtitle, text):
    subprocess.Popen(
        ["osascript", "-e", "on run argv", "-e",
         "display notification (item 3 of argv) with title (item 1 of argv) "
         "subtitle (item 2 of argv)", "-e", "end run", title, subtitle, text[:200]],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# The check queue: at most checkQueue.maxChecks heavy checks run across every agent's
# commands, and a new one waits, stopped, until a slot frees and running checks use under
# checkQueue.maxCores. A unit is the topmost heavy process with its descendants, so
# turbo's eight lint tasks are eight units while oxlint's own tsgolint child shares
# oxlint's slot: a child waiting on a slot its parent holds would deadlock.
HOLD_SECONDS = 15 * 60  # a unit still held this long, with the queue still full, dies
GATE_WINDOW_SECONDS = 2  # the CPU gate's window, and the least time between admissions
# A unit first seen older than this is never held: SIGSTOP mid-run turns a test's timers
# into timeouts, and a unit started before the governor, or before it was re-enabled, is
# never held either. Three seconds covers a scan delayed by a loaded Mac.
NEW_UNIT_SECONDS = 3
QUEUE = os.path.join(os.path.expanduser(os.environ.get("ADDYSTACK_STATE", "~/.local/state/addystack")),
                     "check-queue.json")
# A checker's binary, or the script an interpreter runs: node_modules/.bin/tsc,
# typescript/bin/tsc, vitest.mjs, eslint.js, a native tsgolint.
HEAVY = re.compile(r"(^|/)(tsc|tsgo|tsgolint|oxlint|eslint|vitest|jest)(\.c?m?js)?$"
                   r"|@typescript/native-preview")
INTERPRETERS = {"node", "bun", "bunx", "deno", "npx"}
# Each checker's own watch flags: Jest's `-w` is --maxWorkers, a one-off run.
WATCH_FLAGS = {"tsc": {"--watch", "-w"}, "tsgo": {"--watch", "-w"}, "vitest": {"--watch", "-w"},
               "jest": {"--watch", "--watchAll"}}
UNIT_IDLE_TICKS = 2  # a running unit missing this many scans in a row has finished

# top: the topmost heavy process's ident, the unit's id; head: its command's head;
# members: the top and its descendants.
Unit = namedtuple("Unit", "top head members")


def is_heavy(argv):
    """Whether argv runs a heavy check: tsc, tsgo, tsgolint, oxlint, eslint, jest, or
    vitest not watching, by the binary or an interpreter's script, never a later
    argument, so `grep tsc` isn't one. A watcher (`--watch`, `-w`, `vitest watch`,
    `vitest dev`) and tsserver are servers, not checks."""
    if not argv or any("tsserver" in arg for arg in argv[:3]):
        return False
    tool, rest = argv[0], argv[1:]
    if not HEAVY.search(tool):
        if os.path.basename(tool) not in INTERPRETERS:
            return False
        index = next((i for i, arg in enumerate(rest)
                      if not arg.startswith("-") and arg not in {"run", "x", "exec"}), None)
        if index is None or not HEAVY.search(rest[index]):
            return False
        tool, rest = rest[index], rest[index + 1:]
    name = HEAVY.search(tool).group(2) or "tsgo"  # native-preview's binary is tsgo
    flags = WATCH_FLAGS.get(name, set())
    watching = any(arg in flags or ("--watch" in flags and arg.startswith("--watch=") and arg != "--watch=false")
                   for arg in rest)
    vitest_server = name == "vitest" and rest[:1] in (["watch"], ["dev"])
    return not (watching or vitest_server)


def heavy_units(commands):
    """{top ident: Unit} for every heavy unit in commands ({head: [Proc]})."""
    units = {}
    for head, members in commands.items():
        by_ident = {proc.ident: proc for proc in members}
        hot = {proc.ident for proc in members if is_heavy(proc.argv)}
        if not hot:
            continue
        children = {}
        for proc in members:
            children.setdefault(proc.parent_ident, []).append(proc)

        def ancestors(proc):
            seen = set()
            while proc.parent_ident in by_ident and proc.parent_ident not in seen:
                seen.add(proc.parent_ident)
                proc = by_ident[proc.parent_ident]
                yield proc.ident

        for top in (by_ident[ident] for ident in hot):
            if any(ident in hot for ident in ancestors(top)):
                continue
            tree, stack = [], [top]
            while stack:
                proc = stack.pop()
                tree.append(proc)
                stack.extend(child for child in children.get(proc.ident, []) if child.ident != top.ident)
            units[top.ident] = Unit(top.ident, head, tree)
    return units


_settings = [None, None]  # resolved.json's mtime, and the CheckQueue read at it


def settings():
    """resolved.check_queue(), read again only when resolved.json's mtime changes."""
    import resolved  # here, so a broken config module fails only the check queue
    try:
        mtime = resolved.STATE.expanduser().stat().st_mtime_ns
    except OSError:
        mtime = None
    if _settings[1] is None or _settings[0] != mtime:
        _settings[:] = [mtime, resolved.check_queue()]
    return _settings[1]


class Governor:
    """Every check-queue decision and side effect: units, the cap, the CPU gate, tick
    order, the hold limit, signals, QUEUE, and its log lines. Each tick it drops finished
    units, resumes held ones oldest first, admits new units only when none wait, then
    kills a unit held HOLD_SECONDS with the queue still full. A unit is written to QUEUE
    before it's stopped, and only a unit first seen within NEW_UNIT_SECONDS of its start,
    after the governor started or was re-enabled, is ever held. Memory and CPU rules in
    tick() still run, and win."""

    def __init__(self, settings=settings, state=QUEUE, send=os.kill, current=identity,
                 record=record, notify=notify, wall=time.time):
        """Resumes what an earlier guard left stopped, where the kernel ident still
        matches, and clears `state`."""
        self.settings, self.state, self.send, self.current = settings, state, send, current
        self.record, self.notify = record, notify
        self.started = wall()  # units that started before this are never held
        self.enabled = True
        self.running = {}  # top -> scans missed in a row
        self.held = {}  # top -> {"members": {ident: Proc}, "since": now, "head", "text"}, oldest first
        self.cpu = {}  # top -> (last, debt, began, [(now, total ns)])
        self.last_admit = None  # monotonic time a unit last started or resumed
        self.error = None
        self._resume_saved()

    def tick(self, owners, commands, agents, now, wall):
        """One pass over commands ({head: [Proc]}) with agents ({pid: ident}), `now` on
        the monotonic clock and `wall` the epoch. Never raises: on an error it resumes
        every held unit and reports the error once."""
        try:
            self._tick(owners, commands, agents, now, wall)
            self.error = None
        except Exception as error:  # the memory rules must still run this tick
            self.release(f"the check queue failed: {error!r}")
            if repr(error) != self.error:
                print(f"{time.strftime('%H:%M:%S')} check queue failed: {error!r}",
                      file=sys.stderr, flush=True)
            self.error = repr(error)

    def release(self, why):
        """Resumes every held unit and clears the state file: disabled, stopping, or an
        error."""
        try:
            for top, unit in list(self.held.items()):
                signal_all(unit["members"].values(), signal.SIGCONT, self.send, self.current)
                self.running[top] = 0  # it runs now, so no later tick holds it again
                self._log("release", unit, why=why)
            self.held.clear()
            self._save()
        except Exception as error:  # a release runs on the way out; never fail it
            print(f"{time.strftime('%H:%M:%S')} check queue release failed: {error!r}",
                  file=sys.stderr, flush=True)

    def _tick(self, owners, commands, agents, now, wall):
        config = self.settings()
        if not config.enabled:
            if self.held:
                self.release("the check queue is off")
            self.enabled = False
            self.running.clear()
            self.cpu.clear()
            return
        if not self.enabled:  # re-enabled: what runs now runs on
            self.enabled, self.started = True, wall
        units = heavy_units(commands)
        # 1. Drop finished units.
        for top in list(self.running):
            if top in units:
                self.running[top] = 0
            else:
                self.running[top] += 1
                if self.running[top] >= UNIT_IDLE_TICKS:
                    del self.running[top]
                    self.cpu.pop(top, None)
        alive = {proc.ident for members in commands.values() for proc in members}
        for top in [top for top in self.held if top not in units]:
            if top in alive:
                continue  # still there, only not read as heavy this scan: keep it held
            # It exited, or a memory rule killed its command: resume any member left.
            signal_all(self.held[top]["members"].values(), signal.SIGCONT, self.send, self.current)
            self._forget(top)
        self._measure(units, now, wall)
        # 2. Keep held units stopped, and let go of one whose agent no longer waits.
        for top, unit in list(self.held.items()):
            if top not in units:
                continue
            members = units[top].members
            if not self._attended(commands[unit["head"]], agents):
                self._resume(top, units, now, wall, "its agent's shell is gone")
                continue
            joined = [proc for proc in members if proc.ident not in unit["members"]]
            if joined:
                unit["members"].update((proc.ident, proc) for proc in joined)
                try:
                    self._save()
                except OSError:
                    self._resume(top, units, now, wall, "its new members couldn't be saved")
                    continue
                signal_all(joined, signal.SIGSTOP, self.send, self.current)
        # 3. Resume held units, oldest first, while there's room.
        while self.held and self._room(config, now):
            self._resume(next(iter(self.held)), units, now, wall, "a slot freed")
        # 4. Admit new units only when none wait; hold the rest.
        new = [unit for top, unit in units.items() if top not in self.running and top not in self.held]
        tops = {unit.top: next(proc for proc in unit.members if proc.ident == unit.top) for unit in new}
        for unit in sorted(new, key=lambda unit: tops[unit.top].start):
            top = tops[unit.top]
            holdable = (top.start >= self.started and wall - top.start <= NEW_UNIT_SECONDS
                        and self._attended(commands[unit.head], agents))
            if not holdable:
                self._run(unit.top, unit.members, now, wall)  # already running: never stopped
            elif not self.held and self._room(config, now):
                self._run(unit.top, unit.members, now, wall)
                self.last_admit = now
            else:
                self._hold(owners, unit, commands[unit.head], now, wall)
        # 5. Kill a unit held too long while the queue is still full. One held only by the
        # admission spacing gets its turn within GATE_WINDOW_SECONDS instead.
        full = len(self.running) >= config.maxChecks or (
            bool(self.running) and self._cores(now) >= config.maxCores)
        for top, unit in list(self.held.items()):
            if full and now - unit["since"] >= HOLD_SECONDS:
                self._kill(owners, top, unit, len(self.running))

    def _attended(self, members, agents):
        """Whether an agent still waits on the command: its shell, or itself, is a live
        agent's direct child."""
        return any(agents.get(proc.ppid) == proc.parent_ident for proc in members)

    def _room(self, config, now):
        """Whether one more unit may run: under the cap, and when any unit runs, nothing
        admitted within the gate's window and running units under maxCores over it."""
        if len(self.running) >= config.maxChecks:
            return False
        if not self.running:
            return True
        if self.last_admit is not None and now - self.last_admit < GATE_WINDOW_SECONDS:
            return False
        return self._cores(now) < config.maxCores

    def _measure(self, units, now, wall):
        """Adds each running unit's CPU since the last tick to its marks."""
        for top in self.running:
            if top not in units:
                continue
            last, debt, began, marks = self.cpu.get(top) or ({}, {}, wall, [])
            gained, last, debt = cpu_gained(units[top].members, last, debt, began)
            total = (marks[-1][1] if marks else 0) + gained
            # Keep the newest mark at least a window old, so the window is measured whole.
            old = [i for i, mark in enumerate(marks) if now - mark[0] >= GATE_WINDOW_SECONDS]
            marks = marks[old[-1] if old else 0:] + [(now, total)]
            self.cpu[top] = (last, debt, began, marks)

    def _cores(self, now):
        """Cores the running units used over the last GATE_WINDOW_SECONDS: each unit's CPU
        since its newest mark at least a window old, over the time since that mark. A unit
        tracked for less than the window counts what it used, over the whole window."""
        cores = 0
        for top in self.running:
            marks = self.cpu.get(top, (None, None, None, []))[3]
            if len(marks) < 2:
                continue
            old = [mark for mark in marks if now - mark[0] >= GATE_WINDOW_SECONDS]
            since, before = old[-1] if old else marks[0]
            span = now - since if old else GATE_WINDOW_SECONDS
            cores += (marks[-1][1] - before) / 1e9 / span
        return cores

    def _run(self, top, members, now, wall):
        """Counts the unit as running, and takes its first CPU sample now, so the gate
        counts its first tick."""
        self.running[top] = 0
        _, last, debt = cpu_gained(members, {}, {}, wall)
        self.cpu[top] = (last, debt, wall, [(now, 0)])

    def _hold(self, owners, unit, command, now, wall):
        members = {proc.ident: proc for proc in unit.members}
        # The notice matches a Claude kill by the agent's pid, the head's parent.
        head = next((proc for proc in command if proc.ident == unit.head), None)
        held = {"members": members, "since": now, "head": unit.head,
                "agent_pid": head.ppid if head is not None and head.ppid > 1 else None,
                "text": " ".join(os.path.basename(arg) for arg in
                                 next(p for p in unit.members if p.ident == unit.top).argv[:4])[:70],
                # Whole: the notice matches it by its hash. Logs show its start.
                "command": command_text(owners.argv.get(unit.head) or members[unit.top].argv)}
        self.held[unit.top] = held
        try:
            self._save()  # saved before it's stopped, so a crash can't strand it
        except OSError as error:
            del self.held[unit.top]
            self._run(unit.top, unit.members, now, wall)
            print(f"{time.strftime('%H:%M:%S')} check queue couldn't save a held unit; it runs: "
                  f"{error!r}", file=sys.stderr, flush=True)
            return
        signal_all(unit.members, signal.SIGSTOP, self.send, self.current)
        self._log("stop", held)

    def _resume(self, top, units, now, wall, why):
        unit = self.held[top]
        members = list(unit["members"].values())
        if top in units:
            members += [proc for proc in units[top].members if proc.ident not in unit["members"]]
        signal_all(members, signal.SIGCONT, self.send, self.current)
        self._forget(top)  # only once it runs, so a failed write can't strand it
        self._run(top, members, now, wall)
        self.last_admit = now
        self._log("cont", unit, why=why, waited=round(now - unit["since"], 1))

    def _kill(self, owners, top, unit, running):
        members = list(unit["members"].values())
        reason = (f"held {HOLD_SECONDS // 60} min while the machine's check queue stayed full "
                  f"({running} {'check' if running == 1 else 'checks'} running)")
        line = entry(owners, unit["head"], members, reason, rule="queue", unit=unit["text"])
        line["command"], line["agent_pid"] = unit["command"][:500], unit["agent_pid"]
        line["command_sha256"] = hashlib.sha256(unit["command"].encode()).hexdigest()
        self.record(line)  # logged before the kill, so the notice finds it
        signal_all(members, signal.SIGKILL, self.send, self.current)
        self._forget(top)
        try:
            self.notify("Killed a queued agent check", reason, unit["command"])
        except OSError:
            pass

    def _log(self, event, unit, **more):
        self.record({"event": event, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "at": time.time(),
                     "unit": unit["text"], "command": unit["command"][:200], "running": len(self.running),
                     "held": len(self.held), **more})

    def _forget(self, top):
        """Drops a held unit once its processes ran or died. A failed write leaves its
        record, which the next guard start resumes harmlessly."""
        del self.held[top]
        try:
            self._save()
        except OSError as error:
            print(f"{time.strftime('%H:%M:%S')} check queue couldn't save: {error!r}",
                  file=sys.stderr, flush=True)

    def _save(self):
        """Writes the held units, oldest first, to the state file in one rename."""
        units = [{"unit": top, "members": [[proc.pid, proc.ident] for proc in unit["members"].values()]}
                 for top, unit in self.held.items()]
        os.makedirs(os.path.dirname(self.state), exist_ok=True)
        tmp = f"{self.state}.{os.getpid()}.tmp"
        with open(tmp, "w") as file:
            json.dump({"held": units}, file)
        os.replace(tmp, self.state)

    def _resume_saved(self):
        """Resumes each member an earlier guard saved and left stopped, then clears the
        file. A pid whose kernel ident changed belongs to another process now."""
        try:
            with open(self.state) as file:
                saved = json.load(file)["held"]
        except (OSError, ValueError, KeyError, TypeError):
            saved = []
        for unit in saved:
            try:
                members = [Proc(pid, 0, 0, ident, 0, 0, 0, [], None) for pid, ident in unit["members"]]
            except (TypeError, ValueError, KeyError):
                continue
            signal_all(members, signal.SIGCONT, self.send, self.current)
        try:
            self._save()
        except OSError:
            pass


def tick(owners, scan=processes, abandoned=None, now=time.monotonic, wall=time.time, governor=None):
    procs = scan()
    commands = owners.attribute(procs)
    agents = {pid: proc.ident for pid, proc in procs.items() if is_agent(proc)}
    if governor is not None:
        governor.tick(owners, commands, agents, now(), wall())  # never raises
    found = runaway(commands, owners.services)
    if not found and abandoned is not None:
        found = abandoned.busy(commands, agents, now(), wall())
    if not found:
        return None
    head, reason = found
    # Logged before the kill, so agent-memory-guard-notice.py finds it once the command
    # fails; agent_pid, the full command's hash, and tool_call_id tell it which run died.
    line = entry(owners, head, commands[head], reason)
    record(line)
    _, refused = kill(owners, head, scan)
    if refused:
        print(f"{line['time']} couldn't kill {refused} of {line['command'][:80]!r}",
              file=sys.stderr, flush=True)
    try:
        notify("Killed a runaway agent command", reason, line["command"])
    except OSError:
        pass  # no notification while the process table is full; the log has it
    return line


def main():
    owners, abandoned, last_error = Owners(), Abandoned(), None
    governor = Governor()  # resumes what an earlier guard left stopped
    # launchd stops the guard with SIGTERM; exiting through `finally` resumes held checks.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        while True:
            try:
                tick(owners, abandoned=abandoned, governor=governor)
                last_error = None
            except Exception as error:  # keep guarding; log each distinct failure once
                if repr(error) != last_error:
                    print(f"{time.strftime('%H:%M:%S')} tick failed: {error!r}",
                          file=sys.stderr, flush=True)
                last_error = repr(error)
            time.sleep(INTERVAL_SECONDS)
    finally:
        governor.release("the guard is stopping")


if __name__ == "__main__":
    main()
