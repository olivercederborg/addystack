#!/usr/bin/env python3
"""Stop, in Claude Code, off by default (`"hooks": {"enable": ["cleanest-ask"]}`): when a
review-teammate-pr thread's reply stops for the user, queues `/cleanest` as the thread's
next message, once per run, so the agent answers the user's "is this the cleanest, best
and most idiomatic long-term solution?" before they type it.

It sends only when all of these hold:
- the reply's turn block (turn_block.py) stops with a `review` or `decide` need;
- one top-level T3 thread owns the session, not a delegated child or a coordinator's
  worker (t3_child.py), and it's the thread T3CODE_THREAD_ID names, when set;
- the thread is a review thread: its title starts `◎ #<number>`, which review-teammate-pr
  sets first, and which post-in-the-matrix's review_thread.py and the trial's baseline
  count by;
- the latest prompt is the user's own (user_turn.py), not a PR-watch wake, a coordinator
  tick, another agent's message, or a `/cleanest`;
- the run hasn't asked yet: no prompt since the last reply whose turn block is `done` is a
  `/cleanest` or the user's own quality-bar ask (ASKED), and no `/cleanest` this hook sent
  in this session is still waiting in T3's queue;
- `/cleanest` is installed: Claude Code's commands/cleanest.md, which `addystack install`
  links to the kit's commands/cleanest.md while this hook is enabled.

T3 leaves a message that starts with a slash command without its "not from the user"
note (`withMessageSenderNote`), so the agent gets the command's body, the same sentence
the user types. T3's database still records the message as an agent's, and the command's
text matches no go, so the gates that read the user's latest prompt grant nothing on it.

It sends with `t3 thread send <thread> /cleanest` (T3CODE_CLI_PATH), which queues it as
the thread's next turn. It never blocks the reply and prints nothing: on any doubt or
error it doesn't send. For review threads it appends each decision, a send or a skip
with its reason, to cleanest-ask.jsonl in the state folder (ADDYSTACK_STATE), which the
trial reads. `cleanest-ask.py --dry-run [--transcript PATH] [--session ID]` prints the
decision for this session's last reply and sends nothing."""
import contextlib, json, os, pathlib, re, sqlite3, subprocess, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import t3_child, transcripts, turn_block, user_turn  # noqa: E402

COMMAND = "/cleanest"
REVIEW_TITLE = re.compile(r"◎ #\d")
# The user's own quality-bar ask, as R183 counted it: the run already has its answer.
ASKED = re.compile(r"cleanest|idiomatic|long[- ]term|best practice", re.I)
LOG = pathlib.Path(os.environ.get("ADDYSTACK_STATE", "~/.local/state/addystack")).expanduser() / "cleanest-ask.jsonl"


class Skip(Exception):
    """Why the hook doesn't send, and the review thread once the thread reads as one."""

    def __init__(self, reason, thread=None):
        super().__init__(reason)
        self.thread = thread


def own_command(prompt):
    return prompt.strip().lower().split(" ", 1)[0] == COMMAND


def review_thread(session):
    """The id of the top-level review thread that owns session; raises Skip."""
    try:
        with contextlib.closing(t3_child.connect()) as db:
            owners = t3_child.threads(db, session)
            if len(owners) != 1:
                raise Skip("no single T3 thread owns the session")
            thread = owners[0][0]
            row = db.execute("select title from orchestration_v2_projection_threads where thread_id = ?",
                             (thread,)).fetchone()
    except sqlite3.Error as error:
        raise Skip(f"can't read T3's state database ({error})") from None
    named = os.environ.get("T3CODE_THREAD_ID", "").strip()
    if named and named != thread:
        raise Skip("T3CODE_THREAD_ID names another thread")
    if str(thread).startswith("thread:delegated-task:") or t3_child.delegated_brief(session) is not None:
        raise Skip("a delegated child")
    if not (row and isinstance(row[0], str) and REVIEW_TITLE.match(row[0])):
        raise Skip("not a review thread")
    return thread


