# Replay: #5634's card change reaches every integration (T3 8575bceb, devbox, 2026-11-09 23:27)

Repo: franklin-next. You coordinate the "dinero-export-v3" project: a stack of PRs that
adds Dinero exports (#5527 adapter, #5528 gate, #5634 readiness, #5617 booking). The
project is Dinero only. A worker holds the checkout; nothing is pushed without Oliver's go.

## What the review rounds established

- The receipts page has two cards, Ready to export and Not ready. The Ready card is built
  from field filters (has an account, has a receipt). A Dinero currency exchange can pass
  those filters and still be blocked by start export, so Ready has to ask the same
  readiness check that start export uses.
- #5634 added that check in the shared filter for every integration, not only Dinero:

  ```ts
  // global-filters.ts, #5634 as written
  (!readyToExport || !readiness.isTransactionBlocked(transaction))
  ```

  A Dinero-only version would gate the same line: `(!readyToExport || !isDinero ||
  !readiness.isTransactionBlocked(transaction))`.
- Effect on other integrations: on connections that require a supplier and whose supplier
  list is switched off (a connection that isn't fully set up), a receipt with no supplier
  showed as Ready on develop and then start export blocked it. The loop-5 reviewer ran
  71,280 combinations of connection, catalog state, and receipt: 2,112 misfiled rows before
  #5634, all on those connections (Exact NL, Exact BE, Business Central through Chift,
  Yuki, Nmbrs, Odoo), and 0 with #5634. e-conomic, Moneybird, Business Central direct, and
  Uniconta don't change.
- Once Ready drops those receipts, Not ready must also ask for a supplier
  (`blocksWithoutSupplier`), or they show on neither card. The wider part is about 86 lines.
- #5634's description says it changes the "Dinero receipts page".
- How many production connections are half-configured isn't stored; it only shows as a
  logged warning.
- #5634 sits mid-stack, and reviewers haven't been requested yet.

## The thread

The review rounds are done apart from this call. Report the state and your pick on
#5634's card change to Oliver.
