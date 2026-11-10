# Fix the cause, in scope

**Apply when** picking a fix for a bug, alert, failing check, or review finding.

Before option `a`, dig past the failure's explanation:

- **Know the cause**: reproduce it where it failed, not on a local stand-in; ask why
  until the answer is a design choice; find every entry point that reaches it.
- **Look up the idiom**: how the vendor's docs or source, or a sibling in the codebase,
  already solve it.

Then rank the fixes for option `a`:

1. **At the cause**: correct, idiomatic, and long-term.
2. **Then the smallest** of those.

Two cases change option `a`:

- **Another person or PR owns the cause**: hand it to them with what the fix needs;
  build no parallel fix.
- **Production hurts now, or the cause fix reaches other features or domains**: the
  smallest fix that stops it, labelled a stopgap, with the cause fix offered as its own PR.

**Why:** "I want the smallest most correct long-term fix that is idiomatic and fixes the
cause".

**Pattern:**
- **Revert** what a disproven hypothesis added.
- **Sweep the class**: fix each other place with the same cause, or list it as
  follow-up.
- **Leave a signal**: after a deep dig, propose the always-on log, assertion, or metric
  that would have shown it at once.

**Tell:** a cast, retry, rerun, label, or guard that makes the error go away while its
reason stays.
