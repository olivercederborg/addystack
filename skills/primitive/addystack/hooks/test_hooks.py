"""Pipe tests for the PreToolUse hooks: feed each hook the JSON Claude Code sends and
check whether it denies."""
import contextlib, dataclasses, functools, hashlib, json, os, pathlib, random, re, shlex, shutil, sqlite3, subprocess, sys, tempfile, time, unittest, unittest.mock, warnings

import hook_parity, merge_go, resolved, transcripts, turn_block, verdicts, workflow_triggers

try:
    from markdown_it import MarkdownIt
except ImportError:
    MarkdownIt = None
try:
    import html5lib
except ImportError:
    html5lib = None

HOOKS = pathlib.Path(__file__).resolve().parent
# The checkout: the addystack skill's folder is skills/primitive/addystack.
REPO = HOOKS.parents[3]
# A reply rules file: the maintainer's replies.md in the workshop, a stand-in in the kit.
RULES = REPO / "replies.md"
if not RULES.is_file():
    RULES = pathlib.Path(tempfile.mkdtemp(prefix="replies-"), "replies.md")
    RULES.write_text("# Replies\n\nEnd each reply on a Next block.\n")
# Where merge-gate's deny reasons point, as they print it.
STACK_SH = str(HOOKS.parent / "scripts" / "stack.sh").replace(os.path.expanduser("~"), "~", 1)

# Transcript entries in each shape the hooks read, and a T3 citation block whose comment isn't text.
ENTRIES = [
    {"type": "user", "message": {"content": "merge it"}},
    {"type": "user", "message": {"content": [{"type": "text", "text": "merge it"}]}},
    {"type": "response_item", "payload": {"type": "message", "role": "user",
                                          "content": [{"type": "input_text", "text": "merge it"}]}},
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                   "input": {"command": "gh stack push"}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
    {"type": "user", "message": {"content": '<assistant_citations>\n[{"citation": {"comment": 1}}]\n'
                                            "</assistant_citations>"}},
]


# Lines no shape swap makes: one that isn't JSON, and nesting Python 3.9 recurses on.
UNPARSED = ['{"type": "user", "message":', "[" * 2000 + "0" + "]" * 2000]
# Each Python a hook may run under: this one, and macOS's own, an older one.
PYTHONS = [sys.executable, *(["/usr/bin/python3"] if os.path.exists("/usr/bin/python3") else [])]


def malformed(value):
    """Each copy of value with one value in it, or value itself, swapped for another JSON type."""
    yield from (bad for bad in (None, 1, "x", [], {}) if type(bad) is not type(value))
    for key, child in (value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()):
        for bad in malformed(child):
            yield {**value, key: bad} if isinstance(value, dict) else [*value[:key], bad, *value[key + 1:]]


def resolved_state(folder, config_text, kit=None):
    """os.environ with ADDYSTACK_STATE at a resolved.json that lib/config.py built from
    config_text, a user config, as `addystack build` writes it, for the kit at kit or this
    checkout."""
    if str(HOOKS.parent / "lib") not in sys.path:
        sys.path.append(str(HOOKS.parent / "lib"))
    import config
    user = pathlib.Path(folder, "addystack.jsonc")
    user.write_text(config_text)
    layers = config.load_layers(user)
    assert not config.validate(layers), config.validate(layers)
    value = config.merge(layers, pathlib.Path(kit) if kit else HOOKS.parent)
    pathlib.Path(folder, "resolved.json").write_text(json.dumps(value))
    return {**os.environ, "ADDYSTACK_STATE": str(folder)}


# A user config that selects every hook in the manifest: each reply hook needs its
# preference on, so it names reply-shape and a rules file, and a trial hook, one no preset
# includes, needs its id enabled.
ALL_HOOKS = json.dumps({"hooks": {"preset": "all", "enable": sorted(
    {e["id"] for es in json.loads((HOOKS / "manifest.json").read_text()).values() for e in es})}, "replies": {
    "style": "reply-shape", "rules": str(RULES), "turnBlock": True}})


def denies(hook, tool, tool_input, transcript_text="", env=None, cwd=None):
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl") as transcript:
        transcript.write(transcript_text)
        transcript.flush()
        payload = {"tool_name": tool, "tool_input": tool_input, "transcript_path": transcript.name}
        if cwd:
            payload["cwd"] = cwd
        out = subprocess.run([str(HOOKS / hook)], input=json.dumps(payload), env=env,
                             capture_output=True, text=True, check=True).stdout
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def run_hook(hook, payload, env=None):
    out = subprocess.run([str(HOOKS / hook)], input=json.dumps(payload), capture_output=True,
                         text=True, check=True, env={**os.environ, **(env or {})}).stdout
    return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""


def state_db(folder, thread, brief, creator="agent"):
    """A T3 state database in folder whose thread runs session "s" and "s1", with brief as its first message."""
    path = os.path.join(folder, f"state-{hashlib.sha1((thread + brief + creator).encode()).hexdigest()[:8]}.sqlite")
    if os.path.exists(path):
        return path
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        db.execute("create table orchestration_v2_projection_provider_threads (thread_id text, payload_json text)")
        db.execute("create table orchestration_v2_projection_messages "
                   "(thread_id text, role text, payload_json text, created_at text)")
        for session in ("s", "s1"):
            db.execute("insert into orchestration_v2_projection_provider_threads values (?, ?)",
                       (thread, json.dumps({"nativeThreadRef": {"nativeId": session}})))
        db.execute("insert into orchestration_v2_projection_messages values (?, 'user', ?, '2026-11-08')",
                   (thread, json.dumps({"text": brief, "createdBy": creator})))
    return path


def fake_home(folder, drop=()):
    """A home under folder with a kit at ~/kit whose hooks link to this checkout's, a
    resolved.json in ~/state that selects every hook, and settings.json and hooks.json
    holding every manifest entry with `{{kit}}` as ~/kit, less the commands in drop.
    Returns its env: HOME, as the resolved path, ADDYSTACK_STATE, and CLAUDE_CONFIG_DIR as
    ~/.claude, so a caller's own Claude Code folder isn't read."""
    home = pathlib.Path(folder).resolve()
    kit_hooks = home / "kit" / "hooks"
    kit_hooks.mkdir(parents=True, exist_ok=True)
    for script in HOOKS.glob("*.py"):
        if not (kit_hooks / script.name).is_symlink():
            (kit_hooks / script.name).symlink_to(script)
    (home / "state").mkdir(exist_ok=True)
    resolved_state(home / "state", ALL_HOOKS, kit=home / "kit")
    manifest = json.loads((HOOKS / "manifest.json").read_text())
    for runtime, entries in manifest.items():
        config = {"hooks": {}}
        for entry in entries:
            command = entry["command"].replace("{{kit}}", "~/kit")
            if command in drop:
                continue
            hook = {"type": "command", "command": command, "timeout": entry["timeout"],
                    **({"onFailure": entry["onFailure"]} if "onFailure" in entry else {})}
            config["hooks"].setdefault(entry["event"], []).append(
                {**({"matcher": entry["matcher"]} if entry["matcher"] else {}), "hooks": [hook]})
        path = home / {"claude": ".claude/settings.json", "codex": ".codex/hooks.json"}[runtime]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config))
    return {"HOME": str(home), "ADDYSTACK_STATE": str(home / "state"), "CLAUDE_CONFIG_DIR": str(home / ".claude")}


@unittest.skipUnless(sys.platform == "darwin", "the guard only runs on macOS")
class KeychainHomeGuard(unittest.TestCase):
    HOOK = "keychain-home-guard.py"

    def bash(self, command):
        return denies(self.HOOK, "Bash", {"command": command})

    def test_denies_keychain_writers_under_a_fake_home(self):
        for command in [
            # The commands that popped the dialog on Oct 26, 2026.
            'H=$(cat /tmp/p); export HOME="$H" XDG_CONFIG_HOME="$H/.config"; cd "$H"\n'
            '"$H/.config/yadm/bootstrap.d/45-claude-code.sh" 2>&1',
            'export HOME="$H"\nfor d in a b; do (cd "$d" && claude mcp list 2>&1); done',
            "HOME=/tmp/h gh auth status",
            "HOME=/tmp/h ~/.local/bin/claude mcp get x",
            "env HOME=/tmp/h yadm bootstrap",
            "HOME=$d git -C repo fetch origin",
            "HOME=/tmp/h security find-generic-password -s x",
            "(HOME=/tmp/h; claude --version)",
            "HOME=$(mktemp -d) claude mcp list",
            'HOME="$(mktemp -d)" yadm status',
            # An apostrophe in a comment or a double-quoted string doesn't hide what follows.
            "export HOME=$H\n# as main's manifest would leave it\nclaude mcp add-json --scope user x '{}'",
            'export HOME=/tmp/h; echo "it\'s set"; claude mcp list',
            # A heredoc a shell reads is its script, not data.
            "bash <<'EOS'\nenv -i HOME=$H2 PATH=$PATH yadm clone url\nEOS",
            "STEP=~/.config/yadm/bootstrap.d/45-claude-code.sh\nexport HOME=$H; bash $STEP > log",
            'HOME=/tmp/h X="a\\"b" claude x',
            'HOME=/tmp/h X=a\\"b claude x',
        ]:
            with self.subTest(command=command):
                self.assertTrue(self.bash(command))

    def test_allows_the_real_home_and_keychain_free_commands(self):
        for command in [
            "claude mcp list",
            "HOME=$HOME claude mcp list",
            'HOME="$HOME" gh pr view 2',
            "HOME=~ gh auth status",
            "CLAUDE_CONFIG_DIR=/tmp/c claude mcp list",
            "HOME=/tmp/fake python3 hooks/test_hooks.py",
            "HOME=/tmp/h python3 ~/.claude/hooks/reply-shape-context.py",
            "HOME=/tmp/h bash -n 45-claude-code.sh",
            "grep -n 'HOME=/tmp claude' notes.md",
            "python3 - <<'EOF'\nimport os; os.environ['HOME']='/tmp/h'\nEOF\ngh pr view 2",
            "HOME=/tmp/h git -C repo log --oneline -3",
            "HOME=/tmp/h; grep -n source ~/.config/yadm/bootstrap.d/47-codex-hooks.sh",
            "HOME=/tmp/h sed -n 1,20p bootstrap.d/45-claude-code.sh",
            'HOME=/tmp/h; grep -n "git fetch" ~/.config/yadm/bootstrap.d/47-codex-hooks.sh',
            'HOME=/tmp/h rg "git push" hooks/',
            "HOME=/tmp/h python3 - <<'EOF'\nimport subprocess  # runs gh later\nEOF",
            "F=~/.config/yadm/bootstrap.d/47-codex-hooks.sh; HOME=/tmp/h grep -n source $F",
            "HOME=/tmp/h; bash ~/dotfiles/do-thing.sh",
        ]:
            with self.subTest(command=command):
                self.assertFalse(self.bash(command))


    def test_quote_heavy_commands_finish_fast(self):
        # Overlapping assignment patterns once took over 20s here; the hook times out at 10s.
        pairs = ",".join(f'\\"k{i}\\":\\"v{i}\\"' for i in range(16))
        for command in [f'HOME=/tmp/h; P="{{{pairs}}}" curl -d "$P" x', 'HOME=/tmp/h; X=' + '""' * 30 + " y"]:
            with self.subTest(command=command):
                subprocess.run([str(HOOKS / self.HOOK)], input=json.dumps({"tool_input": {"command": command}}),
                               capture_output=True, text=True, timeout=2, check=True)

class ChildFastModeOff(unittest.TestCase):
    HOOK = "child-fast-mode-off.py"
    SESSION = "sess-parent"
    PARENT = {"instanceId": "claudeAgent", "model": "claude-opus-5-5",
              "options": [{"id": "effort", "value": "high"}, {"id": "fastMode", "value": True}]}

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        manifest = os.path.join(self.folder.name, "model-manifest.json")
        descriptors = lambda *ids: {"capabilities": {"optionDescriptors": [{"id": i} for i in ids]}}
        with open(manifest, "w") as f:
            json.dump({"manifest": {"providers": {"claudeAgent": {
                "profiles": {"opus": descriptors("effort", "fastMode"), "sonnet": descriptors("effort")},
                "models": [{"slug": "claude-opus-5-5", "profile": "opus", "aliases": ["opus"]},
                           {"slug": "claude-sonnet-5-5", "profile": "sonnet", "aliases": ["sonnet"]}]}}}}, f)
        self.env = {**os.environ, "T3CODE_CLI_PATH": "/t3", "T3_MODEL_MANIFEST": manifest}
        self.env["T3_STATE_DB"] = self.state_db(self.PARENT)

    def state_db(self, selection, owners=("thread-parent",)):
        path = os.path.join(self.folder.name, f"{len(os.listdir(self.folder.name))}-state.sqlite")
        with contextlib.closing(sqlite3.connect(path)) as db, db:
            db.execute("create table orchestration_v2_projection_provider_threads (thread_id text, payload_json text not null)")
            db.execute("create table orchestration_v2_projection_threads (thread_id text, payload_json text not null)")
            db.executemany("insert into orchestration_v2_projection_provider_threads values (?, ?)",
                           [(owner, json.dumps({"nativeThreadRef": {"nativeId": self.SESSION}})) for owner in owners])
            db.execute("insert into orchestration_v2_projection_threads values (?, ?)",
                       ("thread-parent", json.dumps({"modelSelection": selection} if selection else {})))
        return path

    def run_on(self, tool, tool_input, mode="bypassPermissions", env=None):
        payload = {"tool_name": f"mcp__t3-code__{tool}", "tool_input": tool_input,
                   "permission_mode": mode, "session_id": self.SESSION}
        out = subprocess.run([str(HOOKS / self.HOOK)], input=json.dumps(payload), capture_output=True,
                             text=True, check=True, env=env or self.env).stdout
        return json.loads(out)["hookSpecificOutput"] if out else None

    def updated(self, tool, tool_input, **kwargs):
        return self.run_on(tool, tool_input, **kwargs)["updatedInput"]

    def test_delegate_task_options_keep_their_shape(self):
        cases = [
            ({"effort": "high"}, {"effort": "high", "fastMode": False}),
            ({"fastMode": True}, {"fastMode": False}),
            ([{"id": "effort", "value": "high"}], [{"id": "effort", "value": "high"}, {"id": "fastMode", "value": False}]),
            ([{"id": "fastMode", "value": True}, {"id": "effort", "value": "max"}],
             [{"id": "fastMode", "value": False}, {"id": "effort", "value": "max"}]),
        ]
        for options, expected in cases:
            with self.subTest(options=options):
                tool_input = {"task": "t", "target": {"model": "claude-opus-5-5", "options": options}}
                self.assertEqual(self.updated("delegate_task", tool_input),
                                 {"task": "t", "target": {"model": "claude-opus-5-5", "options": expected}})

    def test_delegate_task_without_target_gets_one(self):
        # It runs the parent's model, Opus here.
        self.assertEqual(self.updated("delegate_task", {"task": "t", "mode": "async"}),
                         {"task": "t", "mode": "async", "target": {"options": {"fastMode": False}}})
        self.assertEqual(self.updated("delegate_task", {"task": "t", "target": {"model": "opus"}}),
                         {"task": "t", "target": {"model": "opus", "options": {"fastMode": False}}})

    def test_model_without_fast_mode_passes(self):
        # T3 rejects fastMode on a model whose catalog entry doesn't offer it, such as Sonnet.
        sonnet_parent = {**self.PARENT, "model": "claude-sonnet-5-5", "options": [{"id": "effort", "value": "high"}]}
        for tool, tool_input, env in (
                ("delegate_task", {"task": "t", "target": {"model": "claude-sonnet-5-5"}}, self.env),
                ("delegate_task", {"task": "t", "target": {"model": "sonnet", "options": {"effort": "low"}}}, self.env),
                ("delegate_task", {"task": "t"}, {**self.env, "T3_STATE_DB": self.state_db(sonnet_parent)}),
                ("t3_thread_launch", {"title": "x", "modelSelection": {"model": "claude-sonnet-5-5"}}, self.env),
                ("t3_thread_launch", {"title": "x"}, {**self.env, "T3_STATE_DB": self.state_db(sonnet_parent)})):
            with self.subTest(tool_input=tool_input):
                self.assertIsNone(self.run_on(tool, tool_input, env=env))

    def test_empty_options_keep_their_clear(self):
        # An empty set clears the inherited options, and T3 runs a cleared selection with fastMode off.
        for options in ({}, []):
            with self.subTest(options=options):
                self.assertIsNone(self.run_on("delegate_task", {"task": "t", "target": {"options": options}}))

    def test_passes_when_the_model_is_unknown(self):
        missing = {**self.env, "T3_MODEL_MANIFEST": "/nonexistent/model-manifest.json"}
        self.assertIsNone(self.run_on("delegate_task", {"task": "t", "target": {"model": "claude-opus-5-5"}}, env=missing))
        no_parent = {**self.env, "T3_STATE_DB": "/nonexistent/statev2.sqlite"}
        self.assertIsNone(self.run_on("delegate_task", {"task": "t"}, env=no_parent))

    def test_already_off_passes(self):
        for tool_input in ({"task": "t", "target": {"options": {"fastMode": False}}},
                           {"task": "t", "target": {"options": [{"id": "fastMode", "value": False}]}},
                           {"threads": [{"prompt": "p", "target": {"options": {"fastMode": False}}}]},
                           {"title": "x", "modelSelection": {"model": "claude-opus-5-5", "options": {"fastMode": False}}}):
            tool = ("delegate_task" if "task" in tool_input else "create_threads" if "threads" in tool_input
                    else "t3_thread_launch")
            with self.subTest(tool_input=tool_input):
                self.assertIsNone(self.run_on(tool, tool_input))

    def test_another_provider_passes(self):
        # Only Claude has fastMode; a Codex target keeps its own options.
        for target in ({"providerInstanceId": "codex", "model": "gpt-6.1-sol"}, {"model": "gpt-6.1-sol"},
                       {"driverKind": "codex"}):
            with self.subTest(target=target):
                self.assertIsNone(self.run_on("delegate_task", {"task": "t", "target": target}))
        self.assertIsNone(self.run_on("t3_thread_launch", {"title": "x", "modelSelection": {
            "instanceId": "codex", "model": "gpt-6.1-sol"}}))

    def test_create_threads_turns_off_each_thread(self):
        tool_input = {"threads": [{"prompt": "a"}, {"prompt": "b", "target": {"options": [{"id": "effort", "value": "low"}]}},
                                  {"prompt": "c", "target": {"providerInstanceId": "codex"}}]}
        self.assertEqual(self.updated("create_threads", tool_input), {"threads": [
            {"prompt": "a", "target": {"options": {"fastMode": False}}},
            {"prompt": "b", "target": {"options": [{"id": "effort", "value": "low"}, {"id": "fastMode", "value": False}]}},
            {"prompt": "c", "target": {"providerInstanceId": "codex"}}]})

    def test_launch_with_model_selection(self):
        self.assertEqual(self.updated("t3_thread_launch", {"title": "x", "modelSelection": {
            "instanceId": "claudeAgent", "model": "claude-opus-5-5", "options": [{"id": "fastMode", "value": True}]}}),
            {"title": "x", "modelSelection": {"instanceId": "claudeAgent", "model": "claude-opus-5-5",
                                              "options": [{"id": "fastMode", "value": False}]}})
        self.assertEqual(self.updated("t3_thread_launch", {"title": "x", "modelSelection": {"model": "claude-opus-5-5"}}),
                         {"title": "x", "modelSelection": {"model": "claude-opus-5-5", "options": {"fastMode": False}}})
        # T3 takes `opus` as an alias for claude-opus-5-5.
        self.assertEqual(self.updated("t3_thread_launch", {"title": "x", "modelSelection": {
            "instanceId": "claudeAgent", "model": "opus", "options": [{"id": "fastMode", "value": True}]}}),
            {"title": "x", "modelSelection": {"instanceId": "claudeAgent", "model": "opus",
                                              "options": [{"id": "fastMode", "value": False}]}})

    def test_launch_without_model_selection_copies_the_parents(self):
        env = {**self.env, "T3_STATE_DB": self.state_db(self.PARENT)}
        self.assertEqual(self.updated("t3_thread_launch", {"title": "x", "message": "m"}, env=env), {
            "title": "x", "message": "m", "modelSelection": {
                "instanceId": "claudeAgent", "model": "claude-opus-5-5",
                "options": [{"id": "effort", "value": "high"}, {"id": "fastMode", "value": False}]}})

    def test_launch_without_model_selection_passes_in_doubt(self):
        codex = {"instanceId": "codex", "model": "gpt-6.1-sol", "options": [{"id": "reasoningEffort", "value": "high"}]}
        off = {**self.PARENT, "options": [{"id": "effort", "value": "high"}, {"id": "fastMode", "value": False}]}
        dbs = {"missing": "/nonexistent/statev2.sqlite", "codex parent": self.state_db(codex),
               "already off": self.state_db(off), "no selection": self.state_db(None),
               "two owners": self.state_db(self.PARENT, owners=("thread-parent", "thread-other")),
               "no owner": self.state_db(self.PARENT, owners=())}
        for name, db in dbs.items():
            with self.subTest(name):
                self.assertIsNone(self.run_on("t3_thread_launch", {"title": "x"}, env={**self.env, "T3_STATE_DB": db}))

    def test_leaves_the_permission_decision_to_the_mode(self):
        # An "ask" would stop an auto-mode thread at a prompt.
        for mode in ("bypassPermissions", "auto", "default", "acceptEdits", "dontAsk"):
            with self.subTest(mode=mode):
                out = self.run_on("delegate_task", {"task": "t"}, mode=mode)
                self.assertEqual(set(out), {"hookEventName", "updatedInput"})

    def test_outside_t3_nothing_happens(self):
        env = {k: v for k, v in self.env.items() if k != "T3CODE_CLI_PATH"}
        self.assertIsNone(self.run_on("delegate_task", {"task": "t"}, env=env))

    def test_never_crashes(self):
        for tool, tool_input in (("delegate_task", {"task": "t", "target": {"options": [{"id": "effort", "value": "x"}]}}),
                                 ("create_threads", {"threads": [{"target": {"options": {}}}]}),
                                 ("t3_thread_launch", {"title": "x", "modelSelection": {"model": "claude-opus-5-5"}})):
            for payload in malformed({"tool_name": f"mcp__t3-code__{tool}", "tool_input": tool_input,
                                      "permission_mode": "default", "session_id": self.SESSION}):
                with self.subTest(payload=payload):
                    subprocess.run([str(HOOKS / self.HOOK)], input=json.dumps(payload), capture_output=True,
                                   text=True, check=True, env=self.env)


FAKE_WATCH_GH = r"""#!/usr/bin/env python3
import json, os, sys
s = json.load(open(os.environ["FAKE_GH"]))
a = sys.argv[1:]
open(os.environ["FAKE_GH"] + ".calls", "a").write(" ".join(a) + "\n")
if s.get("broken"):
    sys.exit("gh: network down")
if a[:2] == ["pr", "view"]:
    print(json.dumps(s["pr"]))
elif a[:2] == ["api", "user"]:
    print(s["me"])
else:
    sys.exit(1)
"""


class UnwatchGate(unittest.TestCase):
    """unwatch-gate.py, replaying the unwatch of a work repo's #6226 at hand-back on
    Nov 25, 2026, while two review requests were pending, with gh faked."""
    HOOK = "unwatch-gate.py"
    URL = "https://github.com/acme/app/pull/6226"
    # The call as the agent made it (transcript acdfd830), the repo replaced.
    CALL = {"url": URL}

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        bin_dir = os.path.join(self.dir, "bin")
        os.makedirs(bin_dir)
        pathlib.Path(bin_dir, "gh").write_text(FAKE_WATCH_GH)
        os.chmod(os.path.join(bin_dir, "gh"), 0o755)
        outside_t3 = {k: v for k, v in os.environ.items() if k != "T3CODE_CLI_PATH"}
        self.gh = os.path.join(self.dir, "scenario.json")
        self.env = dict(outside_t3, PATH=f"{bin_dir}:{os.environ['PATH']}", FAKE_GH=self.gh,
                        T3_STATE_DB="/nonexistent")
        self.scenario()

    def scenario(self, state="OPEN", draft=False, author="author", **extra):
        pathlib.Path(self.gh).write_text(json.dumps({"me": "author", **extra, "pr": {
            "number": 6226, "url": self.URL, "state": state, "isDraft": draft, "author": {"login": author}}}))

    def reason(self, tool_input=CALL, said=("a",), env=None):
        """The deny reason for the call after the transcript said, or None when it passes."""
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl") as transcript:
            transcript.write("".join(json.dumps(claude_said(entry) if isinstance(entry, str) else entry) + "\n"
                                     for entry in said))
            transcript.flush()
            payload = {"tool_name": "mcp__t3-code__unwatch_pull_request", "tool_input": tool_input,
                       "transcript_path": transcript.name, "session_id": "s"}
            out = subprocess.run([str(HOOKS / self.HOOK)], input=json.dumps(payload), env={**self.env, **(env or {})},
                                 capture_output=True, text=True, check=True).stdout
        if not out:
            return None
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        return decision["permissionDecisionReason"]

    def offer(self, text):
        return claude_wrote("🟡 **Stop watching #6226?**\n\n" + block({"state": "stop", "needs": [], "options": [
            {"key": "a", "class": "routine", "text": text}]}))

    def test_the_hand_back_unwatch_of_an_open_ready_pr_is_denied(self):
        reason = self.reason()
        self.assertIn("#6226 is open and ready for review", reason)
        # T3 can't show a watch's mode, so the denial asks for the re-watch whatever it is.
        self.assertIn('call `watch_pull_request` with `until: "checks"` before ending the turn', reason)
        self.assertNotIn("only when it watches until merged", reason)

    def test_a_pr_that_merged_closed_or_is_a_draft_passes(self):
        for state, draft in (("MERGED", False), ("CLOSED", False), ("OPEN", True)):
            with self.subTest(state=state, draft=draft):
                self.scenario(state=state, draft=draft)
                self.assertIsNone(self.reason())

    def test_another_authors_pr_passes(self):
        self.scenario(author="teammate")
        self.assertIsNone(self.reason())

    def test_a_typed_request_to_stop_watching_passes(self):
        for prompt in ("stop watching it", "unwatch #6226", "ok, unwatch https://github.com/acme/app/pull/6226",
                       "no need to watch it anymore", "don't babysit it", "please stop watching #6226 and #6215",
                       "unwatch https://github.com/Acme/App/pull/6226", "unwatch PR #6226",
                       "can you stop watching #6226?", "could you please unwatch PRs #6226 and #6215"):
            with self.subTest(prompt=prompt):
                self.assertIsNone(self.reason(said=(prompt,)))

    def test_a_refusal_or_another_request_is_denied(self):
        for prompt in ("don't unwatch it", "keep watching it", "merge it", "request a review",
                       # A question or complaint about the hand-back unwatch, which the go once read as a request.
                       "why did you unwatch #6226?", "is it safe to unwatch it", "should you stop watching it?",
                       "you unwatch PRs too early, never do that", "unwatch it once it merges", "unwatch it?",
                       "can you stop watching #6215?",
                       # A request for another PR.
                       "don’t unwatch it", "the unwatch on #6226 was a bug", "re-check the unwatch-gate fix",
                       "stop watching #6215", "unwatch 6215", "unwatch " + "x" * 200,
                       # The same number in another repo.
                       "unwatch https://github.com/other/repo/pull/6226",
                       "stop watching https://github.com/acme/web/pull/6226",
                       "unwatch https://github.com/pull/6226", "unwatch HTTPS://github.com/other/repo/pull/6226"):
            with self.subTest(prompt=prompt):
                self.assertIsNotNone(self.reason(said=(prompt,)))

    def test_a_key_passes_only_when_its_option_asks_to_stop_watching(self):
        self.assertIsNone(self.reason(said=("fix it", self.offer("stop watching #6226"), "a")))
        self.assertIsNotNone(self.reason(said=("fix it", self.offer("hand the thread back"), "a")))
        self.assertIsNotNone(self.reason(said=("fix it", self.offer("stop watching #6226"), "b")))

    def test_number_and_repository_name_the_pr(self):
        self.assertIsNotNone(self.reason({"number": 6226, "repository": "acme/app"}))
        self.assertIn("#6226 is open", self.reason({"url": "HTTPS://github.com/acme/app/pull/6226"}))
        calls = pathlib.Path(self.gh + ".calls").read_text()
        self.assertIn("pr view 6226 -R github.com/acme/app", calls)

    def test_it_fails_closed(self):
        self.assertIn("names no PR", self.reason({}))
        self.assertIn("names no PR", self.reason({"number": 6226}))
        self.scenario(broken=True)
        self.assertIn("couldn't read the PR's state (gh: network down)", self.reason())

    def test_a_delegated_child_passes(self):
        db = state_db(self.dir, "thread:delegated-task:abc", "Mode: planning autonomous, trust draft\n\nFix it.")
        self.assertIsNone(self.reason(env={"T3_STATE_DB": db}))
        self.assertFalse(os.path.exists(self.gh + ".calls"))

    def test_dry_run_prints_the_verdict(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl") as transcript:
            transcript.write(json.dumps(claude_said("a")) + "\n")
            transcript.flush()
            run = subprocess.run([sys.executable, str(HOOKS / self.HOOK), "--dry-run", self.URL, "--transcript",
                                  transcript.name], env=self.env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 1)
        self.assertTrue(run.stdout.endswith("would deny\n"), run.stdout)


class WatchReminder(unittest.TestCase):
    """watch-reminder.py, replaying the review request on a work repo's #6215 on Nov 25,
    2026, after which the agent ended its turn with no watch."""
    HOOK = "watch-reminder.py"
    ENV = {"T3_STATE_DB": "/nonexistent"}

    def remind(self, tool, tool_input, env=None):
        return run_hook(self.HOOK, {"tool_name": tool, "tool_input": tool_input, "session_id": "s"},
                        env={**self.ENV, **(env or {})})

    def test_marking_ready_or_requesting_reviews_reminds(self):
        for tool, tool_input in (
                ("mcp__t3-code__pull_request_update", {"number": 6215, "requestReviewers": ["first-reviewer", "second-reviewer"]}),
                ("mcp__t3-code__pull_request_update", {"ready": True}),
                ("mcp__t3-code__pull_request_create", {"title": "t", "body": "b"}),
                ("Bash", {"command": "gh pr ready 6215"}),
                ("Bash", {"command": "cd ~/app && gh pr edit 6215 --add-reviewer first-reviewer,second-reviewer"}),
                ("Bash", {"command": "gh pr create --title t --body b"}),
                ("Bash", {"command": "gh pr create --fill --draft=false"}),
                ("Bash", {"command": "gh stack submit --open"}),
                # T3 ends a watch when its PR closes, so reopening one starts the wait again.
                ("mcp__t3-code__pull_request_update", {"number": 6092, "state": "open"}),
                ("Bash", {"command": "gh pr reopen 6092"})):
            with self.subTest(tool=tool, tool_input=tool_input):
                reminder = self.remind(tool, tool_input)
                self.assertIn('`until: "checks"`', reminder)
                # The call alone can't tell a draft, another author's PR, or a stack's several PRs.
                self.assertIn("each one that is open, ready (not a draft), and the user's", reminder)

    def test_other_calls_add_nothing(self):
        for tool, tool_input in (
                ("mcp__t3-code__pull_request_update", {"ready": False}),
                ("mcp__t3-code__pull_request_update", {"title": "t"}),
                ("mcp__t3-code__pull_request_update", {"state": "closed"}),
                ("Bash", {"command": "gh pr close 6092"}),
                ("mcp__t3-code__pull_request_create", {"title": "t", "body": "b", "draft": True}),
                ("Bash", {"command": "gh pr ready 6215 --undo"}),
                ("Bash", {"command": "gh pr create --draft --title t"}),
                ("Bash", {"command": "gh pr create -d --title t"}),
                ("Bash", {"command": "gh pr edit 6215 --title t; echo --add-reviewer"}),
                ("Bash", {"command": "gh stack submit"}),
                ("Bash", {"command": 1}),
                ("Read", {"file_path": "/tmp/x"})):
            with self.subTest(tool=tool, tool_input=tool_input):
                self.assertEqual(self.remind(tool, tool_input), "")

    def test_a_delegated_child_gets_no_reminder(self):
        with tempfile.TemporaryDirectory() as folder:
            db = state_db(folder, "thread:delegated-task:abc", "Fix it.")
            self.assertEqual(self.remind("Bash", {"command": "gh pr ready 6215"}, env={"T3_STATE_DB": db}), "")

    def test_input_it_doesnt_expect_adds_nothing(self):
        for payload in ("not json", "[]", json.dumps({"tool_name": "Bash", "tool_input": []})):
            with self.subTest(payload=payload):
                out = subprocess.run([str(HOOKS / self.HOOK)], input=payload, capture_output=True, text=True,
                                     env={**os.environ, **self.ENV})
                self.assertEqual((out.returncode, out.stdout), (0, ""))


def card(state="stop", kinds=("review",), classes=("stop:post", "routine")):
    """A reply ending on a turn block in this state, with a need of each kind and an option of each class."""
    block = {"state": state} if state == "done" else {
        "state": state, "needs": [{"id": n + 1, "kind": kind, "name": "Review the drafted comments"}
                                  for n, kind in enumerate(kinds)],
        "options": [{"key": "abc"[n], "class": cls, "text": "Post the review"} for n, cls in enumerate(classes)]}
    if state == "running":
        block = {"state": "running", "elapsed": "2m"}
    return f"Here's the review.\n\n<!-- turn {json.dumps(block)} -->"


# The option classes the implementation scope fires on: cleanest-ask.py IMPLEMENTATION_CLASSES.
IMPLEMENTATION_CLASSES = ("decision", "stop:merge", "stop:push")


class CleanestAskCase(unittest.TestCase):
    """cleanest-ask.py, on review-teammate-pr's card on a work repo's #6215 on Nov 25, 2026,
    after which the user typed "is this the cleanest, best and most idiomatic long-term
    solution?", as they did in 50 of 85 review threads they typed in that week."""
    HOOK = "cleanest-ask.py"
    ARGS = ()
    TITLE = "◎ #6215 · first-reviewer"
    THREAD = "mcp:launch:review6215"
    SESSION = "5f0c6a40-9d1e-4b1a-8c3e-2a7d9e0b6215"
    ASK = "Review https://github.com/acme/app/pull/6215"
    # What Claude Code writes when /cleanest arrives: the command, then its body as meta.
    COMMAND = ['<command-message>cleanest</command-message>\n<command-name>/cleanest</command-name>',
               "is this the cleanest, best and most idiomatic long-term solution?"]

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = pathlib.Path(folder.name)
        self.sent = self.dir / "sent.txt"
        cli = self.dir / "t3"
        cli.write_text(f'#!/bin/sh\nprintf "%s|" "$@" >> {self.sent}; echo >> {self.sent}\n'
                       'if [ -n "$T3_FAIL" ]; then echo "thread busy" >&2; exit 1; fi\n'
                       f'echo "{{\\"runId\\": \\"run-$(wc -l < {self.sent} | tr -d \' \')\\", \\"delivery\\": \\"queued\\"}}"\n')
        cli.chmod(0o755)
        (self.dir / "claude/commands").mkdir(parents=True)
        shutil.copy(HOOKS.parent / "commands/cleanest.md", self.dir / "claude/commands/cleanest.md")
        self.env = {"T3_STATE_DB": self.db(), "T3CODE_CLI_PATH": str(cli), "T3CODE_THREAD_ID": self.THREAD,
                    "CLAUDE_CONFIG_DIR": str(self.dir / "claude"), "ADDYSTACK_STATE": str(self.dir / "state")}

    def db(self, thread=None, title=None, first=None, first_by="user", agent_sent=(), lineage=None):
        """T3's state database: thread owns SESSION, with this title, lineage, and first
        message, and each text in agent_sent sent into it by an agent."""
        thread, title, first = thread or self.THREAD, title or self.TITLE, first or self.ASK
        key = repr((thread, title, first, first_by, agent_sent, lineage))
        path = self.dir / f"state-{hashlib.sha1(key.encode()).hexdigest()[:8]}.sqlite"
        if path.exists():  # this test built it already
            return str(path)
        with contextlib.closing(sqlite3.connect(path)) as db, db:
            db.execute("create table orchestration_v2_projection_provider_threads (thread_id text, provider_thread_id text, payload_json text)")
            db.execute("create table orchestration_v2_projection_threads (thread_id text, title text, payload_json text)")
            db.execute("create table orchestration_v2_projection_messages (thread_id text, role text, payload_json text, created_at text, run_id text)")
            db.execute("create table orchestration_v2_projection_runs (run_id text, provider_thread_id text, status text)")
            db.execute("insert into orchestration_v2_projection_provider_threads values (?, 'p1', ?)",
                       (thread, json.dumps({"nativeThreadRef": {"nativeId": self.SESSION}})))
            db.execute("insert into orchestration_v2_projection_threads values (?, ?, ?)",
                       (thread, title, json.dumps({"lineage": lineage or {"parentThreadId": None}})))
            db.executemany("insert into orchestration_v2_projection_messages values (?, 'user', ?, ?, null)",
                           [(thread, json.dumps({"text": text, "createdBy": by}), f"2026-11-25T10:0{n}:00Z")
                            for n, (text, by) in enumerate([(first, first_by), *((t, "agent") for t in agent_sent)])])
        return str(path)

    def transcript(self, *turns):
        """A Claude Code transcript: each turn a prompt (a string, or a list of parts) then its reply."""
        path = self.dir / f"{self.SESSION}.jsonl"
        lines = []
        for prompt, reply in turns:
            if isinstance(prompt, list):
                lines += [claude_said(prompt[0]), {"type": "user", "isMeta": True, "message": {"content": prompt[1]}}]
            else:
                lines.append(claude_said(prompt))
            lines.append(claude_wrote(reply))
        path.write_text("".join(json.dumps(line) + "\n" for line in lines))
        return str(path)

    def stop(self, *turns, env=None, reply=None, args=None):
        """Runs the hook, once for each of args' argument lists (one run of ARGS by default),
        at the end of the last turn; returns the CLI calls they made."""
        payload = {"hook_event_name": "Stop", "session_id": self.SESSION, "transcript_path": self.transcript(*turns),
                   "stop_hook_active": False, "last_assistant_message": reply or turns[-1][1]}
        for args in ((self.ARGS,) if args is None else args):
            out = subprocess.run([str(HOOKS / self.HOOK), *args], input=json.dumps(payload), capture_output=True,
                                 text=True, env={**os.environ, **self.env, **(env or {})})
            self.assertEqual((out.returncode, out.stdout, out.stderr), (0, "", ""))
        return self.sent.read_text().splitlines() if self.sent.exists() else []

    def fresh(self):
        """Forgets every send and log row, for the next subtest."""
        self.sent.unlink(missing_ok=True)
        (self.dir / "state/cleanest-ask.jsonl").unlink(missing_ok=True)

    def set_run(self, run, status):
        """Gives T3's run for the hook's nth send this status, as T3 does once it starts or cancels it."""
        with contextlib.closing(sqlite3.connect(self.env["T3_STATE_DB"])) as db, db:
            db.execute("insert into orchestration_v2_projection_runs values (?, 'p1', ?)", (run, status))

    def log(self, raw=False):
        """The decision log, each send as its last row, as the hook reads it, or every row when raw."""
        path = self.dir / "state/cleanest-ask.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        if raw:
            return rows
        latest = {}
        for at, row in enumerate(rows):
            latest[row.get("send") or at] = row
        return list(latest.values())


class CleanestAsk(CleanestAskCase):
    """The review scope, the `cleanest-ask` id."""

    def test_sends_once_on_a_card_that_stops_on_a_review_or_decide_need(self):
        for kinds in (("review",), ("decide",), ("do", "decide")):
            with self.subTest(kinds=kinds):
                self.sent.unlink(missing_ok=True)
                (self.dir / "state/cleanest-ask.jsonl").unlink(missing_ok=True)
                self.assertEqual(self.stop((self.ASK, card(kinds=kinds))), [f"thread|send|--json|{self.THREAD}|/cleanest|"])
                self.assertEqual([(row["thread"], row["sent"], row["scope"]) for row in self.log()],
                                 [(self.THREAD, True, "review")])

    def test_sends_once_per_run(self):
        first = (self.ASK, card())
        self.assertEqual(len(self.stop(first)), 1)
        # Another stop before the queued /cleanest arrives, such as a prompt the user queued first.
        self.assertEqual(len(self.stop(first, ("tighten comment 2", card()))), 1)
        self.assertEqual(self.log()[-1]["reason"], "this run already asked")
        # Its own turn, then the user's pick and the next card in the same run.
        self.set_run("run-1", "completed")
        answered = [first, (self.COMMAND, card()), ("a", card())]
        self.assertEqual(len(self.stop(*answered[:2])), 1)
        self.assertEqual(self.log()[-1]["reason"], "the latest prompt is /cleanest")
        self.assertEqual(len(self.stop(*answered)), 1)
        self.assertEqual(self.log()[-1]["reason"], "this run already asked")
        # A reply that ends done closes the run: a later re-review asks again.
        self.assertEqual(len(self.stop(*answered, ("b", card("done")), ("re-review the new commits", card()))), 2)

    def test_sends_on_the_card_after_a_delegated_reviewers_result(self):
        # On one machine, 18 of the 23 cards the user asked on in the week to Nov 25, 2026 came
        # right after review-loop's reviewer reported back, as in ◎ #6217.
        result = "Delegated task node:delegated-task:rl-6215-r1 (◎ #6215 r1 · gpt-6.1) [completed]:\nTwo findings."
        env = {"T3_STATE_DB": self.db(first="Review #6215 with the review-teammate-pr skill.", first_by="agent",
                                      agent_sent=(result,))}
        self.assertEqual(self.stop(("Review #6215 with the review-teammate-pr skill.", card("running")), (result, card()),
                                   env=env), [f"thread|send|--json|{self.THREAD}|/cleanest|"])
        # A background task's notice after the result, as in #6047 on Nov 19, 2026, continues the run too.
        self.sent.unlink()
        (self.dir / "state/cleanest-ask.jsonl").unlink()
        task = "<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n</task-notification>"
        self.assertEqual(len(self.stop(("Review #6215 with the review-teammate-pr skill.", card("running")),
                                       (result, card("running")), (task, card()), env=env)), 1)

    def test_a_cleanest_the_user_typed_earlier_doesnt_hide_a_queued_send(self):
        earlier = [(self.ASK, card()), (self.COMMAND, card()), ("b", card("done")), ("re-review it", card())]
        self.assertEqual(len(self.stop(*earlier)), 1)
        self.assertEqual(len(self.stop(*earlier, ("tighten comment 2", card()))), 1)
        self.assertEqual(self.log()[-1]["reason"], "this run already asked")

    def test_a_cancelled_send_holds_only_until_the_run_ends(self):
        first = (self.ASK, card())
        self.assertEqual(len(self.stop(first)), 1)
        # The user cancelled the queued /cleanest: no second one this run, but the next run asks.
        self.assertEqual(len(self.stop(first, ("a", card()))), 1)
        self.set_run("run-1", "cancelled")
        self.assertEqual(len(self.stop(first, ("a", card()), ("b", card("done")), ("re-review it", card()))), 2)

    def test_a_send_still_queued_holds_the_next_run(self):
        # Prompts the user queued first can end a run and start another before /cleanest arrives.
        first = (self.ASK, card())
        self.assertEqual(len(self.stop(first)), 1)
        self.assertEqual(len(self.stop(first, ("post it", card("done")), ("now review #6216", card()))), 1)
        self.assertEqual(self.log()[-1]["reason"], "a /cleanest this hook sent is still queued")
        self.assertEqual(self.log()[0]["run"], "run-1")

    def test_review_words_that_ask_nothing_dont_count_as_an_ask(self):
        for prompt in ("Review PR #6215; it changes the long-term archive.",
                       "Review PR #6215: will the long-term archive preserve deletions?"):
            with self.subTest(prompt=prompt):
                self.sent.unlink(missing_ok=True)
                (self.dir / "state/cleanest-ask.jsonl").unlink(missing_ok=True)
                self.assertEqual(len(self.stop((prompt, card()))), 1)
        for asked in ("Is it the most idiomatic and best-practice long-term implementation?", "make it the cleanest",
                      "whats the best long-term solution?", "is this really necessary for the long term?"):
            with self.subTest(asked=asked):
                self.sent.unlink(missing_ok=True)
                (self.dir / "state/cleanest-ask.jsonl").unlink(missing_ok=True)
                self.assertEqual(self.stop((self.ASK, card()), (asked, card())), [])

    def test_skips_a_run_where_the_user_asked_themselves(self):
        self.assertEqual(self.stop((self.ASK, card()), ("is this the cleanest, best and most idiomatic long-term solution?", card()),
                                   ("a", card())), [])
        self.assertEqual(self.log()[-1]["reason"], "this run already asked")

    def test_skips_replies_that_dont_stop_on_a_review_or_decide_need(self):
        for reply in (card("done"), card("running"), card(kinds=(), classes=("routine",)), card(kinds=("do",)),
                      "No turn block here.", ""):
            with self.subTest(reply=reply):
                self.assertEqual(self.stop((self.ASK, reply)), [])
        self.assertEqual(self.log(), [])

    def test_skips_prompts_the_user_didnt_type(self):
        wake = "Update on pull request #6215: a new review from first-reviewer."
        tick = '<coordinator-tick project="app">\n- r12 due\n</coordinator-tick>'
        # T3 puts its sender note before an agent's message in the transcript, not in its database.
        noted = "Please also check the tests, then post."
        note = f'[T3 Code: the agent in T3 thread "coord" sent this message, not the user.]\n\n{noted}'
        report = "From the Platform lane (thread x): the fix is pushed."
        plain = "Please also check the tests."  # only T3's database says an agent sent it
        env = {"T3_STATE_DB": self.db(agent_sent=(wake, tick, report, plain, noted))}
        for prompt in (wake, tick, report, plain, note, self.COMMAND):
            with self.subTest(prompt=prompt):
                self.assertEqual(self.stop((self.ASK, card()), (prompt, card()), env=env), [])
                self.assertEqual(self.log()[-1]["reason"], "the latest prompt is /cleanest" if prompt is self.COMMAND
                                 else "the latest prompt isn't the user's: a wake, a tick, or another agent's message")

    def test_skips_children_workers_and_other_threads(self):
        worker = "Act as the review sub-agent.\n\nWorker of: t3-thread://v2/env/5ba1b6b8\nReview it."
        for name, env in (("delegated child", {"T3_STATE_DB": self.db("thread:delegated-task:abc"),
                                               "T3CODE_THREAD_ID": "thread:delegated-task:abc"}),
                          ("coordinator's worker", {"T3_STATE_DB": self.db(first=worker, first_by="agent")}),
                          ("review-loop reviewer", {"T3_STATE_DB": self.db("thread:delegated-task:r1", "◎ #6215 r1 · gpt-6.1"),
                                                    "T3CODE_THREAD_ID": "thread:delegated-task:r1"}),
                          ("not a review thread", {"T3_STATE_DB": self.db(title="Fix the login redirect")}),
                          # An unattended workflow review on Nov 23, 2026, whose prompts T3 records as the system's.
                          ("workflow step", {"T3_STATE_DB": self.db("workflow:fefcbdb4", first_by="system",
                                                                    lineage={"workflowStep": True}),
                                             "T3CODE_THREAD_ID": "workflow:fefcbdb4"}),
                          ("another thread's id", {"T3CODE_THREAD_ID": "mcp:launch:other"}),
                          ("no T3", {"T3_STATE_DB": str(self.dir / "missing.sqlite")})):
            with self.subTest(name):
                self.assertEqual(self.stop((self.ASK, card()), env=env), [])
        self.assertEqual(self.log(), [])

    def test_stays_silent_when_it_cant_send(self):
        self.assertEqual(self.stop((self.ASK, card()), env={"T3_FAIL": "1"}), [f"thread|send|--json|{self.THREAD}|/cleanest|"])
        self.assertEqual(self.log()[-1]["reason"], "t3 thread send failed: thread busy")
        (self.dir / "claude/commands/cleanest.md").write_text("my own command\n")
        self.assertEqual(len(self.stop((self.ASK, card()))), 1)
        self.assertEqual(self.log()[-1]["reason"], f"commands/cleanest.md in {self.dir / 'claude'} isn't the kit's /cleanest")
        (self.dir / "claude/commands/cleanest.md").unlink()
        self.assertEqual(len(self.stop((self.ASK, card()))), 1)
        self.assertEqual(self.log()[-1]["reason"], "/cleanest isn't installed; run addystack install")
        for payload in ("not json", "[]", json.dumps({"session_id": 1, "last_assistant_message": card()})):
            with self.subTest(payload=payload):
                out = subprocess.run([str(HOOKS / self.HOOK)], input=payload, capture_output=True, text=True,
                                     env={**os.environ, **self.env})
                self.assertEqual((out.returncode, out.stdout), (0, ""))

    def test_a_send_whose_answer_is_lost_still_counts(self):
        # T3 queues the message, then the CLI times out before it answers.
        (self.dir / "t3").write_text(f'#!/bin/sh\necho accepted >> {self.sent}\nexec sleep 30\n')
        first = (self.ASK, card())
        self.assertEqual(len(self.stop(first)), 1)
        self.assertEqual(self.log()[-1]["reason"], "t3 thread send timed out; counted as sent")
        self.assertEqual(len(self.stop(first, ("tighten comment 2", card()))), 1)
        self.assertEqual(self.log()[-1]["reason"], "this run already asked")
        # With no record of a send, none goes out.
        (self.dir / "state/cleanest-ask.jsonl").unlink()
        (self.dir / "state/cleanest-ask.jsonl").mkdir()
        self.assertEqual(len(self.stop(first)), 1)

    def test_dry_run_prints_the_decision_and_sends_nothing(self):
        run = lambda *turns: subprocess.run([str(HOOKS / self.HOOK), "--dry-run", "--transcript", self.transcript(*turns),
                                             "--session", self.SESSION], capture_output=True, text=True,
                                            env={**os.environ, **self.env}).stdout
        self.assertEqual(run((self.ASK, card())), f"would send /cleanest to {self.THREAD}\n")
        self.assertEqual(run((self.ASK, card("done"))), "skip: the reply is done\n")
        self.assertFalse(self.sent.exists())
        self.assertEqual(self.log(), [])

    def test_only_an_enable_by_id_installs_it(self):
        if str(HOOKS.parent / "lib") not in sys.path:
            sys.path.append(str(HOOKS.parent / "lib"))
        import config, hookset
        for hook in ("cleanest-ask", "cleanest-ask-impl"):
            for hooks, on in (({"preset": "recommended"}, False), ({"preset": "all"}, False),
                              ({"preset": "all", "enable": [hook]}, True),
                              ({"preset": "recommended", "enable": [hook]}, True)):
                with self.subTest(hook=hook, hooks=hooks):
                    user = self.dir / "addystack.jsonc"
                    user.write_text(json.dumps({"hooks": hooks}))
                    selected = [entry.id for entry in hookset.select(config.resolve(user), "claude", "linux")]
                    self.assertEqual(hook in selected, on)
                    self.assertEqual(len(set(selected) & {"cleanest-ask", "cleanest-ask-impl"}), int(on))
                    self.assertNotIn(hook, [entry.id for entry in hookset.select(config.resolve(user), "codex", "linux")])


class CleanestAskImplementation(CleanestAskCase):
    """The implementation scope, the `cleanest-ask-impl` id: a coordinator thread's card on
    Nov 24, 2026, after which the user typed "is this the cleanest, best and most idiomatic
    long-term solution?", as they did on 47 of 1,168 stop cards in implementation and
    coordinator threads that week."""
    ARGS = ("--scope", "implementation")
    THREAD = "mcp:launch:coord-effect"
    TITLE = "◆ effect-native"
    ASK = "Build the token store as its own client, then push a draft"
    RESULT = "Delegated task node:delegated-task:w1 (token store) [completed]:\nPushed #6110."
    SENT = "thread|send|--json|mcp:launch:coord-effect|/cleanest|"

    def card(self, state="stop", kinds=("decide",), classes=("decision", "decision")):
        return card(state, kinds, classes)

    def test_sends_where_option_a_decides_merges_or_pushes(self):
        for cls in IMPLEMENTATION_CLASSES:
            with self.subTest(cls=cls):
                self.fresh()
                self.assertEqual(self.stop((self.ASK, self.card(classes=(cls, "decision")))), [self.SENT])
                self.assertEqual([(row["thread"], row["sent"], row["scope"]) for row in self.log()],
                                 [(self.THREAD, True, "implementation")])

    def test_skips_a_card_whose_option_a_is_routine_a_post_or_another_stop(self):
        for cls in ("routine", "stop:post", "stop:prod", "stop:credential"):
            with self.subTest(cls=cls):
                self.assertEqual(self.stop((self.ASK, self.card(classes=(cls, "decision")))), [])
        # A stop with a need and no options, as on 4 Mac cards that week.
        for reply in (self.card(classes=()), self.card(kinds=("do",)), self.card("done"), self.card("running"),
                      "No turn block here."):
            with self.subTest(reply=reply):
                self.assertEqual(self.stop((self.ASK, reply)), [])
        self.assertEqual(self.log(), [])

    def test_a_prompt_the_user_types_starts_a_new_run(self):
        first = (self.ASK, self.card())
        self.assertEqual(len(self.stop(first)), 1)
        # A worker's result in the same run doesn't ask again, delivered or not.
        self.assertEqual(len(self.stop(first, (self.RESULT, self.card()))), 1)
        self.assertEqual(self.log()[-1]["reason"], "this run already asked")
        self.set_run("run-1", "completed")
        answered = [first, (self.COMMAND, self.card())]
        self.assertEqual(len(self.stop(*answered)), 1)
        self.assertEqual(self.log()[-1]["reason"], "the latest prompt is /cleanest")
        # The user's pick starts the next run, though no reply ended `done`.
        self.assertEqual(len(self.stop(*answered, ("a", self.card()))), 2)
        # Their own ask holds the run they typed it in, and their next prompt starts another.
        asked = [*answered, ("a", self.card()), ("is this really necessary for the long term?", self.card())]
        self.set_run("run-2", "completed")
        self.assertEqual(len(self.stop(*asked)), 2)
        self.assertEqual(self.log()[-1]["reason"], "this run already asked")
        self.assertEqual(len(self.stop(*asked, ("ok, build it", self.card()))), 3)

    def test_sends_on_the_card_after_a_workers_result_in_a_run_the_user_started(self):
        # 18 of the 47 asked-on cards that week came right after a worker or child reported back.
        env = {"T3_STATE_DB": self.db(agent_sent=(self.RESULT,))}
        self.assertEqual(self.stop((self.ASK, self.card("running")), (self.RESULT, self.card()), env=env), [self.SENT])

    def test_skips_a_run_no_prompt_the_user_typed_started(self):
        tick = '<coordinator-tick project="effect-v4">\n- r12 due\n</coordinator-tick>'
        scheduled = "Daily develop sync for the effect-v4 project."
        env = {"T3_STATE_DB": self.db(first=scheduled, first_by="agent", agent_sent=(tick, self.RESULT))}
        for turns in ([(scheduled, self.card("running")), (self.RESULT, self.card())],
                      # The user's run ended `done`; a tick then started a worker.
                      [(self.ASK, self.card("done")), (tick, self.card("running")), (self.RESULT, self.card())]):
            with self.subTest(turns=turns):
                self.assertEqual(self.stop(*turns, env=env), [])
                self.assertEqual(self.log()[-1]["reason"], "no prompt the user typed started this run")

    def test_skips_wakes_ticks_and_other_agents_messages(self):
        wake = "Update on pull request #6110: a new review from CasperEngl."
        tick = '<coordinator-tick project="effect-v4">\n- r12 due\n</coordinator-tick>'
        report = "From the Platform lane (thread x): the fix is pushed."
        env = {"T3_STATE_DB": self.db(agent_sent=(wake, tick, report))}
        for prompt in (wake, tick, report):
            with self.subTest(prompt=prompt):
                self.assertEqual(self.stop((self.ASK, self.card()), (prompt, self.card()), env=env), [])
                self.assertEqual(self.log()[-1]["reason"],
                                 "the latest prompt isn't the user's: a wake, a tick, or another agent's message")

    def test_skips_review_threads_children_workers_and_workflow_steps(self):
        worker = "Act as the implementation sub-agent.\n\nWorker of: t3-thread://v2/env/5ba1b6b8\nBuild it."
        for name, env in (("review thread", {"T3_STATE_DB": self.db(title="◎ #6215 · first-reviewer")}),
                          ("delegated child", {"T3_STATE_DB": self.db("thread:delegated-task:abc"),
                                               "T3CODE_THREAD_ID": "thread:delegated-task:abc"}),
                          ("coordinator's worker", {"T3_STATE_DB": self.db(first=worker, first_by="agent")}),
                          ("worker naming its coordinator", {"T3_STATE_DB": self.db(first=worker.replace(
                              "Worker of: t3-thread://", "Worker of: the ◆ app coordinator (t3-thread://"), first_by="agent")}),
                          ("workflow step", {"T3_STATE_DB": self.db("workflow:fefcbdb4", first_by="system",
                                                                    lineage={"workflowStep": True}),
                                             "T3CODE_THREAD_ID": "workflow:fefcbdb4"})):
            with self.subTest(name):
                self.assertEqual(self.stop((self.ASK, self.card()), env=env), [])
        self.assertEqual(self.log(), [])

    def test_both_ids_on_send_once_and_the_review_scope_keeps_its_rules(self):
        both = ((), self.ARGS)
        for title, thread_scope in (("◎ #6215 · first-reviewer", "review"), (self.TITLE, "implementation")):
            with self.subTest(title=title):
                self.fresh()
                env = {"T3_STATE_DB": self.db(title=title, agent_sent=(self.RESULT,))}
                self.assertEqual(self.stop((self.ASK, self.card()), env=env, args=both), [self.SENT])
                self.assertEqual([row["scope"] for row in self.log() if row["sent"]], [thread_scope])
                # A worker's result, then a second Stop in the same run: neither id sends again.
                self.assertEqual(len(self.stop((self.ASK, self.card()), (self.RESULT, self.card()), env=env,
                                               args=both)), 1)
                self.assertEqual(self.log()[-1]["reason"], "this run already asked")
        # In a review thread a typed prompt doesn't start a new run, and a post card still asks.
        self.fresh()
        env = {"T3_STATE_DB": self.db(title="◎ #6215 · first-reviewer")}
        self.assertEqual(len(self.stop((self.ASK, self.card(classes=("stop:post",))), env=env, args=both)), 1)
        self.assertEqual(len(self.stop((self.ASK, self.card()), (self.COMMAND, self.card()), ("a", self.card()),
                                       env=env, args=both)), 1)
        self.assertEqual(self.log()[-1]["reason"], "this run already asked")

    def test_dry_run_takes_the_scope(self):
        run = lambda *turns: subprocess.run([str(HOOKS / self.HOOK), *self.ARGS, "--dry-run", "--transcript",
                                             self.transcript(*turns), "--session", self.SESSION],
                                            capture_output=True, text=True, env={**os.environ, **self.env}).stdout
        self.assertEqual(run((self.ASK, self.card())), f"would send /cleanest to {self.THREAD}\n")
        self.assertEqual(run((self.ASK, self.card(classes=("routine",)))), "skip: option a is routine\n")
        self.assertFalse(self.sent.exists())


class CompileClean(unittest.TestCase):
    def test_every_hook_compiles_without_warnings(self):
        # A SyntaxWarning prints on every tool call today, and the escape it warns about
        # becomes an error in a later Python, which turns the hook off.
        for hook in sorted(HOOKS.glob("*.py")):
            with self.subTest(hook=hook.name):
                with warnings.catch_warnings():
                    warnings.simplefilter("error")
                    compile(hook.read_text(), str(hook), "exec")


class SkillsCheckoutCheck(unittest.TestCase):
    HOOK = "skills-checkout-check.py"

    def git(self, folder, *args):
        return subprocess.run(["git", "-C", folder, "-c", "user.email=e@x", "-c", "user.name=e", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def checkout(self, folder, branch, behind=0):
        git = functools.partial(self.git, folder)
        git("init", "-q", "-b", "main")
        pathlib.Path(folder, "reply-shape").mkdir()
        for n in range(behind + 1):
            pathlib.Path(folder, "reply-shape", "SKILL.md").write_text(str(n))
            git("add", "-A")
            git("commit", "-qm", f"commit {n}")
        git("update-ref", "refs/remotes/origin/main", "HEAD")
        git("reset", "-q", "--hard", f"HEAD~{behind}")
        if branch != "main":
            git("checkout", "-qb", branch)
        link = pathlib.Path(folder, "link")
        link.symlink_to(pathlib.Path(folder, "reply-shape"))
        return {"SKILLS_LINK": str(link), **fake_home(folder)}

    def test_quiet_on_main(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(run_hook(self.HOOK, {}, self.checkout(folder, "main")), "")

    def test_warns_on_another_branch(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIn("is on feature", run_hook(self.HOOK, {}, self.checkout(folder, "feature")))

    def test_fast_forwards_a_clean_main_that_is_behind(self):
        with tempfile.TemporaryDirectory() as folder:
            env = self.checkout(folder, "main", behind=2)
            pathlib.Path(folder, "notes.txt").write_text("untracked")  # an untracked file isn't a change
            self.assertEqual(run_hook(self.HOOK, {}, env), "")
            self.assertEqual(self.git(folder, "rev-parse", "HEAD"), self.git(folder, "rev-parse", "origin/main"))

    def run_after_fast_forward(self, folder, change):
        """Runs a kit copy's skills-checkout-check.py one commit behind origin/main, where
        change(kit) made that commit, and returns its output."""
        env = self.checkout(folder, "main")
        git = functools.partial(self.git, folder)
        kit = pathlib.Path(folder)
        (kit / "hooks").mkdir()
        # hook_parity.py and the modules it selects through.
        (kit / "lib").mkdir()
        for name in ("hooks/skills-checkout-check.py", "hooks/hook_parity.py", "hooks/manifest.json",
                     "hooks/resolved.py", "lib/config.py", "lib/hookset.py"):
            shutil.copy(HOOKS.parent / name, kit / name)
        git("add", "-A")
        git("commit", "-qm", "hooks")
        change(kit)
        git("commit", "-qam", "a change")
        git("update-ref", "refs/remotes/origin/main", "HEAD")
        git("reset", "-q", "--hard", "HEAD~1")
        return subprocess.run([sys.executable, str(kit / "hooks/skills-checkout-check.py")], input="{}",
                              capture_output=True, text=True, check=True, env={**os.environ, **env}).stdout

    def test_reads_hook_drift_after_the_fast_forward(self):
        """A fast-forward that adds a hook to the manifest is drift this session reports."""
        def add(kit):
            manifest = json.loads((kit / "hooks/manifest.json").read_text())
            manifest["claude"].append({"id": "new", "tags": ["workflow"], "event": "Stop", "matcher": None,
                                       "command": "{{kit}}/hooks/new.py", "timeout": 10})
            (kit / "hooks/manifest.json").write_text(json.dumps(manifest))
        with tempfile.TemporaryDirectory() as folder:
            self.assertIn("missing Stop ~/kit/hooks/new.py", self.run_after_fast_forward(folder, add))

    def test_a_hook_the_fast_forward_retires_is_drift_this_session(self):
        """The pulled hookset's RETIRED, not the one this process loaded before the pull,
        decides what drift reports (Codex review of r165)."""
        def retire(kit):
            manifest = json.loads((kit / "hooks/manifest.json").read_text())
            manifest["claude"] = [entry for entry in manifest["claude"] if entry["id"] != "verdict-stamp"]
            (kit / "hooks/manifest.json").write_text(json.dumps(manifest))
            hookset = kit / "lib/hookset.py"
            hookset.write_text(hookset.read_text().replace("RETIRED = (", 'RETIRED = ("verdict-stamp.py", ', 1))
        with tempfile.TemporaryDirectory() as folder:
            self.assertIn("extra PreToolUse ~/kit/hooks/verdict-stamp.py", self.run_after_fast_forward(folder, retire))

    def test_warns_when_main_is_behind_with_local_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            env = self.checkout(folder, "main", behind=2)
            pathlib.Path(folder, "reply-shape", "SKILL.md").write_text("edited")
            head = self.git(folder, "rev-parse", "HEAD")
            self.assertIn("is on main, 2 commits behind origin/main", run_hook(self.HOOK, {}, env))
            self.assertEqual(self.git(folder, "rev-parse", "HEAD"), head)
            self.assertIn("2 commits behind", run_hook(self.HOOK, {}, env))  # every session, not once a day

    def test_warns_once_a_day_per_branch(self):
        with tempfile.TemporaryDirectory() as folder:
            env = self.checkout(folder, "feature", behind=1)
            self.assertIn("is on feature, 1 commits behind", run_hook(self.HOOK, {}, env))
            self.assertEqual(run_hook(self.HOOK, {}, env), "")
            self.git(folder, "checkout", "-qb", "other")
            self.assertIn("is on other", run_hook(self.HOOK, {}, env))
            state = pathlib.Path(folder, ".git", "skills-checkout-warned")
            state.write_text("2020-01-01 other\n")  # warned on an earlier day
            self.assertIn("is on other", run_hook(self.HOOK, {}, env))

    def test_quiet_without_the_link(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(run_hook(self.HOOK, {}, {"SKILLS_LINK": "/nonexistent/skill",
                                                      **fake_home(folder)}), "")

    def test_warns_on_hook_drift_in_the_same_warning(self):
        with tempfile.TemporaryDirectory() as folder:
            env = self.checkout(folder, "feature")
            fake_home(folder, drop={"~/kit/hooks/ready-gate.py"})
            context = run_hook(self.HOOK, {}, env)
        self.assertIn("is on feature", context)
        self.assertIn("claude: missing PreToolUse ~/kit/hooks/ready-gate.py", context)
        self.assertEqual(context.count("Tell the user"), 1)

    def test_warns_on_hook_drift_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            env = self.checkout(folder, "main")
            fake_home(folder, drop={"~/kit/hooks/ready-gate.py"})
            self.assertIn("missing PreToolUse ~/kit/hooks/ready-gate.py", run_hook(self.HOOK, {}, env))


class StaleBuildCheck(unittest.TestCase):
    """skills-checkout-check.py rebuilding stale built files, in a copy of this kit committed
    to its own repo, built once into a scratch home: the hook runs from the copy, so
    resolved.json's kit is the hook's own."""
    HOOK = "skills-checkout-check.py"

    def setUp(self):
        self.folder = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.repo, home = self.folder / "repo", self.folder / "home"
        # At its place in the repo, so skill_layer finds the core skill a note names beside it.
        self.kit = self.repo / "skills/primitive/addystack"
        shutil.copytree(HOOKS.parent, self.kit, ignore=shutil.ignore_patterns("__pycache__"))
        self.config = home / ".config/addystack/addystack.jsonc"
        self.config.parent.mkdir(parents=True)
        self.config.write_text("{}")
        self.skill = self.repo / "skills/primitive/build/SKILL.md"
        self.skill.parent.mkdir(parents=True)
        self.skill.write_text("---\nname: build\nmetadata:\n  layer: primitive\n---\n\n## 1. Build\n")
        (self.config.parent / "notes").mkdir()
        (self.config.parent / "notes/build.md").write_text("After step 1, run the linter.\n")
        self.state = home / ".local/state/addystack"
        self.env = {**os.environ, "HOME": str(home), "ADDYSTACK_STATE": str(self.state),
                    "ADDYSTACK_CONFIG": str(self.config), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                    "SKILLS_LINK": str(self.kit / "hooks")}
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-qm", "kit")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.build()
        self.age()
        self.principles = self.state / "principles.md"
        self.built = self.principles.read_text()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=e@x", "-c", "user.name=e", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def build(self, *args):
        return subprocess.run([sys.executable, str(self.kit / "bin/addystack"), "build", *args], env=self.env,
                              capture_output=True, text=True)

    def age(self):
        """Dates the built files an hour back, as a build from an earlier session."""
        hour_ago = time.time() - 3600
        for path in [*self.state.rglob("*"), pathlib.Path(self.env["CLAUDE_CONFIG_DIR"], "CLAUDE.md"),
                     pathlib.Path(self.env["HOME"], ".codex/AGENTS.md")]:
            if path.is_file():
                os.utime(path, (hour_ago, hour_ago))

    def hook(self):
        out = subprocess.run([sys.executable, str(self.kit / "hooks" / self.HOOK)], input="{}", env=self.env,
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""

    def change_index(self):
        """Edits the kit's principles index, as a merged principle change does."""
        index = self.kit / "core/principles.md"
        index.write_text(index.read_text() + "- **[later](x.md)**: a principle merged later.\n")

    def assert_rebuilt(self, context):
        self.assertIn("addystack rebuilt", context)
        self.assertIn("principles.md", context)
        self.assertIn("read the ones your host loads", context)
        self.assertIn("principles.md (Claude Code)", context)
        self.assertIn("AGENTS.md (Codex)", context)
        self.assertEqual(self.build("--check").returncode, 0)

    def test_codex_keeps_the_trusted_reply_hooks_in_place(self):
        """Codex trusts a hook by its position, so the check comes after the reply hooks."""
        manifest = json.loads((HOOKS / "manifest.json").read_text())
        ids = [entry["id"] for entry in manifest["codex"] if entry["event"] == "SessionStart"]
        self.assertEqual(ids, ["reply-shape-context", "reply-rules", "skills-checkout-check"])

    def assert_quiet(self, context):
        """Nothing from the build check; the scratch home's missing settings still show as drift."""
        for phrase in ("addystack rebuilt", "built instructions", "addystack notes"):
            self.assertNotIn(phrase, context)

    def test_current_build_is_left_alone(self):
        before = self.principles.stat().st_mtime_ns
        self.assert_quiet(self.hook())
        self.assertEqual(self.principles.stat().st_mtime_ns, before)

    def test_rebuilds_after_a_pull(self):
        self.change_index()
        self.git("commit", "-qam", "a merged principle")
        self.assert_rebuilt(self.hook())
        self.assertIn("a principle merged later", self.principles.read_text())

    def test_rebuilds_after_its_own_fast_forward(self):
        self.change_index()
        self.git("commit", "-qam", "a merged principle")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.assert_rebuilt(self.hook())
        self.assertEqual(self.git("rev-parse", "HEAD"), self.git("rev-parse", "origin/main"))

    def test_rebuilds_after_a_config_edit(self):
        self.config.write_text('{"judgment": {"principles": {"exclude": ["slim-scope"]}}}')
        self.assert_rebuilt(self.hook())
        self.assertNotIn("slim-scope", self.principles.read_text())

    def test_quiet_rebuild_when_no_instruction_file_changed(self):
        (self.state / "resolved.json").write_text((self.state / "resolved.json").read_text() + " ")
        self.assert_quiet(self.hook())
        self.assertEqual(self.build("--check").returncode, 0)

    def test_warns_without_rebuilding_a_dirty_checkout(self):
        self.change_index()
        context = self.hook()
        self.assertIn("has local changes, so they weren't rebuilt", context)
        self.assertEqual(self.principles.read_text(), self.built)

    def test_leaves_another_branch_to_the_branch_warning(self):
        self.git("checkout", "-qb", "feature")
        self.change_index()
        self.git("commit", "-qam", "unmerged")
        context = self.hook()
        self.assertIn("is on feature", context)
        self.assertNotIn("built instructions", context)
        self.assertEqual(self.principles.read_text(), self.built)

    def test_rebuilds_a_kit_inside_another_repo(self):
        """An npx-installed kit under a home folder kept in git, on another branch with changes."""
        self.git("rm", "-rq", "--cached", "skills")
        self.git("commit", "-qm", "untrack the kit")
        self.git("checkout", "-qb", "master")
        (self.repo / "dotfile").write_text("x")
        self.git("add", "dotfile")
        self.change_index()
        self.assert_rebuilt(self.hook())

    def test_leaves_a_hand_written_instruction_file_to_install(self):
        claude_md = pathlib.Path(self.env["CLAUDE_CONFIG_DIR"], "CLAUDE.md")
        claude_md.write_text("# My own rules\n")
        self.change_index()
        self.git("commit", "-qam", "a merged principle")
        self.assertIn("holds text addystack didn't build", self.hook())
        self.assertEqual(claude_md.read_text(), "# My own rules\n")
        self.assertEqual(self.principles.read_text(), self.built)

    def test_restores_a_missing_resolved_json(self):
        """Without it, hooks fall back to the kit's defaults, such as gated planning."""
        (self.state / "resolved.json").unlink()
        self.hook()
        self.assertTrue((self.state / "resolved.json").is_file())
        self.assertEqual(self.build("--check").returncode, 0)

    def test_keeps_a_changed_skill_note_in_view(self):
        """The build refreshes the note's skill hash, so the session hears what doctor would have said."""
        self.skill.write_text(self.skill.read_text() + "## 2. Lint\n")
        self.change_index()
        self.git("commit", "-qam", "a merged skill change")
        context = self.hook()
        self.assert_rebuilt(context)
        self.assertIn("reread", context)
        self.assertIn("notes/build.md", context)

    def test_tells_a_session_that_started_just_before_another_sessions_rebuild(self):
        """Its instructions loaded before the rebuild, and its own check finds the build fresh."""
        self.change_index()
        self.git("commit", "-qam", "a merged principle")
        self.build()
        context = self.hook()
        self.assertIn("in the last 30 seconds", context)
        self.assertIn("principles.md", context)

    def test_names_files_another_build_wrote_while_others_are_still_stale(self):
        """A session whose hook lands mid-way through another session's build."""
        self.change_index()
        self.git("commit", "-qam", "a merged principle")
        claude_md = pathlib.Path(self.env["CLAUDE_CONFIG_DIR"], "CLAUDE.md")
        claude_md.write_text(claude_md.read_text())  # the other build's first write
        context = self.hook()
        self.assertIn("CLAUDE.md (Claude Code)", context)
        self.assertIn("principles.md (Claude Code)", context)

    def test_names_a_changed_note_and_a_removed_one(self):
        """A session that already read a note's old text, or one since deleted."""
        notes = self.config.parent / "notes"
        (notes / "build.md").write_text("After step 1, run the formatter.\n")
        self.assertIn("notes/build.md (skill note)", self.hook())
        self.age()
        (notes / "build.md").unlink()
        self.assertIn("notes/build.md (skill note, removed: stop following it)", self.hook())
        self.assertEqual(self.build("--check").returncode, 0)

    def test_keeps_a_copy_of_a_built_file_edited_by_hand(self):
        for path in (pathlib.Path(self.env["CLAUDE_CONFIG_DIR"], "CLAUDE.md"),
                     pathlib.Path(self.env["HOME"], ".codex/AGENTS.md")):
            path.write_text(path.read_text() + "\n- A rule added by hand.\n")
            context = self.hook()
            self.assertIn(f"{path.name}.bak", context)
            self.assertIn("A rule added by hand", path.with_name(f"{path.name}.bak").read_text())
            self.assertNotIn("A rule added by hand", path.read_text())
            self.age()
        # The second rebuild left CLAUDE.md alone, so its copy keeps the first hand edit.
        self.assertIn("A rule added by hand", pathlib.Path(self.env["CLAUDE_CONFIG_DIR"], "CLAUDE.md.bak").read_text())

    def test_a_copy_that_cannot_be_written_is_a_warning(self):
        agents = pathlib.Path(self.env["HOME"], ".codex/AGENTS.md")
        agents.write_text(agents.read_text() + "\n- A rule added by hand.\n")
        agents.parent.chmod(0o555)
        self.addCleanup(agents.parent.chmod, 0o755)
        self.assertIn("`addystack build` failed", self.hook())
        self.assertIn("A rule added by hand", agents.read_text())

    def test_reports_a_failed_build(self):
        self.change_index()
        self.git("commit", "-qam", "a merged principle")
        self.state.chmod(0o555)
        self.addCleanup(self.state.chmod, 0o755)
        self.assertIn("`addystack build` failed", self.hook())
        self.assertEqual(self.principles.read_text(), self.built)

    def test_a_stuck_build_costs_the_session_at_most_seconds(self):
        self.change_index()
        self.git("commit", "-qam", "a merged principle")
        cli = self.kit / "bin/addystack"
        cli.write_text("#!/usr/bin/env python3\nimport sys, time\nif sys.argv[1:] == ['build']: time.sleep(30)\n")
        self.git("commit", "-qam", "a build that hangs")
        start = time.monotonic()
        context = self.hook()
        self.assertLess(time.monotonic() - start, 6)
        self.assertIn("`addystack build` failed", context)

    def test_a_failed_build_keeps_the_notes_to_reread(self):
        self.skill.write_text(self.skill.read_text() + "## 2. Lint\n")
        self.change_index()
        self.git("commit", "-qam", "a merged skill change")
        self.state.chmod(0o555)
        self.addCleanup(self.state.chmod, 0o755)
        context = self.hook()
        self.assertIn("`addystack build` failed", context)
        self.assertIn("notes/build.md", context)

    def test_reports_a_config_that_does_not_resolve(self):
        self.config.write_text('{"judgment": {"principles": {"preset": "nope"}}}')
        self.assertIn("the config doesn't resolve", self.hook())


class HookParity(unittest.TestCase):
    CLI = HOOKS / "hook_parity.py"

    def setUp(self):
        # Resolved, as fake_home's HOME is, so ~/kit commands and file paths agree.
        self.home = str(pathlib.Path(tempfile.mkdtemp()).resolve())
        self.addCleanup(shutil.rmtree, self.home)
        self.env = fake_home(self.home)
        self.claude = pathlib.Path(self.home, ".claude/settings.json")
        self.codex = pathlib.Path(self.home, ".codex/hooks.json")

    def drift(self, runtime="claude", required=True):
        state = pathlib.Path(self.env["ADDYSTACK_STATE"], "resolved.json")
        with unittest.mock.patch.dict(os.environ, self.env), \
                unittest.mock.patch.object(hook_parity.resolved, "STATE", state):
            return hook_parity.drift(runtime, required=required)

    def edit(self, path, change):
        config = json.loads(path.read_text())
        change(config["hooks"])
        path.write_text(json.dumps(config))

    # A codex whose app-server lists one untrusted and one trusted hook.
    APP_SERVER = f"""#!{sys.executable}
import json, sys
for line in sys.stdin:
    id_ = json.loads(line).get("id")
    hooks = [{{"key": "h:stop:0:0", "trustStatus": "untrusted", "command": "~/x.py"}},
             {{"key": "h:stop:0:1", "trustStatus": "trusted", "command": "~/y.py"}},
             {{"key": "managed:stop:0:0", "trustStatus": "managed", "command": "/opt/audit"}}]
    if id_:
        print(json.dumps({{"id": id_, "result": {{"data": [{{"hooks": hooks, "errors": []}}]}}}}), flush=True)
"""

    def cli(self, *args, codex_on_path=False, codex="#!/bin/sh\n"):
        bin_dir = pathlib.Path(self.home, "bin")
        bin_dir.mkdir(exist_ok=True)
        if codex_on_path:
            (bin_dir / "codex").write_text(codex)
            (bin_dir / "codex").chmod(0o755)
        env = {**os.environ, **self.env, "PATH": f"{bin_dir}:/usr/bin:/bin"}
        result = subprocess.run([sys.executable, str(self.CLI), *args], env=env, capture_output=True, text=True)
        return result.returncode, result.stdout

    def test_clean(self):
        self.assertEqual(self.drift("claude") + self.drift("codex"), [])
        self.assertEqual(self.cli(), (0, "hooks match manifest.json\n"))

    def test_missing(self):
        self.env = fake_home(self.home, drop={"~/kit/hooks/verdict-stamp.py"})
        self.assertEqual(self.drift(), ["claude: missing PreToolUse ~/kit/hooks/verdict-stamp.py"])
        self.assertEqual(self.cli(), (1, "claude: missing PreToolUse ~/kit/hooks/verdict-stamp.py\n"))

    def test_extra(self):
        self.edit(self.codex, lambda hooks: hooks.setdefault("Stop", []).append({"hooks": [{"command": "~/kit/hooks/merge-gate.py"}]}))
        self.assertEqual(self.drift("codex"), ["codex: extra Stop ~/kit/hooks/merge-gate.py"])

    def test_a_kit_script_no_manifest_entry_runs_isnt_compared(self):
        self.edit(self.codex, lambda hooks: hooks.setdefault("Stop", []).append({"hooks": [{"command": "~/kit/hooks/x.py"}]}))
        self.assertEqual(self.drift("codex"), [])

    def test_an_older_link_to_a_kit_hook_is_extra(self):
        self.edit(self.claude, lambda hooks: hooks.setdefault("Stop", []).append({"hooks": [{"command": "~/.claude/hooks/ready-gate.py"}]}))
        self.assertEqual(self.drift(), ["claude: extra Stop ~/.claude/hooks/ready-gate.py"])

    def test_a_hook_addystack_didnt_install_isnt_compared(self):
        self.edit(self.codex, lambda hooks: hooks.setdefault("Stop", []).append({"hooks": [{"command": "~/bin/my-own-hook.sh"}]}))
        self.assertEqual(self.drift("codex"), [])

    def test_a_hook_the_config_doesnt_select_is_extra(self):
        no_rules = json.loads(ALL_HOOKS)
        no_rules["replies"]["rules"] = None
        resolved_state(self.env["ADDYSTACK_STATE"], json.dumps(no_rules), kit=pathlib.Path(self.env["HOME"], "kit"))
        self.assertEqual(self.drift(), ["claude: extra SessionStart ~/kit/hooks/reply-shape-context.py --rules"])

    def test_without_a_build_the_kit_defaults_select_the_recommended_hooks(self):
        os.remove(pathlib.Path(self.env["ADDYSTACK_STATE"], "resolved.json"))
        with unittest.mock.patch.object(hook_parity.resolved, "STATE", pathlib.Path(self.home, "none.json")):
            entries = hook_parity.declared("claude", "darwin")
        self.assertEqual({tag for entry in entries
                          for tag in next(e["tags"] for e in json.loads((HOOKS / "manifest.json").read_text())["claude"]
                                          if e["id"] == entry["id"])}, {"safety", "workflow"})
        self.assertTrue(all(entry["command"].startswith(hook_parity.hookset._kit({"kit": str(HOOKS.parent)}))
                            for entry in entries))

    def test_a_malformed_build_falls_back_to_the_kit_defaults(self):
        state = pathlib.Path(self.home, "malformed.json")
        good = json.loads(pathlib.Path(self.env["ADDYSTACK_STATE"], "resolved.json").read_text())
        for broken in ({**good, "kit": None}, {**good, "kit": ""}, {k: v for k, v in good.items() if k != "replies"},
                       {**good, "hooks": {**good["hooks"], "disable": "merge-gate"}}):
            state.write_text(json.dumps(broken))
            with self.subTest(broken=sorted(set(good) ^ set(broken)) or "kit null"), \
                    unittest.mock.patch.object(hook_parity.resolved, "STATE", state):
                entries = hook_parity.declared("claude", "darwin")
                self.assertFalse(any(entry["command"].startswith(("None", "''", "/hooks")) for entry in entries))
                self.assertIn("merge-gate", [entry["id"] for entry in entries])
                self.assertNotIn("reply-shape-context", [entry["id"] for entry in entries])

    def test_changed_timeout_matcher_and_on_failure(self):
        def change(hooks):
            for group in hooks["PreToolUse"]:
                for hook in group["hooks"]:
                    if hook["command"].endswith("merge-gate.py"):
                        hook["timeout"], group["matcher"] = 10, "Bash|Write"
                        del hook["onFailure"]
        self.edit(self.claude, change)
        self.assertEqual(self.drift(), [
            'claude: PreToolUse ~/kit/hooks/merge-gate.py has matcher "Bash|Write", manifest says "Bash"',
            "claude: PreToolUse ~/kit/hooks/merge-gate.py has timeout 10, manifest says 60",
            'claude: PreToolUse ~/kit/hooks/merge-gate.py has onFailure null, manifest says "block"'])

    def test_missing_or_dangling_script(self):
        home = self.env["HOME"]
        os.remove(pathlib.Path(home, "kit/hooks/ready-gate.py"))
        dangling = pathlib.Path(home, "kit/hooks/skills-checkout-check.py")
        os.remove(dangling)
        dangling.symlink_to(pathlib.Path(home, "gone.py"))
        self.assertEqual(self.drift(), [
            f"claude: PreToolUse ~/kit/hooks/ready-gate.py: {home}/kit/hooks/ready-gate.py doesn't exist",
            f"claude: SessionStart ~/kit/hooks/skills-checkout-check.py: {home}/kit/hooks/skills-checkout-check.py doesn't exist"])

    def test_missing_codex_file_counts_only_when_codex_is_installed_or_named(self):
        self.codex.unlink()
        missing = f"codex: {self.codex} is missing\n"
        self.assertEqual(self.cli(), (0, "hooks match manifest.json\n"))
        self.assertEqual(self.cli(codex_on_path=True), (1, missing))
        self.assertEqual(self.cli("--codex", str(self.codex)), (1, missing))

    def test_codex_trust_names_each_untrusted_hook(self):
        self.assertEqual(self.cli("--codex-trust", codex_on_path=True, codex=self.APP_SERVER),
                         (1, "codex trust: h:stop:0:0 is untrusted: ~/x.py\n"))

    def test_codex_trust_is_not_checked_when_the_server_exits_or_codex_is_missing(self):
        self.assertEqual(self.cli("--codex-trust", codex_on_path=True), (
            1, "codex trust: not checked, codex app-server didn't answer: it exited\n"))
        pathlib.Path(self.home, "bin", "codex").unlink()
        self.assertEqual(self.cli("--codex-trust"), (1, "codex trust: not checked, codex isn't on PATH\n"))

    def test_codex_trust_is_not_checked_when_the_server_exits_before_the_first_write(self):
        # The race in the test above, forced: the write then breaks the pipe.
        self.cli(codex_on_path=True)
        popen = subprocess.Popen

        def exited(*args, **kwargs):
            server = popen(*args, **kwargs)
            server.wait()
            return server

        with unittest.mock.patch.dict(os.environ, {"PATH": str(pathlib.Path(self.home, "bin"))}), \
                unittest.mock.patch.object(hook_parity.subprocess, "Popen", exited):
            self.assertEqual(hook_parity._codex_trust(),
                             ["codex trust: not checked, codex app-server didn't answer: it exited"])

    def test_codex_trust_is_not_checked_when_codex_cant_start(self):
        code, out = self.cli("--codex-trust", codex_on_path=True, codex="#!/nonexistent/interpreter\n")
        self.assertEqual(code, 1)
        self.assertRegex(out, "^codex trust: not checked, codex app-server didn't start: .+\n$")

    def test_malformed_config_gives_lines_not_a_crash(self):
        config = json.loads(self.claude.read_text())
        for bad in malformed(config):
            with self.subTest(bad=bad):
                self.claude.write_text(json.dumps(bad))
                self.assertIsInstance(self.drift(), list)
        self.claude.write_text("{")
        self.assertRegex(self.drift()[0], "^claude: can't read ")


class ManifestMatchesReadme(unittest.TestCase):
    """manifest.json and README.md's table describe the same hooks."""

    def setUp(self):
        manifest = json.loads((HOOKS / "manifest.json").read_text())
        self.scripts = {}
        for runtime, entries in manifest.items():
            for entry in entries:
                script = entry.get("script", pathlib.PurePath(entry["command"].split()[0]).name)
                self.scripts.setdefault(script, []).append((runtime, entry["event"]))
        self.rows = dict(re.findall(r"^\| `([^`]+)` \| ((?:[^|\\]|\\.)+) \|", (HOOKS / "README.md").read_text(), re.M))

    def test_every_manifest_script_is_in_hooks(self):
        for script in self.scripts:
            with self.subTest(script=script):
                self.assertTrue((HOOKS / script).is_file())

    def test_the_manifest_and_the_table_name_the_same_hooks(self):
        self.assertEqual(sorted(self.scripts), sorted(self.rows))

    def test_each_row_names_the_events_and_runtimes_the_manifest_gives(self):
        for script, uses in self.scripts.items():
            with self.subTest(script=script):
                runs_on = self.rows.get(script, "")
                for _, event in uses:
                    self.assertIn(event, runs_on)
                self.assertEqual("Codex" in runs_on, any(runtime == "codex" for runtime, _ in uses))


# A reply-shape path with no file behind it.
MISSING_SKILL = "/nonexistent/reply-shape.md"


class ReplyShapeContext(unittest.TestCase):
    HOOK = "reply-shape-context.py"

    SESSION = "296aa078-551a-4580-98b1-f667cc52d930"
    CHILD = "thread:delegated-task:command%3Amcp%3Aabc%3Adelegate-task%3Areview"

    # Reply preferences: reply-shape on, with no rules file unless a test names one.
    REPLY_SHAPE = '{ "replies": { "style": "reply-shape" } }'

    def run_hook(self, skill, source="startup", args=(), db="/nonexistent/statev2.sqlite", config=REPLY_SHAPE):
        with tempfile.TemporaryDirectory() as folder:
            env = resolved_state(folder, config)
            return subprocess.run(
                [str(HOOKS / self.HOOK), *args],
                input=json.dumps({"session_id": self.SESSION, "source": source}),
                capture_output=True, text=True, check=True,
                env={**env, "REPLY_SHAPE_SKILL": skill, "T3_STATE_DB": db}).stdout

    def output(self, skill, source="startup", args=(), db="/nonexistent/statev2.sqlite", config=REPLY_SHAPE):
        return json.loads(self.run_hook(skill, source, args, db, config))

    def test_without_an_override_it_loads_from_claude_config_dir(self):
        with tempfile.TemporaryDirectory() as folder:
            skill = pathlib.Path(folder, "profile", "skills", "reply-shape", "SKILL.md")
            skill.parent.mkdir(parents=True)
            skill.write_text("PROFILE SKILL")
            env = {key: value for key, value in resolved_state(folder, self.REPLY_SHAPE).items()
                   if key != "REPLY_SHAPE_SKILL"}
            out = subprocess.run(
                [str(HOOKS / self.HOOK)], input=json.dumps({"session_id": self.SESSION, "source": "startup"}),
                capture_output=True, text=True, check=True,
                env={**env, "CLAUDE_CONFIG_DIR": str(skill.parents[2]), "T3_STATE_DB": "/nonexistent"}).stdout
            self.assertIn("PROFILE SKILL", out)

    def test_an_old_path_argument_loads_the_rules_file(self):
        # Settings rendered before --rules pass a path; that entry must still load the rules.
        with tempfile.TemporaryDirectory() as folder:
            skill, rules = pathlib.Path(folder, "skill.md"), pathlib.Path(folder, "rules.md")
            skill.write_text("SKILL CONTENT")
            rules.write_text("RULES CONTENT")
            out = self.output(str(skill), args=[str(pathlib.Path(folder, "old-replies.md"))],
                              config=self.with_rules(rules))
            self.assertIn("RULES CONTENT", out["hookSpecificOutput"]["additionalContext"])
            self.assertNotIn("SKILL CONTENT", out["hookSpecificOutput"]["additionalContext"])

    @staticmethod
    def with_rules(path, style="reply-shape"):
        """A user config with this reply style and rules file."""
        return json.dumps({"replies": {"style": style, "rules": str(path)}})

    def state_db(self, folder, thread_id, brief, native_id=SESSION, head_id=None, others=(), created_by=None):
        """A T3 state database whose thread_id row names native_id and, optionally, a conversation
        head. others adds (thread_id, own native id, head native id) rows. Messages come oldest
        user one first; created_by sets who wrote the brief."""
        path = os.path.join(folder, f"{len(os.listdir(folder))}-{thread_id}-{native_id}.sqlite".replace(":", "_"))
        db = sqlite3.connect(path)

        def payload(own, head):
            refs = {"nativeThreadRef": {"nativeId": own}}
            if head:
                refs["nativeConversationHeadRef"] = {"nativeId": head}
            return json.dumps(refs, separators=(",", ":"))

        with db:
            db.execute("create table orchestration_v2_projection_provider_threads "
                       "(thread_id text, payload_json text not null)")
            db.execute("create table orchestration_v2_projection_messages "
                       "(thread_id text not null, role text not null, created_at text not null, "
                       "payload_json text not null)")
            db.executemany("insert into orchestration_v2_projection_provider_threads values (?, ?)",
                           [(t, payload(own, head)) for t, own, head in [(thread_id, native_id, head_id), *others]])
            db.executemany("insert into orchestration_v2_projection_messages values (?, ?, ?, ?)", [
                (thread_id, "user", "2026-10-16T10:00:01Z", json.dumps({"text": "Reply rules: on"})),
                (thread_id, "user", "2026-10-16T10:00:00Z",
                 json.dumps({"text": brief, **({"createdBy": created_by} if created_by else {})})),
                (thread_id, "assistant", "2026-10-16T09:00:00Z", json.dumps({"text": "Reply rules: on"})),
            ])
        db.close()
        return path

    def test_skips_a_delegated_child(self):
        with tempfile.TemporaryDirectory() as folder:
            brief = "Act as the review sub-agent for this task.\n\nReview it."
            skill = str(REPO / "skills" / "optional" / "reply-shape" / "SKILL.md")
            own = self.state_db(folder, self.CHILD, brief)
            for args in [(), ("--rules",)]:
                with self.subTest(args=args):
                    self.assertEqual(self.run_hook(skill, args=args, db=own,
                                                   config=self.with_rules(RULES)), "")
            head = self.state_db(folder, self.CHILD, brief, native_id="other", head_id=self.SESSION)
            with self.subTest("matched through its head ref"):
                self.assertEqual(self.run_hook(skill, db=head), "")

    def test_skips_a_coordinators_marked_worker(self):
        # A worker on a linked machine is a top-level mcp:launch: thread there; its brief marks it.
        worker = "mcp:launch:3f9a1c"
        brief = ("Act as the research sub-agent for this task.\n\nMode: personal, planning autonomous\n"
                 "Worker of: t3-thread://v2/env-mac/5ba1b6b8-31b4-45fa-a466-ee92b89ec497\nProbe it.")
        with tempfile.TemporaryDirectory() as folder, \
                tempfile.NamedTemporaryFile("w", suffix=".md") as skill:
            skill.write("# Reply shape\n")
            skill.flush()
            for case, db, skips in [
                ("agent-written brief with the marker", self.state_db(folder, worker, brief, created_by="agent"), True),
                # As 51 Mac worker briefs named their coordinator by Nov 25, 2026.
                ("the marker naming the coordinator", self.state_db(folder, worker, brief.replace(
                    "Worker of: t3-thread://", "Worker of: the ◆ app coordinator (t3-thread://"), created_by="agent"), True),
                ("the same text the user typed", self.state_db(folder, worker, brief, created_by="user"), False),
                ("agent-written brief without the marker", self.state_db(
                    folder, worker, brief.replace("Worker of:", "Worker for:"), created_by="agent"), False),
                ("the marker inside a line", self.state_db(
                    folder, worker, brief.replace("\nWorker of:", " Worker of:"), created_by="agent"), False),
            ]:
                with self.subTest(case):
                    self.assertEqual(self.run_hook(skill.name, db=db) == "", skips)

    def test_loads_for_a_child_that_opts_in(self):
        brief = ("Act as the test sub-agent for this task.\n\n"
                 "Reply rules: on. This run plays the user's own session.\nWork in /tmp/x.")
        with tempfile.TemporaryDirectory() as folder, \
                tempfile.NamedTemporaryFile("w", suffix=".md") as skill:
            skill.write("# Reply shape\n")
            skill.flush()
            out = self.output(skill.name, db=self.state_db(folder, self.CHILD, brief))
        self.assertIn("# Reply shape", out["hookSpecificOutput"]["additionalContext"])

    def test_loads_unless_the_db_names_a_delegated_child(self):
        with tempfile.TemporaryDirectory() as folder, \
                tempfile.NamedTemporaryFile("w", suffix=".md") as skill:
            skill.write("# Reply shape\n")
            skill.flush()
            no_tables = os.path.join(folder, "empty.sqlite")
            sqlite3.connect(no_tables).close()
            for case, db in [
                ("own thread", self.state_db(folder, "5ba1b6b8-31b4-45fa-a466-ee92b89ec497", "Review it.")),
                ("no matching row", self.state_db(folder, self.CHILD, "Review it.", native_id="other")),
                ("two threads match", self.state_db(folder, self.CHILD, "Review it.", others=[
                    ("5ba1b6b8-31b4-45fa-a466-ee92b89ec497", "other", self.SESSION)])),
                ("missing db", "/nonexistent/statev2.sqlite"),
                ("db without the tables", no_tables),
            ]:
                with self.subTest(case):
                    out = self.output(skill.name, db=db)["hookSpecificOutput"]
                    self.assertIn("# Reply shape", out["additionalContext"])

    def test_loads_the_body_without_frontmatter(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md") as skill:
            skill.write("---\nname: reply-shape\n---\n\n# Reply shape\n\n## Sections\n")
            skill.flush()
            out = self.output(skill.name)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        self.assertTrue(out["additionalContext"].startswith(
            f"These are the user's reply rules, from {skill.name}."))
        self.assertIn("# Reply shape\n\n## Sections", out["additionalContext"])
        self.assertNotIn("name: reply-shape", out["additionalContext"])

    def test_loads_from_every_source(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md") as skill, \
                tempfile.NamedTemporaryFile("w", suffix=".md") as extra:
            skill.write("# Reply shape\n")
            extra.write("# Replies\n")
            skill.flush()
            extra.flush()
            for args, heading in [((), "# Reply shape"), (("--rules",), "# Replies")]:
                for source in ["startup", "resume", "clear", "compact", "fork"]:
                    with self.subTest(source=source, args=args):
                        out = self.output(skill.name, source, args, config=self.with_rules(extra.name))
                        out = out["hookSpecificOutput"]
                        self.assertIn(heading, out["additionalContext"])

    def test_warns_past_the_hook_limit(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md") as skill:
            skill.write("x" * 10_000)
            skill.flush()
            out = self.output(skill.name)
        self.assertIn("over the hook limit", out["systemMessage"])
        self.assertIn("x" * 10_000, out["hookSpecificOutput"]["additionalContext"])

    def test_the_real_skill_fits_the_hook_limit(self):
        out = self.output(str(REPO / "skills" / "optional" / "reply-shape" / "SKILL.md"))
        self.assertNotIn("systemMessage", out)
        self.assertLess(len(out["hookSpecificOutput"]["additionalContext"]), 10_000)

    @unittest.skipUnless((REPO / "replies.md").is_file(), "the maintainer's replies.md is the workshop's")
    def test_the_real_replies_fit_the_hook_limit(self):
        out = self.output(MISSING_SKILL, args=["--rules"],
                          config=self.with_rules(REPO / "replies.md"))
        self.assertNotIn("systemMessage", out)
        self.assertLess(len(out["hookSpecificOutput"]["additionalContext"]), 10_000)

    def test_style_own_without_rules_loads_nothing(self):
        skill = str(REPO / "skills" / "optional" / "reply-shape" / "SKILL.md")
        for config in ['{ "replies": { "style": "own" } }', "{}"]:
            for args in [(), ("--rules",)]:
                with self.subTest(config=config, args=args):
                    self.assertEqual(self.run_hook(skill, args=args, config=config), "")

    def test_each_entry_loads_its_own_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md") as skill, \
                tempfile.NamedTemporaryFile("w", suffix=".md") as rules:
            skill.write("# Reply shape\n")
            rules.write("# My rules\n")
            skill.flush()
            rules.flush()
            config = self.with_rules(rules.name)
            shape = self.output(skill.name, config=config)["hookSpecificOutput"]["additionalContext"]
            mine = self.output(skill.name, args=["--rules"], config=config)["hookSpecificOutput"]["additionalContext"]
            own = self.output(skill.name, args=["--rules"], config=self.with_rules(rules.name, "own"))
        self.assertIn("# Reply shape", shape)
        self.assertNotIn("# My rules", shape)
        self.assertIn("# My rules", mine)
        self.assertNotIn("# Reply shape", mine)
        self.assertIn(f"from {rules.name}.", mine)
        # Style own still loads a rules file the user named.
        self.assertIn("# My rules", own["hookSpecificOutput"]["additionalContext"])

    def test_a_missing_rules_file_loads_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            rules = pathlib.Path(folder, "replies.md")
            rules.write_text("# My rules\n")
            env = resolved_state(folder, self.with_rules(rules))
            rules.unlink()
            result = subprocess.run([str(HOOKS / self.HOOK), "--rules"], input="{}", capture_output=True,
                                    text=True, env={**env, "T3_STATE_DB": "/nonexistent/statev2.sqlite"})
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_warns_when_the_skill_is_missing(self):
        out = self.output("/nonexistent/SKILL.md")
        self.assertIn("reply-shape couldn't load", out["systemMessage"])
        self.assertIn("replies use the default format", out["systemMessage"])
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_rules_load_without_frontmatter(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md") as skill, \
                tempfile.NamedTemporaryFile("w", suffix=".md") as extra:
            skill.write("# Reply shape\n")
            extra.write("---\nname: extra\n---\n\n# Replies\n")
            skill.flush()
            extra.flush()
            context = self.output(skill.name, args=["--rules"], config=self.with_rules(extra.name))
            context = context["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(context.startswith(f"These are the user's reply rules, from {extra.name}."))
        self.assertIn("# Replies", context)
        self.assertNotIn("# Reply shape", context)
        self.assertNotIn("name: extra", context)


class AgentMemoryGuardNotice(unittest.TestCase):
    HOOK = "agent-memory-guard-notice.py"
    STORM = "zsh -c 'for i in {1..700}; do sleep 1 & done; wait'"

    def entry(self, command, seconds_ago=1, agent_pid=None):
        # The hook runs as this test's child, so this test process stands in for the agent.
        return json.dumps({"at": time.time() - seconds_ago, "agent_pid": agent_pid or os.getpid(),
                           "reason": "702 processes, over the per-command 600",
                           "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
                           "command": command[:500]}) + "\n"

    def output(self, command, log, duration_ms=3000, home=None):
        with tempfile.TemporaryDirectory() as fresh:
            home = home or fresh
            logs = pathlib.Path(home, "Library", "Logs")
            logs.mkdir(parents=True, exist_ok=True)
            (logs / "agent-memory-guard.log").write_text(log)
            return run_hook(self.HOOK, {"tool_name": "Bash", "tool_input": {"command": command},
                                        "error": "Exit code 1", "duration_ms": duration_ms},
                            env={"HOME": home})

    def test_reports_a_kill_once_so_an_immediate_retry_stays_quiet(self):
        log = self.entry(self.STORM, seconds_ago=0.5)
        with tempfile.TemporaryDirectory() as home:
            self.assertIn("702 processes", self.output(self.STORM, log, home=home))
            self.assertEqual(self.output(self.STORM, log, duration_ms=100, home=home), "")

    def test_tells_the_agent_its_command_was_killed(self):
        self.assertIn("702 processes", self.output(self.STORM, self.entry(self.STORM)))

    def test_quiet_for_another_command_sharing_the_first_500_characters(self):
        preamble = "python3 - <<'EOF'\n" + "# setup\n" * 100
        killed, failed = preamble + "storm()\nEOF", preamble + "check()\nEOF"
        self.assertEqual(self.output(failed, self.entry(killed)), "")

    def test_quiet_for_a_kill_before_this_run_started(self):
        self.assertEqual(self.output(self.STORM, self.entry(self.STORM, seconds_ago=4),
                                     duration_ms=100), "")

    def test_quiet_for_another_sessions_kill_of_the_same_command(self):
        other = subprocess.Popen(["sleep", "5"])
        try:
            self.assertEqual(self.output(self.STORM, self.entry(self.STORM, agent_pid=other.pid)), "")
        finally:
            other.kill()
            other.wait()

    def test_skips_a_partial_line_and_still_finds_the_kill(self):
        log = self.entry(self.STORM) + '{"at": 1, "reason": "trunc'
        self.assertIn("702 processes", self.output(self.STORM, log))
        self.assertEqual(self.output("bun run test", '{"partial'), "")

    def test_quiet_without_a_log(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(run_hook(self.HOOK, {"tool_input": {"command": "x"}},
                                      env={"HOME": home}), "")


FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
s = json.load(open(os.environ["FAKE_GH"]))
a = sys.argv[1:]
if s.get("broken"):
    sys.exit("gh: network down")
if a[:2] == ["pr", "view"]:
    print(s["pr"])
elif a[:2] == ["stack", "view"]:
    print(json.dumps(s["stack"])) if "stack_error" not in s else sys.exit(s["stack_error"])
elif a[:2] == ["repo", "view"] and "url" in a:  # a named repo's URL, or the checkout's
    named = a[2] if len(a) > 2 and not a[2].startswith("-") else None
    print(("https://" + named if named.count("/") == 2 else "https://github.com/" + named) if named
          else s.get("clone", "https://github.com/o/r"))
elif a[:2] == ["repo", "view"]:
    print("o r")
elif a[:2] == ["api", "graphql"]:
    host = a[a.index("--hostname") + 1] if "--hostname" in a else "github.com"
    if host != s.get("host", "github.com"):
        sys.exit(f"gh: {host} isn't the repo's host")
    print(json.dumps({"data": {"repository": s["repository"]}}))
else:
    sys.exit(1)
"""


class MergeGate(unittest.TestCase):
    HOOK = "merge-gate.py"

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        bin_dir = os.path.join(self.dir, "bin")
        os.makedirs(bin_dir)
        gh = os.path.join(bin_dir, "gh")
        with open(gh, "w") as f:
            f.write(FAKE_GH)
        os.chmod(gh, 0o755)
        outside_t3 = {k: v for k, v in os.environ.items() if k != "T3CODE_CLI_PATH"}
        self.env = dict(outside_t3, PATH=f"{bin_dir}:{os.environ['PATH']}",
                        FAKE_GH=os.path.join(self.dir, "scenario.json"), T3_STATE_DB="/nonexistent",
                        # Nothing built here, so the kit's defaults (trust draft) until a test calls trust().
                        ADDYSTACK_STATE=os.path.join(self.dir, "state"), GIT_AUTHOR_NAME="t",
                        GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        # PR heads are made in a writer clone, so the gate's own clone must fetch them.
        origin, self.writer = os.path.join(self.dir, "origin"), os.path.join(self.dir, "writer")
        self.repo, self.heads, self.merges, self.base = os.path.join(self.dir, "repo"), {}, {}, "main"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", self.writer], check=True)
        self.git("remote", "add", "origin", origin)
        pathlib.Path(self.writer, "f").write_text("a\n")
        pathlib.Path(self.writer, "b.bin").write_bytes(b"\0\1")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.git("push", "-q", "origin", "main")
        self.main = self.git("rev-parse", "HEAD").strip()
        subprocess.run(["git", "clone", "-q", origin, self.repo], check=True)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.writer, env=self.env, check=True,
                              capture_output=True, text=True).stdout

    def pr(self, n, files=()):
        """PR n's head on origin: a text change, or a binary one for n >= 20, or the files
        given, as a list of names that each hold n or a dict of names to text."""
        if n not in self.heads:
            self.git("checkout", "-q", "--detach", self.main)
            if n >= 20 and not files:
                pathlib.Path(self.writer, "b.bin").write_bytes(bytes([0, n]))
            elif not files:
                files = [f"f{n}"]
            for name in files:
                pathlib.Path(self.writer, name).parent.mkdir(parents=True, exist_ok=True)
                pathlib.Path(self.writer, name).write_text(files[name] if isinstance(files, dict) else f"{n}\n")
            self.git("add", ".")
            self.git("commit", "-qm", str(n))
            self.git("push", "-q", "origin", f"HEAD:refs/pull/{n}/head")
            self.heads[n] = self.git("rev-parse", "HEAD").strip()
            self.git("checkout", "-q", "main")
        return self.heads[n]

    def merge(self, n):
        """PR n's merge commit on origin, as GitHub makes refs/pull/n/merge: its base merged
        with its head."""
        if n not in self.merges:
            tree = self.git("merge-tree", "--write-tree", self.main, self.pr(n)).strip()
            self.merges[n] = self.git("commit-tree", tree, "-p", self.main, "-p", self.pr(n), "-m", f"merge {n}").strip()
            self.git("push", "-q", "origin", f"{self.merges[n]}:refs/pull/{n}/merge")
        return self.merges[n]

    def verify(self, n, legacy=False):
        out = subprocess.run(["git", "patch-id", "--verbatim"], capture_output=True, text=True, check=True,
                             input=verdicts.diff(pathlib.Path(self.writer), self.main, self.pr(n))).stdout
        os.makedirs(os.path.join(self.repo, ".git", "verify-work"), exist_ok=True)
        with open(os.path.join(self.repo, ".git", "verify-work", "verdicts.tsv"), "w" if legacy else "a") as f:
            f.write(out.split()[0] + ("\tsha\tmain\tnow\n" if legacy else "\thead\tbase\tnow\tv2\ts\ta\twork-verifier\n"))

    def scenario(self, main="SUCCESS", prs=None, **extra):
        prs = prs or {12: "SUCCESS"}
        rollup = lambda state: {"state": state} if state else None
        default = self.git("rev-parse", "main").strip()
        repository = {"defaultBranchRef": {"name": "main", "target": {"oid": default, "statusCheckRollup": rollup(main)}}}
        for n, state in prs.items():
            repository[f"p{n}"] = {"number": n, "state": "OPEN", "baseRefName": self.base, "baseRefOid": self.main,
                                   "headRefOid": self.pr(n), "potentialMergeCommit": {"oid": self.merge(n)}, "commits": {"nodes": [
                {"commit": {"oid": self.pr(n), "statusCheckRollup": rollup(state)}}]}}
        stack = {"branches": [{"pr": {"number": n, "state": "OPEN"}, "isMerged": False} for n in prs]}
        data = {"pr": next(iter(prs)), "stack": stack, "repository": repository, **extra}
        with open(self.env["FAKE_GH"], "w") as f:
            json.dump(data, f)

    def reason(self, command, said=(), **event):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": self.repo, **event}
        if said:
            payload["transcript_path"] = os.path.join(self.dir, f"{event.get('session_id', 'session')}.jsonl")
            with open(payload["transcript_path"], "w") as transcript:
                for entry in said:  # a typed prompt, or an entry as it is, such as a reply
                    transcript.write(json.dumps(claude_said(entry) if isinstance(entry, str) else entry) + "\n")
        out = subprocess.run([str(HOOKS / self.HOOK)], input=json.dumps(payload), env=self.env,
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] if out else None

    def test_allows_green_verified_merges(self):
        self.scenario(prs={12: "SUCCESS", 13: "SUCCESS"})
        self.verify(12)
        self.verify(13)
        for command in ["gh pr merge 12 --squash", "gh pr merge", "gh stack merge --yes",
                        "gh stack merge 13", "cd . && gh pr merge 12 -R o/r"]:
            with self.subTest(command=command):
                self.assertIsNone(self.reason(command))

    def test_reads_a_cd_path_that_ends_at_a_semicolon(self):
        # Nov 16 and 23, 2026: `cd <worktree>; gh stack merge …` was read as the path `<worktree>;`.
        self.scenario()
        self.verify(12)
        for command in [f"cd {self.repo}; gh pr merge 12 --squash", f"cd {self.repo}&& gh pr merge 12",
                        f"cd {self.dir}; cd repo; gh pr merge 12", f"cd {self.repo} && git status | head -3 && gh pr merge 12",
                        f"cd {self.repo} || exit 1; gh pr merge 12", "cd repo; (cd .) && gh pr merge 12"]:
            with self.subTest(command=command):
                self.assertIsNone(self.reason(command, cwd=self.dir))
        # Review of #102: each cd counts, in order, so `cd <other>; cd .` stays in <other>,
        # and one that may not run in this shell, if it moves, leaves the checkout unknown.
        # verify-work on #102: the merge reads its cds as ready-gate does (shell_dirs.Walk), so
        # cd -P, an assignment before cd, and builtin cd and command cd move the shell too.
        self.assertIsNone(self.reason(f"cd -P {self.repo} && gh pr merge 12", cwd=self.dir))
        for command in [f"cd {self.dir}; cd .; gh pr merge 12 --squash", f"X=1 cd {self.dir} && gh pr merge 12",
                        f"noglob cd {self.dir} && gh pr merge 12",
                        f"builtin cd {self.dir} && gh pr merge 12", f"command cd {self.dir} && gh pr merge 12"]:
            with self.subTest(command=command):
                self.assertIn("couldn't check the merge", self.reason(command))
        for command in ["(cd child); cd .. && gh pr merge 12 --squash", f"false || cd {self.dir}; gh pr merge 12",
                        f"if true; then cd {self.dir}; fi; gh pr merge 12",
                        f"true | cd {self.dir}; gh pr merge 12", "popd && gh pr merge 12",
                        # Round 3: a cd in a && chain the merge isn't in, or in a case arm.
                        f"false && cd {self.dir}; cd . && gh pr merge 12",
                        f"case x in y) cd {self.dir} ;; esac; gh pr merge 12", f"\\cd {self.dir} && gh pr merge 12"]:
            with self.subTest(command=command):
                self.assertIn("so the gate can't tell which checkout the merge runs in: run `cd <checkout> && "
                              "gh pr merge 12", self.reason(command))
        # verify-work on #102, round 2: eval or source runs code that may cd, and a cd that
        # may not run, though it doesn't move, may still set the directory `cd -` returns to.
        for command in [f"eval cd {self.dir} && gh pr merge 12", ". ./env.sh && gh pr merge 12",
                        f"cd {self.dir}; false || cd {self.dir}; cd - && gh pr merge 12"]:
            with self.subTest(command=command):
                self.assertIn("so the gate can't tell which checkout the merge runs in", self.reason(command))
        self.assertIn("runs `.`, whose code it can't read", self.reason(". ./env.sh && gh pr merge 12"))
        # zsh's AUTO_CD enters a directory named as a command, as ready-gate.py reads it.
        self.assertIn("which zsh's AUTO_CD enters", self.reason("repo && gh pr merge 12", cwd=self.dir))

    def test_reads_githubs_stack_when_no_local_stack_holds_the_pr(self):
        # Nov 11, 16, 19, and 20, 2026: `gh stack merge N` from a checkout on no branch, or on
        # a branch in no local stack, was denied as "couldn't check", though gh stack merges
        # GitHub's stack of N from there.
        def scenario(error, entries, alone=()):
            self.scenario(prs={n: "SUCCESS" for n in (12, 13)}, stack_error=error)
            data = json.loads(pathlib.Path(self.env["FAKE_GH"]).read_text())
            data["repository"]["stackOf"] = {"stack": {"entries": {"nodes": [
                {"position": at, "pullRequest": {"number": n, "state": state}} for at, (n, state) in entries]}}
                if entries else None}
            for n in alone:
                data["repository"][f"p{n}"]["stack"] = None
            pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps(data))
        self.verify(12)
        self.verify(13)
        for error in ['\u2717 current branch "feat/x" is not part of a stack',
                      "\u2717 failed to get current branch: git: not on any branch"]:
            with self.subTest(error=error):
                scenario(error, [(2, (13, "OPEN")), (1, (12, "OPEN")), (0, (11, "MERGED"))])
                self.assertIsNone(self.reason("gh stack merge 13 --yes --squash"))
                scenario(error, [(1, (12, "OPEN")), (2, (13, "OPEN"))])
                self.assertIsNone(self.reason("gh stack merge 12"))  # only the PRs up to 12
                self.assertIn("couldn't check the merge", self.reason("gh stack merge --yes"))  # no PR to read
                scenario(error, None, alone=[12])
                self.assertIn("#12 is in no stack on GitHub, so `gh stack merge` can't merge it: use `gh pr merge 12`",
                              self.reason("gh stack merge 12 --yes --squash"))
                scenario(error, [(1, (14, "OPEN"))])  # a stack that doesn't hold the PR fails closed
                self.assertIn("couldn't check the merge", self.reason("gh stack merge 12"))
        pathlib.Path(self.repo, ".git", "verify-work", "verdicts.tsv").unlink()
        self.verify(13)  # each PR of GitHub's stack still needs its own Done
        scenario('\u2717 current branch "feat/x" is not part of a stack', [(1, (12, "OPEN")), (2, (13, "OPEN"))])
        self.assertIn("#12 has no Done verdict", self.reason("gh stack merge 13"))

    def test_checks_a_merge_run_outside_a_checkout_in_the_sessions_clone(self):
        # Nov 23, 2026: `cd /tmp && … gh pr merge 6136 -R o/r --squash` was denied as "not a git
        # repository", though the session's own checkout is a clone of o/r.
        self.scenario()
        self.verify(12)
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside)
        self.assertIsNone(self.reason(f"cd {outside} && gh pr merge 12 -R o/r --squash"))
        self.assertIn("couldn't check the merge", self.reason(f"cd {outside} && gh pr merge 12 --squash"))  # no -R
        self.scenario(clone="https://github.com/x/y")
        self.assertIn("this merge runs outside a checkout of o/r, so the gate can't read its verdicts: run it from "
                      "one, as `cd <checkout of o/r> && gh pr merge 12 -R o/r --squash`",
                      self.reason(f"cd {outside} && gh pr merge 12 -R o/r --squash"))
        self.scenario()  # review of #102: o/r on another host isn't this clone's o/r
        self.assertIn("this merge runs outside a checkout of o/r",
                      self.reason(f"cd {outside} && gh pr merge 12 -R ghe.example/o/r --squash"))
        self.scenario(clone="https://ghe.example/o/r", host="ghe.example")  # a clone of it: its queries go there
        self.assertIsNone(self.reason(f"cd {outside} && gh pr merge 12 -R ghe.example/o/r --squash"))
        self.assertIn("couldn't check the merge", self.reason(f"cd {outside} && gh pr merge 12 -R o/r", cwd=outside))
        bare = os.path.join(outside, "bare.git")  # review of #102: git calls a bare repo no work tree
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
        self.scenario()
        self.assertIsNone(self.reason(f"cd {bare} && gh pr merge 12 -R o/r --squash"))

    def test_denies_a_red_or_running_default_branch(self):
        self.verify(12)
        for state, words in [("FAILURE", "is red"), ("PENDING", "still running")]:
            with self.subTest(state=state):
                self.scenario(main=state)
                self.assertIn(words, self.reason("gh pr merge 12"))

    def test_denies_failing_missing_or_unverified_pr_checks(self):
        self.verify(12)
        self.scenario(prs={12: "FAILURE"})
        self.assertIn("#12 checks are failure", self.reason("gh pr merge 12"))
        self.scenario(prs={12: None})
        self.assertIn("no CI on PRs", self.reason("gh pr merge 12"))
        self.scenario(prs={12: "SUCCESS", 13: "SUCCESS"})
        self.assertIn("#13 has no Done verdict", self.reason("gh stack merge"))
        self.assertNotIn("#12 has no Done verdict", self.reason("gh stack merge"))
        self.verify(12, legacy=True)
        self.assertIn("#12 has no Done verdict", self.reason("gh pr merge 12"))  # pre-verifier row

    def test_merges_a_pr_without_checks_on_the_users_go(self):
        # Oct 22, 2026: "if all these PRs add value and are safe to merge, then just do it",
        # on skills PRs, a repo with no CI, which the gate then denied.
        self.scenario(prs={12: None})
        self.verify(12)
        for go in ["just merge it for me", "merge it and start next", "Can you merge #12?", "merge it",
                   "a, and merge it", "a + merge it", "go ahead and merge 14 and 15", "Merge them.",
                   "great, lets merge the pr", "Can you please merge it.", "can you merge all the PRs that are ready",
                   "a, and merge it when it’s passing ci", "merge both, then `a`", "merge #17 and #18 -> c",
                   "sounds good mark them ready for review and merge in that order", "  merge the stack of #53-#55 ",
                   # A go that names a repo is held to its PRs, so these name #12 here.
                   "merge r#12", "merge o/r#12", "go ahead and merge r#12 and skills#118",
                   # Oct 25, 2026: denied as a go until "the ones" counted as a target.
                   "can you just merge the ones that are ready to be merged now?", "merge those",
                   "merge the ready ones",
                   # Oct 29, 2026: denied as a go until "both stacks" and a closing "please" counted
                   # (MergeGo holds the rest of the replayed prompts).
                   "merge both stacks please"]:
            with self.subTest(go=go):
                self.assertIsNone(self.reason("gh pr merge 12", said=("fix it", go)))
        # Gos the sentence matcher read that the literal one doesn't: another step, a
        # question first, or an if-clause. Picking the reply's merge option still works.
        for said in [("what's left? merge it",), ("Push it and merge it",), ("fix it, then please merge it",),
                     ("Can you merge it? Thanks.",), ("Merge it. Any issues?",),
                     ("if all these PRs add value and are safe to merge, then just do it",),
                     ("merge it?",), ("no, merge it",), ("merge it and revert it",), ("merge it " + "now " * 60,),
                     ("please " * 30 + "merge it",)]:  # past the 200-character cap
            with self.subTest(said=said):
                self.assertIn("no CI on PRs", self.reason("gh pr merge 12", said=said))
        for said in [(), ("merge it", "a"), ("is it ready to merge?",), ("don't merge it yet",),
                     ("never merge without me",), ("verify it, but do not merge",),
                     ("fix the merge conflicts and push",), ("verify the merge-gate change",),
                     ("/resolving-merge-conflicts",), ("Review the merge gate",),
                     ("merge main into the branch",), ("Can you check whether it is safe to merge?",),
                     ("don’t merge it yet",), ("no merging today",), ("hold off on merging",),
                     ("wait before merging",), ("Should I merge #12 now?\nNo, wait for my review",),
                     ("merge it", "Caveat: don't merge it yet"),
                     ("merge it", "Update on pull request #12, which T3 Code is watching for you"),
                     ("merge the ones that are failing",), ("which ones should I merge?",),
                     ("merge the failing ones",), ("merge those failing ones",),
                     ("ill just try to merge the stack of the 5 PRs again",), ("lets just let them merge it",),
                     ("tried to merge it, please look into why it failed",), ("the first 3 have been merge - please restack",),
                     ("it's now queued to merge. next please",), ("rebase it before we merge the full stack",),
                     ("list them in merge order",), ("revert the merge",), ("I'll merge it myself",),
                     ("merge it, but not yet",), ("merge into 2",), ("Check whether this PR is ready to merge.",),
                     ("Do not do anything until I explicitly tell you to merge.",),
                     ("No new push, PR-state, merge, deploy, paid-call or recorder permission.",),
                     ("do not push or open PRs, merge, or deploy anything",), ("it failed, merge was denied by the gate",),
                     ("CI passed, merge is blocked",), ("PR #12: merge blocked",), ("use rebase and merge as the method",),
                     ("see `Layer.merge(a, b)` in the diff",), ("Explain this command: merge it.",),
                     ("Tell me why we should merge, then go ahead with the review.",),
                     ("From the overview coordinator: " + "the slice is ready. " * 20 + "Merge it.",),
                     ("Resolve the merge conflicts, then just do it",), ("check the merge gate logs, then just do it",),
                     ("read up on merge queues, then do it",), ("don't merge dotfiles#1",), ("merge dotfiles#1?",),
                     ("the merge for dotfiles#1 failed",)]:
            with self.subTest(said=said):
                self.assertIn("no CI on PRs", self.reason("gh pr merge 12", said=said))
        with tempfile.TemporaryDirectory() as folder:  # another agent's brief, not the user
            self.env["T3_STATE_DB"] = ReplyShapeContext.state_db(
                self, folder, ReplyShapeContext.CHILD, "Merge it once verified.")
            self.assertIn("no CI on PRs", self.reason(
                "gh pr merge 12", said=("Merge it once verified.",), session_id=ReplyShapeContext.SESSION))
        self.env["T3CODE_CLI_PATH"] = "/t3"  # in T3, a go needs a database that tells a child apart
        self.assertIn("no CI on PRs", self.reason("gh pr merge 12", said=("merge it",)))
        for native_id, go in [("other", False), (ReplyShapeContext.SESSION, True)]:  # a session T3 doesn't own gives none
            with tempfile.TemporaryDirectory() as folder:
                self.env["T3_STATE_DB"] = ReplyShapeContext.state_db(self, folder, "thread:main", "hi", native_id=native_id)
                # Without the runs table, transcripts.py can't tell what another thread sent.
                self.assertIn("no CI on PRs", self.reason("gh pr merge 12", said=("merge it",), session_id=ReplyShapeContext.SESSION))
                with contextlib.closing(sqlite3.connect(self.env["T3_STATE_DB"])) as db:
                    db.execute("create table orchestration_v2_projection_runs (run_id text, provider_thread_id text)")
                    db.execute("alter table orchestration_v2_projection_messages add column run_id text")
                    db.commit()
                reason = self.reason("gh pr merge 12", said=("merge it",), session_id=ReplyShapeContext.SESSION)
                self.assertIsNone(reason) if go else self.assertIn("no CI on PRs", reason)
                self.assertIn("no CI on PRs", self.reason("gh pr merge 12", said=("merge it",)))  # no session id to look up
        del self.env["T3CODE_CLI_PATH"]
        self.env["T3_STATE_DB"] = "/nonexistent"
        self.scenario(prs={12: "FAILURE", 13: None})
        self.assertIn("#12 checks are failure", self.reason("gh stack merge", said=("merge them",)))
        self.assertIn("#13 has no Done verdict", self.reason("gh stack merge", said=("merge them",)))
        os.makedirs(os.path.join(self.writer, ".github", "workflows"))
        pathlib.Path(self.writer, ".github", "workflows", "ci.yml").write_text("on: pull_request\n")
        self.git("add", ".")
        self.git("commit", "-qm", "ci")
        self.git("push", "-q", "origin", "main")
        self.main = self.git("rev-parse", "HEAD").strip()
        self.scenario(prs={14: None})  # a CI repo whose checks haven't registered yet
        self.verify(14)
        self.assertIn("#14 has no checks yet", self.reason("gh pr merge 14", said=("merge it",)))

    def test_merges_on_a_pick_of_the_replys_merge_option(self):
        self.scenario(prs={12: None})
        self.verify(12)
        merge = {"key": "a", "class": "stop:merge", "text": "merge #12"}
        verify = {"key": "b", "class": "routine", "text": "run verify-work on #12 again"}
        offer = lambda *options: claude_wrote("✅ Verified.\n\n" + block({"state": "stop", "needs": [], "options": [
            {**option, "key": key} for key, option in zip("abc", options)]}))
        for said in [("fix it", offer(merge, verify), "a"), ("fix it", offer(verify, merge), " B. "),
                     ("fix it", offer(merge), "a, and merge it")] + [
                     ("fix it", offer({**merge, "text": text}), "a") for text in (
                         "merge #12 and #13", "merge the stack", "mark them ready for review and merge them all",
                         "merge #2 through #12 into main")]:
            with self.subTest(said=said[1:]):
                self.assertIsNone(self.reason("gh pr merge 12", said=said))
        for name, said in {
            "a routine option": ("fix it", offer(verify, merge), "a"),
            "a routine option that says merge": ("fix it", offer({**verify, "text": "merge main into the branch"}), "a"),
            "a merge class whose text doesn't say merge": ("fix it", offer({**merge, "text": "mark #12 ready"}), "a"),
            # stop:merge covers marking ready too, so an option that only mentions merging isn't a go.
            **{f"a merge class whose text isn't a go: {text}": ("fix it", offer({**merge, "text": text}), "a") for text in (
                "mark #17 ready, but don't merge",
                "mark #8 and #7 ready for review, so they can merge together",
                "confirm the merge gate allows #48, and mark it ready",
                "merge #90 and deploy production from the main checkout on main")},
            "a pick of a stale reply's option": ("fix it", offer(merge), "hold on", claude_wrote("Holding."), "a"),
            "a reply without a block": ("fix it", claude_wrote("**Next**\n\n- `a` → merge #12"), "a"),
            "a pick with more in it": ("fix it", offer(merge), "a, but wait"),
            "a question": ("fix it", offer(merge), "a?"),
            "no option with that key": ("fix it", offer(merge), "c"),
        }.items():
            with self.subTest(case=name):
                self.assertIn("no CI on PRs", self.reason("gh pr merge 12", said=said))
        with tempfile.TemporaryDirectory() as folder:  # a delegated child's pick isn't the user's
            self.env["T3_STATE_DB"] = ReplyShapeContext.state_db(self, folder, ReplyShapeContext.CHILD, "a")
            self.assertIn("no CI on PRs", self.reason("gh pr merge 12", said=("fix it", offer(merge), "a"),
                                                      session_id=ReplyShapeContext.SESSION))
        self.env["T3CODE_CLI_PATH"] = "/t3"  # in T3, an unreadable database gives no go
        self.env["T3_STATE_DB"] = "/nonexistent"
        self.assertIn("no CI on PRs", self.reason("gh pr merge 12", said=("fix it", offer(merge), "a")))

    # The coordinator's merge cards from suite-audit, 2026-11-02 and 11-03 (transcript
    # b5d5dbbc, lines 10587-10647 and 11883-11896), cut down, with their PRs renumbered.
    SCHEDULED = ("<command-message>coordinator</command-message>\n<command-name>/coordinator</command-name>\n"
                 "<command-args>check-in on #12's review-loop. If it reports verify-work Done, bring the user the "
                 "merge card (\"merge #12\"). Then delete this task.</command-args>")
    CARD = ("🟡 **Merge #12 now that review and verify-work are done?**\n\n"
            "1 of 1 needs you · Expo 58 upgrade <t3-thread://v2/0c5f5b0f-2c19-43e6-8a82-8fe66c1580b9/"
            "mcp:a0dc8ad7-3238-4b2e-ad9a-7898e62c0daf>\n\n**Problem**: agents skip diagnosing-bugs.\n\n"
            "```text\n#12  bug-route hook   +155 −7 · verify-work Done at 6b40fd79 · no CI\n```\n\n---\n\n"
            "**Next**\n\n- **`a` → merge #12** · *recommended*\n\n")
    WAKE = ("Delegated task node:delegated-task:command%3Amcp%3Acac6c54e%3Athread-send%3Asuite-audit-r39-empty-guard "
            "(suite-audit R39: Dagger CI + Dagger Cloud) [completed]:\n1. **Status: done.** verify-work ✅ Done at "
            "72837cd1; draft PR #13.\n\n")

    def card(self, options, text=CARD):
        return claude_wrote(text + block({"state": "stop", "needs": [{"id": 1, "kind": "review", "name": "merge #12"}],
                                          "options": options, "project": "suite-audit"}))

    def test_merges_on_a_pick_of_a_card_a_scheduled_wake_posted(self):
        # skills#257: the card names its worker's thread as an autolink, which isn't raw HTML.
        self.scenario(prs={12: None})
        self.verify(12)
        merge = [{"key": "a", "class": "stop:merge", "text": "merge #12"}]
        self.assertIsNone(self.reason("gh pr merge 12", said=(self.SCHEDULED, self.card(merge), "a")))
        # The scheduled prompt is never the go itself, as the latest prompt or as the card's pick.
        for said in [(self.card(merge), self.SCHEDULED.replace("check-in on #12's review-loop.", "a")),
                     (self.card(merge), self.SCHEDULED.replace("check-in on", "merge"))]:
            with self.subTest(said=said[1]):
                self.assertIn("no CI on PRs", self.reason("gh pr merge 12", said=said))
        with tempfile.TemporaryDirectory() as folder:  # nor is a bare "a" T3 says an agent sent
            self.env["T3_STATE_DB"] = ReplyShapeContext.state_db(self, folder, "thread:main", "a", created_by="agent")
            with contextlib.closing(sqlite3.connect(self.env["T3_STATE_DB"])) as db:
                db.execute("create table orchestration_v2_projection_runs (run_id text, provider_thread_id text)")
                db.execute("alter table orchestration_v2_projection_messages add column run_id text")
                db.commit()
            self.assertIn("no CI on PRs", self.reason("gh pr merge 12", said=(self.card(merge), "a"),
                                                      session_id=ReplyShapeContext.SESSION))

    # A manual /compact as Claude Code records it, and two merge cards, from suite-audit's
    # coordinator (transcript 4a2774dc, lines 6362-6366 and the cards before 6384 and 8610),
    # cut down, with their PRs renumbered. The gate refused both picks: the compact rows read
    # as a prompt nothing answered, and each card held a tag in a fold or in inline code.
    COMPACT = (
        {"type": "system", "subtype": "compact_boundary", "isMeta": False, "content": "Conversation compacted",
         "compactMetadata": {"trigger": "manual", "preTokens": 260652}},
        {"type": "user", "isCompactSummary": True, "isVisibleInTranscriptOnly": True, "message": {
            "role": "user", "content": "This session is being continued from a previous conversation that ran out "
                                       "of context. The summary below covers the earlier portion of the conversation."}},
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": (
            "<local-command-caveat>The command below was run directly in Claude Code, not sent to you as a request, "
            "and its output goes straight to the user. It's recorded here as context for later messages."
            "</local-command-caveat>")}},
        "<command-name>/compact</command-name>\n            <command-message>compact</command-message>\n"
        "            <command-args></command-args>",
        "<local-command-stdout>Compacted </local-command-stdout>",
    )
    CAST_CARD = ("🟡 **The cast script catches the real miss, but isn't fit to merge.**\n\n"
                 "<details><summary>Checks: ⚠️ review capped at 3 rounds, rated 1/10 · ⚠️ no CI · ✅ done check · "
                 "✅ tests 27/27</summary>\n\n**Why I wouldn't merge it**\n\n"
                 "- Example gap: JSX text such as `<p>save as Draft</p>` is read as a cast.\n\n</details>\n\n---\n\n"
                 "**Next**\n\n- **`a` → merge #12** · *recommended*\n"
                 "- `b` → test a small grouped cast list on the same replay, as a draft\n\n")
    DRAFTS_CARD = ("🟡 **Merge the three kit drafts: #12, #13 and #14?**\n\n"
                   "<details><summary>Checks: ⚠️ <code>xhigh</code> unmeasured · ⚠️ audit not run live · "
                   "✅ merge gate needs only your go</summary>\n\n**Reviews**\n\n- #13: Codex found nothing.\n\n"
                   "</details>\n\n---\n\n**Next**\n\n- **`a` → merge #12, #13 and #14** · *recommended*\n"
                   "- `b` → merge #12 and #13\n\n")

    def test_merges_on_a_recorded_pick_after_a_compact_or_past_a_tag(self):
        self.scenario(prs={12: None})
        self.verify(12)
        cast = self.card([{"key": "a", "class": "stop:merge", "text": "merge #12"},
                          {"key": "b", "class": "decision", "text": "test a small grouped cast list on the same "
                                                                    "replay, as a draft"}], text=self.CAST_CARD)
        drafts = self.card([{"key": "a", "class": "stop:merge", "text": "merge #12, #13 and #14"},
                            {"key": "b", "class": "stop:merge", "text": "merge #12 and #13"}], text=self.DRAFTS_CARD)
        for said in [(cast, *self.COMPACT, "a"), (drafts, "a"), (drafts, *self.COMPACT, *self.COMPACT[3:], "a")]:
            with self.subTest(said=said[1:]):
                self.assertIsNone(self.reason("gh pr merge 12", said=said))
        # A /compact still waiting on its output answered nothing, so the pick picks nothing.
        self.assertIn("no reply of yours came before it", self.reason("gh pr merge 12", said=(cast, self.COMPACT[3], "a")))
        # A tag that hides the block still refuses the pick.
        hidden = self.card([{"key": "a", "class": "stop:merge", "text": "merge #12"}],
                           text=self.CAST_CARD.replace("<p>save as Draft</p>", "<title>"))
        self.assertIn("can't be sure your reply's turn block was hidden", self.reason("gh pr merge 12", said=(hidden, "a")))

    def t3_sent(self, folder, sent, native_id=ReplyShapeContext.SESSION):
        """A T3 state database whose one thread owns native_id and holds sent, (text, creator)
        pairs oldest first, as its user-role messages."""
        path = self.env["T3_STATE_DB"] = os.path.join(folder, "statev2.sqlite")
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.execute("create table orchestration_v2_projection_provider_threads "
                       "(thread_id text, provider_thread_id text, payload_json text)")
            db.execute("create table orchestration_v2_projection_messages "
                       "(thread_id text, role text, created_at text, payload_json text, run_id text)")
            db.execute("create table orchestration_v2_projection_runs (run_id text, provider_thread_id text)")
            db.execute("insert into orchestration_v2_projection_provider_threads values (?, ?, ?)",
                       ("thread:main", "p1", json.dumps({"nativeThreadRef": {"nativeId": native_id}})))
            db.executemany("insert into orchestration_v2_projection_messages values (?, ?, ?, ?, ?)", [
                ("thread:main", "user", str(at), json.dumps({"text": text.strip(), "createdBy": creator}), None)
                for at, (text, creator) in enumerate(sent)])
            db.commit()

    def test_a_pick_answers_the_card_before_a_wake_in_the_same_turn(self):
        # skills#269: a worker's result, offering its own "a" = "merge #13", landed 2 s before
        # The user's "a" on the coordinator's card, in one turn with no reply between them.
        merge = [{"key": "a", "class": "stop:merge", "text": "merge #12"},
                 {"key": "b", "class": "decision", "text": "leave #12 as a draft for now"}]
        wake = self.WAKE + block({"state": "stop", "needs": [], "project": "suite-audit", "options": [
            {"key": "a", "class": "stop:merge", "text": "merge #13"}]})
        merge_wake = self.WAKE + block({"state": "stop", "needs": [], "options": [
            {"key": "a", "class": "stop:merge", "text": "merge #12"}]})
        folder = tempfile.mkdtemp(dir=self.dir)
        # T3 keeps an agent's "Background task completed." that the transcript lacks, so the
        # user's own copy pairs with it: a text the user sent too isn't surely an agent's.
        self.t3_sent(folder, [(wake, "agent"), (merge_wake, "agent"), ("Background task completed.", "agent"),
                              ("Background task completed.", "user"), ("a", "user")])
        reason = lambda command, said: self.reason(command, said=said, session_id=ReplyShapeContext.SESSION)
        self.scenario(prs={12: None})
        self.verify(12)
        self.assertIsNone(reason("gh pr merge 12", (self.card(merge), wake, "a")))
        self.assertIsNone(reason("gh pr merge 12", (self.card(merge), wake, wake, "a")))
        self.scenario(prs={13: None})
        self.verify(13)
        denied = reason("gh pr merge 13", (self.card(merge), wake, "a"))
        self.assertIn('the user\'s "a" picks "merge #12" from your reply before it, not a merge of #13', denied)
        self.assertIn('ask the user for "merge #13"', denied)
        self.scenario(prs={12: None})
        for name, said in {
            "the wake's own block": (self.card([{"key": "a", "class": "routine", "text": "fix the flaky test"}]),
                                     merge_wake, "a"),
            "a message the user typed that got no reply": (self.card(merge), "hold on", "a"),
            # Claude Code's own caveat prefix empties a typed message, but it's still the user's.
            "a typed message that reads as untyped": (self.card(merge), "Caveat: don't merge yet", "a"),
            # Only T3's database says who sent a message, not how it starts.
            "a typed message that looks like a wake": (self.card(merge), self.WAKE + "hold on, don't merge", "a"),
            "a wake outside T3's record": (self.card(merge), self.WAKE + "Done.", "a"),
            "a typed copy of an agent's text": (self.card(merge), "Background task completed.", "a"),
            "a wake with no card before it": ("fix it", claude_wrote("Looking."), "status?", wake, "a"),
        }.items():
            with self.subTest(case=name):
                self.assertIn("no CI on PRs", reason("gh pr merge 12", said))
        self.assertIn('the user\'s "a" picks "fix the flaky test" from your reply before it, which isn\'t a merge go',
                      reason("gh pr merge 12", (self.card([
                          {"key": "a", "class": "routine", "text": "fix the flaky test"}]), wake, "a")))
        self.assertIn('the user\'s "a" picks nothing: no reply of yours came before it',
                      reason("gh pr merge 12", (self.card(merge), "hold on", "a")))
        self.assertIn('picks nothing: your reply before it offers no option c',
                      reason("gh pr merge 12", (self.card(merge), "c")))
        self.assertIn("picks nothing: the gate can't be sure your reply's turn block was hidden",
                      reason("gh pr merge 12", (self.card(merge, "<title>\n\n"), "a")))

    def test_an_agents_pick_after_a_wake_never_counts(self):
        merge = [{"key": "a", "class": "stop:merge", "text": "merge #12"}]
        self.scenario(prs={12: None})
        self.verify(12)
        self.env["T3CODE_CLI_PATH"] = "/t3"
        for native_id, sender, go in [("other", "agent", False), (ReplyShapeContext.SESSION, "agent", False),
                                      (ReplyShapeContext.SESSION, "user", True)]:
            with self.subTest(native_id=native_id, sender=sender), tempfile.TemporaryDirectory() as folder:
                self.t3_sent(folder, [(self.WAKE, "agent"), ("a", sender)], native_id=native_id)
                reason = self.reason("gh pr merge 12", said=(self.card(merge), self.WAKE, "a"),
                                     session_id=ReplyShapeContext.SESSION)
                self.assertIsNone(reason) if go else self.assertIn("no CI on PRs", reason)

    def test_a_pick_merges_only_the_pr_its_option_names(self):
        self.scenario(prs={12: None})
        self.verify(12)
        for text, go in [("merge #12", True), ("merge 12", True), ("merge r#12", True), ("merge o/r#12", True),
                         ("merge #11 and #12", True), ("merge #2 through #12", True), ("merge #10-#14", True),
                         ("merge 10-14", True), ("merge #10- #14", True), ("merge #10 - #14", True),
                         ("merge #11&#12", True), ("merge 11 &12", True), ("merge #10 THROUGH #14", True),
                         ("merge #1 through 20", True),
                         ("merge the prs for the v2", True), ("merge them", True),
                         ("merge the 2 prs", True), ("merge the 2 PRs", True), ("merge the 12", True), ("merge the stack", True), ("merge #13", False), ("merge 13", False),
                         ("merge 13 and 14", False), ("merge 13&14", False), ("merge dotfiles#12", False),
                         ("merge other/r#12", False),
                         ("merge other/.r#12", False), ("merge #10 through other/r#14", False),
                         # A word that starts like a PR but doesn't read as one fails closed.
                         ("merge #10-#14-#16", False), ("merge #10 - #14 - #16", False), ("merge the 13", False),
                         ("merge #13 through #20", False)]:
            with self.subTest(text=text):
                reason = self.reason("gh pr merge 12", said=(
                    "fix it", self.card([{"key": "a", "class": "stop:merge", "text": text}]), "a"))
                self.assertIsNone(reason) if go else self.assertIn("not a merge of #12", reason)
        self.assertIsNone(self.reason("gh pr merge 12", said=("merge #13",)))  # a typed go isn't held to its PRs

    def test_a_pick_reads_a_bare_pr_beside_one_that_names_this_repo_as_another_repos(self):
        # Nov 10, 2026: a coordinator's card offered "merge #55 and dotfiles #36" for addystack
        # #55 and dotfiles #36. Read in dotfiles, its bare #55 is addystack's, so this repo, r,
        # stands in for each side in turn.
        self.scenario(prs={12: None})
        self.verify(12)
        for text, go in [("merge #12 and dotfiles#36", True), ("merge r#12 and dotfiles#36", True),
                         ("merge dotfiles#36 and #12", False), ("merge #36 and dotfiles#12", False),
                         ("merge #12 and r#36", False), ("merge #12 and o/r#36", False),
                         ("merge r#36 and #12", False), ("merge #12 and other/r#36", True),
                         # A range's bare end is in its other end's repo.
                         ("merge r#10 through #14", True), ("merge #10 through r#14", True),
                         ("merge r#10-#14", True), ("merge dotfiles#10 through #14", False),
                         ("merge #10 through dotfiles#14", False), ("merge dotfiles#10-#14", False),
                         ("merge #1 and r#10 through #14", True),
                         # review-loop r1, Nov 10, 2026: a range's bare end isn't also a PR of its own.
                         ("merge r#10 through #12", True), ("merge r #10 through #12", True),
                         ("merge #12 through r#14", True), ("merge #12 and sam/12306 #36", True),
                         ("merge #12 and 1password #36", True),
                         # The same round: a refusal of a range written high to low, and one
                         # in a word that is this repo's name, as a repo named exclude would read
                         # "merge exclude #10-#14, exclude #12". Naming one PR twice is no go.
                         ("merge #10-#14, exclude #14-#12", False), ("merge r #10-#14, r #12", False),
                         ("merge r #11, r #12", True),
                         ("merge #10-#14 and #12", True),  # naming one PR twice, with no repo, as before
                         # Round 3: a bare PR after one that names a repo may be that repo's.
                         ("merge dotfiles #36 and #12", False), ("merge dotfiles #36, #12", False),
                         # Round 2: a chained range can't say where its middle end is.
                         ("merge #10 through dotfiles #12 through #14", False),
                         ("merge #10 through dotfiles#12 through #14", False), ("merge #10-dotfiles#12 to #14", False),
                         # The card's own form, a space between repo and PR.
                         ("merge #12 and dotfiles #36", True), ("merge r #12 and dotfiles #36", True),
                         ("merge R #12", True), ("merge o/r #12", True), ("merge dotfiles #12", False),
                         ("merge other/r #12", False), ("merge #36 and dotfiles #12", False),
                         ("merge #12 and r #36", False), ("merge r #10 through #14", True),
                         ("merge r #10-#14", True), ("merge dotfiles #10 through #14", False),
                         # A word NOT_REPO misses, on a PR the option also names.
                         ("merge #10-#14, exclude #12", False), ("merge #12 and dotfiles #12", False),
                         ("merge #12 and dotfiles #13", True)]:
            with self.subTest(text=text):
                reason = self.reason("gh pr merge 12", said=(
                    "fix it", self.card([{"key": "a", "class": "stop:merge", "text": text}]), "a"))
                self.assertIsNone(reason) if go else self.assertIn("not a merge of #12", reason)

    def test_a_typed_go_that_names_a_pr_as_repo_space_number_is_held_to_its_prs(self):
        # Nov 10, 2026: verify-work found "merge #36, skip #12" passed for #12 once a word
        # before " #N" read as a repo, since a typed go isn't held to its PRs.
        self.scenario(prs={12: None})
        self.verify(12)
        for text in ["merge #12 and dotfiles #36", "merge r #12", "merge o/r #12 and dotfiles #36",
                     "merge r #10 through #12", "merge #13"]:  # no repo word, so as unheld as before
            with self.subTest(text=text):
                self.assertIsNone(self.reason("gh pr merge 12", said=(text,)))
        # verify-work's re-check, Nov 10, 2026: a word NOT_REPO misses, on a PR the go also
        # names, so a PR the merge holds that the go places in another repo gives no go.
        for text in ["merge #36, skippy #12", "merge #36 and dontt #12", "merge #36 and dotfiles #12",
                     "merge dotfiles #12", "merge #12 and r #36", "merge #10-#14, exclude #12",
                     "merge #10 through #14, leave #12", "merge #12, retest #12", "merge #12, omit #10-#14",
                     "merge #12 and dotfiles #12", "merge #10-#14, exclude #14-#12", "merge r #10-#14, r #12",
                     # review-loop r1: the joined form too, which no typed go was held to before.
                     "merge dotfiles#12", "merge dotfiles#1", "merge #55 and dotfiles#12",
                     "merge #10-dotfiles#14",  # round 2: a joined repo at a range's end
                     "merge dotfiles #36 and #12",  # round 3: a bare PR after a repo-named one
                     "merge sam/12306#12"]:
            with self.subTest(text=text):
                self.assertIn(f"the user's \"{text}\" isn't a merge of #12", self.reason("gh pr merge 12", said=(text,)))
        # gh stack merge takes every PR below the top one, so a go can't place any of them elsewhere.
        self.scenario(prs={11: None, 12: None})
        self.verify(11)
        self.assertIsNone(self.reason("gh stack merge 12", said=("merge #11-#12 and dotfiles #36",)))
        for text in ["merge #10-#12, exclude #11", "merge #12, retest #11", "merge #12, exclude #11-#10"]:
            with self.subTest(text=text):
                self.assertIn("isn't a merge of #12", self.reason("gh stack merge 12", said=(text,)))
                reason = self.reason("gh stack merge 12", said=(
                    "fix it", self.card([{"key": "a", "class": "stop:merge", "text": text}]), "a"))
                self.assertIn("not a merge of #12", reason)

    def workflow(self, text, name="ci.yml"):
        """Commit a workflow to main; PRs made after it branch from it."""
        path = pathlib.Path(self.writer, ".github", "workflows", name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text) if isinstance(text, bytes) else path.write_text(text)
        self.git("add", ".")
        self.git("commit", "-qm", f"workflow {name}")
        self.git("push", "-q", "origin", "main")
        self.main, self.heads, self.merges = self.git("rev-parse", "HEAD").strip(), {}, {}

    def test_merges_a_pr_its_workflows_skip_on_the_users_go(self):
        # workout-tracker-jj's #179 changed only docs, which its ci.yml ignores, so no check
        # ever ran, and the gate waited for CI to register even on the user's go.
        self.workflow(WorkflowTriggers.CI_YML)
        self.pr(30, ["AGENTS.md", "docs/x.md"])
        self.scenario(prs={30: None})
        self.verify(30)
        self.assertIsNone(self.reason("gh pr merge 30", said=("merge it",)))
        self.assertIn("#30 has no checks: this repo's CI skips it by its path or branch filters, so it merges "
                      "only when the user's latest prompt asks for the merge", self.reason("gh pr merge 30"))
        self.workflow("on:\n  pull_request:\n    branches: [release]\n")
        self.pr(31, ["apps/web/x.ts"])  # a code file, into a base the branch filter excludes
        self.scenario(prs={31: None})
        self.verify(31)
        self.assertIsNone(self.reason("gh pr merge 31", said=("merge it",)))

    def trust(self, value, remote=None):
        """Builds the policy the hook reads: trust value everywhere, or only in repos whose
        origin matches remote."""
        policy = {"repos": [{"match": {"remote": remote}, "trust": value}]} if remote else {"defaults": {"trust": value}}
        os.makedirs(self.env["ADDYSTACK_STATE"], exist_ok=True)
        resolved_state(self.env["ADDYSTACK_STATE"], json.dumps({"policy": policy}))

    def test_a_gate_repo_merges_a_pr_without_checks_on_a_fresh_done_alone(self):
        # Nov 8, 2026: the user asked twice for prefrontal, a repo with no CI, to merge on
        # its own, then still answered 56 merge cards that week.
        self.trust("gate")
        self.scenario(prs={12: None, 13: None})
        self.verify(12)
        self.verify(13)
        for command in ["gh pr merge 12", "gh stack merge --yes"]:
            with self.subTest(command=command):
                self.assertIsNone(self.reason(command))

    def test_a_gate_repo_asks_for_the_go_where_a_workflow_could_run(self):
        # Review round 1: a workflow the PR adds, or a pull_request_target one on the default
        # branch only, runs on the PR; and one its filters skip may still run on push.
        self.trust("gate")
        release = self.main  # a branch with no workflows
        self.git("push", "-q", "origin", f"{release}:refs/heads/release")
        self.pr(14, {".github/workflows/ci.yml": WorkflowTriggers.CI_YML})
        self.scenario(prs={14: None})
        self.verify(14)
        self.assertIn("#14 has no checks: this repo runs no CI on PRs", self.reason("gh pr merge 14"))
        self.workflow(WorkflowTriggers.CI_YML)
        self.pr(30, ["docs/x.md"])
        self.scenario(prs={30: None})
        self.verify(30)
        self.assertIn("#30 has no checks: this repo's CI skips it", self.reason("gh pr merge 30"))
        self.assertIsNone(self.reason("gh pr merge 30", said=("merge it",)))
        self.workflow("on: pull_request_target\n", "target.yml")
        self.main, self.base = release, "release"  # PRs into release, while main has workflows
        self.pr(15)
        self.scenario(prs={15: None})
        self.verify(15)
        self.assertIn("#15 has no checks: this repo runs no CI on PRs", self.reason("gh pr merge 15"))

    def test_a_gate_policy_that_didnt_resolve_asks_for_the_go(self):
        # Every rule is gate, so the strictest value, which an unreadable repo file gets, is too.
        self.trust("gate")
        self.scenario(prs={12: None})
        self.verify(12)
        pathlib.Path(self.repo, ".agents").mkdir()
        pathlib.Path(self.repo, ".agents", "addystack.jsonc").write_text('{ "trust": "draft",')
        self.assertIn("asks for the merge", self.reason("gh pr merge 12"))

    def test_a_gate_repo_merges_on_a_done_alone_from_the_lines_stack_sh_prints(self):
        self.trust("gate")
        self.scenario(prs={12: None})
        self.verify(12)
        for command in [f"cd {self.repo} && gh pr merge 12 --merge", f"cd {self.repo} && gh stack merge 12 --yes",
                        "gh pr ready 12 && gh pr merge 12 --merge", "gh pr merge 12 --squash -d"]:
            with self.subTest(command=command):
                self.assertIsNone(self.reason(command))

    def test_a_gate_repo_asks_for_the_go_for_a_merge_it_cant_bind_to_itself(self):
        # Review rounds 2 and 3: the gate resolves the PR, its trust, and its Done in the
        # checkout, so any other shell, which could merge another repo's PR or run somewhere
        # else, keeps the go: a repo flag in any form, a URL, branch, or missing target, or a
        # cd that a subshell, pipe, branch, or text could make not apply.
        self.trust("gate")
        self.scenario(prs={12: None})
        self.verify(12)
        for command in ["gh pr merge 12 -R o/r", "gh pr merge --repo=o/other 12", "gh pr merge -Ro/other 12",
                        "gh pr merge 12 -sRo/other", "GH_REPO=o/other gh pr merge 12",
                        "gh pr merge https://github.com/o/other/pull/12", "gh pr merge feature", "gh pr merge",
                        "( cd . ) && gh pr merge 12",
                        "false || cd . && gh pr merge 12", "cd . | cat && gh pr merge 12", "cd . ; gh pr merge 12",
                        "cd . && cd . && gh pr merge 12", "pushd . && gh pr merge 12", "echo cd . && gh pr merge 12"]:
            with self.subTest(command=command):
                self.assertIn("asks for the merge", self.reason(command))
        self.env["GH_REPO"] = "o/other"
        self.assertIn("asks for the merge", self.reason("gh pr merge 12"))

    def test_a_gate_repo_still_needs_a_fresh_done_and_passing_checks(self):
        self.trust("gate")
        self.scenario(prs={12: None})
        for verdict in [None, 13, "legacy"]:  # none, a Done for another diff, a pre-verifier row
            with self.subTest(verdict=verdict):
                if verdict:
                    self.verify(12, legacy=True) if verdict == "legacy" else self.verify(verdict)
                reason = self.reason("gh pr merge 12", said=("merge it",))
                self.assertIn("#12 has no Done verdict", reason)
                self.assertNotIn("asks for the merge", reason)  # no go to ask for: it wouldn't help
        self.verify(12)
        self.scenario(prs={12: "FAILURE"})
        self.assertIn("#12 checks are failure", self.reason("gh pr merge 12"))

    def test_only_a_gate_repo_merges_without_the_go(self):
        self.scenario(prs={12: None})
        self.verify(12)
        for trust, remote in [("merge-on-go", None), ("draft", None), ("gate", "/elsewhere$")]:
            with self.subTest(trust=trust, remote=remote):
                self.trust(trust, remote)
                self.assertIn("no CI on PRs", self.reason("gh pr merge 12"))
                self.assertIsNone(self.reason("gh pr merge 12", said=("merge it",)))
        self.trust("gate", "/origin$")  # this checkout's origin
        self.assertIsNone(self.reason("gh pr merge 12"))

    def test_waits_for_ci_a_pr_its_workflows_run_for_or_cant_be_read(self):
        self.workflow(WorkflowTriggers.CI_YML)
        prs = {32: ["apps/web/x.ts", "docs/x.md"],  # a code file runs CI
               # A PR that edits a workflow runs it: its own file isn't docs.
               33: {"docs/x.md": "x\n", ".github/workflows/ci.yml": WorkflowTriggers.CI_YML + "# edited\n"},
               # A workflow only the head adds runs too.
               34: {"docs/x.md": "x\n", ".github/workflows/lint.yml": "on: pull_request\n"}}
        for n, files in prs.items():
            with self.subTest(files=files):
                self.pr(n, files)
                self.scenario(prs={n: None})
                self.verify(n)
                self.assertIn(f"#{n} has no checks yet", self.reason(f"gh pr merge {n}", said=("merge it",)))
        unknown = [WorkflowTriggers.CI_YML.replace("  pull_request:", "  pull_request: &pr"),
                   WorkflowTriggers.CI_YML.replace("      - 'docs/**'", "\t- 'docs/**'"),
                   "on: {pull_request: {paths-ignore: ['docs/**']}}\n",
                   b"on:\n  pull_request:\n    paths-ignore: ['docs/\xff**']\n"]
        for n, text in enumerate(unknown, 40):
            with self.subTest(workflow=text):
                self.workflow(text)
                self.pr(n, ["docs/x.md"])
                self.scenario(prs={n: None})
                self.verify(n)
                self.assertIn(f"#{n} has no checks yet", self.reason(f"gh pr merge {n}", said=("merge it",)))

    def test_waits_for_ci_a_workflow_only_the_merge_commit_runs(self):
        # Codex review round 9: base and head each change ci.yml so that it skips the PR, but
        # pull_request runs the merge commit's ci.yml, which takes the base's branches and the
        # head's paths.
        ci = "on:\n  pull_request:\n    branches: [{}]\n    types: [opened]\n    paths: ['{}/**']\n"
        self.workflow(ci.format("release", "src"))
        head = self.pr(35, {"docs/x.md": "x\n", ".github/workflows/ci.yml": ci.format("release", "docs")})
        self.workflow(ci.format("main", "src"))
        self.heads[35] = head
        self.scenario(prs={35: None})
        self.verify(35)
        self.assertEqual(self.git("show", f"{self.merge(35)}:.github/workflows/ci.yml"), ci.format("main", "docs"))
        self.assertIn("#35 has no checks yet", self.reason("gh pr merge 35", said=("merge it",)))

    def test_waits_for_ci_a_workflow_only_the_default_branch_runs(self):
        # Codex review round 9: pull_request_target runs the default branch's workflows, so an
        # unfiltered one on main runs for a docs PR into release, whose own ci.yml skips it.
        self.workflow(WorkflowTriggers.CI_YML)
        self.git("branch", "release")
        self.git("push", "-q", "origin", "release")
        self.base = "release"
        self.workflow("on: pull_request_target\n", name="target.yml")
        self.main = self.git("rev-parse", "release").strip()  # PRs branch from release
        self.pr(36, ["docs/x.md"])
        self.scenario(prs={36: None})
        self.verify(36)
        self.assertIn("#36 has no checks yet", self.reason("gh pr merge 36", said=("merge it",)))

    def test_waits_for_ci_a_pr_without_a_merge_commit(self):
        # A conflicting PR has no merge commit, so what pull_request would run is unknown.
        self.workflow(WorkflowTriggers.CI_YML)
        self.pr(37, ["docs/x.md"])
        self.verify(37)
        self.scenario(prs={37: None})
        scenario = json.loads(pathlib.Path(self.env["FAKE_GH"]).read_text())
        scenario["repository"]["p37"]["potentialMergeCommit"] = None
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps(scenario))
        self.assertIn("#37 has no checks yet", self.reason("gh pr merge 37", said=("merge it",)))
        self.scenario(prs={37: None})
        self.git("push", "-q", "origin", ":refs/pull/37/merge")
        self.assertIn("#37 has no checks yet", self.reason("gh pr merge 37", said=("merge it",)))

    def test_reads_a_long_prompt_quickly(self):
        self.scenario(prs={12: None})
        self.verify(12)
        started = time.monotonic()
        self.assertIn("no CI on PRs", self.reason("gh pr merge 12", said=("lets " * 26 + "fix it",)))
        self.assertLess(time.monotonic() - started, 3)  # 9 s or more when the regex backtracks

    def test_matches_binary_changes_by_full_blob_ids(self):
        self.scenario(prs={20: "SUCCESS"})
        self.assertRegex(verdicts.diff(pathlib.Path(self.writer), self.main, self.pr(20)),
                         r"index [0-9a-f]{40}\.\.[0-9a-f]{40}")
        self.assertIn("#20 has no Done verdict", self.reason("gh pr merge 20"))
        self.verify(20)
        self.assertIsNone(self.reason("gh pr merge 20"))

    def land(self, files, branch="main"):
        """A commit on origin's branch after the PRs branched, as another PR merging; the
        scenario's baseRefOid stays at the old tip, as GitHub's does."""
        self.git("checkout", "-q", branch)
        for name in files:
            pathlib.Path(self.writer, name).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(self.writer, name).write_text(f"landed on {branch}\n")
        self.git("add", ".")
        self.git("commit", "-qm", f"land {files}")
        self.git("push", "-q", "origin", branch)
        self.git("checkout", "-q", "main")
        return self.git("rev-parse", branch).strip()

    def test_denies_a_pr_whose_base_changed_its_files_since_it_branched(self):
        # Two owner threads merge into one repo: PR A lands on main touching x.ts, and PR B,
        # branched before A and touching x.ts too, still shows green checks and a matching verdict.
        self.pr(12, ["x.ts"])
        self.pr(13, ["src/a.ts", "src/b.ts", "src/c.ts", "src/d.ts"])
        self.verify(12)
        self.verify(13)
        # A clone whose fetch refspec doesn't map main still compares against main's new tip.
        subprocess.run(["git", "config", "remote.origin.fetch", "+refs/heads/other:refs/remotes/origin/other"],
                       cwd=self.repo, check=True)
        tip = self.land(["x.ts", "src/a.ts", "src/b.ts", "src/c.ts", "src/d.ts"])
        self.scenario()
        self.assertEqual(self.reason("gh pr merge 12"), "Merge gate: #12's base `main` gained commits since it "
                         "branched that touch files it changes (`x.ts`): restack it onto `main` with "
                         f"`{STACK_SH} restack`, push, and wait for green. Fix what's listed and merge "
                         "again, or ask the user to merge it themselves. Don't route around the gate with `gh api` or "
                         "a push to the base branch.")
        self.assertEqual(subprocess.run(["git", "rev-parse", "origin/main"], cwd=self.repo, check=True,
                                        capture_output=True, text=True).stdout.strip(), tip)
        self.scenario(prs={13: "SUCCESS"})
        self.assertIn("(`src/a.ts`, `src/b.ts`, `src/c.ts`, and 1 more): restack it", self.reason("gh pr merge 13"))

    def test_denies_a_pr_that_renamed_a_file_its_base_then_changed(self):
        # With rename detection the PR changes only `g` and the base only `f`, so nothing overlaps.
        self.git("checkout", "-q", "--detach", self.main)
        self.git("mv", "f", "g")
        self.git("commit", "-qm", "12")
        self.git("push", "-q", "origin", "HEAD:refs/pull/12/head")
        self.heads[12] = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "main")
        self.verify(12)
        self.land(["f"])
        self.scenario()
        self.assertIn("files it changes (`f`): restack it", self.reason("gh pr merge 12"))

    def test_allows_a_pr_whose_base_moved_on_other_files(self):
        self.pr(12, ["x.ts"])
        self.verify(12)
        self.land(["y.ts"])
        self.scenario()
        self.assertIsNone(self.reason("gh pr merge 12"))

    def test_denies_only_the_stack_layer_whose_base_changed_its_files(self):
        # #13 is stacked on #12's branch, which gained a commit touching #13's file after #13
        # branched from it; #12 itself still sits on main's tip.
        old = self.pr(12, ["x.ts"])
        self.git("push", "-q", "origin", f"{old}:refs/heads/layer-12")
        self.git("checkout", "-q", "--detach", old)
        pathlib.Path(self.writer, "y.ts").write_text("13\n")
        self.git("add", ".")
        self.git("commit", "-qm", "13")
        self.git("push", "-q", "origin", "HEAD:refs/pull/13/head")
        self.heads[13] = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "-b", "layer-12", old)
        self.heads[12] = self.land(["y.ts"], branch="layer-12")
        self.git("push", "-q", "origin", f"{self.heads[12]}:refs/pull/12/head")
        self.verify(12)
        self.scenario(prs={12: "SUCCESS", 13: "SUCCESS"})
        scenario = json.loads(pathlib.Path(self.env["FAKE_GH"]).read_text())
        scenario["repository"]["p13"].update(baseRefName="layer-12", baseRefOid=old)
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps(scenario))
        reason = self.reason("gh stack merge")
        self.assertIn("#13's base `layer-12` gained commits since it branched that touch files it changes (`y.ts`)", reason)
        self.assertNotIn("#12's base", reason)

    def test_denies_an_unknown_stack_target_and_fails_closed(self):
        self.verify(12)
        self.scenario()
        self.assertIn("can't tell which PRs", self.reason("gh stack merge 7"))
        self.scenario(broken=True)
        self.assertIn("couldn't check the merge", self.reason("gh pr merge 12"))
        self.scenario()
        self.git("push", "-q", "origin", ":refs/pull/12/head")
        self.assertIn("couldn't check the merge", self.reason("gh pr merge 12"))  # fetch fails

    def test_denies_a_command_with_more_than_one_merge(self):
        # Nov 9, 2026: a dry run of `gh pr merge 39 --merge && gh pr merge 41 --merge` listed #39
        # alone, so #41 would have merged on #39's go with no verdict of its own.
        self.scenario(prs={12: "SUCCESS", 13: "SUCCESS"})
        self.verify(12)
        for command in ["gh pr merge 12 --merge && gh pr merge 13 --merge", "gh pr merge 12; gh stack merge",
                        "gh pr merge --help; gh pr merge 12 && gh pr merge 13"]:
            with self.subTest(command=command):
                self.assertIn("runs 2 merges", self.reason(command))
        self.assertIn("#13 has no Done verdict", self.reason("gh pr merge --help; gh stack merge"))
        self.assertIsNone(self.reason("gh pr merge 12 --disable-auto && gh pr merge 12"))
        self.assertEqual(self.dry_run("gh pr merge 12 && gh pr merge 13"),
                         (1, "- this command runs 2 merges and the gate checks one: run each merge as its own "
                             "command\nwould deny\n"))

    def test_ignores_other_commands(self):
        self.scenario(broken=True)
        for command in ["gh pr view 12", "gh pr merge --help", "gh pr merge 12 --disable-auto",
                        "echo 'gh pr merge 12'", "gh stack view", "git merge main"]:
            with self.subTest(command=command):
                self.assertIsNone(self.reason(command))

    # Replays of the 60 merge-gate denials from Oct 20 to 30, 2026 (suite-audit r2, section 6),
    # each command as recorded but for a `cd` into a checkout the fixture doesn't have.

    def dry_run(self, command, said=(), cwd=None, **env):
        args = [str(HOOKS / self.HOOK), "--dry-run", command]
        if said:
            args += ["--transcript", os.path.join(self.dir, "dry-run.jsonl")]
            with open(args[-1], "w") as transcript:
                transcript.writelines(json.dumps(claude_said(text)) + "\n" for text in said)
        env = {**{k: v for k, v in self.env.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")}, **env}
        result = subprocess.run(args, cwd=cwd or self.repo, env=env, capture_output=True, text=True)
        return result.returncode, result.stdout

    def test_dry_run_says_what_the_hook_would(self):
        self.scenario(prs={12: "SUCCESS", 13: "SUCCESS"})
        self.verify(12)
        self.assertEqual(self.dry_run("gh stack merge 13 --yes"),
                         (1, f"PRs: #12, #13 (from {os.path.realpath(self.repo)})\n- #13 has no Done verdict from a fresh "
                             "work-verifier for its current diff: run /verify-work\nwould deny\n"))
        self.assertIn("#13 has no Done verdict from a fresh work-verifier for its current diff: run /verify-work. "
                      "Fix what's listed", self.reason("gh stack merge 13 --yes"))
        self.verify(13)
        self.assertEqual(self.dry_run("gh stack merge 13 --yes"), (0, f"PRs: #12, #13 (from {os.path.realpath(self.repo)})\nwould pass\n"))
        self.assertEqual(self.dry_run("gh pr view 12"),
                         (0, "would pass: no `gh pr merge` or `gh stack merge` outside quotes for the gate to check\n"))

    def test_names_the_go_to_ask_for(self):
        # no-checks-needs-go, 31 denials: "#95 has no checks: this repo runs no CI on PRs, so
        # only the user can merge it; #96 has no checks: …", and no go to ask for.
        self.scenario(prs={95: None, 96: None})
        self.verify(95)
        self.verify(96)
        command = "gh stack merge 96 --yes 2>&1 | tail -8"
        why = "has no checks: this repo runs no CI on PRs, so it merges only when the user's latest prompt asks for the merge"
        self.assertEqual(self.reason(command), f"Merge gate: #95 {why}; #96 {why}; ask the user for \"merge #95 and #96\". "
                         "Fix what's listed and merge again, or ask the user to merge it themselves. Don't route "
                         "around the gate with `gh api` or a push to the base branch.")
        # The go it names is one.
        self.assertEqual(self.dry_run(command, said=("merge #95 and #96",)),
                         (0, f"PRs: #95, #96 (from {os.path.realpath(self.repo)})\n"
                             f"go: yes, from {self.dir}/dry-run.jsonl\nwould pass\n"))
        # In Codex, the session's rollout holds the prompt.
        session = "01a18cf3-a658-7800-b162-1dfb35904392"
        rollout = pathlib.Path(self.dir, "codex", "sessions", "2026", "10", "30", f"rollout-2026-10-30T14-15-40-{session}.jsonl")
        rollout.parent.mkdir(parents=True)
        rollout.write_text(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user",
                                       "content": [{"type": "input_text", "text": "merge #95 and #96"}]}}) + "\n")
        status, out = self.dry_run(command, CODEX_THREAD_ID=session, CODEX_HOME=os.path.join(self.dir, "codex"))
        self.assertEqual((status, out.splitlines()[1]), (0, f"go: yes, from {rollout}"))
        # In Claude Code, the session's transcript, under CLAUDE_CONFIG_DIR when that's set.
        transcript = pathlib.Path(self.dir, "claude", "projects", "-work", f"{session}.jsonl")
        transcript.parent.mkdir(parents=True)
        transcript.write_text(json.dumps(claude_said("merge #95 and #96")) + "\n")
        status, out = self.dry_run(command, CLAUDE_CODE_SESSION_ID=session, CLAUDE_CONFIG_DIR=os.path.join(self.dir, "claude"),
                                   CODEX_HOME=os.path.join(self.dir, "no-codex"))
        self.assertEqual((status, out.splitlines()[1]), (0, f"go: yes, from {transcript}"))
        self.assertIn("go: no, from no transcript; pass --transcript", self.dry_run(command)[1])

    def test_names_a_go_the_matcher_takes_for_a_long_stack(self):
        numbers = range(100, 141)  # their list passes merge_go's 200 characters
        self.scenario(prs={n: None for n in numbers})
        self.assertIn('ask the user for "merge the stack"', self.reason("gh stack merge 140 --yes"))
        self.assertTrue(merge_go.literal_go("merge the stack"))

    def test_points_a_misplaced_merge_at_stack_sh(self):
        self.scenario(prs={95: "SUCCESS", 96: "SUCCESS", 98: "SUCCESS"})
        where = (f"`{STACK_SH} where #97`, run in a checkout of the repo, prints the checkout to merge from and "
                 "the merge line to run there")
        # which-PRs-ambiguous, 12 denials.
        self.assertEqual(self.dry_run("for n in 95 96 98; do gh pr ready $n 2>&1 | tail -1; done && "
                                      "gh stack merge 97 --yes --merge 2>&1 | tail -12"),
                         (1, "- can't tell which PRs `gh stack merge 97` merges from this checkout's stack (open PRs: "
                             f"[95, 96, 98]); pass one of those PR numbers\n- {where}\nwould deny\n"))
        # stack-view-failed, 4 denials.
        self.scenario(stack_error='✗ branch "main" belongs to multiple stacks; checkout a non-trunk branch first')
        reason = self.reason("gh stack merge 122 --yes --squash 2>&1 | tail -8")
        self.assertIn("belongs to multiple stacks", reason)
        self.assertIn(f"`{STACK_SH} where #122`", reason)
        # no-such-file, 3 denials: a `cd` into a variable the gate can't expand, now denied before any fetch.
        self.scenario(prs={188: "SUCCESS"})
        reason = self.reason("d=$(ls -d ~/.t3/worktrees/skills/t3-1ef29bd5); cd $d && gh pr ready 188 && "
                             "gh stack merge 188 --yes --merge 2>&1 | tail -5")
        self.assertIn("runs `cd $d`, whose directory it can't read", reason)
        self.assertIn(f"`{STACK_SH} where #188`", reason)
        # fetch-failed, 4 denials: `gh pr merge -R` run outside any checkout.
        self.scenario(prs={139: "SUCCESS"})
        status, out = self.dry_run("gh pr merge 139 -R sam/skills --squash 2>&1 | tail -2", cwd=self.dir)
        self.assertEqual(status, 1)
        self.assertIn("not a git repository", out)
        self.assertIn(f"`{STACK_SH} where #139`", out)

    def test_reads_a_redirect_after_the_merge_as_a_redirect(self):
        # 5 of the 12 which-PRs denials named the PR `2>`: "can't tell which PRs `gh stack merge 2>` merges".
        self.scenario(prs={12: "SUCCESS", 13: "SUCCESS"})
        self.verify(12)
        self.verify(13)
        for command in ["gh stack merge --yes 2>&1 | tail -10; gh pr view 120 --json state",
                        "gh stack merge 2>&1 | tail -15", "gh stack merge --yes --squash 2>&1 | tail -15; echo \"exit=$?\"",
                        "gh stack merge >/tmp/merge.log", "gh pr merge 12 --merge 2> /dev/null"]:
            with self.subTest(command=command):
                self.assertIsNone(self.reason(command))

    def test_denies_a_stack_merge_of_a_pr_in_no_github_stack(self):
        # gh stack's own "✗ #176 is not a stack number or a stacked pull request", 17 failed
        # `gh stack merge` runs: GitHub links a stack only once it has two PRs.
        self.scenario()
        self.verify(12)
        scenario = json.loads(pathlib.Path(self.env["FAKE_GH"]).read_text())
        scenario["repository"]["p12"]["stack"] = None
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps(scenario))
        self.assertIn("#12 is in no stack on GitHub, so `gh stack merge` can't merge it: use `gh pr merge 12`",
                      self.reason("gh stack merge 12 --yes --merge"))
        self.assertIsNone(self.reason("gh pr merge 12 --merge"))
        scenario["repository"]["p12"]["stack"] = {"number": 30}
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps(scenario))
        self.assertIsNone(self.reason("gh stack merge 12 --yes"))

class MergeGo(unittest.TestCase):
    """merge_go.literal_go on real prompts: every prompt merge-gate denied for want of the
    user's go from Oct 11 to Oct 29, 2026, in Claude Code transcripts on the Mac and the
    linux, and the nearest misses among the 7,923 prompts typed there from Sep 23. Each
    source is the prompt's day and its transcript's session id, on the Mac unless it says
    linux. A picked option's text stands for the pick."""

    GOS = {
        "merge everything that is ready": "2026-10-11 f894bfc0",
        "just merge it for me": "2026-10-15 5ba1b6b8",
        "a + merge it when its ready": "2026-10-15 0dca46e9",
        "merge both, then `a`": "2026-10-15 0dca46e9",
        "merge it": "2026-10-16 d34c93a1",
        "merge them all": "2026-10-16 5ba1b6b8",
        "please merge whats ready now and merge the rest when they come back done": "2026-10-18 ffdb7d2d",
        "so lets merge this PR?": "2026-10-20 78a07cf7",
        "mark the PRs ready for review and merge them all": "2026-10-23 a313fe46",
        "merge dotfiles#1": "2026-10-24 a1127c68",
        "looks good, lets merge it all": "2026-10-24 b9a74657",
        "merge #92 through #112 into main": "2026-10-24 b9a74657",
        "can you just merge the ones that are ready to be merged now?": "2026-10-25 7f90013d",
        "lets merge it?": "2026-10-25 b9a74657",  # The user answered "a" to the agent's "merge it?" card
        "merge them the full list": "2026-10-25 7f90013d",
        "lets get the final PRs merged": "2026-10-26 7f90013d",
        "just merge it and then we can always change it back": "2026-10-28 ab1c3b07",
        "merge both stacks please": "2026-10-29 405ca507",
        # A picked option, then the same option with both repos named, in T3's suite-audit
        # coordinator thread 3cce05fc: the gate read neither as a go until "dotfiles #36" did.
        "merge #55 and dotfiles #36": "2026-11-10 T3 3cce05fc",
        "merge addystack #55 and dotfiles #36": "2026-11-10 T3 3cce05fc",
        # Merge requests the gate never judged, in repos with CI.
        "lets get all the current PRs for the redesign merged": "2026-10-03 a1cb0fac",
        "a + merge when ready": "2026-10-05 linux 43e516e7",
        "lets get it merged if its ready": "2026-10-06 linux 01a112df",
        "a, and please merge all the PRs that are done": "2026-10-24 a1127c68",
        "just merge the rest": "2026-10-24 8c894c98",
    }

    NOT_GOS = {
        # No merge in it.
        "/autopilot": "2026-10-15 face613c",
        "handle all this for me": "2026-10-22 dc694097",
        "do this for me go with recommended do one more": "2026-10-24 a1127c68",
        # A question about whether to merge, or an if-clause first. The user asks both ways with
        # "can we …?": the agent answered the Linux one with "Technically yes … I wouldn't".
        "can we make the stack ready for review and merge them?": "2026-10-11 6cd7383d",
        "is it ready to just get merged?": "2026-10-05 a3d0e42b",
        "can we merge the PRs without testing on phone?": "2026-10-04 linux 1616ddb2",
        "can we merge the PRs?": "2026-10-04 linux 1616ddb2, without its rest",
        "should we make the whole stack ready for review and merge it? is it ready?": "2026-10-10 56096bae",
        "the mac app seems fine for now, so lets just get the stack ready to merge?": "2026-10-18 d732f9e7",
        "should we merge #140 too?": "2026-10-26 ab1c3b07",
        "if the PR is ready to get merged then please merge it": "2026-10-04 c346eade",
        "if all these PRs add value and are safe to merge, then just do it": "2026-10-22 a313fe46",
        # Another step before the merge. "make … ready" can mean work, where "mark … ready" can't.
        "make the stack ready for review and merge them": "2026-10-11 6cd7383d, without its \"can we\"",
        "/verify-work and merge it when its ready": "2026-10-05 ce57c75a",
        "get #141 and #142 ready to merge and then merge them": "2026-10-10 3fcfecf8",
        "pick it up, rebase and merge it when its verified again": "2026-10-25 5ee80caf",
        "merge #92 through #112 into main without the device checks: verify the eight PRs, record Done, then merge "
        "both stacks": "2026-10-24 b9a74657",
        "merge dotfiles #2 once verify-work says it's done; the guard now keeps the verifier off fake homes":
            "2026-10-26 ab1c3b07",
        # Another step after it. "handle it" answered a reply whose next step was yadm work after the merge.
        "please just merge them for me and handle it": "2026-10-21 a1f35fad",
        "When done, open the pr, merge and release it": "2026-10-04 linux b8050106",
        "just merge and release, im the only user still": "2026-10-04 linux 1616ddb2",
        "lets get these improvements merged and synced before we do further improvements": "2026-10-09 7e06c164",
        "lets just fucking merge and deploy, we have no users anyways": "2026-10-10 3fcfecf8",
        "Can we just merge the current prs for the landing page and then continue with the mobile optimisation?":
            "2026-10-11 3fcfecf8",
        "merge #90 once its dev webhook test passes, then deploy production from the main checkout on main":
            "2026-10-27 c295ac97",
        "merge #90 and deploy production": "2026-10-27 c295ac97",
        "merge the whole stack, deploy production and make new builds for testflight": "2026-10-27 b237b2f6",
        "lets merge the whole stack and try it out": "2026-10-29 48f537dd",
        # A destination the gate doesn't check against the PR's base: only "into main" is read.
        "merge #92 through #112 into develop": "2026-10-24 b9a74657, with develop in place of main",
        # Talk about merging.
        "lets just let them merge it and then prepare my own follow-up with this": "2026-10-09 b20a0a92",
        "Lets just focus on merging all the ready stuff now": "2026-10-15 face613c",
    }

    def test_reads_each_real_merge_request_as_a_go(self):
        for prompt, source in self.GOS.items():
            with self.subTest(prompt=prompt, source=source):
                self.assertTrue(merge_go.literal_go(prompt))

    def test_reads_no_question_condition_or_other_step_as_a_go(self):
        for prompt, source in self.NOT_GOS.items():
            with self.subTest(prompt=prompt, source=source):
                self.assertFalse(merge_go.literal_go(prompt))

    def test_reads_a_word_before_a_pr_as_its_repo_unless_a_sentence_puts_it_there(self):
        for text in ["merge dotfiles #36", "merge sam/dotfiles #36", "merge sam/12306 #36", "merge 1password-codex-plugin #36", "merge Dotfiles #36 and #37", "merge #55, dotfiles #36",
                     "merge dotfiles #36 through #38", "merge dotfiles #36-#38", "a, and merge dotfiles #36",
                     "merge the stack of dotfiles #36"]:
            with self.subTest(text=text):
                self.assertTrue(merge_go.literal_go(text))
        # A time or a condition, a refusal, a noun that isn't a repo ("PR #36", or "stack #3",
        # a stack's number the gate can't place), a count, or the grammar's own words.
        for text in ["merge after #36", "merge before #36", "merge once #36", "merge except #36", "merge not #36",
                     "merge without #36", "merge only #36", "merge into #36", "merge with #36", "merge PR #36",
                     "merge prs #36", "merge stack #36", "merge 55 #36", "merge 10-14 #36", "merge both #55 and #36", "merge it #36",
                     "merge the #36", "merge and #36", "merge #55 and after #36", "merge #36 to after #38",
                     # verify-work's near misses, Nov 10, 2026: a refusal, a time, or another step.
                     "merge #36, skip #12", "merge #36 and dont #12", "merge #36 and rebase #12",
                     "merge #12 and fix #36", "merge excluding #36", "merge unless #36", "merge no #36",
                     "merge never #36", "merge #55, ignore #36", "merge #55 and drop #36", "merge later #36",
                     "merge maybe #36", "merge #55, hold #36", "merge #55 and revert #36", "merge #55 and push #36",
                     "merge #55 and deploy #36", "merge #55 and verify #36", "merge #55 and close #36",
                     "merge #55, release #36", "merge #55, review #36",
                     # push-gate's steps, Nov 24, 2026: "restack #6091" read as the repo restack.
                     "merge #55 and restack #36", "merge #55, sync #36", "merge #55 and submit #36",
                     "merge #55 and force-push #36"]:
            with self.subTest(text=text):
                self.assertFalse(merge_go.literal_go(text))

    def test_stays_fast_on_a_long_run_of_openers(self):
        started = time.monotonic()
        for text in ["please " * 28 + "x", "a, and " * 28 + "x", "merge it and " * 15 + "x", "lets " * 39 + "x"]:
            merge_go.literal_go(text)
        self.assertLess(time.monotonic() - started, 1)

class WorkflowTriggers(unittest.TestCase):
    # workout-tracker-jj's ci.yml, shortened.
    CI_YML = """name: CI

on:
  # Draft PRs skip CI; marking one ready runs it. A PR whose every file matches paths-ignore
  # skips it too. Pushes to main always run.
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
    paths-ignore:
      - '**/*.md'
      - '**/*.mdx'
      - 'docs/**'
      - 'plans/**'
      - 'research/**'
  push:
    branches: [main]

jobs:
  check:
    runs-on: [self-hosted, linux]
    steps:
      - run: pnpm test
"""

    def test_reads_each_form_of_on(self):
        for text, expected in {
            self.CI_YML: [{"types": ["opened", "synchronize", "reopened", "ready_for_review"],
                      "paths-ignore": ["**/*.md", "**/*.mdx", "docs/**", "plans/**", "research/**"]}],
            "on: pull_request\n": [{}],
            "on: pull_request  # always\n": [{}],
            '"on": [push, pull_request_target]\n': [{}],
            "'on':\n  - push\n  - pull_request\n": [{}],
            "---\ntrue:\n  pull_request:\n  push:\n": [{}],
            "on:\n  pull_request: ~\n  pull_request_target: {}\n": [{}, {}],
            "on:\n  pull_request:\n    branches:\n    - main\n\n    paths:\n# a column-0 comment\n"
            "      - \"src/**\"  # code\n      - 'it''s'\n": [{"branches": ["main"], "paths": ["src/**", "it's"]}],
            "on:\n  pull_request:\n  pull_request_target:\n    branches: [main, 'release/**']\n":
                [{}, {"branches": ["main", "release/**"]}],
            "on: push\n": [],
            "on:\n  workflow_call:\n    inputs:\n      x: {type: string, default: '*'}\n": [],
            # Only column 0 starts a top-level key, so a block scalar's `on:` is text.
            "env:\n  A: |\n    on: pull_request\non: push\n": [],
            "on: pull_request\njobs:\n  x:\n    run: echo '\t'\n": [{}],  # a tab outside `on:`
        }.items():
            with self.subTest(text=text):
                self.assertEqual(workflow_triggers.triggers(text), expected)

    def test_an_on_it_cant_follow_is_unknown_and_runs(self):
        for text in [
            "on:\n  pull_request: &pr\n    paths: [a]\n",
            "on:\n  pull_request:\n    paths: *p\n",
            "on:\n  pull_request:\n    paths:\n      - *p\n",
            "on:\n  pull_request:\n    <<: *p\n",
            "on:\n  pull_request:\n\tpaths: [a]\n",
            "on:\n  pull_request:\n    paths: [a]\t\n",
            "on:\n  pull_request:\n    paths: |\n      a\n",
            "on:\n  pull_request:\n    paths: [a,\n      b]\n",
            "on:\n  pull_request:\n    tags: [v1]\n",
            "on:\n  pull_request:\n    paths: docs/**\n",
            "on:\n  pull_request:\n    paths: []\n",
            "on:\n  pull_request:\n    paths:\n",
            "on:\n  pull_request:\n    paths: [a]\n    paths-ignore: [b]\n",
            'on:\n  pull_request:\n    paths: ["a\\"b"]\n',
            "on:\n  pull_request: {paths: [a]}\n",
            "on: {pull_request: {}}\n",
            "on:\n    pull_request:\n  push:\n",
            "on:\n- pull_request\n",
            "on:\n  pull_request:\n  pull_request:\n",
            "on: push\non: pull_request\n",
            "on: null\n",
            "on:\n",
            "name: x\n",
            "on: push\n---\nx: 1\n",
            "name: 'a\nb'\non: push\n",
        ]:
            with self.subTest(text=text):
                with self.assertRaises(workflow_triggers.Unknown):
                    workflow_triggers.triggers(text)
                self.assertTrue(workflow_triggers.runs(text, "main", ["docs/x.md"]))

    def test_globs_match_as_githubs_cheat_sheet_says(self):
        for pattern, matches, misses in [
            ("**/*.md", ["README.md", "a/b/c.md"], ["a.mdx", "a/b.md/c"]),  # root files too, on GitHub
            ("*.md", ["README.md"], ["docs/a.md"]),
            ("docs/**", ["docs/a", "docs/a/b.md"], ["docsx/a", "a/docs/b"]),
            ("docs/**/*.md", ["docs/README.md", "docs/a/b.md"], ["docs/a.ts"]),
            ("**/docs/**", ["docs/a", "x/docs/a/b"], ["xdocs/a"]),
            ("**.js", ["a.js", "a/b.js"], ["a.jsx"]),
            ("*.jsx?", ["a.js", "a.jsx"], ["a.jsxx", "a/b.js"]),
            ("v[12].[0-9]+.[0-9]+", ["v1.10.3", "v2.0.0"], ["v3.1.1", "v1.x.1", "v1..1"]),
            ("feature/*", ["feature/a"], ["feature/a/b"]),
            ("a!b(c)", ["a!b(c)"], ["ab"]),
        ]:
            with self.subTest(pattern=pattern):
                regex = workflow_triggers.glob(pattern)
                self.assertEqual([name for name in matches + misses if regex.fullmatch(name)], matches)
        for pattern in ["a\\*", "{a,b}", "?a", "a*?", "**+", "[!a]", "[z-a]", "[a", "a]", "[.]", "/docs", "./docs", "docs/", ""]:
            with self.subTest(pattern=pattern), self.assertRaises(workflow_triggers.Unknown):
                workflow_triggers.glob(pattern)

    def test_runs_by_its_branch_and_path_filters(self):
        on = lambda filters: "on:\n  pull_request:\n" + "".join(f"    {key}: {value}\n" for key, value in filters.items())
        runs = lambda filters, files, base="main": workflow_triggers.runs(on(filters), base, files)
        docs = ["AGENTS.md", "docs/x.md"]
        self.assertFalse(workflow_triggers.runs(self.CI_YML, "main", docs))
        self.assertFalse(workflow_triggers.runs(self.CI_YML, "main", ["README.md"]))
        self.assertTrue(workflow_triggers.runs(self.CI_YML, "main", docs + ["apps/web/x.ts"]))
        self.assertTrue(workflow_triggers.runs(self.CI_YML, "main", [f"docs/{i}.md" for i in range(301)]))
        self.assertFalse(workflow_triggers.runs(self.CI_YML, "main", [f"docs/{i}.md" for i in range(300)]))
        self.assertTrue(workflow_triggers.runs(self.CI_YML, "main", []))
        # paths: any file the last matching pattern includes, `!` excluding.
        self.assertFalse(runs({"paths": "['**', '!**/*.md']"}, docs))
        self.assertTrue(runs({"paths": "['**', '!**/*.md']"}, ["docs/x.md", "src/a.ts"]))
        self.assertTrue(runs({"paths": "['**/*.md', '!README.md', 'README*']"}, ["README.md"]))
        self.assertFalse(runs({"paths": "['**/*.md', '!README.md']"}, ["README.md"]))
        self.assertTrue(runs({"paths": "['**/*.md', '!README.md']"}, ["README.md", "docs/x.md"]))
        self.assertTrue(runs({"paths": "['src/**', '{a,b}']"}, docs))  # a pattern it can't read
        self.assertTrue(runs({"paths-ignore": "['**/*.md', '!README.md']"}, docs))
        self.assertTrue(runs({"paths-ignore": "['docs/**', '\\\\x']"}, docs))
        # branches: the PR's base branch.
        self.assertFalse(runs({"branches": "['release/**']"}, ["src/a.ts"]))
        self.assertTrue(runs({"branches": "['release/**']"}, ["src/a.ts"], base="release/1.0"))
        self.assertFalse(runs({"branches": "['**', '!main']"}, ["src/a.ts"]))
        self.assertFalse(runs({"branches-ignore": "[main]"}, ["src/a.ts"]))
        self.assertTrue(runs({"branches-ignore": "[main]"}, ["src/a.ts"], base="dev"))
        self.assertFalse(runs({"branches": "[main]", "paths-ignore": "['docs/**', '**/*.md']"}, docs))
        self.assertFalse(runs({"types": "[ready_for_review]", "paths-ignore": "['**/*.md', 'docs/**']"}, docs))


class Verdicts(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.repo = os.path.join(self.dir, "repo")
        self.git("init", "-q", self.repo, cwd=self.dir)
        for text in ["a\n", "b\n"]:
            pathlib.Path(self.repo, "f").write_text(text)
            self.git("add", "f")
            self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", text)
        self.base, self.head = self.git("rev-parse", "HEAD~1").strip(), self.git("rev-parse", "HEAD").strip()

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, check=True, capture_output=True,
                              text=True).stdout

    def record(self, context=None, head=None, **verdict):
        if context is None:
            context = json.dumps({"session_id": "s", "agent_id": "a1", "agent_type": "work-verifier"})
        return verdicts.record(pathlib.Path(self.repo), verdicts.ReviewTarget(self.base, head or self.head), context,
                               **verdict)

    def test_records_only_from_the_verifier_at_the_clean_reviewed_head(self):
        for context in ["", json.dumps({"session_id": "s", "agent_id": "a1", "agent_type": "general-purpose"})]:
            with self.subTest(context=context), self.assertRaisesRegex(verdicts.VerdictError, "only a fresh"):
                self.record(context)
        with self.assertRaisesRegex(verdicts.VerdictError, "isn't the reviewed head"):
            self.record(head=self.base)
        pathlib.Path(self.repo, "f").write_text("dirty\n")
        with self.assertRaisesRegex(verdicts.VerdictError, "uncommitted"):
            self.record()
        self.git("checkout", "-q", "f")
        receipt = self.record()
        diff = self.git("diff", f"{self.base}...{self.head}")
        self.assertEqual(verdicts.find_done(pathlib.Path(self.repo), diff), receipt)
        self.assertIsNone(verdicts.find_done(pathlib.Path(self.repo), diff.replace("+b", "+c")))
        self.assertIsNone(verdicts.find_done(pathlib.Path(self.repo), diff.replace("+b", "+ b")))  # re-indent
        self.git("checkout", "-q", "-b", "crlf", self.base)
        pathlib.Path(self.repo, "f").write_bytes(b"b\r\n")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "crlf")
        crlf = verdicts._git(pathlib.Path(self.repo), "diff", f"{self.base}...crlf")
        self.assertIsNone(verdicts.find_done(pathlib.Path(self.repo), crlf))  # only line endings changed
        worktree = os.path.join(self.dir, "wt")
        self.git("worktree", "add", "-q", "--detach", worktree)
        self.assertEqual(verdicts.find_done(pathlib.Path(worktree), diff), receipt)

    def status(self, base, head):
        return subprocess.run(["python3", str(HOOKS / "verdicts.py"), "status", base, head], cwd=self.repo,
                              capture_output=True, text=True)

    def test_status_prints_the_patch_id_and_whether_it_is_done(self):
        patch_id = verdicts._patch_id(pathlib.Path(self.repo), verdicts.diff(pathlib.Path(self.repo), self.base, self.head))
        before = self.status(self.base, self.head)
        self.assertEqual((before.returncode, before.stdout),
                         (0, f"patch-id: {patch_id}\ndone: no\nsize: +1 −1 in 1 file\nreview: none\n"))
        self.record()
        after = self.status(self.base, "HEAD")
        self.assertEqual(after.returncode, 0)
        self.assertRegex(after.stdout, rf"^patch-id: {patch_id}\ndone: yes \(.*a1.*\)\nsize: .*\nreview: none\n$")
        self.assertNotEqual(self.status(self.base, "nope").returncode, 0)

    def store(self):
        return pathlib.Path(self.repo, ".git", "verify-work", "verdicts.tsv")

    def commit(self, files):
        for name, text in files.items():
            path = pathlib.Path(self.repo, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text) if isinstance(text, bytes) else path.write_text(text)
            self.git("add", name)
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")
        self.head = self.git("rev-parse", "HEAD").strip()

    def test_size_leaves_out_lockfiles_vendored_generated_and_binary_files(self):
        self.commit({".gitattributes": "api/*.ts linguist-generated\n", "f": "b\nc\n", "web/bun.lock": "x\ny\n", "vendor/lib.js": "v\n", "app.min.js": "m\n",
                     "api/client.ts": "g\n", "logo.png": b"\x89PNG\x00\x01", "src/a b.ts": "s\n"})
        repo = pathlib.Path(self.repo)
        why = {path: why for _, _, path, why in verdicts.left_out(
            repo, self.git("diff", "--numstat", "-z", "--no-renames", f"{self.base}...{self.head}").encode())}
        self.assertEqual(why, {"f": "", "web/bun.lock": "lockfile", "vendor/lib.js": "vendored", "app.min.js": "generated",
                               "api/client.ts": "generated", "logo.png": "binary", "src/a b.ts": "",
                               ".gitattributes": ""})
        self.assertEqual(verdicts.size(repo, self.base, self.head),
                         "+4 −1 in 3 files, leaving out +5 −0 in 5 files: web/bun.lock (lockfile, +2 −0); "
                         "api/client.ts (generated, +1 −0); app.min.js (generated, +1 −0); and 2 more")

    def test_size_reads_attributes_at_the_head_counts_a_move_as_its_edits_and_names_the_largest_left_out(self):
        self.commit({"old.txt": "".join(f"{n}\n" for n in range(100)), "z.generated.ts": "z\n" * 1000,
                     **{f"{n}.min.js": "m\n" for n in "abc"}})
        base = self.head
        self.git("mv", "old.txt", "new.txt")
        self.commit({".gitattributes": "api/*.ts linguist-generated\n", "api/client.ts": "g\n" * 100, "f": "d\n"})
        self.git("checkout", "-q", base)  # the checkout has neither the attributes nor the move
        self.base = base
        self.assertEqual(verdicts.size(pathlib.Path(self.repo), base, self.git("rev-parse", "@{-1}").strip()),
                         "+2 −1 in 3 files, leaving out +100 −0 in 1 file: api/client.ts (generated, +100 −0)")
        first = self.git("rev-list", "--max-parents=0", "HEAD").strip()
        self.assertTrue(verdicts.size(pathlib.Path(self.repo), first, base).endswith(
            "leaving out +1003 −0 in 4 files: z.generated.ts (generated, +1000 −0); a.min.js (generated, +1 −0); "
            "b.min.js (generated, +1 −0); and 1 more"))

    def test_size_is_the_same_from_a_subfolder_and_reads_a_deleted_files_attributes_at_the_base(self):
        self.commit({".gitattributes": "/copy.txt linguist-generated\n", "copy.txt": "g\n" * 100,
                     "dir/a.txt": "a\n"})
        base = self.head
        pathlib.Path(self.repo, ".gitattributes").write_text("dir/*.gen linguist-generated\n")
        self.git("rm", "-q", "copy.txt")
        self.commit({".gitattributes": "dir/*.gen linguist-generated\n", "dir/b.gen": "b\n" * 5})
        want = ("+1 −1 in 1 file, leaving out +5 −100 in 2 files: copy.txt (generated, +0 −100); "
                "dir/b.gen (generated, +5 −0)")
        for folder in [self.repo, os.path.join(self.repo, "dir")]:
            with self.subTest(folder=folder):
                self.assertEqual(verdicts.size(pathlib.Path(folder), base, self.head), want)

    @unittest.skipIf(tuple(map(int, re.findall(r"\d+", subprocess.run(["git", "--version"], capture_output=True,
                                                                     text=True).stdout)[:2])) < (2, 42),
                     "GIT_ATTR_SOURCE needs git 2.42")
    def test_a_diff_attribute_in_the_checkout_doesnt_hide_a_text_edit(self):
        self.commit({".gitattributes": "*.txt -diff\n", "file.txt": "before\n"})
        base = self.head
        self.git("rm", "-q", ".gitattributes")
        self.commit({"file.txt": "after\n"})
        self.git("checkout", "-q", base)
        self.assertEqual(verdicts.size(pathlib.Path(self.repo), base, self.head), "+1 −2 in 2 files")

    def test_size_reads_the_old_side_at_the_merge_base_and_ignores_diff_relative(self):
        self.commit({".gitattributes": "/copy.txt linguist-generated\n", "copy.txt": "g\n" * 100, "dir/a": "a\n"})
        fork = self.head
        self.git("checkout", "-q", "-b", "feature")
        pathlib.Path(self.repo, ".gitattributes").write_text("")
        self.git("rm", "-q", "copy.txt")
        self.commit({".gitattributes": ""})
        feature = self.head
        self.git("checkout", "-q", fork)
        self.commit({".gitattributes": "", "dir/a": "a\nb\n"})  # the target branch drops the rule too
        target = self.head
        self.git("config", "diff.relative", "true")
        want = "+0 −1 in 1 file, leaving out +0 −100 in 1 file: copy.txt (generated, +0 −100)"
        for folder in [self.repo, os.path.join(self.repo, "dir")]:
            with self.subTest(folder=folder):
                self.assertEqual(verdicts.size(pathlib.Path(folder), target, feature), want)

    def test_numstat_writes_why_first_for_packet_sh(self):
        self.commit({"yarn.lock": "x\n"})
        numstat = self.git("diff", "--numstat", "-z", "--no-renames", f"{self.base}...{self.head}")
        for source in [[], ["--source", self.head]]:
            out = subprocess.run(["python3", str(HOOKS / "verdicts.py"), "numstat", *source], cwd=self.repo,
                                 input=numstat, capture_output=True, text=True, check=True).stdout
            self.assertEqual(out, "kept\t1\t1\tf\0lockfile\t1\t0\tyarn.lock\0")

    def review(self, *args):
        return subprocess.run(["python3", str(HOOKS / "verdicts.py"), "review", self.base, self.head, *args],
                              cwd=self.repo, capture_output=True, text=True)

    def test_a_review_records_its_rating_and_status_shows_it(self):
        reviewed = lambda: self.status(self.base, self.head).stdout.splitlines()[3]
        self.assertEqual(self.review("--rounds", "1").returncode, 0)
        self.assertEqual(reviewed(), "review: 1 round, no rating")
        out = self.review("--rounds", "2", "--rating", "7", "--reason", "one retry path has no test")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual({key: json.loads(out.stdout)[key] for key in ("rounds", "rating", "reason")},
                         {"rounds": 2, "rating": 7, "reason": "one retry path has no test"})
        self.assertEqual(json.loads(self.store().read_text().splitlines()[-1].split("\t")[8]),
                         {"rounds": 2, "rating": 7, "reason": "one retry path has no test"})
        self.assertEqual(reviewed(), "review: 2 rounds, rated 7/10: one retry path has no test")
        self.assertEqual(self.review("--skip", "Sam: ship it").returncode, 0)
        self.assertEqual(reviewed(), "review: skipped: Sam: ship it")

    def test_a_rating_needs_rounds_a_reason_and_1_to_10(self):
        for args in [("--rounds", "1", "--rating", "11", "--reason", "x"), ("--rounds", "1", "--rating", "0", "--reason", "x"),
                     ("--rounds", "1", "--rating", "7"), ("--rounds", "1", "--reason", "x"),
                     ("--skip", "s", "--rating", "7", "--reason", "x")]:
            with self.subTest(args=args):
                self.assertEqual(self.review(*args).returncode, 1)
        self.assertFalse(self.store().exists())

    def test_an_unreadable_review_shows_in_status_without_failing_it(self):
        self.store().parent.mkdir(parents=True)
        for body in ['{"rounds":1,"rating":7}', '{"rounds":1,"rating":12,"reason":"x"}', '{"rounds":1,"reason":"x"}']:
            with self.subTest(body=body):
                self.store().write_text("\t".join([self.patch_id(), self.head, self.base, "at", "v3", "s", "-",
                                                     "review-loop", body]) + "\n")
                status = self.status(self.base, self.head)
                self.assertEqual(status.returncode, 0)
                self.assertIn("review: unreadable: can't read the review result", status.stdout)
                with self.assertRaises(verdicts.VerdictError):
                    verdicts.find_review(pathlib.Path(self.repo),
                                         verdicts.diff(pathlib.Path(self.repo), self.base, self.head))


    def patch_id(self):
        return verdicts._patch_id(pathlib.Path(self.repo), verdicts.diff(pathlib.Path(self.repo), self.base, self.head))

    def cli_record(self, *args):
        context = json.dumps({"session_id": "s", "agent_id": "a1", "agent_type": "work-verifier"})
        return subprocess.run(["python3", str(HOOKS / "verdicts.py"), "record", self.base, self.head, *args],
                              cwd=self.repo, capture_output=True, text=True, env={**os.environ, "VERIFY_WORK_HOOK_CONTEXT": context})

    def test_records_not_done_with_its_findings_and_evidence(self):
        out = self.cli_record("--verdict", "not-done", "--evidence", "deploy=https://x.example/v?a=1",
                              "--evidence", "deploy=not-run:b\tc", "--evidence", "ui=not-run:no simulator",
                              "--finding", "retry skips publish\n`export.ts:12`")
        self.assertEqual(out.returncode, 0, out.stderr)
        receipt = json.loads(out.stdout)
        verdict = {"verdict": "not-done", "evidence": {"deploy": ["https://x.example/v?a=1", "not-run:b\tc"],
                                                       "ui": ["not-run:no simulator"]},
                   "findings": ["retry skips publish\n`export.ts:12`"], "required": {}}
        self.assertEqual({key: receipt[key] for key in verdict}, verdict)
        row = self.store().read_text().splitlines()[-1].split("\t")
        self.assertEqual(row[:3] + row[4:8], [self.patch_id(), self.head, self.base, "v3", "s", "a1", "work-verifier"])
        branch = self.git("symbolic-ref", "--short", "HEAD").strip()
        self.assertEqual((len(row), json.loads(row[8])), (9, {**verdict, "branch": branch}))
        self.assertIsNone(verdicts.find_done(pathlib.Path(self.repo), verdicts.diff(pathlib.Path(self.repo), self.base, self.head)))
        status = self.status(self.base, self.head)
        self.assertEqual(status.returncode, 0)
        self.assertTrue(status.stdout.startswith(f"patch-id: {self.patch_id()}\ndone: no\nsize: "))

    def test_refuses_a_gap_without_a_finding_or_a_bad_evidence_kind(self):
        for verdict in ["not-done", "not-verified"]:
            with self.subTest(verdict=verdict), self.assertRaisesRegex(verdicts.VerdictError, "at least one finding"):
                self.record(verdict=verdict)
        with self.assertRaisesRegex(verdicts.VerdictError, "empty finding"):
            self.record(verdict="not-done", findings=[" "])
        with self.assertRaisesRegex(verdicts.VerdictError, "evidence kind"):
            self.record(evidence={"Real run": ["x"]})
        with self.assertRaisesRegex(verdicts.VerdictError, "verdict"):
            self.record(verdict="maybe")
        self.assertEqual(self.cli_record("--verdict", "not-verified").returncode, 1)
        self.assertEqual(self.cli_record("--verdict", "maybe").returncode, 2)
        self.assertEqual(self.cli_record("--evidence", "no-equals").returncode, 2)
        self.assertFalse(self.store().exists())

    def test_the_latest_verdict_for_a_diff_decides(self):
        done = lambda: self.status(self.base, self.head).stdout.splitlines()[1]
        self.record(verdict="not-done", findings=["1"])
        receipt = self.record()
        self.assertEqual(done(), f"done: yes ({receipt.recorded_at}, head {self.head[:12]}, a1)")
        self.record(verdict="not-verified", findings=["no device here"])
        self.assertEqual(done(), "done: no")
        self.assertIsNone(verdicts.find_done(pathlib.Path(self.repo), verdicts.diff(pathlib.Path(self.repo), self.base, self.head)))

    def test_a_legacy_done_row_still_counts(self):
        self.record(verdict="not-done", findings=["1"])
        with self.store().open("a") as f:
            f.write("\t".join([self.patch_id(), self.head, self.base, "now", "v2", "s", "a0", "work-verifier"]) + "\n")
        receipt = verdicts.find_done(pathlib.Path(self.repo), verdicts.diff(pathlib.Path(self.repo), self.base, self.head))
        self.assertEqual((receipt.verdict, receipt.verifier.agent_id, receipt.findings), ("done", "a0", []))

    def test_an_old_reader_ignores_every_new_row(self):
        """main's 8-column v2 predicate, as a neighbor on old code still reads the store."""
        old = lambda patch_id: [row for row in (line.split("\t") for line in self.store().read_text().splitlines())
                                if len(row) == 8 and row[0] == patch_id and row[4] == "v2" and row[7] == "work-verifier"]
        self.record(verdict="not-done", findings=["1"])
        self.record()
        self.assertEqual(old(self.patch_id()), [])

    def test_a_broken_row_fails_closed_only_for_its_own_diff(self):
        diff = verdicts.diff(pathlib.Path(self.repo), self.base, self.head)
        receipt = self.record()
        with self.store().open("a") as f:
            f.write("\t".join(["other", self.head, self.base, "now", "v3", "s", "a2", "work-verifier", "{"]) + "\n")
        self.assertEqual(verdicts.find_done(pathlib.Path(self.repo), diff), receipt)
        for broken in ["{", "[]", '{"verdict": "done", "evidence": [], "findings": []}', '{"verdict": "yes"}',
                       '{"verdict": "done", "evidence": {"test": "a"}, "findings": []}',
                       '{"verdict": "done", "evidence": {}, "findings": "a"}']:
            with self.subTest(json=broken):
                with self.store().open("a") as f:
                    f.write("\t".join([self.patch_id(), self.head, self.base, "now", "v3", "s", "a2", "work-verifier",
                                       broken]) + "\n")
                with self.assertRaisesRegex(verdicts.VerdictError, "can't read the verdict"):
                    verdicts.find_done(pathlib.Path(self.repo), diff)
                self.assertEqual(self.status(self.base, self.head).returncode, 1)

    def last(self, branch):
        return subprocess.run(["python3", str(HOOKS / "verdicts.py"), "last", branch], cwd=self.repo,
                              capture_output=True, text=True)

    def test_last_reads_the_newest_verdict_on_the_branch(self):
        branch = self.git("symbolic-ref", "--short", "HEAD").strip()
        self.assertEqual((self.last(branch).returncode, self.last(branch).stdout), (0, "last: none\n"))
        self.record(verdict="not-done", findings=["retry skips publish"])
        receipt = self.record(verdict="not-verified", findings=["no device here"])
        self.git("checkout", "-q", "-b", "other")
        self.record(verdict="not-done", findings=["on other"])
        out = self.last(branch)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), json.loads(json.dumps(dataclasses.asdict(receipt))))
        self.assertEqual(json.loads(self.last("other").stdout)["findings"], ["on other"])
        self.assertEqual(self.last("nope").stdout, "last: none\n")

    def test_last_names_the_branch_when_a_tag_shares_its_name(self):
        branch = self.git("symbolic-ref", "--short", "HEAD").strip()
        self.record()
        self.git("tag", branch)  # `symbolic-ref --short` now says heads/<branch>
        self.record(verdict="not-done", findings=["missed failure"])
        self.assertEqual(json.loads(self.last(branch).stdout)["findings"], ["missed failure"])

    def test_last_ignores_a_verdict_without_a_branch(self):
        branch = self.git("symbolic-ref", "--short", "HEAD").strip()
        self.git("checkout", "-q", "--detach")
        self.record(verdict="not-done", findings=["detached"])
        row = self.store().read_text().splitlines()[-1].split("\t")
        self.assertNotIn("branch", json.loads(row[8]))
        with self.store().open("a") as f:  # a row recorded before verdicts named their branch
            f.write("\t".join([self.patch_id(), self.head, self.base, "now", "v3", "s", "a9", "work-verifier",
                               '{"verdict":"done","evidence":{},"findings":[]}']) + "\n")
        self.assertEqual(self.last(branch).stdout, "last: none\n")
        self.assertEqual(self.last("").stdout, "last: none\n")

    def test_last_reads_an_unreadable_store_as_no_verdict(self):
        branch = self.git("symbolic-ref", "--short", "HEAD").strip()
        self.record(verdict="not-done", findings=["1"])
        with self.store().open("a") as f:  # a broken row is skipped, not fatal
            f.write("\t".join([self.patch_id(), self.head, self.base, "now", "v3", "s", "a2", "work-verifier",
                               '{"verdict":"maybe","branch":"%s"}' % branch]) + "\n")
        self.assertEqual(json.loads(self.last(branch).stdout)["findings"], ["1"])
        with self.store().open("ab") as f:
            f.write(b"\xff\n")
        self.assertEqual((self.last(branch).returncode, self.last(branch).stdout), (0, "last: none\n"))
        self.store().unlink()
        self.store().mkdir()
        self.assertEqual((self.last(branch).returncode, self.last(branch).stdout), (0, "last: none\n"))
        self.assertIsNone(verdicts.last(pathlib.Path(self.dir), branch))  # not a git repo

    def known(self, branch, base, head):
        out = subprocess.run(["python3", str(HOOKS / "verdicts.py"), "last", branch, base, head], cwd=self.repo,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout).get("known")

    def test_last_knows_a_not_verified_waits_on_its_real_run(self):
        branch = self.git("symbolic-ref", "--short", "HEAD").strip()
        self.record(verdict="not-verified", findings=["1 · the iOS run needs a device"])
        self.assertEqual(self.known(branch, self.base, self.head), "not verified until it runs: 1 · the iOS run needs a device")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--amend", "-m", "reworded")
        self.assertIn("needs a device", self.known(branch, self.base, self.git("rev-parse", "HEAD").strip()))
        # A commit since changes the diff, so its re-check reads that code, and still owes the run.
        self.assertIsNone(self.known(branch, self.base, self.commit_change("c\n")))

    def test_last_knows_a_fix_marked_finding_without_a_commit(self):
        branch = self.git("symbolic-ref", "--short", "HEAD").strip()
        fix, skip = "1 · Blocker · retry skips publish · `export.ts:12` → fix", "2 · Cleanup · x → skip: out of scope"
        self.record(verdict="not-done", findings=[fix, skip])
        self.assertEqual(self.known(branch, self.base, self.head), f"same diff as {self.head[:12]}, so still open: {fix}")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--amend", "-m", "reworded")
        head = self.git("rev-parse", "HEAD").strip()  # the same diff on a new commit, as after a restack
        self.assertNotEqual(head, self.head)
        self.assertIn("so still open", self.known(branch, self.base, head))

    def test_last_leaves_a_recheck_that_can_find_something_new(self):
        branch = self.git("symbolic-ref", "--short", "HEAD").strip()
        self.record(verdict="not-done", findings=["1 · Blocker · retry skips publish → fix"])
        head = self.commit_change("c\n")
        self.assertIsNone(self.known(branch, self.base, head))  # a commit since: the fix may be in it
        self.assertIsNone(self.known(branch, self.base, "nope"))  # a diff that won't read runs the re-check
        self.git("reset", "-q", "--hard", self.head)
        self.git("checkout", "-q", "-b", "parent", self.base)  # the fix lands in the parent layer
        pathlib.Path(self.repo, "g").write_text("fix\n")
        self.git("add", "g")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "fix")
        parent = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", branch)
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "rebase", "-q", "parent")
        restacked = self.git("rev-parse", "HEAD").strip()
        self.assertEqual(verdicts.diff(pathlib.Path(self.repo), parent, restacked),
                         verdicts.diff(pathlib.Path(self.repo), self.base, self.head))  # the same diff
        self.assertIsNone(self.known(branch, parent, restacked))  # on a new merge base, which may hold the fix
        self.git("reset", "-q", "--hard", self.head)
        for findings in (["2 · Cleanup · x → follow-up"], ["3 · Cleanup · x → fixed upstream"]):
            self.record(verdict="not-done", findings=findings)
            self.assertIsNone(self.known(branch, self.base, self.head), findings)  # nothing marked fix
        self.record()
        self.assertIn("Done stands", self.known(branch, self.base, self.head))
        self.commit_change("c\n")  # a commit since changes the diff, so the re-check reads it
        self.assertNotIn("known", json.loads(self.last(branch).stdout))
        usage = subprocess.run(["python3", str(HOOKS / "verdicts.py"), "last", branch, self.base], cwd=self.repo,
                               capture_output=True, text=True)
        self.assertEqual(usage.returncode, 2)

    def test_last_keeps_a_done_across_a_rebase_that_leaves_the_diff_the_same(self):
        branch = self.git("symbolic-ref", "--short", "HEAD").strip()
        self.record()
        self.git("checkout", "-q", "-b", "parent", self.base)  # the base gains an unrelated commit
        pathlib.Path(self.repo, "g").write_text("g\n")
        self.git("add", "g")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "g")
        parent = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", branch)
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "rebase", "-q", "parent")
        head = self.git("rev-parse", "HEAD").strip()
        self.assertNotEqual(head, self.head)
        self.assertEqual(self.known(branch, parent, head), f"same diff as {self.head[:12]}, Done stands; rerun the "
                         "layer's checks and a trial merge at the new head")
        self.assertIsNotNone(verdicts.find_done(pathlib.Path(self.repo), verdicts.diff(pathlib.Path(self.repo), parent,
                                                                                       head)))  # the gate keeps it too
        self.assertIsNone(self.known(branch, parent, "nope"))  # a diff that won't read runs the re-check

    def test_a_kept_done_still_fails_the_checks_a_new_base_breaks(self):
        # A rebase that leaves the patch the same can still break it: the base renames
        # the function the diff's test calls. known() keeps the Done, so the checks it
        # names must be what catches this.
        def commit(name, text, message):
            pathlib.Path(self.repo, name).write_text(text)
            self.git("add", name)
            self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)
            return self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "-b", "trunk", self.head)
        base = commit("lib.py", "def total(xs):\n    return sum(xs)\n", "lib")
        self.git("checkout", "-q", "-b", "work")
        self.base = base
        self.head = commit("test_lib.py", "import unittest, lib\n\n\nclass T(unittest.TestCase):\n"
                           "    def test_total(self):\n        self.assertEqual(lib.total([1, 2]), 3)\n", "test")
        check = ["python3", "-m", "unittest", "-q", "test_lib"]
        self.assertEqual(subprocess.run(check, cwd=self.repo, capture_output=True).returncode, 0)
        self.record(branch="work")
        self.git("checkout", "-q", "trunk")
        broken = commit("lib.py", "def sum_of(xs):\n    return sum(xs)\n", "rename total")
        self.git("checkout", "-q", "work")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "rebase", "-q", "trunk")
        head = self.git("rev-parse", "HEAD").strip()
        self.assertIn("Done stands; rerun the layer's checks", self.known("work", broken, head))
        merge = subprocess.run(["git", "merge-tree", "--write-tree", broken, head], cwd=self.repo, capture_output=True)
        self.assertEqual(merge.returncode, 0)  # the trial merge is clean
        self.assertNotEqual(subprocess.run(check, cwd=self.repo, capture_output=True).returncode, 0)  # the checks fail it

    def test_a_done_stands_only_for_its_own_commits_rebased(self):
        # Review of #99: a commit added after a Done can leave the whole diff's patch-id the
        # same, since patch-id ignores where a hunk lands: here it moves `access = True` from
        # admin() to guest(). The re-check reads that commit; a kept Done would not.
        body = "    # one\n    # two\n    # three\n    access = False\n    # four\n    # five\n    # six\n    return access\n"
        text = "def admin():\n" + body + "\n\ndef guest():\n" + body
        def commit(content, message):
            pathlib.Path(self.repo, "policy.py").write_text(content)
            self.git("add", "policy.py")
            self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)
            return self.git("rev-parse", "HEAD").strip()
        self.base = commit(text, "policy")
        self.git("checkout", "-q", "-b", "work")
        self.head = commit(text.replace("access = False", "access = True", 1), "allow admin")
        idiom = pathlib.Path(self.dir, "idiom.txt")
        idiom.write_text("none: a plain assignment\n")
        self.record(branch="work", evidence={"idiom": [str(idiom)]})
        self.assertIn("Done stands", self.known("work", self.base, self.head))
        first, rest = text.rsplit("access = False", 1)
        head = commit(first + "access = True" + rest, "allow guest instead")
        self.assertEqual(verdicts._patch_id(pathlib.Path(self.repo), verdicts.diff(pathlib.Path(self.repo), self.base, head)),
                         self.patch_id())  # the same patch-id, so the merge gate's Done covers it too
        self.assertIsNone(self.known("work", self.base, head))
        # Review of #99, round 2: a rebase can move the hunk itself. The base changes admin()'s
        # context, so `git rebase --apply` lands `access = True` in guest() under one commit
        # whose patch-id still matches; range-diff pairs it as changed (!).
        self.git("reset", "-q", "--hard", self.head)
        self.git("checkout", "-q", "-b", "parent", self.base)
        moved = commit(text.replace("# two", "# parent changed it", 1), "change admin's context")
        self.git("checkout", "-q", "work")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "rebase", "-q", "--apply", "parent")
        head = self.git("rev-parse", "HEAD").strip()
        self.assertIn("def guest", self.git("diff", moved, head))
        self.assertEqual(verdicts._patch_id(pathlib.Path(self.repo), verdicts.diff(pathlib.Path(self.repo), moved, head)),
                         self.patch_id())
        self.assertIsNone(self.known("work", moved, head))
        # Round 3: with context the base changed identically in both places, range-diff pairs
        # the moved hunk as =; a base that changed a file the diff touches gets a re-check.
        self.assertEqual(verdicts._git(pathlib.Path(self.repo), "diff", "--name-only", self.base, moved).split(), ["policy.py"])

    def test_a_done_with_a_merge_commit_or_a_binary_file_gets_a_full_recheck(self):
        # verify-work's re-check runs a full pass on both, since range-diff can't show them.
        self.git("checkout", "-q", "-b", "work")
        pathlib.Path(self.repo, "asset.bin").write_bytes(b"\0\1")
        self.git("add", "asset.bin")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "asset")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.record(branch="work")
        self.assertIsNone(self.known("work", self.base, self.head))
        self.git("reset", "-q", "--hard", "HEAD~1")  # a text-only branch, so only the merge commit stops it
        self.commit_change("c\n")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.record(branch="work")
        self.assertIn("Done stands", self.known("work", self.base, self.head))
        self.git("checkout", "-q", "-b", "side", self.base)
        pathlib.Path(self.repo, "g").write_text("side\n")
        self.git("add", "g")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "side")
        self.git("checkout", "-q", "work")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "merge", "-q", "--no-ff", "-m", "merge", "side")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.record(branch="work")
        self.assertIsNone(self.known("work", self.base, self.head))

    def test_a_done_another_verdict_superseded_or_new_evidence_needs_gets_a_recheck(self):
        branch = self.git("symbolic-ref", "--short", "HEAD").strip()
        self.record()
        self.assertIn("Done stands", self.known(branch, self.base, self.head))
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--amend", "-m", "refactor f")
        reworded = self.git("rev-parse", "HEAD").strip()  # the same diff, now a refactor: range-diff pairs it !
        self.assertIsNone(self.known(branch, self.base, reworded))
        self.git("reset", "-q", "--hard", self.head)
        # A kind the range needs that the Done never backed, as after evidence.py gains a rule.
        receipt = verdicts.last(pathlib.Path(self.repo), branch)
        self.assertTrue(verdicts.known(pathlib.Path(self.repo), receipt, self.base, self.head))
        with unittest.mock.patch.object(verdicts, "classify", return_value={"parity": ["a rule added since"]}):
            self.assertEqual(verdicts.known(pathlib.Path(self.repo), receipt, self.base, self.head), "")
        self.git("checkout", "-q", "-b", "other")
        self.record(verdict="not-done", findings=["1 · Blocker · x → fix"], branch="other")
        self.assertIsNone(self.known(branch, self.base, self.head))  # the merge gate reads the Not done

    def test_a_done_whose_evidence_no_longer_backs_it_gets_a_recheck(self):
        # Review of #99, round 2: a kind the verdict was required to back, and a log gone since.
        branch = self.git("symbolic-ref", "--short", "HEAD").strip()
        log = pathlib.Path(self.dir, "mutants.log")
        log.write_text("killed: one\nkilled: two\nkilled: three\n")
        self.record(evidence={"mutants": [str(log)]}, require=["mutants"])
        self.assertIn("Done stands", self.known(branch, self.base, self.head))
        log.write_text("killed: one\nkilled: two\nsurvived: three\n")  # the required log now shows a survivor
        self.assertIsNone(self.known(branch, self.base, self.head))
        log.unlink()
        self.assertIsNone(self.known(branch, self.base, self.head))
        # Review of #99, round 3: a mutant log saved for the head since, which a new Done must pass.
        self.record()
        self.assertIn("Done stands", self.known(branch, self.base, self.head))
        saved = self.store().parent / "evidence" / self.head[:12]
        saved.mkdir(parents=True)
        (saved / "mutants.log").write_text("killed: one\nkilled: two\nsurvived: three\n")
        self.assertIsNone(self.known(branch, self.base, self.head))

    def test_a_done_survives_a_rebase_of_a_long_branch(self):
        # verify-work on #99: range-diff pads its numbers to the widest, so 10 commits print
        # " 1:  abc =  1:  def" up to "10:  abc = 10:  def", and a regex for one space read
        # only row 10, keeping a Done whose rows 1-9 changed.
        self.git("checkout", "-q", "-b", "long")
        for n in range(10):
            pathlib.Path(self.repo, f"n{n}").write_text(f"{n}\n")
            self.git("add", f"n{n}")
            self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", f"n{n}")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.record(branch="long")
        self.git("checkout", "-q", "-b", "parent", self.base)
        pathlib.Path(self.repo, "g").write_text("g\n")
        self.git("add", "g")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "g")
        parent = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "long")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "rebase", "-q", "parent")
        rebased = self.git("rev-parse", "HEAD").strip()
        self.assertIn("Done stands", self.known("long", parent, rebased))
        # Rows 2 and 3 rewritten so the whole diff stays the same: n1 first holds x, and n2's
        # commit sets it back as it adds n2.
        self.git("reset", "-q", "--hard", f"{rebased}~9")
        for name, files in (("n1", {"n1": "x\n"}), ("n2", {"n1": "1\n", "n2": "2\n"})):
            for path, text in files.items():
                pathlib.Path(self.repo, path).write_text(text)
            self.git("add", "-A")
            self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", name)
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "cherry-pick", f"{rebased}~7..{rebased}")
        rewritten = self.git("rev-parse", "HEAD").strip()
        self.assertEqual(verdicts.diff(pathlib.Path(self.repo), parent, rewritten),
                         verdicts.diff(pathlib.Path(self.repo), parent, rebased))
        self.assertIsNone(self.known("long", parent, rewritten))

    def test_a_done_gets_a_recheck_when_the_base_changed_a_file_the_diff_touches(self):
        # verify-work on #99: with no function context, range-diff pairs a moved hunk as =.
        # The base edits the first block's context and `git apply` lands the change in the second.
        block = "  # one\n  # two\n  # three\n  access = false\n  # four\n  # five\n  # six\n"
        text = "[admin]\n" + block + "\n[guest]\n" + block
        def commit(content, message):
            pathlib.Path(self.repo, "policy.ini").write_text(content)
            self.git("add", "policy.ini")
            self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)
            return self.git("rev-parse", "HEAD").strip()
        self.base = commit(text, "policy")
        self.git("checkout", "-q", "-b", "work")
        self.head = commit(text.replace("access = false", "access = true", 1), "allow admin")
        self.record(branch="work")
        self.git("checkout", "-q", "-b", "parent", self.base)
        moved = commit(text.replace("# two", "# parent changed it", 1), "change admin's context")
        self.git("checkout", "-q", "work")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "rebase", "-q", "--apply", "parent")
        head = self.git("rev-parse", "HEAD").strip()
        self.assertIn("[guest]\n  # one\n  # two\n  # three\n  access = true", pathlib.Path(self.repo, "policy.ini").read_text())
        self.assertRegex(self.git("range-diff", f"{self.base}..{self.head}", f"{moved}..{head}"), r"^1: +\w+ = 1:")
        self.assertIsNone(self.known("work", moved, head))

    def test_a_done_gets_a_recheck_when_a_line_moves_between_its_commits(self):
        # verify-work on #99: the same whole diff, commit count, and messages, with line x
        # moved from commit b into commit a, which range-diff pairs as ! on both rows.
        def commits(*steps):
            self.git("reset", "-q", "--hard", self.base)
            for message, files in steps:
                for path, text in files.items():
                    pathlib.Path(self.repo, path).write_text(text)
                self.git("add", "-A")
                self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)
            return self.git("rev-parse", "HEAD").strip()
        g, h = "".join(f"g{n}\n" for n in range(20)), "".join(f"h{n}\n" for n in range(20))
        self.git("checkout", "-q", "-b", "work")
        self.head = commits(("a", {"g": g}), ("b", {"h": h, "g": g + "x\n"}))
        self.record(branch="work")
        self.assertIn("Done stands", self.known("work", self.base, self.head))
        moved = commits(("a", {"g": g + "x\n"}), ("b", {"h": h}))
        self.assertEqual(verdicts.diff(pathlib.Path(self.repo), self.base, moved),
                         verdicts.diff(pathlib.Path(self.repo), self.base, self.head))
        self.assertRegex(self.git("range-diff", f"{self.base}..{self.head}", f"{self.base}..{moved}"), r"(?m)^1: +\w+ ! 1:")
        self.assertIsNone(self.known("work", self.base, moved))

    def commit_change(self, text):
        pathlib.Path(self.repo, "f").write_text(text)
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", text)
        return self.git("rev-parse", "HEAD").strip()


FAKE_READY_GH = r"""#!/usr/bin/env python3
import json, os, sys
s = json.load(open(os.environ["FAKE_GH"]))
a = sys.argv[1:]
open(os.environ["FAKE_GH"] + ".calls", "a").write(" ".join(a) + "\n")
if s.get("broken"):
    sys.exit("gh: network down")
if a[:2] == ["pr", "view"] and "-R" in a and (len(a) < 3 or a[2].startswith("-")):
    sys.exit("argument required when using the --repo flag")
if a[:2] == ["pr", "view"]:
    repo = a[a.index("-R") + 1] if "-R" in a else os.environ.get("GH_REPO")
    prs = s.get("repos", {}).get(repo, s["prs"]) if repo else s["prs"]
    print(json.dumps(prs[a[2] if len(a) > 2 and not a[2].startswith("-") else "current"]))
elif a[:2] == ["stack", "view"]:
    print(json.dumps(s["stack"]))
elif a[:2] == ["repo", "view"]:
    print("main")
else:
    sys.exit(1)
"""


class ReadyGate(unittest.TestCase):
    """ready-gate.py against a real origin and clone, with a fake `gh`: a PR is marked ready
    only with a review-loop result for its current diff."""
    HOOK = "ready-gate.py"

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        bin_dir = os.path.join(self.dir, "bin")
        os.makedirs(bin_dir)
        pathlib.Path(bin_dir, "gh").write_text(FAKE_READY_GH)
        os.chmod(os.path.join(bin_dir, "gh"), 0o755)
        self.scenario_path = os.path.join(self.dir, "scenario.json")
        self.env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", FAKE_GH=self.scenario_path,
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        origin, self.repo = os.path.join(self.dir, "origin.git"), os.path.join(self.dir, "repo")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
        subprocess.run(["git", "clone", "-q", origin, self.repo], check=True, capture_output=True)
        self.commit({"f": "a\n"}, "base")
        self.git("push", "-q", "origin", "HEAD:main")
        self.main = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "-b", "feat")
        self.head = self.commit({"g": "1\n"}, "feat")
        self.publish(12, self.main, self.head)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, files, message):
        for name, text in files.items():
            pathlib.Path(self.repo, name).write_text(text)
        self.git("add", ".")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def publish(self, n, base, head, stack=None):
        """PR n on origin at head against main at base, as `gh pr view` reports it."""
        self.git("push", "-q", "-f", "origin", f"{head}:refs/pull/{n}/head", f"{base}:refs/heads/main")
        pr = {"number": n, "url": os.path.join(self.dir, "origin", "pull", str(n)), "baseRefName": "main",
              "baseRefOid": base, "headRefOid": head}
        with open(self.scenario_path, "w") as f:
            json.dump({"prs": {str(n): pr, "current": pr}, "stack": stack or {}}, f)

    def publish_elsewhere(self, repo, n, base, head):
        """PR n at head against main at base in another repo, which `gh -R o/<repo>` reads."""
        place = os.path.join(self.dir, f"{repo}.git")
        if not os.path.exists(place):
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", place], check=True)
        self.git("push", "-q", "-f", place, f"{head}:refs/pull/{n}/head", f"{base}:refs/heads/main")
        pr = {"number": n, "url": os.path.join(self.dir, repo, "pull", str(n)), "baseRefName": "main",
              "baseRefOid": base, "headRefOid": head}
        scenario = json.loads(pathlib.Path(self.scenario_path).read_text())
        scenario.setdefault("repos", {}).setdefault(f"o/{repo}", {})[str(n)] = pr
        pathlib.Path(self.scenario_path).write_text(json.dumps(scenario))
        return pr

    def review(self, base, head, *result):
        return subprocess.run([sys.executable, str(HOOKS / "verdicts.py"), "review", base, head, *result],
                              cwd=self.repo, env=self.env, capture_output=True, text=True)

    def output(self, command, cwd=None):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd or self.repo}
        out = subprocess.run([str(HOOKS / self.HOOK)], input=json.dumps(payload), env=self.env,
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out) if out else {}

    def denial(self, command, cwd=None):
        return self.output(command, cwd).get("hookSpecificOutput", {}).get("permissionDecisionReason")

    def test_a_literal_loop_marks_each_of_its_prs_ready(self):
        # 10 denials Nov 10-23, 2026: `for n in 6118 6080 6081; do gh pr ready $n; done` was
        # read as `gh pr view $n` and denied as "couldn't check".
        self.publish(12, self.main, self.head)
        self.git("checkout", "-q", "-b", "second", self.main)
        second = self.commit({"k": "2\n"}, "second")
        twelve = json.loads(pathlib.Path(self.scenario_path).read_text())["prs"]["12"]
        self.publish(13, self.main, second)
        scenario = json.loads(pathlib.Path(self.scenario_path).read_text())
        scenario["prs"]["12"] = twelve
        pathlib.Path(self.scenario_path).write_text(json.dumps(scenario))
        self.review(self.main, self.head, "--rounds", "1")
        loops = [f"cd {self.repo}; for n in 12 13; do gh pr ready $n 2>&1 | tail -1; done; "
                 "for n in 12 13; do gh pr view $n --json number,isDraft --jq '.number'; done",
                 "for p in 12 13; do gh pr ready $p --repo o/r && gh pr edit $p --repo o/r --add-reviewer x; done",
                 "for n in 12 13\ndo\n  gh pr ready ${n}\ndone",
                 "for r in o/r; do for n in 12 13; do gh pr ready $n -R $r; done; done",
                 'for n in 12 13; do gh pr ready "$n"; done',  # review of #102: a quoted "$n"
                 "for n in 99; do for n in 12 13; do gh pr ready $n; done; done"]  # the inner n wins
        for command in loops:
            with self.subTest(command=command):
                self.assertEqual(self.denial(command), f"Ready gate: #13 has no review-loop result for its diff at head "
                                 f"{second[:12]} (base {self.main[:12]}). " + self.denial("gh pr ready 13").split(". ", 1)[1])
        self.review(self.main, second, "--rounds", "1")
        for command in loops:
            with self.subTest(command=command):
                self.assertEqual(self.output(command), {})
        # A list only the shell knows still denies, naming the command that passes.
        for command in ["for n in $(gh pr list --json number -q '.[].number'); do gh pr ready $n; done",
                        "for n; do gh pr ready $n; done", "for n in 12 13; do :; done; gh pr ready $n",
                        "for n in 12 $M; do gh pr ready $n; done", "gh pr ready $PR",
                        # Review of #102: a loop name set again, a variable left after expanding,
                        # and a word the shell unescapes.
                        "for n in 12; do n=13; gh pr ready $n; done", "for n in 12; do read n; gh pr ready $n; done",
                        "for n in 1; do for p in $V; do gh pr ready $n$p; done; done",
                        "for n in \\13; do gh pr ready $n; done", "for n in 12; do ((n++)); gh pr ready $n; done",
                        # Round 2: a write the round-1 check missed, an inner loop that rebinds
                        # n and ends, and a single-quoted '$n', which the shell passes as is.
                        'for n in 12; do printf -v n %s 13; gh pr ready "$n"; done',
                        'for n in 12; do for n in 13; do :; done; gh pr ready "$n"; done',
                        # Round 3: a write in quoted text, code the gate can't see into, and a
                        # single-quoted '$n', which gh reads as the branch named $n.
                        'for n in 12; do let "n = 13"; gh pr ready "$n"; done',
                        'for n in 12; do eval "$X"; gh pr ready $n; done', "for n in 12; do gh pr ready '$n'; done",
                        # verify-work on #102: a function defined before the loop that rewrites n.
                        "f(){ n=13; }; for n in 12; do f; gh pr ready $n; done",
                        "trap 'n=13' DEBUG; for n in 12; do gh pr ready $n; done"]:
            with self.subTest(command=command):
                self.assertIn("reads a shell variable or quoted text the gate can't expand: write each PR out, as "
                              "`gh pr ready 12 && gh pr ready 13`", self.denial(command))

    def test_checks_a_ready_run_outside_a_checkout_in_the_sessions_clone(self):
        # Nov 18, 2026: `cd ~ && … gh pr ready 5568 --repo o/r` was denied as "not a git
        # repository", though the session's own checkout is a clone of o/r.
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside)
        command = f"cd {outside} && gh pr view 12 --repo o/r && gh pr ready 12 --repo o/r"
        self.assertIn(f"#12 has no review-loop result for its diff at head {self.head[:12]}", self.denial(command))
        self.review(self.main, self.head, "--rounds", "1")
        self.assertEqual(self.output(command), {})
        bare = os.path.join(outside, "bare.git")  # review of #102: git calls a bare repo no work tree
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
        self.assertEqual(self.output(f"cd {bare} && gh pr ready 12 --repo o/r"), {})
        other = os.path.join(self.dir, "other")  # a session in a clone of another repo
        subprocess.run(["git", "init", "-q", other], check=True)
        subprocess.run(["git", "-C", other, "remote", "add", "origin", "https://example.com/x/y.git"], check=True)
        for cwd in (other, outside):
            with self.subTest(cwd=cwd):
                self.assertIn(f"isn't a checkout of {os.path.join(self.dir, 'origin')}, so its verdicts can't be read: "
                              f"run it from one, as `cd <checkout of {os.path.join(self.dir, 'origin')}> && gh pr ready 12`",
                              self.denial(command, cwd))

    def test_no_result_blocks_and_names_the_head_and_the_recorder(self):
        reason = self.denial("gh pr ready 12")
        self.assertIn(f"#12 has no review-loop result for its diff at head {self.head[:12]}", reason)
        self.assertIn("verdicts.py review <base> <head> --skip", reason)

    def test_a_result_at_the_head_allows(self):
        self.assertEqual(self.review(self.main, self.head, "--rounds", "2").returncode, 0)
        self.assertEqual(self.output("gh pr ready 12"), {})
        self.assertEqual(self.output("gh pr ready"), {})  # the current branch's PR

    def test_a_new_commit_after_the_result_blocks(self):
        self.review(self.main, self.head, "--rounds", "1")
        later = self.commit({"g": "2\n"}, "fix")
        self.publish(12, self.main, later)
        self.assertIn(f"at head {later[:12]}", self.denial("gh pr ready 12"))

    def test_the_same_patch_after_a_rebase_allows(self):
        self.review(self.main, self.head, "--rounds", "1")
        self.git("checkout", "-q", "main")
        moved = self.commit({"h": "other\n"}, "unrelated")
        self.git("checkout", "-q", "feat")
        self.git("rebase", "-q", moved)
        rebased = self.git("rev-parse", "HEAD")
        self.assertNotEqual(rebased, self.head)
        self.publish(12, moved, rebased)
        self.assertEqual(self.output("gh pr ready 12"), {})

    def test_a_recorded_skip_allows_and_shows_its_reason(self):
        self.assertEqual(self.review(self.main, self.head, "--skip", "Sam: skip review, ship it").returncode, 0)
        out = self.output("gh pr ready 12")
        said = "Ready gate: #12 skipped review-loop: Sam: skip review, ship it"
        self.assertEqual(out["systemMessage"], said)
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
        self.assertTrue(out["hookSpecificOutput"]["additionalContext"].startswith(said))

    def test_review_needs_rounds_or_a_reason(self):
        for result in [("--rounds", "0"), ("--skip", " "), ()]:
            with self.subTest(result=result):
                self.assertNotEqual(self.review(self.main, self.head, *result).returncode, 0)
        self.assertEqual(self.output("gh pr ready 12")["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_an_unreadable_result_blocks(self):
        patch_id = verdicts._patch_id(pathlib.Path(self.repo), verdicts.diff(pathlib.Path(self.repo), self.main, self.head))
        store = pathlib.Path(self.repo, ".git", "verify-work", "verdicts.tsv")
        store.parent.mkdir(parents=True, exist_ok=True)
        for body in ['{"rounds":0}', '{"rounds":1,"skipped":"x"}', '{"skipped":""}', "[]", "{"]:
            with self.subTest(body=body):
                store.write_text(f"{patch_id}\th\tb\tat\tv3\ts\t-\treview-loop\t{body}\n")
                self.assertIn("can't read the review result", self.denial("gh pr ready 12"))
        good = f"{patch_id}\th\tb\tat\tv3\ts\t-\treview-loop\t" + '{"rounds":1}\n'
        for latest in [f"{patch_id}\th\tb\tat\tv3\ts\t-\treview-loop\n",  # truncated
                       f"{patch_id}\th\tb\tat\tv9\ts\t-\treview-loop\t" + '{"rounds":1}\n']:  # unknown version
            with self.subTest(latest=latest):
                store.write_text(good + latest)  # an older good row never stands in for it
                self.assertIn("can't read the review result", self.denial("gh pr ready 12"))

    def test_checks_only_commands_that_mark_ready(self):
        for command in ["gh pr ready 12 --undo", "gh pr ready 12 --undo=true", "gh pr ready 12 --undo=T",
                        "gh pr create --draft --fill", "gh pr create --draft=1", "gh pr create -d", "gh pr create --web",
                        "gh pr create --draft --dry-run=false --fill", "gh pr create -d --web=false",
                        "gh stack submit --auto", "gh pr view 12", "gh pr ready --help",
                        "echo 'gh pr ready 12'", "git commit -m \"gh pr ready 12\"", "cat <<EOF\ngh pr ready 12\nEOF"]:
            with self.subTest(command=command):
                self.assertEqual(self.output(command), {})
        self.assertFalse(os.path.exists(self.scenario_path + ".calls"))  # never asked gh
        self.git("push", "-q", "origin", "feat")
        for command in ["gh pr ready 12", "cd . && gh pr ready 12 2>&1", "gh pr create --fill", "gh pr new --fill",
                        "gh pr create -B main -H feat --title x", "gh pr create --draft=false", "gh stack submit --auto --open",
                        "gh stack submit --open=true", "gh -R o/r pr ready 12", "gh --repo=o/r pr ready 12",
                        "gh -Ro/r pr ready 12",
                        "gh --repo o/r pr ready 12", "gh pr -R o/r ready 12", "gh pr --repo=o/r ready 12",
                        "gh pr create -B main --title '--draft' --body ok", "gh pr create --draft=f",
                        "gh pr create --draft=FALSE", "gh pr ready 12 --undo=f", "gh stack submit --open=t"]:
            with self.subTest(command=command):
                self.publish(12, self.main, self.head, stack={"trunk": "main", "branches": [
                    {"name": "feat", "pr": {"number": 12, "state": "OPEN"}, "isMerged": False}]})
                self.assertIsNotNone(self.denial(command))

    def test_a_command_that_only_mentions_gh_is_text(self):
        # Gap 1 (dotfiles #27 review): `echo gh pr ready 181` was denied as a ready.
        self.review(self.main, self.head, "--rounds", "1")
        for command in ["echo gh pr ready 181", "printf %s gh pr ready 181", "grep -rn gh pr ready docs",
                        "ls # then gh pr ready 181", "echo git push && gh pr ready 12"]:
            with self.subTest(command=command):
                self.assertEqual(self.output(command), {})
        for command in ["echo $(gh pr ready 181)", "echo `gh pr ready 181`", "x=1 gh pr ready 181",
                        "echo '#' && gh pr ready 181", 'echo "#x" && gh pr ready 181',  # a quoted # is no comment
                        "echo Issue\\ #12 && gh pr ready 181"]:  # nor one after an escaped space
            with self.subTest(command=command):
                self.assertIn("couldn't check", self.denial(command))

    def test_reads_grouped_short_flags_as_gh_does(self):
        # Gap 2 (dotfiles #27 review): `gh pr create -df` was denied while `-d -f` was allowed.
        for command in ["gh pr create -df", "gh pr create -fd", "gh pr create -fdB main", "gh pr create -fd=true",
                        "gh pr create -Bmain -d"]:
            with self.subTest(command=command):
                self.assertEqual(self.output(command), {})
        self.assertFalse(os.path.exists(self.scenario_path + ".calls"))  # never asked gh
        self.git("push", "-q", "origin", "feat")
        for command in ["gh pr create -fd=false", "gh pr create -td -f", "gh pr create -ft -d", "gh pr create -- -d",
                        "gh pr create --attach -df.png --fill"]:  # gh's flags that take a value, as of 2.103
            with self.subTest(command=command):
                self.assertIn("has no review-loop result", self.denial(command))

    def test_checks_the_repo_and_checkout_the_shell_would(self):
        # Gap 3 (dotfiles #27 review): GH_REPO, pushd, and a conditional cd made the gate check
        # the wrong repo's diff.
        self.review(self.main, self.head, "--rounds", "1")  # origin's #12
        other = self.commit({"g": "upstream\n"}, "upstream")  # o/upstream's #12, with no result
        self.publish_elsewhere("upstream", 12, self.main, other)
        outer = os.path.join(self.dir, "outer")
        os.makedirs(outer)
        for command in ["GH_REPO=o/upstream gh pr ready 12", "export GH_REPO=o/upstream; gh pr ready 12",
                        "env GH_REPO=o/upstream gh pr ready 12", "GH_REPO=o/upstream; export GH_REPO; gh pr ready 12",
                        "set -a; GH_REPO=o/upstream; gh pr ready 12",
                        "set -eo allexport; GH_REPO=o/upstream; gh pr ready 12"]:
            with self.subTest(command=command):
                self.assertIn(f"at head {other[:12]}", self.denial(command))
        os.makedirs(os.path.join(outer, "inner"))
        os.symlink(os.path.join(outer, "inner"), os.path.join(self.repo, "link"))
        self.assertEqual(self.output(f"cd {self.repo}/link/.. && gh pr ready 12"), {})  # logical: the repo
        for command in [f"pushd {outer} && gh pr ready 12", f"cd {outer} || exit 1; gh pr ready 12",
                        f"pushd {self.repo} >/dev/null; builtin cd {outer}; gh pr ready 12",
                        f"command cd {outer} && gh pr ready 12",
                        f"cd -P {self.repo}/link/.. && gh pr ready 12",
                        f"cd -L -P {self.repo}/link/.. && gh pr ready 12"]:
            with self.subTest(command=command):
                self.assertIn("couldn't check", self.denial(command))
        for command in [f"cd {outer} && false && cd {self.repo}; gh pr ready 12",
                        f"if true; then cd {outer}; fi; gh pr ready 12", f"{{ cd {outer}; }}; gh pr ready 12",
                        f"cd {outer} | true; gh pr ready 12", f"case y in x) cd {outer} ;; esac; gh pr ready 12",
                        'cd "$NOWHERE" && gh pr ready 12',
                        "popd && gh pr ready 12", "cd - && gh pr ready 12", f"cd {outer} {outer} && gh pr ready 12",
                        f"CDPATH={self.dir}; cd outer && gh pr ready 12", "cd ~+ && gh pr ready 12",
                        "cd +1 && gh pr ready 12", "cd -2 && gh pr ready 12", f"{outer} && gh pr ready 12",
                        f"HOME={outer}; cd && gh pr ready 12", f"export HOME={outer}; cd ~/x && gh pr ready 12",
                        # verify-work on #102: an escaped cd, as merge-gate.py reads it through shell_dirs.
                        f"\\cd {outer} && gh pr ready 12",
                        f"cd {outer}; false || cd {outer}; cd - && gh pr ready 12"]:
            with self.subTest(command=command):
                self.assertIn("can't tell which checkout", self.denial(command))
        for command in ["GH_REPO=$R gh pr ready 12", "true && export GH_REPO=o/upstream; gh pr ready 12",
                        "case y in x) export GH_REPO=o/upstream ;; esac; gh pr ready 12",
                        "export GH_REPO=o/upstream; export -n GH_REPO; gh pr ready 12",
                        "export GH_REPO=o/upstream; typeset +x GH_REPO; gh pr ready 12",
                        "false && set -a; GH_REPO=o/upstream; gh pr ready 12",
                        "GH_REPO=o/upstream env -u GH_REPO gh pr ready 12",
                        'set -a; : "${GH_REPO:=o/upstream}"; gh pr ready 12',
                        "printf %s ${GH_REPO=o/x}; gh pr ready 12"]:
            with self.subTest(command=command):
                self.assertIn("can't tell which repo", self.denial(command))
        for command in ["GH_REPO=o/upstream gh pr ready 12 -R o/origin",
                        "export GH_REPO=o/upstream; unset GH_REPO; gh pr ready 12",
                        "GH_REPO=o/upstream\ngh pr ready 12",  # a shell variable gh never sees
                        "set -- -a; GH_REPO=o/upstream; gh pr ready 12",  # -a is a positional parameter
                        f"pushd {outer} && popd && gh pr ready 12", f"cd {outer}; cd - && gh pr ready 12",
                        f"cd {self.repo} || exit 1; gh pr ready 12", f"cd {outer} && cd {self.repo} && gh pr ready 12",
                        f"echo CDPATH; cd {self.dir} && cd repo && gh pr ready 12"]:
            with self.subTest(command=command):
                self.assertEqual(self.output(command), {})
        self.env["GH_REPO"] = "o/upstream"  # inherited from the session, as gh would read it
        for command in ["env -u GH_REPO gh pr ready 12", "env -i gh pr ready 12"]:
            with self.subTest(command=command, inherited=True):
                self.assertIn("can't tell which repo", self.denial(command))
        scenario = json.loads(pathlib.Path(self.scenario_path).read_text())
        scenario["repos"]["o/upstream"]["current"] = scenario["repos"]["o/upstream"]["12"]
        pathlib.Path(self.scenario_path).write_text(json.dumps(scenario))
        # Exported, so gh sees it.
        for command in ["gh pr ready 12", "GH_REPO=o/upstream; gh pr ready 12", "gh pr ready"]:
            with self.subTest(command=command, inherited=True):
                self.assertIn(f"at head {other[:12]}", self.denial(command))
        for command in ["unset GH_REPO; gh pr ready 12", "GH_REPO= gh pr ready 12", "GH_REPO=; gh pr ready 12"]:
            with self.subTest(command=command, inherited=True):
                self.assertEqual(self.output(command), {})

    def test_reads_quoted_words_and_each_cd_in_order(self):
        self.review(self.main, self.head, "--rounds", "1")
        os.makedirs(os.path.join(self.dir, "outer"))
        for command in ['gh pr ready "12"', "gh pr ready '12'", f"cd {self.dir} && cd repo && gh pr ready 12",
                        "cd /tmp; cd - >/dev/null; true", "gh pr ready 12 --undo && echo 'gh pr ready 13'",
                        "(gh pr ready 12)"]:
            with self.subTest(command=command):
                self.assertEqual(self.output(command), {})
        # The shell ends in outer/repo, which isn't a repo, so the gate can't check it there.
        self.assertIn("couldn't check", self.denial(f"cd {self.dir}/outer && cd repo && gh pr ready 12"))
        for command in [f"(cd {self.dir}/outer && true) && gh pr ready 12", "false && cd /tmp || gh pr ready 12"]:
            with self.subTest(command=command):
                self.assertIn("can't tell which checkout", self.denial(command))

    def test_denies_a_ready_after_a_command_that_moves_a_branch(self):
        self.review(self.main, self.head, "--rounds", "1")
        for command in ["git commit -qam fix && git push && gh pr ready 12", "gh stack push; gh pr ready 12",
                        "git -c user.name=x commit -qam fix && gh pr ready 12", "git --no-pager push && gh pr ready 12",
                        "git -C . rebase main && gh stack submit --open", "gh stack checkout other && gh pr ready",
                        "gh stack up && gh pr ready"]:
            with self.subTest(command=command):
                self.assertIn("can move a branch before it marks a PR ready", self.denial(command))
        self.assertEqual(self.output("gh pr ready 12 && git push"), {})
        # Gap 4 (dotfiles #27 review): `gh pr edit --base` before the ready checked the old diff.
        for command in ["gh pr edit 12 --base other && gh pr ready 12", "gh pr edit 12 -Bother; gh pr ready 12",
                        "gh pr edit 12 --base=other && gh pr ready 12", "gh pr checkout 13 && gh pr ready",
                        "gh pr update-branch 12 && gh pr ready 12", "gh pr merge 11 && gh pr ready 12",
                        "gh stack merge 11 && gh pr ready 12", "gh -Ro/r pr edit 12 --base other && gh pr ready 12",
                        "gh pr -R o/r edit 12 --base other && gh pr ready 12", "gh pr co 13 && gh pr ready",
                        "gh pr create -df -B other && gh pr ready 12",
                        "gh pr create --dry-run --fill && gh pr ready 12"]:
            with self.subTest(command=command):
                self.assertIn("can move a branch before it marks a PR ready", self.denial(command))
        self.assertIn("can move a branch", self.denial("gh pr edit 12 --add-label -t --base other && gh pr ready 12"))
        self.assertEqual(self.output("gh pr edit 12 --title x --body-file - && gh pr ready 12"), {})

    def test_create_checks_the_base_and_head_gh_picks(self):
        self.git("checkout", "-q", "-b", "child")
        child = self.commit({"c": "1\n"}, "child")
        self.git("push", "-q", "origin", "feat", "child")
        self.git("config", "branch.child.gh-merge-base", "feat")
        self.review(self.head, child, "--rounds", "1")  # feat...child, the diff gh opens
        self.assertEqual(self.output("gh pr create --fill"), {})
        self.git("config", "--unset", "branch.child.gh-merge-base")
        self.assertIn(f"at head {child[:12]} (base {self.main[:12]})", self.denial("gh pr create --fill"))
        self.commit({"c": "2\n"}, "unpushed")  # --head opens the pushed branch, not this commit
        self.assertEqual(self.output("gh pr create -B feat -H child --fill"), {})

    def test_a_pr_from_another_repo_is_fetched_from_it(self):
        self.review(self.main, self.head, "--rounds", "1")
        self.git("remote", "set-url", "origin", os.path.join(self.dir, "nowhere"))
        self.assertEqual(self.output("gh pr ready 12 -R o/upstream"), {})
        # Gap 5 (dotfiles #27 review): a PR named by its URL, or the one gh picks in a fork's
        # clone, was fetched from origin.
        upstream = self.publish_elsewhere("upstream", 7, self.main, self.head)
        scenario = json.loads(pathlib.Path(self.scenario_path).read_text())
        scenario["prs"].update({"https://github.com/o/upstream/pull/7": upstream, "current": upstream})
        pathlib.Path(self.scenario_path).write_text(json.dumps(scenario))
        for command in ["gh pr ready https://github.com/o/upstream/pull/7", "gh pr ready"]:
            with self.subTest(command=command):
                self.assertEqual(self.output(command), {})
        scenario["prs"]["current"] = dict(upstream, url=os.path.join(self.dir, "gone", "pull", "7"))
        pathlib.Path(self.scenario_path).write_text(json.dumps(scenario))
        self.assertIn("couldn't check", self.denial("gh pr ready"))  # its own repo is out of reach
        # The same owner and name on another host, or under another path, is another repo.
        scenario["prs"]["9"] = self.publish_elsewhere("hosts/o/project", 9, self.main, self.head)
        pathlib.Path(self.scenario_path).write_text(json.dumps(scenario))
        self.git("remote", "set-url", "origin", os.path.join(self.dir, "elsewhere", "o", "project.git"))
        self.assertEqual(self.output("gh pr ready 9"), {})
        scenario["prs"]["pulled"] = self.publish_elsewhere("o/pull", 12, self.main, self.head)  # a repo named pull
        pathlib.Path(self.scenario_path).write_text(json.dumps(scenario))
        self.assertEqual(self.output("gh pr ready pulled"), {})
        # So is one on another port of the same host; insteadOf points port 2 at a local copy.
        self.publish_elsewhere("port2/o/project", 9, self.main, self.head)
        scenario["prs"]["9"]["url"] = "http://localhost:2/o/project/pull/9"
        pathlib.Path(self.scenario_path).write_text(json.dumps(scenario))
        self.git("config", f"url.{self.dir}/port2/.insteadOf", "http://localhost:2/")
        self.git("remote", "set-url", "origin", "http://localhost:1/o/project.git")
        self.assertEqual(self.output("gh pr ready 9"), {})

    def test_stack_submit_open_checks_each_unmerged_layer(self):
        top = self.git("checkout", "-q", "-b", "top") or self.commit({"t": "1\n"}, "top")
        stack = {"trunk": "main", "branches": [
            {"name": "gone", "isMerged": True},
            {"name": "waiting", "isMerged": False, "isQueued": True},
            {"name": "feat", "pr": {"number": 12, "state": "OPEN"}, "isMerged": False},
            {"name": "top", "isMerged": False}]}
        self.publish(12, self.main, self.head, stack=stack)
        self.review(self.main, self.head, "--rounds", "1")
        reason = self.denial("gh stack submit --open")
        self.assertIn(f"top has no review-loop result for its diff at head {top[:12]} (base {self.head[:12]})", reason)
        self.assertNotIn("#12", reason)
        self.review("feat", "top", "--rounds", "3")
        self.assertEqual(self.output("gh stack submit --open"), {})

    def test_fails_closed(self):
        with open(self.scenario_path, "w") as f:
            json.dump({"broken": True}, f)
        self.assertIn("couldn't check the PRs this marks ready", self.denial("gh pr ready 12"))

    def test_a_slow_check_denies_before_the_hook_times_out(self):
        slow = os.path.join(self.dir, "slow")
        os.makedirs(slow)
        pathlib.Path(slow, "gh").write_text("#!/bin/sh\nsleep 5\n")
        os.chmod(os.path.join(slow, "gh"), 0o755)
        self.env.update(PATH=f"{slow}:{self.env['PATH']}", READY_GATE_SECONDS="1")
        started = time.monotonic()
        self.assertIn("couldn't check", self.denial("gh pr ready 12"))
        self.assertLess(time.monotonic() - started, 4)

    def test_verdict_readers_skip_review_results(self):
        self.review(self.main, self.head, "--rounds", "1")
        repo = pathlib.Path(self.repo)
        self.assertIsNone(verdicts.find_done(repo, verdicts.diff(repo, self.main, self.head)))
        self.assertIsNone(verdicts.last(repo, "feat"))
        status = subprocess.run([sys.executable, str(HOOKS / "verdicts.py"), "status", self.main, self.head],
                                cwd=self.repo, capture_output=True, text=True).stdout
        self.assertIn("done: no", status)
        # maintainer/test_scorecard.py checks the scorecard's reader skips them too.

    def test_review_loop_records_through_its_own_copy(self):
        # A copy of hooks/verdicts.py, which scripts/sync-copies.py --check keeps in sync.
        script = REPO / "skills" / "primitive" / "review-loop" / "scripts" / "verdicts.py"
        out = subprocess.run([sys.executable, str(script), "review", self.main, self.head, "--rounds", "1"],
                             cwd=self.repo, env=self.env, capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out)["rounds"], 1)
        self.assertEqual(self.output("gh pr ready 12"), {})


FAKE_PUSH_GH = r"""#!/usr/bin/env python3
import json, os, sys
s = json.load(open(os.environ["FAKE_GH"]))
a = sys.argv[1:]
open(os.environ["FAKE_GH"] + ".calls", "a").write(" ".join(a) + "\n")
if s.get("broken"):
    sys.exit("gh: network down")
if a[:2] == ["stack", "view"]:
    print(json.dumps(s["stack"]))
elif a[:1] == ["api"] and "/pulls?" in a[-3]:  # --paginate repos/<base>/pulls?head=<owner>:<branch>&… --jq …
    import urllib.parse
    path, query = a[-3].split("?")
    owner, branch = urllib.parse.parse_qs(query)["head"][0].split(":", 1)
    base = path[len("repos/"):-len("/pulls")]
    print("\n".join(str(pr["number"]) for pr in s["prs"].values() if pr["headRefName"] == branch
                    and pr["headRepositoryOwner"]["login"] == owner and pr["state"] == "OPEN"
                    and f"github.com/{base}/pull/" in pr["url"]))
elif a[:1] == ["api"]:  # repos/<repo> --jq '<its parent and source>'
    print(" ".join(s.get("forks", {}).get(a[1][len("repos/"):], [])))
elif a[:2] == ["pr", "view"]:
    base = a[a.index("-R") + 1]
    pr = next((pr for pr in s["prs"].values() if pr["url"] == f"https://github.com/{base}/pull/{a[2]}"), None)
    print(json.dumps(pr)) if pr else sys.exit("no pull requests found")
else:
    sys.exit(1)
"""


class PushGate(unittest.TestCase):
    """push-gate.py, replaying the two pushes that dismissed a teammate's approvals of
    a work repo's #6119 on Nov 24, 2026, with gh faked and a clone whose
    origin URL is GitHub's, rewritten to a local bare repo."""
    HOOK = "push-gate.py"
    URL = "https://github.com/acme/app.git"
    BRANCH = "effect-native/client-allowlists"
    # The worker's command at 11:54:06 (transcript 43a48f1d, line 1554), its checkout replaced.
    WORKER = ("cd {repo}; gh pr view 6119 --json reviews,reviewDecision -q '\"reviews=\\(.reviews|length) "
              "decision=\\(.reviewDecision)\"'; gh stack push 2>&1 | tail -1; sleep 5; "
              "git ls-remote --heads origin effect-native/client-allowlists")
    # The coordinator's command at 12:48:23 (transcript 21e564b0, line 39337), its checkout replaced.
    COORDINATOR = ("gh pr view 6119 --json reviews --jq '[.reviews[]|select(.state==\"APPROVED\")|.author.login]'; "
                   "cd {repo} && git status --short | head -3; git log --oneline -1; "
                   "gh stack push 2>&1 | grep -vE '\\x1b|lefthook' | tail -2; "
                   "git ls-remote origin effect-native/client-allowlists")
    # The card the coordinator's "a" at 12:48:16 picked (line 39326), cut down.
    CARD = ("🟡 **The client-allowlists row is fixed. #6119 still waits on your go.**\n\n---\n\n**Next**\n\n"
            "- **`a` → push the cleanup, post the reply, re-request the teammate on #6119** · *recommended*\n"
            "- `b` → no: push the cleanup only\n\n")
    CARD_OPTIONS = [{"key": "a", "class": "stop:post", "text": "push the cleanup, post the reply, re-request the teammate on #6119"},
                    {"key": "b", "class": "stop:push", "text": "no: push the cleanup only"}]
    APPROVED = {"author": {"login": "teammate"}, "state": "APPROVED", "submittedAt": "2026-11-24T11:25:12Z"}

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        bin_dir = os.path.join(self.dir, "bin")
        os.makedirs(bin_dir)
        pathlib.Path(bin_dir, "gh").write_text(FAKE_PUSH_GH)
        os.chmod(os.path.join(bin_dir, "gh"), 0o755)
        outside_t3 = {k: v for k, v in os.environ.items() if k not in ("T3CODE_CLI_PATH", "GIT_DIR", "GIT_INDEX_FILE")}
        self.env = dict(outside_t3, PATH=f"{bin_dir}:{os.environ['PATH']}", FAKE_GH=os.path.join(self.dir, "scenario.json"),
                        T3_STATE_DB="/nonexistent", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        origin, self.repo = os.path.join(self.dir, "origin"), os.path.join(self.dir, "repo")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        self.git("remote", "add", "origin", self.URL)
        self.git("config", f"url.{origin}.insteadOf", self.URL)
        self.commit("base")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "-b", self.BRANCH)
        self.remote_head = self.commit("restack")  # 280183972f, the teammate's approved head
        self.git("push", "-q", "-u", "origin", self.BRANCH)
        self.local = self.commit("fix")  # ebf5e776c6, not pushed yet
        self.scenario()

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        pathlib.Path(self.repo, "f").write_text(message + "\n")
        self.git("add", ".")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def pull(self, n, branch, head, reviews=(), repo="acme/app", base=None):
        """PR n on base (repo, unless a fork's PR), from branch in repo."""
        return {"number": n, "url": f"https://github.com/{base or repo}/pull/{n}", "state": "OPEN",
                "headRefName": branch, "headRefOid": head, "headRepository": {"name": repo.split("/")[1]},
                "headRepositoryOwner": {"login": repo.split("/")[0]}, "reviews": list(reviews)}

    def scenario(self, reviews=(APPROVED,), head=None, needs_rebase=False, n=6119, branch=BRANCH, **extra):
        """PR n on branch, its head on GitHub at head (the pushed commit) with reviews, and
        the checkout's stack of that one branch."""
        pr = self.pull(n, branch, head or self.remote_head, reviews)
        stack = {"trunk": "main", "currentBranch": branch, "branches": [
            {"name": branch, "head": self.git("rev-parse", branch), "isMerged": False, "isQueued": False,
             "needsRebase": needs_rebase, "pr": {"number": n, "url": pr["url"], "state": "OPEN"}}]}
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps({"stack": stack, "prs": {str(n): pr}, **extra}))

    def reason(self, command, said=(), **event):
        payload = {"tool_name": "Bash", "tool_input": {"command": command.format(repo=self.repo)},
                   "cwd": event.pop("cwd", self.repo), **event}
        if said:
            payload["transcript_path"] = os.path.join(self.dir, f"{event.get('session_id', 'session')}.jsonl")
            with open(payload["transcript_path"], "w") as transcript:
                for entry in said:  # a typed prompt, or an entry as it is, such as a reply
                    transcript.write(json.dumps(claude_said(entry) if isinstance(entry, str) else entry) + "\n")
        out = subprocess.run([str(HOOKS / self.HOOK)], input=json.dumps(payload), env=self.env,
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] if out else None

    def offer(self, *options, text=CARD):
        return claude_wrote(text + block({"state": "stop", "needs": [{"id": 15, "kind": "review", "name": "push #6119"}],
                                          "options": [{**option, "key": key} for key, option in zip("abc", options)]}))

    def dismisses(self, reason, approved="2026-11-24 11:25"):
        self.assertIsNotNone(reason)
        self.assertIn(f"pushing `{self.BRANCH}` moves #6119 from {self.remote_head[:10]} to {self.local[:10]}, which "
                      f"dismisses teammate's approval (submitted {approved} UTC)", reason)
        self.assertIn('ask the user first with a `stop:push` option that names #6119 and the dismissal, such as '
                      '"push #6119 (dismisses teammate\'s approval)"', reason)

    def test_replays_the_workers_push_from_a_delegated_child(self):
        # 11:54:06: the brief said "no approvals"; the push dismissed the teammate's 11:25 approval.
        brief = ("Mode: planning autonomous, trust merge-on-go\nWorker of: effect-native (coordinator ◆ effect-native).\n\n"
                 "Run address-review on #6119's two unresolved threads.")
        with tempfile.TemporaryDirectory() as folder:
            self.env["T3_STATE_DB"] = ReplyShapeContext.state_db(self, folder, ReplyShapeContext.CHILD, brief)
            for said in [(brief,), ("push #6119 (dismisses teammate's approval)",)]:  # a child never has a go
                with self.subTest(said=said):
                    reason = self.reason(self.WORKER, said=said, session_id=ReplyShapeContext.SESSION, cwd=self.dir)
                    self.dismisses(reason)
                    self.assertNotIn("picks", reason)

    def test_replays_the_coordinators_push_on_a_stop_post_pick(self):
        # 12:48:23: the reviews check and the push ran as one command, after a pick of a
        # stop:post option whose Cost row said the push dismissed nothing more.
        reviews = [{**self.APPROVED, "state": "DISMISSED"},
                   {"author": {"login": "coderabbitai"}, "state": "COMMENTED", "submittedAt": "2026-11-24T12:05:25Z"},
                   {**self.APPROVED, "submittedAt": "2026-11-24T12:12:39Z"}]
        self.scenario(reviews=reviews)
        reason = self.reason(self.COORDINATOR, said=("fix it", self.offer(*self.CARD_OPTIONS), "a"), cwd=self.dir)
        self.dismisses(reason, approved="2026-11-24 12:12")
        self.assertIn('the user\'s "a" picks "push the cleanup, post the reply, re-request the teammate on #6119", a '
                      "stop:post option of your reply before it, and only a stop:push option allows a push that "
                      "dismisses an approval", reason)
        # Its b, a stop:push option that doesn't say the push dismisses an approval, and says "no".
        reason = self.reason(self.COORDINATOR, said=("fix it", self.offer(*self.CARD_OPTIONS), "b"), cwd=self.dir)
        self.assertIn('picks "no: push the cleanup only", a stop:push option of your reply before it, which isn\'t '
                      "a plain request to push that says it dismisses an approval", reason)

    def test_allows_a_push_the_users_go_names_the_dismissal_of(self):
        # #6091's restack, the go the brief names, and the go the deny message suggests.
        self.git("branch", "-m", self.BRANCH, "effect-native/action-messages")
        self.git("config", "branch.effect-native/action-messages.merge", "refs/heads/effect-native/action-messages")
        self.scenario(n=6091, branch="effect-native/action-messages")
        restack = {"class": "stop:push", "text": "restack #6091 onto develop, push (dismisses the teammate's approval)"}
        for said in [("fix it", self.offer(restack, text="Restack?\n\n"), "a"),
                     ("fix it", self.offer({"class": "routine", "text": "verify"}, restack, text="Restack?\n\n"), " B. "),
                     ("push #6091 (dismisses teammate's approval)",),
                     ("ok, restack and push #6091, dismissing the teammate's approval",),
                     ("go ahead and push #6091, it dismisses the teammate's approval",),
                     ("lets push #6091 and dismiss the teammate's approval",)]:
            with self.subTest(said=said[-1]):
                self.assertIsNone(self.reason("gh stack push", said=said))
                self.assertIsNone(self.reason("git push --force-with-lease", said=said))
        for said, why in [
            (("fix it", self.offer({**restack, "class": "decision"}, text="Restack?\n\n"), "a"), "a decision option"),
            (("fix it", self.offer({**restack, "text": "restack #6091 onto develop and push"}, text="Restack?\n\n"), "a"),
             "isn't a plain request to push"),
            # verify-work, Nov 24, 2026: a stop:push option that refuses or puts off the push.
            *((("fix it", self.offer({**restack, "text": text}, text="Restack?\n\n"), "a"), "isn't a plain request to push")
              for text in ("don't push #6091 yet, it would dismiss the teammate's approval",
                           "hold #6091: pushing would dismiss the teammate's approval",
                           "push #6091 only if it doesn't dismiss the teammate's approval",
                           "wait for the teammate; a push to #6091 would dismiss the approval")),
            (("fix it", self.offer({**restack, "text": "push #6092 (dismisses the teammate's approval)"}, text="Restack?\n\n"), "a"),
             "doesn't name #6091"),
            (("fix it", self.offer(restack, text="Restack?\n\n"), "hold on", claude_wrote("Holding."), "a"), "picks nothing"),
            (("push #6091",), None), (("push #6091, dismissing the teammate's approval?",), None),
            (("don't push #6091, it would dismiss the teammate's approval",), None),
            (("push #6091 if it dismisses nothing",), None),
            # review-loop r1 on #104: a push word and "dismiss" that don't ask to dismiss the approval.
            (("push #6091 after the approval has been dismissed",), None),
            (("Is a push to #6091 going to dismiss the approval",), None),
            (("push #6091 and dismiss the notification",), None),
            # review-loop r3: a statement about the push isn't a request for it.
            (("pushing #6091 dismisses the teammate's approval",), None),
            (("FYI the push to #6091 dismisses the teammate's approval",), None),
            # review-loop r3 (Claude): a warning that opens with a push word.
            *(((text,), None) for text in (
                "push to #6091 will dismiss the teammate's approval, so ask me first",
                "push to #6091 would dismiss the teammate's approval",
                "sync on #6091 dismisses the approval, careful",
                "push #6091 would dismiss the approval, so ping me first",
                "push #6091 dismisses the teammate's approval. ask me first",
                "push #6091 dismisses the teammate's approval; I'll decide tomorrow",
                "push #6091 (dismisses the teammate's approval), so ask me first",
                # verify-work on ae9214f: a delay, a warning, or a report with the dismissal last.
                "push #6091 tomorrow (dismisses the approval)", "push #6091 is risky, it dismisses the approval",
                "push #6091 failed and dismissed the approval", "push #6091 next week, dismissing the approval",
                "push everything except #6091 (dismisses approvals)",
                # verify-work on 39ac7a0: a bare remark, with no "(", comma, or "and" before the dismissal.
                "push #6091 dismisses the teammate's approval", "push #6091 dismisses the teammate's approval.",
                "push #6091 and it dismisses the teammate's approval")),
            (("fix it", self.offer({**restack, "text": "push #6091 once the teammate dismisses their approval"},
                                   text="Restack?\n\n"), "a"), "isn't a plain request to push"),
        ]:
            with self.subTest(said=said[-1]):
                reason = self.reason("gh stack push", said=said)
                self.assertIn("which dismisses teammate's approval", reason)
                if why:
                    self.assertIn(why, reason)
        with tempfile.TemporaryDirectory() as folder:  # in T3, a database it can't read gives no go
            self.env["T3CODE_CLI_PATH"] = "/t3"
            self.assertIsNotNone(self.reason("gh stack push", said=("push #6091 (dismisses teammate's approval)",)))

    def test_replays_the_push_picks_with_steps_after_the_dismissal(self):
        # Nov 25, 2026: the stop:push options the user picked on #6203 at 10:36:55 (transcript
        # 7ba090ed) and on #6215 at 11:59:39 (acdfd830), which the gate refused for the steps
        # after the dismissal, and the 10:36:37 one, which names no dismissal.
        for n, text in [(6203, "push #6203 (dismisses the reviewer's approval), then post 3 replies, resolve both threads"),
                        (6215, "push #6215 (dismisses the reviewer's approval), post the reply, resolve the thread"),
                        (6203, "push #6203, dismissing the reviewer's approval; then reply, resolve, update the PR description")]:
            with self.subTest(text=text):
                self.scenario(n=n)
                self.assertIsNone(self.reason("gh stack push", said=("fix it", self.offer(
                    {"class": "stop:push", "text": text}, text="Push?\n\n"), "a")))
        self.scenario(n=6203)
        for text, why in [("yes: push both fixes, post the 3 replies, resolve both threads", "isn't a plain request"),
                          # A step after the dismissal that refuses, waits, asks, or opens on no step verb.
                          *((text, "isn't a plain request") for text in (
                              "push #6203 (dismisses the reviewer's approval), so ask me first",
                              "push #6203 (dismisses the reviewer's approval), and ask me first",
                              "push #6203 (dismisses the reviewer's approval), then wait for CI",
                              "push #6203 (dismisses the reviewer's approval), post the reply once CI passes",
                              "push #6203 (dismisses the reviewer's approval), tomorrow post the reply",
                              "push #6203 (dismisses the reviewer's approval), post the reply, but not yet")),
                          # The PRs count only in the push: a trailing step names none.
                          ("push #6204 (dismisses the reviewer's approval), then post the reply on #6203", "isn't a plain request")]:
            with self.subTest(text=text):
                reason = self.reason("gh stack push", said=("fix it", self.offer(
                    {"class": "stop:push", "text": text}, text="Push?\n\n"), "a"))
                self.assertIn("which dismisses teammate's approval", reason)
                self.assertIn(why, reason)

    def test_takes_a_yes_opener_and_no_pr_for_one_live_approval(self):
        # Nov 25, 2026: the stop:push option the user picked on #6215 at 11:58:09 (transcript
        # acdfd830) opens on "yes:" and names no PR, as merge-gate takes a go that names none.
        self.scenario(n=6215)
        picks = [("fix it", self.offer({"class": "stop:push", "text": text}, text="Push?\n\n"), "a") for text in (
            "yes: push (dismisses the reviewer's approval), post the reply, resolve the thread",
            "push it (dismisses the teammate's approval)", "yes: push #6215 (dismisses the reviewer's approval)")]
        for said in picks + [("push it, dismissing the teammate's approval",), ("yes: push (dismisses the reviewer's approval)",)]:
            with self.subTest(said=said[-1] if len(said) == 1 else said[1]):
                self.assertIsNone(self.reason("gh stack push", said=said))
        # With two live approvals, a go names each PR.
        scenario = json.loads(pathlib.Path(self.env["FAKE_GH"]).read_text())
        scenario["prs"]["6216"] = self.pull(6216, self.BRANCH, self.remote_head, [self.APPROVED])
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps(scenario))
        for text, why in [("yes: push (dismisses the reviewer's approval), post the reply, resolve the thread",
                           "doesn't name #6215 and #6216"),
                          ("push #6215 (dismisses the reviewer's approval)", "doesn't name #6216"),
                          ("yes: push (dismisses the reviewer's approval), post the reply on #6216", "isn't a plain request")]:
            with self.subTest(text=text):
                self.assertIn(why, self.reason("gh stack push", said=("fix it", self.offer(
                    {"class": "stop:push", "text": text}, text="Push?\n\n"), "a")))
        self.assertIsNone(self.reason("gh stack push", said=("push #6215 and #6216 (dismisses the teammate's approvals)",)))
        # verify-work on b512f73: with one live approval, a go naming no PR in its push names
        # none after it either, and a step after the dismissal opens on a routine step verb.
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps({**scenario, "prs": {"6216": scenario["prs"]["6216"]}}))
        for text, why in [("push it (dismisses the reviewer's approval), then post the reply on #6215", "isn't a plain request"),
                          ("push (dismisses the reviewer's approval), then run gh stack push on #6215", "isn't a plain request"),
                          ("push #6216 (dismisses the reviewer's approval), then run the deploy to production",
                           "isn't a plain request"),
                          ("push #6216 (dismisses the reviewer's approval), then update production data", "isn't a plain request"),
                          ("push #6216 (dismisses the reviewer's approval), restack #6215", "isn't a plain request"),
                          # verify-work on dc8690e and review-loop r1: a step after the dismissal names
                          # no PR, takes no other action, and doesn't undo the push.
                          *((text, "isn't a plain request") for text in (
                              "push (dismisses the reviewer's approval), then post the reply on PR 6215",
                              "push it (dismisses the reviewer's approval), then post the reply and force-push 6215",
                              "push (dismisses the reviewer's approval), post the reply on https://github.com/acme/app/pull/6215",
                              "push (dismisses the reviewer's approval), then post the reply on #6215",
                              "push #6216 (dismisses the reviewer's approval), post the reply and skip the push",
                              "push #6216 (dismisses the reviewer's approval), post the reply and do the push tomorrow",
                              "push #6216 (dismisses the reviewer's approval), then watch #6215",
                              # review-loop r2: a name after the dismissal holds no digit, so no PR.
                              "push (dismisses the reviewer's approval), post the reply on PR6215",
                              "push (dismisses the reviewer's approval), post the reply on PR-6215",
                              "push (dismisses the reviewer's approval), post the PR6215 reply"))]:
            with self.subTest(text=text):
                self.assertIn(why, self.reason("gh stack push", said=("fix it", self.offer(
                    {"class": "stop:push", "text": text}, text="Push?\n\n"), "a")))
        for text in ("push #6216 (dismisses the reviewer's approval), run CI, update both PR descriptions",
                     "push (dismisses the reviewer's approval), then re-verify and watch CI",
                     "yes: push #6216 (dismisses the reviewer's approval), post the 3 replies, resolve both threads",
                     # review-loop r1: a count or an approver's login with a digit names no PR.
                     "yes: push (dismisses the reviewer's approval), post the 3 replies, resolve both threads",
                     "push (dismisses reviewer2's approval), post the reply",
                     "push (dismisses the reviewer's approval), then post the CodeRabbit reply and resolve its thread, "
                     "re-request the reviewer's review"):
            with self.subTest(text=text):
                self.assertIsNone(self.reason("gh stack push", said=("fix it", self.offer(
                    {"class": "stop:push", "text": text}, text="Push?\n\n"), "a")))
        # review-loop r2: PRs count only in the push steps, so a count in the dismissal names none.
        self.assertIsNone(self.reason("gh stack push", said=("push (dismisses 2 approvals), post 3 replies",)))
        scenario = json.loads(pathlib.Path(self.env["FAKE_GH"]).read_text())
        scenario["prs"]["6215"] = self.pull(6215, self.BRANCH, self.remote_head, [self.APPROVED])
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps(scenario))
        self.assertIsNotNone(self.reason("gh stack push", said=("push (dismisses 6215-6216 approvals), post the reply",)))
        # review-loop r3: a PR in the dismissal, or a base the push goes onto, names no pushed PR.
        for said in [("push (dismisses PR 6215's approval)",), ("push (dismisses PR6215's approval)",),
                     ("rebase #6216 onto 6215 and push (dismisses the reviewer's approvals), post the reply",)]:
            with self.subTest(said=said[0]):
                self.assertIsNotNone(self.reason("gh stack push", said=said))
        # Only a push takes the "yes:" lead; merge_go doesn't change.
        import merge_go
        self.assertFalse(merge_go.literal_go("yes: merge it"))

    def five(self):
        """The Nov 26, 2026 push: five PRs move, and the teammate approved #6179 and #6213."""
        prs = {str(n): self.pull(n, self.BRANCH, self.remote_head, [self.APPROVED] if n in (6179, 6213) else [])
               for n in (6153, 6179, 6213, 6225, 6248)}
        scenario = json.loads(pathlib.Path(self.env["FAKE_GH"]).read_text())
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps({**scenario, "prs": prs}))

    def test_replays_the_three_refused_goes_on_five_prs(self):
        # Nov 26, 2026 (transcript 467a616c): the user's goes at 06:42:03 and 06:45:18 picked
        # these options, and at 06:46:20 typed the push, answering a reply whose option a
        # said the dismissal. The gate refused all three; only the 06:46 option's wording passed.
        self.five()
        named = "push #6153, #6179, #6213, #6225 and #6248 (dismisses the teammate's approval)"
        pick = lambda text, cls="stop:push": ("fix it", self.offer({"class": cls, "text": text}, text="Push?\n\n"), "A")
        typed = "push #6153, #6179, #6213, #6225 and #6248"
        for said in [pick("yes: push all five PRs, dismissing the teammate's approvals on #6179 and #6213"),
                     pick("push #6153, #6179, #6213, #6225 and #6248 (dismisses the teammate's approval on #6179 and #6213)"),
                     pick(named), pick(named)[:2] + (typed,),
                     pick("yes: push all five PRs, dismissing the teammate's approvals on #6179 and #6213")[:2] + (typed,),
                     pick("push the stack (dismisses the teammate's approvals on #6179 & #6213)"),
                     pick("push #6153 (dismisses the teammate's approval on #6179 and #6213), post the reply"),
                     (typed + " (dismisses the teammate's approval on PR #6179 and #6213)",)]:
            with self.subTest(said=repr(said)[-240:]):
                self.assertIsNone(self.reason("gh stack push", said=said))
        for said, why in [
                # A refusal, a question, or a dismissal that misses a live PR or names one the push doesn't move.
                (pick("don't push #6179 (dismisses the teammate's approval on #6179 and #6213)"), "isn't a plain request"),
                (pick("push #6179 and #6213 (dismisses the teammate's approval on #6179 and #6213)?"), "isn't a plain request"),
                (pick("push all five PRs, dismissing the teammate's approvals on #6179"), "doesn't name #6213"),
                (pick("push all five PRs (dismisses the teammate's approval)"), "doesn't name #6179 and #6213"),
                (pick("push all five PRs, dismissing the teammate's approvals on #6179, #6213 and #6999"),
                 "names #6999 in its dismissal, which this push doesn't move"),
                (pick("push all 5 PRs, dismissing the teammate's approvals on 6179 and 6213"), "isn't a plain request"),
                (pick("push all five PRs, dismissing the teammate's approvals on #6179 and #6213", "stop:post"),
                 "only a stop:push option"),
                # A typed push without the dismissal: only right after a reply whose stop:push option is a go.
                ((typed,), "your reply before it offers no stop:push option that does"),
                (pick(named, "decision")[:2] + (typed,), "offers no stop:push option that does"),
                (pick("push #6153, #6179, #6213, #6225 and #6248 (dismisses the teammate's approval on #6179)")[:2]
                 + (typed,), "offers no stop:push option that does"),
                (pick("push #6153, #6179, #6213, #6225 and #6248 (dismisses the teammate's approval on #6179)"),
                 "doesn't name #6213"),
                (pick(named)[:2] + ("push #6153 and #6179",), "doesn't name #6213"),
                (pick(named)[:2] + ("hold on", claude_wrote("Holding."), typed), "offers no stop:push option"),
                (pick(named)[:2] + ("push #6153, #6179, #6213, #6225 and #6248 tomorrow",), None),
                (pick(named)[:2] + ("rebase the stack",), None)]:
            with self.subTest(said=repr(said)[-240:]):
                reason = self.reason("gh stack push", said=said)
                self.assertIn("which dismisses teammate's approval", reason)
                if why:
                    self.assertIn(why, reason)

    def test_takes_a_typed_push_only_with_its_prs_and_a_true_count(self):
        # review-loop r1 on 7a90b85: a typed push without its dismissal names each PR itself,
        # its verb, not a branch name, pushes, and a count matches the PRs the push moves.
        card = ("fix it", self.offer({"class": "stop:push", "text": "push #6119 (dismisses the teammate's approval)"},
                                     text="Push?\n\n"))
        self.assertIsNone(self.reason("gh stack push", said=card + ("push #6119",)))
        self.assertIn("doesn't name #6119", self.reason("gh stack push", said=card + ("push it",)))
        self.assertIsNotNone(self.reason("gh stack push", said=card + ("rebase #6119 onto push-fixes",)))
        self.five()
        text = "push both PRs, dismissing the teammate's approvals on #6179 and #6213"
        for said in [(text,), ("fix it", self.offer({"class": "stop:push", "text": text}, text="Push?\n\n"), "a")]:
            with self.subTest(said=said[-1]):
                self.assertIn("says 2 PRs, but this push moves 5", self.reason("gh stack push", said=said))

    def test_takes_a_push_restacked_on_its_base(self):
        # Nov 25, 2026, 12:23 (transcript 21e564b0): the user's "a" on #6091's restack.
        self.scenario(n=6091)
        text = "push #6091 restacked on develop (dismisses the teammate's approval), re-request teammate"
        self.assertIsNone(self.reason("gh stack push", said=("fix it", self.offer(
            {"class": "stop:push", "text": text}, text="Push?\n\n"), "a")))
        scenario = json.loads(pathlib.Path(self.env["FAKE_GH"]).read_text())
        scenario["prs"]["6092"] = self.pull(6092, self.BRANCH, self.remote_head, [self.APPROVED])
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps(scenario))
        self.assertIn("doesn't name #6092", self.reason("gh stack push", said=(
            "push #6091 restacked on 6092 (dismisses the teammate's approvals)",)))

    # The reply the user's 11:58:09 "a" answered on Nov 25, 2026 (transcript acdfd830), names
    # replaced: its reviewer-reply disclosure line, `<sub>` and `<br>`, made the gate read the
    # pick as nothing.
    DISCLOSED = (
        "🟡 **Push the new tests to #6215? It dismisses the teammate's approval.**\n"
        "\n"
        "| Problem | the teammate's comment holds in part. The new sign-up, company and recovery tests only read the server HTML, so a field turned controlled again would pass them. |\n"
        "|---|---|\n"
        "| Pick | Push `456f073579`: each of those tests now types, hydrates and submits, as the sign-in test does. |\n"
        "| Proof | 16/16 pass. Making the text fields controlled again fails all four. Lint passes. |\n"
        "| Cost | The repo dismisses approvals on push, so the teammate has to approve again. Thread resolution is also required before merge. |\n"
        "\n"
        "> <sub>`AGENT` Claude Opus 5.5 · on behalf of **the user**</sub><br>\n"
        "> Good catch. The sign-up, company, forgot-password and reset-password tests now type into the server HTML, hydrate, and submit, as the sign-in test does. With the text fields turned controlled again, all four fail.\n"
        ">\n"
        "> <sub>Fixed in: `456f073579`</sub>\n"
        "\n"
        "---\n"
        "\n"
        "**Next**\n"
        "\n"
        "- **`a` → yes: push (dismisses the teammate's approval), post the reply, resolve the thread** · *recommended*\n"
        "- `b` → no: keep the approval, reply that the test change is a follow-up\n"
        "\n"
        "<!-- turn {\"state\":\"stop\",\"needs\":[{\"id\":1,\"kind\":\"decide\",\"name\":\"push the new tests\"},{\"id\":2,\"kind\":\"review\",\"name\":\"reply to the teammate\"}],\"options\":[{\"key\":\"a\",\"class\":\"stop:push\",\"text\":\"yes: push (dismisses the teammate's approval), post the reply, resolve the thread\"},{\"key\":\"b\",\"class\":\"stop:post\",\"text\":\"no: keep the approval, reply that the test change is a follow-up\"}],\"project\":\"password managers\"} -->"
    )

    def test_replays_the_pick_under_a_reviewer_reply_disclosure(self):
        self.scenario(n=6215)
        self.assertIsNone(self.reason("gh stack push", said=("fix it", claude_wrote(self.DISCLOSED), "a")))
        self.assertIn('picks "no: keep the approval, reply that the test change is a follow-up", a stop:post option',
                      self.reason("gh stack push", said=("fix it", claude_wrote(self.DISCLOSED), "b")))

    def test_passes_a_push_that_dismisses_nothing(self):
        # Unchanged: the branch's tip is the PR's head.
        self.scenario(head=self.local)
        self.assertIsNone(self.reason("gh stack push"))
        self.assertIsNone(self.reason("git push origin HEAD"))
        # No live approval: none, only comments, a change request after it, or already dismissed.
        for reviews in [(), [{**self.APPROVED, "state": "COMMENTED"}],
                        [self.APPROVED, {**self.APPROVED, "state": "CHANGES_REQUESTED", "submittedAt": "2026-11-24T11:30:00Z"}],
                        [{**self.APPROVED, "state": "DISMISSED"}],
                        [{**self.APPROVED, "state": "PENDING", "submittedAt": None}]]:
            with self.subTest(reviews=reviews):
                self.scenario(reviews=reviews)
                self.assertIsNone(self.reason("gh stack push"))
                self.assertIsNone(self.reason("git push"))
        # Another reviewer's comment after the approval leaves it live.
        self.scenario(reviews=[self.APPROVED, {"author": {"login": "teammate"}, "state": "COMMENTED",
                                                "submittedAt": "2026-11-24T13:02:09Z"}])
        self.dismisses(self.reason("gh stack push"))
        # No PR: a new branch, a stack branch without one, a tag, and a remote off GitHub.
        self.scenario()
        self.git("checkout", "-q", "-b", "effect-native/next")
        self.assertIsNone(self.reason("git push -u origin effect-native/next"))
        stack = json.loads(pathlib.Path(self.env["FAKE_GH"]).read_text())
        del stack["stack"]["branches"][0]["pr"]
        # review-loop r1 on #104: gh stack view finds PRs best-effort, so one it lists without
        # its PR (an API error it swallowed) is still looked up.
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps(stack))
        self.dismisses(self.reason("gh stack push"))
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps({**stack, "prs": {}}))
        self.assertIsNone(self.reason("gh stack push"))
        self.scenario()
        self.git("tag", "v1")
        self.assertIsNone(self.reason(f"git push origin refs/tags/v1 {self.BRANCH}:refs/tags/v2"))
        self.git("remote", "add", "mirror", "ssh://mirror.example/~/repo.git")
        self.assertIsNone(self.reason(f"git push mirror {self.BRANCH}"))
        self.git("checkout", "-q", self.BRANCH)
        self.git("config", f"branch.{self.BRANCH}.pushRemote", "mirror")  # a bare push goes there
        self.assertIsNone(self.reason("git push"))
        self.dismisses(self.reason("git push origin"))
        self.git("config", "--unset", f"branch.{self.BRANCH}.pushRemote")
        # Not a push: quoted, a heredoc, printed, or help.
        for command in ["echo 'git push'", "git commit -m \"then gh stack push\"", "cat <<EOF\ngit push\nEOF",
                        "echo git push", "gh stack push --help", "git push --dry-run", "git stash push -m x",
                        "grep -n 'stack sync' notes.md"]:
            with self.subTest(command=command):
                self.assertIsNone(self.reason(command))

    def test_reads_each_way_a_command_pushes_the_branch(self):
        self.git("checkout", "-q", "main")
        elsewhere = os.path.join(self.dir, "elsewhere")
        os.makedirs(elsewhere)
        for command in [f"git push origin {self.BRANCH}", f"git push -f origin {self.BRANCH}",
                        f"git push origin +{self.BRANCH}", f"git push origin 'HEAD' {self.local}:refs/heads/{self.BRANCH}",
                        f"git push origin {self.BRANCH}:{self.BRANCH} 2>&1 | tail -3", "git push --all origin",
                        f"cd {{repo}} && git push origin {self.BRANCH}", f"git -C {{repo}} push origin {self.BRANCH}",
                        f"FOO=1 time git push origin {self.BRANCH}", f"if git push origin {self.BRANCH}; then echo ok; fi",
                        "gh stack submit --auto", "gh stack push --remote origin", f"env git push origin {self.BRANCH}",
                        "d=$(cd {repo}/.. && pwd); cd {repo} && gh stack push"]:
            with self.subTest(command=command):
                cwd = self.repo if "{repo}" not in command else elsewhere
                self.dismisses(self.reason(command, cwd=cwd))
        self.git("checkout", "-q", self.BRANCH)
        self.dismisses(self.reason("git push"))
        self.dismisses(self.reason("git push -u origin HEAD"))

    def test_reads_what_git_itself_would_push(self):
        # review-loop r1 on #104: push.default=matching, a configured pushurl, and a deletion,
        # each read by the gate's own refspec rules, as `git push --dry-run --porcelain` reads them.
        self.git("checkout", "-q", "main")
        self.git("config", "push.default", "matching")
        self.dismisses(self.reason("git push origin"))
        self.git("config", "--unset", "push.default")
        self.git("checkout", "-q", self.BRANCH)
        target = "https://github.com/acme/target.git"
        self.git("config", "--add", f"url.{os.path.join(self.dir, 'origin')}.insteadOf", target)
        self.git("remote", "set-url", "--push", "origin", target)
        scenario = json.loads(pathlib.Path(self.env["FAKE_GH"]).read_text())
        scenario["prs"]["6119"].update(self.pull(6119, self.BRANCH, self.remote_head, [self.APPROVED], repo="acme/target"))
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps(scenario))
        self.dismisses(self.reason("git push origin HEAD"))
        self.assertIn("repos/acme/target/pulls?head=acme:", pathlib.Path(self.env["FAKE_GH"] + ".calls").read_text())
        self.git("config", "--unset", "remote.origin.pushurl")
        self.scenario()
        # Deleting the PR's branch moves it; deleting a branch with no PR, or none, moves nothing.
        self.assertIn(f"moves #6119 from {self.remote_head[:10]} to a deletion", self.reason(f"git push origin --delete {self.BRANCH}"))
        self.assertIn("to a deletion", self.reason(f"git push origin :{self.BRANCH}"))
        self.git("push", "-q", "origin", "main:obsolete")
        for command in ["git push origin --delete obsolete", "git push origin :obsolete", "git push origin --delete gone"]:
            with self.subTest(command=command):
                self.assertIsNone(self.reason(command))
        self.assertIsNone(self.reason("git push -q origin HEAD:refs/heads/new-branch"))

    def test_finds_every_pr_a_branch_heads(self):
        # review-loop r1 on #104: a fork's PR on its parent, a second PR from the same head,
        # and two repos' #6119 in one command.
        scenario = json.loads(pathlib.Path(self.env["FAKE_GH"]).read_text())
        upstream = self.pull(6119, self.BRANCH, self.remote_head, [self.APPROVED], base="upstream/app")
        scenario.update(prs={"fork": upstream}, forks={"acme/app": ["upstream/app"]})
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps(scenario))
        self.dismisses(self.reason("git push --force origin HEAD"))
        self.dismisses(self.reason("gh stack push"))
        # review-loop r2: listed by GitHub's exact head=<owner>:<branch> filter, every page, since
        # `gh pr list --head` matches the name in every fork and stops at 30.
        self.assertIn(f"api --paginate repos/upstream/app/pulls?head=acme:{self.BRANCH}&state=open",
                      pathlib.Path(self.env["FAKE_GH"] + ".calls").read_text())
        scenario.update(prs={"other": self.pull(6118, self.BRANCH, self.remote_head),
                             "6119": self.pull(6119, self.BRANCH, self.remote_head, [self.APPROVED])}, forks={})
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps(scenario))
        self.dismisses(self.reason("git push origin HEAD"))
        self.dismisses(self.reason("gh stack push"))
        # A second remote whose repo has its own approved #6119.
        self.git("remote", "add", "other", "https://github.com/acme/other.git")
        self.git("config", "--add", f"url.{os.path.join(self.dir, 'origin')}.insteadOf", "https://github.com/acme/other.git")
        scenario["prs"]["second"] = self.pull(6119, self.BRANCH, self.remote_head, [self.APPROVED], repo="acme/other")
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps(scenario))
        both = "git push origin HEAD && git push other HEAD"
        reason = self.reason(both, said=("push other #6119 (dismisses teammate's approval)",))
        self.assertIn("moves app #6119 from", reason)
        self.assertIn("moves other #6119 from", reason)
        self.assertIn("doesn't name app #6119", reason)
        # merge_go reads one number named twice beside a repo as a possible refusal, so two
        # repos' #6119 get no go in one command; the denial says to push each on its own.
        reason = self.reason(both, said=("push app #6119 and other #6119 (dismisses teammate's approvals)",))
        self.assertIn("two of these PRs share a number, so push each in its own command", reason)
        # review-loop r3: a bare #6119 names neither repo's #6119.
        reason = self.reason(both, said=("push #6119 (dismisses teammate's approvals), post the reply",))
        self.assertIn("doesn't name app #6119 and other #6119", reason)
        self.assertIsNone(self.reason("git push other HEAD", said=("push other #6119 (dismisses teammate's approval)",)))

    def test_a_sync_reads_the_remote_and_branches_gh_stack_does(self):
        # review-loop r1 on #104: gh stack picks the branch's pushRemote over origin, and a
        # lower branch the remote moved ahead fast-forwards, so the approved one above it rebases.
        self.scenario(head=self.local)
        upstream, writer = os.path.join(self.dir, "upstream"), os.path.join(self.dir, "writer")
        subprocess.run(["git", "clone", "-q", "--bare", os.path.join(self.dir, "origin"), upstream], check=True, env=self.env)
        subprocess.run(["git", "clone", "-q", upstream, writer], check=True, env=self.env)
        pathlib.Path(writer, "g").write_text("moved\n")
        self.git("add", ".", cwd=writer)
        self.git("commit", "-qm", "upstream moved", cwd=writer)
        self.git("push", "-q", "origin", "main", cwd=writer)
        self.git("remote", "add", "upstream", "https://github.com/acme/app.git")
        self.git("config", "--add", f"url.{upstream}.insteadOf", "https://github.com/acme/app.git/")
        self.git("config", "remote.upstream.url", "https://github.com/acme/app.git/")
        self.assertIsNone(self.reason("gh stack sync"))  # the branch's remote, origin, whose trunk hasn't moved
        self.git("config", f"branch.{self.BRANCH}.pushRemote", "upstream")
        self.assertIn("to a rebased tip", self.reason("gh stack sync"))
        self.assertIsNone(self.reason("gh stack sync --remote origin"))
        self.git("config", "--unset", f"branch.{self.BRANCH}.pushRemote")
        self.git("config", "--unset", f"branch.{self.BRANCH}.remote")
        self.assertIn("can't pick a remote here without asking", self.reason("gh stack sync"))
        self.git("remote", "remove", "upstream")
        # A two-branch stack: lower, which the remote moved ahead, under the approved branch.
        lower = self.git("rev-parse", "main")
        self.git("push", "-q", "origin", "main:lower")
        subprocess.run(["git", "clone", "-q", os.path.join(self.dir, "origin"), writer + "2"], check=True, env=self.env)
        self.git("checkout", "-q", "lower", cwd=writer + "2")
        pathlib.Path(writer + "2", "h").write_text("lower moved\n")
        self.git("add", ".", cwd=writer + "2")
        self.git("commit", "-qm", "lower moved", cwd=writer + "2")
        self.git("push", "-q", "origin", "lower", cwd=writer + "2")
        self.git("branch", "lower", lower)
        scenario = json.loads(pathlib.Path(self.env["FAKE_GH"]).read_text())
        scenario["stack"]["branches"].insert(0, {"name": "lower", "isMerged": False, "isQueued": False, "needsRebase": False})
        pathlib.Path(self.env["FAKE_GH"]).write_text(json.dumps(scenario))
        self.assertIn(f"moves #6119 from {self.local[:10]} to a rebased tip", self.reason("gh stack sync"))
        self.assertIsNone(self.reason("gh stack push"))

    def test_counts_a_push_git_rejects_now_after_a_fetch(self):
        # review-loop r3: a push git rejects as it stands (behind its remote, or a stale lease)
        # can pass once a pull, fetch, or rebase earlier in the command runs, so then it counts.
        self.git("reset", "-q", "--hard", "HEAD~2")  # behind the PR's head
        self.assertIsNone(self.reason("git push origin HEAD"))  # git rejects it, so it dismisses nothing
        for command in ["git pull --rebase && git push origin HEAD", "git fetch origin && git push --force-with-lease"]:
            with self.subTest(command=command):
                self.assertIn("to a tip an earlier command in this one makes", self.reason(command))
        self.scenario(reviews=())
        self.assertIsNone(self.reason("git fetch && git push origin HEAD"))

    def test_counts_a_branch_an_earlier_command_moves(self):
        # review-loop r1 on #104: the gate reads the tips before the shell runs, so a commit
        # chained before the push passed while the PR's head still matched, then moved it.
        self.scenario(head=self.local)
        self.assertIsNone(self.reason("git push origin HEAD"))
        for command in ["git commit --allow-empty -qm fix && git push -q origin HEAD",
                        "git rebase main; gh stack push", "gh stack rebase && gh stack push"]:
            with self.subTest(command=command):
                self.assertIn(f"moves #6119 from {self.local[:10]} to a tip an earlier command in this one makes",
                              self.reason(command))
        self.scenario(reviews=())  # with no live approval, it still passes
        self.assertIsNone(self.reason("git commit -qm fix && gh stack push"))
        for command in ["git checkout main && git push", "gh stack checkout 12 && gh stack push", "git switch - ; git push"]:
            with self.subTest(command=command):
                self.assertIn("before it pushes, which changes the branches the push reads", self.reason(command))

    def test_a_sync_counts_a_branch_it_rebases(self):
        self.scenario(head=self.local)
        self.assertIsNone(self.reason("gh stack sync"))  # the trunk hasn't moved: nothing to push
        # The trunk moved on the remote, so sync rebases the branch onto it and pushes.
        writer = os.path.join(self.dir, "writer")
        subprocess.run(["git", "clone", "-q", os.path.join(self.dir, "origin"), writer], check=True, env=self.env)
        pathlib.Path(writer, "g").write_text("develop\n")
        self.git("add", ".", cwd=writer)
        self.git("commit", "-qm", "develop moved", cwd=writer)
        self.git("push", "-q", "origin", "main", cwd=writer)
        reason = self.reason("gh stack sync")
        self.assertIn(f"moves #6119 from {self.local[:10]} to a rebased tip, which dismisses teammate's approval", reason)
        self.assertIsNone(self.reason("gh stack push"))  # push doesn't rebase
        self.scenario(head=self.local, needs_rebase=True)
        self.assertIn("to a rebased tip", self.reason("gh stack push && gh stack sync"))

    def test_fails_closed(self):
        self.scenario(broken=True)
        self.assertIn("couldn't check what this push would move (`gh stack view --json` failed: gh: network down)",
                      self.reason("gh stack push"))
        self.assertIn("gh: network down", self.reason("git push"))
        self.scenario()
        # A cd the gate can't read, or one that may not run before the push, as shell_dirs.Walk
        # reads it for merge-gate.py and ready-gate.py. The old parser read `(cd mirror); git
        # push` as a push from mirror, whose remote is off GitHub, and let it through.
        mirror = os.path.join(self.dir, "mirror")
        subprocess.run(["git", "init", "-q", "-b", "main", mirror], check=True)
        self.git("remote", "add", "origin", "ssh://mirror.example/~/repo.git", cwd=mirror)
        for command in ["(cd {repo}/../mirror); git push", "false || cd {repo}/../mirror; git push",
                        "(cd {repo}/../mirror && gh stack push)", "\\cd {repo}/../mirror && git push", "git -C $D push"]:
            with self.subTest(command=command):
                self.assertIn("so the gate can't tell what it pushes", self.reason(command))
        for command, why in [("d=$(pwd); cd $d && gh stack push", "runs `cd $d`, whose directory it can't read"),
                             ("git push origin \"$BRANCH\"", "can't tell which remote or refspec"),
                             ("cd /nonexistent && git push", "No such file or directory")]:
            with self.subTest(command=command):
                self.assertIn(why, self.reason(command))

    def dry_run(self, command, said=(), cwd=None):
        args = [str(HOOKS / self.HOOK), "--dry-run", command]
        if said:
            transcript = pathlib.Path(self.dir, "dry-run.jsonl")
            transcript.write_text("".join(json.dumps(claude_said(text)) + "\n" for text in said))
            args += ["--transcript", str(transcript)]
        env = {k: v for k, v in self.env.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")}
        result = subprocess.run(args, cwd=cwd or self.repo, env=env, capture_output=True, text=True)
        return result.returncode, result.stdout

    def test_dry_run_says_what_the_hook_would(self):
        where = os.path.realpath(self.repo)
        status, out = self.dry_run("gh stack push")
        self.assertEqual(status, 1)
        self.assertTrue(out.startswith(f"{self.BRANCH}: #6119, {self.remote_head[:10]} → {self.local[:10]} (from {where})\n"
                                       "go: no, from no transcript; pass --transcript\n- pushing"), out)
        self.assertTrue(out.endswith("would deny\n"))
        self.assertEqual(self.dry_run("gh stack push", said=("push #6119 (dismisses teammate's approval)",)),
                         (0, f"{self.BRANCH}: #6119, {self.remote_head[:10]} → {self.local[:10]} (from {where})\n"
                             f"go: yes, from {self.dir}/dry-run.jsonl\nwould pass: the user's latest prompt names each dismissal\n"))
        self.scenario(head=self.local)
        self.assertEqual(self.dry_run("gh stack push"), (0, f"{self.BRANCH}: #6119, unchanged (from {where})\n"
                                                            "would pass: no PR this push moves has a live approval\n"))
        self.assertEqual(self.dry_run("gh pr view 6119"), (0, "would pass: no `gh stack push`, `submit`, or `sync`, or "
                                                              "`git push`, outside quotes for the gate to check\n"))


class CardCheck(unittest.TestCase):
    """card-check.py on the stop:push options of real cards."""

    def run_hook(self, *options, active=False):
        reply = "Push?\n\n" + block({"state": "stop", "needs": [{"id": 1, "kind": "decide", "name": "push the fixes"}],
                                      "options": [{"key": key, "class": cls, "text": text}
                                                  for key, (cls, text) in zip("ab", options)]})
        out = subprocess.run([str(HOOKS / "card-check.py")], capture_output=True, text=True, check=True, input=json.dumps(
            {"hook_event_name": "Stop", "last_assistant_message": reply, "stop_hook_active": active})).stdout
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else None

    def test_sends_back_a_push_option_the_gate_would_refuse(self):
        # Real options from Nov 18 to 26, 2026, names replaced: each a pick push-gate refuses.
        for text in ("fix both gaps, push (dismisses the reviewer's approvals), re-verify",
                     "push 837dc2fa0d now, which dismisses the reviewer's approvals on #5805 and #5806",
                     "you merge #6110 and #6076; then I restack #6091 (dismisses the reviewer's approval)"):
            with self.subTest(text=text):
                reason = self.run_hook(("stop:push", text), ("decision", "no: hold it"))
                self.assertIn(f'option a, "{text}", is stop:push, but push-gate would refuse it', reason)
                self.assertIn("Send your whole reply again", reason)
                self.assertIsNone(self.run_hook(("stop:push", text), active=True))  # once per stop

    def test_passes_an_option_the_gate_takes_or_that_asks_for_no_push(self):
        for cls, text in [("stop:push", "yes: push all five PRs, dismissing the reviewer's approvals on #6179 and #6213"),
                          ("stop:push", "push #6153, #6179, #6213, #6225 and #6248 (dismisses the reviewer's approval)"),
                          # No dismissal named: whether one is live is the gate's call, from GitHub.
                          ("stop:push", "push both PRs, re-request the reviewer"), ("stop:push", "force-push the branch"),
                          # review-loop r1 on 7a90b85: a refusal, or an option that asks for no push.
                          ("stop:push", "don't push #6179 (dismisses the reviewer's approval on #6179)"),
                          ("stop:push", "report only the details, which dismisses approvals on #5805 and #5806"),
                          # merge-gate reads a merge go only for a PR with no checks, which a reply can't see.
                          ("stop:merge", "merge only #6080"), ("stop:merge", "mark #12 ready, but do not merge"),
                          ("stop:post", "push #6091 and post the reply, which dismisses the approval")]:
            with self.subTest(text=text):
                self.assertIsNone(self.run_hook((cls, text)))
        for payload in ("", "not json", json.dumps({"last_assistant_message": "no block"})):
            with self.subTest(payload=payload):
                self.assertEqual(subprocess.run([str(HOOKS / "card-check.py")], input=payload, capture_output=True,
                                                text=True, check=True).stdout, "")


class VerdictStamp(unittest.TestCase):
    HOOK = "verdict-stamp.py"

    def output(self, command, **agent):
        payload = {"tool_name": "Bash", "session_id": "s", "tool_input": {"command": command, "description": "d"}, **agent}
        out = subprocess.run([str(HOOKS / self.HOOK)], input=json.dumps(payload), capture_output=True,
                             text=True, check=True).stdout
        return json.loads(out)["hookSpecificOutput"] if out else None

    def test_stamps_only_the_verifier(self):
        for command in ["cd x && ~/skills/verify-work/scripts/record-verdict.sh abc def",
                        '"$d/record-verdict.sh" a b', "# Record Done\n./record-verdict.sh a b",
                        'receipt="$(./record-verdict.sh a b)"', "printf '%s\\n' ';' 'record-verdict.sh'"]:
            with self.subTest(command=command):
                rewritten = self.output(command, agent_id="a1", agent_type="work-verifier")["updatedInput"]
                self.assertEqual(rewritten["description"], "d")
                self.assertEqual(rewritten["command"], "export VERIFY_WORK_HOOK_CONTEXT='{\"session_id\": \"s\", "
                                 "\"agent_id\": \"a1\", \"agent_type\": \"work-verifier\"}'; " + command)
                self.assertIsNone(self.output(command))
                self.assertIsNone(self.output(command, agent_id="a2", agent_type="general-purpose"))
        self.assertIsNone(self.output("ls", agent_id="a1", agent_type="work-verifier"))


def block(value, raw=False):
    """A turn block with value as its JSON, or as its body when raw."""
    return f"<!-- turn {value if raw else json.dumps(value)} -->"


class TurnBlock(unittest.TestCase):
    STOP = {"state": "stop", "needs": [{"id": 3, "kind": "decide", "name": "currency column"}],
            "options": [{"key": "a", "class": "stop:merge", "text": "merge #12 and #13"},
                        {"key": "b", "class": "routine", "text": "run verify-work on #13 again"}]}
    REPLY = "✅ **Verified.**\n\n**Next**\n\n- **`a` → merge #12 and #13** · *recommended*\n\n"

    def reason(self, reply):
        with self.assertRaises(turn_block.Malformed) as caught:
            turn_block.parse(reply)
        self.assertNotIn("\n", str(caught.exception))
        return str(caught.exception)

    def test_reads_each_state(self):
        turn = turn_block.parse(self.REPLY + block(self.STOP) + "\n")
        self.assertEqual(turn, turn_block.Turn("stop", (turn_block.Need(3, "decide", "currency column"),), (
            turn_block.Option("a", "stop:merge", "merge #12 and #13"),
            turn_block.Option("b", "routine", "run verify-work on #13 again")), None, None))
        self.assertEqual(turn.recommended.key, "a")
        done = turn_block.parse("Done.\n" + block({"state": "done", "needs": [], "options": []}))
        self.assertEqual((done.state, done.recommended), ("done", None))
        running = turn_block.parse(block({"state": "running", "needs": [{"id": 1, "kind": "review", "name": "the header"}],
                                          "options": [], "eta": "10 min", "elapsed": "2 min"}))
        self.assertEqual((running.eta, running.elapsed, running.recommended), ("10 min", "2 min", None))
        # eta is optional, since a guess at time left misleads; elapsed is always measured.
        unmeasured = turn_block.parse(block({"state": "running", "needs": [], "options": [], "elapsed": "6 min"}))
        self.assertEqual((unmeasured.eta, unmeasured.elapsed), (None, "6 min"))
        self.assertEqual(turn_block.parse(block({**self.STOP, "options": []})).needs[0].id, 3)
        self.assertEqual(turn_block.parse(block({**self.STOP, "needs": []})).needs, ())
        # Spread over lines, or as the mark and body with other spacing, it still reads.
        self.assertEqual(turn_block.parse("<!--turn\n" + json.dumps(self.STOP, indent=2) + "\n-->").state, "stop")
        self.assertTrue(turn_block.MARK in self.REPLY + block(self.STOP))

    def test_reads_the_project_any_state_names(self):
        """prefrontal-turns' optional `project`, the short name Prefrontal groups by."""
        self.assertEqual(turn_block.parse(block({**self.STOP, "project": "effect-v4"})).project, "effect-v4")
        self.assertEqual(turn_block.parse(block({"state": "done", "needs": [], "options": [],
                                                 "project": "x" * 40})).project, "x" * 40)
        self.assertIsNone(turn_block.parse(block(self.STOP)).project)
        for bad in (3, None, ["effect-v4"], "", " ", "x" * 41):
            with self.subTest(project=bad):
                self.assertEqual(self.reason(block({**self.STOP, "project": bad})),
                                 "project must be text of 1-40 characters")

    def test_reads_standing_items_with_every_state(self):
        """`standing`: the user's items still open from earlier replies that don't block this
        turn's next step, in needs' shape, with ids unique across both lists."""
        keychain = {"id": 5, "kind": "do", "name": "delete the old Keychain item"}
        read = turn_block.Need(5, "do", "delete the old Keychain item")
        running = {"state": "running", "needs": [], "options": [], "elapsed": "2 min"}
        for value in [{**self.STOP, "standing": [keychain]}, {**self.STOP, "needs": [], "standing": [keychain]},
                      {**self.STOP, "options": [], "standing": [keychain]},
                      {"state": "done", "needs": [], "options": [], "standing": [keychain]},
                      {**running, "standing": [keychain]}, {**running, "needs": self.STOP["needs"], "standing": [keychain]}]:
            with self.subTest(value=value):
                turn = turn_block.parse(block(value))
                self.assertEqual(turn.standing, (read,))
                self.assertEqual(turn.needs, turn_block.parse(block({**value, "standing": []})).needs)
                self.assertEqual(turn.items, (*turn.needs, read))
        # Old blocks read exactly as before, and an empty list is the same as none.
        old = turn_block.parse(block(self.STOP))
        self.assertEqual((old.standing, old.items), ((), old.needs))
        self.assertEqual(turn_block.parse(block({**self.STOP, "standing": []})), old)
        self.assertEqual(old, turn_block.Turn("stop", old.needs, old.options, None, None))
        # A pick reads the same, so merge-gate's go doesn't depend on it.
        self.assertEqual(turn_block.picked(self.REPLY + block({**self.STOP, "standing": [keychain]}), "a").cls, "stop:merge")
        # standing alone doesn't make a stop, and done still carries no needs.
        self.assertEqual(self.reason(block({"state": "stop", "needs": [], "options": [], "standing": [keychain]})),
                         "state stop has no options or needs")
        self.assertEqual(self.reason(block({"state": "done", "needs": self.STOP["needs"], "options": [],
                                            "standing": [keychain]})), "state done carries needs")
        need = self.STOP["needs"][0]
        for value, reason in [
            ({**self.STOP, "standing": [{**keychain, "id": 3}]}, "standing[0].id 3 repeats an earlier need"),
            ({**self.STOP, "standing": [keychain, {**keychain, "name": "sign in again"}]},
             "standing[1].id 5 repeats an earlier standing item"),
            ({**self.STOP, "standing": {}}, "standing is not a list"),
            ({**self.STOP, "standing": None}, "standing is not a list"),
            ({**self.STOP, "standing": [3]}, "standing[0] is not a JSON object"),
            ({**self.STOP, "standing": [{**keychain, "label": "x"}]}, 'unknown field "standing[0].label"'),
            ({**self.STOP, "standing": [{"id": 5, "kind": "do"}]}, 'missing field "standing[0].name"'),
            ({**self.STOP, "standing": [{**keychain, "kind": "wait"}]},
             'standing[0].kind "wait" is not one of decide, review, do'),
            ({**self.STOP, "standing": [{**keychain, "id": 0}]}, "standing[0].id 0 is not a whole number of 1 or more"),
            ({**self.STOP, "standing": [{**keychain, "name": "12 34"}]},
             "standing[0].name must be text of 1-80 characters with a word of 3+ letters"),
            ({**self.STOP, "standing": [keychain, keychain], "needs": [need, need]}, "needs[1].id 3 repeats an earlier need"),
        ]:
            with self.subTest(value=value):
                self.assertEqual(self.reason(block(value)), reason)
        for bad in malformed({**self.STOP, "standing": [keychain]}):
            with self.subTest(bad=bad):
                try:
                    turn_block.parse(block(bad))
                except turn_block.Malformed as error:
                    self.assertNotIn("\n", str(error))

    def test_a_missing_list_reads_as_empty_on_running_and_done_only(self):
        """running and done may omit needs, options, and standing, since [] is the only valid
        options for both; a stop still names both lists, and an explicit null is malformed."""
        need = self.STOP["needs"][0]
        running = {"state": "running", "needs": [], "options": [], "elapsed": "2 min"}
        done = {"state": "done", "needs": [], "options": []}
        for full in (running, done, {**running, "needs": [need]}):
            for gone in (("needs",), ("options",), ("needs", "options"), ("standing",)):
                value = {key: item for key, item in full.items() if key not in gone}
                with self.subTest(value=value):
                    # The same Turn as the block with each missing list written as [].
                    self.assertEqual(turn_block.parse(block(value)),
                                     turn_block.parse(block({**value, **{key: [] for key in gone}})))
        kept = turn_block.parse(block({"state": "running", "needs": [need], "elapsed": "2 min"}))
        self.assertEqual((kept.needs, kept.options, kept.standing),
                         ((turn_block.Need(3, "decide", "currency column"),), (), ()))
        # The lists' other rules still hold when one is left out.
        self.assertEqual(self.reason(block({"state": "done", "needs": [need]})), "state done carries needs")
        self.assertEqual(self.reason(block({"state": "running", "options": self.STOP["options"], "elapsed": "2 min"})),
                         "state running carries options")
        self.assertEqual(self.reason(block({"state": "running"})), "state running needs elapsed")
        # A stop names both lists, as before.
        for gone in ("needs", "options"):
            with self.subTest(stop_without=gone):
                self.assertEqual(self.reason(block({key: item for key, item in self.STOP.items() if key != gone})),
                                 f'missing field "{gone}"')
        self.assertEqual(self.reason(block({"state": "stop"})), 'missing field "needs"')
        # A state that isn't one of the three gets no default either.
        self.assertEqual(self.reason(block({"state": "waiting"})), 'missing field "needs"')
        self.assertEqual(self.reason(block({"needs": [], "options": []})), 'missing field "state"')
        # An explicit null is still not a list, in every state.
        for value in (running, done, self.STOP):
            for field in ("needs", "options", "standing"):
                with self.subTest(state=value["state"], null=field):
                    self.assertEqual(self.reason(block({**value, field: None})), f"{field} is not a list")
        # Picks from a stop's options read as before, and a listless done picks nothing.
        self.assertEqual(turn_block.picked(self.REPLY + block(self.STOP), "a").cls, "stop:merge")
        self.assertIsNone(turn_block.picked("Done.\n" + block({"state": "done"}), "a"))

    def test_the_block_is_last_outside_code_blocks_and_alone(self):
        valid = block(self.STOP)
        START = "the turn block must start at the beginning of its own line"
        for reply, reason in [
            ("", "no turn block at the end of the reply"),
            (self.REPLY, "no turn block at the end of the reply"),
            (None, "no turn block at the end of the reply"),
            (valid + "\n\nOne more thing.", "the turn block is not the last thing in the reply"),
            (valid + "\n```\ncode\n```", "the turn block is not the last thing in the reply"),
            (valid[:-3], "the turn block is not closed with -->"),
            # A block in a code block is an example, and an unclosed fence runs to the end.
            (f"```\n{valid}\n```", "no turn block at the end of the reply"),
            (f"~~~~ markdown\n{valid}\n~~~~", "no turn block at the end of the reply"),
            (f"Done.\n```\n{valid}\n", "no turn block at the end of the reply"),
            (f"- step\n  ```\n  {valid}\n  ```\n", "no turn block at the end of the reply"),
            (f"Last time: {valid}\n\n{valid}", "more than one turn block"),
            # Any indent, or a list marker or quote mark before it, puts it in a container, an
            # example, even in a fence in_fence can't see; an earlier example still counts.
            (f"Example:\n\n- ```markdown\n  {valid}\n", START),
            (f"Example:\n\n1. ```\n   {valid}\n", START),
            (f"> {valid}\n", START),
            (f"Here is an example:\n\n    {valid}\n", START),
            (f"Here is an example:\n\n\t{valid}\n", START),
            (f"Example:\n\n    {valid}\n\n{valid}", "more than one turn block"),
            (f"Done. {valid}", START),
            (f"{block('{', raw=True)}\n{valid}", "more than one turn block"),
            (block({**self.STOP, "options": [{"key": "a", "class": "routine", "text": "fix it --> now"}]}),
             "the turn block holds --> or --!>, which ends the comment early"),
            (block('{"state": "stop"} --!> {}', raw=True), "the turn block holds --> or --!>, which ends the comment early"),
        ]:
            with self.subTest(reply=reply):
                self.assertEqual(self.reason(reply), reason)
        # Examples in code blocks don't count, closed by a longer fence or not.
        for fence in ["```", "````", "~~~"]:
            with self.subTest(fence=fence):
                example = f"Shape:\n\n{fence}markdown\n{valid}\n{fence}`\n\n" if fence == "```" else \
                          f"Shape:\n\n{fence}markdown\n{valid}\n{fence}\n\n"
                self.assertEqual(turn_block.parse(example + valid).state, "stop")
        for indent in [" ", "  ", "   "]:
            with self.subTest(indent=indent):
                self.assertEqual(self.reason(f"Done.\n\n{indent}{valid}"), START)
        # At column 0 it's top-level: it closes a list item's unclosed fence, and CRLF is fine.
        self.assertEqual(turn_block.parse(f"Done.\n\n{valid}").state, "stop")
        self.assertEqual(turn_block.parse(f"- ```\n  code\n{valid}").state, "stop")
        self.assertEqual(turn_block.parse(f"Done.\r\n\r\n{valid}\r\n").state, "stop")
        for example in ["Here is an example:\n\n    ", "Example:\n\n- ```markdown\n  ", "1. ```\n   "]:
            with self.subTest(example=example):
                self.assertIsNone(turn_block.picked(f"{example}{valid}\n", "a"))
        # A line of backticks with more after it on the line isn't a fence.
        self.assertEqual(self.reason(f"```inline``` {valid}\n{valid}"), "more than one turn block")
        # A mention in a code span is text, not a block: a reply may talk about the format.
        for mention in ["`<!-- turn `", "``<!-- turn {…} -->``", "`` `<!-- turn` ``", "a `x` and `<!-- turn`"]:
            with self.subTest(mention=mention):
                self.assertEqual(turn_block.parse(f"Each reply ends with {mention}.\n\n{valid}").state, "stop")
        # A span opens only on a run the same length closes, and a comment that comes first wins.
        for line in ["`` <!-- turn ` -->", "an unclosed ` then <!-- turn", "<!-- turn `x` -->", "``x` <!-- turn"]:
            with self.subTest(line=line):
                self.assertEqual(self.reason(f"{line}\n\n{valid}"), "more than one turn block")
        # The block itself may hold backticks, and the closing block can't hide in a span.
        self.assertEqual(turn_block.parse(block({**self.STOP, "options": [
            {"key": "a", "class": "routine", "text": "run `verify-work` on #13"}]})).recommended.text, "run `verify-work` on #13")
        self.assertEqual(self.reason(f"Done. `{valid}`"), "no turn block at the end of the reply")

    def test_picked_refuses_a_fence_line_it_cant_place(self):
        valid = block(self.STOP)
        for example, parsed in [
            # A closer or opener indented 4+ isn't one, and a lone CR ends a line, so the
            # example is in a code block.
            ("```markdown\n    ```\n", None),
            ("Example\r```markdown\n", None),
            ("Shape:\n\n    ```\n```\n", None),
            # Fences in a list item, a blockquote, or an HTML block hide from a line reader.
            ("- ```\n  ```\n```\n", "stop"),
            ("> ```\n```\n", None),
            ("<details><summary>x</summary>\n```\n\n```\n", "stop"),
            ("- ```\n  code\n", "stop"),
            ("- item\n\n  ```\n```\n", "stop"),
            ("- x\n  ```\nfoo\n  ```\n", "stop"),
            ("<!--\n\n```\n\n-->\n```\n", "stop"),
        ]:
            with self.subTest(example=example):
                self.assertIsNone(turn_block.picked(example + valid, "a"))
                if parsed:
                    self.assertEqual(turn_block.parse(example + valid).state, parsed)
                else:
                    self.assertEqual(self.reason(example + valid), "no turn block at the end of the reply")
        for reply in [
            f"Done.\n\n```py\nx = 1\n```\n\n{valid}",
            f"<details><summary>x</summary>\n\n```\ncode\n```\n\n</details>\n\n{valid}",
            f"Done.\r\n\r\n```\r\nx\r\n```\r\n\r\n{valid}\r\n",
            f"1. Step\n   ```bash\n   cmd\n   ```\n\n{valid}",
        ]:
            with self.subTest(reply=reply):
                self.assertEqual(turn_block.picked(reply, "a").cls, "stop:merge")
        # The renderer drops one byte-order mark at the very start, so its fence line opens a
        # code block that holds the block; a mark anywhere else stays text.
        for reply in [f"\ufeff```markdown\n{valid}", f"\ufeff~~~\n{valid}"]:
            with self.subTest(reply=reply):
                self.assertIsNone(turn_block.picked(reply, "a"))
                self.assertEqual(self.reason(reply), "no turn block at the end of the reply")
        for reply in [f"\ufeffDone.\n\n{valid}", f"Done.\ufeff\n\n{valid}", f"It costs 5\u00a0kr.\n\n{valid}"]:
            with self.subTest(reply=reply):
                self.assertEqual(turn_block.picked(reply, "a").cls, "stop:merge")
        # T3's importer shows the reply after JS trim(), so a leading run trim drops may open a
        # fence there. A run inside the reply stays, so a line there reads the same both ways.
        for pre in ["\ufeff\ufeff", "\v", "\f", "\u00a0", "\u1680", "\u2000", "\u200a", "\u2028", "\u2029",
                    "\u202f", "\u205f", "\u3000", "\ufeff", "  \u3000", "\t\u3000", "    \u3000", "   \u3000"]:
            with self.subTest(pre=pre):
                self.assertIsNone(turn_block.picked(f"{pre}```markdown\n\n{valid}", "a"))
                self.assertEqual(turn_block.picked(f"Intro.\n{pre}```markdown\n\n{valid}", "a").cls, "stop:merge")
                self.assertEqual(turn_block.picked(f"```\n{pre}```\n```\n\n{valid}", "a").cls, "stop:merge")
        for reply in [f"  ```markdown\n\n{valid}", f"\u3000~~~\n{valid}", f"\n\n    ```\n{valid}",
                      f"\n\u3000\v```\n{valid}"]:
            with self.subTest(reply=reply):
                self.assertIsNone(turn_block.picked(reply, "a"))
        # A closer may trail only spaces and tabs, and trim() reaches no line end before the block.
        for pre, post in [("    ", ""), ("\t", ""), (" \t", ""), ("", "\u3000"), ("", "\u00a0"), ("", "\v")]:
            with self.subTest(pre=pre, post=post):
                self.assertEqual(turn_block.picked(f"```\n{pre}```{post}\n```\n\n{valid}", "a").cls, "stop:merge")
        self.assertEqual(turn_block.picked(f"\u3000Done.\n\n{valid}\n\u3000", "a").cls, "stop:merge")
        example = f"Shape:\n\n```markdown\n{valid}\n```\n\n{valid}"
        self.assertEqual(turn_block.parse("\ufeff" + example), turn_block.parse(example))
        self.assertEqual(turn_block.lines_ended("\ufeff\ufeffa\r\nb\rc\ufeff"), "\ufeffa\nb\nc\ufeff")

    @unittest.skipIf(shutil.which("node") is None, "node isn't installed")
    def test_js_space_is_what_js_trim_drops(self):
        script = ("let s = ''; for (let i = 0; i < 0x10000; i++) { const c = String.fromCharCode(i); "
                  "if ((c + 'a' + c).trim() === 'a') s += c; } process.stdout.write(JSON.stringify(s))")
        found = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(found), turn_block.JS_SPACE)

    def test_picked_refuses_replies_whose_raw_html_may_hide_the_block(self):
        valid = block(self.STOP)
        # The renderer reads raw HTML by HTML's rules, not CommonMark's: an open <title> or
        # <textarea> holds the rest as text, and only </textarea> ends a textarea.
        for example in [
            *[f"Example:\n\n<{tag}>\n" for tag in ["textarea", "script", "style", "pre"]],
            "<title>\n\n",
            "<textarea>\n</pre>\n",
            "<pre>\ncode\n</pre>\n",
            "Write \\`<title>\\` here.\n\n",
            "Wrap it in <PRE class=x>.\n\n",
            # A comment, CDATA, a declaration, or a processing instruction, closed or not.
            "<!-- note\n\n",
            "Note <!-- aside --> here.\n\n",
            "<![CDATA[x]]>\n\n",
            "<?php echo 1 ?>\n\n",
            # A table moves what follows it out of the table, past the block.
            "x <table> y\n\n",
            "<td>\n\n",
            # Codex r1: a template's content isn't shown, and an open fold collapses the options.
            "a → test #12\n\n<template>\n\na → merge #12\n\n",
            'a → test #12\n\n<details id="checks"><summary>Checks</summary>\n\na → merge #12\n\n',
            "<details><summary>Checks</summary>\n\n- ok\n\n</details>\n\n<details>\n\n",
            # Codex r2: a closer in a code span, in an attribute, or before the fold closes nothing.
            'Example: `</details>`.\n\n- `a` → test #12\n\n<details id="checks"><summary>More</summary>\n\n- `a` → merge #12\n\n',
            '<span title="</details>">x</span>\n\n<details><summary>More</summary>\n\nmore\n\n',
            "</details>\n\n<details><summary>More</summary>\n\nmore\n\n",
            # Codex r3: inside these, the parser ignores the </details> that looks like it closes the fold.
            *[f"<details><summary>More</summary>\n\n<{tag}>\n\n- `a` → merge #12\n\n</details>\n\n"
              for tag in ["select", "object", "applet", "marquee"]],
            # An autolink is fine, but not a raw-text tag beside or in it.
            "See <https://x.y> or <title>.\n\n",
            "See <ab:`> and `<title>`.\n\n",
            "See <ab:<title>.\n\n",
            # A line that starts with HTML keeps its HTML block open to the next blank line, past a fence.
            "<details><summary>x</summary>\n```\ncode\n```\n\n</details>\n\n",
            "<details>\n<summary>x</summary>\n\nmore\n\n</details>\n\n",
            "</details>\n",
            # And hands an unclosed tag to the renderer raw, whose attribute takes what follows.
            '<div title="x\n\n',
            # review-loop r1: an inline tag's attribute that runs onto the next lines takes the
            # visible option, at a line's start or mid-line.
            '<span title="Choose:\n    - **`a` → merge #12**\n">\n- `b` → keep\n\n',
            'Choose <span title="x\n    - **`a` → merge #12**\n">\n- `b` → keep\n\n',
            '<span a="b>\nmore\n\n',
            "</ x\nmore\n\n",
            # review-loop r2: a line that starts with a tag other than an attribute-free
            # formatting one may hide the options after it, closed before the block or not.
            '<sub>Info</sub><details><summary>Options</summary>\n- **`a` → merge #12**\n</details>\n\n',
            '<span></span><h2 class="sr-only">\n- **`a` → merge #12**\n</h2>\n\n',
            '<span></span><h2 class="sr-only">\n\n- **`a` → merge #12**\n\n</h2>\n\n',
            '<sub class="x">a</sub> b\n\n',
            '<span title="a > b">x</span>\n\n',
            "- <span>x</span>\nmore\n\n",
            '<source src="movie.mp4"><br>\nmore\n\n',
            # Any < in inline code counts: a link destination can take a span's backtick.
            "Use `a\nb` <title> `c`\n\n",
            # The link takes the first backtick, so <plaintext> is raw and the block is text.
            "[x](/`) <plaintext> `\n\n",
        ]:
            with self.subTest(example=example):
                self.assertEqual(turn_block.parse(example + valid).state, "stop")
                self.assertIsNone(turn_block.picked(example + valid, "a"))
        mermaid = "```mermaid\nflowchart LR\n  a --> b\n```\n\n"
        for example in [
            "✅ **Verified.**\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n---\n\n",
            mermaid,
            "<details><summary>Checks: ✅ 3 passed</summary>\n\n- ok\n\n</details>\n\n",
            "<details open><summary>x</summary>\n\nmore\n\n</details>\n\n",
            "<details>\n\n<summary>x</summary>\n\nmore\n\n</details>\n\n",
            "<DETAILS>\n\nx\n\n</DETAILS>\n\n",
            "```html\n<title>\n```\n\n",
            "See <https://x.y>.\n\n",
            "1 of 1 needs you · Expo 58 <t3-thread://v2/0c5f/mcp:a0dc8ad7-3238>\n\n**Problem**: x\n\n",
            # Tags that hide nothing: whole tags, in a fold's summary, in prose, or in inline code.
            "<details><summary>Checks: ⚠️ <code>xhigh</code> unmeasured</summary>\n\nmore\n\n</details>\n\n",
            "<details><summary>a <b>bold</b> fold</summary>\n\nx\n\n</details>\n\n",
            "<details><summary>See <ab:b></summary>\n\nx\n\n</details>\n\n",
            # Codex r3: a fold opened and closed on one line.
            "<details><summary>Checks: OK</summary></details>\n\n",
            '<details open><summary>a</summary>x</details>\n\n',
            "- Example gap: JSX text such as `<p>save as Draft</p>` is read as a cast.\n\n",
            "Line one<br>\nline two\n\n",
            "Returns `Option<T>`, or ``a ` <b>`` when empty.\n\n",
            "Run `` then `x < y`.\n\n",
            "It returns `Effect<A, E, R>` and `Map<string, Array<number>>`.\n\n",
            # Not autolinks, and not tags CommonMark reads, so they render as text.
            "See <ab:b.\n\n",
            "See <<ab:b>.\n\n",
            "See <a:b>.\n\n",
            "x < y and a <b c\n\n",
            # Lines that start no HTML block by CommonMark's conditions 6 and 7, such as the kit's
            # reviewer-reply disclosure line, which on Nov 25, 2026 cost the user a typed push go.
            "> <sub>`AGENT` Claude Opus 5.5 · on behalf of **the user**</sub><br>\n> Good catch.\n>\n"
            "> <sub>Fixed in: `456f073579`</sub>\n\n",
            "<details><summary>x</summary>\n\n- thread <t3-thread://v2/a/b>, PR <https://github.com/o/r/pull/1>\n\n</details>\n\n",
        ]:
            with self.subTest(example=example):
                self.assertEqual(turn_block.picked(example + valid, "a").cls, "stop:merge")
        self.assertEqual(turn_block.in_fence(["</details>"]), [False])
        # Raw HTML in the block itself doesn't count.
        option = {"key": "a", "class": "stop:merge", "text": "merge <T> #12"}
        self.assertEqual(turn_block.picked(f"Done.\n\n<!--turn\n{json.dumps({**self.STOP, 'options': [option]})}\n-->",
                                           "a").text, "merge <T> #12")

    def test_rejects_bad_json(self):
        for body, reason in [
            ("{", "not JSON: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"),
            ('{"state": NaN}', "not JSON: NaN"),
            ('{"state": "stop", "state": "done", "needs": [], "options": []}', 'field "state" appears twice'),
            ('{"state": "stop", "needs": [{"id": 1, "id": 2, "kind": "do", "name": "the key"}], "options": []}',
             'field "id" appears twice'),
            ('{"": 1, "": 2}', 'field "" appears twice'),
            ("[" * 100000 + "]" * 100000, None),
            ("[]", "the turn block is not a JSON object"),
        ]:
            with self.subTest(body=body[:40]):
                found = self.reason(block(body, raw=True))
                if reason:
                    self.assertEqual(found, reason)
                else:
                    self.assertTrue(found.startswith(("not JSON: ", "the turn block is not")), found)

    def test_rejects_each_bad_field(self):
        need = {"id": 3, "kind": "decide", "name": "currency column"}
        option = {"key": "a", "class": "routine", "text": "run verify-work"}
        stop = {"state": "stop", "needs": [need], "options": [option]}
        running = {"state": "running", "needs": [], "options": [], "eta": "10 min", "elapsed": "2 min"}
        cases = [
            ({**stop, "option": []}, 'unknown field "option"'),
            ({**stop, "": 1}, 'unknown field ""'),
            ({**stop, "needs": [{**need, "": 1}]}, 'unknown field "needs[0]."'),
            ({**stop, "needs": [{**need, "label": "x"}]}, 'unknown field "needs[0].label"'),
            ({"state": "stop", "options": [option]}, 'missing field "needs"'),
            ({**stop, "options": [{"key": "a", "text": "x"}]}, 'missing field "options[0].class"'),
            ({**stop, "state": "waiting"}, 'state "waiting" is not one of stop, done, running'),
            ({**stop, "state": ["stop"]}, 'state ["stop"] is not one of stop, done, running'),
            ({**stop, "needs": [{**need, "kind": "approve"}]}, 'needs[0].kind "approve" is not one of decide, review, do'),
            ({**stop, "options": [{**option, "class": "merge"}]},
             'options[0].class "merge" is not one of routine, decision, stop:merge, stop:push, stop:post, '
             'stop:prod, stop:credential'),
            ({**stop, "needs": {}}, "needs is not a list"),
            ({**stop, "needs": [3]}, "needs[0] is not a JSON object"),
            ({**stop, "options": "a"}, "options is not a list"),
            ({**stop, "needs": [need, {**need, "name": "null dates"}]}, "needs[1].id 3 repeats an earlier need"),
            ({**stop, "options": [{**option, "key": "b"}]}, 'options[0].key "b" should be "a"'),
            ({**stop, "options": [option, option]}, 'options[1].key "a" should be "b"'),
            ({**stop, "options": [{**option, "key": "A"}]}, 'options[0].key "A" should be "a"'),
            ({**stop, "options": [{**option, "key": k} for k in "abcd"]}, "options has 4 items, at most 3"),
            ({**running, "eta": None}, "eta must be text of 1-40 characters"),
            ({**running, "elapsed": "x" * 41}, "elapsed must be text of 1-40 characters"),
            # Each state's own rules.
            ({key: value for key, value in running.items() if key != "elapsed"}, "state running needs elapsed"),
            ({**running, "options": [option]}, "state running carries options"),
            ({**stop, "eta": "10 min"}, "state stop carries eta"),
            ({"state": "done", "needs": [], "options": [], "elapsed": "1 min"}, "state done carries elapsed"),
            ({"state": "done", "needs": [], "options": [option]}, "state done carries options"),
            ({"state": "done", "needs": [need], "options": []}, "state done carries needs"),
            ({"state": "stop", "needs": [], "options": []}, "state stop has no options or needs"),
            *[({**stop, "needs": [{**need, "id": bad}]}, f"needs[0].id {json.dumps(bad)} is not a whole number of 1 or more")
              for bad in (0, -1, 1.0, True, "3", None)],
            *[({**stop, "needs": [{**need, "name": bad}]},
               "needs[0].name must be text of 1-80 characters with a word of 3+ letters")
              for bad in ("", "  ", "3", "a b", "12 34", "x" * 81, 3, None)],
            *[({**stop, "options": [{**option, "text": bad}]}, "options[0].text must be text of 1-400 characters")
              for bad in ("", " ", "x" * 401, 1, [])],
        ]
        for value, reason in cases:
            with self.subTest(value=value):
                self.assertEqual(self.reason(block(value)), reason)
        # Names in any script pass, at the length limits.
        for name in ("Währung", "x" * 80, "fix it"):
            self.assertEqual(turn_block.parse(block({**stop, "needs": [{**need, "name": name}]})).needs[0].name, name)
        self.assertEqual(len(turn_block.parse(block({**stop, "options": [
            {**option, "key": k, "text": "x" * 400} for k in "abc"]})).options), 3)

    def test_rejects_every_malformed_value_without_crashing(self):
        for bad in malformed(self.STOP):
            with self.subTest(bad=bad):
                try:
                    turn_block.parse(block(bad))
                except turn_block.Malformed as error:
                    self.assertNotIn("\n", str(error))

    def test_picked_reads_exactly_one_key(self):
        reply = self.REPLY + block(self.STOP)
        option_a, option_b = turn_block.parse(reply).options
        for prompt, option in [("a", option_a), (" A. ", option_a), ("`b`", option_b), ("b!", option_b),
                               ("a, skip 3", None), ("a and b", None), ("a?", None), ("c", None), ("", None),
                               ("ab", None), ("merge it", None), (None, None)]:
            with self.subTest(prompt=prompt):
                self.assertEqual(turn_block.picked(reply, prompt), option)
        self.assertIsNone(turn_block.picked(None, "a"))
        self.assertIsNone(turn_block.picked(self.REPLY, "a"))
        self.assertIsNone(turn_block.picked(reply + "\nmore", "a"))
        self.assertIsNone(turn_block.picked(self.REPLY + block({**self.STOP, "options": self.STOP["options"][:1]}), "b"))

    def test_runs_under_each_python(self):
        for python in PYTHONS:
            with self.subTest(python=python):
                read = subprocess.run([python, "-c", "import sys, turn_block; t = turn_block.parse(sys.argv[1]); "
                                       "print(t.recommended.cls, turn_block.picked(sys.argv[1], 'a').text)",
                                       self.REPLY + block(self.STOP)], cwd=HOOKS, capture_output=True, text=True, check=True)
                self.assertEqual(read.stdout, "stop:merge merge #12 and #13\n")


def last_node(html):
    """html's last node in document order, past whitespace-only text, as rehype-raw parses
    it: a root with no doctype or <html> is a fragment in a <template>."""
    node = html5lib.parseFragment(html, container="template", treebuilder="dom")
    while kids := [kid for kid in node.childNodes if not (kid.nodeType == kid.TEXT_NODE and not kid.data.strip())]:
        node = kids[-1]
    return node


@unittest.skipIf(MarkdownIt is None or html5lib is None, "markdown-it-py or html5lib isn't installed")
class TurnBlockAgainstCommonMark(unittest.TestCase):
    def test_a_pick_is_a_top_level_html_block(self):
        """Whenever picked returns an option, markdown-it-py's last block is an HTML block
        the turn block opens, and its HTML, read by html5lib's WHATWG tokenizer as parse5
        reads it for T3, ends in the block's comment, both as written and after JS trim(), on
        replies built from lines that place fences, HTML blocks, code spans, and the
        characters trim() drops hard."""
        md, rng, picks, unseen = MarkdownIt("commonmark"), random.Random(4), 0, 0
        valid = block({"state": "stop", "needs": [], "options": [{"key": "a", "class": "stop:merge", "text": "merge #12"}]})
        def hidden(text):
            node = last_node(md.render(text))
            return node.nodeType == node.COMMENT_NODE and node.data.startswith(" turn")
        def raw():
            return f"<{rng.choice(['plaintext', 'xmp', 'iframe', 'noembed', 'noframes', 'script', 'title', 'textarea'])}>"
        def trimmed():
            return "".join(rng.choice("\u00a0\u3000\ufeff\v\n \t") for _ in range(rng.randrange(1, 3)))
        def line():
            fence = rng.choice("`~") * rng.choice([3, 4]) + rng.choice(["", "markdown"])
            prefix = rng.choice([" " * rng.randrange(6), "\t", "- ", "1. ", "> ", "  - ", "- > "])
            text = rng.choice([fence, fence, prefix + fence, prefix + fence, prefix + "text", "Shape:", "", "  code",
                             "- item", "<details><summary>x</summary>", "</details>", "<div>", "<span>",
                             "<!-- note", "-->", "<pre>", "</pre>", "<textarea>", "<script>", "<style>",
                             "<title>", "<textarea>\n</pre>", "Use `Option<T>`", "`a\nb` <pre> `c`",
                             raw(), raw(), f"[x](/`) {raw()} `", f"[x](<`>) {raw()} `", f"Use `{raw()}`",
                             "See <t3-thread://v2/a/b>", "<https://x.y> `", f"<ab:b> {raw()}", "`<ab:b>` `",
                             "[x](<ab:b>) <cd:d>", "\\<ab:b> `x`", "- <ab:b>", "<ab:b>", "<ab:`>", "<ab:<b>",
                             # Tags that hide nothing, and the shapes around them that can.
                             "<details><summary>a <code>b</code></summary>", "Use `Effect<A, E>`", "a<br>b",
                             "<code>x</code> y", '<span title="x">', '<div title="x', '<span title="x', '- <div a="',
                             "<b>", "</div>", "</ x", "x </ y", "> <sub>`AGENT` x · on behalf of **y**</sub><br>",
                             "<span>x</span>", "<sub>x</sub> y", "<x-y a=1 b='c' d>", "<DIV CLASS=x", "<p/>", "<hr/>", "<!-- a -->", '<x a="<title>" b=`c>', "<a / =\"x>\"",
                             '<a b="c" d=\'e>\'>', rng.choice(["<body>", "</html>", "</template>", "<table>", "<svg>",
                                                              "<math>", "<select>", "<frameset>", "<head>", "<html>",
                                                              "<template>", "<listing>", "<option>", "<a href=\"x>", "<tr>", "<td>", "<th>",
                                                              "<caption>", "<col>", "<colgroup>", "<tbody>", "</table>"])])
            return rng.choice(["", "", "", trimmed()]) + text + rng.choice(["", "", "", trimmed()])
        for case in range(60000):
            ending = rng.choice(["\n", "\r\n", "\r"])
            reply = "\n".join([line() for _ in range(rng.randrange(1, 8))] + [valid] + rng.choice([[], [""]]))
            reply = (rng.choice(["", "", trimmed()]) + reply).replace("\n", ending)
            if turn_block.picked(reply, "a") is None:
                # A pick only the imported view refuses, and the oracle shows there as text.
                unseen += turn_block.certain(reply) is not None and not hidden(reply.strip(turn_block.JS_SPACE))
                continue
            picks += 1
            with self.subTest(reply=reply):
                live = reply.removeprefix("\ufeff")  # micromark drops one, markdown-it-py doesn't
                token = md.parse(live)[-1]
                self.assertEqual(token.type, "html_block")
                self.assertTrue(token.content.lstrip().startswith(valid), token.content)
                self.assertTrue(hidden(live), md.render(live))
                imported = reply.strip(turn_block.JS_SPACE)
                self.assertTrue(hidden(imported), md.render(imported))
        self.assertGreater(picks, 2000)
        self.assertGreater(unseen, 0)
        # The oracle sees what CommonMark alone misses: the link takes the first backtick, so
        # <plaintext> is raw and the block renders as text.
        shown = "[x](/`) <plaintext> `\n\n" + valid
        self.assertEqual(md.parse(shown)[-1].type, "html_block")
        node = last_node(md.render(shown))
        self.assertEqual(node.nodeType, node.TEXT_NODE)


    def test_html_start_reads_the_specs_html_blocks(self):
        """Every line of CommonMark 0.31.2's HTML-block examples (§4.6, examples 148 to 191)
        that holds a <, alone or behind a list or quote marker, that markdown-it-py starts an
        HTML block on, HTML_START or UNSAFE reads as one too."""
        md = MarkdownIt("commonmark")
        lines = [
            "         <foo><a>",
            "    <!-- foo -->",
            "    </td>",
            "    <div>",
            "    <td>",
            "  <!-- foo -->",
            "  </tr>",
            "  <div>",
            "  <tr>",
            "  if (a < b && a < 0) then {",
            " <div>",
            "- <div>",
            "<!-- Foo",
            "<!-- foo -->*bar*",
            "<!DOCTYPE html>",
            "<![CDATA[",
            "</DIV>",
            "</Warning>",
            "</a>",
            "</code></pre>",
            "</del>",
            "</div>",
            "</i>",
            "</ins>",
            "</pre>",
            "</script>",
            "</script>1. *bar*",
            "</style>",
            "</table>",
            "</td>",
            "</td></tr></table>",
            "</textarea>",
            "</tr>",
            "<?php",
            "<DIV CLASS=\"foo\">",
            "<Warning>",
            "<a href=\"bar\">",
            "<a href=\"foo\">",
            "<del>",
            "<del>*foo*</del>",
            "<div *???-&&&-<---",
            "<div class",
            "<div id=\"foo\"",
            "<div id=\"foo\" class=\"bar",
            "<div>",
            "<div></div>",
            "<div><a href=\"bar\">*foo*</a></div>",
            "<i class=\"foo\">",
            "<pre language=\"haskell\"><code>",
            "<pre>",
            "<script type=\"text/javascript\">",
            "<script>",
            "<style",
            "<style>p{color:red;}</style>",
            "<table>",
            "<table><tr><td>",
            "<td>",
            "<textarea>",
            "<tr>",
            "> <div>",
        ]
        for line in lines:
            for prefix in ("", "> ", "- ", "1. "):
                with self.subTest(line=prefix + line):
                    if any(token.type == "html_block" for token in md.parse(prefix + line + "\n")):
                        self.assertTrue(turn_block.HTML_START.match(prefix + line) or turn_block.UNSAFE.search(line))
        self.assertIsNone(turn_block.HTML_START.match("> <sub>`AGENT` Claude · on behalf of **the user**</sub><br>"))


def claude_said(text):
    return {"type": "user", "message": {"content": text}}


def claude_wrote(*parts, **flags):
    return {"type": "assistant", "isSidechain": False, **flags, "message": {"content": [
        {"type": "text", "text": part} if isinstance(part, str) else part for part in parts]}}


def codex_said(text):
    return {"type": "response_item", "payload": {"type": "message", "role": "user",
                                                 "content": [{"type": "input_text", "text": text}]}}


def codex_wrote(text, phase="final_answer"):
    return {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": phase,
                                                 "content": [{"type": "output_text", "text": text}]}}


class Exchanges(unittest.TestCase):
    FINAL = "Fixed.\n\n" + block({"state": "stop", "needs": [], "options": [
        {"key": "a", "class": "routine", "text": "run verify-work on #87"}]})
    TOOL = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}}
    RESULT = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}

    def read(self, *lines, strict=False, name="transcript"):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, f"{name}.jsonl")
            with open(path, "w") as transcript:
                transcript.writelines((line if isinstance(line, str) else json.dumps(line)) + "\n" for line in lines)
            return transcripts.exchanges(path, strict)

    def test_pairs_each_claude_prompt_with_the_turn_before(self):
        thinking = {"type": "thinking", "thinking": "hm"}
        found = self.read(claude_said("fix the header"), claude_wrote(thinking), claude_wrote("Looking at it."),
                          self.TOOL, self.RESULT, {**claude_said("[Image: 1x1]"), "isMeta": True},
                          claude_wrote(self.FINAL), claude_wrote("side work", isSidechain=True),
                          claude_wrote(thinking), claude_said("a"))
        self.assertEqual(found, [transcripts.Exchange(None, "fix the header"), transcripts.Exchange(self.FINAL, "a")])
        self.assertEqual(turn_block.picked(*found[-1][:2]).text, "run verify-work on #87")
        # Text parts in one entry join; a string content is one text part.
        self.assertEqual(transcripts.reply_text(claude_wrote("one", thinking, "two")), "one\ntwo")
        self.assertEqual(transcripts.reply_text({"type": "assistant", "message": {"content": "done"}}), "done")

    def test_pairs_each_codex_prompt_with_its_final_answer(self):
        found = self.read(codex_said("fix the header"), codex_wrote("Looking at it.", "commentary"),
                          {"type": "response_item", "payload": {"type": "function_call", "name": "shell"}},
                          {"type": "response_item", "payload": {"type": "function_call_output", "output": "ok"}},
                          codex_wrote(self.FINAL),
                          {"type": "event_msg", "payload": {"type": "agent_message", "message": "ignored"}},
                          codex_said("a"))
        self.assertEqual(found, [transcripts.Exchange(None, "fix the header"), transcripts.Exchange(self.FINAL, "a")])

    def test_a_turn_without_text_gives_no_reply(self):
        # Interrupted before any text, and its interrupt marker is a prompt the user didn't type.
        self.assertEqual(self.read(claude_wrote(self.FINAL), claude_said("fix the header"), self.TOOL,
                                   claude_said("[Request interrupted by user]"), claude_said("a")),
                         [transcripts.Exchange(self.FINAL, "fix the header"), transcripts.Exchange(None, ""),
                          transcripts.Exchange(None, "a")])
        self.assertEqual(self.read(claude_wrote("  \n"), claude_wrote({"type": "text", "text": 1}), claude_said("a")),
                         [transcripts.Exchange(None, "a")])

    def test_a_queued_prompt_pairs_with_the_commentary_before_it(self):
        found = self.read(codex_said("fix the header"), codex_wrote("Looking at it.", "commentary"), codex_said("a"),
                          codex_wrote(self.FINAL))
        self.assertEqual(found[-1], transcripts.Exchange("Looking at it.", "a"))
        self.assertIsNone(turn_block.picked(*found[-1][:2]))

    def test_a_command_claude_code_runs_itself_is_no_prompt(self):
        compact = claude_said("<command-name>/compact</command-name>\n            <command-message>compact"
                              "</command-message>\n            <command-args></command-args>")
        compacted = claude_said("<local-command-stdout>Compacted </local-command-stdout>")
        model = claude_said("<command-name>/model</command-name>\n<command-message>model</command-message>\n"
                            "<command-args>opus</command-args>")
        Exchange = transcripts.Exchange
        self.assertEqual(self.read(claude_wrote(self.FINAL), compact, compacted, claude_said("a")),
                         [Exchange(self.FINAL, "a")])
        self.assertEqual(self.read(claude_wrote(self.FINAL), model, claude_said("<local-command-stdout>Set model to "
                                                                                "opus</local-command-stdout>"),
                                   compact, compacted, claude_said("a")),
                         [Exchange(self.FINAL, "a")])
        # A command with no output yet, one whose turn replied, such as a skill, and output with
        # no command before it each stay a prompt.
        self.assertEqual(self.read(claude_wrote(self.FINAL), compact, claude_said("a")),
                         [Exchange(self.FINAL, "/compact"), Exchange(None, "a")])
        self.assertEqual(self.read(claude_wrote(self.FINAL), compact, claude_wrote("Done."), compacted, claude_said("a")),
                         [Exchange(self.FINAL, "/compact"), Exchange("Done.", ""), Exchange(None, "a")])
        self.assertEqual(self.read(claude_wrote(self.FINAL), compacted, claude_said("a")),
                         [Exchange(self.FINAL, ""), Exchange(None, "a")])

    def test_a_line_it_cannot_read_resets_the_reply(self):
        for bad in UNPARSED:
            with self.subTest(bad=bad[:30]):
                self.assertEqual(self.read(claude_wrote(self.FINAL), bad, claude_said("a")),
                                 [transcripts.Exchange(self.FINAL, ""), transcripts.Exchange(None, "a")])

    def test_reads_every_malformed_reply_as_text_or_none(self):
        for entry in (bad for entry in [claude_wrote(self.FINAL), codex_wrote(self.FINAL)] for bad in malformed(entry)):
            with self.subTest(entry=entry):
                self.assertIn(type(transcripts.reply_text(entry)), (str, type(None)))
        for other in [*ENTRIES[:5], None, codex_said("a"), claude_wrote(self.FINAL, isSidechain=True),
                      claude_wrote(self.FINAL, isMeta="false")]:
            self.assertIsNone(transcripts.reply_text(other))

    def test_an_agent_message_with_t3s_sender_note_reads_as_untyped(self):
        # T3 stores the text without the note, so the note alone tells it from a typed one.
        noted = '[T3 Code: the agent in T3 thread "3cce05fc" sent this message, not the user.]\n\nmerge it'
        self.assertEqual(self.read(claude_wrote(self.FINAL), claude_said(noted)), [transcripts.Exchange(self.FINAL, "")])
        session = "0b4c1f3e-5d6a-4e7b-8c9d-0e1f2a3b4c5d"
        with tempfile.TemporaryDirectory() as folder:
            db_path = os.path.join(folder, "statev2.sqlite")
            with contextlib.closing(sqlite3.connect(db_path)) as db, db:
                db.execute("create table orchestration_v2_projection_provider_threads "
                           "(provider_thread_id text, thread_id text, payload_json text not null)")
                db.execute("create table orchestration_v2_projection_runs (run_id text, provider_thread_id text)")
                db.execute("create table orchestration_v2_projection_messages (thread_id text not null, "
                           "run_id text, role text not null, created_at text not null, payload_json text not null)")
                db.execute("insert into orchestration_v2_projection_provider_threads values (?, ?, ?)",
                           ("p-1", "thread-1", json.dumps({"nativeThreadRef": {"nativeId": session}})))
                db.execute("insert into orchestration_v2_projection_messages values (?, ?, ?, ?, ?)",
                           ("thread-1", None, "user", "06:00", json.dumps({"createdBy": "agent", "text": "merge it"})))
            with unittest.mock.patch.object(transcripts.t3_child, "STATE_DB", db_path):
                found = self.read(claude_wrote(self.FINAL), claude_said(noted), strict=True, name=session)
        self.assertEqual(found, [transcripts.Exchange(self.FINAL, "", agent=True)])

    def test_an_agent_sent_prompt_reads_as_untyped_in_strict_mode(self):
        session = "0b4c1f3e-5d6a-4e7b-8c9d-0e1f2a3b4c5d"
        with tempfile.TemporaryDirectory() as folder:
            db_path = os.path.join(folder, "statev2.sqlite")
            with contextlib.closing(sqlite3.connect(db_path)) as db, db:
                db.execute("create table orchestration_v2_projection_provider_threads "
                           "(provider_thread_id text, thread_id text, payload_json text not null)")
                db.execute("create table orchestration_v2_projection_runs (run_id text, provider_thread_id text)")
                db.execute("create table orchestration_v2_projection_messages (thread_id text not null, "
                           "run_id text, role text not null, created_at text not null, payload_json text not null)")
                db.execute("insert into orchestration_v2_projection_provider_threads values (?, ?, ?)",
                           ("p-1", "thread-1", json.dumps({"nativeThreadRef": {"nativeId": session}})))
                db.execute("insert into orchestration_v2_projection_messages values (?, ?, ?, ?, ?)",
                           ("thread-1", None, "user", "06:00", json.dumps({"createdBy": "agent", "text": "a"})))
            with unittest.mock.patch.object(transcripts.t3_child, "STATE_DB", db_path):
                found = self.read(claude_wrote(self.FINAL), claude_said("a"), strict=True, name=session)
            self.assertEqual(found, [transcripts.Exchange(self.FINAL, "", agent=True)])
            self.assertIsNone(turn_block.picked(*found[-1][:2]))
            with unittest.mock.patch.object(transcripts.t3_child, "STATE_DB", os.path.join(folder, "missing", "db")):
                with self.assertRaises(sqlite3.Error):
                    self.read(claude_wrote(self.FINAL), claude_said("a"), strict=True, name=session)
        with self.assertRaises(ValueError):
            self.read(claude_said("a"), strict=True)
        self.assertEqual(transcripts.exchanges("/nonexistent/x.jsonl"), [])


if __name__ == "__main__":
    unittest.main()
