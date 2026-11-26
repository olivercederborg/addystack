#!/usr/bin/env python3
"""Stop, in Claude Code, off by default: when a top-level thread's reply stops for the user,
queues `/cleanest` as the thread's next message, once per run, so the agent answers the
user's "is this the cleanest, best and most idiomatic long-term solution?" before they type
it. Two hook ids run it, each enabled on its own (`"hooks": {"enable": [...]}`), so each
scope is trialled and measured apart:
- `cleanest-ask`: review-teammate-pr threads, titled `◎ #<number>`, which review-teammate-pr
  sets first, and which post-in-the-matrix's review_thread.py and the trial's baseline count by;
- `cleanest-ask-impl` (`--scope implementation`): every other top-level thread, such as an
  implementation or coordinator thread. Its cards are many, and the user asked on about 1 in
  20 of each shape in the week to Nov 25, 2026, so it fires only where option `a` decides,
  merges, or pushes (IMPLEMENTATION_CLASSES), and a run is shorter: a prompt the user typed
  that isn't the ask starts a new one, since a coordinator's replies rarely end `done`.

It sends only when all of these hold:
- the reply's turn block (turn_block.py) stops with a `review` or `decide` need, and, in
  the implementation scope, option `a`'s class is one of IMPLEMENTATION_CLASSES;
- one top-level T3 thread owns the session, not a delegated child, a coordinator's worker
  (t3_child.py), or a T3 workflow's step, and it's the thread T3CODE_THREAD_ID names, when
  set;
- the thread is in the scope: a review thread, or, for the implementation scope, not one;
- the latest prompt is the user's own (user_turn.py), or a notice that a delegated child,
  such as review-loop's reviewer or a coordinator's worker, or a background task finished
  (CONTINUES); not a PR-watch wake, a coordinator tick, another agent's message, or a
  `/cleanest`;
- the run hasn't asked yet: no prompt in it is a `/cleanest` or the user's own quality-bar
  ask (ASKED), and this hook sent none in it, delivered or cancelled. A run is the turns
  since the last reply whose turn block is `done`; in the implementation scope it also
  starts at the user's last typed prompt that isn't an ask, and needs one: a run an agent's
  prompt started, such as a scheduled task's, doesn't ask;
- in the implementation scope, the card names a `review` or `decide` need the session hasn't
  checked (checked), since a follow-up question the user types about a card starts a new run,
  and a coordinator shows its queued needs for many turns;
- no `/cleanest` it sent to the thread is still queued: T3's run for it, by the run id
  `t3 thread send --json` returns, is `queued`, or T3 has no run for it;
- `/cleanest` is the kit's: Claude Code's commands/cleanest.md holds the kit's
  commands/cleanest.md, which `addystack install` links while either hook id is enabled.

T3 leaves a message that starts with a slash command without its "not from the user"
note (`withMessageSenderNote`), so the agent gets the command's body, the same sentence
the user types. T3's database still records the message as an agent's, and the command's
text matches no go, so the gates that read the user's latest prompt grant nothing on it.

It sends with `t3 thread send <thread> /cleanest`, through the CLI t3_child.cli finds, which
queues it as the thread's next turn. It never blocks the reply and prints nothing: on any doubt or
error it doesn't send; a send it records before running the CLI, so one whose answer is
lost still counts, and then holds the thread's later runs too. Once a card that can fire
reaches a thread in its scope, it appends its decision, a send or a skip with its reason and
its scope, to cleanest-ask.jsonl in the state folder (ADDYSTACK_STATE), which the trial
reads. `cleanest-ask.py [--scope implementation] --dry-run [--transcript PATH] [--session
ID]` prints the decision for this session's last reply and sends nothing."""
import contextlib, json, os, pathlib, re, sqlite3, subprocess, sys, time, uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import t3_child, transcripts, turn_block, user_turn  # noqa: E402

