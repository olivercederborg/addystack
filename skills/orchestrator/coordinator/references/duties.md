# Duties

Read when the user asks for a recurring check, such as "check bug reports every hour",
"watch production for a week after the cutover", or "daily security review", and on
each duty tick. A duty is a scheduled, read-only probe of one source. Its new findings
become units. It runs through phase ends and while the project is parked, and ends at
its `until` or on the user's word.

## Start a duty

In the turn the user asks:

1. **Name** it with a short slug, such as `bug-reports`.
2. **Schedule** it: a `schedule_task` bound to this thread at the user's cadence, whose
   prompt names `project.md`'s path to read first and says `Duty <name> tick`.
3. **Write its line** under Listening with the task id `schedule_task` returned:
   `scripts/project.py <folder> listen "Duty <name>" "<task id> · <cadence> · <source>
   · until <end>"`. The source is where the probe reads, such as a Sentry project, a
   tracker query, or production logs. The end is a date, or a condition a tick can
   check, such as `the first clean week after the cutover`. When the user names no end,
   write `until the user ends it`.

**Done when:** the scheduled task exists, bound to this thread, and Listening holds its
`Duty <name>` line.

## A tick

1. **Check the end**: read the duty's line. When its date has passed or its condition
   holds, end the duty (below) and reply with one status line.
2. **Probe**: start a read-only probe subthread, a `delegate_task` like a worker's
   (SKILL.md step 3's More work), titled `◇ <project> · duty <name>`. It only reads, so
   it takes no slot. Its brief names:
   - the source;
   - the window: from the line's `last` time, or the duty's start, to now;
   - what counts as new: a finding the window holds that isn't already a Workers row, a
     Follow-up, or in an earlier tick's report;
   - that it reads only, and returns each finding with its evidence and a proposed
     proof;
   - `standing-rules.md`, pasted in full.

   Record it in Workers as `duty <name>` with its link and `taskId`, reusing that row
   each tick. When the last tick's probe still runs, let this tick pass; the next
   window starts at the line's `last` time.
3. **Handle the result** as a worker result (SKILL.md step 4). Each new finding becomes
   a queued unit, a Workers row with its proof that steps 2 and 3 start, or a
   Follow-up when it's outside the goal. An issue or a message to a person stays a
   draft and reaches the user as a card through step 5, per the router's Stops.
4. **Record the tick**: rewrite the line with `listen`, keeping its value and ending it
   `· last <window end, ISO time>, <n> new`, so the next window starts there. Set the
   `duty <name>` row to `done`.

A tick with nothing new posts nothing: end the turn with only the turn block.

**Done when:** the line's `last` time is this tick's window end, and every new finding
is a Workers row, a Follow-up, or a queued card.

## End a duty

A duty ends at its `until`, on the user's word, or at close. Delete its scheduled task
with `delete_scheduled_task`, and rewrite its line with `listen` to `none (ended
<date>: <reason>)`.

**Done when:** the duty's scheduled task is gone and its line reads `none`.
