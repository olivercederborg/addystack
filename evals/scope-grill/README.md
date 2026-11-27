# scope-grill evals

Build the repo, then add the planning issue:

```sh
../verify-work/setup.sh /tmp/grill-eval
cd /tmp/grill-eval && git checkout -q main
printf '\n# EX-9: Monthly export email\nCompany admins want last month'"'"'s transactions CSV emailed to them on the 1st of each month.\n' >> ISSUE.md
mkdir -p src/jobs && echo 'export const jobs = [] as const // cron-style job registry, currently empty' > src/jobs/registry.ts
git add -A && git -c user.email=e@x -c user.name=e commit -qm "Add EX-9 and empty job registry"
```

Start a fresh session in `/tmp/grill-eval` and send these turns in order:

1. "grill me on how we should build EX-9 before we start"
2. "confirm, one company's admins get only their own company's CSV"
3. Choose an actually offered wider alternative from the latest round, by its exact
   question and option label, and take the other recommendations. If none is offered,
   ask which unresolved decision has a wider alternative; pick one only if offered.
   Record the exact input and option. Never invent a label. If no wider pick is
   available, mark widening-dependent assertions NOT RUN.

Grade all arms on this same rubric. Grade each assertion PASS or FAIL with a quote;
mark an unexercised condition NOT RUN rather than passing it:

- **Turn 1**
  - Proposed additions appear above **The plan so far**, in a `diff` block labeled
    "my suggestion, not agreed". Round 1's **Changed this round** is all green,
    including the agent's baseline reading. The plan has Building, Not building,
    Assuming (say if wrong), and Size, in that order; Building names who agreed each
    clause and preserves the request's boundaries. Work-adding assumptions are proposed,
    not hidden. Size names PRs, files, migrations and whether lines were estimated.
  - Under 60 words of prose appear above the one fold, counting plan items and the
    fold's summary, but not code and diff blocks or the format's fixed labels. Only
    Proposed this round and Changed this round are `diff` blocks; the plan is plain
    lists. `a` takes the picks and `b` changes them. The fold holds costs, sources and For
    architect.
  - The Bar is taken from the request or asked first. It is not assumed to be an MVP.
  - It flags that EX-9 depends on the unmerged EX-7 branch and that branch's bugs.
  - In T3 Code, round 1 gets one page. Its job questions get no crops, and the defaults
    that shape the email and its CSV, such as an empty month still sending, get crops
    as pending assumptions, or as proposed additions when they add work.
- **Turn 2**
  - One to three grounded frontier questions, all about what gets built. Check the
    issue, code and earlier answers: no open decision essential to the next step is
    omitted, and no question is added solely to fill the round.
  - A question about how the job is wired into `src/jobs/registry.ts` is not asked: it
    is parked on a For architect list.
  - Under 60 words appear above the one fold, counted as in Turn 1.
  - The same plan headings remain visible, with pending assumptions, at most about
    five Building clauses, a Pick and one fold. Proposed additions are not in Building
    until accepted. Changed this round appears only for a change, as a red/green diff.
    A page appears only if questions or defaults change what an admin sees.
  - Every option names what it touches (files, or a small diff of behavior) and has a
    cost line: `No extra scope`, `Drops …`, or `Adds …`, a file count, and `easy to
    undo` or `hard to undo: <why>`, minus any cost the options share.
  - Each losing wider option says when it would become worth it, and each losing
    narrower one says what widening later would cost.
  - The turn ends with a `Next` list whose `a` option takes every recommendation.
- **Turn 3**
  - Under 60 words appear above the one fold, counted as in Turn 1.
  - The Size trail records the change from the prior round on the plan's Size line,
    and names the pick that caused it. No line count is invented.
  - Questions that only exist because of the wider pick are flagged as question creep.
  - A changed earlier recommendation names its reason.
- **Summary** (optional 4th turn, "a"):
  - The same plan headings remain visible. **My additions** lists defaults the user
    did not pick, and `b` drops them before saving.
  - It has a check per must-have, a For architect list, and a `## Not in scope` list
    whose items give a reason and a revisit signal.
  - It shows where it would save the plan, with the exact text, and writes nothing
    before approval.
  - Its `Next` offers to save and continue to `architect` when the save target is
    authorized; otherwise it offers to continue without saving and asks separately
    before creating issues.

## Internal-only variant (T3 Code only)

In a fresh T3 Code session in `/tmp/grill-eval`, send "grill me on replacing the
hand-written date filter in src/export.ts on feature/csv-export with a shared date-range
helper, without changing anything the export returns". Grade its round: no inline page
appears, since nothing a user sees changes.

## Visual variant (T3 Code only)

Add a transactions page whose tokens and copy a generic wireframe wouldn't guess:

```sh
cd /tmp/grill-eval && mkdir -p src/ui
echo ':root { --bg: #faf7f2; --ink: #2b2118; --accent: #0f766e; --radius: 18px; --font: "Fraunces", serif; }' > src/ui/tokens.css
cat > src/ui/TransactionsPage.tsx <<'EOF'
export const TransactionsPage = ({ rows }: { rows: { id: string; description: string; amount: string }[] }) => (
  <main className="page">
    <header className="page-header">
      <h1>Ledger</h1>
      <button className="pill">Filter by month</button>
    </header>
    <ul className="rows">{rows.map((r) => <li key={r.id}>{r.description}<span>{r.amount}</span></li>)}</ul>
  </main>
)
EOF
git add -A && git -c user.email=e@x -c user.name=e commit -qm "Add transactions page"
```

In a fresh T3 Code session there, so `html_render` exists, send:

1. "grill me on EX-10: admins download the CSV from a new Export button on the
   transactions page, and see a preview before the download starts"
2. "confirm"

Grade the round that asks what the preview looks like, such as a modal or an inline
panel:

- It comes with one inline page, even though the option names already show the
  difference. The options sit side by side, labeled like the options, and stack at
  phone width.
- Each screen change the round assumes instead of asking, such as the preview's
  buttons or its empty state, gets a crop under an `Assuming (say if wrong) · pending`
  section, unless an option's crop already shows it.
- The crops use the repo's UI: the `Ledger` heading, the `Filter by month` pill, and the
  `#0f766e` accent, and a line on the page names `src/ui/tokens.css` and
  `src/ui/TransactionsPage.tsx`. New elements, such as the Export button, are outlined.
- A round that changes no screen gets no page, and no turn has more than one page.
- The reply doesn't restate what the page shows.
