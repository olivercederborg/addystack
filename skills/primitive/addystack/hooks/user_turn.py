"""The user's latest prompt in a hook's session, and the reply it answers, for the gates
that take a go from it: merge-gate.py and push-gate.py. Only the user's own latest
prompt counts. A T3 delegated child never has one, and in T3 a state database it can't
read, or a session no T3 thread owns, gives none, since only T3's database tells another
agent's message from the user's (transcripts.py). Each gate's `--dry-run` builds its hook
payload here, reading the latest prompt from this session's transcript."""
import contextlib, glob, os, sqlite3, sys

import t3_child, transcripts, turn_block


def dry_run_payload(argv, hook):
    """The payload hook's `--dry-run '<command>' [--transcript PATH] [--session ID]` stands
    for: the command, run from the current directory, in this session (CLAUDE_CODE_SESSION_ID
    in Claude Code, CODEX_THREAD_ID in Codex) or the one --session names."""
    usage = f"usage: {hook} --dry-run '<command>' [--transcript PATH] [--session ID]"
    if not argv or argv[0].startswith("-") or len(argv) % 2 == 0:
        sys.exit(usage)
    flags = dict(zip(argv[1::2], argv[2::2]))
    if set(flags) - {"--transcript", "--session"}:
        sys.exit(f"{hook} --dry-run: unknown flag {sorted(set(flags) - {'--transcript', '--session'})[0]}")
    session = flags.get("--session") or os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CODEX_THREAD_ID")
    import hook_parity  # here: only a dry run looks the transcript up
    claude, codex = hook_parity.config.claude_home(), os.environ.get("CODEX_HOME") or "~/.codex"
    found = sorted(glob.glob(f"{claude}/projects/*/{session}.jsonl")
                   + glob.glob(os.path.expanduser(f"{codex}/sessions/*/*/*/rollout-*-{session}.jsonl")),
                   key=os.path.getmtime) if session else []
    return {"tool_input": {"command": argv[0]}, "cwd": os.getcwd(), "session_id": session,
            "transcript_path": flags.get("--transcript") or (found[-1] if found else None)}


def exchanges(payload):
    """The session's exchanges (transcripts.exchanges), whose last prompt is the user's
    latest, or None when no prompt of this session can be a go: a T3 delegated child, or in
    T3, a state database it can't read or a session no T3 thread owns. Raises what
    transcripts raises in T3 when it can't tell who sent a message."""
    in_t3 = t3_child.in_t3()  # where only T3's database tells another agent from the user
    try:
        with contextlib.closing(t3_child.connect()) as db:
            owners = t3_child.threads(db, payload.get("session_id"))
    except sqlite3.Error:
        if in_t3:
            return None
        owners = []
    if any(str(thread).startswith("thread:delegated-task:") for thread, in owners):
        return None
    if in_t3 and not owners:  # T3 can't tell its agents' messages from the user's in a session it doesn't own
        return None
    return transcripts.exchanges(payload.get("transcript_path"), strict=in_t3)


def answered(found):
    """The reply the latest prompt answers: the last one before it, past messages T3 says
    another agent sent (Exchange.agent) that landed in the same turn, such as a worker's
    result that arrived as the user typed. Those messages' own turn blocks never count. Any
    other message in between that got no reply, typed or not, gives None."""
    at = len(found) - 1
    while found[at].reply is None and at and found[at - 1].agent:
        at -= 1
    return found[at].reply


def letter_miss(reply, key):
    """Why the key picks no option of the reply."""
    if reply is None:
        return "no reply of yours came before it"
    try:
        offered = turn_block.options(reply)
    except turn_block.Malformed as error:
        return f"your reply before it has no valid turn block ({error})"
    if all(option.key != key for option in offered):
        return f"your reply before it offers no option {key}"
    return ("the gate can't be sure your reply's turn block was hidden: it has raw HTML that can hide it, "
            "such as an open <title>, a comment, or a line that starts an HTML block and has no blank line after it, "
            "or a fence line it can't place")
