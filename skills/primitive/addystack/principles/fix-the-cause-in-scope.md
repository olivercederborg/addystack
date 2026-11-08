# Fix the cause, in scope

**Apply when** fixing a bug, a review finding, or a type error.

Fix the cause, not the symptom, and every instance of it. When the cause sits outside
the change's scope, fix the symptom and name the cause as a follow-up, unless the user
asked for it.

**Why:** "obviously it depends. if fixing the cause means increasing the scope to an
extend that doesnt fit in the PR, then it could just be flagged as a possible
follow-up".

**Pattern:**
- **Reproduce where it failed**: the hosted build, deploy, or device that broke, not a
  local stand-in.
- **Ship what the evidence shows**: only the lines the confirmed cause needs. Revert what a
  disproven hypothesis added.
- **Ask why** until the answer is a design choice, not another symptom.
- **Sweep the class**: search for the same cause elsewhere, and list each hit as fixed or
  follow-up: "Make sure it doesn't happen anywhere else on the app".
- **Small and in the touched flow**, or the user asked: fix it now. **Unrelated or
  large**: follow-up.
- **Leave a signal**: when the deciding fact took a deep dig to find, propose the cheap,
  always-on signal, such as a log line, an assertion, or a metric, that would have shown
  it at first look.

**Tell:** a type annotation, cast, retry, or guard that makes the error go away while
the reason it happened stays.
