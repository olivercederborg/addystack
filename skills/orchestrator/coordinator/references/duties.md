# Duties

Read when the user starts, changes, or stops a recurring check, such as "check bug
reports every hour", "watch production for a week after the cutover", or "daily
security review", and on each duty tick or probe result. A duty is a scheduled,
read-only probe of one source. Its new findings become units. It runs through phase
ends and while the project is parked, and ends at the first tick past its `until` or
on the user's word.

## Start a duty

In the turn the user asks:

1. **Name** it with a short slug, such as `bug-reports`. When Listening already has a
   live `Duty <name>` line, this request changes that duty: delete its scheduled task,
   `task_cancel` a probe still running on its row, and set the row `done` with
   `worker "duty <name>" --state done --thread "<its link> · task none"`. Then go on,
   keeping its `last` time in step 3 unless the source changed.
2. **Schedule** it: a `schedule_task` bound to this thread at the user's cadence, whose
   prompt names `project.md`'s path to read first and says `Duty <name> tick`.
3. **Write its line** under Listening with the task id `schedule_task` returned:
   `scripts/project.py <folder> listen "Duty <name>" "<task id> · <cadence> · <source>
   · until <end> · last <now, ISO time>, 0 new"`, so the first window starts now. The
   source is where the probe reads, such as a Sentry project, a tracker query, or
   production logs. The end is a date, or a condition a tick can check, such as `the
   first clean week after the cutover`. When the user names no end, write `until the
   user ends it`.

**Done when:** one scheduled task exists for the duty, bound to this thread, and
Listening holds its `Duty <name>` line with a `last` time.

## A tick

1. **Probe**: start a read-only probe subthread, a `delegate_task` like a worker's
   (SKILL.md step 3's More work), titled `◇ <project> · duty <name>`. It only reads, so
   it takes no slot. Its brief names:
   - the source;
   - the window: from the line's `last` time to now, or to the duty's end date when
     that comes first;
   - what counts as new: a finding the window holds that isn't in
     `duties/<name>.md` in the project folder, a Workers row, or a Follow-up, with
     `project.md`'s absolute path to read;
   - that it reads only, and returns each finding with a stable identity qualified by
     its source, such as `prod:<error fingerprint>`, its evidence, and a proposed
     proof, and, for an end condition, whether it holds and the evidence;
   - `standing-rules.md` and `duties/<name>.md`, pasted in full, a missing history
     being empty.

   Record it in Workers as `duty <name>`, `running`, with its link and `taskId`,
   reusing that row each tick. When the last tick's probe still runs, let this tick
   pass; the next window starts at the line's `last` time.
2. **Handle the result**, on the wake its `duty <name>` row's result brings, as a worker
   result (SKILL.md step 4). A result for an ended duty, or one whose `taskId` isn't
   the row's, is dropped. A failed probe sets the row `done` and leaves `last` as it
   was, so the next tick covers its window. Each new finding not already a Workers row or a Follow-up becomes
   a queued unit, a Workers row with its proof that steps 2 and 3 start, or a Follow-up
   when it's outside the goal. Then append its identity and date to `duties/<name>.md`,
   creating the folder, which outlives phase ends.
   On a parked project, a finding worth work reaches the user as a card to start a
   phase for it, which [phases](phases.md)' `start` opens. An issue or a message to a
   person stays a draft and reaches the user as a card through step 5, per the
   router's Stops.
3. **Record the tick**: rewrite the line with `listen`, keeping its value and ending it
   `· last <window end, ISO time>, <n> new`, so the next window starts there. Set the
   `duty <name>` row to `done`.
4. **Check the end**: when this successful probe's window reached the end date, or the
   condition holds, end the duty (below).

A tick with nothing new posts nothing, and its reply is quiet: no headline or status.

**Done when:** the line's `last` time is the successful probe's window end, and every
new finding is in `duties/<name>.md` and is a Workers row, a Follow-up, or a queued card.

## End a duty

A duty ends at its `until`, on the user's word, or at close. Delete its scheduled task
with `delete_scheduled_task`, `task_cancel` a probe still running on its row, set the
row `done`, and rewrite its line with `listen` to `none (ended <date>: <reason>)`.

**Done when:** the duty's scheduled task is gone, no probe of it runs, and its line
reads `none`.
