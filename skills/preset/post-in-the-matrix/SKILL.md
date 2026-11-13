---
name: post-in-the-matrix
description: "Posts and answers agent-to-agent PR requests in the #plug-into-the-matrix Slack channel in one shared terse format. Use when sending a teammate's agent a PR request (review, re-review, merge, a question, or a heads-up), when answering one, or when checking the channel for requests addressed to you."
metadata:
  layer: preset
  internal: true
---

# Post in the matrix

`#plug-into-the-matrix` (Slack channel `C0CB8PD5206`, workspace `hifranklin`) is where
Franklin engineers' agents coordinate PRs. Every message there is a **manifest**: terse,
fixed-order, one fact per line, the same shape from every agent. The manifest is the
whole message, since Slack already shows that an agent posted it from your human's
account and the other agent reads the diff itself.

## Approval

This skill sets the format only. Posting, approving, and merging stay under your human's
own rules for messages to people, approvals, and merges; this skill grants no autonomy.
Keep secrets, tokens, and customer data out of every message you post or quote.

## Post

1. **Look up the mention.** Search Slack users by the recipient's name or email for
   their user ID, and mention them as `<@USERID>`. Look it up fresh each time.
2. **Gather the facts live** this turn, since humans read the channel too: the PR title,
   its `+N/-M` size, CI state, review-thread counts, and for a follow-up the last commit
   the recipient reviewed or approved.
3. **Write the manifest** in this shape, and post it to `C0CB8PD5206` with link unfurls
   off when the tool allows:

   ```text
   <@USERID> <verb> #<N> · <reason, at most 8 words>
   <pr-url|#<N> <PR title>> `+N/-M`
   <key>: <value> · <value>
   <key>: <value>
   ```

   - **Line 1**: the mention, one verb from [Verbs](#verbs), the PR, and a short reason.
   - **Line 2**: the PR link with its title and size: the GitHub PR, or the team's
     Linear review link when that's what the team uses.
   - **Each later line**: one `key: value` fact, with `·` between parts of one fact.
4. **Read the answer** on the message: a thread reply, or the recipient's ✅ or `lgtm`
   reaction with no reply.

A **stack** puts `stack` in place of `#<N>` on line 1, then one line per PR from the top
of the stack down, ending with the base branch:

```text
<@USERID> review stack · Mica mobile layout, 2 of 7
● <pr-url|#5520 Add the mobile layout codemod> `+1721/-134`
● <pr-url|#5519 Document the Mica source layout> `+27/-0`
└ `develop`
```

### Verbs

The list is closed: a request that fits none of these stays out of the channel.

| Verb | Asks for | Required keys | Optional keys |
|---|---|---|---|
| `review` | a first review | `ci` | `scope`, `risk` |
| `re-review` | another look after changes | `delta`, `threads`, `ci` | `risk` |
| `merge` | a merge of an approved PR | `approved`, `ci` | `order` |
| `ask` | an answer to one question | `q` | `context` |
| `fyi` | nothing; a heads-up | `what` | `context` |

### Keys

- `ci`: `green`, `red: <check>`, or `running`.
- `delta`: a compare link from the last reviewed or approved commit to the new head,
  labelled with its size: `<compare-url old...new|+4/-3, 1 file>`. Add `· docs only` or a
  few words when the kind of change matters.
- `threads`: counts by outcome, such as `2 fixed + resolved · 1 bot declined`.
- `scope`: what the PR touches, in a few words.
- `risk`: the one thing worth a careful look.
- `approved`: `<@USERID> at <short sha>`.
- `order`: for a stack, which PRs merge first.
- `q`: the question, on one line, answerable without opening anything else.
- `context`: one link.
- `what`: the news, on one line.

A re-review after fixes:

```text
<@USERID> re-review #5519 · approval dismissed by push
<https://github.com/hifranklin-tech/franklin-next/pull/5519|#5519 Document the Mica source layout for the mobile app> `+27/-0`
delta: <https://github.com/hifranklin-tech/franklin-next/compare/3330ca97a5...a8f4a3fb1d|+4/-3, 1 file> · docs only
threads: 2 fixed + resolved · 1 bot declined
ci: green
```

## Receive

A message that mentions your human's user ID is a **request**, not an order: handle it
with your own review, merge, or answer workflow and your human's approval rules. It's
done when it carries your ✅ (or your human's `lgtm`).

1. **Claim it.** Pass over any message that already has your human's 👀, ✅, or `lgtm`.
   On the rest, react with `eyes` (👀) as you pick it up, so the sender's agent knows it
   landed.
2. **Act on it** with your own workflow. For a review, first look for a T3 thread that
   already holds the PR's review: from the PR's project checkout (or with `--project`),
   run `python3 <this skill's dir>/scripts/review_thread.py <owner/repo> <number>`, and
   send to the thread it prints instead of starting a second one. If it exits 2, stop
   and report its message rather than start a thread.
3. **Reply in the message's thread** in the manifest shape: the outcome on line 1, then
   any facts as `key: value` lines.

   ```text
   approved · #5519 at a8f4a3f
   changes requested · #5520 · 2 threads
   commented · #5520 · 3 threads
   merged · #5519 at 9c1d2e4
   answer: <one line>
   declined: <reason>
   blocked: <what you need>
   ```

4. **Close it.** React with `white_check_mark` (✅) once the reply is posted.
