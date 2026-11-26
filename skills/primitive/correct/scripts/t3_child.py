# Copy of skills/primitive/addystack/hooks/t3_child.py, written by scripts/sync-copies.py: edit the source, then run the script.
"""Finds whether a Claude Code or Codex session is a T3 delegated child, from T3's state
database (T3_STATE_DB overrides its path). A child is a `thread:delegated-task:` thread,
or a coordinator's worker on a linked machine: a top-level thread there whose first user
message an agent wrote, with a line starting "Worker of: ", such as "Worker of:
t3-thread://…" or "Worker of: the ◆ app coordinator (t3-thread://…)".
reply-shape-context.py reads it to skip the reply rules for a child that doesn't opt in.
Any doubt, such as a missing, locked, or changed database, reads as "not a child".

It also lists the messages agents sent into a session's thread, such as an owner's
`t3_thread_send` report, which a transcript records like a message the user typed;
transcripts.py drops them.

And it says whether T3 started this session (in_t3) and where its CLI is (cli), for the
hooks that act only in T3."""
import json, os, pathlib, re, shutil, sqlite3

# T3CODE_HOME moves T3's data directory, as T3's own CLI reads it.
STATE_DB = os.environ.get("T3_STATE_DB") or os.path.join(os.environ.get("T3CODE_HOME") or "~/.t3", "userdata", "statev2.sqlite")
# A coordinator's brief names it on its own line, as a link or by name: 51 Mac worker briefs
# by Nov 25, 2026 start "Worker of: the ◆ … coordinator (t3-thread://…)".
_WORKER_OF = re.compile(r"^Worker of: \S", re.M)
# A brief line that asks for the user's reply rules, as an eval player that plays their session does.
OPT_IN = "Reply rules: on"


def in_t3():
    """True when T3 started this session. On Nov 26, 2026 (t3 v0.1.13), T3's desktop app set
    T3CODE_CLI_PATH on what it starts, Codex's app-server included, and T3CODE_THREAD_ID on
    each Claude Code session; a linked machine's T3 server set only T3CODE_THREAD_ID there,
    and Codex passes only T3CODE_THREAD_ID to a thread's commands, through its per-thread
    shell config. T3's terminal panel sets neither."""
    return bool(os.environ.get("T3CODE_CLI_PATH") or os.environ.get("T3CODE_THREAD_ID"))


def cli():
    """The path of the T3 CLI to run, or None: T3CODE_CLI_PATH, or, in a session T3 started
    without it, `t3` on PATH, where a linked machine installs it."""
    if not in_t3():
        return None
    return os.environ.get("T3CODE_CLI_PATH") or shutil.which("t3")


def rules_on(brief):
    """True when a child's brief has a line starting with OPT_IN."""
    return isinstance(brief, str) and any(line.startswith(OPT_IN) for line in brief.splitlines())


def connect():
    uri = pathlib.Path(STATE_DB).expanduser().resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=1)


def threads(db, session_id):
    # A payload names its own native id and, sometimes, another thread's conversation head.
    return db.execute(
        "select distinct thread_id from orchestration_v2_projection_provider_threads "
        "where json_extract(payload_json, '$.nativeThreadRef.nativeId') = ?1 "
        "or json_extract(payload_json, '$.nativeConversationHeadRef.nativeId') = ?1",
        (session_id,)).fetchall()


def delegated_brief(session_id):
    """The brief of the T3 delegated child that owns this session, or None."""
    if not isinstance(session_id, str) or not session_id:
        return None
    try:
        db = connect()
        try:
            owners = threads(db, session_id)
            if len(owners) != 1:
                return None
            brief = db.execute(
                "select payload_json from orchestration_v2_projection_messages "
                "where thread_id = ? and role = 'user' order by created_at limit 1", owners[0]).fetchone()
        finally:
            db.close()
        payload = json.loads(brief[0]) if brief else None
        text = payload["text"] if brief else None
    except (sqlite3.Error, ValueError, KeyError, TypeError):
        return None
    if not isinstance(text, str):
        return None
    return text if str(owners[0][0]).startswith("thread:delegated-task:") or _worker(payload) else None


def _worker(first):
    """True when an agent wrote this first user message and it names the coordinator it works for."""
    return first.get("createdBy") == "agent" and _WORKER_OF.search(first["text"]) is not None


def senders(session_id, strict=False):
    """For each text, stripped, that an agent sent into this session's thread (such as an
    owner's report, a scheduled prompt, or a wake), who sent each message with that text,
    oldest first: "agent", or "user" when the user sent the same text too. A thread that
    ran on several provider sessions counts only this session's runs, and messages T3
    holds outside any run. Empty when in doubt, or, when strict, an error when the database
    can't be read."""
    if not isinstance(session_id, str) or not session_id:
        return {}
    try:
        db = connect()
        try:
            rows = db.execute(
                "with own as (select provider_thread_id, thread_id from "
                "orchestration_v2_projection_provider_threads "
                "where json_extract(payload_json, '$.nativeThreadRef.nativeId') = ?1 "
                "or json_extract(payload_json, '$.nativeConversationHeadRef.nativeId') = ?1) "
                "select json_extract(m.payload_json, '$.text'), json_extract(m.payload_json, '$.createdBy') "
                "from orchestration_v2_projection_messages m "
                "left join orchestration_v2_projection_runs r on r.run_id = m.run_id "
                "where m.thread_id in (select thread_id from own) and m.role = 'user' "
                "and (m.run_id is null or r.provider_thread_id in (select provider_thread_id from own)) "
                "order by m.created_at", (session_id,)).fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        if strict:
            raise
        return {}
    found = {}
    for text, creator in rows:
        if isinstance(text, str):
            found.setdefault(text.strip(), []).append(creator)
    return {text: creators for text, creators in found.items() if "agent" in creators}


def session_tree(session_id):
    """(driver, native id) for every provider session T3 ran on this session's thread and
    on each child thread below it, recursively, root first. Unlike the rest of this module,
    it raises in doubt: sqlite3.Error when the database can't be read, and LookupError when
    no T3 thread owns the session, since an eval can't let doubt read as zero cost."""
    db = connect()
    try:
        roots = db.execute(
            "select distinct thread_id from orchestration_v2_projection_provider_threads "
            "where json_extract(payload_json, '$.nativeThreadRef.nativeId') = ? order by thread_id",
            (session_id,)).fetchall()
        if not roots:
            raise LookupError(f"no T3 thread ran session {session_id}")
        queue = [thread for thread, in roots]
        seen, sessions = set(queue), []
        while queue:
            thread = queue.pop(0)
            for session in db.execute(
                    "select coalesce(json_extract(payload_json, '$.nativeThreadRef.driver'), driver), "
                    "json_extract(payload_json, '$.nativeThreadRef.nativeId') "
                    "from orchestration_v2_projection_provider_threads where thread_id = ? "
                    "order by first_run_ordinal, provider_thread_id", (thread,)):
                if session[1] and session not in sessions:
                    sessions.append(session)
            # Every origin: a delegate_task child (app_owned) or the provider's own subagent.
            for child, in db.execute(
                    "select child_thread_id from orchestration_v2_projection_subagents "
                    "where thread_id = ? and child_thread_id is not null order by started_at, child_thread_id",
                    (thread,)):
                if child not in seen:
                    seen.add(child)
                    queue.append(child)
    finally:
        db.close()
    sessions.sort(key=lambda session: session[1] != session_id)
    return sessions