COMMAND = "/cleanest"
REVIEW, IMPLEMENTATION = "review", "implementation"
REVIEW_TITLE = re.compile(r"◎ #\d")
# Option a's classes the implementation scope fires on: a design or plan pick, and a ship gate
# that merges, marks ready, or pushes. In the week to Nov 25, 2026, they were option a on 40 of
# the 47 cards the user asked on in implementation and coordinator threads; a routine step or a
# post to a person was option a on the other 7, and on 438 cards they didn't ask on (R188).
IMPLEMENTATION_CLASSES = ("decision", "stop:merge", "stop:push")
# The user's own quality-bar ask: it matches 129 of the 131 messages R183's broader count found
# (Nov 18-25, 2026), and not the 2 audit requests, nor "long-term" naming a feature. The run
# already has its answer.
ASKED = re.compile(r"cleanest|idiomatic|best[- ]practices?\b|\b(?:best|better|right)\b[^?.\n]{0,40}\blong[- ]?term"
                   r"|\blong[- ]?term\b[^?.\n]{0,20}\b(?:solution|approach|direction|fix|shape|structure|architecture"
                   r"|implementation)\b|necessary for the long[- ]?term", re.I)
# The command the kit ships, which install links into Claude Code's commands/.
KIT_COMMAND = pathlib.Path(__file__).resolve().parent.parent / "commands" / "cleanest.md"
# How T3 starts the notice that a delegated child finished, and Claude Code its notice that a
# background task did: work the run started reporting back, so the card after it continues the run.
CONTINUES = ("Delegated task node:", "<task-notification>")
LOG = pathlib.Path(os.environ.get("ADDYSTACK_STATE", "~/.local/state/addystack")).expanduser() / "cleanest-ask.jsonl"


class Skip(Exception):
    """Why the hook doesn't send, and the review thread once the thread reads as one."""

    def __init__(self, reason, thread=None):
        super().__init__(reason)
        self.thread = thread


def own_command(prompt):
    return prompt.strip().lower().split(" ", 1)[0] == COMMAND


def scoped_thread(session, scope):
    """The id of the top-level thread in scope that owns session; raises Skip."""
    try:
        with contextlib.closing(t3_child.connect()) as db:
            owners = t3_child.threads(db, session)
            if len(owners) != 1:
                raise Skip("no single T3 thread owns the session")
            thread = owners[0][0]
            row = db.execute("select title, json_extract(payload_json, '$.lineage.workflowStep') "
                             "from orchestration_v2_projection_threads where thread_id = ?", (thread,)).fetchone()
    except sqlite3.Error as error:
        raise Skip(f"can't read T3's state database ({error})") from None
    named = os.environ.get("T3CODE_THREAD_ID", "").strip()
    if named and named != thread:
        raise Skip("T3CODE_THREAD_ID names another thread")
    if str(thread).startswith("thread:delegated-task:") or t3_child.delegated_brief(session) is not None:
        raise Skip("a delegated child")
    if row and row[1]:  # a T3 workflow's unattended step, whose prompts T3 records as the system's
        raise Skip("a workflow step")
    review = bool(row and isinstance(row[0], str) and REVIEW_TITLE.match(row[0]))
    if scope == REVIEW and not review:
        raise Skip("not a review thread")
    if scope == IMPLEMENTATION and review:
        raise Skip("a review thread")
    return thread


