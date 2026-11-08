#!/usr/bin/env python3
"""UserPromptSubmit: when the user's message names a PR or a Linear issue this session
hasn't seen yet, list the other T3 threads that already hold it, from T3's state
database: threads linked to the PR, and threads whose branch, worktree, or title names
it. A thread whose messages only mention it doesn't count: in the month to Oct 29, 2026
that was the sole match in 111 of the hook's 225 fires on the Mac, and 21 of all 225
were followed by a t3_thread_read within the hour.

In the week to Oct 22, 2026, the user had to ask "don't I already have a PR open for
this?" or "do I already have a thread open for reviewing this?" in 6 threads, while
agents started the work again. Prose in do-it-before-asking.md already said to look.
Delegated children pass, and any doubt about the database lists nothing. Claude Code
only, as additionalContext."""
import json, re, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bare_references, t3_child, transcripts  # noqa: E402

PR_URL = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
LINEAR_URL = re.compile(r"linear\.app/[\w-]+/issue/([A-Z]{2,6}-\d{1,6})")
# The Linear team key that counts bare, without a linear.app URL. A bare "GPT-6" or
# "UTF-8" isn't an issue.
LINEAR = re.compile(r"\b(DEV-\d{1,6})\b", re.I)
SHOWN = 5
RANK = {"linked PR": 0, "title or branch": 1}


def refs(text):
    """The PRs, as ("owner/repo", number), and Linear ids a message names."""
    found = [("pr", repo.lower(), int(number)) for repo, number in PR_URL.findall(text)]  # as T3 keys it
    found += [("linear", issue.upper(), None) for issue in LINEAR_URL.findall(text) + LINEAR.findall(text)]
    return list(dict.fromkeys(found))


def label(ref):
    kind, name, number = ref
    return f"{name}#{number}" if kind == "pr" else name


def exact(ref):
    """Matches ref's whole name, so DEV-30 isn't DEV-3009, nor #52 #5239."""
    kind, name, number = ref
    return re.compile(re.escape(f"{name}/pull/{number}") + r"(?!\d)" if kind == "pr"
                      else r"(?<![\w-])" + re.escape(name) + r"(?!\d)", re.I)


def ranked(rows):
    """Open threads first, before settled or archived ones, then a linked PR before a title
    or branch, then the newest."""
    newest = sorted(rows, key=lambda row: str(row[2] or ""), reverse=True)
    return sorted(newest, key=lambda row: (bool(row[4]), RANK[row[3]]))


def holders(db, ref, own):
    """Other top-level threads that hold ref, as (id, title, updated, why, state). A stack
    link the user dismissed doesn't count."""
    kind, name, number = ref
    exact_ref = exact(ref)
    db.create_function("names_ref", 1, lambda text: bool(exact_ref.search(text or "")), deterministic=True)
    named = ("names_ref(coalesce(t.title, '') || ' ' || coalesce(json_extract(t.payload_json, '$.branch'), '') "
             "|| ' ' || coalesce(json_extract(t.payload_json, '$.worktreePath'), ''))")
    linked = ("(?1 = 'pr' and exists (select 1 from json_each(t.payload_json, '$.pullRequests') p "
              "where json_extract(p.value, '$.repository') = ?2 and json_extract(p.value, '$.number') = ?3 "
              "and coalesce(json_extract(p.value, '$.source'), '') != 'stack-dismissed'))")
    rows = db.execute(
        f"select t.thread_id, t.title, t.updated_at, "
        f"case when {linked} then 'linked PR' else 'title or branch' end, "
        f"case when t.archived_at is not null then 'archived' "
        f"when json_extract(t.payload_json, '$.settledAt') is not null then 'settled' end "
        f"from orchestration_v2_projection_threads t "
        f"where t.deleted_at is null and t.thread_id not like 'thread:%' and ({named} or {linked}) "
        f"order by t.updated_at desc", (kind, name, number)).fetchall()
    return [row for row in rows if row[0] not in own]


def lookup(session_id, new_refs):
    """One context line per ref another thread holds; [] when in doubt."""
    lines = []
    try:
        db = t3_child.connect()
        try:
            own = {thread for (thread,) in t3_child.threads(db, session_id)} if session_id else set()
            for ref in new_refs:
                found = ranked(holders(db, ref, own))
                for thread, title, updated, why, closed in found[:SHOWN]:
                    state = f" · {closed}" if closed else ""
                    lines.append(f"- {label(ref)}: [{title or 'Untitled'}](t3-thread://v1/{thread}) · "
                                 f"{why} · updated {str(updated)[:10]}{state}")
                if len(found) > SHOWN:
                    lines.append(f"- {label(ref)}: {len(found) - SHOWN} older threads too")
        finally:
            db.close()
    except (sqlite3.Error, ValueError, TypeError):
        return []
    return lines


def main():
    try:
        event = json.loads(sys.stdin.read())
    except ValueError:
        return
    prompt = event.get("prompt") or ""
    if not isinstance(prompt, str) or not (named := refs(prompt)) or bare_references.delegated_child(event):
        return
    earlier = transcripts.user_messages(event.get("transcript_path"))
    if earlier and earlier[-1].strip() == prompt.strip():
        earlier = earlier[:-1]
    seen = {ref for message in earlier for ref in refs(message)}
    lines = lookup(event.get("session_id"), [ref for ref in named if ref not in seen])
    if not lines:
        return
    context = ("Other T3 threads already hold what the user's message names:\n" + "\n".join(lines) +
               "\nBefore starting new work on it, read the first of these with t3_thread_read. Then "
               "continue there, or build on what it found, and tell the user which thread holds it, "
               "linked as above.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}))


if __name__ == "__main__":
    main()
