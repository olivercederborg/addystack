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
included, gets 2 hours at that rate, the longest Claude Code's Bash tool waits: on Nov 27,
2026 two `bun` probe scripts Codex started without a shell spun at 100% CPU for 9 and 11
hours under a live Codex, long after their threads finished.

Known limits:
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
  counts toward the total.
- A CPU-heavy job an agent starts dies at over half a core: after 30 minutes when the
  agent doesn't wait on it (`nohup` or `&`), after 2 hours when it does, a background
  task it tracks included. Run a longer one in a terminal, outside the agent.
- A worker whose parent exits before reaping it loses the CPU it used after the last tick
  saw it."""
import ctypes, ctypes.util, hashlib, json, os, plistlib, signal, struct, subprocess, sys, time
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
# averages ABANDONED_CORES over this longer window.
ATTENDED_WINDOW_SECONDS = 2 * 60 * 60
CHECKPOINT_SECONDS = 5  # CPU in a window's first this-many seconds may go uncounted
LOG = os.path.expanduser("~/Library/Logs/agent-memory-guard.log")

# ident is the kernel's process id that's never reused within a boot and survives exec;
# version changes on every exec (XNU kern_exec.c, "identity version"); parent_ident is
# the parent's ident, so a parent link survives pid reuse.
# cpu is the process's own user plus system time and reaped its reaped children's, in
# nanoseconds, or None when the read failed; start is when it started, in seconds since
# the epoch.
Proc = namedtuple("Proc", "pid ppid pgid ident version parent_ident footprint argv marked "
                  "cpu start reaped", defaults=(0, 0, 0))


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
command_lines = {}


def parse_procargs(raw):
    """KERN_PROCARGS2 is argc, the exec path, NUL padding, argv, then the environment.
    Returns argv and whether the environment marks the process as agent work, or None
    when the environment is hidden or empty, as macOS hides Apple binaries'."""
    argc = struct.unpack("i", raw[:4])[0]
    body = raw[4:]
    start = body.find(b"\0")
    while 0 <= start < len(body) and body[start] == 0:
        start += 1
    fields = body[start:].split(b"\0") if start >= 0 else []
    args = [arg.decode(errors="replace") for arg in fields[:argc]]
    env = [var for var in fields[argc:] if var]
    return args, any(var.startswith(AGENT_ENV) for var in env) if env else None


def command_line(pid, ident, version):
    """The process's argv and agent mark, read once per exec. The kernel hides argv from
    other users and the environment of Apple's own binaries (sleep, zsh), so either can
    come back empty; a failed read is retried next tick."""
    key = (ident, version)
    if key not in command_lines:
        raw = sysctl([CTL_KERN, KERN_PROCARGS2, pid], args_buffer)
        if not raw:
            return [], False
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
        result[pid] = Proc(pid, info.bsd.ppid, info.bsd.pgid, ident, version,
                           info.ids.parent_ident, footprint, *command_line(pid, ident, version),
                           cpu, info.bsd.start_sec + info.bsd.start_usec / 1e6, reaped)
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
    same way over the 2-hour window; one that moves between the two states starts over."""

    def __init__(self):
        # head -> (attended, wall time first seen in that state,
        #          last {ident: (cpu ns, reaped ns, parent ident)},
        #          debt {ident: ns}, total ns, [(time, total)] oldest first)
        self.state = {}

    def busy(self, commands, agents, now, wall=None):
        """Return (head, reason) for a command whose CPU inside the last window is over
        ABANDONED_CORES for the whole window, or None: 30 minutes for an abandoned command,
        2 hours for one an agent still waits on. `agents` maps each agent's pid to its
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
            seen, debt, here = {}, dict(debt), {proc.ident for proc in members}
            for ident in last.keys() - here:
                # The nearest ancestor still here reaps it, directly or through parents
                # that vanished with it, and its reaped CPU then holds this one's again.
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
                    total += max(0, proc.cpu - cpu)
                    gained = max(0, proc.reaped - reaped)
                    owed = debt.pop(proc.ident, 0)
                    if owed > gained:
                        debt[proc.ident] = owed - gained
                    total += max(0, gained - owed)
                elif proc.start > began:
                    total += proc.cpu + proc.reaped  # started since: all of it is new
                # else it existed before tracking began, so it counts from now
                seen[proc.ident] = (proc.cpu, proc.reaped, proc.parent_ident)
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
            if cores > ABANDONED_CORES:
                label = "busy while its agent waits on it" if attended else "abandoned by its agent"
                found = head, f"{label}, at {cores:.1f} cores for {window // 60} min"
        self.state = kept
        return found


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
    """What the agent ran. A Claude Bash call wraps it as
    `<setup> && eval '<cmd>' < /dev/null && pwd -P >| <file>`, without `< /dev/null` when
    <cmd> has a heredoc, and with each ' in <cmd> written as '"'"'."""
    text = " ".join(args)
    start = text.find("eval '")
    if start < 0:
        return text
    end = text.rfind(" && pwd -P >| ")
    quoted = text[start + 6:end if end > start else len(text)]
    return quoted.removesuffix(" < /dev/null").removesuffix("'").replace("'\"'\"'", "'")


def notify(title, subtitle, text):
    subprocess.Popen(
        ["osascript", "-e", "on run argv", "-e",
         "display notification (item 3 of argv) with title (item 1 of argv) "
         "subtitle (item 2 of argv)", "-e", "end run", title, subtitle, text[:200]],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def tick(owners, scan=processes, abandoned=None, now=time.monotonic, wall=time.time):
    procs = scan()
    commands = owners.attribute(procs)
    found = runaway(commands, owners.services)
    if not found and abandoned is not None:
        agents = {pid: proc.ident for pid, proc in procs.items() if is_agent(proc)}
        found = abandoned.busy(commands, agents, now(), wall())
    if not found:
        return None
    head, reason = found
    members = commands[head]
    first = next((p for p in members if p.ident == head), None)
    text = command_text((first or members[0]).argv)
    # Logged before the kill, so agent-memory-guard-notice.py finds it once the command
    # fails; agent_pid and the full command's hash tell it which run was killed.
    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "at": time.time(), "reason": reason,
             "processes": len(members), "gb": round(footprint(members) / GB, 1),
             "agent_pid": first.ppid if first and first.ppid > 1 else None,
             "command_sha256": hashlib.sha256(text.encode()).hexdigest(), "command": text[:500]}
    try:
        with open(LOG, "a") as log:
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as error:  # a full disk must not stop the kill
        print(f"{entry['time']} couldn't log a kill: {error!r}", file=sys.stderr, flush=True)
    _, refused = kill(owners, head, scan)
    if refused:
        print(f"{entry['time']} couldn't kill {refused} of {text[:80]!r}",
              file=sys.stderr, flush=True)
    try:
        notify("Killed a runaway agent command", reason, text)
    except OSError:
        pass  # no notification while the process table is full; the log has it
    return entry


def main():
    owners, abandoned, last_error = Owners(), Abandoned(), None
    while True:
        try:
            tick(owners, abandoned=abandoned)
            last_error = None
        except Exception as error:  # keep guarding; log each distinct failure once
            if repr(error) != last_error:
                print(f"{time.strftime('%H:%M:%S')} tick failed: {error!r}",
                      file=sys.stderr, flush=True)
            last_error = repr(error)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
