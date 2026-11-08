# Do it before asking

**Apply when** you're about to ask the user a question, hand them a step, say a tool isn't
available, or answer from the code what live data would show.

What you can look up, observe by running something, or do yourself isn't the user's to
answer. Bring them only preference and product calls.

**Why:** "having the user upload it manually should be a last resort".

**Pattern:**
- **Look it up**: the code, config, open PRs and issues, `--help`, Executor, past sessions.
- **Probe it**: when the answer shows up once code runs (behaviour, layout, timing, a
  library's quirk), build a throwaway probe in the scratchpad and bring the result.
- **Drive it**: start the CLI or OAuth login yourself and hand over only the click.
- **Try a second route** before reporting something can't be done.

**Where the data is**, before the user has to name it:
- Customers, transactions, and production behaviour: the product's support or data MCP
  through Executor (`using-executor`). Count real rows instead of inferring from code.
- Vendor consoles and workspaces, such as Slack, Linear, and Sentry: Executor. List its
  live connections first, and add the vendor's source when it's missing.
- Xcode builds, logs, previews, and simulators: the Xcode MCP.
- A connected iPhone: `xcrun devicectl device install app` and `… device process launch`.

**Boundary:** credentials, payment, physical steps, and the stops in
[the router](../core/router.md#stops) still go to the user.

**Tell:** an option or **Do** item that starts with "you" and has no `tried:` line
naming what you tried, or a claim about customers or production that cites only code.
