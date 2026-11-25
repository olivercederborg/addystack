<!-- Copy of shared/workflow.md, written by scripts/sync-copies.py: edit the source, then run the script. -->
# Builder workflow

How addystack builds with agents, and what it is moving toward. Check a skill change
against this before making it. Agents follow the router (the kit's `core/router.md`, built into the user's instructions); this file explains
why.

## Two flows

The autonomous flow needs autonomy from the user's instructions, which the router
grants. Without it, every repo takes the gated flow. With it, a repo whose policy says
`planning: gated` (`<kit>/bin/addystack policy --repo <path>`, as the router's Plan runs it), such as a team's work repo, and
any request where the user asks to plan take the gated flow, and every other repo takes
the autonomous one.

```text
autonomous   request ─▶ autopilot ─▶ stack of draft PRs
             you        agent, until a stop     you review

gated        brain dump ─▶ scope-grill ─▶ architect ─▶ "go" ─▶ autopilot ─▶ stack of draft PRs
             you           you + agent    you approve         agent, until a gate      you review
```

**Autonomous** (the default, as in Lauren Tan's pstack):

1. **Request.** Code work goes straight to `autopilot`, which writes a brief from the
   request (goal, checks, Not in scope, For architect) and logs it.
2. **Architect**, when an interface changes. Three sketchers each draw one. The agent
   picks one and records the pick in the contract commit's `Shape-` trailers.
3. **Autopilot** builds, proves, and opens the draft stack. It pauses only at the
   router's stops.
4. **Review.** The user reviews the stack afterwards, starting with any interface the
   agent picked.

**Gated** (`planning: gated`, or when asked):

1. **Brain dump.** Loose thoughts about a feature, refactor, or idea, in any order.
2. **Scope** (`scope-grill`). The agent plays the dump back, maps its milestones, and
   grills the next one into a goal, decisions, checks, and a Not in scope list, each
   option showing its cost. The user answers only the decisions about what gets built.
   The plan is saved where autopilot reads it.
3. **Architect** (`architect`). The user's main job: the interfaces and how modules
   call each other. Three sketchers each draw a structurally different shape; the user
   picks, merges, or edits one. The approved sketch is the plan's contract. A plan that
   changes no interface skips this step: the interfaces on the base are its contract.
4. **Autopilot** (`autopilot`). An agent builds against the contract and proves it
   (grounding, tests, the project's `verify-<app>` skill, a second model's review, and
   `verify-work` in a fresh verifier), keeps a decision log, and opens the stack. It
   pauses only at a stop or a gate.
5. **Review.** The user reviews the stack bottom-up against the interfaces they approved,
   and lands it or lets the agent merge, per the repo's trust value.

## After delivery

Autopilot runs `babysit` once on its draft PRs: it restacks conflicts, handles review
threads, and reruns or fixes CI, then pushes once and replies. Only PRs left unfinished
after that pass get a watch, and each wake runs another pass. Maintenance done means
the required checks are green (every check, when the base requires none), threads are
handled, and nothing conflicts; babysit then keeps the watch only on a ready PR, which
still waits on reviewers, and stops at the repo's merge rule. Independent PRs each get an owner thread that watches its own PR, and an
hourly check reports on the owners while any are open.

## Projects

A project the user runs from one thread gets a `coordinator`: a pinned `◆ <project>`
thread that plans, starts a worker per PR stack or research question, and keeps its
memory in `~/.local/state/orchestrate/<project>/`. Workers and subthreads run all code,
so the user can always reach it. It watches its PRs, hands each event to the PR's worker,
and answers what the plan settles. The user answers only there, one card at a time.

## Stops and gates

Both flows stop at the router's Stops, such as merging beyond the repo's trust
value or a message to a person. The gated flow also stops at its planning gates:

- An approved interface would change, or a plan without a contract would add or
  reshape one.
- The scope would grow past the plan's decisions.
- A check still fails after two different fixes.

Everything else is the agent's call, recorded in its decision log.

## Trust per repo

A repo's trust is the `trust` field of its policy, from
`<kit>/bin/addystack policy --repo <checkout>`. The user's config sets it per repo, and a repo's
own `.agents/addystack.jsonc` can only make it stricter.

- **`draft`**: autopilot ends at a draft stack. The user requests reviewers and merges,
  or tells the agent to, in their latest message. Asking to merge covers marking ready.
- **`merge on go`** (`merge-on-go`): the agent marks ready and merges a verified stack
  when the user's go names merging ("merge it and start next"), whether that's their
  latest message or the go that started the run.
- **`gate`**: the agent marks ready and merges a verified stack once the merge-gate
  hook allows it, which in a repo with no workflows needs no go for the merge line
  `scripts/stack.sh where` prints. Claude Code and Codex both run that hook, with four
  limits in Codex:
  - Only a Claude `work-verifier` subagent can record a Done verdict, since
    `verdict-stamp.py` runs only in Claude Code. A Codex session can merge only once a
    Claude verify-work run has recorded Done for that diff.
  - Codex has no `onFailure: "block"`, so when the merge gate crashes or times out,
    the merge goes through.
  - The hook sees the session's cwd, never `exec_command`'s `workdir`, so it checks the
    wrong repo when the merge reaches its repo only through `workdir`. Start the merge
    with `cd <checkout> && …` on a literal, unquoted path.
  - Codex runs the hook only while its `/hooks` entry is trusted, and skips a changed
    entry until it's trusted again. Until then, `gate` works like `merge on go` in Codex.

## Two tracks

The gated flow keeps the interface gate for a repo whose codebase doesn't yet
constrain the shape of the code, and for any request where the user asks to plan. Lauren
Tan (poteto) skips that gate because the framework leaves "only one way to do
something". In other repos, the autonomous flow skips it too and logs each pick for
review.

- **Builder workflow (now):** in a gated repo, the user's taste reaches the code through
  the interfaces they approve. Elsewhere, it reaches the code through their review of
  the agent's picks.
- **Framework (gradually):** each correction the user repeats becomes a lint rule, a
  convention, or a type, through `reflect`, which hands target-repo ones to `correct`;
  `correct` proves each check fails on a past mistake and extends the repo's lint
  ratchet. Every structural rule the codebase enforces is one less shape to approve.

**End state:** the user approves only interfaces that are genuinely new, and the
framework decides the rest.

