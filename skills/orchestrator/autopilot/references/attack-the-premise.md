<!-- Copy of skills/primitive/addystack/principles/attack-the-premise.md, written by scripts/sync-copies.py: edit the source, then run the script. -->
# Attack the premise

**Apply when** two fixes that share an assumption have failed the same check.

Suspect the assumption, not the fixes, and test it before a third try.

**Why:** each failed fix is evidence against the belief it assumed, so a third fix on
that belief looks where the evidence already says the cause isn't.

**Pattern:**
- **Write the premise**: the one sentence both failed fixes assumed.
- **Test it**: make one observation that would come out differently if the premise were
  false, as a rerunnable script. Look at where the failures fall, not only how big they
  are.
- **Follow the evidence**: when it contradicts the premise, look for what the failures
  share that the premise didn't predict. When it confirms the premise, ask the next why,
  since the earlier fixes may have treated a consequence.
- **Remove the condition**: change what puts the failure there, rather than add a
  mechanism that cleans up after it. Where the workflow stops after two failed fixes, as
  autopilot does without autonomy, bring the user the premise, the test, and the fix
  instead of applying it. With autonomy, act on what the test shows and go on.

**Tell:** a third fix built on the same assumption as the first two.
