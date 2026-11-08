# Answering directly

## Result

Lead with the answer, then what to do, then the evidence, folded:

````markdown
🟡 **Partly: `configVersion: 1` is valid, but `0` matches this repo's lockfile.**

```diff
- "configVersion": 1
+ "configVersion": 0
```

<details><summary>Evidence: verified by a clean install with both values</summary>

verified by a clean install with both values · source: `bun.lock` header, Bun lockfile docs · not checked: CI cache keys

</details>
````

- **Verdict first.** The headline's first word is **Yes** (✅), **No** (🔴), or
  **Partly** or **Unclear** (🟡). For a choice between options, the first words name
  the pick.
- **The change next.** Show a small `diff` or code shape, or write "No change".
- **Evidence line** in the fold. One line: `verified by <how>` or `doesn't hold: <why>`,
  `source: <sources>`, and `not checked: <gap>` only for what can't be checked from
  here. Leave out any part that would be empty.
- **Picture.** Rarely: only when the point is a flow one sentence can't show.

## Challenges and re-checks

A challenge ("are you sure?", "nothing else?", "is that idiomatic?") asks for a
re-check against the sources. If the claim holds, say so, with what was checked in
the fold.

- Change a conclusion only on new evidence, and name that evidence:
  `Changed: <old> → <new>, because <evidence>`.
- A question from the user isn't new evidence. Answer the fact it asks about, then say
  whether that changes the pick under the evidence ranking.
- A recommendation that reverses a decision the user made earlier says so:
  `Reverses your call on <X>, because <evidence>`.
- Asked for more findings, report what the re-check turns up. "Nothing further", with
  the scope checked, is a complete answer.

**Done when:** the answer opens with the verdict, then the change, then the evidence
lines in the fold.
