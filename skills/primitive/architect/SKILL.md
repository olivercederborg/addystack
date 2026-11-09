---
name: architect
description: "Designs a change's interfaces before code: three competing sketches, then a pick committed as the build's contract. Use when a feature, refactor, or plan adds or reshapes a module's interface, or when asked to architect a change or design interfaces."
metadata:
  layer: primitive
---

# Architect

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

In the builder workflow, the user's main job is the interfaces and how modules call
each other.

<!-- toolkit-format:start (edit shared/format-pointer.md, then run scripts/sync-format.sh) -->
**Chat format**: read [`references/format.md`](references/format.md) first, and again
before you report if its text has left your context.
<!-- toolkit-format:end -->

Item kind here: one **Review** item for the candidate shapes, asked in the headline.
Calls, one per candidate: **recommended** or **alternative**.

## 1. Load the plan

- **Plan**: the decisions, the **For architect** questions, and the **Not in scope**
  list from `scope-grill`, taken from this conversation, the saved plan, the ticket, or
  the spec, or the caller's brief. The approved shape settles each For architect
  question. When there is no agreed plan or brief and the change isn't trivial, offer
  `scope-grill` first.
- **Trace**: for each module the change touches, read its public interface and its
  callers through imports and tests, on a branch with nothing missing from the
  just-fetched default: `git rev-list --count HEAD..origin/<default>` is 0, because a
  sketch traced on stale code gives a stale contract. Use the repo's file-placement
  skill (such as a `file-structure` skill) and `codebase-design` for ownership and
  seams when they're installed.
- **Names**: use the glossary's terms from `CONTEXT.md`.

Before a candidate adds scope beyond a saved plan, show **Proposed this round** ·
*my suggestion, not agreed* with a `diff` block of `+` additions and any Size change,
above the plan. Wait for the user's answer before including the addition.

**Done when:** every touched module, its current interface, and its callers are named.

## 2. Sketch three shapes

Start from the caller's usage: the few lines a caller writes to use the change. Then
the shape behind it:

