"""Tests for common.sh's require_own_web: a stand-in server on a free port, and a run
folder whose web.pid does or doesn't own it. No Franklin checkout or app needed."""
import pathlib, socket, subprocess, sys, tempfile, time, unittest

COMMON = pathlib.Path(__file__).resolve().parent / "common.sh"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def listening(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def require_own_web(run, port):
    """Exit status and stderr of require_own_web with CURRENT=run and WEB_PORT=port."""
    script = f'source "{COMMON}"; CURRENT="{run}"; WEB_PORT={port}; require_own_web'
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "VERIFY_REPO": str(run)})
    return result.returncode, result.stderr


class RequireOwnWeb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = pathlib.Path(self.tmp.name)
        self.port = free_port()
        # A wrapper shell with the server as its child, as launch.sh records web.pid.
        self.wrapper = subprocess.Popen(
            ["sh", "-c", f'"{sys.executable}" -m http.server {self.port} --bind 127.0.0.1; true'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(self.stop_server)
        deadline = time.monotonic() + 10
        while not listening(self.port):
            self.assertLess(time.monotonic(), deadline, "stand-in server didn't start")
            time.sleep(0.1)

    def stop_server(self):
        subprocess.run(["pkill", "-P", str(self.wrapper.pid)])
        self.wrapper.kill()
        self.wrapper.wait()
        self.tmp.cleanup()

    def record(self, pid):
        (self.run_dir / "web.pid").write_text(f"{pid}\n")

    def test_passes_when_the_run_started_the_server(self):
        self.record(self.wrapper.pid)
        self.assertEqual(require_own_web(self.run_dir, self.port), (0, ""))

    def test_refuses_a_server_another_process_started(self):
        other = subprocess.Popen(["sleep", "30"])
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)
        self.record(other.pid)
        status, error = require_own_web(self.run_dir, self.port)
        self.assertEqual(status, 1)
        self.assertIn("not served by this run", error)

    def test_refuses_when_nothing_listens(self):
        self.record(self.wrapper.pid)
        status, error = require_own_web(self.run_dir, free_port())
        self.assertEqual(status, 1)
        self.assertIn("not served by this run", error)

    def test_refuses_without_a_run(self):
        status, error = require_own_web(self.run_dir / "missing", self.port)
        self.assertEqual(status, 1)
        self.assertIn("no run", error)


if __name__ == "__main__":
    unittest.main()
