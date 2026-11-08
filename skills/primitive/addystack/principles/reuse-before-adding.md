# Reuse before adding

**Apply when** you're about to add a service, type, enum value, config file, hook,
helper, or dependency.

Before adding a piece, check for one that already does the job.

**Why:** "do we really need to create a new service? couldnt it just be … the current
Database service?"

**Pattern:**
- **Repo**: an existing service, type, flag, or the pattern the newest work uses.
- **Platform and library**: a native or built-in API: "is there no react-native/expo api
  for this?"
- **Report** what you checked, and why it doesn't fit, in the step's evidence.

**Tell:** a new file or type whose job a neighbour already does.