def sends(thread):
    """The log's sends to thread, oldest first: each send's last row, by its id, that still
    says it was sent. A send is recorded before the CLI runs, so one whose outcome is unknown,
    such as a timeout, counts as sent."""
    try:
        lines = LOG.read_text().splitlines()
    except FileNotFoundError:
        return []
    latest = {}
    for at, line in enumerate(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("thread") == thread:
            latest[row.get("send") or at] = row
    return [row for row in latest.values() if row.get("sent") is True]


def queued(run):
    """Whether T3's run for a send is still queued; a run T3 doesn't know counts as queued."""
    if not isinstance(run, str):
        return True
    with contextlib.closing(t3_child.connect()) as db:
        status = db.execute("select status from orchestration_v2_projection_runs where run_id = ?", (run,)).fetchone()
    return status is None or status[0] == "queued"


def asks(prompt):
    """Whether prompt is a /cleanest or the user's own quality-bar ask."""
    return own_command(prompt) or bool(ASKED.search(prompt))


def decision(need):
    """What names a need's decision across cards: its id and its name. An id alone misleads: in
    the week to Nov 25, 2026, 197 of the implementation scope's 362 replayed sends shared a need
    id with a card a /cleanest or the user's ask had checked, but only 55 its id and name; most
    of the rest reused id 1 for another decision. A name alone matched 3 more, needs re-queued
    under a new id, one after a rebase changed it, and the user asked again there (R189)."""
    return need.id, " ".join(need.name.split()).casefold()


def card_needs(reply):
    """The decisions a reply that ends its turn shows: a stop card's needs, none for a done
    reply, or None for progress text, a running reply, or no block."""
    try:
        turn = turn_block.parse(reply or "")
    except turn_block.Malformed:
        return None
    return {decision(need) for need in turn.needs} if turn.state in ("stop", "done") else None


def checked(found):
    """The decisions a /cleanest or the user's quality-bar ask already checked this session:
    each need on the card the ask answered and on the first stop or done reply after the ask
    before the user typed again. Both reach past prompts the user didn't type that landed in the ask's
    turn, such as a worker's result or a task notice, and past progress text."""
    seen = set()
    for at, exchange in enumerate(found):
        if not asks(exchange.prompt):
            continue
        before = at
        while found[before].reply is None and before and not found[before - 1].prompt:
            before -= 1
        seen |= card_needs(found[before].reply) or set()
        for later in found[at + 1:]:
            answer = card_needs(later.reply)
            if answer is not None or later.prompt:
                seen |= answer or set()
                break
    return seen


def ended(exchanges, scope):
    """Whether any of exchanges ends its run: its reply's turn block is done, or, in the
    implementation scope, its prompt is one the user typed that isn't an ask."""
    for exchange in exchanges:
        if scope == IMPLEMENTATION and exchange.prompt and not asks(exchange.prompt):
            return True
        try:
            if exchange.reply is not None and turn_block.parse(exchange.reply).state == "done":
                return True
        except turn_block.Malformed:
            pass
    return False


def latest_raw(path):
    """The text of the transcript's last prompt, typed or not."""
    raw = ""
    with open(path) as transcript:
        for line in transcript:
            try:
                entry = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if transcripts.prompt_text(entry) is not None:
                raw = "\n".join(transcripts.texts(transcripts.text_parts(entry))).strip()
    return raw


def check_run(found, path, thread, session, scope):
    """Raises Skip unless the latest prompt is the user's or a notice that a child or
    background task finished (CONTINUES), this run hasn't asked, the user started it in the
    implementation scope, and nothing sent is queued."""
    latest = found[-1].prompt
    if not latest and not latest_raw(path).startswith(CONTINUES):
        raise Skip("the latest prompt isn't the user's: a wake, a tick, or another agent's message", thread)
    if own_command(latest):
        raise Skip(f"the latest prompt is {COMMAND}", thread)
    typed = False
    for exchange in reversed(found):
        if asks(exchange.prompt):
            raise Skip("this run already asked", thread)
        typed = typed or bool(exchange.prompt)
        if ended([exchange], scope):
            break
    if scope == IMPLEMENTATION and not typed:
        raise Skip("no prompt the user typed started this run", thread)
    earlier = sends(thread)
    # A send this run made, delivered or cancelled: the session held `prompts` prompts then,
    # and nothing since has ended the run.
    if any(row.get("session") == session and isinstance(row.get("prompts"), int)
           and not ended(found[row["prompts"]:], scope) for row in earlier):
        raise Skip("this run already asked", thread)
    try:
        if any(queued(row.get("run")) for row in earlier):
            raise Skip(f"a {COMMAND} this hook sent is still queued", thread)
    except sqlite3.Error as error:
        raise Skip(f"can't read T3's state database ({error})", thread) from None


def decide(payload, scope):
    """The thread to send /cleanest to, how many prompts the session holds, and the T3 CLI to
    send it with; raises Skip."""
    try:
        turn = turn_block.parse(payload.get("last_assistant_message") or "")
    except turn_block.Malformed as error:
        raise Skip(f"no turn block ({error})") from None
    if turn.state != "stop":
        raise Skip(f"the reply is {turn.state}")
    if not any(need.kind in ("review", "decide") for need in turn.needs):
        raise Skip("no review or decide need")
    if scope == IMPLEMENTATION and (turn.recommended is None or turn.recommended.cls not in IMPLEMENTATION_CLASSES):
        raise Skip(f"option a is {turn.recommended.cls}" if turn.recommended else "no option a")
    session = payload.get("session_id")
    thread = scoped_thread(session, scope)
    try:
        found = user_turn.exchanges(payload)
    except (ValueError, sqlite3.Error) as error:
        raise Skip(f"can't tell who sent the latest prompt ({error})", thread) from None
    if not found:
        raise Skip("can't tell who sent the latest prompt", thread)
    check_run(found, payload.get("transcript_path"), thread, session, scope)
    if scope == IMPLEMENTATION and {decision(need) for need in turn.needs
                                    if need.kind in ("review", "decide")} <= checked(found):
        raise Skip(f"a {COMMAND} or the user's ask already checked every decision on the card", thread)
    home = os.environ.get("CLAUDE_CONFIG_DIR", "").strip() or os.path.expanduser("~/.claude")
    try:
        installed = pathlib.Path(home, "commands", "cleanest.md").read_bytes() == KIT_COMMAND.read_bytes()
    except OSError:
        raise Skip(f"{COMMAND} isn't installed; run addystack install", thread) from None
    if not installed:
        raise Skip(f"commands/cleanest.md in {home} isn't the kit's {COMMAND}", thread)
    cli = t3_child.cli()
    if not cli:
        raise Skip("no T3 CLI (T3CODE_CLI_PATH, or t3 on PATH)", thread)
    return thread, len(found), cli


def run_id(output):
    """The run id in `t3 thread send --json`'s output, or None."""
    try:
        run = json.loads(output).get("runId")
    except (ValueError, AttributeError):
        return None
    return run if isinstance(run, str) else None


def log(row, scope):
    """Appends row, with its scope, to the log; False when it can't."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as file:
            file.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "scope": scope, **row}) + "\n")
    except OSError:
        return False
    return True


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
    args = sys.argv[1:]
    scope = IMPLEMENTATION if args[:2] == ["--scope", IMPLEMENTATION] else REVIEW
    args = args[2:] if scope == IMPLEMENTATION else args
    if args[:1] == ["--dry-run"]:
        payload = user_turn.dry_run_payload(["(stop)", *args[1:]], "cleanest-ask.py")
        try:
            payload["last_assistant_message"] = last_reply(payload["transcript_path"]) if payload["transcript_path"] else None
            print(f"would send {COMMAND} to {decide(payload, scope)[0]}")
        except Skip as skip:
            print(f"skip: {skip}")
        except Exception as error:  # noqa: BLE001 - the live hook stays silent on these too
            print(f"skip: error {type(error).__name__}: {error}")
        return
    payload = {}
    try:
        payload = json.load(sys.stdin)
        thread, prompts, cli = decide(payload, scope)
        send = {"session": payload.get("session_id"), "thread": thread, "send": uuid.uuid4().hex, "prompts": prompts}
        # Recorded first, so a send whose answer is lost still counts; none without a record.
        if not log({**send, "sent": True, "run": None}, scope):
            return
        try:
            sent = subprocess.run([cli, "thread", "send", "--json", thread, COMMAND],
                                  capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            log({**send, "sent": True, "run": None, "reason": "t3 thread send timed out; counted as sent"}, scope)
            return
        if sent.returncode:
            log({**send, "sent": False, "reason": f"t3 thread send failed: {(sent.stderr or sent.stdout).strip()[:300]}"}, scope)
            return
        log({**send, "sent": True, "run": run_id(sent.stdout)}, scope)
    except Skip as skip:
        if skip.thread:
            log({"session": payload.get("session_id"), "thread": skip.thread, "sent": False, "reason": str(skip)}, scope)
    except Exception as error:  # noqa: BLE001 - never block the reply
        log({"session": payload.get("session_id") if isinstance(payload, dict) else None,
             "thread": os.environ.get("T3CODE_THREAD_ID"), "sent": False,
             "reason": f"error {type(error).__name__}: {error}"}, scope)


main()
