# Slim scope

**Apply when** you're shaping a plan, a stack, a review round, or a `Next` list,
deferring a change, or weighing a push that dismisses an approval.

Its line in the [principles index](../core/principles.md) states the rule. A follow-up
that waits gets no separate or stacked PR unless asked.

**Atomic PRs**: an approval doesn't finish a PR; its merge does. A fix the PR needs, from
a bot, a reviewer, or a check, lands in it before then. The push that dismisses the
approval stays a router stop: the card waits for the user's go with that push as `a`,
naming whose approval it dismisses. An approver's own ask goes in their PR or an open
draft above it: they re-approve it quickly, and a new PR needs a review of its own.

**Why:** "If something fits into a PR that has already been approved, it should be fixed
in that PR instead of a follow-up" · "we need to think about the work as atomic PRs.
Once they're merged it needs to be finished" · "its getting way too out of hand. lets
keep it simple" · "but isnt it the best long term solution ?".

**Pattern:**
- **PRs**: vertical slices of up to about 1000 changed lines.
- **Review loops**: stop at the skill's round cap and list what's still open.
- **Option `a`**: inside the PR's scope, or it names the scope change it makes.

**Tell:** a plan that grew without the user asking, or a follow-up PR for a finding on
the PR's own change.
