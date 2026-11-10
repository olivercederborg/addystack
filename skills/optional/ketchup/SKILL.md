---
name: ketchup
description: Catch the user up on what changed in this chat since their last message, in plain words and small visuals, and list every call waiting on them with what they need to make it from the reply alone.
disable-model-invocation: true
metadata:
  layer: optional
---

# Ketchup

Catch the user up on what changed since the last message they wrote before `/ketchup`,
and help them understand each change, not only where it stands. Then lay out every call
waiting on them so they can make it from the reply alone. Notifications and subagent
results aren't their messages. Assume they remember that message and nothing after it.

Use `bro`'s voice, not its task: plain words and short sentences, like one person
catching up another. Say what changed for the user, not how you did it: "the tests
pass", not "CI is green". Leave out hashes, file paths, commands, build numbers, and test
counts unless the user needs one to act. Call each PR, branch, thread, or agent by a
name they'd know, not a label coined during the work. When a fact needs context to make
sense, give the context or leave the fact out.

## 1. Gather

Keep this turn read-only. Build visuals only from what already exists: change no code,
start no app or job, and post nothing. Collect your own work since that message,
subagent and child task reports, and messages from anyone else in the chat. Fetch the
live state of each PR, CI run, thread, and agent the chat touched, and note which are
still running and which you couldn't check. Check each number you'll show against the
facts it comes from, and say so when you correct one.

An action item is a call only the user can make: a product choice, an approval, an
irreversible step, or access you lack. Include one raised before their last message if
it still waits. Work you can still do yourself isn't one, and neither is a call made up
to fill the reply. A step the user didn't ask for and the work doesn't need isn't one
either, unless it's irreversible and waiting on them: give it one line and no visual.

One call can cover many items, such as each PR in a set awaiting merge. For each item,
collect its link, what it changes for users, the evidence behind your pick, its risk,
and your pick. Write "unknown" for a fact the call needs that you don't know, and leave
out a link you don't have.

**Done when:** every PR, run, and agent the chat touched has a live state or a reason it
has none, and every action item has its five facts or "unknown" for each.

## 2. Reply

Lay it out in the user's reply style, with the action items where it puts calls for the
reader. Spend words on the calls, not the story.

- **Status**: one short sentence naming what waits on the user, or saying nothing does.
  When nothing happened and nothing waits, say so and stop.
- **What happened**: under 100 words, not counting pictures, and shorter when less
  happened. Leave out work that changed nothing for the user. Pictures first: the
  screenshots and videos the work produced, then a diagram that explains a change. Then
  one short bullet per thing the user asked for: what came of it, and whether it's done,
  still running, failed, or not checked. Write each line the way you'd say it out loud:
  "Search was slow from a missing index", not "Search review: done". Name any bug found
  and fixed on the way. Each line stays true read alone, never marks done what still
  waits on the user, and leaves out what the action items say. Under the bullets, at
  most three short lines that change what the user knows or must do, then one line
  naming work you can still do yourself.
- **Action items**: every one, about 30 words each, so the reply grows with the count.
  Never cut or shrink an item to save words, and never put a count or a link in place of
  one: a link adds depth, but the reply alone must be enough to decide.

Write each action item as the call the user owns, such as merge, approve, or pick, with
your pick. A step you'd take first, anything that must happen first, and anything that
can't be undone go in the pick. Give the number or link of each PR, issue, or agent the
call is about.

- **One item**: one bullet with the call, your pick, what it changes for users, the
  evidence behind the pick, and its risk.
- **A shared call**: the call and your pick once, then one bullet per item, riskiest
  first, with its link and name, what it changes for users, the evidence, and its risk.
  Name an item's pick only where it differs.
- **A choice between options**: every option the work weighed, each with what it gets
  the user, what it costs, and the current state when there is one. Those costs are its
  risk, so add no risk line. When screenshots above show the options, put each option's
  gain and cost under its screenshot.

Give each item's risk even when it's low, as in "Low risk: only the colors change." Say
what waiting costs only when it's more than a delay, such as a deadline or lost data.

## Visuals

A visual is a picture: a screenshot, a video, a Mermaid diagram, or a chart. A Markdown
table isn't one, even with before and after columns.

Draw one when a picture is easier to grasp than sentences: how a design or system works,
a PR stack with each PR's state, a before and after of a fix, or options side by side.
Never draw a status list, a list of action items, or boxes with nothing connecting them,
and never give a fact twice, in text or across visuals. Keep each one readable at a
glance, within the reply style's size limit and at most eight words a box, labeled in
plain words a person would say, not tags like "Tests: pass".

Embed screenshots and videos inline when the change is visible, not only as links. When
a visible change has none, mark its line "No screenshot yet" and say what changed on
screen. Draw diagrams and charts only from facts you have. Never invent a number or
picture a screen you didn't capture, and link only artifacts that exist.

Adapted from Lauren Tan's `ketchup` in pstack (MIT); see [NOTICE](NOTICE).
