# Router

How {{user}}'s agents pick a workflow and when they stop. Skills don't read this file: a
skill waits at its approval steps unless these rules grant autonomy.

@principles.md

## Routes

Use the first line that matches. The last two are fallbacks. `plan` is the Plan step
below. If nothing matches, use the skill whose description fits, or
none.

- **Project** (start, resume, or run a multi-PR project from one coordinator thread;
  any message or wake in a coordinator thread) → coordinator
- **PR watch woke** (a `watch_pull_request` wake on {{user}}'s own PR) → babysit
- **Repeated correction** (an agent repeats a mistake {{user}} already corrected, "you
  did X again", "make this impossible") → correct
- **Bug or failing check** (broken, throws, failing, regression) → diagnosing-bugs →
  plan → autopilot
- **Slow code** (slow, latency, perf) → diagnosing-bugs, measuring first → plan →
  autopilot
- **Skill or agent-doc edit** (a SKILL.md, AGENTS.md, CLAUDE.md) →
  writing-for-agents → plan → autopilot
- **Comments on {{user}}'s PR** (review comments, bot findings) → address-review
- **Teammate's PR** (review their PR) → review-teammate-pr
- **Done check** ("is it done?", "anything left?") → verify-work
- **Second opinion** (review this, cross-check) → review-loop
- **Blast radius** ("what could break?") → blast-radius
- **Claim to check** ("are you sure?", "is it idiomatic?") → grounding
- **Feature, refactor, or ticket** (any other code change) → plan → autopilot
- **Question** (any other read-only request) → answer from the code and its sources

## Plan

Find the policy once for each target repo, the checkout the work lands in. Take
`planning` and `trust` from your brief's `Mode:` line, or for any it doesn't name, run
`{{addystack}} policy --repo <target>` and read them from its JSON. Start every
child task's brief with `Mode: planning <gated|autonomous>, trust <draft|gate|merge-on-go>`.

- **Autonomous** (`planning` is `autonomous`): `plan` is empty, and autopilot writes its
  own brief from the request.
- **Gated** (`planning` is `gated`, or when {{user}} asks to plan): `plan` is scope-grill, then
  architect if an interface changes. These wait for {{user}}: scope-grill's questions and
  plan save, architect's pick, the go that starts autopilot, and autopilot's interface,
  scope, and third-retry gates.

Every other step outside Stops has autonomy. If {{user}} withholds it for the session
("no autonomy"), nothing has it: skills wait as they would without this file,
Continuation is off, and code work takes the gated flow.

## Stops

Stop before the next action when it is one of these:

- **Merging or marking ready** beyond the policy's `trust`. `draft` ends at a draft stack.
  `gate` marks ready and merges a verified stack once the merge-gate hook allows it.
  `merge-on-go` does so when {{user}}'s go names merging, in the latest message or the go
  that started the run; asking to merge covers marking ready.
- **A production write**, or a migration on shared data.
- **A force-push** to a shared branch: the default branch, or one someone else pushed to.
- **A message to a person**: Slack, a comment on someone else's PR, approving or
  requesting changes on it, a reply to a human reviewer, a reviewer request, or a new
  issue or ticket. Draft it and stop. Replies to bots go out.
- **A push to a branch someone else owns**, or one that would dismiss someone's
  approval. slim-scope decides if it waits.
- **A missing credential**, account, or secret you can't create, once the next action
  needs it.
- **A check that still fails** after the fix attack-the-premise's test pointed to.
- **A gate the Plan section keeps**, or any approval step when autonomy is off.
- **A product call** no probe or experiment can settle.

{{user}}'s latest message asking for the action clears its stop. Limits in the request,
such as read-only or a Not in scope list, still hold. At a stop, commit what's done,
draft what the stop needs, and end with `Next`.

## Continuation

Outside Stops, keep going, and log each call you'd otherwise have asked about, in the
run's decision log or as a line in the report. When two different fixes fail the same
check, run attack-the-premise, act on what its test shows, and go on. A review that
hits its round cap goes on too: its open findings lead the PR description, and a later
fix still gets verify-work's re-check.

A question asking you to act ("can you…?", "can't you just…?") is an instruction: do
it. A question about which, when, whether, or why ("why not X?", "is it…?") gets an
answer, and any change it implies becomes option `a`, not an edit.

## Skills outside the addystack kit

Skills the addystack kit doesn't own, such as pr-ui-artifacts or capture-ui-artifacts, ask
first only at a stop. Otherwise they go ahead and log the call.
