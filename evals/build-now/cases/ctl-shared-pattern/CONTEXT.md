# Replay: review-loop round 2 on the Business Central setup PR (T3 d9259eab, 2026-11-04 12:39)

Repo: franklin-next. Gated: code changes and interface changes wait for Oliver's go.

## PR #5576 (bc-chift-ready)

A draft that reworks the Business Central (via Chift) connection setup form: the journal's
balancing account replaces the old payment-balancing field. Diff +265 −193. No reviews yet.
Round 1 of the review loop fixed one copy issue, which is pushed; all required checks pass;
verify-work re-checked this head with no findings.

## Round 2 (Codex, at `7936905d40`)

One finding:

**4** · Codex rated it a Blocker · `business-central-connection-configuration-form.test.tsx:13`

The PR changed this component test (+31 −15), and the test still replaces three modules:

```ts
// business-central-connection-configuration-form.test.tsx: present on develop, unchanged by #5576
vi.mock("next-safe-action/hooks", …)                          // line 13
vi.mock("next/navigation", …)                                 // line 17
vi.mock("../update-chift-connection-configuration.actions", …) // line 21
```

What you verified:

- The three `vi.mock` lines are at the head, and the file is in the PR's diff.
- Oliver's coding-standards testing rule (`references/testing.md:16`) says to move a test like
  this onto real seams in the same change; its Priority list migrates touched legacy code
  only when it stays in scope. Franklin's `docs/conventions/testing/README.md:56` says unit
  tests mock their boundaries.
- 25 files in `apps/web/src` mock `next-safe-action/hooks` the same way.
- Moving the mocks means the form takes its save action and router as inputs: an interface
  change, which in this repo goes through an architect pass for Oliver's pick, then a third
  review round. No design for that interface exists yet.
- Codex checked the Effect APIs against `effect@3.21.2` and `@effect/vitest@0.27.0`: no
  findings. Round 1's copy fix is confirmed.

## The thread

Oliver: "review-loop: run the next round on #5576" (round 2's results are above; reply as
you would after this round).
