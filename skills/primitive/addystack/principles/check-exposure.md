# Check exposure

**Apply when** weighing compatibility, a migration, a shim, a rollout step, a
deprecation, or how severe a finding is.

Its line in the [principles index](../core/principles.md) states the rule. Restructuring
code that is about to be replaced is left to the replacement.

**Why:** "no customers are really using the export v3 flow yet, so now is the time" ·
"we should not make any big changes to the export v2 flow, because very soon the new v3
flow will be taking over".

**Pattern:**
- **Check**: flag state, real callers, live users, and whether a replacement is underway.
- **Report** who can hit it in the finding's evidence.

**Tell:** a compatibility layer, versioned name, or staged rollout for code that nobody
runs yet.