- the modules involved, and what each one owns;
- the types and the function or method signatures, with bodies left out;
- a typed call stack of how the modules call each other, as in [views](references/views.md#typed-call-stack).

Make three candidates that differ in structure (module split, ownership, or data
shape), not in naming or detail. Sketch one yourself. The other model (Codex when you
are Claude, Claude when you are Codex) sketches the second, and the third sketcher from
the Roles table in [t3-delegation](references/t3-delegation.md) sketches the third, each
from the same brief without seeing the others. Run both as T3 child tasks in parallel,
with the prompt below as `task`, `role: "design"`, `interactionMode: "plan"`,
`mode: "wait"`, and `timeoutMs: 1800000`. A wait that times out isn't a failure, so wait
for the child to finish. If the second model fails, such as on auth, sketch the second
yourself and say so in the report. If the third sketcher fails, report its sketch as
missing and go on with two.

```text
Sketch the interfaces for this change. Read-only: do not edit, commit, or push.
Goal: <goal>
Decisions: <one line each>
Not in scope: <list>
Touched modules and their callers: <paths>
Lenses: <the chat format's Lenses skills>; load each, and follow them.
Return the caller's usage first, then the modules and what each owns, the types and
function signatures with bodies left out, and a typed call stack of how the modules call
each other, with the type at each hop where it carries information. Prefer the shape that hides the most behind the smallest interface.
```

Before presenting, load the chat format's **Lenses** skills, and ground every signature
with [grounding](references/grounding.md) against them and the version it will compile
on (the target branch's lockfile, read from a checkout with it installed). Find each
part's precedent: the repo file whose pattern it follows, or the framework's idiom where
the repo has none. Then screen every candidate for these red flags,
revising or dropping one that has them. Assume the next contributor is an agent that sees
only the files it opened, copies the nearest example, and takes the shortest path that
compiles. Prefer the shape where a change that looks right from one file is right for
the whole repo.

- **Shallow module**: callers coordinate several calls to finish one operation, or the
  interface is about as large as what it hides.
- **Leaked internals**: a storage schema, wire type, or provider detail appears in more
  than one module's interface.
- **Temporal split**: modules follow execution order (load, validate, save) instead of
  the knowledge they own, so one rule repeats across them.
- **Pass-through**: a layer forwards the same arguments to another without adding
  policy or adaptation.
- **Split ownership**: more than one module writes the same state or keeps its own
  copy. Give each piece of state one owner that the others ask.
- **Two ways**: the design allows more than one way to do the same task, and each way
  keeps gaining callers. Keep one, and move the callers off the rest in the same change.
- **Importable internals**: a caller can import a module's internals. Make them
  unreachable, so an outside import fails the build.
- **Hand-synced lists**: adding an item means editing several lists. Derive them from
  one, or fail the build when they disagree.

**Done when:** three screened candidates, or two with the third reported missing,
differ in structure, and each has usage traced from where the flow starts to its result,
signatures with their precedents, and a typed call stack.

## 3. Present and decide

The recommended candidate is the reply's shape: one code block with the signatures, each
commented with its precedent, the caller's usage traced from where the flow starts to its
result, and the typed call stack as a closing comment, under a first-line comment naming
what it hides. Each other candidate is one note naming what a caller must know. The fold holds their code blocks, written the same way, and the evidence.
Recommend the shape that hides the most behind the smallest interface.

````markdown
🟡 **Which shape for the monthly summary? 1 hides the most.**

```ts
// 1 · Export owns the date range: hides filtering and column order
export declare function exportCsv(range: DateRange): Effect<CsvFile, ExportError> // as exportSummary, export.ts:12
// ExportButton's handler, the flow's start; it knows only DateRange
const file = yield* exportCsv({ from: month.start, to: month.end })
yield* download(file)
// exportCsv → transactions.inRange(range) → toCsv(rows)
```

- **2** · Shared transaction query: summary and export both know the query's fields.
- **3** · Summary reads the export's rows: a column change reaches the summary.

<details><summary>Shapes 2 and 3 in code, and evidence → 1</summary>

```ts
// 2 · Shared transaction query
export declare function query(q: TransactionQuery): Effect<Row[], QueryError> // as transactions.list, transactions.ts:30
// ExportButton's handler: it builds the query and the CSV itself
const rows = yield* transactions.query({ from: month.start, to: month.end })
yield* download(toCsv(rows))
// summary → query(q) · export → query(q) → toCsv(rows)

// 3 · Summary reads the export's rows
export declare function exportRows(range: DateRange): Effect<Row[], ExportError> // no repo precedent; follows Effect.fn's docs
// SummaryCard's loader, the flow's start
const rows = yield* exportRows({ from: month.start, to: month.end })
return summarize(rows) // the card's totals
// summary → exportRows(range) → summarize(rows) · export → exportRows(range) → toCsv(rows)
```

Precedents verified by grounding with the lenses · source: Codex sketched 2, Fable sketched 3

</details>
````

Offer the recommended shape and the smallest other one, and wait for the user's pick;
picking a shape approves it and commits its contract.
The user can pick any
shape, or a merge of two, in their own words. Iterate on the user's edits by showing
only what changed.

With autonomy, pick the recommended shape, or a merge that names what it takes from
each, and go straight to step 4. The user reviews it later from the commit's trailers
and the decision log.

**Done when:** the user approves one shape, or, with autonomy, one is picked.

## 4. Commit the contract

Write the approved new types and signatures into their real files, with bodies that
throw (in TypeScript, `throw new Error("not implemented")`), so the contract
typechecks. A reshaped existing interface goes into the plan as a before → after line
instead, because changing it now would break its callers before the build reaches them.
Commit with the repo's tooling, and put the typed call stack and the usage in the commit
message. End it with three trailers: `Shape-Picked-By:` `agent` or `user`,
`Shape-Why:` the reason in one line, and `Shape-Alternative:` the strongest losing
shape in one line. Put them in the message's last paragraph, so git reads them as
trailers. Then log the pick with show-me-your-work's `log.sh --pr you`, or `--pr agent`
when you picked it, the commit's SHA as evidence, and `instead of <Shape-Alternative>`
in its why.

**Done when:** the contract commit typechecks, and every reshaped interface has its
before → after line in the plan.

## 5. Hand off

The headline names the contract commit, the shape is the approved typed call stack, and
any open question is a **Decide** note. Then stop: the user goes on with the next step
the router picks against the contract (or `build` when they want to go step by step),
or changes the shape. With autonomy, return to the caller instead of stopping.

**Done when:** the user has the commit and the hand-off.

## During the build

The approved interfaces are the contract. Inside them, every decision is the build's,
recorded in its report. Changing an approved interface stops the build for the user,
or, with autonomy, comes back here for a new pick.

Come back to this skill instead of patching when the shape proves wrong. Signs:

- the same workaround appears in unrelated code;
- edge cases each need their own branch;
- types need casts or `any` to compile;
- callers must know a module's internal rules;
- two or more deviations from the sketch have the same shape.

A few edge cases don't condemn a shape. Complexity in the data isn't complexity in the
design.

Adapted from Lauren Tan's `architect` in pstack (MIT); see [NOTICE](NOTICE).
