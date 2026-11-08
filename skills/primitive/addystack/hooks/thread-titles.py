#!/usr/bin/env python3
"""PreToolUse on T3's `delegate_task` and `t3_thread_launch`: refuses a thread whose title
doesn't say what kind it is, so the user, in plain T3 or in a sidebar that groups by
title, can tell a coordinator's workers and review threads apart from the rest.

- **A review**, a `delegate_task` with `role: "review"`, needs a title that starts `◎ `:
  `◎ <PR #N or unit> r<round> · <reviewer model>`, in any thread. The role is the only
  mark a review launch carries, so a child that reviews no PR, plan, or diff takes
  another role. `t3_thread_launch` has no role, so a top-level review started outside a
  coordinator passes unchecked.
- **A coordinator's call** needs a task line that starts exactly `Worker of:
  t3-thread://`, the coordinator's link bare, which is how the kit's hooks
  (`t3_child.py`) find a top-level thread's coordinator, and a title that starts
  `◇ <project> · `, or `◎ ` on a launch that reviews. A call is a coordinator's when the
  calling thread's title is `◆ <project>`, after any status emoji, read from T3's state
  database, or, when the database can't name the caller, when the task opens as a
  worker's brief does (`t3_child.worker_project`). The project comes from the brief's
  opening `Project:` line, else from the `◆` title. An idle
  launch counts as an empty brief, since the `t3_thread_send` that starts it skips this
  hook.

Every other call, and any doubt (outside T3, an input it doesn't expect, a database it
can't read), passes. Claude transcripts from Oct 24 to Nov 7, 2026 hold 2,428
`delegate_task` and 88 `t3_thread_launch` calls. None of the 1,424 with `role: "review"`
was titled `◎`, and about half were eval graders and players, scope judges, or sketchers,
which now take other roles. The hook would refuse 409 of the 410 calls from `◆` threads,
and 149 of them, 87 of its 108 reviews among them, lacked the bare `Worker of:` line; it
refuses none of the 790 non-review calls from other threads. Codex's hook docs
(learn.chatgpt.com/docs/hooks, Nov 2026) say PreToolUse covers MCP tools, and calls made
from code mode's JavaScript. A live Codex run on Nov 8, 2026 confirmed it: called from
code mode as `mcp__t3_code__delegate_task`, which the Codex entry's name-suffix matcher
catches, a review titled "plain review test" was refused and one titled `◎ ` passed."""
import json, os, pathlib, re, sqlite3, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import t3_child  # noqa: E402

REVIEW = "◎ "
WORKER = "◇ "
_COORDINATOR = re.compile(r"\A(?:[^\w\s]+ )?◆ (\S.*)\Z")


def own_title(session_id):
    """The title of the T3 thread that runs this session, or None in doubt."""
    if not isinstance(session_id, str) or not session_id:
        return None
    try:
        db = t3_child.connect()
        try:
            owners = t3_child.threads(db, session_id)
            if len(owners) != 1:
                return None
            row = db.execute("select title from orchestration_v2_projection_threads where thread_id = ?",
                             owners[0]).fetchone()
        finally:
            db.close()
    except sqlite3.Error:
        return None
    return row[0] if row and isinstance(row[0], str) else None


def project(brief, session_id):
    """The coordinator project this call starts a worker for, or None when it isn't one. The
    caller's title decides when T3 names it, so a worker that hands its own brief lines on
    passes; the brief's opening lines decide only when it can't."""
    title = own_title(session_id)
    if title is None:
        return t3_child.worker_project(brief)
    coordinator = _COORDINATOR.match(title.strip())
    if not coordinator:
        return None
    return t3_child.worker_project(brief) or coordinator.group(1).strip()


def refusal(tool, tool_input, session_id):
    """Why this call is refused, in a sentence or two, or None when it passes."""
    if tool.endswith("delegate_task"):
        brief = tool_input.get("task")
    elif tool.endswith("t3_thread_launch"):
        # An idle launch has no message; a later t3_thread_send would skip this hook.
        brief = tool_input.get("message", "")
    else:
        return None
    title = tool_input.get("title")
    title = title.strip() if isinstance(title, str) else ""
    review = tool.endswith("delegate_task") and tool_input.get("role") == "review"
    # A launch has no role, so its title alone can mark it a review.
    launched_review = (REVIEW,) if tool.endswith("t3_thread_launch") else ()
    name = project(brief, session_id) if isinstance(brief, str) else None
    missing = []
    review_title = f"`{REVIEW}<PR #N or unit> r<round> · <reviewer model>`"
    untitled_review = review and not title.startswith(REVIEW)
    if untitled_review:
        missing.append(f"the title {review_title}, such as `◎ #312 r1 · gpt-6.1-terra`")
    elif name and not review and not title.startswith((f"{WORKER}{name} · ",) + launched_review):
        how = review_title if launched_review else f'`role: "review"` and {review_title}'
        missing.append(f"the title `◇ {name} · <unit>` ({how} for a review)")
    if name and not t3_child._WORKER_OF.search(brief):
        missing.append("a task line starting exactly `Worker of: t3-thread://`, this thread's link bare")
    if not missing:
        return None
    kind = "A review" if review else "A coordinator's worker"
    other_role = " A child that reviews no PR, plan, or diff takes another role." if untitled_review else ""
    return f"{kind} needs {' and '.join(missing)}, so the sidebar and the kit's hooks find it.{other_role}"


def main():
    # Outside T3 Code there are no T3 threads to start.
    if not os.environ.get("T3CODE_CLI_PATH"):
        return
    payload = json.load(sys.stdin)
    tool, tool_input = payload.get("tool_name"), payload.get("tool_input")
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        return
    reason = refusal(tool, tool_input, payload.get("session_id"))
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))


try:
    main()
except Exception:  # noqa: BLE001 — a crash would show a hook error on every T3 call; let the call through instead
    pass
