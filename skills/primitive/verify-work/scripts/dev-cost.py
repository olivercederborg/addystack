#!/usr/bin/env python3
"""Measure one cold dev-server run and print the line the toolchain evidence kind reads.

    dev-cost.py LABEL --url URL [--path /page ...] [--clean DIR ...] -- COMMAND...

Removes each --clean directory (the bundler's cache, such as `.next`), starts COMMAND in
its own process group, waits until URL answers, then requests each --path in order so the
dev server compiles it. It samples the summed RSS and the process count of COMMAND's
process tree every half second, stops the group, and prints:

    LABEL: peak_rss_mb=5815 procs=14 startup_s=29.4 compile_s=8.4

LABEL is `base` or `head`. Run it in a worktree of each, alternating, at least twice each,
and append every line to one log."""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

STARTUP_LIMIT_S = 600


def tree(root: int) -> list[tuple[int, int]]:
    """Each process under `root`, root included, as (pid, rss_kb)."""
    rows = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss="], capture_output=True, text=True).stdout.split()
    children: dict[int, list[int]] = {}
    rss: dict[int, int] = {}
    for pid, ppid, kb in zip(*[iter(map(int, rows))] * 3):
        children.setdefault(ppid, []).append(pid)
        rss[pid] = kb
    found, queue = [], [root]
    while queue:
        pid = queue.pop()
        if pid in rss:
            found.append((pid, rss[pid]))
            queue.extend(children.get(pid, []))
    return found


def answers(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=600)
        return True
    except urllib.error.HTTPError:
        return True  # a 404 or a redirect still means the server is up and compiled the route
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("label", choices=["base", "head"])
    parser.add_argument("--url", required=True, help="the dev server's origin, such as http://localhost:3100")
    parser.add_argument("--path", action="append", default=[], help="a page to compile, in order")
    parser.add_argument("--clean", action="append", default=[], help="a cache directory to remove first")
    argv = sys.argv[1:]
    if "--" not in argv or argv.index("--") == len(argv) - 1:
        parser.error("give the dev command after --")
    args, command = parser.parse_args(argv[:argv.index("--")]), argv[argv.index("--") + 1:]

    for directory in args.clean:
        shutil.rmtree(directory, ignore_errors=True)
    server = subprocess.Popen(command, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    peak_kb, procs, done = 0, 0, threading.Event()

    def sample() -> None:
        nonlocal peak_kb, procs
        while not done.is_set():
            found = tree(server.pid)
            peak_kb, procs = max(peak_kb, sum(kb for _, kb in found)), max(procs, len(found))
            done.wait(0.5)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    started = time.monotonic()
    try:
        while not answers(args.url):
            if server.poll() is not None:
                raise SystemExit(f"the dev command exited with {server.returncode} before {args.url} answered")
            if time.monotonic() - started > STARTUP_LIMIT_S:
                raise SystemExit(f"{args.url} didn't answer within {STARTUP_LIMIT_S}s")
            time.sleep(0.3)
        startup = time.monotonic() - started
        compiling = time.monotonic()
        for path in args.path:
            answers(args.url.rstrip("/") + path)
        compile_s = time.monotonic() - compiling
        time.sleep(3)  # let workers spawned for the last compile show up
    finally:
        done.set()
        sampler.join()
        stop(server)
    print(f"{args.label}: peak_rss_mb={peak_kb // 1024} procs={procs} "
          f"startup_s={startup:.1f} compile_s={compile_s:.1f}")


def stop(server: subprocess.Popen) -> None:
    """End the dev server's whole process group, forcibly after 10 seconds."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(server.pid, sig)
            server.wait(timeout=10)
            return
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            continue


if __name__ == "__main__":
    main()
