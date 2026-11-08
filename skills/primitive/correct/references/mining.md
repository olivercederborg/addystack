# Mining

Where `correct` looks for repeated corrections, and how to cite each occurrence. Every
query here is read-only. Run them from the target repo, with `<base>` as its default
branch (`origin/main`).

## Review-fix commits

The richest code source in the user's own repos: verify-work, review-loop, and
cross-model reviews land as commits whose bodies name the finding.

```bash
git log <base> -i -E --grep='verify-work|review-loop|codex review|claude review|review fix|from review' --format='%h %s%n%b%n--'
git log <base> --grep='^Revert' --format='%h %s'
```

For each hit, open the diff (`git show <sha>`) and find the commit that introduced the
mistake (`git log -S'<pattern>' -- <path>`), since the pre-fix file is the replay proof
in step 4. A later commit that brings back what a fix removed (a `.finally` returning
after its removal) is another occurrence of the same class.

Cite as the fix commit's short SHA.

## PR review comments

```bash
gh pr list --state merged --limit 100 --json number,title
gh api --paginate repos/<o>/<r>/pulls/<n>/comments --jq '.[] | [.user.login, .html_url, .body] | @tsv'
gh api --paginate repos/<o>/<r>/pulls/<n>/reviews --jq '.[] | select(.body != "") | [.user.login, .html_url, .body] | @tsv'
```

Read teammates' comments first; a bot's comment counts when someone acted on it, such as
a fix commit that answers it. Cite as the comment's `html_url`.

## CI failures

```bash
gh run list --status failure --limit 50 --json databaseId,headBranch,displayTitle
gh run view <id> --log-failed
```

A check that failed on several branches for the same reason is a class whose enforcer
already exists; the gap is that agents don't run it before pushing, so the fix is a
pre-commit hook or a local command that matches CI. Cite as the run URL.

## The user's typed corrections in T3

`scripts/corrections.py` reads T3's state database read-only and keeps only what the
user typed:

```bash
python3 <this skill's dir>/scripts/corrections.py projects
python3 <this skill's dir>/scripts/corrections.py messages --project <title|id> --since 2026-09-01
python3 <this skill's dir>/scripts/corrections.py messages --project <id> --grep 'again|instead|not |use the'
```

`--db <path>` reads another state database, such as a copied one or an eval fixture.
`projects` gives each project's id, title, workspace root, and typed-message count; pick
the one whose root is the target repo, by id when two share a title. `messages` prints
`created_at`, thread id, thread title, and the text, with newlines escaped. A comment the
user wrote on a quoted reply reads as their comment, so a correction aimed at one reply
shows as plain text.

Another machine keeps its own T3 database. Stream this machine's script to it, run from
that machine's kit checkout's `hooks/`, which holds the `transcripts.py` and `t3_child.py` it imports
(`python3 -` reads the script from stdin; the arguments follow):

```bash
ssh <machine> 'cd <kit>/hooks && python3 - projects' < <this skill's dir>/scripts/corrections.py
ssh <machine> 'cd <kit>/hooks && python3 - messages --project <id>' < <this skill's dir>/scripts/corrections.py
```

When ssh fails, mark that machine unavailable with that reason.

Threads whose id starts with `import:` replay native sessions, where T3 records every
prompt as the user's, including an agent-run `codex exec` reviewer's brief. Read each
row's text before citing it.

Messages from deleted T3 threads are included, so a cited thread may not open in T3.

Cite as `T3 <thread id> <created_at>`, plus `(<machine>)` for another machine's database.

## Grouping

Group by the shape of the fix: "handle an Effect's failure inside the Effect" is one
class whether the complaint said `try/catch`, `.catch`, or `.finally`. Typed corrections
lean toward UI taste (spacing, tokens, native controls) and commit bodies toward code
shape, so a class seen in only one kind of source is normal.
