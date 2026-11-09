# File archive cleanup

An owner picks how long unmatched files stay in the file archive before Franklin moves
them to trash, sees it saved, and finds the same choice after a reload.

## Sub-features

- `cleanup-save` saves a new window for moving unmatched files to trash.
- `cleanup-persist` keeps the saved window after a reload.

## How to get to it (user POV)

- Choose `Settings` in the sidebar, on the `General` tab, then the "File archive
  cleanup" card.
- Open `/settings` directly.

## Driving it with verify-franklin

Preconditions:

- Signed in as `dev+local@hifranklin.com`, with "Franklin Test" active.
- Run: `scripts/run.sh features/archive-cleanup.ts`.

- **Save.** In the `Move unmatched files to trash` combobox, choose `After 90 days` (or
  `After 60 days` when it already is 90), then that card's `Save changes`. The toast
  "File archive cleanup saved" appears. Proof `01-cleanup-saved`.
- **Persist.** Reload `/settings`. The combobox shows the saved window. Proof
  `02-cleanup-after-reload`.
- **Restore.** Choose the original window, save, reload, and assert it. Proof
  `03-cleanup-restored`.

## Gotchas

- The options are `Never`, `After 60 days`, `After 90 days`, and `After 180 days`; the
  seed starts at `Never`.
- The combobox renders disabled and empty until the page loads its value, so the recipe
  waits for it to be enabled before reading the original.
- The page has several `Save changes` buttons; the recipe takes the one in the
  combobox's own form.
- A window applies to files already in the archive: older unmatched files move to trash
  within 24 hours. The recipe restores within seconds, so a cleanup job would have to
  run in that gap.
