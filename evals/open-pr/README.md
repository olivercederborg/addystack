# open-pr evals

`./setup.sh` builds two repos in `/tmp/open-pr-eval`. Neither has a remote, so tell
the agent to use no `gh` and no network.

**open/**: "open a PR for this branch" (the branch still has its planted gaps)
- Shows the title and body once below a **Review** note, and publishes nothing.
- The body uses the default shape: a bold line on what changes for users, the export's
  flow as its picture (it's new behavior, so there's no before), then Rule, Evidence,
  Checks, and Reach bullets. There's no Not in scope bullet, since EX-7 has no such
  section.
- Evidence names a test or command output that shows the export working, not
  just a list of checks.
- Known gaps (missing `currency`, the JSON option) go in a `[!WARNING]` callout, and the
  issue link says "Part of", not "Closes".
- It runs `scripts/check-body.mjs` on the body before showing it, and the checks
  name its result.
- It doesn't review the code with cards. It offers `verify-work` in `Next`.

**sync/**: "is the PR description still accurate?" (`pr.json` is the live PR)
- The verdict is 🟡 **Not current** in the headline.
- The proposed update shows once as a `diff` of the description, the reply's one
  snippet, keeping the PR's existing sections. The fold flags the title (still says
  JSON), the stale JSON note, and the stale change outline as one-line items, with no
  per-section cards.
- Robin's note on inclusive date bounds is kept word for word.
- Code problems (the mock test) are left to `verify-work`.
