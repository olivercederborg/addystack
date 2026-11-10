# Fix the cause, in scope

**Apply when** picking a fix for a bug, alert, failing check, or review finding.

Rank the fixes, and make the first one option `a`:

1. **At the cause**: correct, idiomatic (the way the vendor, library, or codebase
   already solves it), and long-term.
2. **Then the smallest** of those. Size only breaks ties.

A quick fix ranks first only when production hurts now, another person or PR owns the
cause, or the cause fix reaches other features or domains. Label it a stopgap, and offer
the cause fix beside it, naming who builds it.

**Why:** "I want the smallest most correct long-term fix that is idiomatic and fixes the
cause".

**Pattern:**
- **Reproduce where it failed**: the hosted build, deploy, or device that broke, not a
  local stand-in.
- **Ship what the evidence shows**: revert what a disproven hypothesis added.
- **Ask why** until the answer is a design choice, not another symptom.
- **Sweep the class**: fix each other place with the same cause, or list it as a
  follow-up.
- **Leave a signal**: after a deep dig, propose the always-on log, assertion, or metric
  that would have shown it at once.

**Tell:** a cast, retry, rerun, label, or guard that makes the error go away while its
reason stays.
