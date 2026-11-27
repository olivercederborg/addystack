# Status

When the user asks where the project stands, show the overview inline and change nothing
else: no plan change, no message, no retry.

1. Run `scripts/project.py <folder> status --json` and read it yourself: it's the data
   the page draws, and its `queue` gives the top item the reply ends on.
2. Run `scripts/project.py <folder> status --html`. It writes the page to the temp folder
   and prints its absolute path.
3. Show it with `html_render`, passing that path and a `height` from `html_preview`'s
   `contentHeight`. A thread that can't pass a path passes the file's contents as `html`.
4. End the reply on the queue's top item as step 5 says, or on the missing queue for a
   project from before the queue.

Both runs read `project.md` and live state and never write the project's folder. A read
that fails is named on stderr, with the CLI's reason.

## What the page shows

- **Header**: the project's name and the first line of its Goal.
- **Needs you**: the Queue's items in order, the top one marked. With no Queue section,
  or a table it can't read, it says the queue is unknown.
- **Units**, grouped by state: stuck, waiting, overdue, unknown, running, queued, done,
  dropped, then replaced or absorbed. Each Workers row is one card:
  - its worker, linked to its thread as the row stores it;
  - the thread's live status from `t3 thread show`. A row in a final state (done,
    dropped, replaced, absorbed) gets no read. A thread on another machine, or a read
    that fails, shows `unread`;
  - each PR in Branch or PR with its title, state, draft, and check counts, or `no
    checks`, `checks unread`, or `unread`. A PR from another repo than the checkout's is
    named `owner/repo#N`. A `#N` or `repo#N` whose repo the checkout's origin can't tell
    shows `repo unknown`, with no `gh` call;
  - the Issue cell, when the table has the column and the cell isn't empty;
  - what it waits on.
- **Unread rows**: rows whose cells don't match the Workers header, by their first cell.
- **Decisions** and **Phases**, folded: each section's lines as written.

## The data

`status --json` prints `status_data(lines, live=True)` from `scripts/project.py`:
`project`, `goal`, `queue` (items, or null with no Queue) and `queue_unread`, `groups` in
the order above, each `{state, units}`, then `unread_rows`, `decisions`, and `phases`.
Text is as project.md holds it, unescaped. `--no-live` skips `t3` and `gh`, so a unit has
no `thread_status` and a PR no `read`, `title`, `state`, `draft`, or `checks`; it still
reads the checkout's origin from git to resolve `#N`.

## The page

`scripts/status.html` is the page's one template. `status --html` replaces the `null` in
its `<script type="application/json" id="status-data">` block with the data, escaping `<`
and `>`, and the page's `draw(data)` renders it, setting every text through
`textContent`. Only `https:`, `http:`, and `t3-thread:` links become links. The page loads
nothing from the network and uses T3's theme variables, so it follows the thread's theme.
