# Status

When the user asks where the project stands, run `scripts/project.py <folder> status`
and show what it prints. It reads `project.md` and live state, and writes nothing: no
file, no plan change, no message, no retry. Show the output, then end the reply on the
queue's top item as step 5 says, or on `no queue` for a project from before the queue.

## What it prints

- **Header**: the project's name and the first line of its Goal.
- **Needs you**: the Queue as `queue show` prints it, `no queue` when project.md has no
  Queue section, or `unread:` and the reason when its table can't be read.
- **Units**, grouped by state: stuck, waiting, overdue, unknown, running, queued, done,
  dropped, then replaced or absorbed. Each Workers row is one item:
  - its worker, linked to its thread as the row stores it;
  - the thread's live status from `t3 thread show`. A row in a final state (done,
    dropped, replaced, absorbed) gets no read. A thread on another machine, or a read
    that fails, shows `unread`;
  - each PR in Branch or PR as `[#N, title](url)`, with its state, draft, and checks
    (`✅ 12 pass`, `❌ 1 fail`, `⏳ 3 pending`, `no checks`, or `checks unread`). A PR from
    another repo than the checkout's is named `owner/repo#N`. A `#N` or `repo#N` whose
    repo the checkout's origin can't tell prints `#N unresolved`, with no `gh` call;
  - the Issue cell as written, when the table has the column and the cell isn't empty;
  - `waits on …` from Waits on.
- **unread rows**: rows whose cells don't match the Workers header, by their first cell.
- **Decisions** and **Phases**: each section's lines as written, or `none`.

A project with no Workers section prints `no workers`. A read that fails is named on
stderr, with the CLI's reason.

## For a program

`status --json` prints the same overview as data, from `status_data(lines, live=True)` in
`scripts/project.py`: `project`, `goal`, `queue` (items, or null with no Queue) and
`queue_unread`, `groups` in the order above, each `{state, units}`, then `unread_rows`,
`decisions`, and `phases`. Text is as project.md holds it, unescaped. `--no-live` skips
`t3` and `gh`, so a unit has no `thread_status` and a PR no `read`, `title`, `state`,
`draft`, or `checks`; it still reads the checkout's origin from git to resolve `#N`.
