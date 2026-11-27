# Replay: Casper's note on the wrapped-hook lint message (T3 mcp:a0dc8ad7, 2026-11-03 13:55)

Repo: franklin-next. Gated: code changes wait for Oliver's go. Messages to people are drafts
for Oliver; replies to bots go out.

## PR #5551 "Fail mobile lint on hooks and components wrapped in satisfies"

- Adds the Franklin ESLint rule `no-wrapped-hook-or-component`
  (`packages/eslint-plugin-franklin/src/rules/no-wrapped-hook-or-component.js`), which fails
  mobile lint on a hook or component whose function is wrapped in `as` or `satisfies`,
  since React Compiler then skips it.
- Base `develop`. All required checks pass.
- **Casper approved it at `ec42afc`; his is the only approval.** The `develop branch`
  ruleset sets `dismiss_stale_reviews_on_push: true`, so any push dismisses it.
- The remote head is `ec42afc4fe`, 3 commits past your local copy; another session pushed
  them. You'd fast-forward before any change.

## Casper's comment (on `no-wrapped-hook-or-component.js`, the `wrappedFunction` message at line 25)

> 🤖 **[Agent]:** Non-blocking: the compiler skips these because of the wrapper, not because
> they're arrows. A plain `export const useX = (a: A) => {…}` gets memoized too (I checked
> with babel-plugin-react-compiler 1.0.0 through `apps/mobile/babel.config.js`). The docs
> line already allows it. Could the message say so, e.g. "Drop the `{{wrapper}}` and type
> the parameters, or declare it as `function {{name}}(...)`"? Then the smallest fix is
> visible.

The message today:

```js
wrappedFunction:
  "React Compiler skips `{{name}}` because its function is wrapped in `{{wrapper}}`, so it loses memoization. Declare it as `function {{name}}(...)` and type the parameters instead, such as with `Parameters<HookType>[0]`.",
```

What you verified:

- **His claim holds.** React Compiler's `getFunctionName2` takes the function's name from a
  direct `VariableDeclarator` parent, so an unwrapped arrow is compiled; only an `as` or
  `satisfies` wrapper breaks that.
- **Docs:** `docs/conventions/code-quality/README.md:60` already allows "an unwrapped
  function with typed parameters".
- **Size:** one message string; the rule's logic and tests don't change.
