<!-- Copy of shared/taste.md, written by scripts/sync-copies.py: edit the source, then run the script. -->
# Taste

What good looks like in every repo. A repo's own `AGENTS.md` or `domain-modeling`
glossary (`CONTEXT.md`) wins where it's more specific.

## Architecture

- **Small capability services**, not one big integration port: "smaller optional
  services that each provider can implement in isolation".
- **Domain packages.** App-agnostic logic moves out of the app into a domain package.
- **Newest direction.** When the repo holds two patterns, follow the one the newest
  work started: "cant we use the same approach as the export v3 flow has started
  implementing?"
- **Best practice over convention.** When the repo's convention and the ecosystem's
  best practice differ, new code uses the best practice. Name the difference, so
  the user can decide whether to migrate the rest: "i know thats our current testing
  convention, but what is the best practice".
- **Flags over permanent variants.** Gate a transition behind a feature flag, instead
  of adding a type or enum value that stays forever: "avoid ending up with a
  `BUSINESS_CENTRAL_LEGACY` serviceType that will just be there forever".
- **Consistent siblings.** Markets, providers, and screens that do the same job do it
  the same way: "we should just be consistent across NL/BE no matter what we go with".
- **Thin task wrappers.** Background tasks only call a plain handler function, which
  holds the logic and the tests.

## Code

- **Ecosystem idioms.** Write what the library's own ecosystem writes. For Effect,
  check how OpenCode and t3code do it.
- **Short, specific names.** Rename a vague or long name in the same pass, and its
  stale siblings with it.
- **Effect modules.** Import a module as a namespace and name its main type after it:
  `import * as Program`, then `Program.Program`.
- **No real providers.** Unit and e2e tests never call a real external service, such
  as e-conomic or Trigger.dev.

## UI

- **Native first.** Use the platform's native control before a custom one, such as iOS
  27 buttons, sheets, and keyboards.
- **Principles, not looks.** "Clean", "fluid", "floating", "spacious". Take a cited app
  or designer's approach, never palette, components, or timings; match a mockup made
  for this app. Treat "overpowering", "cramped", and "AI-generated looking" as defects.
- **See it first.** For a new flow or screen, build a prototype with every state side
  by side before the real change.
