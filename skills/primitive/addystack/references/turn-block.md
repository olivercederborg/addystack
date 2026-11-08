# Turn block

With `replies.turnBlock` on, every final reply ends with one turn block: a line of JSON in
an HTML comment, which T3 hides from the user. `hooks/turn_block.py` parses it,
`hooks/routine_stop.py` reads it to tell a routine step from a stop, and
`hooks/merge-gate.py` reads which option a key picked. With the routine-stop hook
installed (the `replies` hooks, as in the `all` preset), a reply whose block is missing or
malformed goes back once with the reason. A user's own reply rules file (`replies.rules`)
may restate this section; the hooks then cite that file instead. `turn_block.py`'s
docstring holds the parser's exact limits: which code blocks and spans hide an example
block, and which replies' picks count as a merge go.

````markdown
<!-- turn {"state":"stop","needs":[{"id":1,"kind":"decide","name":"which export fixes"}],"options":[{"key":"a","class":"routine","text":"yes: fix the currency column and null dates, one commit each"},{"key":"b","class":"routine","text":"no: fix only the currency column"}]} -->
<!-- turn {"state":"done","needs":[],"options":[]} -->
<!-- turn {"state":"running","needs":[],"options":[],"elapsed":"10 min"} -->
````

One block per reply; these are three alternatives.

## Form

- **Placement**: the reply's last non-whitespace text, starting at the first column of its
  own line, outside any code block or code span. A block inside one is an example; a
  second block outside one makes the reply malformed.
- **Body**: one JSON object, each field once, no unknown fields, and no `-->` or `--!>`,
  which would end the comment early and show the rest. `state`, `needs`, and `options` are
  required in every block; `needs` and `options` are lists, empty when there's nothing.

## Fields

The shared fields and their limits are prefrontal-turns' base, the spec Prefrontal reads.

- **`state`**: `stop` ends on Next, `done` on Done, and `running` on a ⏳ line while CI, a
  child, or a watch runs, or is the block alone where a skill makes that a quiet watch
  wake's whole reply.
  - `stop` carries at least one option or need.
  - `done` carries neither: both are empty lists.
  - `running` carries no options and always `elapsed` (1-40 characters, not blank, such
    as `"10 min"`), plus `eta`, the time left (1-40 characters, not blank), only when it's
    measured. Only `running`
    carries either.
- **`needs`**: each Decide, Review, or Do item the reply asks of the user, and a decision
  card's question, as `{"id", "kind", "name"}`. `id` is a whole number of 1 or more,
  unique, the number the visible item gives it; `kind` is `decide`, `review`, or `do`;
  `name` is 1-80 characters with a word of 3+ letters, as the visible item names it. A
  screenshot or recording waiting for the user's look is a `review`. A Do from an earlier
  reply that's still open stays listed.
- **`standing`** (optional): items still open from earlier replies that don't block this
  turn's next step, in `needs`' item shape. An `id` is unique across both lists, any state
  may carry it, and alone it doesn't make a `stop`; only `needs` counts as needing the user.
- **`options`**: the Next options in order, as `{"key", "class", "text"}`, with `text` 1-400
  characters, not blank. The first is the recommended one.
- **`project`** (optional): 1-40 characters, not blank; threads that share it group into one row.
  A child whose brief has a `Project:` line sets it to that name.

## Options

addystack adds the two-option cap and each option's class.

- **Keys**: `a`, the recommended pick, and `b` only when the reply stops for the user's
  call, as on a decision card's no or the smallest option. `routine_stop.py` sends back a
  reply with a third.
- **`class`**: the router stop the option crosses, one of:
  - `stop:merge`: merging or marking ready. A merge option's text is the plain merge
    request with no other step, as in "merge #12 and #13", since only that counts as the
    user's go when they pick it; a ready-only option, such as "mark #12 ready", isn't one.
  - `stop:push`: a force-push to a shared branch, or a push to a branch someone else
    owns or one that would dismiss an approval.
  - `stop:post`: a message to a person.
  - `stop:prod`: a production write or a migration on shared data.
  - `stop:credential`: a missing credential, account, or secret.
  - `decision`: a product call, a real fork, a plan gate, or an option after answering a
    read-only question.
  - `routine`: anything else outside the stops, such as fix, verify, review, push the
    user's own branch, open a draft PR, or watch. When the state is `stop`, nothing is in
    `needs`, and `a` is `routine`, `routine_stop.py` sends the agent on to do it, unless
    the turn answers the user's question or they said "no autonomy".
