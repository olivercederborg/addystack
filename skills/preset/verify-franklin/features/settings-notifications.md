# Notification settings

An owner sets the balance below which Franklin sends a low-balance notification, sees
it saved, and can't save a negative threshold.

## Sub-features

- `threshold-save` saves a new low-balance threshold.
- `threshold-persist` keeps the saved value after a reload.
- `threshold-negative` rejects a negative value with a validation message.

## How to get to it (user POV)

- Choose `Settings` in the sidebar, on the `General` tab.
- Open `/settings` directly.

## Driving it with verify-franklin

Preconditions:

- Signed in as `dev+local@hifranklin.com`, with "Franklin Test" active.
- Run: `scripts/run.sh features/settings-notifications.ts`.

- **Save.** Fill `Low balance notification threshold` with `1000` (or `1500` when it
  already is `1000`), choose the first `Save changes`. The toast "Notification settings
  saved" appears. Proof `01-threshold-saved`.
- **Persist.** Reload `/settings`. The field shows the saved value. Proof
  `02-threshold-after-reload`.
- **Reject negative.** Fill `-100`, choose `Save changes`. The text "Notification
  threshold must be greater than or equal to 0" appears. Proof `03-negative-rejected`.
- **Restore.** Reload, fill the original value, save, reload, and assert the original.

## Gotchas

- The page has several `Save changes` buttons; the first belongs to Notifications.
- The toast fades within seconds, so the screenshot can show it half-transparent.
  The recipe asserts it before the proof.
- On `develop` up to `934292c735`, the Settings page logs a hydration mismatch on every
  load, so expect `page-errors.txt`. Cause: react-collapsible 1.1.12 bundles react-slot
  1.2.3, whose `Slot` renders nothing for the lazy children a server component passes, so
  the "Support information" card's `asChild` parts were missing from the server HTML.
  Fixed on branch `10-02-fix_web_upgrade_react-collapsible_so_aschild_renders_on_the_server`
  (react-collapsible 1.1.20). It doesn't block these steps.