def sent_here(thread, session):
    """How many /cleanest this hook sent to thread in session, from the log."""
    try:
        lines = LOG.read_text().splitlines()
    except FileNotFoundError:
        return 0
    count = 0
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        count += isinstance(row, dict) and row.get("sent") is True and (row.get("thread"), row.get("session")) == (thread, session)
    return count


def check_run(found, thread, session):
    """Raises Skip unless the latest prompt is the user's and this run hasn't asked yet."""
    latest = found[-1].prompt
    if not latest:
        raise Skip("the latest prompt isn't the user's: a wake, a tick, or another agent's message", thread)
    if own_command(latest):
        raise Skip(f"the latest prompt is {COMMAND}", thread)
    for exchange in reversed(found):
        if own_command(exchange.prompt) or ASKED.search(exchange.prompt):
            raise Skip("this run already asked", thread)
        try:
            if exchange.reply is not None and turn_block.parse(exchange.reply).state == "done":
                break
        except turn_block.Malformed:
            pass
    if sent_here(thread, session) > sum(own_command(exchange.prompt) for exchange in found):
        raise Skip(f"a {COMMAND} this hook sent is still queued", thread)


def decide(payload):
    """The thread to send /cleanest to; raises Skip."""
    try:
        turn = turn_block.parse(payload.get("last_assistant_message") or "")
    except turn_block.Malformed as error:
        raise Skip(f"no turn block ({error})") from None
    if turn.state != "stop":
        raise Skip(f"the reply is {turn.state}")
    if not any(need.kind in ("review", "decide") for need in turn.needs):
        raise Skip("no review or decide need")
    session = payload.get("session_id")
    thread = review_thread(session)
    try:
        found = user_turn.exchanges(payload)
    except (ValueError, sqlite3.Error) as error:
        raise Skip(f"can't tell who sent the latest prompt ({error})", thread) from None
    if not found:
        raise Skip("can't tell who sent the latest prompt", thread)
    check_run(found, thread, session)
    home = os.environ.get("CLAUDE_CONFIG_DIR", "").strip() or os.path.expanduser("~/.claude")
    if not os.path.isfile(os.path.join(home, "commands", "cleanest.md")):
        raise Skip(f"{COMMAND} isn't installed; run addystack install", thread)
    if not os.environ.get("T3CODE_CLI_PATH"):
        raise Skip("no T3 CLI (T3CODE_CLI_PATH)", thread)
    return thread


def log(row):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as file:
            file.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **row}) + "\n")
    except OSError:
        pass


def last_reply(path):
    """The last assistant text in the transcript at path, for --dry-run."""
    reply = None
    with open(path) as transcript:
        for line in transcript:
            try:
                reply = transcripts.reply_text(json.loads(line)) or reply
            except (ValueError, RecursionError):
                continue
    return reply


def main():
    if sys.argv[1:2] == ["--dry-run"]:
        payload = user_turn.dry_run_payload(["(stop)", *sys.argv[2:]], "cleanest-ask.py")
        try:
            payload["last_assistant_message"] = last_reply(payload["transcript_path"]) if payload["transcript_path"] else None
            print(f"would send {COMMAND} to {decide(payload)}")
        except Skip as skip:
            print(f"skip: {skip}")
        except Exception as error:  # noqa: BLE001 - the live hook stays silent on these too
            print(f"skip: error {type(error).__name__}: {error}")
        return
    payload = {}
    try:
        payload = json.load(sys.stdin)
        thread = decide(payload)
        sent = subprocess.run([os.environ["T3CODE_CLI_PATH"], "thread", "send", thread, COMMAND],
                              capture_output=True, text=True, timeout=20)
        if sent.returncode:
            raise Skip(f"t3 thread send failed: {(sent.stderr or sent.stdout).strip()[:300]}", thread)
        log({"session": payload.get("session_id"), "thread": thread, "sent": True})
    except Skip as skip:
        if skip.thread:
            log({"session": payload.get("session_id"), "thread": skip.thread, "sent": False, "reason": str(skip)})
    except Exception as error:  # noqa: BLE001 - never block the reply
        log({"session": payload.get("session_id") if isinstance(payload, dict) else None,
             "thread": os.environ.get("T3CODE_THREAD_ID"), "sent": False,
             "reason": f"error {type(error).__name__}: {error}"})


main()
