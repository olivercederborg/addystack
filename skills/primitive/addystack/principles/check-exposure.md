# Check exposure

**Apply when** weighing compatibility, a migration, a shim, a rollout step, a
deprecation, or how severe a finding is.

Find out who can hit the code today before paying for safety. When code is about to be
replaced, make only the fixes its users need, and leave restructuring to the
replacement.

**Why:** "no customers are really using the export v3 flow yet, so now is the time" ·
"we should not make any big changes to the export v2 flow, because very soon the new v3
flow will be taking over".

**Pattern:**
- **Check**: flag state, real callers, live users, and whether a replacement is underway.
- **Report** who can hit it in the finding's evidence.
- **Nobody can hit it**: now is the cheapest time. Build the right shape, with no shim.

**Tell:** a compatibility layer, versioned name, or staged rollout for code that nobody
runs yet.
