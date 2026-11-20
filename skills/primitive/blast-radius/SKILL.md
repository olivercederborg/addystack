---
name: blast-radius
description: "Finds what a change could break beyond the diff before it ships, proving the fact that makes it safe with real code. Use for 'blast radius of X', 'what could this break', a new dependency, SDK, or telemetry, a lockfile or toolchain change, or a small diff you don't trust."
metadata:
  layer: primitive
---

# Blast radius

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

Blast radius finds what the change breaks somewhere else. Listing callers is not the job; grep does that in a second. The job is the breakage grep won't show you.

## Don't trust your own writeup

A writeup that sounds right is worthless: it reads as convincing whether or not it's true. So don't hand back the writeup. Find the one or two facts the whole thing depends on and prove them by running code. Words are where you start, not what you ship.

For each fact the change's safety depends on, get it as far down this list as is cheap, and say where it stopped.

1. You said so. Worthless on its own.
2. You pointed at the line. A real `file:line`, or the library's own source.
3. You showed the bad case can't happen. You walked the failure step by step and it doesn't reach.
4. You ran it. A script or test that calls the real code and fails loud if you're wrong.
5. You reproduced it in the running app.

Mark any safety fact you can't get to step 4 unproven, out loud. Don't round it up to settled.

## Steps

1. Read the change. The diff, the symbols it adds, changes, and deletes, and what it now does differently, including the part the diff doesn't spell out, and the PR and commits behind it.
2. Find the one fact it's safe because of. Most changes that look scary are safe because of a single fact, like "this call only drops already-dead cache entries and does nothing else". If it holds, most of the scary cases die at once, so spend your time here, not on a long list of maybes.
3. Look where grep stops. Read the source of the library you call, and check its pinned version and any local patch. Work out when things run: microtasks, unmount and teardown, Solid versus React. Follow what a symbol search misses: the JSON an API returns, a DB column, a wire format, another language reading the same bytes, a feature flag, code three hops downstream. For data the change sends off the device or service, list every field each route or event carries; a deny-list filter stays unproven until it covers them all.
4. Be honest about each risk. Give it a real chance of happening and a real cost if it does. Keep the risks you confirmed; list the ones you checked and cleared separately. Cite a real `file:line`; a search that finds nothing is still an answer; never make up a caller or an API.
5. Prove the one fact. Write a script or test that runs the real code, usually one small script that imports the same library the app ships and calls the exact function you're worried about. Run it and paste what happened.
6. For a change that touches more than one package, a shared format, persistence, or a dependency, ask several models the same question, as `review-loop` does, and merge the answers.

## What to hand back

- **What it does.** What changed, including the part that isn't obvious.
- **The one fact it's safe because of.** State it, say which step you got it to, and show the proof or write unproven.
- **Risks.** Only the real ones. Each names how it breaks, the `file:line`, how likely and how bad, and how to check. Paste the proof for the ones that matter.
- **Cleared.** What you checked and why it's fine.
- **Before you merge.** The cheapest test or repro that catches the real bug, including the script you wrote.

Write it through `unslop` when it's installed, and strip anything private before it goes anywhere public.

**Reply:** the writeup above, with the one safety fact either proven or marked unproven.
