# Command palette

The ⌘K/Ctrl+K palette in the authenticated app searches pages and, for companies with the `COMMAND_PALETTE` flag, the member's cards, transactions, and receipts over `/api/rpc`, then opens the selected result.

## Sub-features

- `open`: the shortcut opens and closes the dialog.
- `cards`: card search by display name or last digits.
- `transactions`: transaction search by description.
- `receipts`: receipt search by transaction description.
- `navigate`: selecting a result closes the palette and opens its page.

## How to get to it (user POV)

- ⌘K on macOS or Ctrl+K elsewhere, on any authenticated page.

## Driving it with verify-franklin

Preconditions: the baseline in the README. The seeded "Franklin Test" company gets `COMMAND_PALETTE` as an internal-testing flag, owns "Test Card 2", and has a Slack transaction with a receipt.

- **Open**: press `ControlOrMeta+k` on `/settings` until the search input shows (step `palette-open`).
- **Cards**: type "Test Card"; the Cards group lists "Test Card 2" (step `cards-found`).
- **Transactions and receipts**: type "Slack"; the Transactions and Receipts groups each list the Slack charge, with no "Search failed" banner (step `transactions-and-receipts-found`).
- **Navigate**: click the Slack transaction; the palette closes on a `/transactions` URL (step `transaction-opened`).

## Gotchas

- `next dev` can attach the shortcut listener after the page loads, so the recipe retries the key press.
- Opening the palette logs Radix's "DialogContent requires a DialogTitle" console error, which the dev overlay counts as an issue; it isn't a page error.
- Entity groups need two or more characters, after a short debounce.
