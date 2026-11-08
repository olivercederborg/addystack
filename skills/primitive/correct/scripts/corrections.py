"""Lists what the user typed into T3, read-only from its state database, so /correct can
mine their corrections. A message counts when T3 recorded the user as its sender and
transcripts.typed() leaves text in it, which drops injected context such as task
notifications and AGENTS.md blocks. Output is TSV, with tabs, newlines, and backslashes
in each field escaped.

  corrections.py [--db PATH] projects
  corrections.py [--db PATH] messages --project TITLE|ID [--since YYYY-MM-DD] [--grep REGEX]

Imported threads (ids starting `import:`) replay native sessions, where T3 records every
prompt as the user's, including agent-run ones such as a `codex exec` reviewer's brief.
Read a row's text before citing it."""
import argparse, collections, datetime, re, sqlite3, sys

import t3_child
import transcripts

USER_MESSAGES = (
    "select m.created_at, m.thread_id, t.title, json_extract(m.payload_json, '$.text'), t.project_id "
    "from orchestration_v2_projection_messages m "
    "join orchestration_v2_projection_threads t on t.thread_id = m.thread_id "
    "where m.role = 'user' and json_extract(m.payload_json, '$.createdBy') = 'user' ")


class ProjectError(Exception):
    pass


def field(value):
    return str(value).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def project_id(db, wanted):
    """The id of the project whose id or title is wanted."""
    found = db.execute("select project_id, workspace_root from projection_projects where project_id = ?1 "
                       "or (title = ?1 and not exists (select 1 from projection_projects where project_id = ?1)) "
                       "order by project_id", (wanted,)).fetchall()
    if not found:
        raise ProjectError(f"no project with id or title {wanted!r}; run `projects` to list them")
    if len(found) > 1:
        raise ProjectError(f"{len(found)} projects are titled {wanted!r}; pass an id instead:\n"
                           + "\n".join(f"  {pid}\t{root}" for pid, root in found))
    return found[0][0]


def day(value):
    """A YYYY-MM-DD date, checked."""
    return datetime.date.fromisoformat(value).isoformat()


def typed_rows(rows):
    for created_at, thread_id, title, text, _ in rows:
        if isinstance(text, str) and (typed := transcripts.typed(text)):
            yield created_at, thread_id, title or "", typed


def projects(db):
    counts = collections.Counter(
        pid for _, _, _, text, pid in db.execute(USER_MESSAGES) if isinstance(text, str) and transcripts.typed(text))
    for pid, title, root in db.execute(
            "select project_id, title, workspace_root from projection_projects order by title, project_id"):
        yield pid, title, root, counts[pid]


def messages(db, project, since=None, grep=None):
    pattern = re.compile(grep, re.I) if grep else None
    rows = db.execute(USER_MESSAGES + "and t.project_id = ? and m.created_at >= ? order by m.created_at, m.message_id",
                      (project_id(db, project), since or ""))
    for row in typed_rows(rows):
        if not pattern or pattern.search(row[3]):
            yield row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=t3_child.STATE_DB, help="T3 state database (default: %(default)s)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("projects", help="each project's id, title, workspace root, and typed-message count")
    listing = commands.add_parser("messages", help="one row per typed message: created_at, thread id, thread title, text")
    listing.add_argument("--project", required=True, help="a project title or id")
    listing.add_argument("--since", type=day, help="only messages on or after this date (YYYY-MM-DD)")
    listing.add_argument("--grep", help="only messages matching this regex, ignoring case")
    args = parser.parse_args(argv)
    t3_child.STATE_DB = args.db
    try:
        db = t3_child.connect()
        try:
            rows = projects(db) if args.command == "projects" else messages(db, args.project, args.since, args.grep)
            for row in rows:
                print("\t".join(field(value) for value in row))
        finally:
            db.close()
    except (ProjectError, sqlite3.Error, re.error) as error:
        print(f"corrections.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
