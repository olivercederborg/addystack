# Fix the cause, in scope

**Apply when** fixing a bug, a review finding, or a type error.

Fix the cause, not the symptom, and every instance of it. When production hurts now,
ship the symptom fix first and offer the cause fix as its own PR.

**Why:** "I want the smallest most correct long-term fix that is idiomatic and fixes the
cause".

**Pattern:**
- **Reproduce where it failed**: the hosted build, deploy, or device that broke, not a
  local stand-in.
- **Ship what the evidence shows**: the confirmed cause's fix, in slim-scope's shape.
  Revert what a disproven hypothesis added.
- **Ask why** until the answer is a design choice, not another symptom.
- **Sweep the class**: search for the same cause elsewhere, and list each hit as fixed or
  follow-up: "Make sure it doesn't happen anywhere else on the app".
- **Leave a signal**: when the deciding fact took a deep dig to find, propose the cheap,
  always-on signal, such as a log line, an assertion, or a metric, that would have shown
  it at first look.

**Tell:** a type annotation, cast, retry, or guard that makes the error go away while
the reason it happened stays.
