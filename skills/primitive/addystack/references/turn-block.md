# Turn block

A reply rules file (`replies.rules`) can end every final reply with one turn block: a line
of JSON in an HTML comment, which T3 hides from the user. `hooks/turn_block.py` parses it,
`hooks/merge-gate.py` reads which option a key picked, and tools such as Prefrontal read
the rest. `replies.turnBlock` no longer changes anything: it chose the Stop hooks that
checked the block, which the kit removed.
`turn_block.py`'s docstring holds the parser's exact limits: which code blocks and spans
hide an example block, and which replies' picks count as a merge go.

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
  which would end the comment early and show the rest. `state` is required in every block.
  `needs` and `options` are lists, empty when there's nothing: a `stop` names both, and a
  `running` or `done` block may leave either out, which reads as `[]`. `null` is never a
  list.

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
- **`needs`**: what this turn waits on the user for: each Decide, Review, or Do item, and
  a decision card's question, as `{"id", "kind", "name"}`. `id` is a whole number of 1 or
  more, unique, the number the visible item gives it; `kind` is `decide`, `review`, or
  `do`; `name` is 1-80 characters with a word of 3+ letters, as the visible item names it.
  A screenshot or recording waiting for the user's look is a `review`. An item only the
  user can do that a routine option waits on goes here; an earlier reply's open Do that
  doesn't block this turn's next step goes in `standing`.
- **`standing`** (optional): items still open from earlier replies that don't block this
  turn's next step, in `needs`' item shape. An `id` is unique across both lists, any state
  may carry it, and alone it doesn't make a `stop`; only `needs` counts as needing the user.
  So a decide or review the user still owes is a need the reply shows until they answer it,
  or, where a thread brings them one at a time, waits in `standing` behind the one it
  shows, with a line the user sees saying how many wait.
- **`options`**: the Next options in order, as `{"key", "class", "text"}`, with `text` 1-400
  characters, not blank. The first is the recommended one.
- **`project`** (optional): 1-40 characters, not blank; threads that share it group into one row.
  A child whose brief has a `Project:` line sets it to that name.

## Options

addystack adds the two-option cap and each option's class.

- **Keys**: `a`, the recommended pick, and `b` only when the reply stops for the user's
  call, as on a decision card's no or the smallest option.
- **`class`**: the router stop the option crosses, one of:
  - `stop:merge`: merging or marking ready. A merge option's text is the plain merge
    request with no other step, as in "merge #12 and #13", since only that counts as the
    user's go when they pick it; a ready-only option, such as "mark #12 ready", isn't one.
    Across repos it names each PR's repo, as in "merge addystack #56 and skills #313":
    merge-gate places a bare PR after one named with its repo in no repo.
  - `stop:push`: a force-push to a shared branch, or a push to a branch someone else
    owns or one that would dismiss an approval. A push that would dismiss one opens with
    the push, names each PR (or, for a lone approval, no #N anywhere), then the dismissal
    and only steps such as replying, in at most 200 characters, with no refusal,
    condition, or question, as in "push #6119 (dismisses the reviewer's approval), post
    the reply". push-gate allows that push only on a pick of such an option, so a push
    folded into a `stop:post` option or "don't push #6119 yet, it would dismiss the
    approval" is denied.
  - `stop:post`: a message to a person.
  - `stop:prod`: a production write or a migration on shared data.
  - `stop:credential`: a missing credential, account, or secret.
  - `decision`: a product call, a fork (two options that change different files or
    outcomes), a plan gate, or an option after answering a read-only question.
  - `routine`: anything else outside the stops, such as fix, verify, review, push the
    user's own branch, open a draft PR, or watch.
