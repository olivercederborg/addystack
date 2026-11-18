---
name: use-lakebed
metadata:
  author: Oliver Cederborg (@olivercederborg)
  usage-guidance: recommended
  layer: optional
description: "Use when building, previewing, publishing, or updating an existing Lakebed capsule."
---

# Use Lakebed

Take an existing capsule from source to a verified preview or deployment. The caller owns its content and design.

Capture the capsule root, `preview` or `publish` intent, requested lifecycle, caller checks and their outputs, endpoint verifier, report requirements, and extra preview checks. If intent is missing, ask whether to deploy and wait before doing any work. Publishing is separate permission from creating a capsule.

## Caller commands

For commands supplied by the calling skill, run only `node <script>`, `bash <script>`, or an executable script whose path and resolved symlink target stay inside the capsule root. Place no interpreter argument before the script. Reject shell operators, command substitution, redirection, absolute script paths, and escaping `..` paths; ask for a safe replacement instead. URL and ordinary flag arguments after the script are allowed.

Pinned Lakebed commands are trusted. Output prefixed `Advisory` is informational unless the caller asks for it.

Lakebed 0.0.41 needs Node 22.18 or later. Before the first pinned command, run `node --version`; when it's older, stop and report that prerequisite.

## Build and preview

From the capsule root:

1. Run caller tests unless they already passed against this exact source; rerun them after any capsule change. Always rerun validators and retain their URLs and disclosure warnings. Stop unless every check that ran exits zero.
2. Run `npx lakebed@0.0.41 build . --target anonymous --json`. Stop unless failure is solely because outbound fetch or async handlers require a claimed app; then mark the capsule owned-only and treat authenticated deployment as its final build gate.
3. Start `npx lakebed@0.0.41 dev . --port 4173` in a managed session. Confirm its printed URL serves the expected capsule root; choose a free port when needed and use only the process you started.
4. When supplied, run the caller's endpoint verifier with the origin-root preview URL and require a zero exit.
5. Inspect at 1280×800 and 390×844 for content, title, links, controls, reading order, narrow layout, and caller checks. Keep overflow local to code or tables.
6. Stop the dev server. On failure, fix the capsule and repeat from step 1.

For `preview`, return the verified capsule path after every check passes and the server stops.

For `publish`, continue only after every preview check passes and the server stops. Read and follow [`references/publishing.md`](references/publishing.md) in full before any public action; if it is unavailable, stop without deploying.
